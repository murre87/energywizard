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
import hashlib
import hmac
import json
import math
import os
import sys
import time
import zoneinfo

import re
import requests

sys.path.insert(0, "/smartbox")
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine, text

import webauth
import discovery
import house_config
import pump

WATCHTOWER_URL = os.environ.get("WATCHTOWER_URL", "http://host.docker.internal:8090")
WATCHTOWER_TOKEN = os.environ.get("WATCHTOWER_API_TOKEN", "")
# Bara på utvecklarens egen installation: telemetrisamlarens sammanställning (antal aktiva + utrustning).
TELEMETRY_STATS_URL = os.environ.get("TELEMETRY_STATS_URL", "").strip()
TELEMETRY_STATS_TOKEN = os.environ.get("TELEMETRY_STATS_TOKEN", "").strip()       # samma som samlarens STATS_TOKEN
INSTALLS_PAGE = {"id": "installationer", "name": "Installationer", "icon": "👥", "built": True}
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
AUTH = webauth.Auth(salt="webdash", family_write_prefixes=(), cookie="ew_web")      # egen kaka, se webauth.Auth

# -- styrkommandon: samma knappar som ewapp, inte dubblerad logik ------------------------
# webdashboard har ingen egen Tesla/Nissan/SolarEdge/spa-styrningskod - den enda riktiga
# hårdvarulogiken (handskakningar, HA-anrop) finns i ewapp/app.py, redan testad i skarp
# drift. Istället för att skriva om den (gissad kod = exakt det det här projektet undviker,
# se ROADMAP) PROXAR webdashboard de skrivande anropen till ewapp-containern internt
# (samma docker-nät, container_name "ewapp", port 8502) med ett eget serversignerat
# "ew"-cookie - exakt samma HMAC-formel ewapp/app.py:s _sign() använder (salt "ewapp"),
# bara byggd server-till-server här istället för att komma från webbläsaren.
# OBS: /api/secure + /api/tesla/access (lås/upplåsning/luckor) är MEDVETET INTE proxade -
# det är ett separat omverifieringsflöde (eget "ew2"-cookie, lösenord igen, 10 minuters
# fönster) som förtjänar sin egen, noga testade implementation - inte en hastig kopia.
EWAPP_URL = os.environ.get("EWAPP_URL", "http://ewapp:8502")
_EWAPP_SECRET = hashlib.sha256(("ewapp|" + webauth.owner_password()).encode()).digest()


def _ewapp_cookie() -> str:
    exp = int(time.time()) + 60
    payload = f"{exp}.owner.owner"
    return f"{payload}.{hmac.new(_EWAPP_SECRET, payload.encode(), hashlib.sha256).hexdigest()}"


async def _ewapp_proxy(path: str, body: dict, extra_cookies: dict | None = None) -> JSONResponse:
    try:
        cookies = {"ew": _ewapp_cookie()}
        cookies.update(extra_cookies or {})
        r = requests.post(f"{EWAPP_URL}{path}", cookies=cookies, json=body, timeout=25)
    except requests.RequestException as e:
        return JSONResponse({"detail": f"Nådde inte ewapp: {e}"}, status_code=502)
    try:
        data = r.json()
    except ValueError:
        data = {"detail": r.text}
    return JSONResponse(data, status_code=r.status_code)


# -- Bil-lås/luckor: eget, separat omverifieringsflöde (ew2), inte bara proxat rakt av ----
# Lås upp/luckor kräver lösenordet igen (10 min) precis som i ewapp - webdashboard har sin
# EGEN ew2-kaka (samma hemlighet/formel som ewapp:s _secure_ok(), eftersom bägge delar
# PASSWORD) så den kan vidareskickas till ewapp:s /api/tesla/access och godkännas där utan
# att webdashboard behöver duplicera Tesla-hanteringen eller spärrlogiken - ewapp:s egen
# _secure_ok()/_unlock_fails kör fortfarande på riktigt, bara anropad härifrån också.
_secure_fails: dict = {}


def _secure_ok(request: Request) -> bool:
    v = request.cookies.get("ew2", "")
    try:
        exp, sig = v.split(".", 1)
        return int(exp) > time.time() and hmac.compare_digest(sig, hmac.new(_EWAPP_SECRET, ("sec" + exp).encode(), hashlib.sha256).hexdigest())
    except Exception:
        return False


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
    {"id": "logg", "name": "Logg", "icon": "📜", "built": True},
]

app = FastAPI(title="EnergyWizard Webdashboard")
try:
    import ew_journal
    ew_journal.install("webb")                 # installationens logg (smartbox/ew_journal.py)
except Exception as _je:
    print(f"⚠️ Loggen startade inte: {_je}")


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


# ---------- Startguiden: lösenord, Home Assistant, prylar (allt i webben) ----------
import ew_settings  # noqa: E402
import homeassistant  # noqa: E402


