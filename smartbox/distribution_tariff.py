"""ČEZ HDO schedules: optional distribution or final NT/VT purchase prices.

Read-only HA access, cached for 60 seconds. Missing/invalid/out-of-range schedules
use the higher configured rate, never today's NT state for a future interval.
"""
import logging
import math
import re
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

LOG = logging.getLogger(__name__)
_CACHE = {}


def _timestamp(value):
    try:
        t = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=ZoneInfo("Europe/Prague"))
        return t.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def parse_schedule(attrs):
    """ČEZ HDO's schedule attribute contains explicit NT and VT intervals."""
    result = []
    for item in attrs.get("schedule", []) or []:
        if not isinstance(item, dict):
            continue
        start, end = _timestamp(item.get("start")), _timestamp(item.get("end"))
        tariff = str(item.get("tariff", "")).upper()
        if start is None or end is None or end <= start or tariff not in ("NT", "VT"):
            continue
        # The integration represents midnight as 23:59:59 of the preceding day.
        if str(item.get("end", ""))[11:19] == "23:59:59":
            end += timedelta(seconds=1)
        # ČEZ HDO synthesizes a full VT day when it has no schedule data.
        # Treat that indistinguishable case as unknown rather than cheaper VT.
        local_start = start.astimezone(ZoneInfo("Europe/Prague"))
        local_end = end.astimezone(ZoneInfo("Europe/Prague"))
        if (tariff == "VT" and local_start.time().isoformat() == "00:00:00"
                and local_end.time().isoformat() == "00:00:00"
                and (local_end.date() - local_start.date()).days == 1):
            continue
        result.append((start, end, tariff))
    result.sort()
    # Conflicting overlapping intervals must not make an unknown period cheap.
    if any(b[0] < a[1] for a, b in zip(result, result[1:])):
        return []
    return result


def schedule_for(entity):
    if not re.fullmatch(r"sensor\.[a-z0-9_]+", entity or ""):
        return []
    import homeassistant as H
    # Each process has its own cache; no dependency on engine-only state refresh.
    key = (H._BASE, entity)
    cached = _CACHE.get(key)
    if cached and time.monotonic() - cached[0] < 60:
        return cached[1]
    rows, attrs = [], {}
    try:
        r = H.requests.get(f"{H._BASE}/states/{entity}", headers=H._HEADERS, timeout=5, verify=H._VERIFY)
        r.raise_for_status()
        state = r.json()
        if state.get("state") not in ("unknown", "unavailable", None):
            attrs = state.get("attributes") or {}
            rows = parse_schedule(attrs)
    except Exception as exc:
        LOG.warning("HDO schedule unavailable for %s (%s); using higher distribution rate", entity, type(exc).__name__)
    _CACHE[key] = (time.monotonic(), rows, attrs)
    return rows


def prices_for(entity):
    """Both configured ČEZ HDO rates, never the instantaneous current price."""
    import homeassistant as H
    schedule_for(entity)
    cached = _CACHE.get((H._BASE, entity))
    attrs = cached[2] if cached and len(cached) > 2 else {}
    try:
        raw = [attrs[k] for k in ("low_tariff_price", "high_tariff_price")]
        if any(isinstance(v, bool) for v in raw):
            return None
        rates = tuple(float(v) for v in raw)
        if all(math.isfinite(v) and -100 <= v <= 1000 for v in rates) and rates != (0, 0):
            return rates
    except (KeyError, TypeError, ValueError):
        pass
    return None


def purchase_rates(c):
    if c.get("hdo_price_source") == "ha":
        live = prices_for(c["hdo_entity"])
        if live is not None:
            return live
    # Validated prices saved with the configuration also survive an HA outage.
    rates = tuple(float(c[k]) for k in ("buy_nt", "buy_vt"))
    if not all(math.isfinite(v) and -100 <= v <= 1000 for v in rates):
        raise ValueError("Invalid NT/VT purchase rates")
    return rates


def _at(t, entity, nt, vt):
    if t is None:
        t = datetime.now(timezone.utc)
    if t.tzinfo is None:
        t = t.replace(tzinfo=ZoneInfo("Europe/Prague"))
    t = t.astimezone(timezone.utc)
    for start, end, tariff in schedule_for(entity):
        if start <= t < end:
            return nt if tariff == "NT" else vt
    return max(nt, vt)


def _sql(tcol, entity, nt, vt):
    if not tcol:
        return str(_at(None, entity, nt, vt))
    cases = [f"WHEN {tcol} >= TIMESTAMPTZ '{s.isoformat()}' AND {tcol} < TIMESTAMPTZ '{e.isoformat()}' THEN {nt if k == 'NT' else vt}"
             for s, e, k in schedule_for(entity)]
    if not cases:
        return str(max(nt, vt))
    return "CASE " + " ".join(cases) + f" ELSE {max(nt, vt)} END"


def purchase_at(t, c):
    return _at(t, c["hdo_entity"], *purchase_rates(c))


def sql_purchase_expr(tcol, c):
    return "(" + _sql(tcol, c["hdo_entity"], *purchase_rates(c)) + ")"


def _rates(c):
    nt, vt = float(c["distribution_nt"]), float(c["distribution_vt"])
    if not all(math.isfinite(x) and x >= 0 for x in (nt, vt)):
        raise ValueError("Distribution rates must be finite and non-negative")
    return nt, vt


def distribution_at(t, c):
    if c.get("country") != "CZ" or not c.get("hdo_entity"):
        return 0.0
    return _at(t, c["hdo_entity"], *_rates(c))


def sql_distribution_expr(tcol, c):
    """Same interval boundaries and fallback as distribution_at, for PostgreSQL."""
    if c.get("country") != "CZ" or not c.get("hdo_entity"):
        return ""
    return " + " + _sql(tcol, c["hdo_entity"], *_rates(c))
