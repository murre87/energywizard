"""ew_journal.py - installationens egen logg: allt motorn, appen och webben skriver.

Varje rad som skrivs ut (inläsningar, beslut med orsak, kommandon till enheter, notiser, varningar och fel) sparas i
husets egen databas (tabellen ew_journal) med tid, källa (motor/app/webb), nivå och var i koden den kom ifrån. Ohanterade
undantag sparas med hela förloppet. Användaren läser, söker och laddar ner loggen själv (webben: Logg; appen:
Inställningar -> Logg) - till exempel för att bifoga i en issue. Loggen lämnar aldrig huset av sig själv.

Skrivningen sker i en bakgrundstråd i omgångar, så att en långsam databas aldrig bromsar motorn. Sparas KEEP_DAYS dygn.
"""
import builtins
import os
import queue
import sys
import threading
import time
import traceback

KEEP_DAYS = 14
_Q: "queue.Queue" = queue.Queue(maxsize=20000)
_src = "motor"
_started = False


def level_of(msg: str) -> str:
    m = (msg or "").lstrip()
    # Full disk / databasen nere: användarens miljö, en varning, inte ett fel i EnergyWizard (env_errors.py)
    if any(t in m for t in ("PoolTimeout", "DiskFull", "No space left on device", "couldn't get a connection", "53100")):
        return "varning"
    if m.startswith(("❌", "Traceback", "🚨")) or "Traceback (most recent call last)" in m:
        return "fel"
    if m.startswith(("⚠️", "⚠")):
        return "varning"
    if m.startswith(("🔔", "🔕")):
        return "notis"
    return "info"


def _ensure(cur):
    cur.execute("CREATE TABLE IF NOT EXISTS ew_journal (id BIGSERIAL PRIMARY KEY, ts TIMESTAMPTZ DEFAULT now(), src TEXT, "
                "lvl TEXT, mod TEXT, msg TEXT)")
    cur.execute("CREATE INDEX IF NOT EXISTS ew_journal_ts ON ew_journal (ts)")


def _writer():
    import logger
    made, last_clean = False, 0.0
    while True:
        batch = [_Q.get()]
        t_end = time.time() + 2
        while time.time() < t_end and len(batch) < 500:
            try:
                batch.append(_Q.get(timeout=0.2))
            except queue.Empty:
                break
        try:
            with logger.get_db() as conn, conn.cursor() as cur:
                if not made:
                    _ensure(cur)
                    made = True
                cur.executemany("INSERT INTO ew_journal (ts, src, lvl, mod, msg) VALUES (to_timestamp(%s), %s, %s, %s, %s)", batch)
                if time.time() - last_clean > 3600:
                    cur.execute(f"DELETE FROM ew_journal WHERE ts < now() - interval '{KEEP_DAYS} days'")
                    last_clean = time.time()
                conn.commit()
        except Exception:
            made = False                   # databasen borta en stund: de här raderna tappas, nästa omgång försöker igen
            time.sleep(5)


def add(msg: str, lvl: str | None = None, mod: str = "") -> None:
    if not msg or not msg.strip():
        return
    try:
        _Q.put_nowait((time.time(), _src, lvl or level_of(msg), mod[:60], msg[:4000]))
    except queue.Full:
        pass


def install(source: str = "motor") -> None:
    """Fångar alla utskrifter och ohanterade undantag till loggen. Anropas en gång vid start (motor, app, webb)."""
    global _src, _started
    _src = source
    if _started or os.environ.get("EW_JOURNAL", "1") == "0" or "pytest" in sys.modules:
        return
    _started = True
    threading.Thread(target=_writer, daemon=True, name="ew-journal").start()
    orig = builtins.print

    def journaled(*args, **kwargs):
        orig(*args, **kwargs)
        try:
            if kwargs.get("file") not in (None, sys.stdout, sys.stderr):
                return
            f = sys._getframe(1)
            # Hoppa över andra print-krokar (telemetrin) så att källan blir koden som skrev raden
            while f is not None and os.path.basename(f.f_code.co_filename) in ("telemetry.py", "ew_journal.py"):
                f = f.f_back
            if f is None:
                return
            base = os.path.splitext(os.path.basename(f.f_code.co_filename))[0]
            if base == "traceback":       # traceback.print_exc(): förloppet läggs redan till på felraden nedan
                return
            msg = kwargs.get("sep", " ").join(str(a) for a in args)
            mod = f"{base}.{f.f_code.co_name}"
            if sys.exc_info()[0] is not None and level_of(msg) == "fel":
                msg += "\n" + "".join(traceback.format_exc(limit=8))
            add(msg, mod=mod)
        except Exception:
            pass

    journaled._ew_hook = getattr(orig, "_ew_hook", False)
    builtins.print = journaled

    def exc_hook(t, v, tb):
        add("Traceback (most recent call last):\n" + "".join(traceback.format_exception(t, v, tb)), "fel", "ohanterat")
        sys.__excepthook__(t, v, tb)
    sys.excepthook = exc_hook
    threading.excepthook = lambda a: add("Traceback i tråd " + str(getattr(a.thread, "name", "?")) + ":\n"
                                         + "".join(traceback.format_exception(a.exc_type, a.exc_value, a.exc_traceback)),
                                         "fel", "tråd")


def read(conn, since_h: float = 24, lvl: str | None = None, q: str | None = None, src: str | None = None, limit: int = 500):
    """Senaste raderna (nyast först) för loggsidan. conn = SQLAlchemy-anslutning."""
    from sqlalchemy import text
    where, p = ["ts > now() - make_interval(secs => :s)"], {"s": float(since_h) * 3600, "n": max(1, min(int(limit), 5000))}
    if lvl in ("fel", "varning", "notis", "info"):
        where.append("lvl = :l"); p["l"] = lvl
    if src in ("motor", "app", "webb"):
        where.append("src = :src"); p["src"] = src
    if q:
        where.append("msg ILIKE :q"); p["q"] = f"%{q}%"
    try:
        rows = conn.execute(text(f"SELECT ts, src, lvl, mod, msg FROM ew_journal WHERE {' AND '.join(where)} "
                                 "ORDER BY ts DESC LIMIT :n"), p).fetchall()
    except Exception:
        conn.rollback()
        return []
    return [{"ts": r[0].isoformat(), "src": r[1], "lvl": r[2], "mod": r[3], "msg": r[4]} for r in rows]


def export_text(conn, days: float = 2) -> str:
    """Supportfil: allt de senaste dygnen som ren text, äldst först."""
    rows = _all(conn, days)
    return "".join(f"{r[0].astimezone().strftime('%Y-%m-%d %H:%M:%S')} [{r[1]}] {r[2]:7} {r[3]}: {r[4]}\n" for r in rows)


def _all(conn, days):
    from sqlalchemy import text
    try:
        return conn.execute(text("SELECT ts, src, lvl, mod, msg FROM ew_journal WHERE ts > now() - make_interval(days => :d) "
                                 "ORDER BY ts LIMIT 400000"), {"d": int(max(1, min(days, KEEP_DAYS)))}).fetchall()
    except Exception:
        conn.rollback()
        return []
