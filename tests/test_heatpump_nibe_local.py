"""Local REST contract and failure cases using synthetic metadata; never a real heater."""
from copy import deepcopy
import hashlib
import json
from unittest.mock import Mock

import pytest

import drivers.heatpump_nibe_local as nibe
from house_config import build_heat_pump_driver

PRODUCT = "NIBE S1255"
INPUT = "MODBUS_INPUT_REGISTER"
HOLDING = "MODBUS_HOLDING_REGISTER"


def point(variable, register, raw, divisor=10, unit="°C", writable=False):
    return {"title": "Synthetic point", "metadata": {"variableId": variable, "variableType": "integer",
            "variableSize": "s16", "divisor": divisor, "unit": unit, "isWritable": writable,
            "modbusRegisterID": register, "modbusRegisterType": HOLDING if writable else INPUT,
            "minValue": 0, "maxValue": 0},
            "value": {"type": "datavalue", "isOk": True, "variableId": variable, "integerValue": raw}}


def binding(register=58, **kw):
    return {"register": register, "register_type": HOLDING, "unit": "°C", "limits": [10, 65], **kw}


class Heater:
    def __init__(self):
        self.points = {"4": point(4, 1, -35), "11": point(11, 8, 504),
                       "12": point(12, 9, 466), "3699": point(3699, 58, 400, writable=True)}
        self.product = PRODUCT
        self.apply = True
        self.writes = []
        self.requests = []

    def request(self, host, port, pin, method, path, timeout, payload=None):
        self.requests.append((method, path))
        if path == "/api/v1/devices":
            return {"devices": [{"deviceIndex": 0, "product": {"name": self.product, "serialNumber": "example"}}]}
        assert path == "/api/v1/devices/0/points"
        if method == "PATCH":
            self.writes.append(payload)
            if self.apply:
                for item in payload:
                    self.points[str(item["variableId"])]["value"]["integerValue"] = item["integerValue"]
            return {str(item["variableId"]): "modified" for item in payload}
        return deepcopy(self.points)


@pytest.fixture
def heater(monkeypatch):
    monkeypatch.setattr(nibe, "_HOST", "heater.invalid")
    monkeypatch.setattr(nibe, "_USERNAME", "test-user")
    monkeypatch.setattr(nibe, "_PASSWORD", "test-password")
    monkeypatch.setattr(nibe, "_TLS_PIN_SHA256", hashlib.sha256(b"certificate").hexdigest())
    import shadow
    monkeypatch.setattr(shadow, "active", lambda: False)
    h = Heater()
    monkeypatch.setattr(nibe, "_request", h.request)
    return h


def driver(**kw):
    return nibe.NibeLocalHeatPumpDriver(connection={"expected_product": PRODUCT}, **kw)


def test_real_discovery_shape_uses_device_index_and_scales_by_metadata(heater):
    values = driver().read_sensors()
    assert values["outdoor_temp"] == -3.5 and values["water_temp"] == 50.4
    assert values["forward_temp"] is None and values["compressor_power_kw"] is None
    assert values["_timestamp_basis"] == "local_receipt"
    assert heater.requests == [("GET", "/api/v1/devices"), ("GET", "/api/v1/devices/0/points")]


def test_other_models_do_not_inherit_s1255_register_map(heater):
    heater.product = "NIBE S735"
    values = nibe.NibeLocalHeatPumpDriver().read_sensors()
    assert values["water_temp"] is None


def test_wrong_product_or_device_cannot_be_read_or_written(heater):
    heater.product = "unexpected"
    d = driver(control_enabled=True, points={"room_target": binding()})
    assert d.read_sensors() == {}
    assert not d.set_room_temp(21)
    assert not heater.writes


@pytest.mark.parametrize("change", [{"integerValue": -32768}, {"isOk": False}, {"variableId": 999},
                                    {"integerValue": True}])
def test_unavailable_or_wrong_identity_sensor_is_unknown(heater, change):
    heater.points["11"]["value"].update(change)
    assert driver().read_sensors()["water_temp"] is None


@pytest.mark.parametrize("change", [{"divisor": 0}, {"divisor": float("nan")}, {"unit": "W"},
                                    {"variableType": "date"}, {"variableSize": "s8"}])
def test_bad_sensor_metadata_is_unknown(heater, change):
    heater.points["11"]["metadata"].update(change)
    assert driver().read_sensors()["water_temp"] is None


