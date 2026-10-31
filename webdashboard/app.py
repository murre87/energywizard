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
# "built": False döljs i menyn (se /api/me) tills sidan faktiskt har eget innehåll i
# app.js - en platshållarflik ("byggs i en senare fas") är precis det en betatestare
# tolkar som att allt är trasigt, så den ska aldrig synas i en skarp installation.
PAGES = [
    {"id": "oversikt", "name": "Översikt", "icon": "📊", "built": True},
    {"id": "ekonomi", "name": "Ekonomi", "icon": "💰", "built": True},
    {"id": "elforbrukning", "name": "Elförbrukning", "icon": "🔌", "built": True},
    {"id": "elbil", "name": "Elbil", "icon": "⚡", "built": True},
    {"id": "varmepump", "name": "Värmepump", "icon": "♨️", "built": True},
    {"id": "solceller", "name": "Solceller", "icon": "☀️", "built": True},
    {"id": "spabad", "name": "Spabad", "icon": "🛁", "built": True},
    {"id": "temperaturer", "name": "Temperaturer", "icon": "🌡️", "built": True},
    {"id": "prognos", "name": "Prognos", "icon": "📅", "built": True},
    {"id": "historik", "name": "Historik", "icon": "📈", "built": True},
    {"id": "installningar", "name": "Inställningar", "icon": "⚙️", "built": True},
    {"id": "aviseringar", "name": "Aviseringar", "icon": "🔔", "built": True},
    {"id": "system", "name": "System", "icon": "🛠️", "built": True},
]

app = FastAPI(title="EnergyWizard Webdashboard")


@app.on_event("startup")
async def _print_welcome():
    """Skriver ut adressen i docker-loggarna direkt vid start, samma mönster som
    ha-gateway/print-url.sh - annars är README den ENDA platsen en ny användare kan
    hitta adressen, och det kräver att man redan vet att man ska leta där. Kan inte
    räkna ut värdens egen LAN-IP pålitligt inifrån en bridge-nätverkad container
    (containerns egen IP är inte samma sak, skulle bli missvisande) - ärligt
    generiskt istället för en gissning som ser exakt ut men kan vara fel."""
    print("")
    print("=" * 66)
    print("🔆  EnergyWizard webdashboard är igång!")
    print("    Besök http://<din-servers-lokala-IP>:8503 i webbläsaren")
    print("    (hittar du inte IP:n? \"ip addr\" på servern, eller din routers DHCP-lista)")
    print("=" * 66)
    print("")


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
    return {"role": role, "user": user, "pages": [p for p in PAGES if p["built"]]}


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


def _latest_row(c):
    """Senaste raden i sensor_log som dict - delad av alla de nya datasidorna nedan
    istället för att varje endpoint skriver om samma SELECT * ... LIMIT 1."""
    row = c.execute(text(
        "SELECT *, timestamp AT TIME ZONE 'Europe/Stockholm' AS sthlm_time FROM sensor_log ORDER BY timestamp DESC LIMIT 1"
    )).mappings().first()
    return dict(row) if row else None


def _price_24h(c):
    rows = c.execute(text(
        "SELECT time_start, sek_per_kwh FROM elpriser WHERE time_start >= now() - interval '24 hours' ORDER BY time_start"
    )).fetchall()
    return [{"t": r[0].isoformat(), "p": float(r[1])} for r in rows]


@app.get("/api/car")
async def api_car():
    """Elbil-sidan: SoC/laddstatus för båda bilarna + dagens schema (ev_charging_schedule)
    och planerade laddningspass (ev_plan_slots, summeras bara - full passplan hör hemma
    i ewapp:s egen editor, inte duplicerad här)."""
    with ENGINE.connect() as c:
        row = _latest_row(c)
        if row is None:
            return {"ok": False, "error": "Ingen data i sensor_log än"}
        today_dow = time.localtime().tm_wday
        sched = c.execute(text(
            "SELECT car_id, target_time, target_soc, enabled FROM ev_charging_schedule WHERE day_of_week = :d"
        ), {"d": today_dow}).mappings().all()
        planned = c.execute(text(
            "SELECT car_id, SUM(kw) AS kwh FROM ev_plan_slots WHERE t_slot::date = CURRENT_DATE GROUP BY car_id"
        )).mappings().all()
    planned_by_car = {p["car_id"]: _n(p["kwh"]) for p in planned}
    cars = [
        {"id": "tesla", "name": "Tesla Model Y", "soc": _n(row.get("tesla_soc")), "stale": bool(row.get("tesla_soc_stale")),
         "power_kw": _n(row.get("ev_power_kw")), "status": row.get("ev_status"),
         "climate_temp": _n(row.get("tesla_climate_temp")), "climate_state": row.get("tesla_climate_state")},
        {"id": "nissan", "name": "Nissan Leaf", "soc": _n(row.get("nissan_soc")), "stale": bool(row.get("nissan_soc_stale")),
         "power_kw": _n(row.get("ev_carport_power_kw")), "status": row.get("ev_carport_status"),
         "climate_temp": _n(row.get("nissan_climate_temp")), "climate_state": row.get("nissan_climate_state")},
    ]
    for car in cars:
        car["planned_kwh_today"] = planned_by_car.get(car["id"])
    schedule = [{"car_id": s["car_id"], "target_time": str(s["target_time"]) if s["target_time"] else None,
                 "target_soc": s["target_soc"], "enabled": s["enabled"]} for s in sched]
    return {"ok": True, "cars": cars, "session_kwh": _n(row.get("ev_session_kwh")),
            "current_a": _n(row.get("ev_current_a")), "dynamic_limit_a": _n(row.get("ev_dynamic_limit_a")),
            "current_target_limit": _n(row.get("current_target_limit")), "schedule_today": schedule}


