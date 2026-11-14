"""Offline hot-water deadline proposals; no device, database or configuration I/O."""
from datetime import datetime, timedelta, timezone
from math import isfinite

QUARTER = timedelta(minutes=15)


def _time(value):
    stamp = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(stamp, datetime) or stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("Times must include a UTC offset")
    return stamp.astimezone(timezone.utc)


def _number(value, name, minimum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise ValueError(f"Invalid {name}")
    if minimum is not None and value < minimum:
        raise ValueError(f"Invalid {name}")
    return float(value)


def propose(prices, *, now, earliest, deadline, duration_min, electrical_power_kw):
    """Cheapest contiguous fixed-power window; full import prices in currency/kWh.

    Each price row has an offset-aware quarter start `t`, `buy`, and optional
    `permitted=False` from an external guard. Missing quarters cannot be filled.
    Returns an advisory proposal, never an instruction or hygiene guarantee.
    """
    now, earliest, deadline = map(_time, (now, earliest, deadline))
    earliest = max(now, earliest)
    minutes = _number(duration_min, "duration", 1)
    power = _number(electrical_power_kw, "electrical power", .001)
    if minutes > 360 or deadline - now > timedelta(hours=36):
        raise ValueError("Proposal limited to six hours heating and a 36-hour horizon")
    duration = timedelta(minutes=minutes)
    if len(prices) > 144:
        raise ValueError("At most 144 price quarters")
    rows = {}
    for row in prices:
        t = _time(row["t"])
        if t.minute % 15 or t.second or t.microsecond or t in rows:
            raise ValueError("Price quarters must be unique and UTC quarter-aligned")
        permitted = row.get("permitted", True)
        if not isinstance(permitted, bool):
            raise ValueError("permitted must be boolean")
        rows[t] = (_number(row["buy"], "import price"), permitted)
    latest = deadline - duration
    candidates = {earliest, latest}
    # The moving-window price integral is piecewise linear: extrema occur
    # when either end touches a price/permission boundary, or a search bound.
    for t in rows:
        for edge in (t, t + QUARTER):
            candidates.update((edge, edge - duration))
    best = None
    for start in sorted(t for t in candidates if earliest <= t <= latest):
        finish, cost, covered, reservation = start + duration, 0.0, 0.0, []
        blocked = False
        for t, (price, permitted) in sorted(rows.items()):
            seconds = max(0.0, (min(finish, t + QUARTER) - max(start, t)).total_seconds())
            if not seconds:
                continue
            if not permitted:
                blocked = True
                break
            kwh = power * seconds / 3600
            cost += kwh * price
            covered += seconds
            reservation.append({"t": t.isoformat(), "hot_water_kw": kwh / .25})
        if blocked or abs(covered - duration.total_seconds()) > 1e-6:
            continue
        if best is None or (cost, start) < (best["estimated_import_cost"], _time(best["start"])):
            best = {"state": "proposed", "start": start.isoformat(), "end": finish.isoformat(),
                    "deadline": deadline.isoformat(), "energy_kwh": power * minutes / 60,
                    "estimated_import_cost": cost, "quarters": reservation,
                    "control_ready": False}
    return best or {"state": "unavailable", "reason": "no_complete_permitted_window", "control_ready": False}


def reserve_load(forecast, proposal, *, baseline_contract):
    """Add one proposal to an explicitly hot-water-excluded quarter forecast.

    Returns new rows for the pure battery optimizer (`load_kw` includes the
    proposal). Refuses ambiguous baseline semantics and repeated application.
    """
    if baseline_contract != "hot_water_excluded":
        raise ValueError("Baseline must explicitly exclude hot-water electrical demand")
    if proposal.get("state") != "proposed":
        raise ValueError("A complete proposal is required")
    additions = {_time(r["t"]): r["hot_water_kw"] for r in proposal["quarters"]}
    out, seen = [], set()
    for row in forecast:
        t = _time(row["t"])
        if t in seen or "hot_water_kw" in row:
            raise ValueError("Duplicate quarter or hot-water reservation")
        seen.add(t)
        base = _number(row["load_kw"], "residual household load", 0)
        added = additions.get(t, 0.0)
        out.append({**row, "load_kw": base + added, "hot_water_kw": added})
    if not additions.keys() <= seen:
        raise ValueError("Forecast does not cover the complete reservation")
    return out
