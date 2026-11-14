"""Compose real scheduling, evidence, lifecycle and battery input accounting."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest
from hot_water_cycle import ShadowCycle, open_journal
from hot_water_observation import temperature
from hot_water_shadow import evaluate

T = datetime(2026, 11, 14, 10, tzinfo=timezone.utc)
EPOCH = T.timestamp()


def observation(seconds=0, value=45):
    return temperature(value, (T + timedelta(seconds=seconds)).isoformat(), "local_receipt")


def tick(seconds=0, value=45, **flags):
    return {"kind": "tick", "inputs": {"now": EPOCH+seconds, "shadow": True, "permitted": True,
                                         "observation": observation(seconds, value), **flags}}


def ack(seconds=0, outcome="accepted"):
    return {"kind": "acknowledge", "inputs": {"now": EPOCH+seconds, "outcome": outcome}}


@pytest.fixture
def data():
    rows = [{"t": (T + timedelta(minutes=15*i)).isoformat(), "buy": 1, "sell": 0,
             "load_kw": .5, "solar_kw": 0, "ev_kw": .3} for i in range(8)]
    return {"request": {"now": T.isoformat(), "earliest": T.isoformat(),
                        "deadline": (T+timedelta(hours=2)).isoformat(),
                        "duration_min": 30, "electrical_power_kw": 2},
            "prices": [{"t": r["t"], "buy": r["buy"]} for r in rows],
            "forecast": rows, "baseline_contract": "hot_water_excluded", "temperature_role_verified": True,
            "observation": observation(), "policy": {"target_c": 55, "max_runtime_s": 1800,
              "max_age_s": 90, "transport": "nibe_local", "local_rest_enabled": True, "allow_receipt": True},
            "events": []}


def cycle():
    return ShadowCycle(lambda: {}, lambda state: None)


def test_initial_reservation_matches_existing_battery_optimizer_without_input_mutation(data):
    from battery_plan import optimize
    original = deepcopy(data)
    result = evaluate(data, cycle())
    assert result["simulation_only"] and result["control_ready"] is False
    assert result["frames"][0]["remaining_energy_kwh"] == 1
    reserved = result["forecast"]
    assert reserved[0]["load_kw"] == 2.5 and reserved[0]["ev_kw"] == .3
    params = dict(soc0_kwh=0, capacity_kwh=2, reserve_kwh=0, max_kwh=2,
                  charge_kw=1, discharge_kw=1, allowed=("idle",), terminal_pct=0)
    assert optimize(reserved, **params)["cost"] - optimize(data["forecast"], **params)["cost"] == pytest.approx(1)
    assert data == original


def test_partial_quarter_remaining_load_and_repeated_replay_do_not_accumulate(data):
    data["events"] = [tick(), ack(), tick(300)]
    first = evaluate(data, cycle())
    second = evaluate(data, cycle())
    assert first["frames"][-1]["remaining_energy_kwh"] == pytest.approx(5/6)
    assert first["forecast"] == second["forecast"]
    assert first["forecast"][0]["hot_water_kw"] == pytest.approx(4/3)


def test_early_target_release_clears_future_reservation_after_explicit_ack(data):
    data["events"] = [tick(), ack(), tick(300, 56)]
    pending = evaluate(data, cycle())
    assert pending["frames"][-1]["action"] == "would_release"
    assert pending["forecast"] is None  # pending action is not assumed successful
    data["events"].append(ack(301))
    result = evaluate(data, cycle())
    assert result["state"] == "complete"
    assert all(r["hot_water_kw"] == 0 for r in result["forecast"])
    assert all(r["load_kw"] == .5 for r in result["forecast"])


@pytest.mark.parametrize("outcome", ["uncertain", "rejected"])
def test_ambiguous_start_does_not_fabricate_forecast_or_replay_action(data, outcome):
    data["events"] = [tick(), ack(outcome=outcome), tick(20)]
    result = evaluate(data, cycle())
    assert result["state"] == "unconfirmed" and result["forecast"] is None
    assert sum(f["action"] == "would_start" for f in result["frames"]) == 1


@pytest.mark.parametrize("flag", ["manual", "away", "hygiene"])
def test_precedence_removes_reservation_authority(data, flag):
    data["events"] = [tick(), ack(), tick(10, **{flag: True})]
    result = evaluate(data, cycle())
    assert result["state"] == "interrupted" and result["forecast"] is None


def test_restart_and_context_change_cannot_reuse_original_reservation(data, tmp_path):
    path = tmp_path / "cycle.json"
    assert evaluate(data, open_journal(path))["reservation_available"]
    resumed = evaluate(data, open_journal(path))
    assert resumed["state"] == "interrupted" and resumed["forecast"] is None
    obj = cycle()
    evaluate(data, obj)
    data["request"]["electrical_power_kw"] = 3
    changed = evaluate(data, obj)
    assert changed["state"] == "interrupted"
    assert changed["frames"][0]["reason"] == "plan_context_changed"
    assert changed["forecast"] is None


def test_completed_cycle_cannot_claim_a_changed_request_is_complete(data):
    obj = cycle()
    data["events"] = [tick(), ack(), tick(20, 56), ack(21)]
    assert evaluate(data, obj)["state"] == "complete"
    data["events"] = []
    data["policy"]["target_c"] = 60
    assert evaluate(data, obj)["state"] == "interrupted"


@pytest.mark.parametrize("field,value", [("baseline_contract", "whole_house"), ("temperature_role_verified", False)])
def test_qualification_gates_precede_journal_changes(data, field, value):
    obj = cycle()
    data[field] = value
    with pytest.raises(ValueError):
        evaluate(data, obj)
    assert obj.state == {}


def test_local_rest_is_preferred_even_when_price_or_evidence_missing(data):
    data["policy"]["transport"] = "myuplink"
    data["prices"] = []
    with pytest.raises(ValueError, match="local REST"):
        evaluate(data, cycle())


def test_initial_unknown_or_receipt_not_accepted_does_not_schedule(data):
    data["policy"]["allow_receipt"] = False
    obj = cycle()
    result = evaluate(data, obj)
    assert result["state"] == "observation_unavailable" and obj.state == {}


def test_missing_prices_no_schedule_and_reserved_baseline_rejected(data):
    data["prices"] = []
    assert evaluate(data, cycle())["state"] == "schedule_unavailable"
    data["prices"] = [{"t": r["t"], "buy": 1} for r in data["forecast"]]
    data["forecast"][0]["hot_water_kw"] = 0
    with pytest.raises(ValueError, match="reservation"):
        evaluate(data, cycle())


def test_duration_must_fit_runtime_and_events_must_be_chronological(data):
    data["policy"]["max_runtime_s"] = 600
    with pytest.raises(ValueError, match="runtime"):
        evaluate(data, cycle())
    data["policy"]["max_runtime_s"] = 1800
    data["events"] = [tick(1), tick()]
    with pytest.raises(ValueError, match="chronological"):
        evaluate(data, cycle())


def test_cli_combines_all_components_without_device_calls(data, tmp_path):
    import subprocess
    import sys
    from pathlib import Path
    source, journal = tmp_path / "request.json", tmp_path / "journal.json"
    source.write_text(json.dumps(data))
    script = Path(__file__).resolve().parents[1] / "scripts" / "evaluate_hot_water_shadow.py"
    result = subprocess.run([sys.executable, str(script), str(source), "--journal", str(journal)],
                            check=True, capture_output=True, text=True)
    output = json.loads(result.stdout)
    assert output["simulation_only"] and output["reservation_available"]
    assert json.loads(journal.read_text())["context_id"]
