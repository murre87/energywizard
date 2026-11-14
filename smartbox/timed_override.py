"""timed_override.py - överstyrningar med tid som går tillbaka till Auto av sig själva (#397).

Varmvatten "Till" gällde förut tills man själv valde Auto igen. Med en tid sparas <nyckel>_until (unix-tid), och
motorn sätter tillbaka till Auto när tiden har gått ut. Ren funktion, testas i tests/test_issue_397_hotwater_timer.py."""

MIN_MIN, MAX_MIN = 15, 6 * 60


def until(overrides: dict, key: str):
    try:
        return float(str(overrides.get(f"{key}_until") or "").strip())
    except ValueError:
        return None


def expired(overrides: dict, key: str, now_ts: float) -> bool:
    """True när överstyrningen har en tid som gått ut och ska tillbaka till Auto."""
    u = until(overrides, key)
    return u is not None and overrides.get(key, "auto") != "auto" and now_ts >= u


def minutes(value):
    """Giltig längd i minuter (15 min - 6 h) eller None."""
    try:
        m = int(value)
    except (TypeError, ValueError):
        return None
    return m if MIN_MIN <= m <= MAX_MIN else None
