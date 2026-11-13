"""Kupévärme till ett klockslag (#233).

Motorn läser climate_schedule (en rad per bil: på, tid, temperatur) i main.py.
Den här modulen bara kontrollerar det användaren skickar in. Den skriver inget.
"""
from datetime import datetime

TEMP_MIN = 15.0
TEMP_MAX = 28.0
DEFAULT_TEMP = 21.0
DEFAULT_TIME = "07:00"


def _on(enabled) -> bool:
    if isinstance(enabled, str):
        return enabled.strip().lower() in ("1", "true", "on", "ja")
    return bool(enabled)


def normalize(enabled, time_s, temp) -> dict:
    """Tid HH:MM och temperatur 15–28 °C. Ogiltigt värde ger ValueError med en kort svensk mening."""
    raw = str(DEFAULT_TIME if time_s is None else time_s).strip()
    if len(raw) == 8 and raw[2] == ":" and raw[5] == ":":
        raw = raw[:5]
    try:
        datetime.strptime(raw, "%H:%M")
    except ValueError:
        raise ValueError("Ogiltig tid") from None
    if len(raw) != 5:
        raise ValueError("Ogiltig tid")
    try:
        n = float(DEFAULT_TEMP if temp is None or temp == "" else temp)
    except (TypeError, ValueError):
        raise ValueError("Ogiltig temperatur") from None
    if not (TEMP_MIN <= n <= TEMP_MAX):
        raise ValueError("Temperaturen måste ligga mellan 15 och 28 °C")
    return {"enabled": _on(enabled), "time": raw, "temp": round(n, 1)}


def view(row: dict | None, has_climate: bool) -> dict:
    """Raden från settings.get_climate_schedule, plus om bilen har en klimatentitet."""
    row = row or {}
    temp = row.get("target_temp")
    try:
        shown = float(temp) if temp is not None else DEFAULT_TEMP
    except (TypeError, ValueError):
        shown = DEFAULT_TEMP
    return {
        "enabled": bool(row.get("enabled")),
        "time": row.get("target_time") or DEFAULT_TIME,
        "temp": shown,
        "has_climate": bool(has_climate),
    }
