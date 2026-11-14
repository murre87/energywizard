"""Frozen-input handover replay; no runtime, network, driver or actuator I/O."""
from copy import deepcopy
from datetime import datetime
import hashlib
import json

from hot_water_observation import assess
from hot_water_plan import propose, reserve_load


def _epoch(value):
    stamp = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(stamp, datetime) or stamp.utcoffset() is None:
        raise ValueError("Replay request clock requires a UTC offset")
    return stamp.timestamp()


def _remaining(proposal, state, forecast, contract, now):
    """Rebuild from the original residual baseline, never from a prior result."""
    phase = state.get("phase")
    if phase not in ("planned", "active", "complete", "cancelled"):
        return None, None
    start, end = _epoch(proposal["start"]), _epoch(proposal["end"])
    if phase in ("complete", "cancelled"):
        start = end
    else:
        start = max(start, now)
        if phase == "active":
            end = min(end, state["started_at"] + state["max_runtime_s"])
    # The proposal has constant electrical power. Recover that power from
    # total energy/duration, then conserve only the remaining overlap.
    power = proposal["energy_kwh"] / ((_epoch(proposal["end"]) - _epoch(proposal["start"])) / 3600)
    quarters = []
    for row in proposal["quarters"]:
        t = _epoch(row["t"])
        seconds = max(0, min(end, t + 900) - max(start, t))
        if seconds:
            quarters.append({"t": row["t"], "hot_water_kw": power * seconds / 900})
    remaining = {**proposal, "quarters": quarters}
    reserved = reserve_load(forecast, remaining, baseline_contract=contract)
    return reserved, sum(r["hot_water_kw"] * .25 for r in quarters)


def evaluate(data, cycle):
    """Replay either an explicit request or an explicit anchored comfort policy."""
    if "comfort_policy" not in data:
        return _evaluate(data, cycle)
    from hot_water_demand import derive
    if "request" in data:
        raise ValueError("Supply a request or comfort policy, not both")
    if data.get("temperature_role_verified") is not True:
        raise ValueError("Explicit temperature-role qualification required")
    comfort, lifecycle = data["comfort_policy"], data["policy"]
    for key in ("target_c", "max_age_s", "allow_receipt"):
        if comfort[key] != lifecycle.get(key, False if key == "allow_receipt" else None):
            raise ValueError("Comfort and lifecycle evidence policies must match")
    if lifecycle["local_rest_enabled"] and lifecycle["transport"] != "nibe_local":
        raise ValueError("Enabled local REST must remain preferred")
    saved, demand = derive(data.get("demand_state", {}), data["observation"], now=data["now"],
                           policy=comfort, last_trigger_at=data.get("last_trigger_at"))
    if demand["request"] is None:
        return {"simulation_only": True, "control_ready": False, "state": demand["state"],
                "demand": demand, "demand_state": saved, "forecast": None, "frames": []}
    result = _evaluate({**data, "request": demand["request"]}, cycle)
    return {**result, "demand": demand, "demand_state": saved}


def _evaluate(data, cycle):
    """Compose proposal, simulated lifecycle and residual-load reservation.

    `cycle` is a ShadowCycle with caller-owned simulation storage. Every
    acknowledgement is an explicit replay input, never inferred from a tick.
    """
    request, policy = data["request"], data["policy"]
    forecast, contract = data["forecast"], data["baseline_contract"]
    events = data.get("events", [])
    if len(forecast) > 144 or len(events) > 256:
        raise ValueError("Replay limited to 144 forecast quarters and 256 events")
    if contract != "hot_water_excluded":
        raise ValueError("Explicit hot-water-excluded baseline required")
    # The evidence field describes the configured sensor, not automatically
    # a tank-top binding suitable for a specific heater's stop condition.
    if data.get("temperature_role_verified") is not True:
        raise ValueError("Explicit temperature-role qualification required")
    now = _epoch(request["now"])
    if request["duration_min"] * 60 > policy["max_runtime_s"]:
        raise ValueError("Heating duration exceeds cycle runtime bound")
    # Validate transport preference even when no complete price window exists.
    if policy["local_rest_enabled"] and policy["transport"] != "nibe_local":
        raise ValueError("Enabled local REST must remain preferred")
    evidence = assess(data["observation"], now=now, max_age_s=policy["max_age_s"],
                      allow_receipt=policy.get("allow_receipt", False))
    if evidence["state"] != "fresh":
        return {"simulation_only": True, "control_ready": False, "state": "observation_unavailable",
                "evidence": evidence, "forecast": None, "frames": []}
    proposal = propose(data["prices"], **request)
    if proposal["state"] != "proposed":
        return {"simulation_only": True, "control_ready": False, "state": "schedule_unavailable",
                "proposal": proposal, "forecast": None, "frames": []}
    # Validate complete coverage and reject already-reserved input before
    # touching the simulation journal. Every frame then starts from this copy.
    baseline = deepcopy(forecast)
    reserve_load(baseline, proposal, baseline_contract=contract)
    context = json.dumps({"proposal": proposal, "policy": policy, "forecast": baseline},
                         sort_keys=True, allow_nan=False, default=lambda v: v.isoformat())
    context_id = hashlib.sha256(context.encode()).hexdigest()
    status = cycle.arm(proposal, now=now, context_id=context_id, **policy)
    reserved, energy = _remaining(proposal, cycle.state, baseline, contract, now) if not cycle.storage_error else (None, None)
    frames = [{**status, "remaining_energy_kwh": energy}]
    for event in events:
        inputs = event["inputs"]
        if inputs["now"] < now:
            raise ValueError("Replay events must be chronological")
        now = inputs["now"]
        if event["kind"] == "tick":
            status = cycle.tick(**inputs)
        elif event["kind"] == "acknowledge":
            status = cycle.acknowledge(cycle.state.get("token"), **inputs)
        else:
            raise ValueError("Unknown replay event kind")
        reserved, energy = _remaining(proposal, cycle.state, baseline, contract, now) if not cycle.storage_error else (None, None)
        frames.append({**status, "remaining_energy_kwh": energy})
    return {"simulation_only": True, "control_ready": False, "state": status["state"],
            "proposal": proposal, "frames": frames, "forecast": reserved,
            "reservation_available": reserved is not None}