def _devices_chosen() -> bool:
    # Filen som den står (inte med standardvärden ifyllda): något mer än house_id?
    try:
        import yaml
        with open(HOUSE_CONFIG_FILE, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    except Exception:
        return False
    return isinstance(cfg, dict) and any(k != "house_id" and v for k, v in cfg.items())


@app.get("/api/setup/status")
async def api_setup_status(request: Request):
    """Vad som saknas. Öppen före inloggning, men avslöjar inget utöver ja/nej."""
    role, _ = AUTH.session(request)
    has_pw = bool(webauth.owner_password())
    out = {"needs_password": not has_pw, "supervisor": bool(homeassistant.SUPERVISOR_TOKEN),
           "ha_ok": homeassistant.configured(), "devices_chosen": _devices_chosen()}
    if role == "owner":
        out.update(ha_url=homeassistant.HA_URL or "", ha_from_env=bool(homeassistant._ENV_URL or homeassistant.HA_IP),
                   can_save_config=_config_writable())
    return out


@app.post("/api/setup/password")
async def api_setup_password(request: Request):
    """Första lösenordet. Går bara när inget lösenord finns; loggar in direkt."""
    if webauth.owner_password():
        return JSONResponse({"detail": "Lösenordet är redan valt. Logga in."}, status_code=409)
    body = await request.json()
    pw = str(body.get("password", ""))
    if len(pw) < 8:
        return JSONResponse({"detail": "Välj minst 8 tecken."}, status_code=400)
    ew_settings.update(dashboard_password=pw)
    return await AUTH.login(request)


@app.post("/api/setup/ha")
async def api_setup_ha(request: Request):
    """Testar och sparar adress + token till Home Assistant (bara ägaren)."""
    role, _ = AUTH.session(request)
    if role != "owner":
        return JSONResponse({"detail": "Bara ägaren kan ändra anslutningen"}, status_code=403)
    if homeassistant.SUPERVISOR_TOKEN:
        return {"ok": True, "message": "Körs som Home Assistant-tillägg: anslutningen sköts av Home Assistant."}
    if homeassistant._ENV_URL or homeassistant.HA_IP:
        return JSONResponse({"detail": "Anslutningen styrs av HA_URL/HA_IP i .env och ändras där."}, status_code=409)
    body = await request.json()
    url, token = str(body.get("url", "")).strip(), str(body.get("token", "")).strip()
    if not url or not token:
        return JSONResponse({"detail": "Fyll i både adress och token."}, status_code=400)
    ok, msg = homeassistant.test_connection(url, token)
    if not ok:
        return JSONResponse({"detail": msg}, status_code=400)
    ew_settings.update(ha_url=homeassistant.normalize_ha_url(url), ha_token=token)
    homeassistant.reconfigure()
    return {"ok": True, "message": msg}


# ---------- Batteriets planering: stil och försäljning (valt i webben) ----------
@app.get("/api/battery-plan-settings")
async def api_battery_plan_settings():
    import battery_plan
    st = ew_settings.load()
    try:
        bs = house_config.battery_settings(house_config.load_house_config(HOUSE_CONFIG_FILE))
    except Exception:
        bs = {}
    return {"style": st.get("battery_plan_style") or bs.get("plan_style") or battery_plan.DEFAULT_STYLE,
            "allow_export": st.get("battery_allow_export", bs.get("allow_export", True)) is not False,
            "styles": list(battery_plan.PLAN_STYLES), "has_battery": bs.get("control", "av") != "av"}


@app.post("/api/battery-plan-settings")
async def api_battery_plan_settings_save(request: Request):
    import battery_plan
    role, _ = AUTH.session(request)
    if role != "owner":
        return JSONResponse({"detail": "Bara ägaren kan ändra batteriets planering"}, status_code=403)
    body = await request.json()
    upd = {}
    if "style" in body:
        if body["style"] not in battery_plan.PLAN_STYLES:
            return JSONResponse({"detail": "Okänd stil"}, status_code=400)
        upd["battery_plan_style"] = body["style"]
    if "allow_export" in body:
        upd["battery_allow_export"] = bool(body["allow_export"])
    ew_settings.update(**upd)
    return {"ok": True, **upd}


@app.get("/api/solar-forecast-settings")
async def solar_forecast_settings_get(request: Request):
    import asyncio
    import ha_solar_forecast as forecast
    role, _ = AUTH.session(request)
    if role != "owner":
        return JSONResponse({"detail": "Bara ägaren kan ändra solprognosen"}, status_code=403)
    source, entities = forecast.configuration()
    def read():
        candidates = []
        try:
            response = homeassistant.requests.get(f"{homeassistant._BASE}/states", headers=homeassistant._HEADERS,
                                                 verify=homeassistant._VERIFY, timeout=10)
            response.raise_for_status()
            for state in response.json():
                attrs = state.get("attributes") or {}
                entity = state.get("entity_id", "")
                if entity.startswith("sensor.") and ("detailedForecast" in attrs or "detailedHourly" in attrs):
                    candidates.append({"entity": entity, "name": attrs.get("friendly_name") or entity})
        except Exception:
            pass
        return sorted(candidates, key=lambda item: item["entity"]), forecast.snapshot()
    candidates, snapshot = await asyncio.to_thread(read)
    return {"ok": True, "source": source, "entities": list(entities), "candidates": candidates,
            "status": snapshot["state"]}


@app.post("/api/solar-forecast-settings")
async def solar_forecast_settings_save(request: Request):
    import ha_solar_forecast as forecast
    role, _ = AUTH.session(request)
    if role != "owner":
        return JSONResponse({"detail": "Bara ägaren kan ändra solprognosen"}, status_code=403)
    body = await request.json()
    try:
        entities = forecast.validate(body.get("source"), body.get("entities"))
    except ValueError as exc:
        messages = {"invalid_source": "Okänd källa för solprognosen",
                    "invalid_entities": "Välj högst sju giltiga sensorentiteter",
                    "missing_entities": "Välj minst en Solcast-prognossensor"}
        return JSONResponse({"detail": messages[str(exc)]}, status_code=400)
    ew_settings.update(solar_forecast_source=body["source"], solar_forecast_entities=entities)
    forecast.invalidate()
    return {"ok": True}


@app.get("/api/mqtt-settings")
async def mqtt_get(request: Request):
    """Inställningar -> Home Assistant via MQTT (smartbox/mqtt_bridge.py). Lösenordet skickas aldrig tillbaka."""
    role, _ = AUTH.session(request)
    if role != "owner":
        return JSONResponse({"error": "Bara ägaren"}, status_code=403)
    st = ew_settings.load()
    from urllib.parse import urlparse
    guess = urlparse(homeassistant._BASE).hostname or ""
    return {"ok": True, "host": st.get("mqtt_host") or "", "port": st.get("mqtt_port") or 1883, "user": st.get("mqtt_user") or "",
            "has_password": bool(st.get("mqtt_password")), "status": st.get("mqtt_status"), "suggested_host": guess}


@app.post("/api/mqtt-settings")
async def mqtt_set(request: Request):
    role, _ = AUTH.session(request)
    if role != "owner":
        return JSONResponse({"error": "Bara ägaren kan ändra MQTT"}, status_code=403)
    b = await request.json()
    host = str(b.get("host") or "").strip()
    if host and not re.fullmatch(r"[A-Za-z0-9.\-:\[\]]{1,253}", host):
        return JSONResponse({"error": "Ogiltig adress"}, status_code=400)
    try:
        port = int(b.get("port") or 1883)
    except ValueError:
        return JSONResponse({"error": "Ogiltig port"}, status_code=400)
    upd = {"mqtt_host": host or None, "mqtt_port": port if host else None, "mqtt_user": (str(b.get("user") or "").strip() or None) if host else None,
           "mqtt_status": None}
    if not host:
        upd["mqtt_password"] = None
    elif b.get("password"):                        # tomt fält = behåll det sparade lösenordet
        upd["mqtt_password"] = str(b["password"])
    ew_settings.update(**upd)
    return {"ok": True}


@app.get("/api/shadow")
async def shadow_get():
    """Skuggläget (smartbox/shadow.py): på/av och vad EnergyWizard hade gjort de senaste dygnen."""
    import shadow
    try:
        with ENGINE.connect() as c:
            rows = c.execute(text("SELECT ts AT TIME ZONE 'Europe/Stockholm', what, detail FROM shadow_actions "
                                  "ORDER BY ts DESC LIMIT 60")).fetchall()
    except Exception:          # tabellen finns först när något loggats
        rows = []
    return {"ok": True, "active": shadow.active(), "forced_by_env": os.environ.get("SHADOW_MODE", "").lower() in ("1", "true", "ja", "yes"),
            "actions": [{"ts": str(r[0])[:16], "what": r[1], "detail": r[2]} for r in rows]}


@app.post("/api/shadow")
async def shadow_set(request: Request):
    role, _ = AUTH.session(request)
    if role != "owner":
        return JSONResponse({"error": "Bara ägaren kan slå på eller av skuggläget"}, status_code=403)
    ew_settings.update(shadow_mode=bool((await request.json()).get("active")) or None)
    return {"ok": True}


_PRICE_KEYS = ("price_country", "price_area", "price_vat_pct", "price_buy_extra", "price_sell_extra", "price_sell_vat",
               "price_currency", "price_timezone", "price_final", "price_current_entity", "price_ha_entity", "price_tou_extra", "price_tou_hours", "price_tou_months", "price_tou_weekdays",
               "price_buy_mode", "price_buy_fixed", "price_sell_mode", "price_sell_fixed",
               "price_hdo_entity", "price_distribution_nt", "price_distribution_vt",
               "price_buy_nt", "price_buy_vt", "price_hdo_price_source")


@app.get("/api/price-settings")
async def price_settings_get():
    """Inställningar -> Elpris och avgifter: gällande värden, länderna och ett räkneexempel."""
    import nordpool
    c = nordpool.cost_settings()
    c = {**c, "tou_hours": f"{c['tou_hours'][0]}-{c['tou_hours'][1]}", "tou_months": f"{c['tou_months'][0]}-{c['tou_months'][1]}"}
    w = nordpool.high_load_window()
    # Effekttariffens höglasttid (#180): "egen" / "av" / "tidstariff" / "standard" (inget valt)
    power_high = {"choice": w["source"], "hours": f"{w['hours'][0]}-{w['hours'][1]}" if w["source"] == "egen" else "7-20",
                  "months": f"{w['months'][0]}-{w['months'][1]}" if w["source"] == "egen" else "11-3",
                  "weekdays": w["weekdays"] if w["source"] == "egen" else True}
    return {"ok": True, **c, "power_high": power_high, "source": nordpool.price_source(),
            "ha_entity": ew_settings.get("price_ha_entity") or "sensor.nordpool",
            "countries": {k: {"name": v["name"], "vat_pct": v["vat_pct"], "currency": v["currency"], "symbol": nordpool.CURRENCY_SYMBOL.get(v["currency"], v["currency"]),
                               "timezone": v.get("timezone", "Europe/Stockholm"), "areas": v["areas"]}
                          for k, v in nordpool.COUNTRIES.items()},
            # Räkneexempel för spotpris 1,00 exkl. moms: samma formel som nordpool.full_buy_cost/full_sell_income
            "example": {"spot": 1.0, "buy": round(nordpool.full_buy_cost(1.0 * (1 + c["vat_pct"] / 100) if nordpool.prices_include_vat() else 1.0), 4),
                        "sell": round(nordpool.full_sell_income(1.0 * (1 + c["vat_pct"] / 100) if nordpool.prices_include_vat() else 1.0), 4)}}


@app.get("/api/distribution-schedules")
async def distribution_schedules():
    try:
        r = requests.get(f"{homeassistant._BASE}/states", headers=homeassistant._HEADERS, timeout=10, verify=homeassistant._VERIFY)
        r.raise_for_status()
        entities = [{"entity_id": st["entity_id"], "name": (st.get("attributes") or {}).get("friendly_name") or st["entity_id"],
                     "nt": st["attributes"].get("low_tariff_price"), "vt": st["attributes"].get("high_tariff_price")}
                    for st in r.json() if st.get("entity_id", "").startswith("sensor.")
                    and isinstance((st.get("attributes") or {}).get("schedule"), list)
                    and any(isinstance(row, dict) and row.get("tariff") in ("NT", "VT") for row in st["attributes"]["schedule"])]
        return {"ok": True, "entities": entities}
    except Exception:
        return {"ok": False, "entities": [], "error": "Could not read distribution schedules from Home Assistant"}


@app.get("/api/price-entities")
async def price_entities():
    """Prissensorer i Home Assistant med dygnets priser (Nord Pool, ENTSO-e, EPEX Spot, Energi Data Service, Octopus,
    Amber ...), för valet av priskälla i installationen och under Inställningar."""
    import nordpool
    try:
        r = requests.get(f"{homeassistant._BASE}/states", headers=homeassistant._HEADERS, timeout=20, verify=homeassistant._VERIFY)
        r.raise_for_status()
        states = r.json()
    except Exception as e:
        return {"ok": False, "error": f"Kunde inte läsa Home Assistant: {e}", "entities": []}
    out = []
    for st in states:
        e = st.get("entity_id", "")
        if not (e.startswith("sensor.") or e.startswith("event.")) or e.endswith("_next_day_rates"):
            continue
        kind = nordpool.recognize_price_entity(st)
        if kind:
            a = st.get("attributes") or {}
            n = len(nordpool.parse_price_attributes(a, a.get("unit_of_measurement", "")))
            out.append({"entity_id": e, "name": a.get("friendly_name") or e, "integration": kind,
                        "unit": a.get("unit_of_measurement") or "", "points": n})
    selected = ew_settings.get("price_ha_entity") or ""
    if not selected and nordpool.price_source() == "ha_nordpool":       # vald via miljön (PRICE_SOURCE/NORDPOOL_HA_ENTITY)
        selected = os.environ.get("NORDPOOL_HA_ENTITY", "sensor.nordpool")
    return {"ok": True, "entities": out, "selected": selected,
            "final": nordpool.price_final_mode(),
            "current_entity": ew_settings.get("price_current_entity") or "",
            "includes_vat": nordpool.prices_include_vat() if nordpool.price_source() == "ha_nordpool" else
            str(ew_settings.get("price_includes_vat", nordpool.cost_settings()["country"] != "CZ")).lower() not in ("0", "false", "nej", "no")}


# ---- Aviseringar till vilken telefon (issue #123: förut den första mobile_app_* i HA - kunde vara fel persons) ----
@app.get("/api/notify-target")
async def notify_target_get(request: Request):
    role, _ = AUTH.session(request)
    if role != "owner":
        return JSONResponse({"error": "Bara ägaren"}, status_code=403)
    try:
        r = requests.get(f"{homeassistant._BASE}/services", headers=homeassistant._HEADERS, timeout=15, verify=homeassistant._VERIFY)
        r.raise_for_status()
        svcs = next((d.get("services") or {} for d in r.json() if d.get("domain") == "notify"), {})
    except Exception as e:
        return {"ok": False, "error": f"Kunde inte läsa Home Assistant: {e}"}
    phones = sorted(n for n in svcs if n.startswith("mobile_app_"))
    # #170: även andra notify-tjänster (grupper, e-post, Telegram ...) och egna skript (får title och message)
    others = sorted(n for n in svcs if not n.startswith("mobile_app_") and n not in ("notify", "persistent_notification"))
    scripts = []
    try:
        st = requests.get(f"{homeassistant._BASE}/states", headers=homeassistant._HEADERS, timeout=15, verify=homeassistant._VERIFY).json()
        scripts = sorted(({"id": s["entity_id"], "name": (s.get("attributes") or {}).get("friendly_name") or s["entity_id"]}
                          for s in st if str(s.get("entity_id", "")).startswith("script.")), key=lambda x: x["name"].lower())
    except Exception:
        pass
    return {"ok": True, "phones": phones, "others": others, "scripts": scripts, "home_only": bool(ew_settings.get("notify_home_only")),
            "selected": ew_settings.get("notify_target") or "", "env": os.environ.get("NOTIFY_TARGET", "")}


@app.post("/api/notify-target")
async def notify_target_set(request: Request):
    role, _ = AUTH.session(request)
    if role != "owner":
        return JSONResponse({"error": "Bara ägaren kan välja telefon"}, status_code=403)
    body = await request.json()
    t = str(body.get("target") or "").strip()
    if t and not re.fullmatch(r"(script\.)?[a-z0-9_]+", t):
        return JSONResponse({"error": "Ogiltig mottagare"}, status_code=400)
    ew_settings.update(notify_target=t or None)
    if "home_only" in body:
        ew_settings.update(notify_home_only=bool(body.get("home_only")) or None)
    return {"ok": True, "message": "Sparat - aviseringarna går till " + (t or "den första telefonen i Home Assistant")}


@app.get("/api/journal")
async def api_journal(request: Request, hours: float = 24, lvl: str = "", q: str = "", src: str = "", limit: int = 500):
    """Installationens logg (smartbox/ew_journal.py): allt motorn, appen och webben skrivit - nyast först. Bara ägaren."""
    if AUTH.session(request)[0] != "owner":
        return JSONResponse({"error": "Bara ägaren kan läsa loggen"}, status_code=403)
    import ew_journal
    with ENGINE.connect() as c:
        rows = ew_journal.read(c, since_h=max(0.1, min(hours, 24 * ew_journal.KEEP_DAYS)), lvl=lvl or None, q=q.strip() or None,
                               src=src or None, limit=limit)
    return {"ok": True, "rows": rows, "keep_days": ew_journal.KEEP_DAYS}


@app.get("/api/journal/download")
async def api_journal_download(request: Request, days: float = 2):
    """Supportfil: hela loggen de senaste dygnen som text - att bifoga i en issue (granska den först)."""
    if AUTH.session(request)[0] != "owner":
        return JSONResponse({"error": "Bara ägaren kan läsa loggen"}, status_code=403)
    import ew_journal
    from datetime import datetime
    with ENGINE.connect() as c:
        body = ew_journal.export_text(c, days)
    name = f"energywizard-logg-{datetime.now().strftime('%Y%m%d-%H%M')}.txt"
    return Response(content=body, media_type="text/plain; charset=utf-8", headers={"Content-Disposition": f"attachment; filename={name}"})


@app.get("/api/ev-cost")
def api_ev_cost():
    """Elbilsladdningens energi och kostnad idag, veckan, månaden (smartbox/ev_cost.py) - samma i appen och webben."""
    import ev_cost
    with ENGINE.connect() as c:
        return {"ok": True, "periods": ev_cost.summary(c)}


@app.get("/api/notify-log")
def api_notify_log(days: int = 7):
    """Aviseringshistorik med leveransstatus (smartbox/notify_log.py) - samma i appen och webben."""
    import notify_log
    with ENGINE.connect() as c:
        return {"ok": True, "rows": notify_log.recent(c, max(1, min(60, int(days))))}


@app.get("/api/control-journal")
def api_control_journal(back: int = 1):
    """Höll vi planen? Per enhet för ett dygn (0 = idag, 1 = igår), smartbox/control_journal.py - samma i appen och webben."""
    import control_journal
    back = max(0, min(29, int(back)))
    with ENGINE.connect() as c:
        return {"ok": True, "back": back, "devices": control_journal.day_summary(c, back)}


@app.get("/api/control-alerts")
async def control_alerts():
    """Enheter som inte gör det EnergyWizard säger åt dem (smartbox/control_alerts.py, samma som appen) - visas överst."""
    import control_alerts as _ca
    with ENGINE.connect() as c:
        try:
            rows = c.execute(text("SELECT device, mode FROM overrides WHERE device IN ('battery_follow', 'ev_hold', 'ev_in_meter')")).all()
        except Exception:
            rows = []
    return {"ok": True, "alerts": _ca.build({r[0]: r[1] for r in rows})}


@app.get("/api/capacity-tariff")
async def capacity_tariff_get():
    """Effektavgift efter månadens högsta timmar (#141): inställningen och läget just nu (smartbox/capacity_tariff.py)."""
    import capacity_tariff
    from datetime import datetime
    cfg = ew_settings.get("capacity_tariff") or {}
    with ENGINE.connect() as c:
        rows = c.execute(text("""SELECT (h AT TIME ZONE 'Europe/Stockholm')::date, kw FROM (
                                   SELECT date_trunc('hour', timestamp) h, avg(GREATEST(net_power, 0)) / 1000.0 kw FROM sensor_log
                                   WHERE timestamp >= date_trunc('month', now() AT TIME ZONE 'Europe/Stockholm') AT TIME ZONE 'Europe/Stockholm'
                                     AND timestamp < date_trunc('hour', now()) GROUP BY 1) x""")).fetchall()
    peaks = [(d, float(k or 0)) for d, k in rows]
    today = datetime.now(zoneinfo.ZoneInfo("Europe/Stockholm")).date()
    n, distinct = int(cfg.get("top_n") or 3), cfg.get("distinct_days", True) is not False
    lim, info = capacity_tariff.limit_kw(peaks, today, n, distinct, cfg.get("steps"), cfg.get("target_kw"))
    top = capacity_tariff.top_hours(peaks, n, distinct)
    return {"ok": True, "enabled": bool(cfg.get("enabled")), "top_n": n, "distinct_days": distinct,
            "steps": cfg.get("steps") or capacity_tariff.DEFAULT_STEPS, "target_kw": cfg.get("target_kw"),
            "status": {**info, "top_days": [[str(d), round(k, 2)] for d, k in top]}}


@app.post("/api/capacity-tariff")
async def capacity_tariff_set(request: Request):
    role, _ = AUTH.session(request)
    if role != "owner":
        return JSONResponse({"error": "Bara ägaren kan ändra effektavgiften"}, status_code=403)
    b = await request.json()
    try:
        steps = sorted({float(str(x).replace(",", ".")) for x in (b.get("steps") or []) if str(x).strip()})
        n = max(1, min(10, int(b.get("top_n") or 3)))
        target = float(str(b.get("target_kw")).replace(",", ".")) if b.get("target_kw") not in (None, "") else None
    except (TypeError, ValueError):
        return JSONResponse({"error": "Ogiltigt värde"}, status_code=400)
    if steps and (steps[0] <= 0 or len(steps) > 20):
        return JSONResponse({"error": "Trappstegen ska vara positiva kW-värden"}, status_code=400)
    ew_settings.update(capacity_tariff={"enabled": bool(b.get("enabled")), "top_n": n, "distinct_days": b.get("distinct_days", True) is not False,
                                        "steps": steps or None, "target_kw": target})
    return {"ok": True, "message": "Sparat"}


@app.get("/api/notify-prefs")
async def notify_prefs_get():
    """Notiskategorierna och om de är på (smartbox/notify_prefs.py) - alla notiser går att stänga av."""
    import notify_prefs
    return {"ok": True, "categories": notify_prefs.listing()}


@app.post("/api/notify-prefs")
async def notify_prefs_set(request: Request):
    role, _ = AUTH.session(request)
    if role != "owner":
        return JSONResponse({"error": "Bara ägaren kan ändra notiserna"}, status_code=403)
    import notify_prefs
    on = (await request.json()).get("on") or {}
    off = [k for k in notify_prefs.KEYS if on.get(k) is False or (k not in on and k in notify_prefs.disabled())]
    notify_prefs.set_disabled(off)
    return {"ok": True, "categories": notify_prefs.listing(), "message": "Sparat"}


# ---- Givare (2026-11-04): innegivare, utegivare och fukt väljs av användaren - inget är hårdkodat --------------------
_INDOOR_HINT = re.compile(r"inne|inomhus|vardagsrum|sovrum|kök|kok|hall|kontor|living|bedroom|kitchen|room|rum|indoor|matter|zigbee|aqara|timmerflotte", re.I)
_OUTDOOR_HINT = re.compile(r"\bute\b|utomhus|outdoor|outside|ute_|_ute", re.I)
_NOT_ROOM = re.compile(r"cpu|processor|battery|batteri|tesla|leaf|car|bil|inverter|växelriktare|framledning|retur|forward|return|"
                       r"brine|köldbärare|varmvatten|hot ?water|dhw|spa|pool|bad|tank|frys|kyl|freezer|fridge|motor|chip|disk|nas|router|"
                       r"compressor|kompressor|wled|esp32 internal|board", re.I)


@app.get("/api/sensors")
async def sensors_get(request: Request):
    """Temperatur- och fuktgivare i Home Assistant med förslag (innegivare, utegivare), plus nuvarande val."""
    role, _ = AUTH.session(request)
    if role != "owner":
        return JSONResponse({"error": "Bara ägaren"}, status_code=403)
    try:
        r = requests.get(f"{homeassistant._BASE}/states", headers=homeassistant._HEADERS, timeout=20, verify=homeassistant._VERIFY)
        r.raise_for_status()
        states = r.json()
    except Exception as e:
        return {"ok": False, "error": f"Kunde inte läsa Home Assistant: {e}"}
    temps, hums = [], []
    for st in states:
        e, a = st.get("entity_id", ""), st.get("attributes") or {}
        if not e.startswith("sensor."):
            continue
        name = a.get("friendly_name") or e
        try:
            val = float(st.get("state"))
        except (TypeError, ValueError):
            val = None
        dc, unit = a.get("device_class"), a.get("unit_of_measurement")
        text_ = f"{e} {name}"
        if dc == "temperature" or unit in ("°C", "°F"):
            room = bool(_INDOOR_HINT.search(text_)) and not _NOT_ROOM.search(text_) and not _OUTDOOR_HINT.search(text_)
            temps.append({"entity": e, "name": name, "value": val, "suggest_indoor": room and val is not None and 10 <= val <= 30,
                          "suggest_outdoor": bool(_OUTDOOR_HINT.search(text_)) and not _NOT_ROOM.search(text_)})
        elif dc == "humidity" or (unit == "%" and re.search(r"humid|fukt", text_, re.I)):
            hums.append({"entity": e, "name": name, "value": val})
    temps.sort(key=lambda x: (not x["suggest_indoor"], not x["suggest_outdoor"], x["name"].lower()))
    hums.sort(key=lambda x: x["name"].lower())
    return {"ok": True, "temperatures": temps, "humidities": hums, "selected": homeassistant.sensor_config()}


@app.post("/api/sensors")
async def sensors_set(request: Request):
    role, _ = AUTH.session(request)
    if role != "owner":
        return JSONResponse({"error": "Bara ägaren kan ändra givare"}, status_code=403)
    body = await request.json()
    ent_ok = lambda x: isinstance(x, str) and re.fullmatch(r"sensor\.[a-z0-9_]+", x)
    old = {s.get("entity"): s for s in (homeassistant.sensor_config().get("indoor") or []) if isinstance(s, dict)}
    used, indoor = set(), []
    for item in (body.get("indoor") or [])[:12]:
        e = item.get("entity")
        if not ent_ok(e):
            return JSONResponse({"error": f"Ogiltig givare: {e}"}, status_code=400)
        if homeassistant.is_outdoor_sensor(e, item.get("label"), body.get("outdoor")):     # issue #149
            return JSONResponse({"error": f"{item.get('label') or e} är en utegivare och kan inte räknas in i innetemperaturen. "
                                          "Välj den som utegivare längst ner i stället."}, status_code=400)
        prev = old.get(e, {})
        key = prev.get("key")
        if not key or key in used:                       # behåll nyckeln (loggkolumnen) för givare som redan var valda
            n = 1
            while f"in_{n}" in used or any(s.get("key") == f"in_{n}" for s in old.values() if s.get("entity") != e):
                n += 1
            key = f"in_{n}"
        used.add(key)
        s = {"key": key, "entity": e, "label": str(item.get("label") or prev.get("label") or e)[:60]}
        if ent_ok(item.get("humidity")):
            s["humidity"] = item["humidity"]
        try:
            off = float(str(item.get("offset") or 0).replace(",", "."))
        except ValueError:
            return JSONResponse({"error": "Ogiltig korrigering"}, status_code=400)
        if not -5 <= off <= 5:
            return JSONResponse({"error": "Korrigeringen ska vara mellan -5 och 5 °C"}, status_code=400)
        if off:
            s["offset"] = off
        if prev.get("esphome_ip"):
            s["esphome_ip"] = prev["esphome_ip"]
        indoor.append(s)
    outdoor = body.get("outdoor")
    if outdoor and not ent_ok(outdoor):
        return JSONResponse({"error": "Ogiltig utegivare"}, status_code=400)
    ew_settings.update(sensors={"indoor": indoor, **({"outdoor": outdoor} if outdoor else {})})
    return {"ok": True, "message": "Sparat - motorn använder givarna från nästa varv."}


@app.post("/api/price-source")
async def price_source_set(request: Request):
    """Väljer prissensor i HA (tom = standard: elprisetjustnu.se i Sverige) och om priset i den är inklusive moms."""
    role, _ = AUTH.session(request)
    if role != "owner":
        return JSONResponse({"error": "Bara ägaren kan ändra priskällan"}, status_code=403)
    body = await request.json()
    ent = str(body.get("ha_entity") or "").strip()
    if ent and not re.fullmatch(r"(sensor|event)\.[a-z0-9_]+", ent):
        return JSONResponse({"error": "Ogiltig entitet"}, status_code=400)
    import nordpool
    mode = str(body.get("final", "auto")).lower()
    if mode not in ("auto", "true", "false"):
        return JSONResponse({"error": "Invalid price finality"}, status_code=400)
    current = str(body.get("current_entity") or "").strip()
    if current and not re.fullmatch(r"sensor\.[a-z0-9_]+", current):
        return JSONResponse({"error": "Invalid current price entity"}, status_code=400)
    ew_settings.update(price_ha_entity=ent or None, price_includes_vat=bool(body.get("includes_vat", nordpool.cost_settings()["country"] != "CZ")),
                       price_final=mode, price_current_entity=current or None)

    return {"ok": True}


@app.post("/api/price-settings")
async def price_settings_set(request: Request):
    role, _ = AUTH.session(request)
    if role != "owner":
        return JSONResponse({"error": "Bara ägaren kan ändra elpris och avgifter"}, status_code=403)
    import nordpool
    body = await request.json()
    from price_options import extended_price_options, validate_result
    try:
        upd = extended_price_options(body)
        if body.get("buy_mode") == "hdo" and body.get("hdo_price_source") == "ha":
            from distribution_tariff import prices_for
            rates = prices_for(upd["price_hdo_entity"])
            if rates is None:
                raise ValueError("ČEZ HDO saknar giltiga priser för NT och VT. Ange priserna manuellt eller konfigurera dem i integrationen.")
            upd.update(price_buy_nt=rates[0], price_buy_vt=rates[1])
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    country = str(body.get("country") or "SE").upper()
    if country not in nordpool.COUNTRIES:
        return JSONResponse({"error": "Okänt land"}, status_code=400)
    upd["price_country"] = country
    if "timezone" in body:
        tz = str(body.get("timezone") or nordpool.COUNTRIES[country].get("timezone", "Europe/Stockholm"))
        try:
            zoneinfo.ZoneInfo(tz)
        except (ValueError, zoneinfo.ZoneInfoNotFoundError):
            return JSONResponse({"error": "Invalid timezone"}, status_code=400)
        upd["price_timezone"] = tz
    area = str(body.get("area") or "").upper()
    upd["price_area"] = area if area in nordpool.COUNTRIES[country]["areas"] else nordpool.COUNTRIES[country]["areas"][0]
    for key, field, lo, hi in (("price_vat_pct", "vat_pct", 0, 50), ("price_buy_extra", "buy_extra", -5, 50), ("price_sell_extra", "sell_extra", -5, 50)):
        v = body.get(field)
        if v in (None, ""):
            upd[key] = None                     # tomt = landets standard
            continue
        try:
            v = float(str(v).replace(",", "."))
        except ValueError:
            return JSONResponse({"error": f"Ogiltigt värde: {field}"}, status_code=400)
        if not lo <= v <= hi:
            return JSONResponse({"error": f"{field} utanför rimligt intervall"}, status_code=400)
        upd[key] = v
    upd["price_sell_vat"] = bool(body.get("sell_vat"))
    # Tidstariff (issue #98): tillägg under höglasttid. Tomt/0 = ingen.
    if "tou_extra" in body:
        v = body.get("tou_extra")
        try:
            v = 0.0 if v in (None, "") else float(str(v).replace(",", "."))
        except ValueError:
            return JSONResponse({"error": "Ogiltigt värde: tou_extra"}, status_code=400)
        if not 0 <= v <= 20:
            return JSONResponse({"error": "tou_extra utanför rimligt intervall"}, status_code=400)
        upd["price_tou_extra"] = v or None
        for key, field, lo, hi in (("price_tou_hours", "tou_hours", 0, 24), ("price_tou_months", "tou_months", 1, 12)):
            raw = str(body.get(field) or "").replace("–", "-").replace(" ", "")
            m = re.fullmatch(r"(\d{1,2})-(\d{1,2})", raw)
            if not m or not all(lo <= int(x) <= hi for x in m.groups()):
                return JSONResponse({"error": f"Ogiltigt intervall: {field} (t.ex. {'6-22' if field == 'tou_hours' else '11-3'})"}, status_code=400)
            upd[key] = f"{int(m.group(1))}-{int(m.group(2))}"
        upd["price_tou_weekdays"] = bool(body.get("tou_weekdays", True))
    if "power_high" in body:                         # #180: effekttariffens höglasttid
        ph = body.get("power_high") or {}
        choice = str(ph.get("choice") or "")
        if choice == "egen":
            for key, field, lo, hi in (("power_high_hours", "hours", 0, 24), ("power_high_months", "months", 1, 12)):
                raw = str(ph.get(field) or "").replace("–", "-").replace(" ", "")
                m = re.fullmatch(r"(\d{1,2})-(\d{1,2})", raw)
                if not m or not all(lo <= int(x) <= hi for x in m.groups()):
                    return JSONResponse({"error": f"Ogiltigt intervall för effekttariffen: {field} (t.ex. {'7-20' if field == 'hours' else '11-3'})"}, status_code=400)
                upd[key] = f"{int(m.group(1))}-{int(m.group(2))}"
            upd["power_high_enabled"] = True
            upd["power_high_weekdays"] = bool(ph.get("weekdays", True))
        elif choice == "av":
            upd["power_high_enabled"] = False
        else:                                        # tidstariffens tider / standard: inget eget val sparat
            upd.update(power_high_enabled=None, power_high_hours=None, power_high_months=None, power_high_weekdays=None)
    if "ha_entity" in body:
        ent = str(body.get("ha_entity") or "").strip()
        upd["price_ha_entity"] = ent if re.fullmatch(r"(sensor|event)\.[a-z0-9_]+", ent) else None
    try:
        validate_result(nordpool.cost_settings(), upd)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    ew_settings.update(**upd)
    return {"ok": True}


def _hidden_pages(cfg: dict) -> set:
    """#161: flikar för utrustning som installationen inte har döljs (en tom Spabad-flik ser trasig ut), plus de man
    själv valt att dölja (ui.hidden_tabs i house_config.yaml). Översikt, Inställningar och System döljs aldrig."""
    on = lambda k: bool((cfg.get(k) or {}).get("enabled"))
    hidden = set()
    if not on("spa"):
        hidden.add("spabad")
    if not (cfg.get("evs") or []):
        hidden.add("elbil")
    if not on("heat_pump"):
        hidden.add("varmepump")
    if not on("solar") and not on("battery"):          # Solceller-fliken visar även husbatteriet
        hidden.add("solceller")
    extra = (cfg.get("ui") or {}).get("hidden_tabs") or []
    if isinstance(extra, list):
        hidden |= {str(x) for x in extra}
    return hidden - {"oversikt", "installningar", "system"}


@app.get("/api/me")
async def me(request: Request):
    role, user = AUTH.session(request)
    try:
        hidden = _hidden_pages(house_config.load_house_config(HOUSE_CONFIG_FILE))
    except Exception:
        hidden = set()                                    # ingen/trasig installation: visa allt
    pages = [p for p in PAGES if p["built"] and p["id"] not in hidden]
    if TELEMETRY_STATS_URL and role == "owner":       # bara utvecklarens egen server, bara ägaren
        pages.insert(len(pages) - 1, INSTALLS_PAGE)
    import nordpool
    c = nordpool.cost_settings()
    return {"role": role, "user": user, "pages": pages,
            "currency": c["currency"], "currency_symbol": c["symbol"]}


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
    """Effekttariffens höglasttid ur inställningarna (#180), samma som motorn (nordpool.is_high_load_time)."""
    import nordpool
    return nordpool.is_high_load_time(dt)


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
        ov = _overrides(c, ("heat", "hotwater"))
        cfg = _settings_row(c, ("temp_cheap", "temp_expensive"))
    is_high_load = _is_high_load_time(row["sthlm_time"])
    import nordpool
    high_load_source = nordpool.high_load_window()["source"]

    return {
        "ok": True,
        "mode": mode,
        "heat_mode": ov.get("heat", "auto"), "hotwater_mode": ov.get("hotwater", "auto"),
        "temp_cheap": _n(cfg.get("temp_cheap")), "temp_expensive": _n(cfg.get("temp_expensive")),
        "decision": row.get("active_decision") or "Utvärderar…",
        "decision_items": _json_list(row.get("decision_summary")),     # vad görs nu och varför, per enhet
        "price": _n(row.get("price")),
        "indoor_temp": _n(row.get("indoor_temp")),
        "indoor_target": target_room,
        "indoor_humidity": _n(row.get("indoor_humidity")),
        "outdoor_temp": _n(row.get("outdoor_temp")),
        "net_power_w": _n(row.get("net_power")),
        "pv_power_w": _n(row.get("pv_power_w")),
        "water_temp": _n(row.get("water_temp")),
        # Båda laddboxarna (ev_* = Nissans, ev_carport_* = Teslas) - förut bara den ena, så rutan visade
        # 0 kW medan Teslan laddade.
        "ev_power_kw": (None if row.get("ev_power_kw") is None and row.get("ev_carport_power_kw") is None
                        else round((_n(row.get("ev_power_kw")) or 0) + (_n(row.get("ev_carport_power_kw")) or 0), 2)),
        "is_high_load": is_high_load,
        # Visas bara för den som har en effekt- eller tidstariff inställd (#180: alla såg Jönköpings tider)
        "high_load_source": high_load_source,
        # FTW-enheter som inte svarar eller inte ger sol/batteri (#184-#186: tomma flikar utan förklaring)
        "ftw_problems": [s for s in (ew_settings.get("ftw_status") or []) if isinstance(s, dict) and not s.get("ok")],
        "sthlm_time": str(row["sthlm_time"]),
        "price_24h": [{"t": r[0].isoformat(), "p": float(r[1])} for r in price_hist],
        "heat_battery": _heat_battery(row),
        "pump": _pump_block(row),
    }


def _pump_block(row):
    """Värmepumpens mätvärden för Värmepump-fliken. COP (uppmätt) = producerad värme / använd el senaste timmen ur pumpens
    egen energilogg (NIBE); den skattade COP:n (cop) räknas av motorn ur framledning och brinetemperatur."""
    produced, used = _n(row.get("heat_produced_kwh_1h")), _n(row.get("electric_used_kwh_1h"))
    return {"forward_temp": _n(row.get("forward_temp")), "return_temp": _n(row.get("return_temp")),
            "compressor_running": row.get("compressor_running"),
            "compressor_frequency_hz": _n(row.get("compressor_frequency_hz")),
            "compressor_power_w": _n(row.get("compressor_power_w")),
            "heat_produced_kwh_1h": produced, "electric_used_kwh_1h": used,
            "cop_1h": round(produced / used, 1) if produced is not None and used is not None and used >= 0.05 else None,
            "cop_est": _n(row.get("cop"))}


@app.get("/api/updates")
async def updates(request: Request, force: bool = False):
    """System-sidan: vilka containrar på hela NUC:en (inte bara EnergyWizard) har en
    nyare image enligt Watchtower. Cachas 10 min - force=1 kollar om direkt."""
    if not WATCHTOWER_TOKEN:          # ingen Watchtower här (HA-tillägget, de flesta installationer) - inget fel (#121)
        return {"ok": True, "configured": False, "addon": bool(homeassistant.SUPERVISOR_TOKEN)}
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


@app.get("/api/installs")
async def installs(request: Request):
    """System-sidan: hur många som kör EnergyWizard och med vilken utrustning (från telemetrisamlaren)."""
    role, _ = AUTH.session(request)
    if not TELEMETRY_STATS_URL or role != "owner":
        return {"ok": False, "configured": False}
    try:
        import telemetry
        try:
            cfg = house_config.load_house_config(HOUSE_CONFIG_FILE)
        except Exception:
            cfg = {}
        me = telemetry.house_hash(cfg, create=False)      # samma som motorn skickar (installationens slumpade ID)
        r = requests.get(TELEMETRY_STATS_URL, timeout=10, headers={"X-Stats-Token": TELEMETRY_STATS_TOKEN}, params={"me": me})
        r.raise_for_status()
        return {"ok": True, "configured": True, **r.json()}
    except (requests.RequestException, ValueError) as e:
        return {"ok": False, "configured": True, "error": f"Kunde inte nå telemetrisamlaren: {e}"}


def _latest_row(c):
    """Senaste raden i sensor_log som dict - delad av alla de nya datasidorna nedan
    istället för att varje endpoint skriver om samma SELECT * ... LIMIT 1."""
    row = c.execute(text(
        "SELECT *, timestamp AT TIME ZONE 'Europe/Stockholm' AS sthlm_time FROM sensor_log ORDER BY timestamp DESC LIMIT 1"
    )).mappings().first()
    return dict(row) if row else None


def _json_list(raw):
    import json
    try:
        v = json.loads(raw) if raw else []
        return v if isinstance(v, list) else []
    except (ValueError, TypeError):
        return []


def _overrides(c, keys):
    rows = c.execute(text("SELECT device, mode FROM overrides WHERE device = ANY(:k)"), {"k": list(keys)}).fetchall()
    return {r[0]: r[1] for r in rows}


def _settings_row(c, cols):
    row = c.execute(text(f"SELECT {', '.join(cols)} FROM system_settings WHERE id = 1")).mappings().first()
    return dict(row) if row else {}


def _price_24h(c):
    rows = c.execute(text(
        "SELECT time_start, sek_per_kwh FROM elpriser WHERE time_start >= now() - interval '24 hours' ORDER BY time_start"
    )).fetchall()
    return [{"t": r[0].isoformat(), "p": float(r[1])} for r in rows]


def _ewapp_cars() -> list:
    """Bilarna som mobilappen räknar fram ur installationen (house_config.yaml) och Home Assistant."""
    try:
        r = requests.get(f"{EWAPP_URL}/api/state", cookies={"ew": _ewapp_cookie()}, timeout=25)
        r.raise_for_status()
        return r.json().get("cars", []) or []
    except Exception as e:
        print(f"⚠️ Bilarna från mobilappen: {e}", flush=True)
        return []


def _car_limits(charger: dict, learned: dict) -> dict:
    """{"phases": "1"/"3"/"auto", "phases_src", "max_a", "max_a_src"} - src: installation / inlärt / standard."""
    out = {}
    if "phases" in charger:
        out.update(phases=str(charger["phases"]), phases_src="installation")
    elif learned.get("phases") in (1, 3, "1", "3"):
        out.update(phases=str(learned["phases"]), phases_src="inlärt")
    else:
        out.update(phases="auto", phases_src="standard")
    if charger.get("max_a"):
        out.update(max_a=int(charger["max_a"]), max_a_src="installation")
    elif isinstance(learned.get("max_a"), (int, float)) and 6 <= learned["max_a"] < 16:   # som motorn: bara lägre
        out.update(max_a=int(learned["max_a"]), max_a_src="inlärt")
    else:
        out.update(max_a=16, max_a_src="standard")
    return out


@app.get("/api/car")
async def api_car():
    """Elbil-sidan: SoC/laddstatus för båda bilarna + dagens schema (ev_charging_schedule)
    och planerade laddningspass (ev_plan_slots, summeras bara - full passplan hör hemma
    i ewapp:s egen editor, inte duplicerad här)."""
    with ENGINE.connect() as c:
        row = _latest_row(c)
        if row is None:
            return {"ok": False, "error": "Ingen data i sensor_log än"}
        # Hela veckan per bil (#142: förut bara dagens veckodag - planen på kvällen räknar på morgondagens rad)
        try:
            sched = c.execute(text("SELECT car_id, day_of_week, target_time, target_soc, enabled FROM ev_charging_schedule")).mappings().all()
        except Exception:
            c.rollback()
            sched = []
        planned = c.execute(text(
            "SELECT car_id, SUM(kw) / 4.0 AS kwh FROM ev_plan_slots WHERE t_slot::date = CURRENT_DATE GROUP BY car_id"   # 15-min-slottar: kW × 0,25 h
        )).mappings().all()
        try:
            slots = c.execute(text("SELECT car_id, t_slot, kw, start_soc, end_soc FROM ev_plan_slots "
                                   "WHERE t_slot >= (now() AT TIME ZONE 'Europe/Stockholm') - interval '15 minutes' ORDER BY t_slot")).fetchall()
            plan_prices = c.execute(text("SELECT time_start, sek_per_kwh FROM elpriser WHERE time_start >= now() - interval '1 hour' "
                                         "AND time_start < now() + interval '36 hours' ORDER BY time_start")).fetchall()
        except Exception:
            c.rollback()
            slots, plan_prices = [], []
    planned_by_car = {p["car_id"]: _n(p["kwh"]) for p in planned}
    # Bilarna ur installationen, live från mobilappens /api/state (samma bilar och entiteter som där) - inga
    # inbyggda bilnamn eller loggkolumner per bil (issue #113: andra såg Emils Tesla/Nissan utan värden).
    cars = []
    for c in _ewapp_cars():
        cars.append({"id": c.get("key"), "name": c.get("name"), "soc": _n(c.get("soc")), "stale": bool(c.get("soc_stale")),
                     "power_kw": _n(c.get("power_kw")), "status": c.get("status"),
                     "climate_temp": _n(c.get("inside")), "climate_state": "heat_cool" if c.get("climate_on") else "off"})
    # Faser och maxström per bil (roadmap): installationens värde, annars det motorn lärt sig av laddningarna
    # (ev_limits.py, "learned_ev"), annars standard (auto, 16 A)
    try:
        _evs = {e.get("id"): (e.get("charger") or {}) for e in (house_config.load_house_config(HOUSE_CONFIG_FILE).get("evs") or [])}
    except Exception:
        _evs = {}
    import ev_limits
    _learner = ev_limits.LimitLearner(ew_settings.get("learned_ev"))
    for car in cars:
        car["planned_kwh_today"] = planned_by_car.get(car["id"])
        car["limits"] = _car_limits(_evs.get(car["id"]) or {},
                                    {"phases": _learner.phases(car["id"]), "max_a": _learner.max_a(car["id"])})
    week = {car["id"]: [{"day": d, "time": "07:00", "soc": 100, "enabled": False} for d in range(7)] for car in cars}
    for s in sched:
        if s["car_id"] in week and 0 <= int(s["day_of_week"]) <= 6:
            week[s["car_id"]][int(s["day_of_week"])] = {"day": int(s["day_of_week"]), "enabled": bool(s["enabled"]),
                                                        "time": s["target_time"].strftime("%H:%M") if s["target_time"] else "07:00",
                                                        "soc": int(s["target_soc"] or 100)}
    from datetime import datetime
    now = datetime.now(zoneinfo.ZoneInfo("Europe/Stockholm"))
    goals = {g["car"]: g for g in _car_goals([(s["car_id"], int(s["day_of_week"]), s["target_time"], s["target_soc"])
                                               for s in sched if s["enabled"]], now)}
    for car in cars:
        car["next_goal"] = goals.get(car["id"])          # det mål planen räknar med just nu (dag, klockslag, %)
    return {"ok": True, "cars": cars, "session_kwh": _n(row.get("ev_session_kwh")),
            "current_a": _n(row.get("ev_current_a")), "dynamic_limit_a": _n(row.get("ev_dynamic_limit_a")),
            "current_target_limit": _n(row.get("current_target_limit")), "schedule": week,
            # Laddplanen per kvart (naiv svensk lokaltid i ev_plan_slots) + elpriset, för grafen
            "plan": [{"car": r[0], "t": r[1].isoformat(), "kw": _n(r[2]), "soc0": _n(r[3]), "soc1": _n(r[4])} for r in slots],
            "plan_prices": [{"t": t.astimezone(zoneinfo.ZoneInfo("Europe/Stockholm")).replace(tzinfo=None).isoformat(), "p": float(p)} for t, p in plan_prices if p is not None]}


@app.get("/api/solar")
async def api_solar():
    """Solceller-sidan: produktion, dagens energi, exportgräns och husbatteriet - allt
    redan loggat av smartbox i sensor_log varje cykel, ingen live HA-fråga behövs."""
    with ENGINE.connect() as c:
        row = _latest_row(c)
        if row is None:
            return {"ok": False, "error": "Ingen data i sensor_log än"}
        price_24h = _price_24h(c)
        ov = _overrides(c, ("solar_auto_export", "notify_solar_limit"))
        # Dagens produktion: växelriktarens egen räknare om den finns, annars uppmätt effekt minut för minut.
        pv_today = c.execute(text("SELECT sum(pv_power_w) / 60000.0 FROM sensor_log WHERE pv_power_w > 0 AND "
                                  "timestamp >= date_trunc('day', now() AT TIME ZONE 'Europe/Stockholm') AT TIME ZONE 'Europe/Stockholm'")).scalar()
    auto = str(ov.get("solar_auto_export", "true")).lower() != "false"
    price_now = _n(row.get("price"))
    return {"ok": True, "pv_power_w": _n(row.get("pv_power_w")),
            "solar_today_kwh": _n(row.get("solar_today_kwh")) if row.get("solar_today_kwh") is not None else _n(pv_today),
            "solar_forecast_w": _n(row.get("solar_forecast_w")), "solar_limit_pct": _n(row.get("solar_limit_pct")),
            "inverter_status": row.get("inverter_status"), "battery_soc": _n(row.get("battery_soc")),
            "battery_power_w": _n(row.get("battery_power_w")), "net_power_w": _n(row.get("net_power")),
            "price": _n(row.get("price")), "price_24h": price_24h,
            "auto_export": auto, "ai_limit": auto and price_now is not None and price_now < 0,
            "notify": ov.get("notify_solar_limit", "true") == "true"}


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
        import savings
        import nordpool
        from datetime import datetime
        import zoneinfo
        today = datetime.now(zoneinfo.ZoneInfo("Europe/Stockholm")).date().isoformat()
        money = savings.money_rows(c, days=40)
        timing = savings.daily_rows(c, days=40)
    prices = [float(r[0]) for r in today_prices if r[0] is not None]
    avg_price = sum(prices) / len(prices) if prices else None
    # Förut: accumulated_consumption_kwh × snittpris - fältet är alltid 0, så kortet visade 0,00 kr.
    return {"ok": True, "price": _n(row.get("price")), "price_min": min(prices) if prices else None,
            "price_avg": avg_price, "price_max": max(prices) if prices else None, "price_24h": price_24h,
            "symbol": nordpool.cost_settings()["symbol"], "money_days": money[-31:],
            "money": savings.money_periods(money, today), "timing": savings.summarize_periods(timing, today)}


@app.get("/api/savings")
async def api_savings():
    """Besparingskortet: per dag de senaste ~40 dygnen + Idag / 7 dagar / Månad. Samma formel
    som den publika sidan och HA-sensorn - se smartbox/savings.py."""
    import savings
    from datetime import datetime
    import zoneinfo
    today = datetime.now(zoneinfo.ZoneInfo("Europe/Stockholm")).date().isoformat()
    with ENGINE.connect() as c:
        rows = savings.daily_rows(c, days=40)
    return {"ok": True, "today": today, "days": rows[-31:], "periods": savings.summarize_periods(rows, today)}


@app.get("/api/plan")
async def api_plan():
    """Planen framåt i klartext: elbilens laddpass + värmepumpens grundläge enligt elpriset.
    Bygger ingen ny plan, beskriver bara motorns - se smartbox/plan_brief.py."""
    import nordpool
    import plan_brief
    from datetime import datetime
    import zoneinfo
    now = datetime.now(zoneinfo.ZoneInfo("Europe/Stockholm"))
    with ENGINE.connect() as c:
        prices = c.execute(text(
            "SELECT time_start, sek_per_kwh FROM elpriser "
            "WHERE time_start >= date_trunc('day', now() AT TIME ZONE 'Europe/Stockholm') AT TIME ZONE 'Europe/Stockholm' "
            "ORDER BY time_start")).fetchall()
        try:
            ev_rows = c.execute(text("SELECT car_id, t_slot, kw FROM ev_plan_slots")).fetchall()
        except Exception:
            c.rollback()
            ev_rows = []
        bat_rows = plan_brief.load_battery_rows(c)
        cheap_hours = _settings_row(c, ["cheap_hours_count"]).get("cheap_hours_count") or 8
        try:                       # bilarnas mål till planklockan: närmaste påslagna schema idag eller imorgon
            sched = c.execute(text("SELECT car_id, day_of_week, target_time, target_soc FROM ev_charging_schedule "
                                   "WHERE enabled")).fetchall()
        except Exception:
            c.rollback()
            sched = []
        mode_row = c.execute(text("SELECT active_mode FROM sensor_log WHERE active_mode IS NOT NULL "
                                  "ORDER BY timestamp DESC LIMIT 1")).fetchone()
        try:
            import solar_days
            sun = solar_days.load(c, now)
        except Exception:
            sun = None
    brief = plan_brief.build_brief(now, [(r[0], float(r[1])) for r in prices if r[1] is not None],
                                   [tuple(r) for r in ev_rows], nordpool.calculate_day_strategy,
                                   int(cheap_hours), mode_row[0] if mode_row else None, battery_rows=[tuple(r) for r in bat_rows],
                                   currency=nordpool.cost_settings()["currency"], symbol=nordpool.cost_settings()["symbol"])
    from datetime import timedelta
    clock_prices = [{"t": r[0].isoformat(), "spot": round(float(r[1]), 4), "total": round(nordpool.full_buy_cost(float(r[1]), r[0]), 4)}
                    for r in prices if r[1] is not None and now - timedelta(minutes=15) <= r[0] < now + timedelta(hours=24)]
    return {"ok": True, **brief, "solar_days": sun, "now": now.isoformat(), "prices": clock_prices,
            "car_goals": _with_plugged(_car_goals(sched, now))}


def _with_plugged(goals):
    """Lägger till om bilen är ansluten (evs[].entities.plugged_in i house_config): ett mål är bara en plan om
    kabeln sitter i. None = okänt (ingen sådan entitet)."""
    try:
        evs = {e.get("id"): e for e in (house_config.load_house_config(HOUSE_CONFIG_FILE).get("evs") or [])}
    except Exception:
        evs = {}
    for g in goals:
        ent = ((evs.get(g["car"]) or {}).get("entities") or {}).get("plugged_in")
        st = homeassistant._get_raw_state(ent) if ent else None
        g["plugged"] = None if st in (None, "unknown", "unavailable") else str(st).lower() in ("on", "true", "home", "1")
    return goals


def _car_goals(sched, now):
    """Nästa mål per bil ur laddschemat: {'car', 'at' (iso), 'soc'} - första påslagna dagen de kommande sju dygnen
    vars klockslag inte passerat, samma som motorn (decisions.get_car_plan_details, #142)."""
    from datetime import datetime, timedelta
    goals = {}
    for car, dow, tt, soc in sched or []:
        for add in range(8):
            day = (now + timedelta(days=add)).date()
            if day.weekday() != dow or tt is None:
                continue
            at = datetime.combine(day, tt if not isinstance(tt, str) else datetime.strptime(tt[:5], "%H:%M").time(),
                                  tzinfo=now.tzinfo)
            if at > now and (car not in goals or at < datetime.fromisoformat(goals[car]["at"])):
                goals[car] = {"car": car, "at": at.isoformat(), "soc": None if soc is None else int(soc)}
    return sorted(goals.values(), key=lambda g: g["at"])


@app.get("/api/flow")
async def api_flow():
    """Översiktens levande bild: vad som drar/ger el just nu, bara det huset har (live_flow.py)."""
    import live_flow
    with ENGINE.connect() as c:
        row = _latest_row(c)
    if row is None:
        return {"ok": False, "error": "Ingen data i sensor_log än"}
    cars, has_spa, _has_heat = _house_parts()
    d = live_flow.nodes(row, _json_list(row.get("decision_summary")), cars=cars, has_spa=has_spa)
    return {"ok": True, "ts": str(row.get("sthlm_time"))[:16], "battery_sign": _battery_sign_hint(row), **d}


def _battery_sign_hint(row):
    """#166/#139: huset = sol + nät - batteri (+ = laddar). Blir det kraftigt negativt men går ihop med omvänt tecken
    har batterisensorn troligen motsatt tecken. Då föreslår Översikt "Vänd tecknet" (bara om det inte är låst i
    house_config.yaml med battery.power_invert). None = inget att föreslå."""
    pv, net, bat = (_n(row.get(k)) for k in ("pv_power_w", "net_power", "battery_power_w"))
    if net is None:
        return None
    # #139: orimlig batterieffekt (över 15 kW) är fel givare, inte fel tecken
    implausible = bat is not None and abs(bat) > 15000
    raw = (pv or 0) + net - (bat or 0)
    if raw > -300 and not implausible:
        return None
    # #139: visa alltid delarna när huset blir negativt; knappen bara när ett omvänt batteritecken får det att gå ihop
    flipped = (pv or 0) + net + (bat or 0)
    flip_ok = bat is not None and abs(bat) >= 200 and flipped >= -100 and not implausible
    try:
        locked = "power_invert" in (house_config.load_house_config(HOUSE_CONFIG_FILE).get("battery") or {})
    except Exception:
        locked = False
    return {"house_w": round(raw), "house_w_flipped": round(flipped), "locked": locked, "flip_ok": flip_ok,
            "battery_implausible": implausible,
            "pv_w": round(pv or 0), "net_w": round(net), "battery_w": None if bat is None else round(bat),
            "inverted": bool(ew_settings.get("battery_power_invert", False))}


@app.get("/api/sign-settings")
async def sign_settings_get(request: Request):
    """#171: effektgivarnas tecken (batteri, nät) - valen i webben, och om house_config.yaml låser dem."""
    role, _ = AUTH.session(request)
    if role != "owner":
        return JSONResponse({"error": "Bara ägaren"}, status_code=403)
    try:
        hc = house_config.load_house_config(HOUSE_CONFIG_FILE)
    except Exception:
        hc = {}
    bat, pm = (hc.get("battery") or {}), (hc.get("power_meter") or {})
    pm_e = pm.get("entities") if isinstance(pm.get("entities"), dict) else pm
    return {"ok": True, "has_battery": bool(bat.get("enabled")),
            "battery": bool(ew_settings.get("battery_power_invert", False)), "battery_locked": "power_invert" in bat,
            "grid": bool(ew_settings.get("grid_power_invert", False)), "grid_locked": "power_w_invert" in (pm_e or {})}


@app.post("/api/sign-settings")
async def sign_settings_set(request: Request):
    role, _ = AUTH.session(request)
    if role != "owner":
        return JSONResponse({"error": "Bara ägaren"}, status_code=403)
    b = await request.json()
    upd = {}
    if "battery" in b:
        upd["battery_power_invert"] = bool(b["battery"])
    if "grid" in b:
        upd["grid_power_invert"] = bool(b["grid"])
    ew_settings.update(**upd)
    return {"ok": True}


@app.post("/api/battery-invert")
async def battery_invert(request: Request):
    """Vänder tecknet på batteriets effekt (ew_settings, gäller om house_config.yaml inte anger power_invert)."""
    role, _ = AUTH.session(request)
    if role != "owner":
        return JSONResponse({"error": "Bara ägaren kan ändra batteriets inställningar"}, status_code=403)
    new = not bool(ew_settings.get("battery_power_invert", False))
    ew_settings.update(battery_power_invert=new)
    return {"ok": True, "inverted": new}


def _house_parts():
    """Se live_flow.house_parts (delad med mobilappen)."""
    import live_flow
    try:
        hc = house_config.load_house_config(HOUSE_CONFIG_FILE)
    except Exception as e:
        print(f"⚠️ Bilar/spa ur installationen: {e}", flush=True)
        return None, None, None
    return live_flow.house_parts(hc)


@app.get("/api/planclock")
async def api_planclock():
    """Den dragbara planklockan: en rad per kvart 24 h framåt (smartbox/plan_clock.py, samma som mobilappen)."""
    import plan_clock
    cars, _spa, _heat = _house_parts()
    with ENGINE.connect() as c:
        return plan_clock.load(c, cars=[{"id": cid, "name": n} for cid, n, _col in (cars or [])])


@app.get("/planclock.js")
async def planclock_js():
    import plan_clock
    return FileResponse(os.path.join(os.path.dirname(plan_clock.__file__), "static", "planclock.js"),
                        media_type="application/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/journal.js")
async def journal_js():
    import plan_clock
    return FileResponse(os.path.join(os.path.dirname(plan_clock.__file__), "static", "journal.js"),
                        media_type="application/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/liveflow.js")
async def liveflow_js():
    import plan_clock
    return FileResponse(os.path.join(os.path.dirname(plan_clock.__file__), "static", "liveflow.js"),
                        media_type="application/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/planskyline.js")
async def planskyline_js():
    import plan_clock
    return FileResponse(os.path.join(os.path.dirname(plan_clock.__file__), "static", "planskyline.js"),
                        media_type="application/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/api/timeline")
async def api_timeline():
    """Dygnet timme för timme: uppmätt 24 h bakåt + planerat framåt (timeline.py)."""
    import timeline
    cars, has_spa, has_heat = _house_parts()
    with ENGINE.connect() as c:
        return timeline.load(c, cars=cars, has_spa=has_spa, has_heat=has_heat)


@app.get("/api/energyhistory")
async def api_energyhistory(range: str = "24h"):
    """Historik-sidan: energisummor Idag/7 dagar/30 dagar + effekt över tid + senaste värden
    (smartbox/energy_history.py, delad med mobilappen)."""
    import energy_history
    with ENGINE.connect() as c:
        return energy_history.history_payload(c, range)


@app.get("/api/consumption")
async def api_consumption():
    """Elförbrukning-sidan: fasströmmar/effekt just nu + senaste förklarade uppdelningen
    (load_breakdown - EV/pump/spa/oförklarat) och effektvaktens status."""
    with ENGINE.connect() as c:
        row = _latest_row(c)
        if row is None:
            return {"ok": False, "error": "Ingen data i sensor_log än"}
        try:
            lb = c.execute(text(
                "SELECT total_w, ev_w, pump_w, spa_w, unexplained_w, extra_w FROM load_breakdown ORDER BY timestamp DESC LIMIT 1"
            )).mappings().first()
        except Exception:                               # äldre databas utan extra_w (skapas av motorn vid nästa loggning)
            c.rollback()
            lb = c.execute(text(
                "SELECT total_w, ev_w, pump_w, spa_w, unexplained_w FROM load_breakdown ORDER BY timestamp DESC LIMIT 1"
            )).mappings().first()
        cfg = _settings_row(c, ("peak_shaving_enabled", "power_limit_kw", "fuse_size_a"))
    # avg_w_l1..3 är (trots namnet) fasströmmar i ampere ur elmätaren - visas i A mot huvudsäkringen (#130)
    cars, has_spa, has_heat = _house_parts()          # #191: bara det huset har (None = okänt -> visa allt)
    return {"ok": True, "fuse_size_a": _n(cfg.get("fuse_size_a")),
            "has_spa": has_spa, "has_heat": has_heat, "has_ev": None if cars is None else bool(cars),
            "avg_w_l1": _n(row.get("avg_w_l1")), "avg_w_l2": _n(row.get("avg_w_l2")),
            "avg_w_l3": _n(row.get("avg_w_l3")), "avg_w_tot": _n(row.get("avg_w_tot")),
            "house_consumption_w": _n(row.get("house_consumption_w")), "power_oven_w": _n(row.get("power_oven_w")),
            "power_computer_w": _n(row.get("power_computer_w")), "peak_shaving_active": bool(row.get("peak_shaving_active")),
            "predicted_base_load_kw": _n(row.get("predicted_base_load_kw")),
            "peak_shaving_enabled": bool(cfg.get("peak_shaving_enabled")), "power_limit_kw": _n(cfg.get("power_limit_kw")),
            "breakdown": ({**{k: _n(lb[k]) for k in ("total_w", "ev_w", "pump_w", "spa_w", "unexplained_w")},
                           "extra": [x for x in _json_list(lb.get("extra_w")) if isinstance(x, dict) and x.get("name")]} if lb else None)}


@app.get("/api/spa")
async def api_spa():
    """Spabad-sidan: temperatur, mål, värmarstatus och signalstyrka (RF-kanal till
    styrenheten) - direkt ur sensor_log, samma fält gpm.py redan styr mot."""
    with ENGINE.connect() as c:
        row = _latest_row(c)
        if row is None:
            return {"ok": False, "error": "Ingen data i sensor_log än"}
        cfg = _settings_row(c, ("spa_force_heat", "spa_normal_temp", "spa_max_temp", "spa_low_temp",
                                "spa_schedule_enabled", "spa_target_datetime", "spa_target_temp"))
        ov = _overrides(c, ("spa_force_eco",))
        hist = c.execute(text("""SELECT date_trunc('hour', timestamp AT TIME ZONE 'Europe/Stockholm') h, avg(spa_temp), avg(spa_target),
                                        avg(spa_heater_running::int) FROM sensor_log WHERE timestamp > now() - interval '24 hours'
                                 GROUP BY 1 ORDER BY 1""")).fetchall()
    return {"ok": True, "temp": _n(row.get("spa_temp")), "target": _n(row.get("spa_target")),
            "heater_running": bool(row.get("spa_heater_running")), "power_w": _n(row.get("spa_power_w")),
            "signal_pct": _n(row.get("spa_signal_pct")), "rf_channel": _n(row.get("spa_rf_channel")),
            "force_heat": bool(cfg.get("spa_force_heat")), "eco": ov.get("spa_force_eco") == "on",
            "normal_temp": _n(cfg.get("spa_normal_temp")), "max_temp": _n(cfg.get("spa_max_temp")), "low_temp": _n(cfg.get("spa_low_temp")),
            "ready_enabled": bool(cfg.get("spa_schedule_enabled")),
            "ready_at": cfg["spa_target_datetime"].astimezone(zoneinfo.ZoneInfo("Europe/Stockholm")).strftime("%Y-%m-%dT%H:%M") if cfg.get("spa_target_datetime") else None,
            "ready_temp": _n(cfg.get("spa_target_temp")),
            "bath_windows": _bath_windows(),
            "history": [{"t": h.isoformat(), "temp": _n(a), "target": _n(b), "heating": _n(hr)} for h, a, b, hr in hist]}


def _bath_windows() -> list:
    """Badtider (smartbox/spa_bath.py, samma som mobilappen)."""
    import spa_bath
    return spa_bath.listing(ew_settings.get("spa_bath_windows"))


@app.post("/api/spa-bath")
async def spa_bath_set(request: Request):
    role, _ = AUTH.session(request)
    if role != "owner":
        return JSONResponse({"error": "Bara ägaren kan ändra badtiderna"}, status_code=403)
    import spa_bath
    try:
        saved = spa_bath.clean((await request.json()).get("windows"))
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    ew_settings.update(spa_bath_windows=saved)
    return {"ok": True, "message": spa_bath.summary(saved)}


@app.get("/api/temperatures")
async def api_temperatures():
    """Temperaturer-sidan: rummen är de valda innegivarna (homeassistant.room_temps, samma som appens /api/rooms)."""
    with ENGINE.connect() as c:
        row = _latest_row(c)
    if row is None:
        return {"ok": False, "error": "Ingen data i sensor_log än"}
    rooms = homeassistant.room_temps()        # de valda innegivarna, live (#128 - inga fasta rum)
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
    with ENGINE.begin() as c:
        c.execute(text("CREATE TABLE IF NOT EXISTS ew_log (id BIGSERIAL PRIMARY KEY, ts TIMESTAMPTZ DEFAULT NOW(), usr TEXT, txt TEXT)"))
        rows = c.execute(text("SELECT ts, usr, txt FROM ew_log ORDER BY ts DESC LIMIT 80")).fetchall()
    return {"ok": True, "entries": [{"ts": r[0].isoformat(), "user": r[1], "text": r[2]} for r in rows]}


NOTIFY_LABELS = {
    "notify_spa_boost": "Spabadet värmer extra (boost)", "notify_spa_reconnect": "Spabadet tappade kontakten och är tillbaka",
    "notify_ev_full": "Elbilen är fulladdad", "notify_price_tip": "Pristips (ovanligt billig/dyr timme)",
    "notify_high_low": "Höglast/baslast byter", "notify_peak_shaving": "Effektvakten griper in",
    "notify_pump_alarm": "Värmepumpen larmar", "notify_pump_mode": "Värmepumpen byter läge",
    "notify_solar_error": "Solcellsväxelriktaren svarar inte", "notify_solar_limit": "Solexporten begränsas/släpps",
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


@app.post("/api/car/{car}/action")
async def proxy_car_action(car: str, request: Request):
    """Elbil-sidan: start/max/stop/auto-laddning + värm/stoppa klimatet - ewapp:s egen
    car_command()/heat_on/heat_off, bara anropad härifrån också."""
    if not re.fullmatch(r"[a-z0-9_]{1,40}", car or ""):
        return JSONResponse({"detail": "Okänd bil"}, status_code=404)
    body = await request.json()
    if body.get("kind") not in ("start", "max", "set", "stop", "auto", "heat_on", "heat_off"):
        return JSONResponse({"detail": "Okänd åtgärd"}, status_code=400)
    return await _ewapp_proxy(f"/api/car/{car}/action", body)


@app.post("/api/home-action/{what}")
async def proxy_home_action(what: str, request: Request):
    """Spabad-sidan: spa_heat/spa_auto/spa_eco, Värmepump-sidan: heat/hotwater - ewapp:s
    /api/home/{what}. Eget pathnamn (inte /api/home/{what}) så det inte krockar med en
    egen framtida webdashboard-endpoint under /api/home."""
    if what not in ("heat", "hotwater", "spa_heat", "spa_auto", "spa_eco", "spa_ready"):
        return JSONResponse({"detail": "Okänd åtgärd"}, status_code=404)
    body = await request.json()
    return await _ewapp_proxy(f"/api/home/{what}", body)


@app.post("/api/energy-action/{what}")
async def proxy_energy_action(what: str, request: Request):
    """Solceller-sidan: manuell exportgräns, prisgolv, avisering på/av - ewapp:s
    /api/energy/{what}."""
    if what not in ("limit", "auto", "notify"):
        return JSONResponse({"detail": "Okänd åtgärd"}, status_code=404)
    body = await request.json()
    return await _ewapp_proxy(f"/api/energy/{what}", body)


@app.get("/api/schedule")
async def schedule_get():
    """Laddschemat för hela veckan per bil (mobilappens /api/schedule)."""
    try:
        r = requests.get(f"{EWAPP_URL}/api/schedule", cookies={"ew": _ewapp_cookie()}, timeout=25)
        return JSONResponse(r.json(), status_code=r.status_code)
    except Exception as e:
        return JSONResponse({"detail": f"Nådde inte ewapp: {e}"}, status_code=502)


@app.post("/api/schedule")
async def proxy_schedule(request: Request):
    """Elbil-sidan: redigera laddschemat (klar kl/nivå per veckodag) - ewapp:s
    /api/schedule, samma ev_charging_schedule-tabell vi redan läser i /api/car."""
    return await _ewapp_proxy("/api/schedule", await request.json())


@app.post("/api/settings-action")
async def proxy_setting(request: Request):
    """Elförbrukning-sidan (effektvakt på/av + effektgräns) och Värmepump-sidan
    (billig/dyr måltemperatur) - ewapp:s /api/settings, begränsat till de nycklar
    webdashboards sidor faktiskt visar kontroller för."""
    body = await request.json()
    if body.get("key") not in ("peak_shaving_enabled", "power_limit_kw", "temp_cheap", "temp_expensive",
                               "spa_normal_temp", "spa_max_temp", "spa_low_temp"):
        return JSONResponse({"detail": "Okänd inställning"}, status_code=400)
    return await _ewapp_proxy("/api/settings", body)


@app.post("/api/secure")
async def secure(request: Request):
    """Lösenordet igen innan ett lås-/luckokommando går igenom - samma 10-minutersfönster
    som ewapp:s /api/secure, men verifierat lokalt (delad PASSWORD) istället för proxat,
    så webdashboard kan sätta sin egen ew2-kaka utan en extra nätverksrunda."""
    ip = AUTH.client_ip(request)
    if _secure_fails.get(ip, (0, 0))[0] >= 5 and time.time() - _secure_fails[ip][1] < 900:
        return JSONResponse({"detail": "För många försök – vänta en stund"}, status_code=429)
    body = await request.json()
    role, user = AUTH.session(request)
    expected = AUTH.user_password(user or "")
    if not expected or not hmac.compare_digest(str(body.get("password", "")), expected):
        _secure_fails[ip] = (_secure_fails.get(ip, (0, 0))[0] + 1, time.time())
        return JSONResponse({"detail": "Fel lösenord"}, status_code=401)
    _secure_fails.pop(ip, None)
    exp = int(time.time()) + 600
    r = JSONResponse({"ok": True, "until": exp})
    r.set_cookie("ew2", f"{exp}." + hmac.new(_EWAPP_SECRET, ("sec" + str(exp)).encode(), hashlib.sha256).hexdigest(), max_age=600, httponly=True, secure=True, samesite="lax", path="/")
    return r


@app.post("/api/tesla/access")
async def proxy_tesla_access(request: Request):
    """Lås/lås upp bilen, öppna/stäng luckor - ewapp:s /api/tesla/access. Allt utom 'lock'
    kräver en färsk /api/secure härifrån (INTE bara ewapp:s egen, se ovan) innan vi ens
    försöker proxa - annars kunde vem som helst med ett inloggat webdashboard-fönster
    låsa upp bilen utan att ange lösenordet igen."""
    body = await request.json()
    what = body.get("what")
    if what not in ("lock", "unlock", "trunk", "frunk"):
        return JSONResponse({"detail": "Okänd åtgärd"}, status_code=400)
    if what != "lock" and not _secure_ok(request):
        return JSONResponse({"detail": "secure"}, status_code=403)
    car = next((c.get("key") for c in _ewapp_cars() if c.get("access")), None)   # bilen som har lås valda i installationen
    if not car:
        return JSONResponse({"detail": "Ingen bil har lås valda i installationen"}, status_code=404)
    return await _ewapp_proxy(f"/api/car/{car}/access", body, extra_cookies={"ew2": request.cookies.get("ew2", "")})


@app.get("/api/tesla/access-state")
async def tesla_access_state():
    """Lås-/luckostatus (låst/upplåst, bak-/frontlucka öppen) för Elbil-sidan - ewapp:s
    egen /api/state beräknar redan det här (live HA-läsning), vi plockar bara ut biten för
    Tesla istället för att läsa HA-entiteterna en gång till här."""
    try:
        r = requests.get(f"{EWAPP_URL}/api/state", cookies={"ew": _ewapp_cookie()}, timeout=25)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return JSONResponse({"detail": f"Nådde inte ewapp: {e}"}, status_code=502)
    car = next((c for c in data.get("cars", []) if c.get("access")), None)
    return {"ok": True, "access": car.get("access") if car else None, "car": car.get("name") if car else None}


@app.post("/api/discover")
async def api_discover():
    """Entitetsväljare (Inställningar-sidan): skannar husets riktiga Home Assistant
    efter kandidat-entiteter per kategori. Live-anrop mot HA, bara på knapptryck -
    inte cachat/automatiskt som /api/overview."""
    try:
        res = {"ok": True, **discovery.discover_house()}
    except Exception as e:
        return {"ok": False, "error": f"Kunde inte skanna Home Assistant: {e}"}
    res["form"] = _wizard_form()                          # #173: tidigare sparade val fylls i även efter ny skanning
    try:                                                   # #168: senaste skanningen visas igen när man kommer tillbaka
        import json as _json
        res["scanned_at"] = time.time()
        tmp = _last_discovery_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            _json.dump(res, f, ensure_ascii=False)
        os.replace(tmp, _last_discovery_path())
    except Exception as e:
        print(f"⚠️ Kunde inte spara senaste skanningen: {e}")
    return res


def _last_discovery_path() -> str:
    return os.path.join(os.path.dirname(ew_settings.PATH) or ".", "last_discovery.json")


def _wizard_form_path() -> str:
    return os.path.join(os.path.dirname(ew_settings.PATH) or ".", "wizard_form.json")


def _wizard_form():
    try:
        import json as _json
        with open(_wizard_form_path(), encoding="utf-8") as f:
            return _json.load(f)
    except Exception:
        return None


@app.post("/api/discover/form")
async def api_discover_form(request: Request):
    """#173: guidens val (ikryssat, bilnamn, batteristorlek) sparas när man sparar installationen."""
    role, _ = AUTH.session(request)
    if role != "owner":
        return JSONResponse({"error": "Bara ägaren"}, status_code=403)
    body = await request.json()
    if not isinstance(body, dict) or len(str(body)) > 20000:
        return JSONResponse({"error": "Ogiltigt"}, status_code=400)
    import json as _json
    tmp = _wizard_form_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        _json.dump(body, f, ensure_ascii=False)
    os.replace(tmp, _wizard_form_path())
    return {"ok": True}


@app.get("/api/discover/last")
async def api_discover_last(request: Request):
    """Senaste skanningens resultat (sparat på servern, #168) - eller ok: False om ingen skanning gjorts."""
    role, _ = AUTH.session(request)
    if role != "owner":
        return JSONResponse({"error": "Bara ägaren"}, status_code=403)
    try:
        import json as _json
        with open(_last_discovery_path(), encoding="utf-8") as f:
            res = _json.load(f)
    except Exception:
        return {"ok": False}
    res["form"] = _wizard_form()
    return res


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
            # Easee: laddboxens serienummer (integrationens tjänster kräver det), annars enhetsnamnet
            _cid = charger.get("charger_id") if charger_driver == "easee" else None
            lines.append(f"      id: {_cid or charger.get('device_name') or car_id + '_laddare'}")
            lines.append(f"      driver: {charger_driver}  # ihopparningen bil<->laddare är en gissning (ordning på vad du kryssade i) - dubbelkolla den")
            if charger_driver == "easee" and not _cid:
                lines.append("      # FYLL I id: laddboxens serienummer (t.ex. EH123456), står i Easee-appen och i ström-sensorns attribut 'id'")
            if charger_driver == "easee" and charger.get("enable_switch"):
                lines.append(f"      enable_switch: {charger['enable_switch']}")
            lines.append("      entities:")
            charger_entities = {**(charger.get("easee_entities") or {}), **(charger.get("entities") or {})} \
                if charger_driver == "easee" else (charger.get("entities") or {}).copy()
            if charger.get("status_entity"):
                charger_entities.setdefault("status", charger["status_entity"])
            for key, val in charger_entities.items():
                lines.append(f"        {key}: {val}")
    lines.append("")

    hp = sel.get("heat_pump")
    if hp:
        hp_driver = hp.get("driver") or "generic_climate"
        lines += ["heat_pump:", "  enabled: true", f"  driver: {hp_driver}"]
        if hp_driver in ("generic_climate", "ha_entities"):
            lines += ["  entities:"]
            for key, val in (hp.get("entities") or {}).items():
                if re.fullmatch(r"[a-z_]+", str(key)) and re.fullmatch(r"[a-z_]+\.[a-z0-9_]+", str(val)):
                    lines.append(f"    {key}: {val}")
            if hp_driver == "ha_entities" and not (hp.get("entities") or {}).get("room_target"):
                lines.append("    # room_target: number.XXX  # valfritt - pumpens rumsbörvärde, behövs för att EnergyWizard ska styra")
        elif hp_driver == "thermiq":
            _pfx = str(hp.get("prefix") or "")
            if not re.fullmatch(r"thermiq_mqtt_[a-z0-9_]{1,40}", _pfx):
                _pfx = "thermiq_mqtt_vp1  # FYLL I - början på ThermIQ-entiteterna (sensor.<detta>_outdoor_t)"
            lines += [f"  prefix: {_pfx}"]
        elif hp_driver == "heishamon":
            lines += ["  host: 192.168.1.XXX  # FYLL I - HeishaMon-kortets IP (dess webbsida visar /json)",
                      "  base_shift: 0       # din vanliga kurvförskjutning (-5..5); EnergyWizard flyttar relativt den",
                      "  indoor_from_z1: false  # true bara om zon 1 har en rumsgivare"]
        else:
            lines += ["  connection:", "    modbus_host: 192.168.1.XXX  # FYLL I - värmepumpens IP/gateway, kan inte upptäckas automatiskt",
                       "    modbus_port: 502", "    unit_id: 1"]
    else:
        lines += ["heat_pump:", "  enabled: false"]
    lines.append("")

    solar = sel.get("solar")
    _ftw = sel.get("ftw") if isinstance(sel.get("ftw"), dict) and re.fullmatch(r"[a-z0-9_\-]{1,40}", str((sel.get("ftw") or {}).get("driver") or "")) else None
    if _ftw and _ftw.get("solar"):                           # FTW-drivrutin direkt mot växelriktaren
        lines += ["solar:", "  enabled: true", "  driver: ftw", "  ftw:", f"    driver: {_ftw['driver']}",
                  f"    host: {str(_ftw.get('host') or '').strip() or '192.168.1.XXX  # FYLL I - växelriktarens IP'}",
                  f"    port: {int(_ftw.get('port') or 502)}", f"    unit_id: {int(_ftw.get('unit_id') or 1)}", ""]
        solar = None
    elif solar:
        lines += ["solar:", "  enabled: true", f"  driver: {solar.get('driver') or 'generic_number'}", "  entities:"]
        solar_entities = (solar.get("entities") or {}).copy()
        if solar.get("pv_power_entity"):
            solar_entities.setdefault("pv_power_w", solar["pv_power_entity"])
        if solar.get("today_kwh_entity"):
            solar_entities.setdefault("today_kwh", solar["today_kwh_entity"])
        for key, val in solar_entities.items():          # lista/ja-nej (sum_inverters) som JSON - giltig YAML
            lines.append(f"    {key}: {val if isinstance(val, str) else json.dumps(val)}")
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

    ftw = sel.get("ftw") if isinstance(sel.get("ftw"), dict) else None
    if ftw and not re.fullmatch(r"[a-z0-9_\-]{1,40}", str(ftw.get("driver") or "")):
        ftw = None
    ftw_block = []
    if ftw:
        host = str(ftw.get("host") or "").strip()
        ftw_block = ["  ftw:", f"    driver: {ftw['driver']}", f"    host: {host or '192.168.1.XXX  # FYLL I - enhetens IP'}",
                     f"    port: {int(ftw.get('port') or 502)}", f"    unit_id: {int(ftw.get('unit_id') or 1)}",
                     "  # control_unverified: true   # styrning via FTW-drivrutinen på egen risk (overifierad) - börja i skuggläge"]
    battery = sel.get("battery")
    if ftw and ftw.get("battery"):                           # FTW-drivrutin direkt mot batteriet (ingen HA-integration)
        if ftw.get("control"):                               # styrning via FTW-drivrutinen, valt i guiden (overifierad)
            ctl = ["  control: styr        # EnergyWizard laddar billigt och laddar ur dyrt", "  control_unverified: true   # drivrutinen är inte provad på riktig hårdvara - börja i skuggläge"]
            fb = [x for x in ftw_block if "control_unverified" not in x]
        else:
            ctl = ["  control: samarbete   # läs bara; styrning kräver en verifierad FTW-drivrutin"]
            fb = ftw_block
        lines += ["battery:", "  enabled: true", "  driver: ftw", "  capacity_kwh: 10  # FYLL I - batteriets kapacitet i kWh"] + ctl + [
                  "  reserve_soc: 20", "  priority_soc: 50", "  max_power_w: 5000    # FYLL I"] + fb
        battery = None
    elif battery:
        gs = battery.get("generic_suggestion") or {}
        modes = battery.get("modes") or gs.get("modes")
        lines += ["battery:", "  enabled: true", f"  driver: {battery.get('driver') or 'generic'}",
                   "  capacity_kwh: 10  # FYLL I - batteriets kapacitet i kWh",
                   "  control: samarbete   # samarbete = läs bara (ett annat system styr) | styr = EnergyWizard styr | av",
                   "  reserve_soc: 20      # sparas alltid till strömavbrott (%)",
                   "  priority_soc: 50     # över detta får elbilen solöverskottet före batteriet (%)",
                   "  max_power_w: 5000    # FYLL I - batteriets max ladd-/urladdningseffekt (W)"]
        if gs.get("preset") and re.fullmatch(r"[a-z0-9_]{1,40}", str(gs["preset"])):
            lines.append(f"  preset: {gs['preset']}   # vilken förinställning lägena kommer från (för telemetrin)")
        if gs.get("keepalive_s"):
            lines.append(f"  keepalive_s: {int(gs['keepalive_s'])}     # skriv om laddkommandot så här ofta (växelriktarens fjärrstyrning släpper annars)")
        if modes:
            lines.append(f"  modes:               # förifyllt för {gs.get('preset') or 'din integration'} - kontrollera mot HA")
            for intent, opt in modes.items():
                if isinstance(opt, list) or (isinstance(opt, dict) and any(not isinstance(v, str) for v in opt.values())):
                    lines.append(f"    {intent}: {json.dumps(opt, ensure_ascii=False)}")   # tjänsteanrop (t.ex. Huawei) - JSON är giltig YAML
                elif isinstance(opt, dict):
                    pairs = ", ".join(f'{k}: "{v}"' for k, v in opt.items())
                    lines.append(f"    {intent}: {{{pairs}}}")
                else:
                    lines.append(f'    {intent}: "{opt}"')
        else:
            lines += ["  # modes:              # krävs för 'styr' - exakt de alternativ batteriets select visar i HA",
                      "  #   auto: \"Maximize self-consumption\"",
                      "  #   hold: \"...\"", "  #   idle: \"...\"", "  #   charge: \"...\"", "  #   discharge: \"...\""]
        lines.append("  entities:")
        battery_entities = (battery.get("entities") or gs.get("entities") or {}).copy()
        if battery.get("soc_entity"):
            battery_entities.setdefault("soc", battery["soc_entity"])
        if battery.get("power_entity") and "power_charge" not in battery_entities:
            battery_entities.setdefault("power", battery["power_entity"])
        for key, val in battery_entities.items():
            if isinstance(val, list):                     # flera batteribankar (#86)
                lines.append(f"    {key}: [{', '.join(str(v) for v in val)}]")
            else:
                lines.append(f"    {key}: {val}")
        if isinstance(battery_entities.get("soc"), list):
            lines.append(f"    bank_kwh: [{', '.join('10' for _ in battery_entities['soc'])}]   # FYLL I - varje banks storlek i kWh, samma ordning")
    else:
        lines += ["battery:", "  enabled: false"]
    pm = sel.get("power_meter")
    if pm and pm.get("entities"):
        lines += ["", "power_meter:   # nätimport/-export och fasströmmar (effektvakt, säkringsskydd, solladdning)",
                  f"  driver: {pm.get('driver') or 'power_w'}", "  entities:"]
        for key, val in pm["entities"].items():
            lines.append(f"    {key}: {val}")
        if pm.get("driver") == "power_w":
            lines.append("    # power_w_invert: true   # om mätaren visar EXPORT som positivt")
        if pm.get("secondary_power_w") and re.fullmatch(r"sensor\.[a-z0-9_]+", str(pm["secondary_power_w"])):
            lines.append(f"  secondary_power_w: {pm['secondary_power_w']}   # annan byggnad - visas, styr inte säkringsskyddet")
    lines += ["", "fuse:", "  main_fuse_a: 25  # FYLL I - din huvudsäkring i Ampere"]

    # Ett "entities:" utan rader under blir None i YAML - skriv en tom lista över givare i stället (#127)
    def _indent(t):
        return len(t) - len(t.lstrip())
    for i, ln in enumerate(lines):
        if ln.rstrip().endswith("entities:"):
            nxt = next((x for x in lines[i + 1:] if x.strip() and not x.strip().startswith("#")), "")
            if _indent(nxt) <= _indent(ln):
                lines[i] = ln.rstrip() + " {}"
    return "\n".join(lines) + "\n"


@app.get("/api/ftw-drivers")
async def ftw_drivers():
    """Sourcefuls FTW-drivrutiner som följer med (smartbox/ftw_drivers): namn, tillverkare, vad de kan, protokoll."""
    import re as _re
    import plan_clock
    folder = os.path.join(os.path.dirname(plan_clock.__file__), "ftw_drivers")
    out = []
    for f in sorted(os.listdir(folder)):
        if not f.endswith(".lua"):
            continue
        try:
            full = open(os.path.join(folder, f), encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        head = full[:6000]
        # Batteristyrning: drivrutinen tar emot kommandot "battery" (driver_command), som pixii, deye, sigenergy
        _cmd = _re.search(r"^function driver_command\b.*?^end", full, _re.M | _re.S)
        can_control = bool(_cmd and '"battery"' in _cmd.group(0))
        g = lambda k: (_re.search(k + r'\s*=\s*"([^"]*)"', head) or [None, None])[1]
        caps = _re.search(r'capabilities\s*=\s*\{([^}]*)\}', head)
        out.append({"id": f[:-4], "name": g("name") or f[:-4], "manufacturer": g("manufacturer") or "",
                    "protocol": (_re.search(r'^PROTOCOL\s*=\s*"([^"]+)"', head, _re.M) or [None, ""])[1],
                    "capabilities": _re.findall(r'"([a-z0-9_-]+)"', caps.group(1)) if caps else [],
                    "verification": g("verification_status") or "", "can_control": can_control})
    return {"ok": True, "drivers": out}


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
    return Response(content=yaml_text, media_type="text/yaml",
                     headers={"Content-Disposition": "attachment; filename=house_config.yaml"})


HOUSE_CONFIG_FILE = os.environ.get("HOUSE_CONFIG_PATH", "/house_config.yaml")


def _config_writable() -> bool:
    """Bara installationer som install.sh skapat sparar härifrån (HOUSE_CONFIG_WRITABLE=1
    och filen monterad skrivbar). En handskriven config skrivs aldrig över från webben."""
    return os.environ.get("HOUSE_CONFIG_WRITABLE") == "1" and os.access(HOUSE_CONFIG_FILE, os.W_OK)


@app.get("/api/house-config-status")
async def api_house_config_status(request: Request):
    role, _ = AUTH.session(request)
    return {"writable": role == "owner" and _config_writable()}


@app.post("/api/save-house-config")
async def api_save_house_config(request: Request):
    role, _ = AUTH.session(request)
    if role != "owner":
        return JSONResponse({"ok": False, "error": "Bara ägaren kan spara"}, status_code=403)
    if not _config_writable():
        return JSONResponse({"ok": False, "error": "Den här installationen sparar inte från webben. Ladda ner filen i stället."},
                            status_code=409)
    resp = await api_generate_house_config(request)
    if not isinstance(resp, Response):
        return resp
    if getattr(resp, "status_code", 200) != 200:
        return resp
    # Skrivs på plats (samma fil, inte en ny): Docker monterar filen, och en ny fil syns inte i motorn.
    with open(HOUSE_CONFIG_FILE, "w", encoding="utf-8") as f:
        f.write(resp.body.decode("utf-8"))
    return {"ok": True, "message": "Sparat. Motorn startar om och läser in den nya inställningen inom en minut."}


import i18n_routes  # noqa: E402
i18n_routes.register(app)
import web_common  # noqa: E402
web_common.register(app, lambda r: AUTH.session(r)[0], lambda: not webauth.owner_password())
app.mount("/static", StaticFiles(directory="static"), name="static")


_INDEX_CACHE = {"key": None, "html": ""}


def _index_html() -> str:
    """index.html med versionsmärkta app.js/style.css (?v=innehållets hash). #167: Home Assistant-appen på iOS visade en
    sparad, gammal style.css trots Cache-Control: no-cache - ett nytt filnamn per version hämtas alltid på nytt."""
    import hashlib
    files = ("static/index.html", "static/app.js", "static/style.css")
    key = tuple(os.path.getmtime(f) for f in files)
    if _INDEX_CACHE["key"] != key:
        html = open(files[0], encoding="utf-8").read()
        for name in ("app.js", "style.css"):
            v = hashlib.sha1(open(f"static/{name}", "rb").read()).hexdigest()[:10]
            html = html.replace(f'"static/{name}"', f'"static/{name}?v={v}"')
        _INDEX_CACHE.update(key=key, html=html)
    return _INDEX_CACHE["html"]


@app.get("/{full_path:path}")
async def spa(full_path: str):
    return HTMLResponse(_index_html(), headers={"Cache-Control": "no-cache"})
