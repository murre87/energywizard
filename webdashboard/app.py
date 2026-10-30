"""EnergyWizard Webdashboard: ny dator-/surfplatte-dashboard, ersätter smartdashboard
(Streamlit) stegvis (EnergyWizard Open, Fas A-F - se /home/emil/.claude/plans/
glowing-moseying-octopus.md). Byggd på samma mönster som ewapp (FastAPI, inget
byggsteg, delad databas) men med en desktop-layout (sidomeny, flera sidor samtidigt
synliga, vanlig scroll) istället för ewapp:s enda-skärm-mobillayout.

Fas A: bara inloggning (delad med ewapp via smartbox/webauth.py), sidomeny-skal med
alla 13 planerade sidor, och en testgraf som bevisar att ECharts-pipen fungerar.
Ingen sida har riktigt innehåll än - det är Fas B och framåt.
"""
import math
import os
import sys
import time

import requests

sys.path.insert(0, "/smartbox")
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine, text

import webauth

WATCHTOWER_URL = os.environ.get("WATCHTOWER_URL", "http://host.docker.internal:8090")
WATCHTOWER_TOKEN = os.environ.get("WATCHTOWER_API_TOKEN", "")
# /v1/check gör en riktig registry-koll (tar ~5s) - cachas här så "System"-sidan
# inte startar om den varje gång sidan öppnas.
_wt_cache = {"ts": 0, "data": None}
WT_CACHE_TTL = 600

ENGINE = create_engine(
    f"postgresql+psycopg://{os.environ['POSTGRES_USER']}:{os.environ['POSTGRES_PASSWORD']}@{os.environ.get('POSTGRES_HOST', 'postgres-smartbox')}/{os.environ['POSTGRES_DB']}",
    pool_pre_ping=True, pool_size=3,
)

# Eget salt ("webdash") -> egen cookie-scope, skild session från ewapp även om PASSWORD
# är detsamma. family-rollen har inga skriv-vägar än (Fas A har inga formulär alls).
AUTH = webauth.Auth(salt="webdash", family_write_prefixes=())

# De 13 sidorna enligt inventeringen av smartdashboard (se planfilen) - tomma till Fas B+.
PAGES = [
    {"id": "oversikt", "name": "Översikt", "icon": "📊"},
    {"id": "ekonomi", "name": "Ekonomi", "icon": "💰"},
    {"id": "elforbrukning", "name": "Elförbrukning", "icon": "🔌"},
    {"id": "elbil", "name": "Elbil", "icon": "⚡"},
    {"id": "varmepump", "name": "Värmepump", "icon": "♨️"},
    {"id": "solceller", "name": "Solceller", "icon": "☀️"},
    {"id": "spabad", "name": "Spabad", "icon": "🛁"},
    {"id": "temperaturer", "name": "Temperaturer", "icon": "🌡️"},
    {"id": "prognos", "name": "Prognos", "icon": "📅"},
    {"id": "historik", "name": "Historik", "icon": "📈"},
    {"id": "installningar", "name": "Inställningar", "icon": "⚙️"},
    {"id": "aviseringar", "name": "Aviseringar", "icon": "🔔"},
    {"id": "system", "name": "System", "icon": "🛠️"},
]

app = FastAPI(title="EnergyWizard Webdashboard")


@app.middleware("http")
async def guard(request: Request, call_next):
    err = AUTH.guard_response(request)
    if err is not None:
        return err
    resp = await call_next(request)
    resp.headers.update(webauth.SECURITY_HEADERS)
    if request.url.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.post("/api/login")
async def login(request: Request):
    return await AUTH.login(request)


@app.post("/api/logout")
async def logout():
    return AUTH.logout()


@app.get("/api/me")
async def me(request: Request):
    role, user = AUTH.session(request)
    return {"role": role, "user": user, "pages": PAGES}


@app.get("/api/ping")
async def ping():
    """Bevisar att databaskopplingen fungerar - samma ENGINE-mönster som ewapp/smartbox."""
    with ENGINE.connect() as c:
        c.exec_driver_sql("SELECT 1")
    return {"ok": True, "ts": int(time.time())}


def _n(v, default=None):
    """None/NaN-säker talkonvertering - sensor_log har gott om NULL/NaN."""
    try:
        f = float(v)
        return default if math.isnan(f) else f
    except (TypeError, ValueError):
        return default


def _is_high_load_time(dt):
    """Samma regel som smartbox/settings.py:is_high_load_time - inlinad här hellre än att
    dra in hela settings.py:s tunga importkedja (pandas/psycopg_pool/...) för en rad logik."""
    return dt.month in (11, 12, 1, 2, 3) and dt.weekday() <= 4 and 7 <= dt.hour < 20


