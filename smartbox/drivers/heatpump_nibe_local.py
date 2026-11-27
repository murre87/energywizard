"""NIBE local REST: pinned HTTPS, device discovery and metadata-checked settings.

Enable menu 7.5.15. Read presets: S1155/S1255 and S735/S735C (same register map).
Local variable IDs, Modbus addresses and cloud IDs are distinct.
Writes require explicit configuration; boost lifetime belongs to its caller.
No AUX blocks or cloud replay.
See docs/nibe-local-rest.md for the evidence and hardware verification limits.
"""
import base64
from datetime import datetime, timezone
import hashlib
import hmac
import http.client
import json
import logging
import math
import os
import re
import socket
import ssl
import threading
import time

from drivers.heatpump import HeatPumpDriver
from drivers.host import temperature
log = logging.getLogger(__name__)
_HOST = os.environ.get("NIBE_LOCAL_HOST", "")
_PORT = os.environ.get("NIBE_LOCAL_PORT", "8443")
_USERNAME = os.environ.get("NIBE_LOCAL_USERNAME", "")
_PASSWORD = os.environ.get("NIBE_LOCAL_PASSWORD", "")
_TLS_PIN_SHA256 = os.environ.get("NIBE_LOCAL_TLS_PIN_SHA256", "")
_FIELDS = ("indoor_temp", "outdoor_temp", "forward_temp", "return_temp", "water_temp",
           "degree_minutes", "compressor_running", "compressor_power_kw", "operating_mode",
           "compressor_frequency_hz", "compressor_power_w", "heat_produced_kwh_1h", "electric_used_kwh_1h",
           "hot_water_power_w")
# Mätvärden som visas på Värmepump-fliken (aldrig skrivbara). Registren är lästa ur en riktig S1255 (2026-11-06):
# frekvens/el ur kompressorn, och pumpens egen energilogg för senaste timmen (producerad värme / använd el -> COP).
_METRIC_REGISTERS = {"compressor_frequency_hz": {"register": 1046, "unit": "Hz"},
                     "compressor_power_w": {"register": 1048, "unit": "W"},
                     "heat_produced_kwh_1h": {"register": 2283, "unit": "kWh"},
                     "electric_used_kwh_1h": {"register": 2291, "unit": "kWh"}}
# NIBE M12676SV (2026-01-13), S1155/S1255 table; match reported register metadata.
_TEMPERATURE_REGISTERS = {"outdoor_temp": 1, "forward_temp": 5, "return_temp": 7,
                          "water_temp": 8, "indoor_temp": 26}
# Modeller som får läsregistren ovan automatiskt. S735/S735C (frånluft): NIBE:s egen registerexport för S735
# (samma som HA:s nibe_heatpump använder, yozik04/nibe data/s735.csv) har exakt samma typ/adress/enhet/skala för
# 1, 5, 7, 8, 26, 1100, 1046, 1048, 2283 och 2291 som S1155/S1255. Varje värde kontrolleras ändå mot pumpens metadata.
_PRESET_MODELS = re.compile(r"\bS(?:1155|1255|735C?)(?:\b|-)", re.I)
# Värmekurvans förskjutning (S735/S1255: holding 30 "Heating offset climate system 1", s8, -10..10, utan enhet).
_OFFSET_DEFAULTS = {"offset_base_c": 20.5, "offset_steps_per_c": 2.0, "offset_normal": 0.0,
                    "offset_min": -5.0, "offset_max": 5.0}


class LocalRestError(RuntimeError):
    pass