def test_missing_pin_prevents_any_authenticated_request(heater, monkeypatch):
    monkeypatch.setattr(nibe, "_TLS_PIN_SHA256", "invalid")
    assert driver().read_sensors() == {}
    assert not heater.requests


def test_control_is_opt_in_even_with_point_bindings(heater):
    assert not driver(points={"room_target": binding()}).set_room_temp(21)
    assert not nibe.NibeLocalHeatPumpDriver(control_enabled=True, points={"room_target": binding()}).set_room_temp(21)
    assert not heater.writes


@pytest.mark.parametrize("field,method", [("room_target", "set_room_temp"), ("water_stop", "set_water_stop_temp"),
                                        ("water_start", "set_water_start_temp"), ("heating_start", "set_heating_start_temp")])
def test_all_temperature_setters_use_configured_identity_and_readback(heater, field, method):
    d = driver(control_enabled=True, points={field: binding(variable_id=3699)})
    assert getattr(d, method)(42.5)
    assert heater.writes == [[{"type": "datavalue", "isOk": True, "variableId": 3699,
                              "integerValue": 425, "stringValue": ""}]]
    assert heater.requests[-1][0] == "GET"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, "21", 9, 66, 21.55])
def test_invalid_or_unrepresentable_targets_never_write(heater, value):
    assert not driver(control_enabled=True, points={"room_target": binding()}).set_room_temp(value)
    assert not heater.writes


def test_device_metadata_range_and_writability_are_enforced(heater):
    d = driver(control_enabled=True, points={"room_target": binding()})
    heater.points["3699"]["metadata"].update(minValue=400, maxValue=500)
    assert not d.set_room_temp(21)
    heater.points["3699"]["metadata"]["isWritable"] = False
    assert not d.set_room_temp(45)
    assert not heater.writes


def test_no_write_mapping_is_guessed_from_sensor_or_title(heater):
    assert not driver(control_enabled=True).set_room_temp(21)
    assert not driver(control_enabled=True, points={"room_target": {"title": "Synthetic point"}}).set_room_temp(21)
    assert not heater.writes


def test_changed_metadata_is_rechecked_before_every_write(heater):
    d = driver(control_enabled=True, points={"room_target": binding()})
    assert d.set_room_temp(42)
    heater.points["3699"]["metadata"]["modbusRegisterID"] = 59
    assert not d.set_room_temp(43)
    assert len(heater.writes) == 1


def test_noop_target_does_not_write(heater):
    assert driver(control_enabled=True, points={"room_target": binding()}).set_room_temp(40)
    assert not heater.writes


def test_water_threshold_pair_preserves_hysteresis(heater):
    heater.points["3703"] = point(3703, 62, 500, writable=True)
    d = driver(control_enabled=True, points={"water_start": binding(58), "water_stop": binding(62)})
    assert not d.set_water_start_temp(50)
    assert not d.set_water_stop_temp(40)
    assert not heater.writes
    assert d.set_water_stop_temp(55)
    assert d.set_water_start_temp(45)


def test_oversized_response_is_rejected(monkeypatch):
    conn = FakeHTTPS()
    conn.body = b" " * 2_000_001
    monkeypatch.setattr(nibe.http.client, "HTTPSConnection", lambda *a, **kw: conn)
    with pytest.raises(nibe.LocalRestError):
        nibe._request("heater.invalid", 8443, hashlib.sha256(b"certificate").hexdigest(), "GET", "/", 1)
    assert conn.closed


def test_partial_status_and_wrong_readback_do_not_report_success(heater, monkeypatch):
    original = heater.request

    def no_status(*args, **kwargs):
        result = original(*args, **kwargs)
        return {} if args[3] == "PATCH" else result

    monkeypatch.setattr(nibe, "_request", no_status)
    d = driver(control_enabled=True, points={"room_target": binding()})
    assert not d.set_room_temp(42)
    assert d.set_room_temp(42)  # Already applied; independent GET confirms, no new PATCH.
    assert len(heater.writes) == 1


def test_ambiguous_delivery_blocks_replay_until_independent_confirmation(heater):
    d = driver(control_enabled=True, points={"room_target": binding()})
    heater.apply = False
    assert not d.set_room_temp(42)
    assert not d.set_room_temp(42)
    assert len(heater.writes) == 1
    heater.points["3699"]["value"]["integerValue"] = 420
    assert d.set_room_temp(42)
    assert len(heater.writes) == 1


