"""Room, away and vacation for enrolled plugs. This module never calls a switch."""
import math
import re

_PRESENCE = re.compile(r'(?:binary_sensor|input_boolean|device_tracker|person)\.[a-z0-9_]+')
_VACATION = re.compile(r'(?:binary_sensor|input_boolean)\.[a-z0-9_]+')
_SWITCH = re.compile(r'switch\.[a-z0-9_]+')


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def present(snapshot):
    """True when someone is there, False when empty, None when the reading is unknown."""
    if not isinstance(snapshot, dict):
        return None
    entity = snapshot.get('entity_id')
    state = snapshot.get('state')
    if not isinstance(entity, str) or '.' not in entity or not isinstance(state, str):
        return None
    domain = entity.split('.', 1)[0]
    if domain in ('device_tracker', 'person'):
        if state == 'home':
            return True
        if state == 'not_home':
            return False
        return None
    if domain in ('binary_sensor', 'input_boolean'):
        if state == 'on':
            return True
        if state == 'off':
            return False
    return None


def vacation_on(snapshot):
    """An explicit on from a boolean sensor. Unknown and off are not vacation."""
    if not isinstance(snapshot, dict):
        return False
    entity = snapshot.get('entity_id')
    if not isinstance(entity, str) or not _VACATION.fullmatch(entity):
        return False
    return snapshot.get('state') == 'on'


def _delay(raw):
    if not finite(raw) or not 5 <= raw <= 1440:
        return None
    return raw


class Watch:
    def __init__(self, config):
        self.rooms = []
        self.home = None
        self.vacation = None
        self._cut = {}
        self._ready = set()
        self._since = {}
        self._noted = set()
        if not isinstance(config, dict) or config.get('enabled') is not True:
            return
        devices = config.get('devices', [])
        if not isinstance(devices, list) or len(devices) > 32:
            raise ValueError('At most 32 smart plugs supported')
        if 'home' in config or 'away_minutes' in config:
            sensor = config.get('home')
            minutes = _delay(config.get('away_minutes', 15))
            if not isinstance(sensor, str) or not _PRESENCE.fullmatch(sensor) or minutes is None:
                raise ValueError('Invalid smart plug occupancy')
            self.home = dict(entity=sensor, delay=minutes * 60, label=f'{minutes:g}')
        if 'vacation' in config:
            sensor = config.get('vacation')
            if not isinstance(sensor, str) or not _VACATION.fullmatch(sensor):
                raise ValueError('Invalid smart plug occupancy')
            self.vacation = sensor
        seen = set()
        for item in devices:
            if not isinstance(item, dict):
                raise ValueError('Invalid smart plug entry')
            if (item.get('enabled') is not True or item.get('nonessential') is not True
                    or item.get('always_on', False) is not False):
                continue
            switch = item.get('switch', '')
            if not isinstance(switch, str) or not _SWITCH.fullmatch(switch) or switch in seen:
                raise ValueError('Invalid smart plug occupancy')
            seen.add(switch)
            has_room = 'occupied' in item or 'unoccupied_minutes' in item
            off = item.get('presence_off', False)
            away = item.get('away', False)
            holiday = item.get('vacation', False)
            if ((off is not True and off is not False) or (away is not True and away is not False)
                    or (holiday is not True and holiday is not False)):
                raise ValueError('Invalid smart plug occupancy')
            if has_room:
                sensor = item.get('occupied')
                minutes = _delay(item.get('unoccupied_minutes', 15))
                if not isinstance(sensor, str) or not _PRESENCE.fullmatch(sensor) or minutes is None:
                    raise ValueError('Invalid smart plug occupancy')
                self.rooms.append(dict(switch=switch, entity=sensor, delay=minutes * 60, label=f'{minutes:g}'))
            if away and self.home is None:
                raise ValueError('Invalid smart plug occupancy')
            if holiday and self.vacation is None:
                raise ValueError('Invalid smart plug occupancy')
            if off and not has_room and not away and not holiday:
                raise ValueError('Invalid smart plug occupancy')
            if off:
                self._cut[switch] = dict(room=has_room, away=away, vacation=holiday)

    @property
    def active(self):
        return bool(self.rooms or self.home or self.vacation)

    def _episode(self, key, empty, now, delay, record, detail):
        if not empty:
            self._since.pop(key, None)
            self._noted.discard(key)
            self._ready.discard(key)
            return
        since = self._since.get(key)
        if since is None or now < since:
            since = now
            self._noted.discard(key)
            self._ready.discard(key)
        self._since[key] = since
        if now - since < delay:
            return
        self._ready.add(key)
        if key in self._noted:
            return
        try:
            record(key, detail)
        except Exception:
            return
        self._noted.add(key)

    def switches_to_cut(self):
        """Plugs with presence_off whose opted-in signal has finished its wait."""
        home = 'home' in self._ready
        holiday = 'vacation' in self._ready
        return tuple(
            switch for switch, policy in self._cut.items()
            if (policy['room'] and switch in self._ready)
            or (policy['away'] and home) or (policy['vacation'] and holiday))

    def tick(self, now, read, record):
        """read returns one HA state. record may log. Neither path can switch a plug."""
        if not finite(now) or not self.active:
            return
        for room in self.rooms:
            try:
                flag = present(read(room['entity']))
            except Exception:
                flag = None
            self._episode(room['switch'], flag is False, now, room['delay'], record,
                          f"room empty for {room['label']} min")
        if self.home:
            try:
                flag = present(read(self.home['entity']))
            except Exception:
                flag = None
            self._episode('home', flag is False, now, self.home['delay'], record,
                          f"home empty for {self.home['label']} min")
        if self.vacation:
            try:
                on = vacation_on(read(self.vacation))
            except Exception:
                on = False
            self._episode('vacation', on, now, 0, record, 'vacation')


def run(watch, now):
    """GET the configured presence entities. There is no service call."""
    if not watch.active:
        return
    import homeassistant as ha

    def read(entity):
        response = ha.requests.get(f'{ha._BASE}/states/{entity}', headers=ha._HEADERS, timeout=5, verify=ha._VERIFY)
        response.raise_for_status()
        snapshot = response.json()
        return snapshot if isinstance(snapshot, dict) and snapshot.get('entity_id') == entity else None

    def record(key, detail):
        if key in ('home', 'vacation'):
            print(f'Smart plugs: {detail}')
        else:
            print(f'Smart plug {key}: {detail}')

    watch.tick(now, read, record)
