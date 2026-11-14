from datetime import datetime, timedelta, timezone
from itertools import product

import pytest

import battery_balance as B
from battery_plan import optimize, simulate


def modules(now, a=80, b=90):
    return {"a": {"soc_pct": a, "sample_at": now}, "b": {"soc_pct": b, "sample_at": now}}


def config(**kw):
    return B.settings({"balance": {"enabled": True, "confirm_minutes": 1, "hold_minutes": 15, **kw}})


def requested():
    state, status = B.observe({}, modules(100), config(), 100)
    assert status["state"] == "confirming"
    state, status = B.observe(state, modules(160), config(), 160)
    assert status["request"]
    return state


@pytest.mark.parametrize("samples", [{}, {"a": {"soc_pct": 20, "sample_at": 160}},
    modules(1), modules(160, float("nan")), modules(160, 101), modules(1000)])
def test_missing_invalid_stale_future_data_cannot_trigger(samples):
    _, status = B.observe({}, samples, config(), 160)
    assert not status["request"]
    assert status["state"] == "missing_data"


def test_opt_in_and_control_capability_gate():
    for cfg, permitted in [(B.settings({}), True), (config(), False)]:
        state, status = B.observe(requested(), modules(200), cfg, 200, permitted)
        assert not status["request"] and "request_until" not in state


def test_not_periodic_and_small_spread_does_not_trigger():
    state = {}
    for now in (100, 100000, 10000000):
        state, status = B.observe(state, modules(now, 80, 81), config(), now)
        assert not status["request"]


def test_request_deadline_does_not_slide_on_replanning():
    state = requested()
    deadline = state["request_until"]
    for now in (200, 1000, 2000):
        state, status = B.observe(state, modules(now), config(), now)
        assert state["request_until"] == deadline and status["request"]


def test_dwell_requires_all_modules_and_fresh_uninterrupted_samples():
    state = requested()
    state, _ = B.observe(state, modules(200, 100, 98), config(), 200)
    assert "hold_since" not in state
    state, _ = B.observe(state, modules(210, 100, 100), config(), 210)
    state, status = B.observe(state, modules(210, 100, 100), config(), 1110)
    assert status["state"] == "missing_data" and "completed_at" not in state
    assert "hold_since" not in state


def test_natural_full_charge_counts_and_unresolved_spread_is_latched():
    state = {}
    for now in range(100, 1001, 60):
        state, status = B.observe(state, modules(now, 100, 100), config(), now)
    assert status["state"] == "completed" and state["completed_at"] == 1000
    for now in (2000, 2000000, 2000060):
        state, status = B.observe(state, modules(now), config(), now)
        assert not status["request"]
    # A confirmed healthy spread rearms; a new sustained divergence may request.
    for now, a, b in [(2000100, 80, 80), (2000160, 80, 80), (2000200, 80, 90), (2000260, 80, 90)]:
        state, status = B.observe(state, modules(now, a, b), config(), now)
    assert status["request"]


def test_missing_known_module_never_looks_balanced():
    state = requested()
    _, status = B.observe(state, {"a": modules(200)["a"], "c": modules(200)["b"]}, config(), 200)
    assert status["state"] == "missing_data"


def slots(prices, solar=None):
    start = datetime(2026, 11, 13, tzinfo=timezone.utc)
    return [{"t": start + timedelta(minutes=i * 15), "buy": p, "sell": 0,
             "load_kw": 0, "solar_kw": (solar or [0] * len(prices))[i], "ev_kw": 0}
            for i, p in enumerate(prices)]


PARAMS = dict(soc0_kwh=1, capacity_kwh=2, reserve_kwh=0, max_kwh=1.5,
              charge_kw=2, discharge_kw=2, eff=1, step_kwh=0.5, switch_cost=0,
              terminal_pct=0, allowed=("charge", "hold", "auto"),
              balance_target_kwh=2, balance_hold_slots=1)


def test_maintenance_waits_for_cheapest_window_without_arbitrage():
    data = slots([5, 5, 1, 1, 2, 2])
    result = optimize(data, **PARAMS)
    assert [r["action"] for r in result["rows"][:2]] == ["auto", "auto"]
    assert result["rows"][3]["soc_kwh"] == 2
    assert result["rows"][4]["soc_kwh"] == 2  # full quarter after arrival
    assert result["rows"][4]["action"] == "hold"
    assert result["cost"] == 1
    assert not result["rows"][-1]["balance_ceiling"]