def test_timeout_after_patch_does_not_replay(heater, monkeypatch):
    d = driver(control_enabled=True, points={"room_target": binding()})
    original = heater.request

    def uncertain(*args, **kwargs):
        result = original(*args, **kwargs)
        if args[3] == "PATCH":
            raise TimeoutError
        return result

    monkeypatch.setattr(nibe, "_request", uncertain)
    assert not d.set_room_temp(42)
    assert d.set_room_temp(42)
    assert len(heater.writes) == 1


def test_operating_modes_require_explicit_caller_mapping_and_allowlist(heater):
    mode = point(3697, 56, 1, divisor=1, unit="", writable=True)
    heater.points["3697"] = mode
    d = driver(control_enabled=True, points={"operating_mode": binding(56, unit="", allowed_values=[0, 1])},
               mode_values={"heat": 0})
    assert not d.set_operating_mode(1)  # No automatic Thermia code interpretation.
    assert d.set_operating_mode("heat")
    assert heater.writes[0][0]["integerValue"] == 0


def test_shadow_mode_does_not_contact_device(heater, monkeypatch):
    import shadow
    monkeypatch.setattr(shadow, "active", lambda: True)
    monkeypatch.setattr(shadow, "record", Mock())
    assert driver(control_enabled=True, points={"room_target": binding()}).set_room_temp(21)
    assert not heater.requests


def test_builder_passes_explicit_config(heater):
    d = build_heat_pump_driver({"heat_pump": {"enabled": True, "driver": "nibe_local", "control_enabled": True,
                                           "connection": {"expected_product": PRODUCT},
                                           "points": {"room_target": binding()}}})
    assert d.set_room_temp(21)


class FakeHTTPS:
    def __init__(self, cert=b"certificate", status=200, payload=None):
        self.sock = self
        self.cert = cert
        self.status = status
        self.body = json.dumps(payload or {}).encode()
        self.sent = []
        self.closed = False

    def connect(self): pass
    def settimeout(self, value): pass
    def shutdown(self, how): pass
    def getpeercert(self, binary_form): return self.cert
    def close(self): self.closed = True
    def request(self, *args, **kw): self.sent.append((args, kw))
    def getresponse(self): return self
    def read1(self, count):
        chunk, self.body = self.body[:count], self.body[count:]
        return chunk

    def isclosed(self):
        return False      # som http.client utan Content-Length: EOF upptäcks via tom read1


def test_certificate_is_verified_before_any_credentials_are_sent(monkeypatch):
    conn = FakeHTTPS(cert=b"wrong")
    monkeypatch.setattr(nibe.http.client, "HTTPSConnection", lambda *a, **kw: conn)
    with pytest.raises(nibe.LocalRestError):
        nibe._request("heater.invalid", 8443, hashlib.sha256(b"certificate").hexdigest(), "GET", "/", 1)
    assert not conn.sent and conn.closed


@pytest.mark.parametrize("status", [301, 302, 307, 401, 403, 500])
def test_transport_never_follows_redirects_or_http_errors(monkeypatch, status):
    conn = FakeHTTPS(status=status)
    monkeypatch.setattr(nibe.http.client, "HTTPSConnection", lambda *a, **kw: conn)
    with pytest.raises(nibe.LocalRestError):
        nibe._request("heater.invalid", 8443, hashlib.sha256(b"certificate").hexdigest(), "GET", "/", 1)
    assert len(conn.sent) == 1 and conn.closed


def test_pinned_transport_parses_json_and_closes_connection(monkeypatch):
    conn = FakeHTTPS(payload={"devices": []})
    monkeypatch.setattr(nibe.http.client, "HTTPSConnection", lambda *a, **kw: conn)
    result = nibe._request("heater.invalid", 8443, hashlib.sha256(b"certificate").hexdigest(), "GET", "/", 1)
    assert result == {"devices": []} and conn.closed



# ── Tomt product.name på riktig S1255 (issue #145) ───────────────────────────
def test_empty_product_name_reads_nothing_without_model_but_warns_once(heater, capsys):
    heater.product = ""
    d = nibe.NibeLocalHeatPumpDriver()
    assert d.read_sensors()["water_temp"] is None
    d.read_sensors()
    assert capsys.readouterr().out.count("inget produktnamn") == 1


def test_empty_product_name_uses_configured_model_preset(heater):
    heater.product = ""
    values = nibe.NibeLocalHeatPumpDriver(connection={"model": "S1255"}).read_sensors()
    assert values["outdoor_temp"] == -3.5 and values["water_temp"] == 50.4


