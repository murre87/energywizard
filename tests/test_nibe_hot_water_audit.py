"""Captured synthetic metadata only; constructor, transport and writes forbidden."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import pytest
from nibe_hot_water_audit import audit, ROLES
from drivers.heatpump_nibe_local import NibeLocalHeatPumpDriver


@pytest.fixture
def captured(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Offline audit must not construct/read/write a client")
    for method in ("__init__", "_read_points", "_call", "_write"):
        monkeypatch.setattr(NibeLocalHeatPumpDriver, method, forbidden)
    points, bindings = {}, {}
    for i, role in enumerate(ROLES):
        variable, register = 100+i, 900+i  # deliberately synthetic, not NIBE IDs
        command = role in {"boost", "demand_mode"}
        unit = "" if command else "W" if role == "electrical_power" else "°C"
        register_type = "MODBUS_HOLDING_REGISTER" if command else "MODBUS_INPUT_REGISTER"
        raw = 0 if command else 1000 if role == "electrical_power" else 50
        points[str(variable)] = {"title": "private title not for report", "metadata": {
            "variableId": variable, "variableType": "integer", "variableSize": "s16", "divisor": 1,
            "unit": unit, "isWritable": command, "modbusRegisterID": register,
            "modbusRegisterType": register_type, "minValue": 0, "maxValue": 10},
            "value": {"variableId": variable, "isOk": True, "integerValue": raw}}
        bindings[role] = {"variable_id": variable, "register": register, "register_type": register_type, "unit": unit}
        if command:
            bindings[role].update(allowed_values=[0, 3], release_value=0)
            bindings[role]["start_value" if role == "boost" else "requested_value"] = 3
        if role == "electrical_power":
            bindings[role]["boundary"] = "hot_water_electrical"
    return points, bindings


def test_complete_metadata_never_confers_hardware_permission_or_leaks_raw_data(captured):
    points, bindings = captured
    original = deepcopy(captured)
    result = audit(points, bindings)
    assert result["metadata_consistent"]
    for key in ("control_ready", "physical_verified", "release_verified", "timing_verified", "freshness_verified"):
        assert result[key] is False
    assert "private" not in json.dumps(result) and captured == original


def test_no_default_ids_title_or_cloud_fallback(captured):
    points, _ = captured
    result = audit(points, {})
    assert not result["metadata_consistent"]
    assert all(r["reason"] == "binding_missing" for r in result["roles"].values())


@pytest.mark.parametrize("field,value", [("variable_id", True), ("variable_id", 999), ("register", 999),
                                       ("unit", "unknown"), ("start_value", 0), ("allowed_values", [False, 3]),
                                       ("allowed_values", [0, 30]), ("release_value", 30)])
def test_invalid_boost_binding_blocks_report(captured, field, value):
    points, bindings = captured
    bindings["boost"][field] = value
    assert audit(points, bindings)["roles"]["boost"]["state"] == "blocked"


@pytest.mark.parametrize("field,value", [("isWritable", False), ("divisor", 10), ("variableId", 999),
                                       ("variableSize", "invalid"), ("minValue", 10), ("maxValue", 0)])
def test_wrong_metadata_or_unknown_bounds_blocks_report(captured, field, value):
    points, bindings = captured
    points["100"]["metadata"][field] = value
    assert audit(points, bindings)["roles"]["boost"]["state"] == "blocked"


@pytest.mark.parametrize("raw", [-32768, True, None, 99])
def test_unavailable_or_unrecognized_command_state(captured, raw):
    points, bindings = captured
    points["100"]["value"]["integerValue"] = raw
    assert audit(points, bindings)["roles"]["boost"]["state"] == "blocked"


def test_temperature_roles_must_not_share_identity_and_power_boundary_is_explicit(captured):
    points, bindings = captured
    bindings["charging_temperature"] = dict(bindings["top_temperature"])
    del bindings["electrical_power"]["boundary"]
    result = audit(points, bindings)
    assert result["roles"]["top_temperature"]["reason"] == "ambiguous_role_identity"
    assert result["roles"]["charging_temperature"]["reason"] == "ambiguous_role_identity"
    assert result["roles"]["electrical_power"]["reason"] == "electrical_boundary_unqualified"


def test_enum_word_width_and_sentinels_are_checked(captured):
    points, bindings = captured
    bindings["boost"].update(allowed_values=[0, -32768], start_value=-32768)
    points["100"]["metadata"].update(minValue=-32768, maxValue=32767)
    assert audit(points, bindings)["roles"]["boost"]["state"] == "blocked"


def test_cli_reads_only_explicit_local_capture(captured, tmp_path):
    points, bindings = captured
    source = tmp_path / "capture.json"
    source.write_text(json.dumps({"points": points, "bindings": bindings, "credentials": "secret"}))
    script = Path(__file__).resolve().parents[1] / "scripts" / "audit_nibe_hot_water.py"
    output = subprocess.run([sys.executable, str(script), str(source)], check=True, capture_output=True, text=True).stdout
    assert json.loads(output)["metadata_consistent"] and "secret" not in output
