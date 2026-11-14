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
    from hot_water_observation import assess
    observation = values["water_temp_observation"]
    assert observation["value_c"] == 50.4
    assert observation["timestamp_basis"] == "local_receipt"
    assert assess(observation, now=observation["sample_at"], max_age_s=60)["state"] == "receipt_only"
    assert not heater.writes
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


def test_selected_local_rest_never_falls_back_to_cloud_for_timestamp_evidence(heater, monkeypatch):
    from drivers.heatpump_myuplink import MyUplinkHeatPumpDriver
    monkeypatch.setattr(MyUplinkHeatPumpDriver, "_points",
                        lambda *args: pytest.fail("Local REST must not read myUplink"))
    d = build_heat_pump_driver({"heat_pump": {"enabled": True, "driver": "nibe_local",
                              "connection": {"expected_product": PRODUCT},
                              "entities": {"water_temp": "cloud-point"}}})
    assert isinstance(d, nibe.NibeLocalHeatPumpDriver)
    observation = d.read_state()["dhw_temp_observation"]
    assert observation["value_c"] == 50.4 and observation["timestamp_basis"] == "local_receipt"
    heater.product = "unexpected"
    d._device = None
    assert d.read_state()["dhw_temp_observation"]["value_c"] is None
    assert not heater.writes


def test_dedicated_hot_water_power_requires_explicit_boundary_and_units(heater):
    heater.points["123"] = point(123, 9001, 15, unit="kW")
    mapping = {"register": 9001, "unit": "kW", "boundary": "hot_water_electrical"}
    d = driver(points={"hot_water_power_w": mapping})
    assert d.read_sensors()["hot_water_power_w"] == 1500
    del mapping["boundary"]
    assert d.read_sensors()["hot_water_power_w"] is None
    assert not heater.writes


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


@pytest.mark.parametrize("echo_raw,ok", [(None, True), (999, False)])
def test_s1255_svarar_med_hela_punkten_pa_patch(heater, echo_raw, ok):
    """#152: en riktig S1255 svarar på PATCH med hela den uppdaterade punkten i stället för "modified". Ekat värde
    som stämmer = lyckat; ekat värde som inte stämmer = inte bekräftat."""
    orig = heater.request

    def request(host, port, pin, method, path, timeout, payload=None):
        r = orig(host, port, pin, method, path, timeout, payload)
        if method == "PATCH":
            p = deepcopy(heater.points["3699"])
            if echo_raw is not None:
                p["value"]["integerValue"] = echo_raw
            return {"3699": p}
        return r
    nibe._request = request
    d = driver(control_enabled=True, points={"room_target": binding(variable_id=3699)})
    assert d.set_room_temp(45) is ok
    assert heater.points["3699"]["value"]["integerValue"] == 450


def test_s1255_matvarden_for_varmepumpsfliken(heater):
    """#159: kompressorfrekvens, el in och pumpens energilogg för senaste timmen (register ur en riktig S1255)."""
    heater.points.update({"41046": point(41046, 1046, 52, divisor=1, unit="Hz"),
                          "41048": point(41048, 1048, 1430, divisor=1, unit="W"),
                          "42283": point(42283, 2283, 82, divisor=100, unit="kWh"),
                          "42291": point(42291, 2291, -17, divisor=100, unit="kWh")})
    v = driver().read_sensors()
    assert v["compressor_frequency_hz"] == 52 and v["compressor_power_w"] == 1430
    assert v["heat_produced_kwh_1h"] == 0.82
    assert v["electric_used_kwh_1h"] is None                     # negativt = saknas


def test_andra_modeller_far_inga_matvarden(heater):
    heater.product = "NIBE S735"
    heater.points["41046"] = point(41046, 1046, 52, divisor=1, unit="Hz")
    assert nibe.NibeLocalHeatPumpDriver().read_sensors().get("compressor_frequency_hz") is None