def _temp_target(conn, mode: str) -> float:
    row = conn.execute(text("SELECT temp_cheap, temp_expensive FROM system_settings WHERE id = 1")).fetchone()
    cheap, expensive = (row[0], row[1]) if row else (None, None)
    return float(cheap if cheap is not None else 22.0) if mode == "CHEAP" else float(expensive if expensive is not None else 20.0)


def _heat_battery(row) -> dict | None:
    """Varmvattenberedaren som ett termiskt batteri: laddnivå = var water_temp ligger
    mellan husets EGNA aktuella golv (water_start_temp) och tak (water_setpoint) -
    samma gränser gpm.py Prio 4.5 redan styr mot, inte hårdkodade konstanter."""
    water_temp = _n(row.get("water_temp"))
    floor = _n(row.get("water_start_temp"))
    ceiling = _n(row.get("water_setpoint"))
    if water_temp is None or floor is None or ceiling is None or ceiling <= floor:
        return None
    charge_pct = max(0.0, min(100.0, (water_temp - floor) / (ceiling - floor) * 100.0))
    compressor_running = bool(row.get("compressor_running"))
    if compressor_running:
        status = "Laddar"
    elif charge_pct >= 95:
        status = "Vilar"
    else:
        status = "Tömmer"
    return {"charge_pct": round(charge_pct, 0), "status": status, "water_temp": water_temp, "floor": floor, "ceiling": ceiling}


@app.get("/api/overview")
async def overview(request: Request):
    """Fas B, sida 1 (Översikt): beslutsbanner + de åtta nyckeltalen, portade från
    smartdashboard/app.py:s page_overview() (samma SQL, samma fält - bara flyttat
    bakom ett JSON-API istället för Streamlit-rendering)."""
    with ENGINE.connect() as c:
        row = c.execute(text(
            "SELECT *, timestamp AT TIME ZONE 'Europe/Stockholm' AS sthlm_time FROM sensor_log ORDER BY timestamp DESC LIMIT 1"
        )).mappings().first()
        price_hist = c.execute(text(
            "SELECT time_start, sek_per_kwh FROM elpriser WHERE time_start >= now() - interval '24 hours' ORDER BY time_start"
        )).fetchall()
        if row is None:
            return {"ok": False, "error": "Ingen data i sensor_log än"}
        mode = str(row.get("active_mode") or "").upper()
        target_room = _temp_target(c, mode)
    is_high_load = _is_high_load_time(row["sthlm_time"])

    return {
        "ok": True,
        "mode": mode,
        "decision": row.get("active_decision") or "Utvärderar…",
        "price": _n(row.get("price")),
        "indoor_temp": _n(row.get("indoor_temp")),
        "indoor_target": target_room,
        "indoor_humidity": _n(row.get("indoor_humidity")),
        "outdoor_temp": _n(row.get("outdoor_temp")),
        "net_power_w": _n(row.get("net_power")),
        "pv_power_w": _n(row.get("pv_power_w")),
        "water_temp": _n(row.get("water_temp")),
        "ev_power_kw": _n(row.get("ev_power_kw")),
        "is_high_load": is_high_load,
        "sthlm_time": str(row["sthlm_time"]),
        "price_24h": [{"t": r[0].isoformat(), "p": float(r[1])} for r in price_hist],
        "heat_battery": _heat_battery(row),
    }


@app.get("/api/updates")
async def updates(request: Request, force: bool = False):
    """System-sidan: vilka containrar på hela NUC:en (inte bara EnergyWizard) har en
    nyare image enligt Watchtower. Cachas 10 min - force=1 kollar om direkt."""
    now = time.time()
    if force or _wt_cache["data"] is None or now - _wt_cache["ts"] > WT_CACHE_TTL:
        try:
            r = requests.post(
                f"{WATCHTOWER_URL}/v1/check",
                headers={"Authorization": f"Bearer {WATCHTOWER_TOKEN}"},
                timeout=30,
            )
            r.raise_for_status()
            _wt_cache["data"] = r.json()
            _wt_cache["ts"] = now
        except requests.RequestException as e:
            if _wt_cache["data"] is None:
                return {"ok": False, "error": f"Kunde inte nå Watchtower: {e}"}
    containers = _wt_cache["data"].get("containers", [])
    pending = [c["name"] for c in containers if c.get("update_available")]
    return {
        "ok": True,
        "checked_at": _wt_cache["ts"],
        "total": len(containers),
        "pending": sorted(pending),
    }


app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/{full_path:path}")
async def spa(full_path: str):
    return FileResponse("static/index.html")
