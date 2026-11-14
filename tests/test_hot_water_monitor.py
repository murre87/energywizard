"""Default-off runtime advisory plumbing; synthetic signals and isolated PG only."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import threading

import pytest
from hot_water_monitor import Evaluator, Monitor, decode, stored_prices, publish
from hot_water_observation import temperature

T = datetime(2026, 11, 14, 10, tzinfo=timezone.utc)
NOW = T.timestamp()
POLICY = {"comfort_c": 50, "target_c": 55, "max_trigger_age_s": 7200,
          "min_trigger_interval_s": 3600, "comfort_window_s": 1800, "comfort_bypasses_interval": True,
          "duration_min": 15, "electrical_power_kw": 2, "max_age_s": 90, "allow_receipt": True}


def event(**changes):
    return {**{"enabled": True, "driver": "nibe_local", "now": NOW, "shadow": True,
               "manual": False, "away": False, "hygiene": False, "temperature_role_verified": True,
               "observation": temperature(49, T.isoformat(), "local_receipt"), "policy": dict(POLICY)}, **changes}


def test_evaluator_persists_anchors_before_proposal_and_selects_cheaper_price():
    saved, reports = {}, []
    def save(state):
        saved.update(state)
    def prices(now):
        assert saved["comfort_since"] == NOW
        return [{"t": (T+timedelta(minutes=15*i)).isoformat(), "buy": value} for i, value in enumerate([5, 1])]
    evaluator = Evaluator(load=lambda: dict(saved), save=save, prices=prices, sink=reports.append)
    report = evaluator.process(event())
    assert report["state"] == "proposed" and report["start"] == (T+timedelta(minutes=15)).isoformat()
    assert report["control_ready"] is False and report["reservation_applied"] is False
    evaluator.process(event(now=NOW+30, observation=temperature(49, (T+timedelta(seconds=30)).isoformat(), "local_receipt")))
    assert saved["comfort_since"] == NOW and len(reports) == 2
    assert decode(json.dumps(report), NOW)["fresh"]


@pytest.mark.parametrize("changes,state", [
    ({"enabled": False}, "disabled"), ({"shadow": False}, "requires_shadow"),
    ({"manual": True}, "precedence_blocked"), ({"away": True}, "precedence_blocked"),
    ({"hygiene": True}, "precedence_blocked"), ({"driver": "unknown"}, "unsupported_driver"),
    ({"temperature_role_verified": False}, "sensor_role_unqualified"),
])
def test_gates_make_no_state_or_price_calls(changes, state):
    def forbidden(*args):
        pytest.fail("Gated monitor must not read/write state or query prices")
    result = Evaluator(load=forbidden, save=forbidden, prices=forbidden, sink=lambda r: None).process(event(**changes))
    assert result["state"] == state


def test_store_failure_or_bad_evidence_cannot_publish_proposal():
    def fail(state):
        raise OSError("secret endpoint must not appear")
    evaluator = Evaluator(load=lambda: {}, save=fail, prices=lambda now: pytest.fail("No price call"), sink=lambda r: None)
    result = evaluator.process(event())
    assert result["state"] == "unavailable" and "secret" not in json.dumps(result)
    evaluator.save = lambda s: None
    stale = evaluator.process(event(observation=temperature(49, (T-timedelta(hours=1)).isoformat(), "local_receipt")))
    assert stale["state"] == "observation_unavailable"
    malformed = event()["observation"]
    malformed["timestamp_basis"] = "secret endpoint must not appear"
    result = evaluator.process(event(observation=malformed))
    assert "secret" not in json.dumps(result)


def test_actual_settings_store_retains_anchor_across_evaluator_restart(tmp_path, monkeypatch):
    import ew_settings
    monkeypatch.setattr(ew_settings, "PATH", str(tmp_path / "settings.json"))
    for seconds in (0, 30):
        monitor = Evaluator(prices=lambda now: [], sink=lambda r: None)
        result = monitor.process(event(now=NOW+seconds, observation=temperature(49, (T+timedelta(seconds=seconds)).isoformat(), "local_receipt")))
        assert result["state"] == "schedule_unavailable"
    assert ew_settings.get("hot_water_shadow_demand")["anchor_at"] == NOW
    assert ew_settings.get("hot_water_shadow_demand")["comfort_since"] == NOW


def test_default_off_submit_starts_no_worker():
    monitor = Monitor(process=lambda e: pytest.fail("Disabled"))
    assert not monitor.submit({}, {}, now=NOW, shadow=True, manual=False, away=False, hygiene=False)
    assert monitor._thread is None


def test_blocked_worker_does_not_block_submit_and_only_latest_sample_waits():
    entered, release, latest = threading.Event(), threading.Event(), threading.Event()
    received = []
    def process(sample):
        received.append(sample)
        if len(received) == 1:
            entered.set()
            release.wait(5)
        if sample["now"] == NOW+2:
            latest.set()
    monitor = Monitor(process=process)
    house = {"heat_pump": {"enabled": True, "driver": "nibe_local", "connection": {"password": "secret"},
             "hot_water_shadow": {"enabled": True, "temperature_role_verified": True, "comfort_policy": dict(POLICY)}}}
    original = deepcopy(house)
    def submit(now):
        return monitor.submit(house, {"water_temp_observation": event()["observation"], "raw_secret": "secret"},
                              now=now, shadow=True, manual=False, away=False, hygiene=False)
    try:
        assert submit(NOW) and entered.wait(2)
        assert submit(NOW+1) and submit(NOW+2)
        assert monitor._queue.qsize() == 1
        release.set()
        assert latest.wait(2)
        assert [r["now"] for r in received] == [NOW, NOW+2]
        assert "secret" not in json.dumps(received) and house == original
    finally:
        release.set()


def test_status_expiry_and_strict_decoding():
    report = Evaluator(sink=lambda r: None).process(event(enabled=False))
    raw = json.dumps(report)
    assert decode(raw, NOW+90)["fresh"]
    assert not decode(raw, NOW+91)["fresh"] and not decode(raw, NOW-1)["fresh"]
    for key, bad in [("schema", True), ("control_ready", True), ("reservation_applied", True), ("reported_at", float("nan"))]:
        assert not decode(json.dumps({**report, key: bad}), NOW)["fresh"]


def test_stored_price_intervals_and_publication_use_actual_pg(db, monkeypatch):
    import logger
    import nordpool
    @contextmanager
    def connection():
        yield db
    monkeypatch.setattr(logger, "get_db", connection)
    monkeypatch.setattr(nordpool, "full_buy_cost", lambda spot, at: spot+1)
    with db.transaction():
        db.execute("CREATE TEMP TABLE elpriser(time_start timestamptz,time_end timestamptz,sek_per_kwh numeric) ON COMMIT DROP")
        db.execute("CREATE TEMP TABLE overrides(device text PRIMARY KEY,mode text,updated_at timestamptz) ON COMMIT DROP")
        for i in range(3):
            db.execute("INSERT INTO elpriser VALUES (%s,%s,%s)", (T+timedelta(minutes=5*i), T+timedelta(minutes=5*(i+1)), i+1))
        db.execute("INSERT INTO elpriser VALUES (%s,%s,4)", (T+timedelta(minutes=30), T+timedelta(minutes=90)))
        result = stored_prices(NOW)
        assert len(result) == 5 and result[0]["buy"] == 3  # weighted 5-min coverage + tariff
        assert result[1]["t"] == (T+timedelta(minutes=30)).isoformat()  # missing quarter not filled
        assert result[1]["buy"] == 5
        report = Evaluator(sink=lambda r: None).process(event(enabled=False))
        publish(report)
        raw = db.execute("SELECT mode FROM overrides WHERE device='hot_water_shadow_status'").fetchone()[0]
        assert decode(raw, NOW)["state"] == "disabled"
        db.execute("INSERT INTO elpriser VALUES (%s,%s,4)", (T+timedelta(minutes=4), T+timedelta(minutes=6)))
        with pytest.raises(ValueError, match="Overlapping"):
            stored_prices(NOW)


def test_main_hook_only_submits_existing_signals():
    import ast
    source = (Path(__file__).resolve().parents[1] / "smartbox" / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    hooks = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and isinstance(n.func.value, ast.Name) and n.func.value.id == "_hot_water_monitor" and n.func.attr == "submit"]
    assert len(hooks) == 1
    assert [n.id for n in hooks[0].args] == ["house_cfg", "pump_data"]
