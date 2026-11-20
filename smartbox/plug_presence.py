"""Room, away and vacation notes for smart plugs (#217).

Logs what those signals would do after a dwell. Never calls a switch service,
in shadow mode or otherwise. A missing or unknown reading is not "empty".
"""
import math
import re


SWITCH = re.compile(r"switch\.[a-z0-9_]+")
PRESENCE = re.compile(r"(binary_sensor|person|device_tracker|input_boolean)\.[a-z0-9_]+")
VACATION = re.compile(r"(binary_sensor|input_boolean)\.[a-z0-9_]+")
UNKNOWN = {"", "unavailable", "unknown", "none"}
REASONS = (("room", "room empty"), ("away", "house away"), ("vacation", "vacation"))


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _minutes(value, default, label):
    if value is None:
        value = default
    if not finite(value) or not 5 <= value <= 1440:
        raise ValueError(f"Invalid {label}")
    return float(value) * 60


def _entity(value, pattern, label):
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValueError(f"Invalid {label}")
    return value


def present(entity, state):
    """True when someone is there, False when they are not, None when unknown.

    person and device_tracker use HA's home state. binary_sensor and
    input_boolean use on for occupied. Another zone means not in this home.
    """
    if not isinstance(state, str):
        return None
    text = state.strip().lower()
    if text in UNKNOWN:
        return None
    domain = entity.split(".", 1)[0]
    if domain in ("binary_sensor", "input_boolean"):
        if text == "on":
            return True
        if text == "off":
            return False
        return None
    return text == "home"


def vacation_active(state):
    """True when the vacation switch is on. Anything else except off is unknown."""
    if not isinstance(state, str):
        return None
    text = state.strip().lower()
    if text == "on":
        return True
    if text == "off":
        return False
    return None


class Watcher:
    def __init__(self, config):
        self.devices = []
        self._since = {}
        self._announced = {}
        if not isinstance(config, dict):
            return
        presence = config.get("presence")
        if presence is None:
            return
        if not isinstance(presence, dict):
            raise ValueError("Invalid plug presence")
        away = presence.get("away")
        vacation = presence.get("vacation")
        if away is not None:
            away = _entity(away, PRESENCE, "plug presence away entity")
        if vacation is not None:
            vacation = _entity(vacation, VACATION, "plug presence vacation entity")
        away_s = _minutes(presence.get("away_minutes"), 15, "plug presence away dwell")
        vacation_s = _minutes(presence.get("vacation_minutes"), 15, "plug presence vacation dwell")
        devices = presence.get("devices")
        if not isinstance(devices, list) or not 1 <= len(devices) <= 32:
            raise ValueError("Plug presence needs 1 to 32 devices")
        seen = set()
        for item in devices:
            if not isinstance(item, dict):
                raise ValueError("Invalid plug presence device")
            switch = _entity(item.get("switch"), SWITCH, "plug presence switch")
            if switch in seen:
                raise ValueError("Duplicate plug presence switch")
            seen.add(switch)
            occupancy = item.get("occupancy")
            if occupancy is not None:
                occupancy = _entity(occupancy, PRESENCE, "plug presence occupancy entity")
            room_s = _minutes(item.get("unoccupied_minutes"), 15, "plug presence room dwell")
            use_away = item.get("away", False) is True
            use_vacation = item.get("vacation", False) is True
            if use_away and away is None:
                raise ValueError("Plug presence away policy needs an away entity")
            if use_vacation and vacation is None:
                raise ValueError("Plug presence vacation policy needs a vacation entity")
            if occupancy is None and not use_away and not use_vacation:
                raise ValueError("Plug presence device has no room, away or vacation policy")
            self.devices.append(dict(
                switch=switch, occupancy=occupancy, room_s=room_s,
                away=away if use_away else None, away_s=away_s,
                vacation=vacation if use_vacation else None, vacation_s=vacation_s,
            ))

    def _stable(self, key, wanting, seconds, now):
        """True/False once `wanting` has held for the dwell. None if the reading is unknown."""
        if wanting is None:
            self._since.pop(key, None)
            return None
        started = self._since.get(key)
        if started is None or started[0] is not wanting or now < started[1]:
            self._since[key] = (wanting, now)
            return "dwell"
        if now - started[1] >= seconds:
            return wanting
        return "dwell"

    def tick(self, now, read, record):
        if not finite(now) or not self.devices:
            return
        cache = {}

        def reading(entity):
            if entity not in cache:
                try:
                    cache[entity] = read(entity)
                except Exception:
                    cache[entity] = None
            return cache[entity]

        for device in self.devices:
            switch = device["switch"]
            checks = []
            if device["occupancy"]:
                here = present(device["occupancy"], reading(device["occupancy"]))
                checks.append(("room", None if here is None else not here, device["room_s"]))
            if device["away"]:
                here = present(device["away"], reading(device["away"]))
                checks.append(("away", None if here is None else not here, device["away_s"]))
            if device["vacation"]:
                checks.append(("vacation", vacation_active(reading(device["vacation"])), device["vacation_s"]))
            off = []
            pending = False
            for name, wanting, seconds in checks:
                stable = self._stable((switch, name), wanting, seconds, now)
                if stable is True:
                    off.append(name)
                elif stable is None or stable == "dwell":
                    pending = True
            announced = self._announced.get(switch, frozenset())
            current = frozenset(off)
            if current:
                if current == announced:
                    continue
                detail = "presence would turn off (" + ", ".join(
                    text for key, text in REASONS if key in current) + ")"
            elif pending or not announced:
                continue
            else:
                detail = "presence would turn on"
                current = frozenset()
            try:
                record(switch, detail)
            except Exception:
                continue
            self._announced[switch] = current


def run(watcher, now):
    """Read presence entities and log. There is no write function on this path."""
    if not watcher.devices:
        return
    import homeassistant as ha

    def read(entity):
        response = ha.requests.get(
            f"{ha._BASE}/states/{entity}", headers=ha._HEADERS, timeout=5, verify=ha._VERIFY)
        response.raise_for_status()
        snapshot = response.json()
        if not isinstance(snapshot, dict) or snapshot.get("entity_id") != entity:
            return None
        state = snapshot.get("state")
        return state if isinstance(state, str) else None

    def record(entity, detail):
        print(f"Smart plug {entity}: {detail}")

    watcher.tick(now, read, record)
