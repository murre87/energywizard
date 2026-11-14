"""Hot-water timestamp evidence, without contacting HA, cloud or a heater."""
from datetime import datetime, timezone

import pytest
from hot_water_observation import temperature, assess

STAMP = "2026-11-14T10:00:00Z"
T = datetime(2026, 11, 14, 10, tzinfo=timezone.utc).timestamp()


@pytest.mark.parametrize("bad", [None, "not-a-time", "2026-11-14T10:00:00", 123, True])
def test_missing_or_invalid_dates_never_use_current_time(bad):
    obs = temperature(48, bad, "source")
    assert obs == {"value_c": 48, "sample_at": None, "timestamp_basis": "unknown"}
    assert assess(obs, now=T, max_age_s=60)["state"] == "unknown"


@pytest.mark.parametrize("bad", [None, True, float("nan"), float("inf"), "48", -81, 151])
def test_invalid_temperature_cannot_receive_freshness(bad):
    obs = temperature(bad, STAMP, "source")
    assert obs["value_c"] is None and obs["sample_at"] is None


def test_offset_age_stale_future_and_receipt_distinction():
    obs = temperature(48, "2026-11-14T11:00:00+01:00", "source")
    assert obs["sample_at"] == T
    assert assess(obs, now=T+60, max_age_s=60) == {"state": "fresh", "age_s": 60}
    assert assess(obs, now=T+61, max_age_s=60)["state"] == "stale"
    assert assess(obs, now=T-1, max_age_s=60)["state"] == "future"
    receipt = temperature(48, STAMP, "local_receipt")
    assert assess(receipt, now=T+1, max_age_s=60)["state"] == "receipt_only"
    assert assess(receipt, now=T+1, max_age_s=60, allow_receipt=True)["state"] == "fresh"
    assert assess(receipt, now=T+61, max_age_s=60, allow_receipt=True)["state"] == "stale"


@pytest.mark.parametrize("changes", [{"now": True}, {"now": float("nan")}, {"max_age_s": 0}, {"max_age_s": float("inf")}])
def test_invalid_assessment_policy(changes):
    with pytest.raises(ValueError):
        assess(temperature(48, STAMP, "source"), **{**dict(now=T, max_age_s=60), **changes})


def test_ha_repeated_cache_reads_do_not_refresh_temperature(monkeypatch):
    import homeassistant
    from drivers.heatpump_ha_entities import HaEntitiesHeatPumpDriver
    cache = {"sensor.water": {"state": "48", "last_reported": STAMP,
                              "last_updated": "2026-11-14T09:00:00Z"}}
    monkeypatch.setattr(homeassistant, "_states_cache", cache)
    driver = HaEntitiesHeatPumpDriver({"water_temp": "sensor.water"})
    first = driver.read_state()["dhw_temp_observation"]
    assert first == {"value_c": 48, "sample_at": T, "timestamp_basis": "ha_report"}
    assert driver.read_state()["dhw_temp_observation"] == first
    assert assess(first, now=T+61, max_age_s=60)["state"] == "stale"
    del cache["sensor.water"]["last_reported"]
    assert driver.read_state()["dhw_temp_observation"]["sample_at"] == T-3600
    cache["sensor.water"]["state"] = "unavailable"
    assert driver.read_state()["dhw_temp_observation"]["value_c"] is None


def test_cloud_uses_point_date_not_response_read_time(monkeypatch):
    from drivers.heatpump_myuplink import MyUplinkHeatPumpDriver
    driver = MyUplinkHeatPumpDriver({"water_temp": "test-water"})
    points = [{"parameterId": "test-water", "value": 48, "timestamp": STAMP}]
    monkeypatch.setattr(driver, "_points", lambda: points)
    assert driver.read_state()["dhw_temp_observation"] == {
        "value_c": 48, "sample_at": T, "timestamp_basis": "source"}
    del points[0]["timestamp"]
    assert driver.read_state()["dhw_temp_observation"]["sample_at"] is None


def test_legacy_driver_retains_value_without_invented_date():
    from drivers.heatpump import NullHeatPumpDriver
    driver = NullHeatPumpDriver()
    driver.read_sensors = lambda: {"water_temp": 48}
    state = driver.read_state()
    assert state["dhw_temp"] == 48
    assert state["dhw_temp_observation"]["timestamp_basis"] == "unknown"
