"""Simulated lifecycle, durable state and failure boundaries; no device transports."""
from copy import deepcopy
from datetime import datetime, timezone
import json

import pytest
from hot_water_cycle import ShadowCycle, open_journal
from hot_water_observation import temperature

T = datetime(2026, 11, 14, 10, tzinfo=timezone.utc).timestamp()


def iso(stamp):
    return datetime.fromtimestamp(stamp, timezone.utc).isoformat()


def observation(at=T, value=45, basis="local_receipt"):
    return temperature(value, iso(at), basis)


def arm(cycle, **changes):
    return cycle.arm({"state": "proposed", "start": iso(T), "end": iso(T+1800), "deadline": iso(T+3600)},
                     **{**dict(now=T-60, target_c=55, max_runtime_s=1200, max_age_s=90,
                               transport="nibe_local", local_rest_enabled=True, allow_receipt=True), **changes})


def tick(cycle, **changes):
    return cycle.tick(**{**dict(observation=observation(), now=T, shadow=True, permitted=True), **changes})


@pytest.fixture
def cycle():
    saved = []
    obj = ShadowCycle(lambda: {}, lambda state: saved.append(deepcopy(state)))
    obj.saved = saved
    arm(obj)
    return obj


def start(cycle):
    status = tick(cycle)
    assert status["action"] == "would_start"
    # Persistence precedes returning the only simulated start proposal.
    assert cycle.saved[-1]["phase"] == "start_pending"
    return cycle.acknowledge(status["token"], outcome="accepted", now=T)


def test_start_target_and_release_acknowledgement(cycle):
    assert start(cycle)["state"] == "active"
    assert tick(cycle, observation=observation(T, 56))["action"] is None  # pre-send sample
    stop = tick(cycle, now=T+10, observation=observation(T+10, 56))
    assert stop["action"] == "would_release" and stop["reason"] == "target_observed"
    assert tick(cycle, now=T+11)["action"] is None  # no cleanup replay
    done = cycle.acknowledge(stop["token"], outcome="accepted", now=T+12)
    assert done["state"] == "complete" and not done["control_ready"]
    assert tick(cycle, now=T+20)["action"] is None


@pytest.mark.parametrize("outcome", ["rejected", "uncertain"])
def test_ambiguous_attempt_never_retried(cycle, outcome):
    pending = tick(cycle)
    assert tick(cycle, now=T+1)["action"] is None
    assert cycle.acknowledge("wrong-token", outcome="accepted", now=T+1)["state"] == "start_pending"
    assert cycle.acknowledge(pending["token"], outcome=outcome, now=T+2)["state"] == "unconfirmed"
    assert tick(cycle, now=T+3)["action"] is None


@pytest.mark.parametrize("changes,reason", [
    ({"cancel": True}, "cancelled"), ({"permitted": False}, "guard_lost"),
    ({"now": T+1200, "observation": observation(T+1200)}, "runtime_limit"),
    ({"now": T+100}, "freshness_lost"),
])
def test_active_stop_reasons_are_not_success(cycle, changes, reason):
    start(cycle)
    result = tick(cycle, **changes)
    assert result["action"] == "would_release" and result["reason"] == reason
    ack = cycle.acknowledge(result["token"], outcome="accepted", now=changes.get("now", T))
    assert ack["state"] == "cancelled"


@pytest.mark.parametrize("guard", ["manual", "away", "hygiene"])
def test_precedence_removes_simulated_authority_without_cleaning_another_owner(cycle, guard):
    start(cycle)
    result = tick(cycle, **{guard: True})
    assert result["state"] == "interrupted" and result["action"] is None


def test_disabling_shadow_cannot_carry_simulated_action_into_real_control(cycle):
    pending = tick(cycle)
    assert tick(cycle, shadow=False)["state"] == "interrupted"
    assert cycle.acknowledge(pending["token"], outcome="accepted", now=T)["state"] == "interrupted"


def test_clock_rollback_pending_timeout_and_late_ack(cycle):
    pending = tick(cycle)
    result = cycle.acknowledge(pending["token"], outcome="accepted", now=T+60)
    assert result["state"] == "unconfirmed"
    other = ShadowCycle(lambda: {}, lambda s: None)
    arm(other)
    assert tick(other, now=T-61)["reason"] == "clock_moved_backwards"


def test_missed_start_does_not_extend_original_reservation(cycle):
    assert tick(cycle, permitted=False)["state"] == "planned"
    assert tick(cycle, now=T+1)["reason"] == "reserved_start_missed"


