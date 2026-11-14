"""Anchored advisory deadlines, with explicit policy and synthetic history only."""
from copy import deepcopy
from datetime import datetime, timezone

import pytest
from hot_water_demand import derive
from hot_water_observation import temperature

T = datetime(2026, 11, 14, 10, tzinfo=timezone.utc).timestamp()


def observation(now=T, value=52):
    return temperature(value, datetime.fromtimestamp(now, timezone.utc).isoformat(), "local_receipt")


@pytest.fixture
def policy():
    return {"comfort_c": 50, "target_c": 55, "max_trigger_age_s": 7200,
            "min_trigger_interval_s": 3600, "comfort_window_s": 1800,
            "comfort_bypasses_interval": True, "duration_min": 15,
            "electrical_power_kw": 2, "max_age_s": 90, "allow_receipt": True}


def test_missing_history_anchor_never_rolls_forward(policy):
    state, first = derive({}, observation(), now=T, policy=policy)
    original = deepcopy(state)
    updated, second = derive(state, observation(T+600), now=T+600, policy=policy)
    assert first["deadline"] == second["deadline"] == T+7200
    assert not second["history_known"] and state == original
    assert updated["anchor_at"] == T


def test_comfort_lookahead_is_anchored_to_first_cold_observation(policy):
    state, _ = derive({}, observation(), now=T, policy=policy)
    state, first = derive(state, observation(T+600, 49), now=T+600, policy=policy)
    _, second = derive(state, observation(T+900, 49), now=T+900, policy=policy)
    assert first["state"] == "comfort_due"
    assert first["deadline"] == second["deadline"] == T+2400


def test_accepted_trigger_history_spacing_and_new_history(policy):
    state, first = derive({}, observation(), now=T, policy=policy, last_trigger_at=T-300)
    assert datetime.fromisoformat(first["request"]["earliest"]).timestamp() == T+3300
    assert first["deadline"] == T+6900 and first["history_known"]
    state, changed = derive(state, observation(T+60), now=T+60, policy=policy, last_trigger_at=T+30)
    assert changed["deadline"] == T+7230
    _, same = derive(state, observation(T+120), now=T+120, policy=policy, last_trigger_at=T+30)
    assert same["deadline"] == changed["deadline"]


def test_comfort_can_explicitly_bypass_spacing_and_conflicts_do_not_force_heat(policy):
    _, bypass = derive({}, observation(value=49), now=T, policy=policy, last_trigger_at=T-300)
    assert datetime.fromisoformat(bypass["request"]["earliest"]).timestamp() == T
    policy["comfort_bypasses_interval"] = False
    _, blocked = derive({}, observation(value=49), now=T, policy=policy, last_trigger_at=T-300)
    assert blocked["state"] == "interval_conflict" and blocked["request"] is None


def test_overdue_history_is_reported_not_replaced_by_now_plus_duration(policy):
    _, result = derive({}, observation(), now=T, policy=policy, last_trigger_at=T-8000)
    assert result["state"] == "deadline_missed" and result["deadline"] == T-800
    assert result["request"] is None


def test_warm_target_does_not_invent_trigger_history_or_cycle_completion(policy):
    state, result = derive({}, observation(value=56), now=T, policy=policy)
    assert result["state"] == "target_already_observed"
    assert "last_trigger_at" not in state and result["request"] is None


def test_policy_change_and_clock_rollback_do_not_reinterpret_history(policy):
    state, _ = derive({}, observation(), now=T, policy=policy)
    assert derive(state, observation(T-1), now=T-1, policy=policy)[1]["state"] == "clock_moved_backwards"
    policy["target_c"] = 60
    assert derive(state, observation(), now=T, policy=policy)[1]["state"] == "policy_changed"


def test_missing_stale_or_unaccepted_receipt_does_not_create_anchor(policy):
    policy["allow_receipt"] = False
    state, result = derive({}, observation(), now=T, policy=policy)
    assert not state and result["state"] == "observation_unavailable"
    policy["allow_receipt"] = True
    assert not derive({}, observation(), now=T+91, policy=policy)[0]


@pytest.mark.parametrize("change", [{"comfort_c": 56}, {"target_c": 66}, {"duration_min": True},
                                    {"max_trigger_age_s": 1}, {"min_trigger_interval_s": 8000},
                                    {"comfort_window_s": 0}, {"electrical_power_kw": float("nan")},
                                    {"allow_receipt": "true"}])
def test_invalid_policy_rejected(policy, change):
    policy.update(change)
    with pytest.raises(ValueError):
        derive({}, observation(), now=T, policy=policy)


def test_future_history_and_malformed_state_rejected(policy):
    with pytest.raises(ValueError):
        derive({}, observation(), now=T, policy=policy, last_trigger_at=T+1)
    with pytest.raises(ValueError):
        derive({"schema": 1}, observation(), now=T, policy=policy)


def test_composed_replay_chooses_cheaper_comfort_window_and_preserves_local_preference(policy):
    from datetime import timedelta
    from hot_water_cycle import ShadowCycle
    from hot_water_shadow import evaluate
    at = datetime.fromtimestamp(T, timezone.utc)
    rows = [{"t": (at+timedelta(minutes=15*i)).isoformat(), "buy": price, "load_kw": .5}
            for i, price in enumerate([5, 1, 3, 3])]
    data = {"now": T, "comfort_policy": policy, "demand_state": {}, "observation": observation(value=49),
            "temperature_role_verified": True, "baseline_contract": "hot_water_excluded",
            "forecast": rows, "prices": [{"t": r["t"], "buy": r["buy"]} for r in rows],
            "policy": {"target_c": 55, "max_runtime_s": 1800, "max_age_s": 90,
                       "transport": "nibe_local", "local_rest_enabled": True, "allow_receipt": True}}
    result = evaluate(data, ShadowCycle(lambda: {}, lambda s: None))
    assert result["demand"]["state"] == "comfort_due"
    assert datetime.fromisoformat(result["proposal"]["start"]).timestamp() == T+900
    assert result["proposal"]["energy_kwh"] == .5 and not result["control_ready"]
    data["policy"]["transport"] = "myuplink"
    with pytest.raises(ValueError, match="local REST"):
        evaluate(data, ShadowCycle(lambda: {}, lambda s: None))
