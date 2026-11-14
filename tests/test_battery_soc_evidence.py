"""SOC dating stays diagnostic; synthetic HA/cache data only, no network calls."""
from datetime import datetime, timezone

import pytest

import homeassistant as ha
from drivers.battery import soc_input_quality
from drivers.battery_generic import GenericBatteryDriver


def test_quality_reports_age_without_mutating_evidence():
    state = dict(soc_pct=50, soc_sample_at=1000, soc_source="ferroamp_mqtt_received", token="private")
    assert soc_input_quality(50, state, 1030) == dict(source="ferroamp_mqtt_received", known=True, age_s=30)
    assert soc_input_quality(50, state, 1100)["age_s"] == 100
    assert state["soc_sample_at"] == 1000
    assert "private" not in str(soc_input_quality(50, state, 1030))


@pytest.mark.parametrize("change", [dict(soc_sample_at=None), dict(soc_sample_at=1031),
    dict(soc_sample_at=True), dict(soc_sample_at=float("nan")), dict(soc_sample_at=float("inf")),
    dict(soc_sample_at=-1), dict(soc_pct=51), dict(soc_source="secret host"), dict(soc_source={}), dict(soc_pct=True)])
def test_invalid_or_mismatched_evidence_stays_unknown(change):
    state = dict(soc_pct=50, soc_sample_at=1000, soc_source="ha_reported") | change
    assert soc_input_quality(50, state, 1030) == dict(source="battery", known=True, age_s=None)


def test_legacy_and_unknown_soc_have_unknown_age():
    assert soc_input_quality(50, None, 1000) == dict(source="battery", known=True, age_s=None)
    assert soc_input_quality(None, {}, 1000) == dict(source="battery", known=False, age_s=None)


def _read(monkeypatch, states, entities):
    monkeypatch.setattr(ha, "_states_cache", states)
    monkeypatch.setattr(ha, "_get_numeric_state", lambda e: float(states[e]["state"]) if states.get(e, {}).get("state") not in (None, "unavailable") else None)
    monkeypatch.setattr(ha, "get_power_w", lambda e: None)
    return GenericBatteryDriver(entities=entities).read_state()


def test_generic_uses_reported_not_last_changed_or_cache_read_time(monkeypatch):
    state = {"state": "50", "last_changed": "2026-11-01T00:00:00Z",
             "last_updated": "2026-11-14T00:00:00Z", "last_reported": "2026-11-14T01:00:00+01:00"}
    expected = datetime(2026, 11, 14, tzinfo=timezone.utc).timestamp()
    first = _read(monkeypatch, {"sensor.soc": state}, {"soc": "sensor.soc"})
    second = _read(monkeypatch, {"sensor.soc": state}, {"soc": "sensor.soc"})
    assert first["soc_sample_at"] == second["soc_sample_at"] == expected
    assert first["soc_source"] == "ha_reported"


def test_generic_weighted_banks_use_oldest_date_and_weaker_basis(monkeypatch):
    states = {"s.a": {"state": "20", "last_updated": "2026-11-14T00:00:00Z"},
              "s.b": {"state": "80", "last_reported": "2026-11-14T01:00:00Z"}}
    state = _read(monkeypatch, states, {"soc": ["s.a", "s.b"], "bank_kwh": [1, 3]})
    assert state["soc_pct"] == 65
    assert state["soc_source"] == "ha_updated"
    assert state["soc_sample_at"] == datetime(2026, 11, 14, tzinfo=timezone.utc).timestamp()
    states["s.b"]["state"] = "unavailable"
    state = _read(monkeypatch, states, {"soc": ["s.a", "s.b"]})
    assert state["soc_pct"] == 20  # Preserve the pre-existing partial-SOC behavior.
    assert state["soc_sample_at"] is None


@pytest.mark.parametrize("stamp", [None, "unknown", "2026-11-14T00:00:00"])
def test_generic_does_not_invent_dates(monkeypatch, stamp):
    state = _read(monkeypatch, {"s.a": {"state": "50", "last_updated": stamp}}, {"soc": "s.a"})
    assert state["soc_pct"] == 50
    assert state["soc_sample_at"] is None and state["soc_source"] is None
