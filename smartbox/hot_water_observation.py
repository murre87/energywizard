"""Dated hot-water temperature evidence; never infers freshness from read time."""
from datetime import datetime
from math import isfinite


def temperature(value, timestamp=None, basis=None):
    """Normalize one Celsius reading and its explicitly supplied timestamp basis."""
    valid = (not isinstance(value, bool) and isinstance(value, (int, float))
             and isfinite(value) and -80 <= value <= 150)
    result = {"value_c": float(value) if valid else None,
              "sample_at": None, "timestamp_basis": "unknown"}
    if not valid or basis not in ("source", "ha_report", "local_receipt"):
        return result
    try:
        stamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if stamp.utcoffset() is None:
            return result
        seconds = stamp.timestamp()
        if isfinite(seconds):
            result.update(sample_at=seconds, timestamp_basis=basis)
    except (ValueError, TypeError, AttributeError, OverflowError):
        pass
    return result


def assess(observation, *, now, max_age_s, allow_receipt=False):
    """Report source age separately from local-receipt age; no control decision.

    Receipt-only observations require explicit acceptance, never the default.
    Future timestamps are rejected rather than made current using read time.
    """
    for value in (now, max_age_s):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
            raise ValueError("Finite observation clock and age limit required")
    if max_age_s <= 0:
        raise ValueError("Positive observation age limit required")
    stamp = observation.get("sample_at")
    value = observation.get("value_c")
    basis = observation.get("timestamp_basis")
    if (isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value)
            or not -80 <= value <= 150 or isinstance(stamp, bool)
            or not isinstance(stamp, (int, float)) or not isfinite(stamp)
            or basis not in ("source", "ha_report", "local_receipt")):
        return {"state": "unknown", "age_s": None}
    age = now - stamp
    if age < 0:
        return {"state": "future", "age_s": age}
    if age > max_age_s:
        return {"state": "stale", "age_s": age}
    if basis == "local_receipt" and not allow_receipt:
        return {"state": "receipt_only", "age_s": age}
    return {"state": "fresh", "age_s": age}