def test_empty_product_name_can_be_pinned_by_serial_for_writes(heater):
    heater.product = ""
    d = nibe.NibeLocalHeatPumpDriver(connection={"model": "S1255", "expected_serial": "example"},
                                     control_enabled=True, points={"room_target": binding(variable_id=3699)})
    assert d.set_room_temp(42.5) and heater.writes
    wrong = nibe.NibeLocalHeatPumpDriver(connection={"model": "S1255", "expected_serial": "other"},
                                         control_enabled=True, points={"room_target": binding()})
    assert wrong.read_sensors() == {} and not wrong.set_room_temp(21)


def test_request_failure_logs_type_but_never_secrets(heater, monkeypatch, caplog):
    def boom(*a, **k):
        raise OSError(9, "Bad file descriptor test-password")
    monkeypatch.setattr(nibe, "_request", boom)
    d = driver()
    with caplog.at_level("WARNING"):
        assert d.read_sensors() == {}
        assert d.read_sensors() == {}
    msgs = [r.getMessage() for r in caplog.records if "NIBE local REST" in r.getMessage()]
    assert msgs == ["NIBE local REST GET /api/v1/devices failed: OSError errno 9"]
    assert "test-password" not in caplog.text and "test-user" not in caplog.text

# ── Riktig lokal TLS-server (issue #145) ─────────────────────────────────────
# Tidigare testades _request() bara mot mockar. En riktig S1255 stänger anslutningen
# efter svaret (Connection: close), och då gav läsloopen "OSError: [Errno 9] Bad file
# descriptor" i stället för data. De här testerna kör en riktig TLS-handskakning.
import shutil
import socket
import ssl
import subprocess
import threading


@pytest.fixture(scope="module")
def tls_cert(tmp_path_factory):
    if shutil.which("openssl") is None:
        pytest.skip("openssl saknas")
    d = tmp_path_factory.mktemp("nibe-tls")
    cert, key = d / "cert.pem", d / "key.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                    "-subj", "/CN=localhost", "-keyout", str(key), "-out", str(cert)],
                   check=True, capture_output=True)
    der = ssl.PEM_cert_to_DER_cert(cert.read_text())
    return str(cert), str(key), hashlib.sha256(der).hexdigest()


def _serve_once(cert, key, body, framing):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)
    listener = socket.create_server(("127.0.0.1", 0))
    port = listener.getsockname()[1]

    def run():
        with listener:
            raw, _ = listener.accept()
            try:
                _handle(ctx.wrap_socket(raw, server_side=True))
            except (OSError, ssl.SSLError):
                pass                               # klienten avbröt (t.ex. pin-fel) - inte serverns sak

    def _handle(sock):
            with sock as s:
                req = b""
                while b"\r\n\r\n" not in req:
                    chunk = s.recv(4096)
                    if not chunk:
                        return
                    req += chunk
                head = "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                if framing == "close":            # som riktiga S1255: ingen längd, stäng efter svaret
                    s.sendall((head + "Connection: close\r\n\r\n").encode() + body)
                elif framing == "close-length":
                    s.sendall((head + f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n").encode() + body)
                elif framing == "chunked":
                    s.sendall((head + "Transfer-Encoding: chunked\r\n\r\n").encode()
                              + f"{len(body):x}\r\n".encode() + body + b"\r\n0\r\n\r\n")
                else:                              # keep-alive med Content-Length
                    s.sendall((head + f"Content-Length: {len(body)}\r\n\r\n").encode() + body)
                    s.recv(1)                      # håll öppet tills klienten stänger

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return port, t


@pytest.mark.parametrize("framing", ["close", "close-length", "chunked", "keep-alive"])
def test_request_against_real_tls_server(tls_cert, monkeypatch, framing):
    cert, key, pin = tls_cert
    monkeypatch.setattr(nibe, "_USERNAME", "u")
    monkeypatch.setattr(nibe, "_PASSWORD", "p")
    payload = {"devices": [{"deviceIndex": 0, "product": {"name": "", "serialNumber": "x"}}]}
    port, t = _serve_once(cert, key, json.dumps(payload).encode(), framing)
    assert nibe._request("127.0.0.1", port, pin, "GET", "/api/v1/devices", 5) == payload
    t.join(5)


def test_request_real_tls_pin_mismatch(tls_cert, monkeypatch):
    cert, key, _ = tls_cert
    port, _t = _serve_once(cert, key, b"{}", "close")
    with pytest.raises(nibe.LocalRestError, match="pin mismatch"):
        nibe._request("127.0.0.1", port, "0" * 64, "GET", "/api/v1/devices", 5)
