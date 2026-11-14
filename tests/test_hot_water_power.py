"""Optional dedicated-load capture: missing != zero; no network/control calls."""
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
import hot_water_power as power

STAMP = "2026-11-14T10:00:00Z"
T = datetime(2026, 11, 14, 10, tzinfo=timezone.utc).timestamp()
HP = {"enabled": True, "driver": "generic_climate", "hot_water_meter": {
    "entity_id": "sensor.dhw", "boundary": "hot_water_electrical"}}


def cache(value="1.5", unit="kW", **changes):
    return {"sensor.dhw": {"state": value, "attributes": {"unit_of_measurement": unit, "device_class": "power"},
                           "last_reported": STAMP, **changes}}


def test_explicit_cached_power_units_zero_and_old_dates_are_preserved():
    result = power.read(HP, {}, cache())
    assert result == dict(zip(power.KEYS, (1500, T, "ha_report", "ha_sensor")))
    assert power.read(HP, {}, cache("0", "W"))["hot_water_power_w"] == 0
    assert power.read(HP, {}, cache())["hot_water_power_sample_at"] == T  # cache read is not a new measurement


@pytest.mark.parametrize("value", ["unavailable", "unknown", True, "nan", "inf", "-1", None])
def test_unavailable_invalid_or_negative_values_never_become_zero(value):
    assert power.read(HP, {}, cache(value))["hot_water_power_w"] is None


def test_unqualified_units_boundary_and_whole_compressor_power_are_not_used():
    assert power.read(HP, {}, cache(unit="kWh"))["hot_water_power_w"] is None
    assert power.read({"enabled": True, "driver": "generic_climate"}, {"compressor_power_w": 3000}, cache())["hot_water_power_w"] is None
    assert power.read({**HP, "hot_water_meter": {"entity_id": "sensor.dhw"}}, {}, cache())["hot_water_power_w"] is None
    raw = cache()
    raw["sensor.dhw"]["attributes"]["device_class"] = "energy"
    assert power.read(HP, {}, raw)["hot_water_power_w"] is None


def test_missing_or_naive_source_date_stays_unknown_without_losing_numeric_reading():
    for stamp in (None, "bad", "2026-11-14T10:00:00"):
        result = power.read(HP, {}, cache(last_reported=stamp))
        assert result["hot_water_power_w"] == 1500
        assert result["hot_water_power_sample_at"] is None and result["hot_water_power_basis"] == "unknown"


def test_local_rest_exclusive_no_ha_fallback_and_receipt_is_not_device_sample():
    hp = {**HP, "driver": "nibe_local", "points": {"hot_water_power_w": {"boundary": "hot_water_electrical"}}}
    assert power.read(hp, {}, cache())["hot_water_power_w"] is None
    result = power.read(hp, {"hot_water_power_w": 500, "_received_at": STAMP}, cache())
    assert result == dict(zip(power.KEYS, (500, T, "local_receipt", "nibe_local")))
    assert power.read({**hp, "points": {}}, {"hot_water_power_w": 500}, cache())["hot_water_power_w"] is None


def test_logger_fields_refuse_unknown_provenance_and_unavailable_booleans():
    for watts, source in ((True, "ha_sensor"), (1, "secret host"), (float("nan"), "nibe_local")):
        assert all(v is None for v in power.log_fields(dict(zip(power.KEYS, (watts, T, "ha_report", source)))).values())


def test_nullable_schema_and_actual_minute_log_keep_zero_distinct_from_missing(db, monkeypatch):
    import logger
    @contextmanager
    def connection():
        yield db
    monkeypatch.setattr(logger, "get_db", connection)
    monkeypatch.setattr(logger, "_bool_columns", set())
    logger.init_log_db()
    logger.init_log_db()  # additive migration can run repeatedly
    columns = db.execute("SELECT column_name FROM information_schema.columns WHERE table_name='sensor_log'").fetchall()
    assert set(power.KEYS) <= {r[0] for r in columns}
    args = [None] * 20
    for watts in (0, None):
        pump = dict(zip(power.KEYS, (watts, T, "ha_report", "ha_sensor")))
        logger.log_status(*args, pump=pump)
    rows = db.execute("SELECT hot_water_power_w,hot_water_power_sample_at,hot_water_power_basis,hot_water_power_source "
                      "FROM sensor_log ORDER BY timestamp DESC LIMIT 2").fetchall()
    assert rows[0] == (None, None, None, None)
    assert float(rows[1][0]) == 0 and rows[1][1:] == (T, "ha_report", "ha_sensor")