def _request(host, port, pin, method, path, timeout, payload=None):
    """Pin the connected certificate before transmitting credentials; no redirects/retries."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE  # Peer identity is checked below, on this socket.
    conn = http.client.HTTPSConnection(host, port=port, context=context, timeout=timeout)
    peer = None

    def expire():
        if peer is not None:
            try:
                peer.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    timer = threading.Timer(timeout, expire)
    timer.daemon = True
    try:
        conn.connect()
        peer = conn.sock
        if not hmac.compare_digest(hashlib.sha256(peer.getpeercert(binary_form=True)).hexdigest(), pin):
            raise LocalRestError("certificate pin mismatch")
        deadline = time.monotonic() + timeout
        timer.start()
        auth = base64.b64encode(f"{_USERNAME}:{_PASSWORD}".encode()).decode()
        body = None if payload is None else json.dumps(payload, allow_nan=False)
        conn.request(method, path, body=body, headers={"Authorization": f"Basic {auth}",
                     "Accept": "application/json", "Content-Type": "application/json"})
        response = conn.getresponse()
        if response.status != 200:
            # Bara statuskoden, aldrig kroppen (t.ex. 403 när "Tillåt ändringar" i 7.5.15 är avslaget, #152)
            raise LocalRestError(f"request rejected: HTTP {response.status}")
        chunks, size = [], 0
        while True:
            # Pumpen svarar med Connection: close - när svaret är färdigläst har http.client redan stängt socketen,
            # och settimeout() på den gav "Bad file descriptor" (#145, verifierat av Lars mot en riktig S1255)
            if getattr(response, "isclosed", lambda: False)():
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise LocalRestError("request deadline exceeded")
            peer.settimeout(remaining)
            chunk = response.read1(min(65536, 2_000_001 - size))
            if not chunk:
                break
            size += len(chunk)
            if size > 2_000_000:
                raise LocalRestError("response too large")
            chunks.append(chunk)
        return json.loads(b"".join(chunks))
    finally:
        timer.cancel()
        conn.close()


def _number(point):
    meta, data = point.get("metadata", {}), point.get("value", {})
    if not isinstance(meta, dict) or not isinstance(data, dict):
        raise LocalRestError("invalid point data")
    raw, divisor = data.get("integerValue"), meta.get("divisor")
    width = re.fullmatch(r"([su])(8|16|32)", str(meta.get("variableSize", "")))
    if (data.get("isOk") is not True or meta.get("variableType") != "integer" or width is None
            or isinstance(raw, bool) or not isinstance(raw, int)
            or isinstance(divisor, bool) or not isinstance(divisor, (int, float))
            or not math.isfinite(divisor) or divisor <= 0):
        raise LocalRestError("invalid value or scale")
    bits = int(width[2])
    low = -(2 ** (bits - 1)) if width[1] == "s" else 0
    high = 2 ** (bits - (width[1] == "s")) - 1
    sentinel = {"s16": -32768, "s32": -2147483648, "u16": 65535, "u32": 4294967295}
    if not low <= raw <= high or raw == sentinel.get(width[0]):
        raise LocalRestError("unavailable value")
    value = raw / divisor
    if not math.isfinite(value):
        raise LocalRestError("invalid scaled value")
    return value


class NibeLocalHeatPumpDriver(HeatPumpDriver):
    def _boost_binding(self):
        binding = self._bindings.get('hot_water_boost')
        if not isinstance(binding, dict):
            return None
        if (type(binding.get('register')) is not int or not 0 <= binding['register'] <= 65535
                or binding.get('register_type') != 'MODBUS_HOLDING_REGISTER'
                or 'unit' not in binding or binding['unit'] is not None and not isinstance(binding['unit'], str)
                or isinstance(binding.get('variable_id'), bool)
                or not re.fullmatch(r'[0-9]+', str(binding.get('variable_id', '')))):
            return None
        values = binding.get('allowed_values')
        start, release = binding.get('start_value'), binding.get('release_value')
        if (not isinstance(values, list) or not 2 <= len(values) <= 64
                or any(type(v) is not int for v in values) or len(set(values)) != len(values)
                or type(start) is not int or type(release) is not int or start == release
                or start not in values or release not in values):
            return None
        return binding

    def capabilities(self):
        caps = set(super().capabilities())
        if self._control and self._expected_product and self._boost_binding():
            caps.add('hot_water_boost')
        return frozenset(caps)

    def read_hot_water_boost(self):
        binding = self._boost_binding()
        if binding is None:
            return None
        try:
            _, point = self._resolve(self._read_points(), binding)
            if point['metadata']['divisor'] != 1:
                return None
            value = _number(point)
            if value == binding['start_value']:
                return True
            if value == binding['release_value']:
                return False
        except (LocalRestError, KeyError, TypeError, ValueError, OverflowError):
            pass
        return None

    def set_hot_water_boost(self, active):
        binding = self._boost_binding()
        if type(active) is not bool or binding is None:
            return False
        return self._write('hot_water_boost', binding['start_value'] if active else binding['release_value'])

    def __init__(self, connection=None, points=None, control_enabled=False, mode_values=None, offset=None):
        cfg = connection or {}
        self._offset_cfg = dict(_OFFSET_DEFAULTS)
        for k, v in (offset or {}).items():
            if k in _OFFSET_DEFAULTS and not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(v):
                self._offset_cfg[k] = float(v)
        self._host = cfg.get("host", _HOST)
        self._port = int(cfg.get("port", _PORT))
        self._timeout = float(cfg.get("timeout_s", 5))
        self._index = cfg.get("device_index", 0)
        self._expected_product = cfg.get("expected_product")
        self._expected_serial = cfg.get("expected_serial")
        if (not 1 <= self._port <= 65535 or not math.isfinite(self._timeout) or not 0 < self._timeout <= 30
                or isinstance(self._index, bool) or not isinstance(self._index, int) or self._index < 0):
            raise ValueError("Invalid NIBE local connection configuration")
        self._bindings = dict(points or {})
        self._control = control_enabled is True
        self._modes = {str(k): v for k, v in (mode_values or {}).items()}
        self._device = None
        self._product = None
        self._pending = None

    def hot_water_ready(self):
        """An optional installation mode guard is read, never forced."""
        binding = self._bindings.get('hot_water_mode')
        if binding is None:
            return True
        if not isinstance(binding, dict) or type(binding.get('required_value')) is not int:
            return False
        try:
            _, point = self._resolve(self._read_points(), binding)
            return point['metadata']['divisor'] == 1 and _number(point) == binding['required_value']
        except (LocalRestError, KeyError, TypeError, ValueError, OverflowError):
            return False

    def _call(self, method, path, payload=None):
        pin = _TLS_PIN_SHA256.replace(":", "").replace(" ", "").strip().lower()
        if not (self._host and _USERNAME and _PASSWORD and re.fullmatch(r"[0-9a-f]{64}", pin)):
            if not getattr(self, "_warned_missing", False):      # en gång - aldrig själva värdena (#138: felet tegs ihjäl)
                self._warned_missing = True
                missing = [n for n, ok in (("host (heat_pump.connection.host)", self._host), ("användarnamn", _USERNAME),
                                           ("lösenord", _PASSWORD), ("certifikatets SHA-256-pin", re.fullmatch(r"[0-9a-f]{64}", pin)))
                           if not ok]
                print(f"⚠️ NIBE lokalt REST: saknar {', '.join(missing)}. Som Home Assistant-tillägg: fyll i nibe_local_username, "
                      f"nibe_local_password och nibe_local_tls_pin_sha256 under tilläggets Konfiguration. Annars miljövariablerna "
                      f"NIBE_LOCAL_USERNAME/_PASSWORD/_TLS_PIN_SHA256.", flush=True)
            raise LocalRestError("missing connection, credentials or valid SHA-256 pin")
        try:
            return _request(self._host, self._port, pin, method, path, self._timeout, payload)
        except Exception as e:
            # Aldrig uppgifter, svarstext eller auth-huvuden i loggen - men felets typ, så att orsaken syns (#145)
            kind = type(e).__name__ if not isinstance(e, LocalRestError) else str(e)
            if getattr(self, "_last_err", None) != kind:
                self._last_err = kind
                print(f"⚠️ NIBE lokalt REST: {method} {path.split('?')[0]} misslyckades ({kind})", flush=True)
            raise LocalRestError(f"local request could not be confirmed ({kind})") from None

    def _read_points(self):
        if self._device is None:
            discovery = self._call("GET", "/api/v1/devices")
            devices = discovery.get("devices") if isinstance(discovery, dict) else None
            matches = [d for d in devices or [] if isinstance(d, dict) and d.get("deviceIndex") == self._index]
            if len(matches) != 1:
                raise LocalRestError("device discovery mismatch")
            product = matches[0].get("product", {})
            if not isinstance(product, dict):
                raise LocalRestError("invalid device identity")
            # En riktig S1255 svarar med tomt product.name (#145): jämför bara det pumpen faktiskt anger, och välj då
            # register efter den förväntade modellen i installationen
            name = str(product.get("name") or "")
            if ((self._expected_product and name and name != self._expected_product)
                    or (self._expected_serial and product.get("serialNumber") and product.get("serialNumber") != self._expected_serial)):
                raise LocalRestError("device identity mismatch")
            self._product, self._device = name or str(self._expected_product or ""), str(self._index)
        points = self._call("GET", f"/api/v1/devices/{self._device}/points")
        if not isinstance(points, dict):
            raise LocalRestError("invalid point response")
        return points

    @staticmethod
    def _resolve(points, binding, writable=False):
        if not isinstance(binding, dict) or type(binding.get("register")) is not int:
            raise LocalRestError("explicit register binding required")
        register_type = binding.get("register_type", "MODBUS_INPUT_REGISTER")
        matches = []
        for key, point in points.items():
            if not isinstance(point, dict):
                continue
            meta, data = point.get("metadata", {}), point.get("value", {})
            if not isinstance(meta, dict) or not isinstance(data, dict):
                continue
            if (meta.get("modbusRegisterID") == binding["register"]
                    and meta.get("modbusRegisterType") == register_type
                    and ("variable_id" not in binding or str(binding["variable_id"]) == key)):
                if str(meta.get("variableId")) != key or str(data.get("variableId")) != key:
                    raise LocalRestError("point identity mismatch")
                if "unit" in binding and meta.get("unit") != binding["unit"]:
                    raise LocalRestError("point unit mismatch")
                if writable and meta.get("isWritable") is not True:
                    raise LocalRestError("point is not writable")
                _number(point)
                matches.append((key, point))
        if len(matches) != 1:
            raise LocalRestError("point missing or ambiguous")
        return matches[0]

    def read_sensors(self):
        try:
            points = self._read_points()
        except LocalRestError:
            return {}
        result = {field: None for field in _FIELDS}
        bindings = {}
        if _PRESET_MODELS.search(self._product):
            bindings.update({k: {"register": reg, "unit": "°C"} for k, reg in _TEMPERATURE_REGISTERS.items()})
            bindings["compressor_running"] = {"register": 1100}
            bindings.update(_METRIC_REGISTERS)
        bindings.update(self._bindings)
        for field in _FIELDS:
            if field not in bindings:
                continue
            try:
                _, point = self._resolve(points, bindings[field])
                value = _number(point)
                if field == "compressor_running":
                    value = bool(value) if value in (0, 1) else None
                elif field == "operating_mode":
                    keys = [k for k, v in self._modes.items() if v == value]
                    value = (int(keys[0]) if keys[0].isdigit() else keys[0]) if len(keys) == 1 else None
                elif field.endswith("_temp") and not -80 <= value <= 150:
                    value = None
                elif field in _METRIC_REGISTERS and value < 0:
                    value = None
                elif field == "hot_water_power_w":
                    unit = bindings[field].get("unit")
                    if bindings[field].get("boundary") != "hot_water_electrical" or unit not in {"W", "kW"} or value < 0:
                        value = None
                    elif unit == "kW":
                        value *= 1000
                    if value is not None and not math.isfinite(value):
                        value = None
                result[field] = value
            except LocalRestError:
                pass
        result.update(_raw_point_count=len(points), _received_at=datetime.now(timezone.utc).isoformat(),
                      _timestamp_basis="local_receipt")
        result["water_temp_observation"] = temperature(result["water_temp"], result["_received_at"], "local_receipt")
        from drivers.host import hot_water_reservations
        try:
            result.update(hot_water_reservations.boost_fields(points, self._bindings, self._resolve,
                                                             _number, result['_received_at']))
        except LocalRestError:
            result.update(hot_water_boost_active=None, hot_water_boost_sample_at=None)
        return result

    def _write(self, field, value):
        if not self._control or not self._expected_product or field not in self._bindings:
            return False
        binding = self._bindings[field]
        if not isinstance(binding, dict):
            return False
        if field == "heating_offset":
            # Förskjutningen är ett enhetslöst heltal i steg, aldrig grader
            if binding.get("unit", "") != "" or isinstance(value, bool) or not isinstance(value, int):
                return False
        elif field not in {'operating_mode', 'hot_water_boost'} and binding.get("unit") != "°C":
            return False
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            return False
        from drivers.host import shadow
        if shadow.active() and not (field == 'hot_water_boost' and getattr(self, '_boost_live_in_shadow', False)):
            shadow.record("NIBE local REST", f"{field}={value}")
            return True
        try:
            points = self._read_points()
            if self._pending is not None:
                pending_binding, pending_raw = self._pending
                _, pending = self._resolve(points, pending_binding, writable=True)
                if pending["value"]["integerValue"] != pending_raw:
                    return False
                self._pending = None
            key, point = self._resolve(points, binding, writable=True)
            if field == 'hot_water_boost' and value == binding.get('start_value') and 'hot_water_mode' in self._bindings:
                mode_binding = self._bindings['hot_water_mode']
                if not isinstance(mode_binding, dict) or type(mode_binding.get('required_value')) is not int:
                    return False
                _, mode = self._resolve(points, mode_binding)
                if mode['metadata']['divisor'] != 1 or _number(mode) != mode_binding['required_value']:
                    return False
            meta = point["metadata"]
            if meta.get("modbusRegisterType") != "MODBUS_HOLDING_REGISTER":
                return False
            other_field = {"water_start": "water_stop", "water_stop": "water_start"}.get(field)
            if other_field in self._bindings:
                _, other = self._resolve(points, self._bindings[other_field], writable=True)
                other_value = _number(other)
                if (field == "water_start" and value >= other_value) or (field == "water_stop" and value <= other_value):
                    return False
            raw = float(value) * meta["divisor"]
            width = re.fullmatch(r"([su])(8|16|32)", meta["variableSize"])
            bits = int(width[2])
            low = -(2 ** (bits - 1)) if width[1] == "s" else 0
            high = 2 ** (bits - (width[1] == "s")) - 1
            if not math.isfinite(raw) or not raw.is_integer() or not low <= raw <= high:
                return False
            minimum, maximum = meta.get("minValue"), meta.get("maxValue")
            if field == 'hot_water_boost':
                # Validate release as well as start before issuing either request.
                # Equal firmware bounds mean unknown, not a guessed enum range.
                endpoints = (binding['start_value'], binding['release_value'])
                sentinel = {'s16':-32768,'s32':-2147483648,'u16':65535,'u32':4294967295}.get(width[0])
                if (meta['divisor'] != 1 or any(not low <= v <= high or v == sentinel for v in endpoints)
                        or isinstance(minimum, bool) or isinstance(maximum, bool)):
                    return False
                if isinstance(minimum,(int,float)) and isinstance(maximum,(int,float)) and minimum != maximum:
                    if not all(minimum <= v <= maximum for v in endpoints):
                        return False
            if (isinstance(minimum, (int, float)) and isinstance(maximum, (int, float))
                    and minimum != maximum and not minimum <= raw <= maximum):
                return False
            # Unknown firmware bounds require explicit installation bounds, never an unbounded write.
            limits = binding.get("allowed_values") if field in {'operating_mode','hot_water_boost'} else binding.get("limits")
            if field in {'operating_mode','hot_water_boost'}:
                if not isinstance(limits, list) or value not in limits:
                    return False
            elif not (isinstance(limits, list) and len(limits) == 2 and limits[0] <= value <= limits[1]):
                return False
            if point["value"]["integerValue"] == int(raw):
                return True
            self._pending = (dict(binding), int(raw))
            payload = [{"type": "datavalue", "isOk": True, "variableId": int(key),
                        "integerValue": int(raw), "stringValue": ""}]
            status = self._call("PATCH", f"/api/v1/devices/{self._device}/points", payload)
            # Always read back independently; PATCH success alone is not confirmation.
            _, actual = self._resolve(self._read_points(), binding, writable=True)
            if actual["value"]["integerValue"] != int(raw):
                return False
            self._pending = None
            # Svarsformen skiljer mellan firmwares: {"<id>": "modified"} eller hela den uppdaterade punkten (S1255, #152).
            # Den oberoende återläsningen ovan är det som avgör; ekot får bara inte motsäga den.
            echoed = status.get(key) if isinstance(status, dict) else None
            if isinstance(echoed, dict):
                return (echoed.get("value") or {}).get("integerValue") == int(raw)
            return echoed == "modified"
        except (LocalRestError, KeyError, TypeError, ValueError, OverflowError):
            log.warning("NIBE local setting not confirmed; no automatic replay")
            return False

    def set_room_temp(self, target_c):
        """Med rumsgivare: skriv rumsbörvärdet (room_target, °C). Utan (vanligt på S735): översätt önskad innetemp
        till värmekurvans förskjutning (heating_offset) kring husets normala förskjutning, som HA-drivrutinen (#200)."""
        if "room_target" in self._bindings or "heating_offset" not in self._bindings:
            return self._write("room_target", target_c)
        if isinstance(target_c, bool) or not isinstance(target_c, (int, float)) or not math.isfinite(target_c):
            return False
        c = self._offset_cfg
        steps = c["offset_normal"] + c["offset_steps_per_c"] * (float(target_c) - c["offset_base_c"])
        return self._write("heating_offset", int(round(min(max(steps, c["offset_min"]), c["offset_max"]))))

    def set_water_stop_temp(self, target_c):
        return self._write("water_stop", target_c)

    def set_water_start_temp(self, target_c):
        return self._write("water_start", target_c)

    def set_heating_start_temp(self, target_c):
        return self._write("heating_start", target_c)

    def set_operating_mode(self, mode):
        value = self._modes.get(str(mode))
        return False if value is None else self._write("operating_mode", value)


class NibeHotWaterOnlyDriver(NibeLocalHeatPumpDriver):
    """Separate boost owner. Cannot write room, curve, mode or temperature settings."""
    def __init__(self, connection=None, points=None, *, control_enabled=False, live_in_shadow=False):
        permitted = {'water_temp', 'hot_water_boost', 'hot_water_mode'}
        if set(points or {}) - permitted:
            raise ValueError('Hot-water-only driver accepts only explicit hot-water points')
        super().__init__(connection=connection, points=points, control_enabled=control_enabled)
        self._boost_live_in_shadow = control_enabled is True and live_in_shadow is True

    def _write(self, field, value):
        if field != 'hot_water_boost':
            return False
        return super()._write(field, value)
