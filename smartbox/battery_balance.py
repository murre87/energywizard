"""Demand-triggered battery maintenance. No periodic cycles or device writes.

Module SOC is percentage points with a source timestamp, never a cache-read time.
The spread is a configurable heuristic, not a manufacturer BMS diagnosis.
"""
import math

MESSAGES = {
    "unsupported": "Balansering kräver batteristyrning, dygnsplan och stöd för laddning och hålläge.",
    "missing_data": "Balansering väntar på färska laddnivåer från minst två batterimoduler.",
    "storage_error": "Balansering är pausad eftersom underhållsstatus inte kunde sparas. Vanlig batteriplanering fortsätter.",
    "confirming": "Skillnad mellan batterimodulerna upptäckt - inväntar bekräftelse.",
    "requested": "Balansering behövs - planeras efter elpris och solprognos.",
    "active": "Balansering pågår: batteriet laddas eller hålls vid målnivån. Vanlig batteriplanering återupptas efter balanseringen.",
    "paused": "Balanseringen är pausad av husets övriga skydd eller laddbehov och planeras om.",
    "deferred": "Balansering skjuts upp - ingen genomförbar period i den kända planen.",
    "timeout": "Balanseringen blev inte klar inom 36 timmar. Vanlig batteriplanering återupptas; kontrollera batteriets app.",
    "cooldown": "Balansering avvaktar efter föregående försök eller fulladdning.",
    "completed": "Batterimodulerna har hållit målnivån under hela balanseringstiden.",
    "balanced": "Ingen bekräftad skillnad som kräver balansering.",
}


def settings(battery):
    raw = battery.get("balance") or {}
    def number(key, default, low, high):
        value = float(raw.get(key, default))
        if not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"battery.balance.{key} outside {low}..{high}")
        return value
    if not isinstance(raw, dict):
        raise ValueError("battery.balance must be a mapping")
    entities = raw.get("module_entities") or []
    if not isinstance(entities, list) or any(not isinstance(e, str) or not e.startswith("sensor.") for e in entities) or len(set(entities)) != len(entities):
        raise ValueError("battery.balance.module_entities must be unique HA sensor IDs")
    return {"enabled": raw.get("enabled") is True,
            "spread_pct": number("spread_pct", 5, 0.1, 100),
            "target_soc": number("target_soc", 100, 50, 100),
            "hold_minutes": number("hold_minutes", 120, 15, 240),
            "confirm_minutes": number("confirm_minutes", 5, 1, 60),
            "min_interval_days": number("min_interval_days", 7, 1, 365),
            "module_entities": entities}


def ha_modules(entities):
    """Explicit HA SOC sensors (0..100%), usable with any battery brand/driver."""
    import homeassistant
    from datetime import datetime
    out = {}
    for entity in entities:
        raw = homeassistant._states_cache.get(entity) or {}
        try:
            stamp = datetime.fromisoformat((raw.get("last_reported") or raw["last_updated"]).replace("Z", "+00:00"))
            if stamp.utcoffset() is None:
                continue
            out[entity] = {"soc_pct": float(raw["state"]), "sample_at": stamp.timestamp()}
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
    return out