@app.get("/api/solar")
async def api_solar():
    """Solceller-sidan: produktion, dagens energi, exportgräns och husbatteriet - allt
    redan loggat av smartbox i sensor_log varje cykel, ingen live HA-fråga behövs."""
    with ENGINE.connect() as c:
        row = _latest_row(c)
        if row is None:
            return {"ok": False, "error": "Ingen data i sensor_log än"}
        price_24h = _price_24h(c)
    return {"ok": True, "pv_power_w": _n(row.get("pv_power_w")), "solar_today_kwh": _n(row.get("solar_today_kwh")),
            "solar_forecast_w": _n(row.get("solar_forecast_w")), "solar_limit_pct": _n(row.get("solar_limit_pct")),
            "inverter_status": row.get("inverter_status"), "battery_soc": _n(row.get("battery_soc")),
            "battery_power_w": _n(row.get("battery_power_w")), "net_power_w": _n(row.get("net_power")),
            "price": _n(row.get("price")), "price_24h": price_24h}


@app.get("/api/economy")
async def api_economy():
    """Ekonomi-sidan: dagens pris (min/medel/max) och en uppskattad kostnad hittills
    idag (ackumulerad förbrukning × dagens snittpris) - en grov uppskattning, inte en
    exakt timme-för-timme-kostnad, och tydligt märkt som sådan i gränssnittet."""
    with ENGINE.connect() as c:
        row = _latest_row(c)
        if row is None:
            return {"ok": False, "error": "Ingen data i sensor_log än"}
        today_prices = c.execute(text(
            "SELECT sek_per_kwh FROM elpriser WHERE time_start::date = CURRENT_DATE"
        )).fetchall()
        price_24h = _price_24h(c)
    prices = [float(r[0]) for r in today_prices if r[0] is not None]
    avg_price = sum(prices) / len(prices) if prices else None
    consumption = _n(row.get("accumulated_consumption_kwh"))
    est_cost = round(consumption * avg_price, 2) if consumption is not None and avg_price is not None else None
    return {"ok": True, "price": _n(row.get("price")), "price_min": min(prices) if prices else None,
            "price_avg": avg_price, "price_max": max(prices) if prices else None,
            "accumulated_consumption_kwh": consumption, "est_cost_today": est_cost, "price_24h": price_24h}


@app.get("/api/consumption")
async def api_consumption():
    """Elförbrukning-sidan: fasströmmar/effekt just nu + senaste förklarade uppdelningen
    (load_breakdown - EV/pump/spa/oförklarat) och effektvaktens status."""
    with ENGINE.connect() as c:
        row = _latest_row(c)
        if row is None:
            return {"ok": False, "error": "Ingen data i sensor_log än"}
        lb = c.execute(text(
            "SELECT total_w, ev_w, pump_w, spa_w, unexplained_w FROM load_breakdown ORDER BY timestamp DESC LIMIT 1"
        )).mappings().first()
    return {"ok": True, "avg_w_l1": _n(row.get("avg_w_l1")), "avg_w_l2": _n(row.get("avg_w_l2")),
            "avg_w_l3": _n(row.get("avg_w_l3")), "avg_w_tot": _n(row.get("avg_w_tot")),
            "house_consumption_w": _n(row.get("house_consumption_w")), "power_oven_w": _n(row.get("power_oven_w")),
            "power_computer_w": _n(row.get("power_computer_w")), "peak_shaving_active": bool(row.get("peak_shaving_active")),
            "predicted_base_load_kw": _n(row.get("predicted_base_load_kw")),
            "breakdown": {k: _n(lb[k]) for k in ("total_w", "ev_w", "pump_w", "spa_w", "unexplained_w")} if lb else None}


