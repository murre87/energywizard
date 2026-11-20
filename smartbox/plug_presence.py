"""Närvaro och bortaläge för icke-nödvändiga pluggar (#217).

Loggar bara. Reläet ändras inte, varken i skuggläge eller när prisstyrningen är på.
Prisregeln och eventuell standby är orörda.

presence är binary_sensor eller input_boolean. on betyder att rummet är upptaget.
unavailable, unknown och en saknad avläsning är inte ett tomt rum. En påslagen
plugg som varit tom i unoccupied_minutes (standard 15) loggas en gång. Väntan
börjar om när rummet blir upptaget eller pluggen slås av.

Bortaläge loggar en påslagen plugg en gång. Närvaro räknas inte då.
"""
import math
import re

_PRESENCE = re.compile(r"(?:binary_sensor|input_boolean)\.[a-z0-9_]+\Z")


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _minutes(item):
    value = item.get("unoccupied_minutes", 15)
    if not _finite(value) or not 5 <= float(value) <= 1440:
        return 15
    return float(value)


def select(enrolled, raw_devices):
    """Pluggar som prisregeln redan tagit med. Ogiltig närvaro hoppas över."""
    by_switch = {}
    if isinstance(raw_devices, list):
        for item in raw_devices:
            if isinstance(item, dict) and isinstance(item.get("switch"), str):
                by_switch[item["switch"]] = item
    out = []
    for device in enrolled or []:
        if not isinstance(device, dict):
            continue
        entity = device.get("entity")
        if not isinstance(entity, str) or not entity:
            continue
        item = by_switch.get(entity, {})
        presence = item.get("presence") if isinstance(item, dict) else None
        if not isinstance(presence, str) or not _PRESENCE.fullmatch(presence):
            presence = None
        out.append({"entity": entity, "presence": presence, "unoccupied_s": _minutes(item) * 60})
    return out


class Watch:
    def __init__(self, devices):
        self.devices = list(devices or [])
        self._empty_since = {}
        self._noted = {}

    def _clear(self, entity):
        self._empty_since.pop(entity, None)
        self._noted.pop(entity, None)

    def tick(self, now, away, read_switch, read_presence, record):
        if not _finite(now):
            return
        for device in self.devices:
            entity = device["entity"]
            if away is not True and not device["presence"]:
                self._clear(entity)
                continue
            try:
                state = read_switch(entity)
            except Exception:
                state = None
            if state != "on":
                self._clear(entity)
                continue
            noted = self._noted.get(entity, {})
            if away is True:
                self._empty_since.pop(entity, None)
                if not noted.get("away"):
                    if _note(record, entity, "bortaläge, slår inte av"):
                        noted = {**noted, "away": True, "empty": False}
                self._noted[entity] = {**noted, "empty": False}
                continue
            noted = {**noted, "away": False}
            presence = device["presence"]
            if not presence:
                self._empty_since.pop(entity, None)
                self._noted[entity] = noted
                continue
            try:
                occupied = read_presence(presence)
            except Exception:
                occupied = None
            if occupied is not False:
                self._empty_since.pop(entity, None)
                self._noted[entity] = {**noted, "empty": False}
                continue
            since = self._empty_since.get(entity, now)
            if now < since:
                since = now
            self._empty_since[entity] = since
            if not noted.get("empty") and now - since >= device["unoccupied_s"]:
                if _note(record, entity, "rummet har varit tomt, slår inte av"):
                    noted = {**noted, "empty": True}
            self._noted[entity] = noted


def _note(record, entity, detail):
    try:
        record(entity, detail)
    except Exception:
        return False
    return True


def _snapshot(response, entity):
    try:
        body = response.json()
    except Exception:
        return None
    if not isinstance(body, dict) or body.get("entity_id") != entity:
        return None
    return body


def run(watch, now, away):
    """Fräsch läsning från Home Assistant. Inget anrop till switch.turn_on eller turn_off."""
    if not watch.devices:
        return
    import homeassistant as ha

    def read(entity):
        response = ha.requests.get(
            f"{ha._BASE}/states/{entity}", headers=ha._HEADERS, timeout=5, verify=ha._VERIFY)
        response.raise_for_status()
        return _snapshot(response, entity)

    def read_switch(entity):
        body = read(entity)
        state = body.get("state") if body else None
        return state if state in ("on", "off") else None

    def read_presence(entity):
        body = read(entity)
        state = body.get("state") if body else None
        if state == "on":
            return True
        if state == "off":
            return False
        return None

    def record(entity, detail):
        print(f"Smart plug {entity}: {detail}")

    watch.tick(now, away, read_switch, read_presence, record)
