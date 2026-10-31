"""EnergyWizard Webdashboard: ny dator-/surfplatte-dashboard, ersätter smartdashboard
(Streamlit) stegvis (EnergyWizard Open, Fas A-F - se /home/emil/.claude/plans/
glowing-moseying-octopus.md). Byggd på samma mönster som ewapp (FastAPI, inget
byggsteg, delad databas) men med en desktop-layout (sidomeny, flera sidor samtidigt
synliga, vanlig scroll) istället för ewapp:s enda-skärm-mobillayout.

Fas A: bara inloggning (delad med ewapp via smartbox/webauth.py), sidomeny-skal med
alla 13 planerade sidor, och en testgraf som bevisar att ECharts-pipen fungerar.
Ingen sida har riktigt innehåll än - det är Fas B och framåt.
"""
import asyncio
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
import discovery
import house_config
import pump

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
    elif request.url.path.startswith("/static/") or request.url.path == "/":
        # Statiska filer (JS/CSS/HTML) ska alltid hämtas om - annars ser man kvarbliven
        # gammal kod efter en uppdatering tills man själv tömmer webbläsarens cache
        # (upptäckt 2026-10-31 - samma fix som ewapp redan hade för sina statiska filer).
        resp.headers["Cache-Control"] = "no-cache"
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


@app.post("/api/discover")
async def api_discover():
    """Entitetsväljare (Inställningar-sidan): skannar husets riktiga Home Assistant
    efter kandidat-entiteter per kategori. Live-anrop mot HA, bara på knapptryck -
    inte cachat/automatiskt som /api/overview."""
    try:
        return {"ok": True, **discovery.discover_house()}
    except Exception as e:
        return {"ok": False, "error": f"Kunde inte skanna Home Assistant: {e}"}


@app.post("/api/discover-modbus")
async def api_discover_modbus():
    """Eget, valfritt steg - söker efter en Husdata-värmepump på det lokala nätverket
    (för installationer utan PUMP_IP satt alls). EN RIKTIG nätverksoperation (probear
    andra enheter på användarens LAN), därför en separat knapp i gränssnittet, aldrig
    en del av /api/discover. Körs i tråd så den inte blockerar servern i upp till en
    minut (pump.scan_for_husdata gör ett blockerande nätverksanrop per kandidat-IP)."""
    try:
        found = await asyncio.to_thread(pump.scan_for_husdata)
        return {"ok": True, "found": found}
    except Exception as e:
        return {"ok": False, "error": f"Kunde inte söka på nätverket: {e}"}


def _yaml_str(v) -> str:
    return "null" if v is None else f'"{v}"'


def _build_house_config_yaml(sel: dict) -> str:
    """Bygger en riktig house_config.yaml-text från de BEKRÄFTADE valen frontend
    skickar in (samma form som discovery.discover_house() ger, men bara det
    användaren lämnat ikryssat). Fält discovery inte kan avgöra (Modbus-adress,
    fysisk laddarplats) lämnas som tydliga FYLL I-platshållare, inte gissade."""
    lines = ['house_id: "mitt-hus"   # byt gärna till något eget', ""]

    lines.append("evs:")
    cars = sel.get("cars") or []
    if not cars:
        lines[-1] = "evs: []"
    for i, c in enumerate(cars):
        car_id = c.get("id") or f"bil{i + 1}"
        lines.append(f"  - id: {car_id}")
        lines.append(f"    driver: {c.get('driver') or 'generic_ev'}")
        lines.append(f"    battery_kwh: {c.get('battery_kwh') or 60}  # FYLL I - din bils batteristorlek i kWh")
        lines.append("    entities:")
        if c.get("soc_entity"):
            lines.append(f"      soc: {c['soc_entity']}")
        if c.get("plugged_in_entity"):
            lines.append(f"      plugged_in: {c['plugged_in_entity']}")
        if c.get("climate_entity"):
            lines.append(f"      climate: {c['climate_entity']}")
        charger = c.get("charger")
        if charger:
            charger_driver = charger.get("driver") or "generic_charger"
            lines.append("    charger:")
            lines.append(f"      id: {charger.get('device_name') or car_id + '_laddare'}")
            lines.append(f"      driver: {charger_driver}  # ihopparningen bil<->laddare är en gissning (ordning på vad du kryssade i) - dubbelkolla den")
            if charger_driver == "easee":
                dn = (charger.get("device_name") or "").lower()
                guessed_physical = "carport" if "carport" in dn else "lite" if "lite" in dn else None
                if guessed_physical:
                    lines.append(f"      physical: {guessed_physical}  # gissat från enhetsnamnet '{charger.get('device_name')}' - dubbelkolla")
                else:
                    lines.append("      physical: lite  # FYLL I - vilken av dina Easee-boxar (lite/carport, bara namn - byt om du vill)")
            lines.append("      entities:")
            if charger.get("status_entity"):
                lines.append(f"        status: {charger['status_entity']}")
    lines.append("")

    hp = sel.get("heat_pump")
    if hp:
        lines += ["heat_pump:", "  enabled: true", f"  driver: {hp.get('driver') or 'generic_heatpump'}",
                   "  connection:", "    modbus_host: 192.168.1.XXX  # FYLL I - värmepumpens IP/gateway, kan inte upptäckas automatiskt",
                   "    modbus_port: 502", "    unit_id: 1"]
    else:
        lines += ["heat_pump:", "  enabled: false"]
    lines.append("")

    solar = sel.get("solar")
    if solar:
        lines += ["solar:", "  enabled: true", f"  driver: {solar.get('driver') or 'ha_entity_passthrough'}", "  entities:"]
        if solar.get("pv_power_entity"):
            lines.append(f"    pv_power_w: {solar['pv_power_entity']}")
        if solar.get("today_kwh_entity"):
            lines.append(f"    today_kwh: {solar['today_kwh_entity']}")
    else:
        lines += ["solar:", "  enabled: false"]
    lines.append("")

    spa = sel.get("spa")
    if spa:
        lines += ["spa:", "  enabled: true", f"  driver: {spa.get('driver') or 'generic_spa'}", "  entities:"]
        if spa.get("current_temp_entity"):
            lines.append(f"    current_temp: {spa['current_temp_entity']}")
        if spa.get("power_entity"):
            lines.append(f"    power_w: {spa['power_entity']}")
    else:
        lines += ["spa:", "  enabled: false"]
    lines += ["", "fuse:", "  main_fuse_a: 25  # FYLL I - din huvudsäkring i Ampere"]

    return "\n".join(lines) + "\n"


@app.post("/api/generate-house-config")
async def api_generate_house_config(request: Request):
    sel = await request.json()
    yaml_text = _build_house_config_yaml(sel)
    # Egenkontroll innan den lämnas ut: ska gå att läsa in och bygga drivrutiner
    # från, inte bara vara syntaktiskt rätt YAML - samma verktyg som redan finns.
    import tempfile
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=True) as f:
            f.write(yaml_text)
            f.flush()
            cfg = house_config.load_house_config(f.name)
            house_config.build_car_drivers(cfg)
            house_config.build_heat_pump_driver(cfg)
            house_config.build_solar_driver(cfg)
            house_config.build_spa_driver(cfg)
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"Den genererade filen gick inte att läsa in: {e}"}, status_code=500)
    from fastapi.responses import Response
    return Response(content=yaml_text, media_type="text/yaml",
                     headers={"Content-Disposition": "attachment; filename=house_config.yaml"})


app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/{full_path:path}")
async def spa(full_path: str):
    return FileResponse("static/index.html")
