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
    """En rad, sanerad med log_scrub (husets egna namn + mönster + slutkontroll)."""
    import log_scrub
    return log_scrub.scrub_line(str(text or "")[:500], log_scrub.sensitive_words())


def note_error_line(line: str) -> None:
    """Anropas från telemetrins ❌-krok: spara sanerad rad i ringbuffert."""
    if not line:
        return
    s = sanitize(line.rstrip())
    if s:
        _ring.append(s)


_NOISE = re.compile(r"^\s*$|1-minutslogg sparad|^\s*=+\s*$")
JOURNAL_HOURS = 2           # #227: så mycket av husets logg följer med en felrapport
JOURNAL_LINES = 400
_MAX_BUNDLE = 40000


def _journal_lines():
    """Husets logg (ew_journal) de senaste JOURNAL_HOURS timmarna, äldst först, högst JOURNAL_LINES rader."""
    import logger
    with logger.get_db() as conn, conn.cursor() as cur:
        cur.execute("SELECT ts, src, lvl, msg FROM ew_journal WHERE ts > now() - make_interval(hours => %s) "
                    "ORDER BY id DESC LIMIT %s", (JOURNAL_HOURS, JOURNAL_LINES))
        rows = cur.fetchall() or []
    return [(ts, src, lvl, msg) for ts, src, lvl, msg in reversed(rows)]


def build(module: str = "", error_type: str = "") -> str:
    """Supportutdrag för en felrapport (#227): felraderna, de senaste besluten och husets logg de senaste två
    timmarna. Allt saneras rad för rad med log_scrub (husets egna namn, adresser, nycklar, koordinater, serienummer;
    rader som ändå ser känsliga ut tas bort). Tom sträng om användaren stängt av felsökningsutdrag."""
    if not enabled():
        return ""
    import log_scrub
    words = log_scrub.sensitive_words()
    parts = [f"module={module}", f"error_type={error_type}"]
    journal_start = None
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
                parts.append(log_scrub.scrub_line(str(raw)[:400], words))
    except Exception:
        pass
    try:
        lines = _journal_lines()
        if lines:
            journal_start = len(parts)
            parts.append(f"--- log (senaste {JOURNAL_HOURS} h, sanerad) ---")
            for ts, src, lvl, msg in lines:
                if _NOISE.search(str(msg or "")):                # tomma rader och "1-minutslogg sparad" säger inget
                    continue
                first = str(msg or "").split("\n")
                head = f"{ts:%H:%M:%S} {src or ''} {lvl or ''} " if hasattr(ts, "strftime") else ""
                parts.append(head + log_scrub.scrub_line(first[0][:600], words))
                for extra in first[1:12]:                    # traceback-rader (högst elva)
                    parts.append("    " + log_scrub.scrub_line(extra[:300], words))
    except Exception:
        pass
    out = "\n".join(parts)
    if len(out) <= _MAX_BUNDLE:
        return out
    # Preserve the diagnostic header/error ring when the two-hour journal is
    # large. Truncating the whole string from the front discarded the reason
    # the report was sent. All content has already passed the same scrubber.
    prefix = "\n".join(parts[:journal_start]) if journal_start is not None else "\n".join(parts[:2])
    if len(prefix) > _MAX_BUNDLE // 2:
        prefix = "\n".join(parts[:2]) + "\n" + prefix[-(_MAX_BUNDLE // 2):]
    marker = "--- log truncated: older lines omitted ---"
    remaining = _MAX_BUNDLE - len(prefix) - len(marker) - 2
    tail = out[-remaining:]
    tail = tail.partition("\n")[2]  # never start with half a journal line
    return prefix + "\n" + marker + "\n" + tail
