"""EnergyWizard telemetri-samlare: en EGEN, fristående tjänst - driftsätts EN gång
av Emil (inte av varje betatestare). Alla installationer skickar hit
(obligatoriskt sedan 2026-11-06, se smartbox/telemetry.py).

Tar bara emot och lagrar det smartbox/telemetry.py redan sanerat: en hashad
husidentifierare, drivrutinkategorier, feltyper, version, tidsstämpel. Inget UI
än - bara lagring + /api/recent för att själv fråga ut det senaste.
"""
import log_scrub  # noqa: E402  (samma sanering som motorn, smartbox/log_scrub.py)
# Fel i användarens miljö (full disk, databasen nere): inga felgrupper, inga ärenden, inte rött på Installationer.
# Samma lista som smartbox/env_errors.py (Emil 2026-11-13).
ENV_ERROR_TYPES = {"DiskFull", "PoolTimeout", "OperationalError", "TooManyConnections", "AdminShutdown",
                   "CannotConnectNow", "ConnectionTimeout", "InsufficientResources", "OutOfMemory"}
import os
import smtplib
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from email.mime.text import MIMEText

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

DB_PATH = os.environ.get("TELEMETRY_DB_PATH", "/data/telemetry.sqlite3")

# Ny-installation-mejl: valfritt, av om SMTP_HOST/ALERT_EMAIL_TO saknas. Skickas EN
# gång per unik husidentifierare (hash), aldrig på efterföljande snapshots från samma
# hus - annars blir det ett mejl varje gång smartbox startar om.
SMTP_HOST = os.environ.get("SMTP_HOST", "").strip()
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587") or 587)
SMTP_USER = os.environ.get("SMTP_USER", "").strip()
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "").strip()
SMTP_FROM = os.environ.get("SMTP_FROM", "").strip() or SMTP_USER
ALERT_EMAIL_TO = os.environ.get("ALERT_EMAIL_TO", "").strip()


def _send_new_install_email(house: str, version: str) -> None:
    if not (SMTP_HOST and ALERT_EMAIL_TO):
        return
    try:
        msg = MIMEText(
            f"Ny EnergyWizard-installation upptäckt.\n\n"
            f"Husidentifierare (hashad): {house}\n"
            f"Version: {version}\n"
            f"Tid: {datetime.now(timezone.utc).isoformat()}\n"
        )
        msg["Subject"] = "🔆 Ny EnergyWizard-installation"
        msg["From"] = SMTP_FROM
        msg["To"] = ALERT_EMAIL_TO
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as s:
            s.starttls()
            if SMTP_USER:
                s.login(SMTP_USER, SMTP_PASSWORD)
            s.send_message(msg)
    except Exception as e:
        print(f"❌ Kunde inte skicka ny-installation-mejl: {e}")

app = FastAPI(title="EnergyWizard Telemetri-samlare")