@app.get("/api/spa")
async def api_spa():
    """Spabad-sidan: temperatur, mål, värmarstatus och signalstyrka (RF-kanal till
    styrenheten) - direkt ur sensor_log, samma fält gpm.py redan styr mot."""
    with ENGINE.connect() as c:
        row = _latest_row(c)
    if row is None:
        return {"ok": False, "error": "Ingen data i sensor_log än"}
    return {"ok": True, "temp": _n(row.get("spa_temp")), "target": _n(row.get("spa_target")),
            "heater_running": bool(row.get("spa_heater_running")), "power_w": _n(row.get("spa_power_w")),
            "signal_pct": _n(row.get("spa_signal_pct")), "rf_channel": _n(row.get("spa_rf_channel"))}


ROOMS = [("temp_vardagsrum", "Vardagsrum"), ("temp_masterbedroom", "Sovrum"), ("temp_barnrum_nere", "Barnrum nere"),
         ("temp_cesars_rum", "Cesars rum"), ("temp_isacs_rum", "Isacs rum"), ("temp_utbyggnad", "Utbyggnad"),
         ("temp_tvattstuga", "Tvättstuga"), ("temp_friggebod", "Friggebod"), ("temp_garage", "Garage"),
         ("temp_matter_1", "Sensor Matter 1"), ("temp_matter_2", "Sensor Matter 2"), ("temp_matter_3", "Sensor Matter 3"),
         ("temp_esp", "ESP-sensor")]


@app.get("/api/temperatures")
async def api_temperatures():
    """Temperaturer-sidan: samma rumslista som ewapp:s /api/rooms (ROOMS ovan är en
    medveten kopia, inte en delad import - webdashboard har ingen HA-koppling att
    dela, bara sensor_log)."""
    with ENGINE.connect() as c:
        row = _latest_row(c)
    if row is None:
        return {"ok": False, "error": "Ingen data i sensor_log än"}
    rooms = [{"name": n, "temp": _n(row.get(col))} for col, n in ROOMS]
    return {"ok": True, "indoor_temp": _n(row.get("indoor_temp")), "outdoor_temp": _n(row.get("outdoor_temp")),
            "indoor_humidity": _n(row.get("indoor_humidity")), "rooms": [r for r in rooms if r["temp"] is not None],
            "vent_supply_temp": _n(row.get("vent_supply_temp")), "vent_exhaust_temp": _n(row.get("vent_exhaust_temp")),
            "vent_setpoint_c": _n(row.get("vent_setpoint_c"))}


@app.get("/api/forecast")
async def api_forecast():
    """Prognos-sidan: kommande väder (weather_forecast) och kommande elpriser (elpriser) -
    samma tabeller gpm.py redan planerar mot, bara en vy på dem."""
    with ENGINE.connect() as c:
        weather = c.execute(text(
            "SELECT timestamp, temp, cloud_cover, wind_speed, rain_probability, thunder_probability "
            "FROM weather_forecast WHERE timestamp >= now() ORDER BY timestamp LIMIT 48"
        )).mappings().all()
        prices = c.execute(text(
            "SELECT time_start, sek_per_kwh FROM elpriser WHERE time_start >= now() ORDER BY time_start LIMIT 48"
        )).fetchall()
    return {"ok": True,
            "weather": [{"t": w["timestamp"].isoformat(), "temp": _n(w["temp"]), "cloud_cover": _n(w["cloud_cover"]),
                         "wind_speed": _n(w["wind_speed"]), "rain_probability": _n(w["rain_probability"]),
                         "thunder_probability": _n(w["thunder_probability"])} for w in weather],
            "prices": [{"t": r[0].isoformat(), "p": float(r[1])} for r in prices]}


@app.get("/api/historylog")
async def api_historylog():
    """Historik-sidan: ew_log (familjelogg + systemhändelser) - de senaste 80 posterna,
    nyast först."""
    with ENGINE.connect() as c:
        rows = c.execute(text("SELECT ts, usr, txt FROM ew_log ORDER BY ts DESC LIMIT 80")).fetchall()
    return {"ok": True, "entries": [{"ts": r[0].isoformat(), "user": r[1], "text": r[2]} for r in rows]}


