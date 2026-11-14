"""Optional raw cache snapshots, private JSON storage and read-only export."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os

import psycopg
import pytest
from sqlalchemy import create_engine, text

import energy_source_evidence as evidence
from energy_source_export import export
from hot_water_power import read as water_read
from hot_water_residual import reconstruct, CONTRACT

T = datetime(2026, 11, 14, 10, tzinfo=timezone.utc)
HOUSE = {"energy_source_evidence": {"enabled": True, "boundary": "ac_household",
         "grid": {"entity_id": "sensor.grid", "positive": "import"},
         "pv": {"entity_id": "sensor.pv"}, "battery": {"entity_id": "sensor.battery", "positive": "charge"}},
         "heat_pump": {"enabled": True, "driver": "generic_climate", "hot_water_meter": {
             "entity_id": "sensor.water", "boundary": "hot_water_electrical"}}}


def cache(at=T):
    return {"sensor."+name: {"state": str(watts), "last_reported": at.isoformat(),
            "attributes": {"device_class": "power", "unit_of_measurement": "W"}}
            for name, watts in (("grid", 2000), ("pv", 1000), ("battery", 500), ("water", 1000))}


def capture(house=HOUSE, at=T, states=None):
    states = cache(at) if states is None else states
    pump = water_read(house["heat_pump"], {}, states)
    return evidence.capture(house, states, pump, now=at.timestamp())


def test_raw_sources_preserve_dates_units_and_inputs_without_derived_balance():
    states, house = cache(), deepcopy(HOUSE)
    states["sensor.grid"]["state"] = "2"
    states["sensor.grid"]["attributes"]["unit_of_measurement"] = "kW"
    original = deepcopy((states, house))
    result = capture(house, states=states)
    assert result["grid_w"] == 2000 and result["pv_w"] == 1000 and result["battery_w"] == 500
    assert result["hot_water_power_w"] == 1000 and result["grid_sample_at"] == T.timestamp()
    assert capture(house, at=T+timedelta(seconds=30), states=states)["grid_sample_at"] == T.timestamp()
    assert not result["physical_verified"] and len(result["source_context"]) == 64
    assert "sensor.grid" not in json.dumps(result)
    assert (states, house) == original


def test_explicit_signs_no_defaults_no_current_times_or_estimated_zero():
    house = deepcopy(HOUSE)
    house["energy_source_evidence"]["grid"]["positive"] = "export"
    house["energy_source_evidence"]["battery"]["positive"] = "discharge"
    result = capture(house)
    assert result["grid_w"] == -2000 and result["battery_w"] == -500
    del house["energy_source_evidence"]["grid"]["positive"]
    assert capture(house)["grid_w"] is None
    states = cache()
    states["sensor.pv"]["state"] = "unavailable"
    result = capture(states=states)
    assert result["pv_w"] is None and result["pv_sample_at"] is None
    states = cache()
    del states["sensor.grid"]["last_reported"]
    result = capture(states=states)
    assert result["grid_w"] == 2000 and result["grid_sample_at"] is None and result["grid_basis"] == "unknown"


def test_disabled_or_undeclared_boundary_produces_no_snapshot():
    assert evidence.capture({}, {}, {}, now=T.timestamp()) is None
    house = deepcopy(HOUSE)
    house["energy_source_evidence"]["boundary"] = "energyhub_dc"
    assert capture(house) is None


def test_duplicate_meter_role_and_local_preference_are_not_silently_accepted():
    house = deepcopy(HOUSE)
    house["energy_source_evidence"]["pv"]["entity_id"] = "sensor.grid"
    result = capture(house)
    assert result["grid_w"] is None and result["pv_w"] is None
    house = deepcopy(HOUSE)
    house["heat_pump"]["driver"] = "nibe_local"
    result = capture(house)
    assert result["hot_water_power_w"] is None  # valid HA meter cannot override preferred local REST


def test_context_fingerprints_change_with_mapping_and_process_restart(monkeypatch):
    first = capture()
    assert capture()["source_context"] == first["source_context"]
    house = deepcopy(HOUSE)
    house["energy_source_evidence"]["grid"]["entity_id"] = "sensor.other_grid"
    assert capture(house)["source_context"] != first["source_context"]
    monkeypatch.setattr(evidence, "_SESSION", "another-process")
    assert capture()["source_context"] != first["source_context"]


def test_logger_allowlist_drops_raw_data_and_invalid_claims():
    sample = capture()
    assert "secret" not in json.dumps(evidence.log_value({**sample, "entity_id": "secret", "credentials": "secret"}))
    for key, value in (("physical_verified", True), ("grid_w", True), ("pv_w", -1), ("source_context", "bad")):
        assert evidence.log_value({**sample, key: value}) is None
    assert evidence.log_value({**sample, "hot_water_power_source": None}) is None
    assert evidence.log_value({**sample, "hot_water_power_source": "nibe_local"}) is None


def test_reconstruction_refuses_cross_mapping_or_mixed_identity_intervals():
    rows = [capture(), capture(at=T+timedelta(seconds=60))]
    rows[1]["source_context"] = "f"*64
    result = reconstruct(rows, CONTRACT, min_coverage=.01)
    assert not result["rows"] and result["report"]["rejected_intervals"] == {"source_mapping_changed": 1}
    del rows[1]["source_context"]
    assert not reconstruct(rows, CONTRACT, min_coverage=.01)["rows"]


def test_actual_jsonb_log_export_and_reconstruction_keep_legacy_gaps(db, monkeypatch):
    import logger
    @contextmanager
    def connection():
        yield db
    monkeypatch.setattr(logger, "get_db", connection)
    monkeypatch.setattr(logger, "_bool_columns", set())
    logger.init_log_db()
    logger.init_log_db()
    class Clock:
        at = T
        @classmethod
        def now(cls, zone):
            return cls.at.astimezone(zone)
    monkeypatch.setattr(logger, "datetime", Clock)
    for i in range(16):
        Clock.at = T+timedelta(minutes=i)
        sample = capture(at=Clock.at)
        logger.log_status(*([None]*20), pump={}, energy_evidence={**sample, "credentials": "secret"})
    engine = create_engine("postgresql+psycopg://", creator=lambda: psycopg.connect(db.info.dsn,password=os.environ["POSTGRES_PASSWORD"]))
    try:
        with engine.connect() as conn:
            output = export(conn, T, T+timedelta(minutes=15))
            assert conn.execute(text("SHOW transaction_read_only")).scalar() == "on"
        assert len(output["samples"]) == 16 and "secret" not in json.dumps(output)
        assert reconstruct(output["samples"], output["contract"])["rows"][0]["kw"] == 1.5
        db.execute("UPDATE sensor_log SET energy_source_evidence=NULL WHERE timestamp=%s", (T+timedelta(minutes=8),))
        with engine.connect() as conn:
            missing = export(conn, T, T+timedelta(minutes=15))
        assert missing["export_report"]["missing_evidence_rows"] == 1 and len(missing["samples"]) == 16
        assert not reconstruct(missing["samples"], missing["contract"], max_gap_s=300)["rows"]
        with engine.connect() as conn, pytest.raises(ValueError, match="Too many"):
            export(conn, T, T+timedelta(minutes=15), limit=2)
    finally:
        engine.dispose()
        db.execute("DELETE FROM sensor_log WHERE timestamp >= %s AND timestamp <= %s", (T, T+timedelta(minutes=15)))


def test_invalid_export_inputs_are_rejected_before_database_connection(monkeypatch):
    import importlib.util
    from pathlib import Path
    import sys
    from types import SimpleNamespace
    from unittest.mock import Mock
    script = Path(__file__).resolve().parents[1] / "scripts" / "export_energy_source_evidence.py"
    spec = importlib.util.spec_from_file_location("source_export_cli", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    connect = Mock(side_effect=AssertionError("Invalid arguments must not connect"))
    monkeypatch.setitem(sys.modules, "database_engine", SimpleNamespace(engine=SimpleNamespace(connect=connect)))
    monkeypatch.setattr(sys, "argv", [str(script), "--since", "2026-11-14T10:00:00", "--until", "2026-11-15T10:00:00Z"])
    with pytest.raises(SystemExit) as error:
        module.main()
    assert error.value.code == 2
    connect.assert_not_called()


def test_export_cli_does_not_echo_private_connection_errors(monkeypatch, capsys):
    import importlib.util
    from pathlib import Path
    import sys
    from types import SimpleNamespace
    from unittest.mock import Mock
    script = Path(__file__).resolve().parents[1] / "scripts" / "export_energy_source_evidence.py"
    spec = importlib.util.spec_from_file_location("private_source_export_cli", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    connect = Mock(side_effect=ValueError("secret database URL"))
    monkeypatch.setitem(sys.modules, "database_engine", SimpleNamespace(engine=SimpleNamespace(connect=connect)))
    monkeypatch.setattr(sys, "argv", [str(script), "--since", T.isoformat(), "--until", (T+timedelta(minutes=15)).isoformat()])
    with pytest.raises(SystemExit):
        module.main()
    assert "secret" not in capsys.readouterr().err