def observe(saved, modules, cfg, now, permitted=True, active=False):
    """Return (durable state, status). Missing data never triggers/completes.

    A completed attempt is latched until the spread has cleared. A minimum
    interval additionally prevents repeated full charges for unresolved faults.
    Hold time uses consecutive fresh observations; restart/gaps reset the hold.
    """
    state = dict(saved or {})
    status = {"state": "disabled", "request": False, "target_soc": cfg["target_soc"]}
    if not cfg["enabled"] or not permitted:
        state.pop("request_until", None)
        state.pop("hold_since", None)
        state.pop("candidate_since", None)
        state.pop("started", None)
        state.pop("clear_since", None)
        if not cfg["enabled"]:
            state.pop("modules", None)
        return state, {**status, "state": "unsupported" if cfg["enabled"] and not permitted else "disabled"}
    values = []
    known = set(state.get("modules", [])) | set(modules)
    state["modules"] = sorted(known)
    fresh = len(known) >= 2 and set(modules) == known
    for sample in modules.values():
        try:
            soc, at = float(sample["soc_pct"]), float(sample["sample_at"])
            if not (math.isfinite(soc) and 0 <= soc <= 100 and math.isfinite(at) and 0 <= now - at <= 120):
                fresh = False
            values.append(soc)
        except (KeyError, ValueError, TypeError):
            fresh = False
    if not fresh:
        state.pop("candidate_since", None)
        state.pop("hold_since", None)
        state.pop("clear_since", None)
        return state, {**status, "state": "missing_data"}
    spread = max(values) - min(values)
    if active and state.get("request_until"):
        state["started"] = True
    if state.get("request_until", now + 1) <= now:
        state.update(attempted_at=now, latched=True)
        for key in ("request_until", "hold_since", "started", "candidate_since"):
            state.pop(key, None)
        return state, {**status, "state": "timeout", "spread_pct": round(spread, 2)}
    status.update(spread_pct=round(spread, 2), state="balanced")
    cleared = spread < cfg["spread_pct"] / 2
    if cleared:
        state.setdefault("clear_since", now)
        if now - state["clear_since"] >= cfg["confirm_minutes"] * 60:
            state.pop("latched", None)
            if not state.get("started"):
                state.pop("request_until", None)
        state.pop("candidate_since", None)
    else:
        state.pop("clear_since", None)
    # Natural full charges count too. All modules, not just the aggregate, must
    # remain at the configured target (allowing half a point of sensor rounding).
    if min(values) >= cfg["target_soc"] - 0.5 and not state.get("full_seen"):
        state.setdefault("hold_since", now)
        if now - state["hold_since"] >= cfg["hold_minutes"] * 60:
            state.update(completed_at=now, latched=True, full_seen=True)
            state.pop("request_until", None)
            state.pop("hold_since", None)
            state.pop("started", None)
            return state, {**status, "state": "completed"}
    else:
        state.pop("hold_since", None)
        if min(values) < cfg["target_soc"] - 0.5:
            state.pop("full_seen", None)
    cooldown = now - max(state.get("completed_at", -1e20), state.get("attempted_at", -1e20)) < cfg["min_interval_days"] * 86400
    if spread >= cfg["spread_pct"] and not cooldown and not state.get("latched"):
        state.setdefault("candidate_since", now)
        if now - state["candidate_since"] >= cfg["confirm_minutes"] * 60:
            if not state.get("request_until"):
                state["request_until"] = now + 36 * 3600
    elif spread < cfg["spread_pct"]:
        state.pop("candidate_since", None)
    if state.get("request_until"):
        remaining = max(15, cfg["hold_minutes"] - (now - state.get("hold_since", now)) / 60)
        status.update(state="requested", request=True, hold_slots=math.ceil(remaining / 15),
                      deadline_slots=max(1, math.ceil((state["request_until"] - now) / 900)))
    elif cooldown or state.get("latched"):
        status["state"] = "timeout" if state.get("attempted_at", 0) > state.get("completed_at", 0) else "cooldown"
    elif spread >= cfg["spread_pct"]:
        status["state"] = "confirming"
    return state, status


class Monitor:
    def __init__(self):
        import ew_settings
        self.saved = ew_settings.get("battery_balance_state", {})
        if not isinstance(self.saved, dict):
            self.saved = {}
        # A process restart cannot prove uninterrupted dwell/confirmation.
        self.saved = {k: v for k, v in self.saved.items() if k not in ("hold_since", "candidate_since", "clear_since")}
        self.last_at = None

    def update(self, battery_state, cfg, now, permitted, active=False):
        import ew_settings
        if self.last_at is None or now - self.last_at > 120:
            for key in ("hold_since", "candidate_since", "clear_since"):
                self.saved.pop(key, None)
        self.last_at = now
        entities = cfg["module_entities"]
        if self.saved.get("source_entities", []) != entities:
            self.saved.pop("modules", None)
            self.saved["source_entities"] = list(entities)
        modules = ha_modules(entities) if entities else battery_state.get("modules") or {}
        # A configured sensor that has never reported must not be silently omitted.
        if entities:
            modules = {entity: modules.get(entity, {}) for entity in entities}
        saved, status = observe(self.saved, modules, cfg, now, permitted, active)
        if saved != self.saved:
            try:
                ew_settings.update(battery_balance_state=saved)
            except OSError:
                # Maintenance storage must never disable ordinary battery
                # control or its safety decisions. Do not act on unsaved state.
                return {"request": False, "state": "storage_error"}
            self.saved = saved
        return status


def display(status, plan=None, decision=None, applied=None):
    """Describe actual command state separately from the future schedule."""
    plan, decision, applied = plan or {}, decision or {}, applied or {}
    state = status["state"]
    if status["request"]:
        if not plan or plan.get("balance_deferred"):
            state = "deferred"
        elif plan.get("balance_now"):
            state = "active" if decision.get("rule") in ("balance", "soc_limit") and applied.get("intent") == decision.get("intent") else "paused"
    return MESSAGES.get(state, "")