NOTIFY_LABELS = {
    "notify_spa_boost": "Spabadet värmer extra (boost)", "notify_spa_reconnect": "Spabadet tappade kontakten och är tillbaka",
    "notify_ev_full": "Elbilen är fulladdad", "notify_price_tip": "Pristips (ovanligt billig/dyr timme)",
    "notify_high_low": "Höglast/baslast byter", "notify_peak_shaving": "Effektvakten griper in",
    "notify_pump_alarm": "Värmepumpen larmar", "notify_pump_mode": "Värmepumpen byter läge",
    "notify_solar_error": "Solcellsväxelriktaren svarar inte", "notify_solar_limit": "Solexporten begränsas/släpps",
    "notify_mower_mowing": "Robotgräsklipparen klipper", "notify_mower_charging": "Robotgräsklipparen laddar",
    "notify_mower_idle": "Robotgräsklipparen vilar", "notify_mower_weather": "Robotgräsklipparen pausar pga väder",
    "notify_mower_manual": "Robotgräsklipparen körs manuellt", "notify_mower_failsafe": "Robotgräsklipparens failsafe",
}


@app.get("/api/notifications")
async def api_notifications():
    """Aviseringar-sidan: nuvarande på/av-läge för varje aviseringstyp (overrides-
    tabellen, delad med ewapp - samma device/mode-par ewapp:s /api/energy-action:notify
    redan skriver till, bara en läsvy här)."""
    with ENGINE.connect() as c:
        rows = c.execute(text("SELECT device, mode FROM overrides WHERE device LIKE 'notify_%'")).fetchall()
    items = [{"key": r[0], "label": NOTIFY_LABELS.get(r[0], r[0]), "on": str(r[1]).lower() == "true"} for r in rows]
    items.sort(key=lambda i: i["label"])
    return {"ok": True, "items": items}


@app.post("/api/notifications/{key}")
async def set_notification(key: str, request: Request):
    """Växlar en aviseringstyp - samma overrides-tabell/semantik som ewapp:s notify-
    inställningar, så en ändring här syns direkt i ewapp också (och tvärtom)."""
    if key not in NOTIFY_LABELS:
        return JSONResponse({"ok": False, "error": "Okänd aviseringstyp"}, status_code=404)
    v = (await request.json()).get("value")
    with ENGINE.begin() as c:
        c.execute(text(
            "INSERT INTO overrides (device, mode) VALUES (:d, :m) ON CONFLICT (device) DO UPDATE SET mode = :m, updated_at = now()"
        ), {"d": key, "m": "true" if v else "false"})
    return {"ok": True}


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
            charger_driver = charger.get("driver") or "generic"
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
            charger_entities = (charger.get("entities") or {}).copy()
            if charger.get("status_entity"):
                charger_entities.setdefault("status", charger["status_entity"])
            for key, val in charger_entities.items():
                lines.append(f"        {key}: {val}")
    lines.append("")

    hp = sel.get("heat_pump")
    if hp:
        hp_driver = hp.get("driver") or "generic_climate"
        lines += ["heat_pump:", "  enabled: true", f"  driver: {hp_driver}"]
        if hp_driver == "generic_climate":
            lines += ["  entities:"]
            for key, val in (hp.get("entities") or {}).items():
                lines.append(f"    {key}: {val}")
        else:
            lines += ["  connection:", "    modbus_host: 192.168.1.XXX  # FYLL I - värmepumpens IP/gateway, kan inte upptäckas automatiskt",
                       "    modbus_port: 502", "    unit_id: 1"]
    else:
        lines += ["heat_pump:", "  enabled: false"]
    lines.append("")

    solar = sel.get("solar")
    if solar:
        lines += ["solar:", "  enabled: true", f"  driver: {solar.get('driver') or 'generic_number'}", "  entities:"]
        solar_entities = (solar.get("entities") or {}).copy()
        if solar.get("pv_power_entity"):
            solar_entities.setdefault("pv_power_w", solar["pv_power_entity"])
        if solar.get("today_kwh_entity"):
            solar_entities.setdefault("today_kwh", solar["today_kwh_entity"])
        for key, val in solar_entities.items():
            lines.append(f"    {key}: {val}")
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
    lines.append("")

    battery = sel.get("battery")
    if battery:
        lines += ["battery:", "  enabled: true", f"  driver: {battery.get('driver') or 'generic'}",
                   "  capacity_kwh: 10  # FYLL I - batteriets kapacitet i kWh", "  entities:"]
        battery_entities = (battery.get("entities") or {}).copy()
        if battery.get("soc_entity"):
            battery_entities.setdefault("soc", battery["soc_entity"])
        if battery.get("power_entity"):
            battery_entities.setdefault("power", battery["power_entity"])
        for key, val in battery_entities.items():
            lines.append(f"    {key}: {val}")
    else:
        lines += ["battery:", "  enabled: false"]
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
            house_config.build_battery_driver(cfg)
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"Den genererade filen gick inte att läsa in: {e}"}, status_code=500)
    from fastapi.responses import Response
    return Response(content=yaml_text, media_type="text/yaml",
                     headers={"Content-Disposition": "attachment; filename=house_config.yaml"})


app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/{full_path:path}")
async def spa(full_path: str):
    return FileResponse("static/index.html")
