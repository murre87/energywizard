"""Explicit comfort/trigger-age policy for frozen hot-water qualification inputs."""
from datetime import datetime, timezone
import hashlib
import json
from math import isfinite

from hot_water_observation import assess

FIELDS = {"comfort_c", "target_c", "max_trigger_age_s", "min_trigger_interval_s",
          "comfort_window_s", "comfort_bypasses_interval", "duration_min",
          "electrical_power_kw", "max_age_s", "allow_receipt"}
STATE_FIELDS = {"schema", "policy_hash", "anchor_at", "last_at", "last_trigger_at", "comfort_since"}


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value < 0:
        raise ValueError("Finite nonnegative policy/time value required")
    return float(value)


def derive(saved, observation, *, now, policy, last_trigger_at=None):
    """Return (new state, advisory demand) without writes or inferred trigger success.

    last_trigger_at is externally supplied actual accepted-command history,
    never a simulated acknowledgement or proof of heating/hygiene completion.
    Preserve returned state across evaluations to keep missing-history and comfort
    anchors fixed. Changed policy requires a new explicit qualification scenario.
    """
    now = _number(now)
    if set(policy) != FIELDS:
        raise ValueError("Complete explicit comfort policy required")
    numeric = {k: _number(v) for k, v in policy.items()
               if k not in ("allow_receipt", "comfort_bypasses_interval")}
    duration = numeric["duration_min"] * 60
    if (type(policy["allow_receipt"]) is not bool or type(policy["comfort_bypasses_interval"]) is not bool
            or not 0 < numeric["comfort_c"] < numeric["target_c"] <= 65
            or not 60 <= duration <= 21600 or numeric["electrical_power_kw"] <= 0
            or not duration <= numeric["max_trigger_age_s"] <= 36 * 3600
            or not duration <= numeric["comfort_window_s"] <= 36 * 3600
            or numeric["min_trigger_interval_s"] > numeric["max_trigger_age_s"]
            or numeric["max_age_s"] <= 0):
        raise ValueError("Invalid comfort policy bounds")
    fingerprint = hashlib.sha256(json.dumps(policy, sort_keys=True, allow_nan=False).encode()).hexdigest()
    if not isinstance(saved, dict) or set(saved) - STATE_FIELDS:
        raise ValueError("Invalid demand state")
    state = dict(saved)
    if state:
        if (type(state.get("schema")) is not int or state["schema"] != 1
                or not {"policy_hash", "anchor_at", "last_at"} <= state.keys()
                or not isinstance(state["policy_hash"], str)):
            raise ValueError("Invalid demand schema")
        for key in ("anchor_at", "last_at", "last_trigger_at", "comfort_since"):
            if key in state:
                _number(state[key])
        if state["anchor_at"] > state["last_at"] or any(state.get(k, 0) > state["last_at"] for k in ("last_trigger_at", "comfort_since")):
            raise ValueError("Inconsistent demand times")
        if "last_trigger_at" in state and state["anchor_at"] != state["last_trigger_at"]:
            raise ValueError("Trigger anchor does not match history")
        if state["policy_hash"] != fingerprint:
            return state, {"state": "policy_changed", "request": None}
        if now < state["last_at"]:
            return state, {"state": "clock_moved_backwards", "request": None}
    if last_trigger_at is not None:
        last_trigger_at = _number(last_trigger_at)
        if last_trigger_at > now:
            raise ValueError("Trigger history cannot be in the future")
    evidence = assess(observation, now=now, max_age_s=policy["max_age_s"], allow_receipt=policy["allow_receipt"])
    if evidence["state"] != "fresh":
        return state, {"state": "observation_unavailable", "evidence": evidence, "request": None}
    if not state:
        state = {"schema": 1, "policy_hash": fingerprint, "anchor_at": now, "last_at": now}
    state["last_at"] = now
    if last_trigger_at is not None and ("last_trigger_at" not in state or last_trigger_at > state["last_trigger_at"]):
        state.update(last_trigger_at=last_trigger_at, anchor_at=last_trigger_at)
        state.pop("comfort_since", None)
    if observation["value_c"] >= policy["target_c"]:
        state.pop("comfort_since", None)
        return state, {"state": "target_already_observed", "request": None}
    comfort = observation["value_c"] <= policy["comfort_c"]
    if comfort:
        state.setdefault("comfort_since", now)
    else:
        state.pop("comfort_since", None)
    deadline = state["anchor_at"] + policy["max_trigger_age_s"]
    if comfort:
        deadline = min(deadline, state["comfort_since"] + policy["comfort_window_s"])
    earliest = now
    if "last_trigger_at" in state and not (comfort and policy["comfort_bypasses_interval"]):
        earliest = max(earliest, state["last_trigger_at"] + policy["min_trigger_interval_s"])
    if earliest + duration > deadline:
        return state, {"state": "deadline_missed" if now + duration > deadline else "interval_conflict",
                       "deadline": deadline, "request": None}
    iso = lambda value: datetime.fromtimestamp(value, timezone.utc).isoformat()
    return state, {"state": "comfort_due" if comfort else "age_window", "deadline": deadline,
                   "history_known": "last_trigger_at" in state,
                   "request": {"now": iso(now), "earliest": iso(earliest), "deadline": iso(deadline),
                               "duration_min": policy["duration_min"], "electrical_power_kw": policy["electrical_power_kw"]}}