def test_solar_can_fulfil_maintenance_with_no_grid_charge():
    result = optimize(slots([2] * 6, [0, 2, 2, 0, 0, 0]), **PARAMS)
    assert result["cost"] == 0
    assert max(r["soc_kwh"] for r in result["rows"]) == 2


def test_maintenance_cost_matches_exhaustive_feasible_sequences():
    data = slots([3, 1, 2, 4])
    result = optimize(data, **PARAMS)
    costs = []
    for actions in product(PARAMS["allowed"], repeat=len(data)):
        cost, rows = simulate(data, 1, actions, 2, 0, 2, 2, 2, 1)
        if any(rows[i - 1]["soc_kwh"] == rows[i]["soc_kwh"] == 2 for i in range(1, len(rows))):
            costs.append(cost)
    assert result["cost"] == min(costs)


def test_maintenance_keeps_reversal_costs_and_daily_ceiling_after_completion():
    data = slots([0, 6, 0, 1, 4, 5])
    allowed = ("auto", "hold", "charge", "discharge")
    result = optimize(data, **dict(PARAMS, allowed=allowed, reversal_cost_sek=.2))
    costs = []
    for actions in product(allowed, repeat=len(data)):
        cost, rows = simulate(data, 1, actions, 2, 0, 2, 2, 2, 1)
        finished = next((i for i in range(1, len(rows)) if rows[i - 1]["soc_kwh"] == rows[i]["soc_kwh"] == 2), None)
        if finished is None or any(r["battery_kw"] > 0 and r["soc_kwh"] > 1.5 for r in rows[finished + 1:]):
            continue
        last = 0
        for row in rows:
            direction = 1 if row["battery_kw"] > 0 else -1 if row["battery_kw"] < 0 else 0
            cost += .2 if direction and last and direction != last else 0
            last = direction or last
        costs.append(cost)
    assert result["cost"] + result["reversal_cost_sek"] == pytest.approx(min(costs))


def test_completed_maintenance_restores_partial_charging_at_daily_ceiling():
    data = slots([0, 4, -2, 3, 3, 3, 3])
    for row in data:
        row["load_kw"] = 2
    result = optimize(data, **dict(PARAMS, soc0_kwh=2, max_kwh=1.6, step_kwh=.1,
                                  allowed=("auto", "hold", "charge", "discharge")))
    assert result["rows"][0]["balance_hold"]
    assert result["rows"][2]["action"] == "charge"
    assert result["rows"][2]["soc_kwh"] == pytest.approx(1.6)
    assert result["rows"][2]["battery_kw"] == pytest.approx(.4)


def test_impossible_horizon_or_deadline_returns_no_forced_plan():
    for data, deadline in [(slots([1, 1]), 0), (slots([1] * 8), 2)]:
        result = optimize(data, **dict(PARAMS, balance_deadline_slots=deadline))
        assert result["balance_feasible"] is False and not result["rows"]


def test_snapshot_replays_maintenance_requirement():
    import plan_snapshot
    data = slots([5, 5, 1, 1, 2, 2])
    result = optimize(data, **PARAMS)
    snapshot = plan_snapshot.build(data, PARAMS, result, data[0]["t"])
    assert plan_snapshot.replay(snapshot)["matches"]


def test_safety_and_cooperation_override_balance():
    from battery_control import decide
    state = {"soc": 90, "planned_action": "charge", "balance_target_soc": 100}
    cfg = {"control": "styr", "max_soc": 85}
    supported = {"auto", "charge", "hold", "discharge"}
    assert decide(state, cfg, supported)["rule"] == "balance"
    for extra, rule in [({"meter_fresh": False}, "stale"), ({"fuse_state": "trip"}, "fuse"),
                        ({"peak_reached": True, "avg_net_w": 2000}, "peak")]:
        assert decide(dict(state, **extra), cfg, supported)["rule"] == rule
    assert decide(state, dict(cfg, control="samarbete"), supported)["intent"] is None
    assert decide(dict(state, soc=100), cfg, supported)["intent"] == "hold"
    assert decide({**state, "balance_target_soc": None}, cfg, supported)["intent"] == "hold"
    assert decide(dict(state, planned_action="hold", balance_hold_now=True, soc=99), cfg, supported)["intent"] == "charge"
    assert decide(dict(state, planned_action="hold", balance_hold_now=False, soc=99), cfg, supported)["intent"] == "hold"


