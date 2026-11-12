"""Supportutdrag för felsökning (#227).

På som standard (saknad nyckel = på). Användaren kan stänga av i Inställningar.
Skickas tillsammans med felrapporter när det är på: senaste ❌-rader + kort
decision_summary, sanerade (inga entity-id, IP eller långa sökvägar).
Aldrig husnamn, koordinater eller råa undantagsvärden från andra källor.
"""
from __future__ import annotations

import re
from collections import deque

_SETTING = "support_diag"          # ew_settings: True/False; saknas = på
_MAX_LINES = 40
_MAX_CHARS = 6000
_ring: deque[str] = deque(maxlen=_MAX_LINES)

_ENTITY = re.compile(r"\b(?:sensor|switch|number|binary_sensor|climate|button|select|input_\w+|device_tracker|person|media_player|light|cover|lock|vacuum|update|script|automation|scene|zone)\.[a-z0-9_]+\b", re.I)
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_PATH = re.compile(r"(?:/home|/var|/opt|/data|/usr|/tmp)/[^\s\"']+")
_TOKENISH = re.compile(r"\b(?:eyJ|ghp_|github_pat_|sk-)[A-Za-z0-9_\-\.]{12,}\b")


def enabled() -> bool:
    """På för alla befintliga installationer tills någon uttryckligen stänger av."""
    try:
        import ew_settings
        v = ew_settings.get(_SETTING)
        if v is None:
            return True
        if isinstance(v, bool):
            return v
        return str(v).strip().lower() not in ("0", "false", "off", "no", "nej")
    except Exception:
        return True


def set_enabled(on: bool) -> None:
    import ew_settings
    ew_settings.update(**{_SETTING: bool(on)})


def sanitize(text: str) -> str:
    t = _ENTITY.sub("<entitet>", text or "")
    t = _IPV4.sub("<ip>", t)
    t = _PATH.sub("<sökväg>", t)
    t = _TOKENISH.sub("<hemlighet>", t)
    return t[:500]


def note_error_line(line: str) -> None:
    """Anropas från telemetrins ❌-krok: spara sanerad rad i ringbuffert."""
    if not line:
        return
    s = sanitize(line.rstrip())
    if s:
        _ring.append(s)


def build(module: str = "", error_type: str = "") -> str:
    """Kort supportutdrag för en felrapport. Tom sträng om avstängt."""
    if not enabled():
        return ""
    parts = [f"module={module}", f"error_type={error_type}"]
    if _ring:
        parts.append("--- recent_errors ---")
        parts.extend(list(_ring)[-_MAX_LINES:])
    try:
        import logger
        with logger.get_db() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT decision_summary FROM sensor_log WHERE decision_summary IS NOT NULL "
                "ORDER BY timestamp DESC LIMIT 3"
            )
            rows = cur.fetchall() or []
        if rows:
            parts.append("--- recent_decisions ---")
            for (raw,) in rows:
                parts.append(sanitize(str(raw)[:400]))
    except Exception:
        pass
    out = "\n".join(parts)
    return out[:_MAX_CHARS]