def test_receipt_policy_and_local_transport_preference_are_explicit():
    cycle = ShadowCycle(lambda: {}, lambda s: None)
    with pytest.raises(ValueError, match="local REST"):
        arm(cycle, transport="myuplink")
    arm(cycle, allow_receipt=False)
    assert tick(cycle)["action"] is None
    assert tick(cycle, observation=observation(basis="source"))["action"] == "would_start"


def test_storage_failure_prevents_proposal(cycle):
    def fail(state):
        raise OSError("disk unavailable")
    cycle._save = fail
    assert tick(cycle) == {"state": "storage_error", "action": None, "control_ready": False}
    assert tick(cycle)["action"] is None


@pytest.mark.parametrize("phase", ["planned", "start_pending", "active", "release_pending", "complete"])
def test_restart_never_restores_cycle_or_pending_token(tmp_path, phase):
    path = tmp_path / "private" / "cycle.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"schema": 1, "mode": "shadow", "phase": phase, "token": "old"}))
    restored = open_journal(path)
    result = tick(restored)
    assert result["state"] == "interrupted" and result["action"] is None
    assert "token" not in json.loads(path.read_text())
    assert restored.acknowledge("old", outcome="accepted", now=T)["action"] is None


def test_real_private_atomic_journal_and_no_config_data_persisted(tmp_path):
    path = tmp_path / "private" / "cycle.json"
    cycle = open_journal(path)
    arm(cycle)
    pending = tick(cycle)
    saved = json.loads(path.read_text())
    assert saved["token"] == pending["token"] and saved["mode"] == "shadow"
    assert set(saved) <= {"schema", "mode", "phase", "cycle_id", "start", "end", "deadline", "target_c",
                          "max_runtime_s", "max_age_s", "transport", "allow_receipt", "last_at",
                          "reason", "pending_at", "token"}
    assert not list(path.parent.glob(".hot-water-shadow-*"))


def test_corrupt_journal_fails_closed(tmp_path):
    path = tmp_path / "cycle.json"
    path.write_text("not-json")
    assert tick(open_journal(path))["state"] == "storage_error"


@pytest.mark.parametrize("saved", [None, [], False, 0, ""])
def test_non_object_journal_cannot_be_treated_as_new_cycle(saved):
    cycle = ShadowCycle(lambda: saved, lambda s: None)
    assert arm(cycle)["state"] == "storage_error"


def test_pending_expiry_does_not_repeat_action(cycle):
    tick(cycle)
    result = tick(cycle, now=T+60)
    assert result["state"] == "unconfirmed" and result["action"] is None


def test_release_ack_can_follow_original_window_end():
    cycle = ShadowCycle(lambda: {}, lambda s: None)
    arm(cycle, max_runtime_s=3600)
    action = tick(cycle)
    cycle.acknowledge(action["token"], outcome="accepted", now=T)
    stop = tick(cycle, now=T+1800, observation=observation(T+1800))
    assert stop["action"] == "would_release"
    assert cycle.acknowledge(stop["token"], outcome="accepted", now=T+1801)["state"] == "cancelled"


@pytest.mark.parametrize("changes", [{"target_c": 66}, {"max_runtime_s": 0},
                                    {"max_runtime_s": 21601}, {"max_age_s": -1},
                                    {"allow_receipt": "true"}, {"transport": "host-containing-token"}])
def test_invalid_policy_cannot_arm(changes):
    with pytest.raises(ValueError):
        arm(ShadowCycle(lambda: {}, lambda s: None), **changes)


def test_cli_replay_is_shadow_only_and_restart_cannot_repeat_start(tmp_path):
    from pathlib import Path
    import subprocess
    import sys
    source, journal = tmp_path / "replay.json", tmp_path / "cycle.json"
    source.write_text(json.dumps({
        "proposal": {"state": "proposed", "start": iso(T), "end": iso(T+1800), "deadline": iso(T+3600)},
        "policy": {"now": T-60, "target_c": 55, "max_runtime_s": 1200, "max_age_s": 90,
                   "transport": "nibe_local", "local_rest_enabled": True, "allow_receipt": True},
        "events": [{"kind": "tick", "inputs": {"now": T, "shadow": True, "permitted": True,
                                                 "observation": observation()}},
                   {"kind": "acknowledge", "inputs": {"now": T, "outcome": "accepted"}}]}))
    script = Path(__file__).resolve().parents[1] / "scripts" / "replay_hot_water_cycle.py"
    command = [sys.executable, str(script), str(source), "--journal", str(journal)]
    first = json.loads(subprocess.run(command, check=True, capture_output=True, text=True).stdout)
    assert first["simulation_only"] and first["events"][1]["action"] == "would_start"
    second = json.loads(subprocess.run(command, check=True, capture_output=True, text=True).stdout)
    assert all(r["action"] is None and r["state"] == "interrupted" for r in second["events"])