def test_plan_clock_and_timeline_identify_balancing():
    from plan_clock import build
    from plan_brief import battery_items
    now = datetime(2026, 11, 13, tzinfo=timezone.utc)
    rows = [(now, "charge", 100, 1, 2, 2, True)]
    assert build(now, [(now, 1)], bat_rows=rows)["slots"][0]["bat_balance"]
    assert battery_items(rows, now)[0]["title"] == "🔋 Batteriet balanseras"


def test_ha_mapping_is_brand_independent_and_keeps_source_age(monkeypatch):
    import homeassistant
    now = datetime(2026, 11, 13, tzinfo=timezone.utc)
    monkeypatch.setattr(homeassistant, "_states_cache", {
        "sensor.bank_a": {"state": "80", "last_updated": now.isoformat()},
        "sensor.bank_b": {"state": "90", "last_updated": now.isoformat()},
    })
    samples = B.ha_modules(["sensor.bank_a", "sensor.bank_b"])
    assert samples["sensor.bank_a"]["sample_at"] == now.timestamp()
    _, status = B.observe({}, samples, config(), now.timestamp() + 121)
    assert status["state"] == "missing_data"


def test_restart_keeps_request_but_resets_unproven_dwell(tmp_path, monkeypatch):
    import ew_settings
    monkeypatch.setattr(ew_settings, "PATH", str(tmp_path / "settings.json"))
    state = requested()
    state["hold_since"] = 100
    ew_settings.update(battery_balance_state=state)
    monitor = B.Monitor()
    assert "hold_since" not in monitor.saved
    assert monitor.saved["request_until"] == state["request_until"]


def test_storage_failure_suspends_maintenance_without_raising(monkeypatch):
    import ew_settings
    monkeypatch.setattr(ew_settings, "get", lambda *args: {})
    def fail(**values):
        raise OSError("read-only storage")
    monkeypatch.setattr(ew_settings, "update", fail)
    status = B.Monitor().update({"modules": modules(100)}, config(), 100, True)
    assert status == {"request": False, "state": "storage_error"}


def test_started_maintenance_is_not_cancelled_by_spread_closing_early():
    state = requested()
    for now in (200, 260):
        state, status = B.observe(state, modules(now, 95, 95), config(), now, active=True)
    assert status["request"] and state["started"]
    assert "completed_at" not in state


def test_failed_attempt_is_bounded_and_does_not_loop():
    state = requested()
    end = state["request_until"]
    state, status = B.observe(state, modules(end), config(), end, active=True)
    assert status["state"] == "timeout" and not status["request"]
    assert "request_until" not in state and "completed_at" not in state
    for now in (end + 60, end + 1000000, end + 1000060):
        state, status = B.observe(state, modules(now), config(), now)
        assert not status["request"]


def test_display_distinguishes_schedule_active_pause_and_defer():
    status = {"request": True, "state": "requested"}
    assert B.display(status, {"balance_now": False}) == B.MESSAGES["requested"]
    assert B.display(status) == B.MESSAGES["deferred"]
    plan = {"balance_now": True}
    decision = {"rule": "balance", "intent": "charge"}
    assert B.display(status, plan, decision, {"intent": "charge"}) == B.MESSAGES["active"]
    assert B.display(status, plan, {"rule": "fuse", "intent": "discharge"}) == B.MESSAGES["paused"]
    assert B.display(status, {"balance_deferred": True}) == B.MESSAGES["deferred"]


@pytest.mark.parametrize("language", ["en", "cs"])
def test_balancing_messages_and_labels_are_translated(language):
    from i18n_py import tr
    from control_alerts import build
    import json
    for message in (*B.MESSAGES.values(), "Balansering", "🔋 Batteriet balanseras",
                    "Batteriet har nått laddtaket - laddningen pausas.",
                    "Planen: balansering efter uppmätt skillnad mellan batterimodulerna."):
        assert tr(message, language) != message
    card = build({"battery_balance": json.dumps({"text": B.MESSAGES["active"]})})[0]
    assert card["title"] == "Balansering" and card["level"] == "info"


