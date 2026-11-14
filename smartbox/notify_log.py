"""notify_log.py - aviseringshistorik med leveransstatus (idé från FTW v0.160, Emil godkände 2026-11-07).

"Fick jag ingen notis, eller skickades den aldrig?" Varje avisering från motorn (notifier.py) och mobilappen (ewapp
push) sparas här med hur det gick:
  sent    Home Assistant tog emot den (HA bekräftar inte att telefonen fått den, bara att den skickades vidare)
  failed  Home Assistant svarade med fel eller svarade inte (orsaken sparas)
  muted   kategorin är avstängd under Inställningar -> Notiser
  none    ingen mottagare (ingen telefon vald eller hittad, eller ingen hemma med "bara den som är hemma")
Tabellen notify_log hålls i 60 dygn. Egen kort anslutning (används både i motorn och i appen). Fel här får aldrig
stoppa själva aviseringen.
"""
import os
import uuid
from collections import deque
from datetime import datetime, timezone

KEEP_DAYS = 60
# #387: rader som inte kunde sparas (databasen överbelastad/nere) väntar här och sparas vid nästa tillfälle, med
# händelsens ursprungliga tid. Begränsad (äldsta faller bort), utan dubbletter (event_id), och själva aviseringen
# skickas aldrig om - det är bara historikraden som sparas igen.
PENDING_MAX = 200
_pending = deque(maxlen=PENDING_MAX)
_dropped = {"n": 0}
STATUS_TEXT = {"sent": "Skickad", "failed": "Misslyckades", "muted": "Avstängd kategori", "none": "Ingen mottagare"}

_SCHEMA = """CREATE TABLE IF NOT EXISTS notify_log (
    id BIGSERIAL PRIMARY KEY, ts TIMESTAMPTZ NOT NULL DEFAULT NOW(), src TEXT, category TEXT, title TEXT,
    message TEXT, recipient TEXT, status TEXT NOT NULL, detail TEXT)"""
_n = {"writes": 0}


def _category(key, title):
    if key:
        return key
    try:
        import notify_prefs
        return notify_prefs.category_for(title or "")
    except Exception:
        return None


def _connect():
    import psycopg
    return psycopg.connect(host=os.environ.get("POSTGRES_HOST", "postgres-smartbox"), user=os.environ["POSTGRES_USER"],
                           password=os.environ["POSTGRES_PASSWORD"], dbname=os.environ["POSTGRES_DB"], connect_timeout=5)


def _write(c, rows):
    c.execute(_SCHEMA)
    c.execute("ALTER TABLE notify_log ADD COLUMN IF NOT EXISTS event_id TEXT")
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS notify_log_event_id ON notify_log (event_id)")
    for r in rows:
        c.execute("INSERT INTO notify_log (ts, src, category, title, message, recipient, status, detail, event_id) "
                  "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (event_id) DO NOTHING",
                  (r["ts"], r["src"], r["category"], r["title"], r["message"], r["recipient"], r["status"], r["detail"], r["event_id"]))


def add(title, message, status, recipient=None, key=None, detail=None, src="motorn", connect=None):
    row = {"ts": datetime.now(timezone.utc), "src": src, "category": _category(key, title), "title": str(title or "")[:200],
           "message": str(message or "")[:1000], "recipient": (recipient or "").removeprefix("notify.") or None,
           "status": status, "detail": (str(detail)[:300] if detail else None), "event_id": uuid.uuid4().hex}
    if len(_pending) == _pending.maxlen:
        _dropped["n"] += 1
    _pending.append(row)
    flush(connect)


def flush(connect=None):
    """Spara väntande rader (äldst först). Lyckas det inte ligger de kvar till nästa försök. Returnerar antal sparade."""
    if not _pending:
        return 0
    rows = list(_pending)
    try:
        with (connect or _connect)() as c:
            _write(c, rows)
            _n["writes"] += len(rows)
            if _n["writes"] % 50 < len(rows) or _n["writes"] <= len(rows):
                c.execute(f"DELETE FROM notify_log WHERE ts < NOW() - INTERVAL '{KEEP_DAYS} days'")
        for _ in rows:
            _pending.popleft()
        if len(rows) > 1:
            print(f"🗂️ Aviseringshistoriken: {len(rows)} väntande rader sparade.")
        return len(rows)
    except Exception as e:
        print(f"⚠️ Aviseringshistoriken: {type(e).__name__} - {len(_pending)} rader väntar och sparas senare.")
        return 0


def short_error(e) -> str:
    """En begriplig orsak ur ett requests-fel (utan adresser eller nycklar)."""
    s = getattr(getattr(e, "response", None), "status_code", None)
    if s == 401:
        return "Home Assistant nekade (fel eller utgången token)"
    if s == 400:
        return "Home Assistant avvisade aviseringen (finns mottagaren kvar?)"
    if s:
        return f"Home Assistant svarade {s}"
    n = type(e).__name__
    if "Timeout" in n:
        return "Home Assistant svarade inte i tid"
    if "Connection" in n:
        return "Kunde inte nå Home Assistant"
    return n


def recent(conn, days: int = 7, limit: int = 200) -> list:
    """Senaste aviseringarna via en SQLAlchemy-anslutning (appen och webben)."""
    from sqlalchemy import text
    try:
        rows = conn.execute(text("SELECT ts, src, category, title, message, recipient, status, detail FROM notify_log "
                                 "WHERE ts >= NOW() - make_interval(days => :d) ORDER BY ts DESC LIMIT :n"),
                            {"d": int(days), "n": int(limit)}).mappings().all()
    except Exception:
        conn.rollback()           # tabellen finns inte än
        return []
    labels = {}
    try:
        import notify_prefs
        labels = {k: label for k, label, _ in notify_prefs.CATEGORIES}
    except Exception:
        pass
    return [{"ts": r["ts"].isoformat(), "src": r["src"], "category": labels.get(r["category"], r["category"]),
             "title": r["title"], "message": r["message"], "recipient": r["recipient"], "status": r["status"],
             "status_text": STATUS_TEXT.get(r["status"], r["status"]), "detail": r["detail"]} for r in rows]
