"""NIBE local REST: pinned HTTPS, device discovery and metadata-checked settings.

Enable menu 7.5.15. Local variable IDs, Modbus addresses and cloud IDs are distinct.
Writes require explicit configuration; no timed boosts, AUX blocks or cloud replay.
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

log = logging.getLogger(__name__)
_HOST = os.environ.get("NIBE_LOCAL_HOST", "")
_PORT = os.environ.get("NIBE_LOCAL_PORT", "8443")
_USERNAME = os.environ.get("NIBE_LOCAL_USERNAME", "")
_PASSWORD = os.environ.get("NIBE_LOCAL_PASSWORD", "")
_TLS_PIN_SHA256 = os.environ.get("NIBE_LOCAL_TLS_PIN_SHA256", "")
_FIELDS = ("indoor_temp", "outdoor_temp", "forward_temp", "return_temp", "water_temp",
           "degree_minutes", "compressor_running", "compressor_power_kw", "operating_mode")
# NIBE M12676SV (2026-01-13), S1155/S1255 table; match reported register metadata.
_TEMPERATURE_REGISTERS = {"outdoor_temp": 1, "forward_temp": 5, "return_temp": 7,
                          "water_temp": 8, "indoor_temp": 26}


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
            # Statuskoden (aldrig kroppen) i felet - t.ex. 403 "changes are not permitted" när 7.5.15 är skrivskyddad.
            raise LocalRestError(f"request rejected: HTTP {response.status}")
        chunks, size = [], 0
        while True:
            # http.client stänger svaret (och med Connection: close även socketen) så fort
            # Content-Length är uppfylld. Då är kroppen komplett - fråga inte den stängda
            # socketen om timeout, det ger "Bad file descriptor" mot riktig S1255 (#145).
            if response.isclosed():
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
    def __init__(self, connection=None, points=None, control_enabled=False, mode_values=None):
        cfg = connection or {}
        self._host = cfg.get("host", _HOST)
        self._port = int(cfg.get("port", _PORT))
        self._timeout = float(cfg.get("timeout_s", 5))
        self._index = cfg.get("device_index", 0)
        self._expected_product = cfg.get("expected_product")
        self._expected_serial = cfg.get("expected_serial")
        # Vissa S1255 rapporterar tomt product.name (#145) - då väljs registerförinställningen
        # på den konfigurerade modellen i stället, t.ex. model: "S1255".
        self._model = str(cfg.get("model") or "")
        if (not 1 <= self._port <= 65535 or not math.isfinite(self._timeout) or not 0 < self._timeout <= 30
                or isinstance(self._index, bool) or not isinstance(self._index, int) or self._index < 0):
            raise ValueError("Invalid NIBE local connection configuration")
        self._bindings = dict(points or {})
        self._control = control_enabled is True
        self._modes = {str(k): v for k, v in (mode_values or {}).items()}
        self._device = None
        self._product = None
        self._pending = None

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
            result = _request(self._host, self._port, pin, method, path, self._timeout, payload)
        except Exception as exc:
            # Never expose credentials, device response bodies or auth headers in logs:
            # only the exception TYPE, plus our own fixed LocalRestError texts / OS errno (#145).
            if isinstance(exc, LocalRestError):
                reason = str(exc)
            elif isinstance(exc, OSError) and exc.errno is not None:
                reason = f"{type(exc).__name__} errno {exc.errno}"
            else:
                reason = type(exc).__name__
            if reason != getattr(self, "_last_failure", None):   # logga vid ändring, inte varje varv
                self._last_failure = reason
                log.warning("NIBE local REST %s %s failed: %s", method, path.split("?")[0], reason)
            raise LocalRestError("local request could not be confirmed") from None
        if getattr(self, "_last_failure", None) is not None:
            log.info("NIBE local REST responding again")
            self._last_failure = None
        return result

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
            name = str(product.get("name") or "").strip()
            if not name and not getattr(self, "_warned_noname", False):
                self._warned_noname = True
                hint = (f"använder konfigurerad modell '{self._model}' för registervalet" if self._model else
                        "sätt heat_pump.connection.model (t.ex. \"S1255\") eller egna points-bindningar, "
                        "annars läses inga värden")
                if self._expected_product:
                    hint += "; expected_product kan inte matchas mot ett tomt namn - använd expected_serial i stället"
                print(f"⚠️ NIBE lokalt REST: pumpen rapporterar inget produktnamn - {hint}.", flush=True)
            if ((self._expected_product and name != self._expected_product)
                    or (self._expected_serial and product.get("serialNumber") != self._expected_serial)):
                raise LocalRestError("device identity mismatch")
            self._product, self._device = name or self._model, str(self._index)
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
        if re.search(r"\bS(?:1155|1255)(?:\b|-)", self._product, re.I):
            bindings.update({k: {"register": reg, "unit": "°C"} for k, reg in _TEMPERATURE_REGISTERS.items()})
            bindings["compressor_running"] = {"register": 1100}
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
                result[field] = value
            except LocalRestError:
                pass
        result.update(_raw_point_count=len(points), _received_at=datetime.now(timezone.utc).isoformat(),
                      _timestamp_basis="local_receipt")
        return result

    def _write(self, field, value):
        # Skrivning kräver en låst identitet: produktnamn eller (för S1255 med tomt namn, #145) serienummer.
        if not self._control or not (self._expected_product or self._expected_serial) or field not in self._bindings:
            return False
        binding = self._bindings[field]
        if not isinstance(binding, dict):
            return False
        if field != "operating_mode" and binding.get("unit") != "°C":
            return False
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            return False
        import shadow
        if shadow.active():
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
            if (isinstance(minimum, (int, float)) and isinstance(maximum, (int, float))
                    and minimum != maximum and not minimum <= raw <= maximum):
                return False
            # Unknown firmware bounds require explicit installation bounds, never an unbounded write.
            limits = binding.get("allowed_values") if field == "operating_mode" else binding.get("limits")
            if field == "operating_mode":
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
            # Pumpens svar per punkt: "modified" (dokumenterat) eller - som S1255 i #145 - hela den uppdaterade
            # punkten. Godta båda när värdet stämmer; den oberoende återläsningen ovan är ändå avgörande.
            echoed = status.get(key) if isinstance(status, dict) else None
            if isinstance(echoed, dict):
                echoed = (echoed.get("value") or {}).get("integerValue") == int(raw)
            return echoed == "modified" or echoed is True
        except (LocalRestError, KeyError, TypeError, ValueError, OverflowError):
            log.warning("NIBE local setting not confirmed; no automatic replay")
            return False

    def set_room_temp(self, target_c):
        return self._write("room_target", target_c)

    def set_water_stop_temp(self, target_c):
        return self._write("water_stop", target_c)

    def set_water_start_temp(self, target_c):
        return self._write("water_start", target_c)

    def set_heating_start_temp(self, target_c):
        return self._write("heating_start", target_c)

    def set_operating_mode(self, mode):
        value = self._modes.get(str(mode))
        return False if value is None else self._write("operating_mode", value)