def test_ferroamp_real_lua_exposes_source_dated_esos_and_explicit_maintenance(monkeypatch):
    import json
    from pathlib import Path
    from lua_host import LuaDriver, FTW_DIR
    writes = []
    monkeypatch.setattr(LuaDriver, "_mqtt_subscribe", lambda *args: True)
    monkeypatch.setattr(LuaDriver, "_mqtt_publish", lambda self, topic, body: writes.append(json.loads(body)) or True)
    driver = LuaDriver(str(Path(FTW_DIR) / "ferroamp.lua"), allow_write=True, log=lambda *args: None)
    host = driver.L.globals().host
    tick = [10000]
    host.millis = lambda: tick[0]
    host.unix_ms = lambda: 1000000 + tick[0]
    packets = [{"topic": "extapi/data/eso", "payload": json.dumps({"id": {"val": name},
               "soc": {"val": soc}, "ubat": {"val": 50}, "ibat": {"val": 0}})}
               for name, soc in (("a", .97), ("b", .99))]
    host.mqtt_messages = lambda: driver.L.table_from(packets, recursive=True)
    emitted, _ = driver.poll()
    samples = emitted["battery"]["modules"]
    assert samples["a"] == {"soc_pct": 97, "sample_at": 1010}
    assert samples["b"]["soc_pct"] == 99
    packets.clear()
    tick[0] += 10000
    emitted, _ = driver.poll()
    assert emitted["battery"]["modules"]["a"]["sample_at"] == 1010  # poll is not a new source sample
    writes.clear()
    driver.command("battery", 1000)
    assert writes[-1]["cmd"] == {"name": "discharge", "arg": 0}  # existing forced-idle command
    driver.command("battery", 1000, {"balance": True})
    assert writes[-1]["cmd"] == {"name": "charge", "arg": 1000}
    tick[0] += 31000
    emitted, _ = driver.poll()
    # LuaDriver retains its last emission, but its absolute source dates stay old.
    _, status = B.observe({}, emitted["battery"]["modules"], config(), 1200)
    assert status["state"] == "missing_data"


def test_postgres_persists_maintenance_flags_and_defers_impossible_plan(db, monkeypatch, tmp_path):
    import battery_plan
    import ew_settings
    import ha_solar_forecast
    import learning
    import nordpool
    import plan_snapshot
    import weather
    from sqlalchemy import create_engine
    from plan_brief import load_battery_rows
    monkeypatch.setattr(ew_settings, "PATH", str(tmp_path / "settings.json"))
    monkeypatch.setattr(plan_snapshot, "capture", lambda *args, **kwargs: None)
    monkeypatch.setattr(learning, "predict_base_load", lambda *args: 0)
    monkeypatch.setattr(ha_solar_forecast, "power_at", lambda *args: None)
    monkeypatch.setattr(weather, "get_weather_at", lambda *args: (0, 0, 0, 0))
    monkeypatch.setattr(weather, "get_smart_solar_w", lambda *args, **kw: 0)
    monkeypatch.setattr(nordpool, "full_buy_cost", lambda price, at: price)
    monkeypatch.setattr(nordpool, "full_sell_income", lambda price: 0)
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    now = now.replace(minute=now.minute // 15 * 15)
    db.execute("TRUNCATE elpriser")
    for i, price in enumerate([5, 5, 1, 1, 2, 2]):
        db.execute("INSERT INTO elpriser VALUES (%s, %s)", (now + timedelta(minutes=i * 15), price))
    engine = create_engine("postgresql+psycopg://postgres:test@localhost/smartbox_test")
    settings = {"capacity_kwh": 2, "reserve_soc": 0, "max_soc": 75, "max_power_w": 2000,
                "efficiency": 1, "cycle_cost": 0,
                "balance_request": {"request": True, "target_soc": 100, "hold_slots": 1, "deadline_slots": 6}}
    try:
        result = battery_plan.plan_from_db(engine, now, 50, settings, {}, {"auto", "charge", "hold"},
            soc_evidence={"soc_pct": 50, "soc_sample_at": now.timestamp() - 30, "soc_source": "ha_reported"})
        assert result["input_quality"]["soc"] == {"source": "ha_reported", "known": True, "age_s": 30}
        assert not result["balance_deferred"]
        with engine.connect() as conn:
            saved = load_battery_rows(conn)
        assert len(saved) == 6 and any(row[6] for row in saved)
        assert max(float(row[2]) for row in saved) == 100
        settings["balance_request"]["hold_slots"] = 8
        result = battery_plan.plan_from_db(engine, now, 50, settings, {}, {"auto", "charge", "hold"})
        assert result["balance_deferred"] and not result["balance_now"]
        with engine.connect() as conn:
            saved = load_battery_rows(conn)
        assert not any(row[6] for row in saved)
        assert max(float(row[2]) for row in saved) <= 75
        settings["balance_request"]["hold_slots"] = 1
        db.execute("DELETE FROM elpriser WHERE time_start = %s", (now + timedelta(minutes=15),))
        result = battery_plan.plan_from_db(engine, now, 50, settings, {}, {"auto", "charge", "hold"})
        assert result["balance_deferred"]  # no guessed price across a gap
    finally:
        engine.dispose()
