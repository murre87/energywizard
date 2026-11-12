"""Kolumnnamn för en bils värden i sensor_log.

sensor_log använder oquotade SQL-namn. Postgres vekar dem till gemener, och
loggern släppte tidigare bara igenom [a-z0-9_]{1,40}. Ett id som Volvo_Ex40
loggades därför aldrig. Översiktens flöde läser <id>_soc och hoppar över bilen
när både effekt och nivå saknas, så bilen försvann från översikten (#293).

Befintliga id som redan är giltiga kolumnprefix (nissan, tesla, generic_ev)
blir oförändrade, så gamla kolumner fortsätter att användas.
"""
import re

_UNSAFE = re.compile(r"[^a-z0-9_]")
_COLUMN = re.compile(r"[a-z_][a-z0-9_]{0,39}")
_CAR_ID = re.compile(r"[A-Za-z0-9_]{1,64}")
SUFFIXES = ("soc_stale", "charge_completed", "climate_temp", "climate_state", "soc")


def car_log_id(car_id) -> str:
    """Säkert kolumnprefix. Tom sträng om id:t inte kan bli ett SQL-namn."""
    key = _UNSAFE.sub("_", str(car_id or "").strip().lower())[:40]
    if key[:1].isdigit():
        key = ("c" + key)[:40]
    return key if _COLUMN.fullmatch(key or "") else ""


def car_log_column(car_id, kind: str) -> str:
    prefix = car_log_id(car_id)
    if not prefix or kind not in SUFFIXES:
        return ""
    return f"{prefix}_{kind}"


def car_id_ok(car_id) -> bool:
    """Id som får stå i en webbadress. Versaler är giltiga; snedstreck är det inte."""
    return bool(_CAR_ID.fullmatch(str(car_id or "")))


def car_log_fields(cd: dict | None) -> dict:
    """{kolumn: (slag, värde)} ur car_data. Nycklar som inte är en bilkolumn släpps."""
    out = {}
    for k, v in (cd or {}).items():
        key = str(k)
        kind = next((s for s in SUFFIXES if key.endswith("_" + s) and len(key) > len(s) + 1), None)
        if not kind:
            continue
        col = car_log_column(key[: -(len(kind) + 1)], kind)
        if not col:
            continue
        out[col] = (kind, (1 if v else 0) if kind == "charge_completed" else v)
    return out