@contextmanager
def _db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS driver_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT, received_at TEXT, house TEXT,
            version TEXT, drivers TEXT, ts TEXT)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS errors (
            id INTEGER PRIMARY KEY AUTOINCREMENT, received_at TEXT, house TEXT,
            version TEXT, module TEXT, error_type TEXT, ts TEXT)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS known_houses (
            house TEXT PRIMARY KEY, first_seen TEXT)""")
        # #227: sanerat supportutdrag (valfritt fält på felrapporter)
        conn.execute("""CREATE TABLE IF NOT EXISTS error_support (
            id INTEGER PRIMARY KEY AUTOINCREMENT, received_at TEXT, house TEXT,
            version TEXT, module TEXT, error_type TEXT, support TEXT)""")
        try:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(errors)").fetchall()}
            if "has_support" not in cols:
                conn.execute("ALTER TABLE errors ADD COLUMN has_support INTEGER DEFAULT 0")
        except Exception:
            pass
        yield conn
        conn.commit()
    finally:
        conn.close()


@app.on_event("startup")
async def _print_welcome():
    print("")
    print("=" * 60)
    print("📡  EnergyWizard telemetri-samlare är igång!")
    print(f"    Lagrar i {DB_PATH} - bara det betatestare själva slagit på.")
    print("=" * 60)
    print("")


def _str_field(d: dict, key: str, max_len: int = 200) -> str:
    v = d.get(key)
    return str(v)[:max_len] if v is not None else ""


PING_MARK = "~ping"


@app.post("/ingest/drivers")
async def ingest_drivers(request: Request):
    body = await request.json()
    house = _str_field(body, "house", 64)
    version = _str_field(body, "version", 64)
    is_new_house = False
    with _db() as c:
        c.execute(
            "INSERT INTO driver_snapshots (received_at, house, version, drivers, ts) VALUES (?, ?, ?, ?, ?)",
            (
                datetime.now(timezone.utc).isoformat(),
                house,
                version,
                # Anonymt livstecken (telemetrin av, smartbox/telemetry.py send_ping): bara ID + version
                PING_MARK if body.get("ping") is True else ",".join(str(x) for x in (body.get("drivers") or []))[:2000],
                _str_field(body, "ts", 64),
            ),
        )
        if house:
            existing = c.execute("SELECT 1 FROM known_houses WHERE house = ?", (house,)).fetchone()
            if not existing:
                c.execute("INSERT INTO known_houses (house, first_seen) VALUES (?, ?)",
                          (house, datetime.now(timezone.utc).isoformat()))
                is_new_house = True
    if is_new_house:
        _send_new_install_email(house, version)
    return {"ok": True}


@app.post("/ingest/error")
async def ingest_error(request: Request):
    body = await request.json()
    house = _str_field(body, "house", 64)
    version = _str_field(body, "version", 64)
    module = _str_field(body, "module", 100)
    error_type = _str_field(body, "error_type", 100)
    support = body.get("support")
    # #227: sanera igen här (skydd i två lager) innan utdraget kan hamna i ett offentligt ärende
    support_txt = log_scrub.scrub(str(support)[:60000]) if isinstance(support, str) and support.strip() else ""
    now = datetime.now(timezone.utc).isoformat()
    with _db() as c:
        c.execute(
            "INSERT INTO errors (received_at, house, version, module, error_type, ts, has_support) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (now, house, version, module, error_type, _str_field(body, "ts", 64), 1 if support_txt else 0),
        )
        if support_txt:
            c.execute(
                "INSERT INTO error_support (received_at, house, version, module, error_type, support) VALUES (?, ?, ?, ?, ?, ?)",
                (now, house, version, module, error_type, support_txt),
            )
    return {"ok": True}


@app.get("/api/recent")
async def recent(request: Request, limit: int = 50):
    if not _token_ok(request):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    limit = max(1, min(limit, 500))
    with _db() as c:
        drivers = c.execute(
            "SELECT received_at, house, version, drivers FROM driver_snapshots ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        errors = c.execute(
            "SELECT received_at, house, version, module, error_type FROM errors ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return JSONResponse({
        "driver_snapshots": [{"received_at": r[0], "house": r[1], "version": r[2], "drivers": r[3].split(",") if r[3] else []} for r in drivers],
        "errors": [{"received_at": r[0], "house": r[1], "version": r[2], "module": r[3], "error_type": r[4]} for r in errors],
    })


STATS_TOKEN = os.environ.get("STATS_TOKEN", "").strip()   # satt: /api/stats och /api/recent kräver X-Stats-Token


def _token_ok(request: Request) -> bool:
    import hmac
    return not STATS_TOKEN or hmac.compare_digest(request.headers.get("X-Stats-Token", ""), STATS_TOKEN)


ACTIVE_DAYS = 3          # smartbox skickar översikten varje dygn: hörd inom 3 dygn = aktiv


def _is_real_house(h: str) -> bool:
    """Riktiga hus är sha256-prefix (16 hextecken); testposter ("testverify", "smtptest") räknas inte."""
    return len(h) == 16 and all(c in "0123456789abcdef" for c in h)


def _norm(rest: str) -> str:
    """'easee@Easee' -> 'easee': märket är samma som drivrutinens namn och ska inte ge en egen rad."""
    drv, _, brand = rest.partition("@")
    maker, _, model = brand.partition("#")             # "Easee#Home" = märke + modell
    b = maker.lower().replace(" ", "")
    same = brand and (b.startswith(drv.lower()) or drv.lower().startswith(b))
    if same:
        return f"{drv}@{maker}#{model}" if model else drv
    return rest


# Kategorier som beskriver husets utrustning (inte inställningar, temperaturer eller märkesdetaljer som kan bli
# rikare mellan versioner): samma uppsättning = samma hus.
_EQUIPMENT = ("heatpump", "solar", "battery", "car", "charger", "meter", "spa", "size", "country")


def _fingerprint(drivers: list) -> frozenset:
    out = set()
    for d in drivers:
        cat, _, rest = d.partition(":")
        if cat in _EQUIPMENT:
            out.add(f"{cat}:{rest.partition('@')[0]}")
    return frozenset(out)


def _merge_reinstalls(latest: dict, first: dict, last_seen: dict) -> dict:
    """Samma hus med nytt installations-ID (ominstallation, tappad datamapp, eller före 1.2.40 ett ID som kunde
    skrivas över): ett äldre hus som tystnat innan ett nytt med exakt samma utrustning dök upp räknas som samma.
    Kräver minst fem utrustningsdelar, så att två vanliga hus med t.ex. bara en elmätare aldrig slås ihop.
    Tar bort det äldre ur latest och returnerar {nytt hus: [äldre hus ...]}. Inga IP-adresser används."""
    merged = {}
    order = sorted(latest, key=lambda h: first.get(h, ""))
    for i, old in enumerate(order):
        fp = _fingerprint(latest[old][1])
        if len(fp) < 5:
            continue
        for new in order[i + 1:]:
            if new in latest and _fingerprint(latest[new][1]) == fp and last_seen.get(old, "") <= first.get(new, ""):
                merged.setdefault(new, []).extend([old] + merged.pop(old, []))
                latest.pop(old)
                break
    return merged


@app.get("/api/stats")
async def stats(request: Request, me: str = ""):
    """Sammanställning för Emils dashboard: antal aktiva installationer och vilken utrustning de kör.
    Bara räknetal per kategori/drivrutin/märke - inga husidentifierare."""
    from datetime import timedelta
    if not _token_ok(request):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    since = (datetime.now(timezone.utc) - timedelta(days=ACTIVE_DAYS)).isoformat()
    with _db() as c:
        known = [r[0] for r in c.execute("SELECT house FROM known_houses")]
        rows = c.execute(
            "SELECT house, version, drivers, received_at FROM driver_snapshots WHERE received_at >= ? ORDER BY id", (since,)).fetchall()
        first = {r[0]: r[1] for r in c.execute("SELECT house, first_seen FROM known_houses")}
        errs = {}
        # Bara fel som fortfarande uppstår: motorn rapporterar ett kvarstående fel en gång i timmen
        # (smartbox/telemetry.py ERROR_REPEAT), så det som inte setts på 75 minuter har upphört
        recent = (datetime.now(timezone.utc) - timedelta(minutes=75)).isoformat()
        for h, ver, mod, et in c.execute("SELECT DISTINCT house, version, module, error_type FROM errors WHERE received_at >= ?", (recent,)):
            if et in ENV_ERROR_TYPES:                      # användarens miljö, inte ett fel hos oss
                continue
            errs.setdefault(h, []).append((ver, f"{mod}: {et}"))
    latest, last_seen = {}, {}
    for house, version, drivers, at in rows:
        if _is_real_house(house):
            latest[house] = (version, [d for d in (drivers or "").split(",") if d and d != PING_MARK],
                             drivers == PING_MARK)
            last_seen[house] = at
    merged = _merge_reinstalls(latest, first, last_seen)
    # När varje version först sågs (hos något hus): de som dök upp inom 2 dygn från den nyaste räknas som aktuella
    with _db() as c:
        vfirst = {v: t for v, t in c.execute("SELECT version, min(received_at) FROM driver_snapshots WHERE version IS NOT NULL GROUP BY version")}
        egroups = {}
        recent48 = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        for h, ver, mod, et, rec in c.execute("SELECT house, version, module, error_type, received_at FROM errors WHERE received_at >= ?", (recent48,)):
            if not _is_real_house(h) or et in ENV_ERROR_TYPES:
                continue
            g = egroups.setdefault(f"{mod}: {et}", {"key": f"{mod}: {et}", "houses": set(), "versions": set(), "last": rec, "reports": 0})
            g["houses"].add(h); g["versions"].add(ver or "okänd"); g["reports"] += 1; g["last"] = max(g["last"], rec)
    live_versions = [vfirst.get(v[0]) for v in latest.values() if vfirst.get(v[0])]
    newest = max(live_versions) if live_versions else None
    def _current(ver):
        t = vfirst.get(ver)
        if not t or not newest:
            return None
        return (datetime.fromisoformat(newest) - datetime.fromisoformat(t)) <= timedelta(hours=48)
    equipment, versions = {}, {}
    for version, drivers, _ in latest.values():
        versions[version or "okänd"] = versions.get(version or "okänd", 0) + 1
        for d in drivers:                     # enheter, inte hus: två Easee-boxar i samma hus räknas som 2
            cat, _, rest = d.partition(":")
            rest = _norm(rest)
            equipment.setdefault(cat, {})
            equipment[cat][rest] = equipment[cat].get(rest, 0) + 1
    # Per installation, anonymt (Hus 1, 2 ... i den ordning de dök upp) - inga husidentiteter i svaret.
    # me = anroparens eget hash (webben räknar fram det ur sin house_id) markerar "ditt hus".
    houses = []
    since = {h: min([first.get(h) or ""] + [first.get(o) or "" for o in merged.get(h, [])]) for h in latest}
    for i, h in enumerate(sorted(latest, key=lambda x: since[x]), start=1):
        devs = {}
        for d in latest[h][1]:
            cat, _, rest = d.partition(":")
            devs.setdefault(cat, []).append(_norm(rest))
        houses.append({"label": f"Hus {i}", "since": since[h][:10],
                       "reinstalls": len(merged.get(h, [])), "last_seen": last_seen.get(h), "current": _current(latest[h][0]), "mine": bool(me) and h == me, "devices": devs,
                       "ping_only": latest[h][2],     # bara anonymt livstecken (telemetrin av): ID + version
                       # Bara fel från husets nuvarande version: ett fel som rättats i en senare version försvinner
                       # när huset uppdaterats, i stället för att ligga kvar ett dygn
                       "version": latest[h][0], "errors": sorted({e for v, e in errs.get(h, []) if v == latest[h][0]})})
    week = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    return {
        "active": len(latest),
        "active_days": ACTIVE_DAYS,
        "total_known": sum(1 for h in known if _is_real_house(h)) - sum(len(v) for v in merged.values()),
        "new_last_7d": sum(1 for h, f in first.items() if _is_real_house(h) and f >= week)
                       - sum(1 for v in merged.values() for o in v if (first.get(o) or "") >= week),
        "merged_reinstalls": sum(len(v) for v in merged.values()),
        "current_versions": sum(1 for v in latest.values() if _current(v[0])),
        "error_groups": sorted(({"key": g["key"], "houses": len(g["houses"]), "versions": sorted(g["versions"]), "last": g["last"],
                                 "reports": g["reports"]} for g in egroups.values()), key=lambda x: (-x["houses"], -x["reports"])),
        "without_devices": sum(1 for _, d, p in latest.values() if not d and not p),
        "ping_only": sum(1 for _, _, p in latest.values() if p),
        "equipment": {cat: dict(sorted(v.items(), key=lambda kv: -kv[1])) for cat, v in sorted(equipment.items())},
        "versions": versions,
        "houses": houses,
    }


@app.get("/api/error-groups")
async def error_groups(request: Request, days: int = 14):
    """Felen grupperade per modul + feltyp, för skriptet som gör GitHub-issues av dem (ops/gh_error_issues.sh).
    Bara antal hus, versioner och tider - aldrig vilka hus. #227: senaste sanerade supportutdraget per grupp."""
    from datetime import timedelta
    if not _token_ok(request):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    since = (datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 90)))).isoformat()
    groups = {}
    with _db() as c:
        for rec, house, version, module, et in c.execute(
                "SELECT received_at, house, version, module, error_type FROM errors WHERE received_at >= ? ORDER BY id", (since,)):
            if not _is_real_house(house) or et in ENV_ERROR_TYPES:
                continue
            g = groups.setdefault(f"{module}: {et}", {"module": module, "error_type": et, "houses": set(), "versions": set(),
                                                      "first": rec, "last": rec, "count": 0, "support": ""})
            g["houses"].add(house)
            g["versions"].add(version or "okänd")
            g["last"] = rec
            g["count"] += 1
        # Senaste supportutdraget per (module, error_type), utan hus-ID i svaret
        for module, et, support in c.execute(
                "SELECT module, error_type, support FROM error_support WHERE received_at >= ? ORDER BY id DESC",
                (since,)):
            key = f"{module}: {et}"
            if key in groups and not groups[key]["support"] and support:
                # Strip accidental house hashes if a client ever included them
                cleaned = "\n".join(
                    ln for ln in str(support).splitlines()
                    if not (len(ln.strip()) == 16 and all(ch in "0123456789abcdef" for ch in ln.strip()))
                )[-30000:]
                groups[key]["support"] = cleaned
    out = [{"key": k, "module": g["module"], "error_type": g["error_type"], "houses": len(g["houses"]),
            "versions": sorted(g["versions"]), "first": g["first"], "last": g["last"], "reports": g["count"],
            "support": g.get("support") or ""}
           for k, g in groups.items()]
    return {"groups": sorted(out, key=lambda x: (-x["houses"], x["key"]))}


@app.get("/api/ping")
async def ping():
    return {"ok": True}
