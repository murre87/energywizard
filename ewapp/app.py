"""EnergyWizard Mobil (ewapp): lättviktig mobilsida för laddning. Delar HA-, databas- och överstyrningslogik med smartbox (monteras från ./smartbox).
Serveras under /m/ (nginx tar bort prefixet). Allt kräver inloggning med samma lösenord som dashboarden. Bil-knapparna skriver samma överstyrningar som dashboarden (overrides) och slår på/av laddaren direkt."""
import base64, hashlib, hmac, ipaddress, json, math, os, re, sys, time, datetime as dt
from zoneinfo import ZoneInfo

sys.path.insert(0, "/smartbox")
import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine, text

import homeassistant as H
import timed_override   # #397: varmvatten "Till" med tid

TZ = ZoneInfo("Europe/Stockholm")
try:
    import ew_settings
except ImportError:                   # äldre smartbox/ på värden: bara DASHBOARD_PASSWORD, som förut
    ew_settings = None
_ENV_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "")
PASSWORD = _ENV_PASSWORD or (ew_settings.get("dashboard_password", "") if ew_settings else "") or ""
SECRET = hashlib.sha256(("ewapp|" + PASSWORD).encode()).digest()


def _sync_password():
    """Lösenordet från webbens startguide gäller direkt, utan omstart (bara när det inte
    kommer från DASHBOARD_PASSWORD)."""
    global PASSWORD, SECRET
    if _ENV_PASSWORD or ew_settings is None:
        return
    pw = ew_settings.get("dashboard_password", "") or ""
    if pw != PASSWORD:
        PASSWORD, SECRET = pw, hashlib.sha256(("ewapp|" + pw).encode()).digest()
ENGINE = create_engine(f"postgresql+psycopg://{os.environ['POSTGRES_USER']}:{os.environ['POSTGRES_PASSWORD']}@{os.environ.get('POSTGRES_HOST', 'postgres-smartbox')}/{os.environ['POSTGRES_DB']}", pool_pre_ping=True, pool_size=3)

# Bilarna och deras laddboxar kommer från installationen (house_config.yaml, evs[]) - inga bilar eller entiteter är
# inbyggda (2026-11-04). Valfria entiteter (lås, luckor, knappar, räckvidd ...) visas bara om de är valda.
import house_config as HC

HOUSE_CONFIG_PATH = os.environ.get("HOUSE_CONFIG_PATH", "/house_config.yaml")


def _load_cars():
    try:
        cfg = HC.load_house_config(HOUSE_CONFIG_PATH)
    except Exception as e:
        print(f"⚠️ Kunde inte läsa {HOUSE_CONFIG_PATH}: {e}", flush=True)
        cfg = {}
    drivers = HC.build_charger_drivers(cfg)
    specs = HC.car_specs(cfg)
    cars = {}
    for ev in cfg.get("evs") or []:
        cid = ev.get("id")
        if not cid:
            continue
        e = ev.get("entities") or {}
        ch = ev.get("charger") or {}
        ce = ch.get("entities") or {}
        cars[cid] = {
            "name": ev.get("name") or cid.capitalize(), "charger": getattr(drivers.get(cid), "id", "") or "",
            "status": ce.get("status"), "power": ce.get("power_kw") or ce.get("power"), "online": ce.get("online"),
            "soc": e.get("soc"), "tracker": e.get("tracker"), "cap_kwh": float(ev.get("battery_kwh") or 60),
            "phases": 1 if specs.get(cid, {}).get("phases") == "1" else 3, "fixed_phases": specs.get(cid, {}).get("phases") == "1",
            "max_a": int(ch["max_a"]) if ch.get("max_a") else None,      # installationens maxström (#182), annars inlärd/16
            "arrival": e.get("arrival_time"), "dist": e.get("distance_to_arrival"), "destination": e.get("destination_tracker"),
            "climate": e.get("climate"), "inside": e.get("inside_temp"), "shift": e.get("shift_state"),
            "lock": e.get("lock"), "trunk": e.get("trunk"), "frunk": e.get("frunk"),
            "facts": {k: e.get(k) for k in ("range", "outside_temp", "daily_distance") if e.get(k)},
            "tpms": [x for x in (e.get("tpms") or []) if x],
            "buttons": {k: e.get(f"{k}_button") for k in ("flash", "horn", "wake", "refresh", "start_charge") if e.get(f"{k}_button")},
            "notify": ev.get("notify"),           # vilka användares telefoner som får bilens aviseringar (tomt = alla)
            "sleeps": bool(e.get("wake_button") or e.get("update_button")),  # bilen somnar/hämtar bara på begäran - larma inte i onödan
        }
    return cars, drivers


CARS, CHARGER_DRV = _load_cars()


def _load_house_parts():
    """Sol, spabad och väder ur installationen (house_config.yaml) - inga husspecifika entitetsnamn i appen."""
    try:
        cfg = HC.load_house_config(HOUSE_CONFIG_PATH)
    except Exception:
        cfg = {}
    sol = cfg.get("solar") or {}
    on = bool(sol.get("enabled"))
    se = (sol.get("entities") or {}) if on else {}
    is_se = on and sol.get("driver") == "solaredge"

    def chain(own, defaults):
        own = H._as_list(own)
        return own + ([d for d in defaults if d not in own] if is_se else [])
    try:
        drv = HC.build_solar_driver(cfg) if on else None
    except Exception as e:
        print(f"⚠️ Soldrivrutinen: {e}", flush=True)
        drv = None
    solar = {"pv": chain(se.get("pv_power_w"), H.SOLAREDGE_DEFAULT_PV), "today": chain(se.get("today_kwh"), H.SOLAREDGE_DEFAULT_TODAY),
             "status": chain(se.get("status"), H.SOLAREDGE_DEFAULT_STATUS),
             "limit": (sol.get("curtailment") or {}).get("entity") or se.get("limit") or (H.SOLAREDGE_DEFAULT_LIMIT if is_se else None),
             "driver": drv}
    spa = cfg.get("spa") or {}
    spa_e = (spa.get("entities") or {}) if spa.get("enabled") else {}
    ents = set()

    def walk(x):
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        elif isinstance(x, str) and re.fullmatch(r"[a-z_]+\.[a-z0-9_]+", x):
            ents.add(x)
    walk(cfg)
    return solar, spa_e, cfg.get("weather_entity"), ents


SOLAR, SPA_E, WEATHER_CFG, CFG_ENTITIES = _load_house_parts()


def first_num(st: dict, ents):
    for e in ents or []:
        v = num(st, e)
        if v is not None:
            return v
    return None


def attr_num(st: dict, e, a):
    try:
        v = ((st.get(e) or {}).get("attributes") or {}).get(a) if e else None
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def spa_temps(st: dict):
    """(vattentemp, måltemp, värmarens läge) ur spa.entities."""
    e = SPA_E
    temp = num(st, e["current_temp"]) if e.get("current_temp") else None
    target = num(st, e["target_temp"]) if e.get("target_temp") else None
    if e.get("climate"):
        temp = temp if temp is not None else attr_num(st, e["climate"], "current_temperature")
        t = attr_num(st, e["climate"], "temperature")
        target = t if t is not None else target
    return temp, target, (val(st, e["water_heater"]) if e.get("water_heater") else None)


def weather_entity(st: dict):
    """Väderentiteten: weather_entity i installationen, annars den första weather.* i Home Assistant."""
    if WEATHER_CFG:
        return WEATHER_CFG
    return next((e for e in sorted(st) if e.startswith("weather.")), None)
WATCH_AFTER_S = {c["soc"]: 48 * 3600 for c in CARS.values() if c["sleeps"] and c["soc"]}
WATCH = [x for c in CARS.values() for x in (c["status"], c["soc"]) if x]

app = FastAPI(title="EnergyWizard Mobil")
try:
    import ew_journal
    ew_journal.install("app")                  # installationens logg (smartbox/ew_journal.py)
except Exception as _je:
    print(f"⚠️ Loggen startade inte: {_je}")
_cache = {"t": 0.0, "states": {}}


# -- inloggning ------------------------------------------------------------------------------------------------------
GUEST_USER, GUEST_PASS = os.environ.get("GUEST_USER", ""), os.environ.get("GUEST_PASS", "")
EXTRA_USERS = {}                                   # EW_USERS="elin:713803:family,namn2:lösen2": egna konton. Roll family (standard) = bil, schema, ljus; owner = allt
EXTRA_ROLES = {}
for _pair in os.environ.get("EW_USERS", "").split(","):
    _parts = _pair.strip().split(":")
    if len(_parts) >= 2 and _parts[0].strip() and _parts[1].strip():
        EXTRA_USERS[_parts[0].strip().lower()] = _parts[1].strip()
        EXTRA_ROLES[_parts[0].strip().lower()] = _parts[2].strip() if len(_parts) > 2 and _parts[2].strip() in ("owner", "family") else "family"


def _sign(exp: int, role: str = "owner", user: str = "") -> str:
    user = (user or role).replace(".", "_")
    return f"{exp}.{role}.{user}.{hmac.new(SECRET, f'{exp}.{role}.{user}'.encode(), hashlib.sha256).hexdigest()}"


def _session(request: Request):
    """(roll, användare) ur kakan, eller (None, None). Roll: owner (full åtkomst) eller guest (bara titta)."""
    v = request.cookies.get("ew", "")
    try:
        exp, role, user, sig = v.split(".", 3)
        if int(exp) > time.time() and role in ("owner", "family", "guest") and hmac.compare_digest(sig, hmac.new(SECRET, f"{exp}.{role}.{user}".encode(), hashlib.sha256).hexdigest()):
            return role, user
    except Exception:
        pass
    return None, None


def _role(request: Request):
    return _session(request)[0]


def _ok(request: Request) -> bool:
    return _role(request) is not None


def _user_password(user: str):
    """Lösenordet för den inloggade användaren (används för omverifiering vid upplåsning av bilen)."""
    if user == "owner":
        return PASSWORD
    return EXTRA_USERS.get(user.lower())


def client_ip(request: Request) -> str:
    """Klientens IP. X-Forwarded-For litas bara när anropet kommer från vår egen proxy (privat nät): annars kan klienten förfalska den och kringgå inloggningsspärren."""
    peer = request.client.host if request.client else "?"
    try:
        trusted = ipaddress.ip_address(peer).is_private
    except ValueError:
        trusted = False
    xff = [x.strip() for x in request.headers.get("x-forwarded-for", "").split(",") if x.strip()]
    return xff[-1] if (xff and trusted) else peer


_fails: dict = {}


@app.post("/api/login")
async def login(request: Request):
    ip = client_ip(request)
    if _fails.get(ip, (0, 0))[0] >= 8 and time.time() - _fails[ip][1] < 600:
        raise HTTPException(429, "För många försök – vänta några minuter")
    body = await request.json()
    user, pw = str(body.get("user", "")).strip(), str(body.get("password", ""))
    role = who = None
    if user.lower() in ("", "admin") and PASSWORD and hmac.compare_digest(pw, PASSWORD):
        role, who = "owner", "owner"
    elif user.lower() in EXTRA_USERS and hmac.compare_digest(pw, EXTRA_USERS[user.lower()]):
        role, who = EXTRA_ROLES.get(user.lower(), "family"), user.lower()
    elif GUEST_USER and GUEST_PASS and hmac.compare_digest(user.lower(), GUEST_USER.lower()) and hmac.compare_digest(pw, GUEST_PASS):
        role, who = "guest", GUEST_USER.lower()
    if not role:
        n = _fails.get(ip, (0, 0))[0] + 1
        _fails[ip] = (n, time.time())
        raise HTTPException(401, "Fel användarnamn eller lösenord")
    _fails.pop(ip, None)
    print(f"🔑 ewapp inloggning: {who} ({role})", flush=True)
    r = JSONResponse({"ok": True, "role": role, "user": who})
    days = 90 if role in ("owner", "family") else 30
    r.set_cookie("ew", _sign(int(time.time()) + days * 86400, role, who), max_age=days * 86400, httponly=True, secure=True, samesite="lax", path="/")
    return r


@app.post("/api/logout")
async def logout():
    r = JSONResponse({"ok": True})
    for k in ("ew", "ew2"):
        r.delete_cookie(k, path="/")
    return r


@app.middleware("http")
async def guard(request: Request, call_next):
    _sync_password()
    p = request.url.path
    if p.startswith("/api/") and p not in ("/api/login", "/api/logout"):
        role = _role(request)
        if role is None:
            return JSONResponse({"detail": "Inte inloggad"}, status_code=401)
        if role == "guest" and request.method != "GET" and p != "/api/clienterr":
            return JSONResponse({"detail": "Gästläge: du kan bara titta, inte ändra något"}, status_code=403)
        if role == "family" and request.method != "GET" and not (p.startswith(("/api/car/", "/api/tesla/", "/api/lights", "/api/trip", "/api/schedule", "/api/secure", "/api/clienterr"))):
            return JSONResponse({"detail": "Det här kan bara administratören ändra"}, status_code=403)
    resp = await call_next(request)
    resp.headers.update({"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer", "Strict-Transport-Security": "max-age=31536000",
                         "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()"})
    if p.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"            # styrdata ska aldrig ligga kvar i en cache
    return resp


# -- data --------------------------------------------------------------------------------------------------------------
def states() -> dict:
    if time.time() - _cache["t"] < 3:
        return _cache["states"]
    last = None
    for attempt in range(2):                           # Home Assistant tappar ibland en TLS-handskakning: försök en gång till
        try:
            r = requests.get(f"{H._BASE}/states", headers=H._HEADERS, timeout=8, verify=False)
            r.raise_for_status()
            _cache.update(t=time.time(), states={s["entity_id"]: s for s in r.json()})
            return _cache["states"]
        except Exception as e:
            last = e
            time.sleep(0.4)
    if _cache["states"] and time.time() - _cache["t"] < 180:
        return _cache["states"]                        # hellre lite gamla värden än ett fel i appen
    raise last


def val(st: dict, e: str):
    s = st.get(e)
    return None if s is None or s["state"] in ("unavailable", "unknown", "") else s["state"]


def num(st: dict, e: str):
    v = val(st, e)
    try:
        return float(v) if v is not None else None
    except ValueError:
        return None


def overrides() -> dict:
    try:
        with ENGINE.connect() as c:
            return {r[0]: r[1] for r in c.execute(text("SELECT device, mode FROM overrides"))}
    except Exception:
        return {}


def _guest_of(ov: dict, key: str):
    """Gästbil på bilens laddbox (smartbox/guest_charge.py): {kwh, until} eller None."""
    try:
        d = json.loads(ov.get(f"guest_{key}") or "null")
        return {"kwh": d.get("kwh"), "until": d.get("until")} if isinstance(d, dict) and d.get("kwh") else None
    except ValueError:
        return None


@app.post("/api/car/{car}/guest")
async def car_guest(car: str, request: Request):
    """Gästbil på den här bilens laddbox: {"kwh": 20, "until": "07:00" | null} eller {"off": true} (#131)."""
    if car not in CARS:
        raise HTTPException(400, "Okänd bil")
    b = await request.json()
    if b.get("off"):
        set_override(f"guest_{car}", "off")
        logact(request, f"Gästbil på {CARS[car]['name']}s laddbox: avslutad")
        return {"ok": True, "msg": "Gästläget avslutat"}
    kwh = max(1.0, min(100.0, float(intval(b.get("kwh")) or 0) or 0))
    if not b.get("kwh"):
        raise HTTPException(400, "Ange hur många kWh")
    until = None
    if b.get("until"):
        try:
            hh = dt.datetime.strptime(str(b["until"]), "%H:%M").time()
        except ValueError:
            raise HTTPException(400, "Ogiltig tid")
        now = dt.datetime.now(TZ)
        u = dt.datetime.combine(now.date(), hh, tzinfo=TZ)
        until = (u if u > now else u + dt.timedelta(days=1)).isoformat()
    set_override(f"guest_{car}", json.dumps({"kwh": kwh, "until": until, "set_at": dt.datetime.now(TZ).isoformat()}))
    logact(request, f"Gästbil på {CARS[car]['name']}s laddbox: {kwh:.0f} kWh" + (f" klar {b['until']}" if until else " direkt"))
    return {"ok": True, "msg": f"Gästbil: {kwh:.0f} kWh" + (f", klar {b['until']} (billigaste timmarna)" if until else ", laddar direkt")}


def set_override(device: str, mode: str) -> None:
    with ENGINE.begin() as c:
        c.execute(text("INSERT INTO overrides (device, mode, updated_at) VALUES (:d, :m, NOW()) ON CONFLICT (device) DO UPDATE SET mode = EXCLUDED.mode, updated_at = NOW()"), {"d": device, "m": mode})


def intval(x) -> int:
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return 0


def plan_segments(car: str, soc, cap_kwh: float) -> list:
    """Planerad laddning ur smartboxens plan (ev_plan_slots): sammanhängande block med start, slut, snittkW och batterinivå före/efter (räknad från nuvarande nivå, 90 % verkningsgrad)."""
    now = dt.datetime.now(TZ).replace(tzinfo=None)
    try:
        with ENGINE.connect() as c:
            rows = c.execute(text("SELECT t_slot, kw FROM ev_plan_slots WHERE car_id = :c AND t_slot >= :n ORDER BY t_slot"), {"c": car, "n": now - dt.timedelta(minutes=15)}).fetchall()
    except Exception:
        return []
    segs, cur_soc = [], (float(soc) if soc is not None else None)
    for t, kw in rows:
        kw = float(kw)
        gain = (kw * 0.25 * 0.9 / cap_kwh * 100.0) if cap_kwh else 0.0
        if not segs or (t - segs[-1]["_end"]).total_seconds() > 120 * 60:
            segs.append({"_start": t, "_end": t + dt.timedelta(minutes=15), "kws": [kw], "soc0": None if cur_soc is None else round(cur_soc)})
        else:
            segs[-1]["_end"] = t + dt.timedelta(minutes=15); segs[-1]["kws"].append(kw)
        if cur_soc is not None:
            cur_soc = min(100.0, cur_soc + gain)
        segs[-1]["soc1"] = None if cur_soc is None else round(cur_soc)
    out = []
    for g in segs[:2]:
        day = "idag" if g["_start"].date() == now.date() else ("imorgon" if g["_start"].date() == now.date() + dt.timedelta(days=1) else g["_start"].strftime("%a"))
        out.append({"start": g["_start"].strftime("%H:%M"), "end": g["_end"].strftime("%H:%M"), "day": day, "kw": round(sum(g["kws"]) / len(g["kws"]), 1), "soc0": g["soc0"], "soc1": g["soc1"]})
    return out


def plan_blocks_ui(car: str, soc, cap_kwh: float) -> dict:
    """ALLA laddblock i planen (sammanhängande kvartsslots) för appens laddplan: dag, start, slut, kWh, snitt-kW och batterinivå före/efter,
    samt vad bilen beräknas ha kl 06:00 (golvet) - {blocks: [...], kwh, floor: {soc, ok, time}}."""
    now = dt.datetime.now(TZ).replace(tzinfo=None)
    morning = now.replace(hour=6, minute=0, second=0, microsecond=0)
    if morning <= now:
        morning += dt.timedelta(days=1)
    try:
        with ENGINE.connect() as c:
            rows = c.execute(text("SELECT t_slot, kw FROM ev_plan_slots WHERE car_id = :c AND t_slot >= :n AND kw > 0 ORDER BY t_slot"), {"c": car, "n": now - dt.timedelta(minutes=15)}).fetchall()
    except Exception:
        return {"blocks": [], "kwh": 0.0, "floor": None}
    cur = float(soc) if soc is not None else None
    blocks, at_morning = [], cur
    for t, kw in rows:
        kw = float(kw)
        gain = (kw * 0.25 * 0.9 / cap_kwh * 100.0) if cap_kwh else 0.0
        if not blocks or (t - blocks[-1]["_end"]).total_seconds() > 60:
            blocks.append({"_start": t, "_end": t, "kws": [], "soc0": None if cur is None else round(cur)})
        blocks[-1]["_end"] = t + dt.timedelta(minutes=15); blocks[-1]["kws"].append(kw)
        if cur is not None:
            cur = min(100.0, cur + gain)
        blocks[-1]["soc1"] = None if cur is None else round(cur)
        if t + dt.timedelta(minutes=15) <= morning:
            at_morning = cur
    out, total = [], 0.0
    for g in blocks:
        kwh = sum(g["kws"]) * 0.25; total += kwh
        day = "idag" if g["_start"].date() == now.date() else ("imorgon" if g["_start"].date() == now.date() + dt.timedelta(days=1) else g["_start"].strftime("%a"))
        out.append({"day": day, "start": g["_start"].strftime("%H:%M"), "end": g["_end"].strftime("%H:%M"), "kwh": round(kwh, 1), "kw": round(sum(g["kws"]) / len(g["kws"]), 1),
                    "soc0": g["soc0"], "soc1": g["soc1"], "before_morning": g["_end"] <= morning})
    summary = None
    if out:
        summary = {"day": out[0]["day"], "start": out[0]["start"], "end": out[-1]["end"], "soc0": out[0]["soc0"], "soc1": out[-1]["soc1"], "kwh": round(total, 1), "n": len(out)}
    floor = None if at_morning is None else {"soc": round(at_morning), "ok": at_morning >= 49.5, "time": "06:00", "day": "idag" if morning.date() == now.date() else "imorgon"}
    return {"blocks": out, "kwh": round(total, 1), "floor": floor, "summary": summary}


def solar_info(ov: dict) -> dict:
    return {"active": ov.get("solar_ev_active") == "on", "amps": intval(ov.get("solar_ev_amps")), "phases": intval(ov.get("solar_ev_phases")), "last_start": ov.get("solar_ev_last_start"), "last_end": ov.get("solar_ev_last_end")}


def age_h(st: dict, e: str):
    """Timmar sedan entiteten senast skrevs av Home Assistant (None om okänd). Teslan sover när den står stilla: då står siffrorna kvar långt efter att de slutat stämma."""
    s = st.get(e)
    try:
        return round((dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(s["last_updated"])).total_seconds() / 3600.0, 1)
    except Exception:
        return None


def car_facts(key: str, st: dict) -> list:
    """Validerade nyckeltal för första sidan (bara sådant som har ett giltigt, färskt värde och som är valt i installationen)."""
    c, out = CARS[key], []
    f = c["facts"]
    rng = num(st, f["range"]) if f.get("range") else None
    tp = [x for x in (num(st, e) for e in c["tpms"]) if x is not None]
    tmp = num(st, f["outside_temp"]) if f.get("outside_temp") else None
    dd = num(st, f["daily_distance"]) if f.get("daily_distance") else None
    if rng is not None: out.append(f"Räckvidd {rng:.0f} km")
    if tp: out.append(f"Däck {min(tp) * 0.0689476:.1f} bar".replace(".", ","))     # psi -> bar
    if tmp is not None: out.append(f"Ute {tmp:.0f}°")
    if dd is not None and (age_h(st, f["daily_distance"]) or 0) < 3: out.append(f"Idag {dd:.0f} km")
    return out


_CAR_MEM: dict = {}          # senast kända värden per bil: {key: {"soc": x, "home": bool, "t": datetime}}; sparas också i databasen (överlever omstart)
_CAR_MEM_MAX_H = 48
_car_mem_ready = False


def _car_mem_load() -> None:
    """Läser senast kända batterinivå/plats ur databasen en gång (tabellen skapas vid behov)."""
    global _car_mem_ready
    if _car_mem_ready:
        return
    _car_mem_ready = True
    try:
        with ENGINE.begin() as c:
            c.execute(text("CREATE TABLE IF NOT EXISTS ew_car_memory (car text PRIMARY KEY, soc real, home boolean, updated timestamptz NOT NULL DEFAULT now())"))
            for car, soc, home, t in c.execute(text("SELECT car, soc, home, updated FROM ew_car_memory")).fetchall():
                _CAR_MEM[car] = {"soc": soc, "home": home, "t": t}
    except Exception as e:
        print(f"⚠️ bilminne: {type(e).__name__}", flush=True)


def _car_mem_save(key: str, soc, home) -> None:
    """Sparar live-värdena (högst var 10:e minut, eller direkt vid ändrad plats)."""
    now = dt.datetime.now(dt.timezone.utc)
    m = _CAR_MEM.get(key)
    if m and m.get("soc") == soc and m.get("home") == home and (now - m["t"]).total_seconds() < 600:
        return
    _CAR_MEM[key] = {"soc": soc, "home": home, "t": now}
    try:
        with ENGINE.begin() as c:
            c.execute(text("INSERT INTO ew_car_memory (car, soc, home, updated) VALUES (:c, :s, :h, now()) ON CONFLICT (car) DO UPDATE SET soc = EXCLUDED.soc, home = EXCLUDED.home, updated = now()"), {"c": key, "s": soc, "h": home})
    except Exception as e:
        print(f"⚠️ bilminne (spara): {type(e).__name__}", flush=True)


def car_state(key: str, st: dict, ov: dict) -> dict:
    c = CARS[key]
    status = (val(st, c["status"]) or "unknown").lower()
    plugged = status not in ("disconnected", "offline", "unknown")
    tracker = (val(st, c["tracker"]) or "unknown").lower()
    home = tracker == "home"
    p = num(st, c["power"]) or 0.0
    power_kw = p / 1000.0 if p > 100 else p
    soc = num(st, c["soc"])
    # En sovande bil eller en HA-omstart ger "unknown": visa då senast kända värden i stället för "–" och "borta" (högst 48 h gamla).
    _car_mem_load()
    mem = _CAR_MEM.get(key)
    fresh_mem = bool(mem) and (dt.datetime.now(dt.timezone.utc) - mem["t"]).total_seconds() < _CAR_MEM_MAX_H * 3600
    soc_stale = False
    if soc is None and fresh_mem and mem.get("soc") is not None:
        soc, soc_stale = float(mem["soc"]), True
    if tracker in ("unknown", "unavailable") and fresh_mem and mem.get("home") is not None:
        home = bool(mem["home"])
    elif tracker not in ("unknown", "unavailable") and soc is not None and not soc_stale:
        _car_mem_save(key, soc, home)
    amps, phases = intval(ov.get(f"{key}_force_amps")), intval(ov.get(f"{key}_force_phases"))
    charge_now_target = intval(ov.get(f"{key}_charge_now_target")) if amps > 0 else 0       # #394
    hold = ov.get(f"{key}_hold") == "on"
    mode = ("manual" if amps > 0 else ("hold" if hold else "auto")) if (home and plugged) else ("hold" if hold else "auto")
    charging = status == "charging" or power_kw > 0.3
    eta = None
    if charging and soc is not None and power_kw > 0.5:
        hours = c["cap_kwh"] * (100 - soc) / 100.0 * 1.1 / power_kw
        eta = (dt.datetime.now(TZ) + dt.timedelta(hours=hours)).strftime("%H:%M")
    away = None
    if not home and c["arrival"]:
        a = val(st, c["arrival"])
        try:
            hz = (st.get("zone.home") or {}).get("attributes", {})
            hlat, hlon = hz.get("latitude"), hz.get("longitude")
            trk = (st.get(c["tracker"]) or {}).get("attributes", {})
            dst = (st.get(c["destination"]) or {}).get("attributes", {}) if c["destination"] else {}

            def km(la, lo):
                if None in (la, lo, hlat, hlon):
                    return None
                p1, p2 = math.radians(la), math.radians(hlat)
                dl, dg = p2 - p1, math.radians(hlon - lo)
                x = math.sin(dl / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dg / 2) ** 2
                return 6371.0 * 2 * math.asin(math.sqrt(x))
            d_dest, d_car = km(dst.get("latitude"), dst.get("longitude")), km(trk.get("latitude"), trk.get("longitude"))
            arr = dt.datetime.fromisoformat(a.replace("Z", "+00:00")) if a else None
            fresh = arr is not None and arr > dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=2) and (age_h(st, c["arrival"]) or 99) < 1.0      # en gammal ankomsttid betyder att bilen redan är framme
            arrived = arr is not None and not fresh
            away = {"arrival": arr.astimezone(TZ).strftime("%H:%M") if fresh else None, "arrived": arrived, "km": round(num(st, c["dist"]) or 0),
                    "dest_home": None if d_dest is None else d_dest < 1.5, "dest_km_from_home": None if d_dest is None else round(d_dest), "car_km_from_home": None if d_car is None else round(d_car)}
        except Exception:
            away = None
    return {"key": key, "name": c["name"], "charge_now_target": charge_now_target or None,
            "limit_note": (ov.get(f"{key}_limit_note") or None) if charging else None,     # #385
            "goal_risk": (ov.get(f"{key}_goal_risk") or None) if plugged else None,
            "soc": None if soc is None else round(soc), "soc_stale": soc_stale, "status": status, "plugged": plugged, "home": home, "charging": charging, "power_kw": round(power_kw, 1),
            "mode": mode, "amps": amps, "phases": phases, "eta": eta, "away": away, "online": (val(st, c["online"]) or "off") == "on", "default_phases": c["phases"],
            # Klimatet är igång när man kör - det är inte "förvärmning". Bara när bilen står hemma och inte är i körläge.
            "driving": driving(st, c),
            "climate_on": (val(st, c["climate"]) or "off") not in ("off", "unavailable") and home and not driving(st, c),
            "has_climate": bool(c.get("climate")), "inside": num(st, c["inside"]),
            "age_h": age_h(st, c["soc"]), "facts": car_facts(key, st), "plan": plan_segments(key, soc, c["cap_kwh"]), "plan_all": plan_blocks_ui(key, soc, c["cap_kwh"]), "plan_slots": plan_slots(key), "solar": solar_info(ov),
            "guest": _guest_of(ov, key),
            "access": ({"locked": val(st, c["lock"]) == "locked", "trunk": bool(c["trunk"]) and val(st, c["trunk"]) == "open",
                        "frunk": bool(c["frunk"]) and val(st, c["frunk"]) == "open", "has_trunk": bool(c["trunk"]), "has_frunk": bool(c["frunk"])}
                       if c["lock"] else None)}


PRICE_WINDOW_H = 24      # timmar framåt i pris- och laddplansgrafen (framtida dygnspriser finns först efter ca 13:00)

def plan_slots(car: str) -> list:
    """Planerade laddkvartar [{t, kw}] (t = epoch-ms) för laddplansgrafen, samma tidsaxel som prices().hours[].ts."""
    now = dt.datetime.now(TZ).replace(tzinfo=None)
    try:
        with ENGINE.connect() as c:
            rows = c.execute(text("SELECT t_slot, kw FROM ev_plan_slots WHERE car_id = :c AND t_slot >= :n AND kw > 0 ORDER BY t_slot"), {"c": car, "n": now - dt.timedelta(minutes=15)}).fetchall()
    except Exception:
        return []
    return [{"t": int(t.replace(tzinfo=TZ).timestamp() * 1000), "kw": round(float(kw), 1)} for t, kw in rows]

def solar_forecast_w(hours: list) -> dict:
    """Hourly PV power (epoch milliseconds -> W) from HA or the learned model.

    Use time-weighted external intervals where covered; retain the existing
    learned/weather fallback elsewhere, including when HA is unavailable.
    """
    import pickle
    import ha_solar_forecast
    external = {}
    for h in hours:
        value = ha_solar_forecast.hourly_w(h)
        if value is not None:
            external[int(h.timestamp() * 1000)] = round(value)
    try:
        with ENGINE.connect() as c:
            r = c.execute(text("SELECT solar_profile FROM system_settings WHERE id = 1")).fetchone()
            prof = pickle.loads(bytes(r[0])) if r and r[0] else {}
            if not prof or not hours:
                return external
            rows = c.execute(text("SELECT timestamp, cloud_cover FROM weather_forecast WHERE timestamp >= :a AND timestamp <= :b"), {"a": hours[0], "b": hours[-1]}).fetchall()
    except Exception:
        return external
    cloud = {t.astimezone(TZ).replace(minute=0, second=0, microsecond=0): float(cc) for t, cc in rows if cc is not None}
    out = {}
    for h in hours:
        cc, roof = cloud.get(h), prof.get((h.month, h.hour))
        if cc is not None and roof is not None:
            out[int(h.timestamp() * 1000)] = round(max(0.0, roof * (1.0 - cc / 100.0 * 0.85)))
    out.update(external)
    return out

def prices() -> dict:
    now = dt.datetime.now(TZ)
    h0 = now.replace(minute=0, second=0, microsecond=0)
    try:
        with ENGINE.connect() as c:
            rows = c.execute(text("SELECT time_start, sek_per_kwh FROM elpriser WHERE time_start >= :a AND time_start < :b ORDER BY time_start"), {"a": h0, "b": h0 + dt.timedelta(hours=PRICE_WINDOW_H)}).fetchall()
    except Exception:
        rows = []
    byh: dict = {}
    for t, p in rows:
        byh.setdefault(t.astimezone(TZ).replace(minute=0, second=0, microsecond=0), []).append(float(p))
    hours = [{"t": h.strftime("%H"), "p": round(sum(v) / len(v), 2), "now": h == h0, "ts": int(h.timestamp() * 1000)} for h, v in sorted(byh.items())]
    sun = solar_forecast_w(sorted(byh))
    for h in hours:
        if h["ts"] in sun:
            h["sun"] = sun[h["ts"]]
    cur = next((h["p"] for h in hours if h["now"]), None)
    allp = sorted(h["p"] for h in hours) or [0]
    lvl = None if cur is None else ("billigt" if cur <= allp[len(allp) // 3] else ("dyrt" if cur >= allp[2 * len(allp) // 3] else "normalt"))
    return {"now": cur, "level": lvl, "hours": hours}


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


@app.get("/api/update-status")
def api_update_status():
    """Finns en nyare EnergyWizard? (smartbox/update_check.py) - samma i appen och webben. None = inte känt än."""
    import update_check
    return {"ok": True, "status": update_check.status(block=True)}   # väntar bara när svaret är äldre än sex timmar


@app.get("/api/control-journal")
def api_control_journal(back: int = 1):
    """Höll vi planen? Per enhet för ett dygn (0 = idag, 1 = igår), smartbox/control_journal.py - samma i appen och webben."""
    import control_journal
    back = max(0, min(29, int(back)))
    with ENGINE.connect() as c:
        return {"ok": True, "back": back, "devices": control_journal.day_summary(c, back)}


@app.get("/api/flow")
def api_flow(request: Request):
    """Hemskärmens "Just nu": vad som ger och drar el, samma bild som webbens Översikt (live_flow.py). Inloggning: mellanlagret."""
    import json as _json
    import live_flow
    with ENGINE.connect() as c:
        row = c.execute(text("SELECT *, timestamp AT TIME ZONE 'Europe/Stockholm' AS sthlm_time FROM sensor_log "
                             "ORDER BY timestamp DESC LIMIT 1")).mappings().first()
    if row is None:
        return {"ok": False}
    row = dict(row)
    try:
        items = _json.loads(row.get("decision_summary") or "[]")
    except (TypeError, ValueError):
        items = []
    try:
        hc = HC.load_house_config(HOUSE_CONFIG_PATH)
    except Exception:
        hc = {}
    cars, has_spa, _heat = live_flow.house_parts(hc)
    return {"ok": True, "ts": str(row.get("sthlm_time"))[11:16], **live_flow.nodes(row, items if isinstance(items, list) else [], cars=cars, has_spa=has_spa)}


@app.get("/api/state")
def state(request: Request):
    import nordpool
    c = nordpool.cost_settings()
    currency = {"currency": c["currency"], "currency_symbol": c["symbol"]}
    try:
        st = states()
    except Exception as e:
        return {**currency, "ok": False, "role": _role(request), "error": f"Kan inte nå Home Assistant: {e}", "cars": [], "price": {}, "health": [f"Home Assistant svarar inte ({str(e)[:60]})"]}
    ov = overrides()
    health = []
    for e in WATCH:
        v = val(st, e)
        if v is None:
            health.append(("Saknas i Home Assistant: " if e not in st else "Otillgänglig: ") + e)
    return {**currency, "ok": True, "role": _role(request), "user": _session(request)[1], "ts": int(time.time()), "version": os.environ.get("APP_VERSION", "dev"), "cars": [car_state(k, st, ov) for k in CARS], "price": prices(), "health": health,
            "solar_w": first_num(st, SOLAR["pv"])}


def driving(st: dict, c: dict) -> bool:
    """Kör bilen? Växelläget (entities.shift_state: D/R/N) om bilen har det."""
    return str(val(st, c.get("shift")) or "").upper() in ("D", "R", "N", "DRIVE", "REVERSE", "NEUTRAL") if c.get("shift") else False


def car_max_a(car: str) -> int:
    """Maxström för bilens laddning: installationens charger.max_a, annars det motorn lärt sig av laddningarna
    (ev_limits.py, bara om lägre), annars 16 A."""
    c = CARS.get(car) or {}
    if c.get("max_a"):
        return max(6, int(c["max_a"]))
    try:
        import ev_limits
        learned = ev_limits.LimitLearner(ew_settings.get("learned_ev")).max_a(car)
        if learned and 6 <= int(learned) < 16:
            return int(learned)
    except Exception:
        pass
    return 16


def car_command(car: str, kind: str, body: dict | None = None) -> dict | None:
    """Laddknapparnas logik (start/max/set/stop/auto) på ett ställe: används av appens knappar OCH av Home Assistant-väljaren (input_select.<bilnamn>_laddlage), så att båda ger exakt samma överstyrning.
    Returnerar svaret, eller None om kind inte är en laddåtgärd."""
    body = body or {}
    c = CARS[car]
    st = states()
    status = (val(st, c["status"]) or "unknown").lower()
    if kind in ("start", "max", "set") and status in ("disconnected", "unknown", "offline"):
        raise HTTPException(409, "Laddkabeln är inte ansluten till laddaren")
    if kind in ("start", "max", "set"):
        top = car_max_a(car)                          # #182: bilens/laddboxens maxström, inte fasta 16 A
        amps = top if kind == "max" else max(min(6, top), min(top, intval(body.get("amps") or top)))
        phases = intval(body.get("phases")) if intval(body.get("phases")) in (1, 3) else 0
        if c.get("fixed_phases"):                      # laddboxen/bilen klarar bara 1-fas
            phases = 1
        # #394: "Ladda nu till X %" avslutas av sig själv (motorn, charge_now.py). Utan mål: tills man stoppar.
        target = intval(body.get("target_soc")) if kind == "start" else 0
        if target:
            if not 1 <= target <= 100:
                raise HTTPException(400, "Målet ska vara 1–100 %")
            soc = num(st, c["soc"]) if c.get("soc") else None
            if soc is None:                             # sovande bil: senast kända värde, som appen visar
                _car_mem_load()
                soc = (_CAR_MEM.get(car) or {}).get("soc")
            if soc is None:
                raise HTTPException(409, "Bilens laddnivå är okänd – välj Tills jag stoppar")
            if soc >= target:
                raise HTTPException(409, f"Bilen har redan {round(soc)} %")
        set_override(f"{car}_hold", "off")
        set_override(f"{car}_force_amps", str(amps))
        set_override(f"{car}_force_phases", str(phases))
        set_override(f"{car}_charge_now_target", str(target) if target else "")
        set_override(f"{car}_charge_now_until", str(int(time.time() + 24 * 3600)) if target else "")
        drv = CHARGER_DRV.get(car)
        ok = drv.set_limit_a(amps) if drv else False
        if drv and status in ("awaiting_start", "paused", "off", "ready_to_charge", "completed"):
            drv.turn_on()
        until = f" till {target} %, sedan tar planen över" if target else ""
        return {"ok": bool(ok), "msg": (f"Startar laddning, {amps} A" + (f" ({phases}-fas)" if phases else "") + until + " – det kan ta en halv minut innan bilen börjar") if ok else "Laddaren svarade inte – försök igen"}
    if kind in ("stop", "auto"):
        set_override(f"{car}_charge_now_target", "")
        set_override(f"{car}_charge_now_until", "")
    if kind == "stop":
        set_override(f"{car}_force_amps", "0")
        set_override(f"{car}_force_phases", "0")
        set_override(f"{car}_hold", "on")
        drv = CHARGER_DRV.get(car)
        if drv:
            drv.set_limit_a(0)
            drv.turn_off()
        return {"ok": True, "msg": "Laddning stoppad (håller tills du väljer Auto)"}
    if kind == "auto":
        set_override(f"{car}_hold", "off")
        set_override(f"{car}_force_amps", "0")
        set_override(f"{car}_force_phases", "0")
        set_override("force_ev_recalc", "true")
        return {"ok": True, "msg": "Auto – AI:n styr igen"}
    return None


def battery_control_mode() -> str:
    """Hur batteriet används enligt installationen: styr / samarbete / av (#396)."""
    try:
        return HC.battery_settings(HC.load_house_config(HOUSE_CONFIG_PATH))["control"]
    except Exception:
        return "av"


@app.post("/api/battery/topup")
async def battery_topup(request: Request):
    """#396: "Toppa husbatteriet nu till X %" (0 = avbryt). Motorn laddar inom säkringen tills målet eller 6 h."""
    if _role(request) in (None, "guest"):
        raise HTTPException(403, "Inte tillåtet")
    body = await request.json()
    target = intval(body.get("target"))
    if target and not 10 <= target <= 100:
        raise HTTPException(400, "Målet ska vara 10–100 %")
    if target and battery_control_mode() != "styr":
        raise HTTPException(409, "EnergyWizard styr inte batteriet - välj Styr under batteriet i installationen")
    logact(request, f"Batteri: toppa till {target} %" if target else "Batteri: avbryt toppning")
    set_override("battery_topup_target", str(target) if target else "")
    set_override("battery_topup_until", str(int(time.time() + 6 * 3600)) if target else "")
    return {"ok": True, "msg": f"Toppar batteriet till {target} % - startar inom en minut" if target else "Toppningen avbruten - planen tar över"}


@app.post("/api/car/{car}/action")
async def action(car: str, request: Request):
    if car in CARS:
        _b = await request.json()
        logact(request, f"{CARS[car]['name']}: {_b.get('kind')}" + (f" {_b.get('amps')} A" if _b.get("amps") else ""))
    if car not in CARS:
        raise HTTPException(404, "Okänd bil")
    body = await request.json()
    kind = body.get("kind")
    c = CARS[car]
    st = states()
    status = (val(st, c["status"]) or "unknown").lower()
    r = car_command(car, kind, body)
    if r is not None:
        return r
    if kind in ("heat_on", "heat_off"):
        on = kind == "heat_on"
        if not c["climate"]:
            raise HTTPException(409, "Ingen värme vald för bilen - välj bilens klimatentitet i installationen")
        ok = H.set_car_climate(c["climate"], "heat_cool" if on else "off", 21.0 if on else None)
        set_override(f"{car}_climate", "21.0" if on else "off")   # smartbox/car_climate_watch.py följer upp tills bilen värmer
        _cache["t"] = 0.0
        if not ok:
            raise HTTPException(502, "Bilen svarade inte på klimatkommandot")
        return {"ok": True, "msg": ("Värmekommando skickat (21 °C). EnergyWizard kollar att bilen startar värmen, och värmer igen om kupén svalnat "
                                    "10 min efter att den gått av (i en timme, så länge bilen är hemma)."
                                    if on else "Stoppkommando skickat")}
    raise HTTPException(400, "Okänd åtgärd")


_unlock_fails: dict = {}


def _secure_ok(request: Request) -> bool:
    v = request.cookies.get("ew2", "")
    try:
        exp, sig = v.split(".", 1)
        return int(exp) > time.time() and hmac.compare_digest(sig, hmac.new(SECRET, ("sec" + exp).encode(), hashlib.sha256).hexdigest())
    except Exception:
        return False


@app.post("/api/secure")
async def secure(request: Request):
    """Lås upp och öppna luckor kräver lösenordet igen (10 minuters fönster): den som bara har telefonen upplåst kommer inte åt bilen."""
    ip = client_ip(request)
    if _unlock_fails.get(ip, (0, 0))[0] >= 5 and time.time() - _unlock_fails[ip][1] < 900:
        raise HTTPException(429, "För många försök – vänta en stund")
    body = await request.json()
    expected = _user_password(_session(request)[1] or "")
    if not expected or not hmac.compare_digest(str(body.get("password", "")), expected):
        _unlock_fails[ip] = (_unlock_fails.get(ip, (0, 0))[0] + 1, time.time())
        raise HTTPException(401, "Fel lösenord")
    _unlock_fails.pop(ip, None)
    exp = int(time.time()) + 600
    r = JSONResponse({"ok": True, "until": exp})
    r.set_cookie("ew2", f"{exp}." + hmac.new(SECRET, ("sec" + str(exp)).encode(), hashlib.sha256).hexdigest(), max_age=600, httponly=True, secure=True, samesite="lax", path="/")
    return r


def _ha_call(domain: str, service: str, entity: str):
    r = requests.post(f"{H._BASE}/services/{domain}/{service}", headers=H._HEADERS, json={"entity_id": entity}, timeout=25, verify=False)
    r.raise_for_status()


@app.post("/api/car/{car}/access")
async def car_access(car: str, request: Request):
    """Bilens lås och luckor (om de är valda i installationen). what: lock | unlock | trunk | frunk.
    Allt utom 'lock' kräver /api/secure (lösenord) de senaste 10 minuterna. Alla anrop loggas."""
    if car not in CARS:
        raise HTTPException(404, "Okänd bil")
    c = CARS[car]
    body = await request.json()
    what = body.get("what")
    if what not in ("lock", "unlock", "trunk", "frunk"):
        raise HTTPException(400, "Okänd åtgärd")
    ent = c["lock"] if what in ("lock", "unlock") else c[what]
    if not ent:
        raise HTTPException(409, "Den här bilen har ingen sådan entitet vald i installationen")
    if what != "lock" and not _secure_ok(request):
        raise HTTPException(403, "secure")                     # appen ber om lösenord och försöker igen
    st = states()
    try:
        if what in ("lock", "unlock"):
            _ha_call("lock", what, ent); msg = "Bilen låst" if what == "lock" else "Bilen upplåst"
        else:
            is_open = val(st, ent) == "open"
            _ha_call("cover", "close_cover" if is_open else "open_cover", ent)
            msg = ("Baklucka" if what == "trunk" else "Framlucka") + (" stängs" if is_open else " öppnas")
    except Exception as e:
        print(f"🔐 {c['name']} {what} MISSLYCKADES: {e}", flush=True)
        raise HTTPException(502, "Bilen svarade inte (den kan sova – försök igen om en stund)")
    print(f"🔐 {c['name']} {what} OK ({request.headers.get('x-forwarded-for', '?').split(',')[0]})", flush=True)
    logact(request, f"{c['name']}: {msg}")
    _cache["t"] = 0.0
    return {"ok": True, "msg": msg}


# -- Hus: värme, varmvatten, spabad, effekt ----------------------------------------------------------------
SETTING_RULES = {  # kolumn: (typ, min, max, steg)
    "peak_shaving_enabled": ("bool",), "power_limit_kw": ("float", 3.0, 25.0, 0.5), "fuse_size_a": ("float", 16.0, 63.0, 1.0),
    "temp_cheap": ("float", 17.0, 25.0, 0.5), "temp_expensive": ("float", 15.0, 24.0, 0.5), "spa_normal_temp": ("float", 20.0, 40.0, 0.5), "spa_max_temp": ("float", 30.0, 40.0, 0.5), "spa_low_temp": ("float", 10.0, 30.0, 0.5),
    "notify_spa_ready": ("bool",), "notify_ev_start": ("bool",), "notify_washer_start": ("bool",), "notify_spa_open": ("bool",),
}


def get_settings_row() -> dict:
    with ENGINE.connect() as c:
        row = c.execute(text("SELECT " + ", ".join(SETTING_RULES) + ", spa_force_heat, spa_schedule_enabled, spa_target_datetime, spa_target_temp FROM system_settings WHERE id = 1")).mappings().first()
    return dict(row) if row else {}


def net_now():
    """Nettoeffekt mot elnätet i W: plus = köper, minus = säljer (senaste raden i smartboxens logg)."""
    try:
        with ENGINE.connect() as c:
            r = c.execute(text("SELECT net_power FROM sensor_log WHERE net_power IS NOT NULL AND timestamp > NOW() - INTERVAL '10 minutes' ORDER BY timestamp DESC LIMIT 1")).first()
        return None if r is None else float(r[0])
    except Exception:
        return None


def _spa_bath_listing():
    try:
        import spa_bath
        return spa_bath.listing(ew_settings.get("spa_bath_windows") if ew_settings else None)
    except Exception:
        return []


@app.post("/api/spa_bath")
def spa_bath_set(request: Request, body: dict):
    """Badtider för spabadet (smartbox/spa_bath.py, samma som webben). Bara ägaren."""
    if _role(request) != "owner":
        raise HTTPException(403, "Bara ägaren kan ändra badtiderna")
    import spa_bath
    try:
        saved = spa_bath.clean(body.get("windows"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    ew_settings.update(spa_bath_windows=saved)
    return {"ok": True, "msg": spa_bath.summary(saved)}


@app.get("/api/home")
def home():
    st = states()
    ov = overrides()
    cfg = get_settings_row()
    return {"ok": True,
            "heat": {"inside": num(st, "sensor.smartbox_inomhustemp"), "target": num(st, "sensor.smartbox_maltemperatur"), "outside": num(st, "sensor.smartbox_utetemperatur"), "mode": ov.get("heat", "auto"),
                     "pump_w": num(st, "sensor.smartbox_effekt_varmepump"), "price_mode": val(st, "sensor.smartbox_lage"), "cop": num(st, "sensor.smartbox_cop"), "temp_cheap": cfg.get("temp_cheap"), "temp_expensive": cfg.get("temp_expensive")},
            "water": {"temp": num(st, "sensor.smartbox_varmvatten"), "mode": ov.get("hotwater", "auto"),
                      "until": intval(ov.get("hotwater_until")) or None if ov.get("hotwater") == "on" else None},
            "spa": {"bath_windows": _spa_bath_listing(), "temp": spa_temps(st)[0], "target": spa_temps(st)[1], "heater": spa_temps(st)[2],
                    "force_heat": bool(cfg.get("spa_force_heat")), "eco": ov.get("spa_force_eco") == "on",
                    "ready_at": (cfg["spa_target_datetime"].astimezone(TZ).strftime("%a %H:%M") if cfg.get("spa_schedule_enabled") and cfg.get("spa_target_datetime") else None), "ready_temp": cfg.get("spa_target_temp") if cfg.get("spa_schedule_enabled") else None, "power_w": num(st, "sensor.smartbox_effekt_spa"), "error": val(st, SPA_E["error"]) if SPA_E.get("error") else None},
            "power": {"total_w": num(st, "sensor.smartbox_effekt_total"), "ev_w": num(st, "sensor.smartbox_effekt_elbil"), "limit_kw": cfg.get("power_limit_kw"), "peak": bool(cfg.get("peak_shaving_enabled")),
                      "solar_w": first_num(st, SOLAR["pv"]), "solar_forecast_w": num(st, "sensor.smartbox_solprognos"), "saving_today": num(st, "sensor.smartbox_besparing_idag"),
                      "net_w": net_now(), "solar_limit_pct": num(st, SOLAR["limit"]) if SOLAR["limit"] else None, "price_now": prices().get("now")}}


@app.post("/api/home/{what}")
async def home_action(what: str, request: Request):
    body = await request.json()
    v = body.get("value")
    logact(request, f"Hus: {what} → {v}")
    if what in ("heat", "hotwater"):
        if v not in ("auto", "on", "off"):
            raise HTTPException(400, "Ogiltigt läge")
        set_override(what, v)
        # #397: varmvatten "Till" med tid - motorn går tillbaka till Auto när tiden gått ut (timed_override.py)
        mins = timed_override.minutes(body.get("minutes")) if what == "hotwater" and v == "on" else None
        if what == "hotwater":
            set_override("hotwater_until", str(int(time.time() + mins * 60)) if mins else "")
        dur = "" if not mins else (f" i {mins // 60} h" if mins % 60 == 0 else f" i {mins} min")
        return {"ok": True, "msg": {"auto": "Auto", "on": "Tvingar PÅ", "off": "Tvingar FRÅN"}[v] + (" – värme" if what == "heat" else " – varmvatten") + dur}
    if what == "spa_heat":
        with ENGINE.begin() as c:
            c.execute(text("UPDATE system_settings SET spa_force_heat = :v WHERE id = 1"), {"v": bool(v)})
        return {"ok": True, "msg": "Spabad: värmer nu" if v else "Spabad: tvångsvärme av"}
    if what == "spa_auto":                                   # Auto = följer sitt eget schema (HA/smartboxen styr): inget tvång, ingen Eco-överstyrning
        with ENGINE.begin() as c:
            c.execute(text("UPDATE system_settings SET spa_force_heat = FALSE WHERE id = 1"))
        set_override("spa_force_eco", "auto")
        return {"ok": True, "msg": "Spabad: Auto – följer sitt schema"}
    if what == "spa_eco":
        set_override("spa_force_eco", "on" if v else "auto")
        return {"ok": True, "msg": "Spabad: Eco på" if v else "Spabad: Eco av"}
    raise HTTPException(404, "Okänd åtgärd")


# nordpool_vat_enabled lagras ALDRIG i system_settings - sanningen finns bara på ett ställe
# (HA:s egen nordpool-integration), annars riskerar vårt UI visa ett inaktuellt värde.
SETTING_RULES_HA_BACKED = {"nordpool_vat_enabled": ("bool",)}


@app.get("/api/settings")
def get_settings():
    cfg = get_settings_row()
    values = {k: cfg.get(k) for k in SETTING_RULES}
    # Nuvarande VAT-läge går inte att läsa tillbaka från HA på något sätt (varken config
    # entry eller sensorattribut avslöjar det) - alltid None/"okänt" i gränssnittet,
    # aldrig en gissning. Se homeassistant.get_nordpool_config().
    values["nordpool_vat_enabled"] = None
    return {"values": values, "rules": {k: list(v) for k, v in {**SETTING_RULES, **SETTING_RULES_HA_BACKED}.items()}}


@app.post("/api/settings")
async def set_setting(request: Request):
    body = await request.json()
    key, v = body.get("key"), body.get("value")
    if key == "nordpool_vat_enabled":
        v = bool(v)
        if not H.set_nordpool_vat(v):
            raise HTTPException(502, "Kunde inte ändra momsinställningen i Home Assistant - "
                                      "nordpool-integrationen kan behöva läggas till manuellt igen")
        print(f"⚙️ ewapp: nordpool_vat_enabled = {v} (via HA:s nordpool-integration)", flush=True)
        logact(request, f"Inställning: moms (Nord Pool) = {v}")
        return {"ok": True, "value": v, "msg": f"Moms {'på' if v else 'av'} i Nord Pool-priserna"}
    rule = SETTING_RULES.get(key)
    if not rule:
        raise HTTPException(400, "Okänd inställning")
    if rule[0] == "bool":
        v = bool(v)
    else:
        try:
            v = float(v)
        except (TypeError, ValueError):
            raise HTTPException(400, "Ogiltigt värde")
        if not (rule[1] <= v <= rule[2]):
            raise HTTPException(400, f"Måste vara mellan {rule[1]} och {rule[2]}")
    if key == "power_limit_kw" and not get_settings_row().get("peak_shaving_enabled"):
        raise HTTPException(409, "Effektgränsen gäller bara när effektvakten är på")
    with ENGINE.begin() as c:
        c.execute(text(f"UPDATE system_settings SET {key} = :v WHERE id = 1"), {"v": v})
    print(f"⚙️ ewapp: {key} = {v}", flush=True)
    logact(request, f"Inställning: {key} = {v}")
    return {"ok": True, "value": v}


# -- Laddschema ----------------------------------------------------------------------------------------------------------
@app.get("/api/schedule")
def get_schedule():
    out = {k: {d: {"enabled": False, "time": "07:00", "soc": 100} for d in range(7)} for k in CARS}
    with ENGINE.connect() as c:
        for car, day, t, soc, en in c.execute(text("SELECT car_id, day_of_week, target_time, target_soc, enabled FROM ev_charging_schedule")):
            if car in out and 0 <= day <= 6:
                out[car][day] = {"enabled": bool(en), "time": t.strftime("%H:%M"), "soc": int(soc)}
    return out


def save_schedule_row(car: str, day: int, t: str, enabled: bool, soc: int) -> None:
    """Ett laddschema (klar kl T, mål soc %, per veckodag och bil): används av appens schema OCH av Home Assistant (Familjetavlan) så att båda slår igenom i smartboxen."""
    with ENGINE.begin() as c:
        c.execute(text("""INSERT INTO ev_charging_schedule (car_id, day_of_week, target_time, enabled, target_soc, panic_mode) VALUES (:c, :d, :t, :e, :s, FALSE)
                          ON CONFLICT (car_id, day_of_week) DO UPDATE SET target_time = EXCLUDED.target_time, enabled = EXCLUDED.enabled, target_soc = EXCLUDED.target_soc"""),
                  {"c": car, "d": day, "t": t, "e": bool(enabled), "s": max(20, min(100, int(soc)))})
    set_override("force_ev_recalc", "true")                    # smartbox räknar om laddplanen direkt


@app.post("/api/schedule")
async def set_schedule(request: Request):
    b = await request.json()
    car = b.get("car")
    days = b.get("days") if isinstance(b.get("days"), list) else [b.get("day")]     # "days": flera dagar på en gång (#142)
    days = [intval(d) for d in days]
    if car not in CARS or not days or not all(0 <= d <= 6 for d in days):
        raise HTTPException(400, "Ogiltigt")
    t = str(b.get("time", "07:00"))
    try:
        dt.datetime.strptime(t, "%H:%M")
    except ValueError:
        raise HTTPException(400, "Ogiltig tid")
    soc = max(20, min(100, intval(b.get("soc") or 100)))
    for day in days:
        save_schedule_row(car, day, t, bool(b.get("enabled")), soc)
    logact(request, f"Schema {car} dag {','.join(str(d) for d in days)}: {'på' if b.get('enabled') else 'av'} {t} {soc} %")
    return {"ok": True}


@app.get("/api/schedule/climate")
def get_climate_schedule():
    """Kupévärme till ett klockslag (#233). Samma climate_schedule som motorn läser."""
    import settings
    import car_climate_schedule as cc
    saved = settings.get_climate_schedule(list(CARS))
    return {cid: cc.view(saved.get(cid), bool(spec.get("climate"))) for cid, spec in CARS.items()}


@app.post("/api/schedule/climate")
async def set_climate_schedule(request: Request):
    import settings
    import car_climate_schedule as cc
    b = await request.json()
    car = b.get("car")
    if car not in CARS:
        raise HTTPException(400, "Ogiltig bil")
    if not CARS[car].get("climate"):
        raise HTTPException(409, "Ingen värme vald för bilen - välj bilens klimatentitet i installationen")
    try:
        row = cc.normalize(b.get("enabled"), b.get("time"), b.get("temp"))
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    if not settings.save_climate_schedule_db(car, row["enabled"], row["time"], row["temp"]):
        raise HTTPException(502, "Kunde inte spara värmeschemat")
    logact(request, f"Kupévärme {car}: {'på' if row['enabled'] else 'av'} {row['time']} {row['temp']} °C")
    return {"ok": True, **row}


# -- Grafer ----------------------------------------------------------------------------------------------------------------
@app.get("/api/energyhistory")
def energyhistory(range: str = "24h"):
    """Historik-fliken: energisummor + effekt över tid (smartbox/energy_history.py, samma som webben)."""
    import energy_history
    with ENGINE.connect() as c:
        return energy_history.history_payload(c, range)


@app.get("/api/savings")
def savings_api(request: Request):
    """Hem-fliken: besparing Idag/7 dagar/Månad (smartbox/savings.py, samma formel som webben).
    Bara för ägaren - familj och gäster ser inga kronor."""
    if _role(request) != "owner":
        return {"ok": False, "hidden": True}
    import savings
    today = dt.datetime.now(TZ).date().isoformat()
    with ENGINE.connect() as c:
        rows = savings.daily_rows(c, days=40)
        battery = None
        try:                                       # #398: mot batteriet i självförbrukningsläge (bara med husbatteri)
            bcfg = HC.battery_settings(HC.load_house_config(HOUSE_CONFIG_PATH))
            if bcfg.get("control") != "av":
                import battery_baseline
                battery = battery_baseline.periods(c, bcfg, dt.datetime.now(TZ).date(), TZ)
        except Exception as e:
            print(f"⚠️ Jämförelse mot självförbrukning: {e}")
            c.rollback()
    return {"ok": True, "today": today, "periods": savings.summarize_periods(rows, today), "battery_vs_selfuse": battery}


@app.get("/api/plan")
def plan_api():
    """Hem- och Plan-fliken: planen framåt i klartext (smartbox/plan_brief.py, samma som webben)."""
    import nordpool
    import plan_brief
    now = dt.datetime.now(TZ)
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
        ch = c.execute(text("SELECT cheap_hours_count FROM system_settings WHERE id = 1")).fetchone()
        mode_row = c.execute(text("SELECT active_mode FROM sensor_log WHERE active_mode IS NOT NULL ORDER BY timestamp DESC LIMIT 1")).fetchone()
        try:
            import solar_days
            sun = solar_days.load(c, now)
        except Exception:
            sun = None
    brief = plan_brief.build_brief(now, [(r[0], float(r[1])) for r in prices if r[1] is not None],
                                   [tuple(r) for r in ev_rows], nordpool.calculate_day_strategy,
                                   int(ch[0]) if ch and ch[0] else 8, mode_row[0] if mode_row else None, battery_rows=[tuple(r) for r in bat_rows],
                                   currency=nordpool.cost_settings()["currency"], symbol=nordpool.cost_settings()["symbol"])
    return {"ok": True, **brief, "solar_days": sun}


@app.get("/api/journal")
def journal_api(request: Request, hours: float = 6, lvl: str = "", q: str = ""):
    """Installationens logg (smartbox/ew_journal.py) - bara ägaren."""
    if _role(request) != "owner":
        raise HTTPException(403, "Bara ägaren kan läsa loggen")
    import ew_journal
    with ENGINE.connect() as c:
        return {"ok": True, "rows": ew_journal.read(c, since_h=max(0.1, min(hours, 336)), lvl=lvl or None, q=q.strip() or None, limit=300)}


@app.get("/api/journal/download")
def journal_download(request: Request, days: float = 2):
    if _role(request) != "owner":
        raise HTTPException(403, "Bara ägaren kan läsa loggen")
    import ew_journal
    with ENGINE.connect() as c:
        body = ew_journal.export_text(c, days)
    return Response(content=body, media_type="text/plain; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename=energywizard-logg-{dt.datetime.now(TZ).strftime('%Y%m%d-%H%M')}.txt"})


@app.get("/api/notify-prefs")
def notify_prefs_get():
    import notify_prefs
    return {"ok": True, "categories": notify_prefs.listing()}


@app.post("/api/notify-prefs")
async def notify_prefs_set(request: Request):
    if _role(request) != "owner":
        raise HTTPException(403, "Bara ägaren kan ändra notiserna")
    import notify_prefs
    on = (await request.json()).get("on") or {}
    off = [k for k in notify_prefs.KEYS if on.get(k) is False or (k not in on and k in notify_prefs.disabled())]
    notify_prefs.set_disabled(off)
    return {"ok": True, "categories": notify_prefs.listing()}


@app.get("/api/planclock")
def planclock_api():
    """Den dragbara planklockan: en rad per kvart 24 h framåt (smartbox/plan_clock.py, samma som webben)."""
    import plan_clock
    with ENGINE.connect() as c:
        return plan_clock.load(c, cars=[{"id": k, "name": v["name"]} for k, v in CARS.items()])


@app.get("/planclock.js")
def planclock_js():
    import plan_clock
    return FileResponse(os.path.join(os.path.dirname(plan_clock.__file__), "static", "planclock.js"),
                        media_type="application/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/journal.js")
def journal_js():
    import plan_clock
    return FileResponse(os.path.join(os.path.dirname(plan_clock.__file__), "static", "journal.js"),
                        media_type="application/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/liveflow.js")
def liveflow_js():
    import plan_clock
    return FileResponse(os.path.join(os.path.dirname(plan_clock.__file__), "static", "liveflow.js"),
                        media_type="application/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/planskyline.js")
def planskyline_js():
    import plan_clock
    return FileResponse(os.path.join(os.path.dirname(plan_clock.__file__), "static", "planskyline.js"),
                        media_type="application/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/api/timeline")
def timeline_api():
    """Historik → Elpris: uppmätt 24 h bakåt och elpriserna framåt så långt leverantören har publicerat."""
    import live_flow
    import timeline
    try:
        cars, has_spa, has_heat = live_flow.house_parts(HC.load_house_config(HOUSE_CONFIG_PATH))
    except Exception:
        cars, has_spa, has_heat = None, None, None
    with ENGINE.connect() as c:
        return timeline.load(c, cars=cars, has_spa=has_spa, has_heat=has_heat)


@app.get("/api/history")
def history(hours: int = 24):
    hours = max(6, min(hours, 72))
    with ENGINE.connect() as c:
        rows = c.execute(text("""SELECT date_trunc('hour', timestamp) h, avg(house_consumption_w), avg(indoor_temp), avg(outdoor_temp), avg(price), avg(ev_power_kw + COALESCE(ev_carport_power_kw, 0)), avg(pv_power_w), avg(avg_w_tot), avg(spa_power_w), avg(power_oven_w), avg(power_computer_w)
                                 FROM sensor_log WHERE timestamp >= NOW() - make_interval(hours => :n) GROUP BY 1 ORDER BY 1"""), {"n": hours}).fetchall()
    f = lambda x, d=1: None if x is None else round(float(x), d)
    kw = lambda x: f(float(x or 0) / 1000.0, 2)
    return {"t": [r[0].astimezone(TZ).strftime("%H") for r in rows], "total_kw": [kw(r[1]) for r in rows], "indoor": [f(r[2]) for r in rows], "outdoor": [f(r[3]) for r in rows],
            "price": [f(r[4], 2) for r in rows], "ev_kw": [f(r[5], 2) for r in rows], "solar_kw": [kw(r[6]) for r in rows], "pump_kw": [kw(r[7]) for r in rows], "spa_kw": [kw(r[8]) for r in rows],
            "oven_kw": [kw(r[9]) for r in rows], "computer_kw": [kw(r[10]) for r in rows]}


GROUPS = [("Batteri & laddning", ("battery", "charg", "energy", "soc", "state_of_charge", "plugged", "range", "charge_time", "scheduled_charging", "charge_limit", "charge_port")), ("Klimat & temperatur", ("climate", "temperature", "heated", "overheat", "hvac")),
          ("Plats", ("location", "tracker", "arrival", "destination", "distance_to")), ("Lås & luckor", ("lock", "frunk", "trunk", "door", "window", "valet", "sentry", "charger_door")),
          ("Körning & däck", ("odometer", "tpms", "shift", "parking", "speed", "trip", "efficiency", "user_present", "daily", "monthly")), ("System", ("update", "polling", "asleep", "online", "last_", "data_last"))]
_DEV_ENTS: dict = {}


def _car_device_entities(car: str) -> list:
    """Alla entiteter på bilens enhet i Home Assistant (samma enhet som bilens batterisensor) - inga namnprefix."""
    hit = _DEV_ENTS.get(car)
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    soc = CARS[car]["soc"] or CARS[car]["climate"]
    ents = []
    if soc:
        try:
            r = requests.post(f"{H._BASE}/template", headers=H._HEADERS, verify=False, timeout=8,
                              json={"template": "{{ device_entities(device_id('%s')) | tojson }}" % soc})
            r.raise_for_status()
            ents = json.loads(r.text)
        except Exception as e:
            print(f"⚠️ Bilens entiteter ({car}): {e}", flush=True)
    _DEV_ENTS[car] = (time.time(), ents)
    return ents


def _group(eid: str) -> str:
    n = eid.split(".", 1)[1]
    for g, keys in GROUPS:
        if any(k in n for k in keys):
            return g
    return "Övrigt"


@app.get("/api/car/{car}/entities")
def car_entities(car: str):
    """Alla Home Assistant-entiteter för en bil, grupperade, med validering (giltigt värde + färskhet). Visas bara på begäran (Alla data); nyckeltal på första sidan kommer ur de validerade."""
    if car not in CARS:
        raise HTTPException(404, "Okänd bil")
    st = states()
    now = dt.datetime.now(dt.timezone.utc)
    rows = []
    dev_ents = set(_car_device_entities(car))
    for eid, s_ in st.items():
        dom, name = eid.split(".", 1)
        if dom not in ("sensor", "binary_sensor", "switch", "button", "lock", "cover", "climate", "number", "select", "device_tracker", "update") or eid not in dev_ents:
            continue
        try:
            age = (now - dt.datetime.fromisoformat(s_["last_updated"].replace("Z", "+00:00"))).total_seconds() / 3600
        except Exception:
            age = None
        state = s_["state"]
        valid = state not in ("unavailable",) and not (state == "unknown" and dom not in ("button", "update"))
        stale = dom == "sensor" and age is not None and age > 24
        rows.append({"id": eid, "name": (s_["attributes"].get("friendly_name") or eid), "state": state if len(state) < 40 else state[:38] + "…", "unit": s_["attributes"].get("unit_of_measurement") or "", "valid": bool(valid and not stale),
                     "why": "otillgänglig" if state == "unavailable" else ("inte uppdaterad på " + str(round(age)) + " h" if stale else ("okänt värde" if not valid else "")), "group": _group(eid), "age_h": None if age is None else round(age, 1)})
    rows.sort(key=lambda r: (r["group"], r["name"]))
    return {"car": car, "rows": rows, "valid": sum(1 for r in rows if r["valid"]), "total": len(rows), "buttons": list(CARS[car]["buttons"])}


@app.post("/api/car/{car}/press")
async def car_press(car: str, request: Request):
    """Bilens knappar (blinka, tuta, väck, uppdatera data, start laddning i bilen). Fjärrstart/övrigt kräver inte lösenord; lås/luckor har egen spärr."""
    if car not in CARS:
        raise HTTPException(404, "Okänd bil")
    which = (await request.json()).get("button")
    ent = CARS[car]["buttons"].get(which)
    if not ent:
        raise HTTPException(400, "Okänd knapp")
    try:
        _ha_call("button", "press", ent)
    except Exception as e:
        raise HTTPException(502, "Bilen svarade inte (den kan sova – försök igen om en stund)")
    print(f"🔘 {car} {which}", flush=True)
    return {"ok": True, "msg": {"flash": "Blinkar", "horn": "Tutar", "wake": "Väcker bilen", "refresh": "Uppdaterar bilens data", "start_charge": "Startar laddning i bilen"}[which]}


def _version() -> str:
    h = hashlib.sha256()
    for f in ("static/app.js", "static/i18n.js", "static/style.css", "static/index.html"):
        try:
            h.update(open(f, "rb").read())
        except OSError:
            pass
    return h.hexdigest()[:10]


VERSION = _version()


@app.get("/api/version")
def version():
    return {"v": VERSION}


# -- Energi: sol, nät, exportbegränsning, effekttoppar ------------------------------------------------------------------------
SE_STATUS = {"I_STATUS_OFF": "Avstängd", "I_STATUS_SLEEPING": "Vilar (natt)", "I_STATUS_WAKEUP": "Startar", "I_STATUS_MPPT": "Producerar", "I_STATUS_THROTTLED": "Begränsad", "I_STATUS_SHUTTING_DOWN": "Stänger av", "I_STATUS_FAULT": "Fel", "I_STATUS_STANDBY": "Standby"}


def month_peaks() -> list:
    """De tre högsta timmedelvärdena av husets effekt den här månaden (kW, tid)."""
    try:
        with ENGINE.connect() as c:
            rows = c.execute(text("""SELECT h, p FROM (SELECT date_trunc('hour', timestamp) h, avg(avg_w_tot) p FROM sensor_log WHERE timestamp >= date_trunc('month', NOW()) GROUP BY 1) t ORDER BY p DESC LIMIT 3""")).fetchall()
        return [{"kw": round(float(p) / 1000.0, 1), "t": h.astimezone(TZ).strftime("%d/%m %H:%M")} for h, p in rows]
    except Exception:
        return []


def insights(st: dict, ov: dict, pr: dict) -> list:
    """Det som är intressant just nu, på vanlig svenska: elpris och billigaste fönstret, vad AI:n faktiskt gör, planerad laddning, sol och besparing. Rader som bara säger att något är avstängt tas inte med."""
    out = []
    import nordpool
    symbol = nordpool.cost_settings()["symbol"]
    hrs = pr.get("hours") or []
    if pr.get("now") is not None:
        t = f"Elpriset är {pr['now']:.2f} {symbol}/kWh ({pr.get('level') or '–'})."
        fut = [h for h in hrs if not h["now"]]
        if fut and len(hrs) >= 4:
            m = min(fut, key=lambda h: h["p"])
            i = fut.index(m)
            j = i
            while j + 1 < len(fut) and fut[j + 1]["p"] <= m["p"] + 0.08:
                j += 1
            t += f" Billigast {m['t']}–{(int(fut[j]['t']) + 1) % 24:02d} ({m['p']:.2f} {symbol})." if m["p"] < pr["now"] else " Det blir inte billigare de närmaste timmarna."
        out.append({"i": "⚡", "t": t})
    log = val(st, "sensor.smartbox_beslut") or ""
    try:
        with ENGINE.connect() as c:
            log = c.execute(text("SELECT ai_action_log FROM sensor_log WHERE ai_action_log IS NOT NULL ORDER BY timestamp DESC LIMIT 1")).scalar() or log
    except Exception:
        pass
    ai = []
    for blk in str(log).split("\n\n"):
        b = blk.strip()
        if not b or any(k in b for k in ("inaktiverat av", "Normaldrift", "Skyddar ej")):
            continue
        b = re.sub(r"^\S+\s*Prio [\d.]+ \([^)]*\):\s*", "", b)
        b = re.sub(r"^\S+\s*Grundläge:\s*", "", b)
        ai.append(b[:110])
    for b in ai[:2]:
        out.append({"i": "🤖", "t": b})
    for key in CARS:
        c = CARS[key]
        seg = plan_segments(key, num(st, c["soc"]), c["cap_kwh"])
        if seg:
            g = seg[0]
            out.append({"i": "🔌", "t": f"{c['name'].split()[0]} laddas {g['day']} {g['start']}–{g['end']}" + (f" ({g['soc0']}→{g['soc1']} %)" if g.get("soc0") is not None else "") + "."})
            break
    sol = num(st, "sensor.smartbox_solprognos")
    today = first_num(st, SOLAR["today"])
    ev_sun = num(st, "sensor.smartbox_elbil_solel")
    if today is not None or sol is not None:
        t = (f"Solen har gett {today:.0f} kWh idag" if today is not None else "Sol") + (f", prognos nu {sol / 1000:.1f} kW" if sol is not None else "")
        if ev_sun:
            t += f". Elbilarna har laddats {ev_sun:.0f} kWh på solel"
        out.append({"i": "☀️", "t": t + "."})
    sv = num(st, "sensor.smartbox_besparing_idag")
    if sv is not None and sv > 0.5:
        out.append({"i": "💰", "t": f"EnergyWizard har sparat {sv:.1f} {symbol} idag jämfört med ett vanligt hushåll utan styrning (inkl. moms)."})
    return out[:5]


def safe_insights(st, ov, pr):
    try:
        return insights(st, ov, pr)
    except Exception as e:                                   # ett fel i de dagliga tipsen får aldrig fälla hela energisidan
        print(f"⚠️ insights: {e}", flush=True)
        return []


@app.get("/api/energy")
def energy():
    st = states()
    ov = overrides()
    pr = prices()
    raw_lim = val(st, SOLAR["limit"]) if SOLAR["limit"] else None
    # Motorns egna loggade värden (från vilken soldrivrutin som helst) - reserv när solentiteterna saknas
    # (märken som läses via Modbus eller tjänsteanrop i stället för entiteter).
    now_items, sl, house, battery = [], {}, None, None
    try:
        with ENGINE.connect() as c:
            r = c.execute(text("SELECT decision_summary, pv_power_w, solar_limit_pct, solar_today_kwh, indoor_temp, target_room_temp, "
                               "water_temp, active_mode, compressor_running, battery_power_w, battery_soc FROM sensor_log "
                               "WHERE timestamp > now() - interval '10 minutes' ORDER BY timestamp DESC LIMIT 1")).fetchone()
        if r:
            now_items = json.loads(r[0]) if r[0] else []
            sl = {"w": r[1], "limit": r[2], "today": r[3]}
            # Hemskärmens rutor (2026-11-06): inne, värmepump, varmvatten och husbatteri ur motorns senaste minut
            fl = lambda v: None if v is None else round(float(v), 1)
            house = {"inside": fl(r[4]), "target": fl(r[5]), "water": fl(r[6]), "mode": r[7],
                     "running": None if r[8] is None else bool(float(r[8]))}
            if r[9] is not None or r[10] is not None:
                battery = {"w": None if r[9] is None else round(float(r[9])), "soc": None if r[10] is None else round(float(r[10]))}
    except Exception:
        pass
    fb = lambda v, k: v if v is not None else (float(sl[k]) if sl.get(k) is not None else None)
    return {"ok": True, "now": now_items,
            "solar": {"w": fb(first_num(st, SOLAR["pv"]), "w"), "today_kwh": fb(first_num(st, SOLAR["today"]), "today"), "forecast_w": num(st, "sensor.smartbox_solprognos"), "status": (lambda v: SE_STATUS.get(v, v))(next((val(st, e) for e in SOLAR["status"] if val(st, e) is not None), None)),
                      "limit_pct": fb(None if raw_lim is None else num(st, SOLAR["limit"]), "limit"), "ai_limit": str(ov.get("ai_solar_limit_active", "false")).lower() == "true",
                      "export_price_floor": float(ov.get("solar_export_price_limit", -1.0) or -1.0), "notify": str(ov.get("notify_solar_limit", "true")).lower() == "true"},
            "grid": {"net_w": net_now(), "price": pr.get("now"), "level": pr.get("level")},
            "peaks": month_peaks(), "today_kwh": num(st, "sensor.smartbox_forbrukning_idag"), "saving_today": num(st, "sensor.smartbox_besparing_idag"), "decision": val(st, "sensor.smartbox_beslut"),
            "solar_ev_kwh": num(st, "sensor.smartbox_elbil_solel"), "insights": safe_insights(st, ov, pr), "log": val(st, "sensor.smartbox_beslut"),
            "alerts": control_alerts(ov), "house": house,
            "battery": battery and {**battery, "control": battery_control_mode(), "topup_target": intval(ov.get("battery_topup_target")) or None}}


def control_alerts(ov: dict) -> list:
    """Enheter som inte gör det EnergyWizard säger åt dem (smartbox/control_alerts.py, samma som webben)."""
    import control_alerts as _ca
    return _ca.build(ov)


@app.post("/api/energy/{what}")
async def energy_action(what: str, request: Request):
    v = (await request.json()).get("value")
    logact(request, f"Energi: {what} → {v}")
    if what == "limit":
        pct = max(0, min(100, intval(v)))
        auto = str(overrides().get("solar_auto_export", "true")).lower() != "false"
        with ENGINE.connect() as c:
            r = c.execute(text("SELECT price FROM sensor_log WHERE price IS NOT NULL ORDER BY timestamp DESC LIMIT 1")).first()
        price = r[0] if r else None
        if auto and price is not None and float(price) < 0:
            raise HTTPException(409, "Automatiken styr exportgränsen just nu (minuspris). Stäng av automatiken för att styra själv.")
        drv = SOLAR["driver"]
        if drv is None or not drv.supports_curtailment():
            raise HTTPException(409, "Solcellerna i installationen går inte att begränsa")
        if not drv.set_export_limit_pct(pct):
            raise HTTPException(502, "Växelriktaren svarade inte")
        return {"ok": True, "msg": f"Exportgräns satt till {pct} %"}
    if what == "floor":
        f = round(max(-1.0, min(5.0, float(v))), 2)
        set_override("solar_export_price_limit", str(f))
        import nordpool
        return {"ok": True, "msg": f"Begränsar export under {f:.2f} {nordpool.cost_settings()['symbol']}/kWh"}
    if what == "auto":
        set_override("solar_auto_export", "true" if v else "false")
        return {"ok": True, "msg": "Automatisk exportstyrning " + ("på" if v else "av")}
    if what == "notify":
        set_override("notify_solar_limit", "true" if v else "false")
        return {"ok": True, "msg": "Avisering " + ("på" if v else "av")}
    raise HTTPException(404, "Okänd åtgärd")


@app.get("/api/rooms")
def rooms():
    """Rummen = de valda innegivarna, live ur HA (homeassistant.room_temps) - inga fasta rum i koden."""
    try:
        with ENGINE.connect() as c:
            hum = c.execute(text("SELECT indoor_humidity FROM sensor_log ORDER BY timestamp DESC LIMIT 1")).scalar()
    except Exception:
        hum = None
    return {"rows": H.room_temps(), "humidity": None if hum is None else round(float(hum)), "ts": dt.datetime.now(TZ).strftime("%H:%M")}


# -- Hälsning, väder och dagens peppord ----------------------------------------------------------------------------------------
COND = {"clear-night": "Klart", "cloudy": "Molnigt", "fog": "Dimma", "hail": "Hagel", "lightning": "Åska", "lightning-rainy": "Åska och regn", "partlycloudy": "Halvklart", "pouring": "Spöregn", "rainy": "Regn", "snowy": "Snö",
        "snowy-rainy": "Snöblandat regn", "sunny": "Soligt", "windy": "Blåsigt", "windy-variant": "Blåsigt", "exceptional": "Extremt väder"}
# Namn och personliga peppfraser är husets egna (ew_settings "names" och "pep": {användare: {"sv": [...], "en": [...]}})
# - inget i koden. Utan egna fraser: ordspråk och dagsaktuella kommentarer.
def _names() -> dict:
    n = (ew_settings.get("names") if ew_settings else None) or {}
    return n if isinstance(n, dict) else {}


def _pep(user, lang) -> list:
    p = ((ew_settings.get("pep") if ew_settings else None) or {}).get(user or "") or {}
    v = p.get(lang) if isinstance(p, dict) else None
    return [x for x in v if isinstance(x, str)] if isinstance(v, list) else []


def _family_user():
    return next((u for u, r in EXTRA_ROLES.items() if r == "family"), "familj")


PROVERBS = ["Det som inte dödar dig gör dig starkare – men dyr el gör dig bara fattigare.", "Borta bra men hemma bäst.", "Den som väntar på något gott väntar ofta på billig el.", "Ordning och reda ger laddade batterier.",
            "Små steg varje dag tar en långt.", "Gör det du kan, med det du har, där du är.", "Lyckan ler mot den som laddar på natten.", "Bättre en sparad kilowattimme än tio planerade."]


COND_EN = {"clear-night": "Clear", "cloudy": "Cloudy", "fog": "Fog", "hail": "Hail", "lightning": "Thunder", "lightning-rainy": "Thunder and rain", "partlycloudy": "Partly cloudy", "pouring": "Pouring rain", "rainy": "Rain", "snowy": "Snow",
           "snowy-rainy": "Sleet", "sunny": "Sunny", "windy": "Windy", "windy-variant": "Windy", "exceptional": "Extreme weather"}
PROVERBS_EN = ["What doesn't kill you makes you stronger – but expensive electricity just makes you poorer.", "Away is good but home is best.", "Those who wait for something good often wait for cheap electricity.", "Order and tidiness give charged batteries.",
               "Small steps every day take you far.", "Do what you can, with what you have, where you are.", "Luck smiles on those who charge at night.", "Better one saved kilowatt hour than ten planned."]


def forecast_today(st: dict):
    we = weather_entity(st)
    if not we:
        return None, None, None
    try:
        r = requests.post(f"{H._BASE}/services/weather/get_forecasts?return_response", headers=H._HEADERS, json={"entity_id": we, "type": "daily"}, timeout=8, verify=False)
        f = r.json()["service_response"][we]["forecast"][0]
        return f.get("temperature"), f.get("templow"), f.get("precipitation")
    except Exception:
        return None, None, None


@app.get("/api/greeting")
def greeting(request: Request):
    role, user = _session(request)
    if role == "owner" and request.query_params.get("as") == "family":      # ägarens förhandsvisning av familjens vy
        role, user = "family", _family_user()
    elif role == "owner" and request.query_params.get("as") == "guest":
        role, user = "guest", "gäst"
    now = dt.datetime.now(TZ)
    name = _names().get(user or "") or (("guest" if request.query_params.get("lang") == "en" else "gäst") if role == "guest" else ("you" if request.query_params.get("lang") == "en" else "du"))
    en = request.query_params.get("lang") == "en"
    part = ("Good night" if now.hour < 5 else "Good morning" if now.hour < 10 else "Hello" if now.hour < 17 else "Good evening") if en else ("God natt" if now.hour < 5 else "God morgon" if now.hour < 10 else "Hej" if now.hour < 17 else "God kväll")
    st = states()
    w = st.get(weather_entity(st) or "") or {}
    wa = w.get("attributes", {})
    hi, lo, rain = forecast_today(st)
    bits = [(COND_EN if en else COND).get(w.get("state"), (w.get("state") or "").capitalize())]
    if wa.get("temperature") is not None:
        bits.append(f"{wa['temperature']:.0f}°" + (f" ({lo:.0f}–{hi:.0f}°)" if hi is not None and lo is not None else ""))
    if wa.get("wind_speed") is not None:
        bits.append(f"{'wind' if en else 'vind'} {wa['wind_speed'] / 3.6:.0f} m/s")
    if rain:
        bits.append(f"{'rain' if en else 'regn'} {rain:.0f} mm")
    pool = (_pep(user, "en") + PROVERBS_EN) if en else (_pep(user, "sv") + PROVERBS)
    pr = prices()
    net = net_now()
    data_quips = []
    if net is not None and net < -500:
        data_quips.append(f"We're selling {abs(net) / 1000:.1f} kW of solar right now – cha-ching!" if en else f"Vi säljer {abs(net) / 1000:.1f} kW solel just nu – kassakon!")
    if pr.get("level") == "billigt":
        data_quips.append("Electricity is cheap now – take the chance to charge." if en else "Elen är billig nu – passa på att ladda.")
    elif pr.get("level") == "dyrt":
        data_quips.append("Expensive electricity right now – let the car wait." if en else "Dyr el just nu – låt bilen vänta.")
    pool = pool + data_quips * 2                                  # dagsaktuella kommentarer får lite extra vikt
    block = int(time.time() // 600)                               # ny mening var 10:e minut
    line = pool[int(hashlib.sha256(f"{user}|{block}".encode()).hexdigest(), 16) % len(pool)]
    return {"hello": f"{part}, {name}!", "weather": " · ".join(b for b in bits if b), "line": line}


# -- Familjelogg ------------------------------------------------------------------------------------------------------------
def _who(request: Request) -> str:
    u = _session(request)[1] or "?"
    return _names().get(u) or ("Ägaren" if u == "owner" else u.capitalize())


def logact(request: Request, txt: str) -> None:
    try:
        with ENGINE.begin() as c:
            c.execute(text("CREATE TABLE IF NOT EXISTS ew_log (id BIGSERIAL PRIMARY KEY, ts TIMESTAMPTZ DEFAULT NOW(), usr TEXT, txt TEXT)"))
            c.execute(text("INSERT INTO ew_log (usr, txt) VALUES (:u, :t)"), {"u": _who(request), "t": txt[:200]})
    except Exception as e:
        print(f"⚠️ logg: {e}", flush=True)


@app.post("/api/clienterr")
async def clienterr(request: Request):
    try:
        b = await request.json()
        msg = f"{str(b.get('m'))[:300]} @ {str(b.get('s'))[:300]} | {str(b.get('ua'))[:80]}"
    except Exception:
        return {"ok": False}
    _role_user = _session(request)[1] or "?"
    print(f"⚠️ klientfel ({_role_user}): {msg}", flush=True)
    try:
        logact(request, "JS-fel: " + msg[:200])
    except Exception:
        pass
    return {"ok": True}


@app.get("/api/log")
def get_log():
    try:
        with ENGINE.connect() as c:
            rows = c.execute(text("SELECT ts, usr, txt FROM ew_log ORDER BY id DESC LIMIT 40")).fetchall()
    except Exception:
        rows = []
    return {"rows": [{"t": r[0].astimezone(TZ).strftime("%d/%m %H:%M"), "who": r[1], "txt": r[2]} for r in rows]}


# -- Ljus: fönsterlampor och godnatt - bara de lampor man själv valt ---------------------------------------------------------------
# "lights" i /data/energywizard.json: {"windows_group": "light.x" (grupp eller lampa), "up": ["light.a", ...],
# "night_skip": {"entity": "light.y", "from": 18, "to": 8}, "skip": ["light.z"]}. windows_group får också vara en lista
# (grupper och enskilda lampor/reläer, t.ex. ett Shelly-relä som switch.*). Grupper expanderas i alla nivåer; "skip" =
# lampor i grupperna som inte längre används (ersatta, bortkopplade). Utan val: inga lampknappar och ingen lampbevakning
# (#134: förut bevakades ägarens egna lampor i alla hus och larmade "lampa offline" hos andra).
def _lights_cfg() -> dict:
    c = (ew_settings.get("lights") if ew_settings else None) or {}
    return c if isinstance(c, dict) else {}


def _windows_group():
    return _lights_cfg().get("windows_group") or None


def _up_lights() -> list:
    return [e for e in (_lights_cfg().get("up") or []) if isinstance(e, str) and e.startswith(("light.", "switch."))]


def _members(st: dict, group) -> list:
    """Lamporna bakom en grupp, en lista eller en enskild lampa - grupper i grupper expanderas (2026-11-08: Charlies
    lampa låg i en undergrupp, så nattregeln och offline-bevakningen nådde den aldrig). Utan "skip"-lamporna."""
    skip = set(_lights_cfg().get("skip") or [])
    out, seen = [], set()

    def walk(e, depth=0):
        if not isinstance(e, str) or e in seen or depth > 5:
            return
        seen.add(e)
        sub = (st.get(e) or {}).get("attributes", {}).get("entity_id")
        if isinstance(sub, list) and sub:
            for x in sub:
                walk(x, depth + 1)
        elif e not in skip:
            out.append(e)
    for g in (group if isinstance(group, list) else [group] if group else []):
        walk(g)
    return out


def _light_summary(st: dict, ents: list) -> dict:
    on = sum(1 for e in ents if (st.get(e) or {}).get("state") == "on")
    off = sum(1 for e in ents if (st.get(e) or {}).get("state") == "off")
    bad = [((st.get(e) or {}).get("attributes", {}).get("friendly_name") or e) for e in ents if (st.get(e) or {}).get("state") in (None, "unavailable", "unknown")]
    return {"on": on, "off": off, "total": len(ents), "offline": bad}


@app.get("/api/lights")
def lights():
    st = states()
    return {"configured": bool(_windows_group() or _up_lights()), "has_windows": bool(_windows_group()), "has_up": bool(_up_lights()),
            "windows": _light_summary(st, _members(st, _windows_group())), "up": _light_summary(st, _up_lights())}


def _lights_work(a, who_req_log):
    OFFLINE = (None, "unavailable", "unknown")
    wg, up = _windows_group(), _up_lights()
    plan = {"windows_on": (_members(states(), wg), "turn_on", "Fönsterlampor tända"), "windows_off": (_members(states(), wg), "turn_off", "Fönsterlampor släckta"),
            "up_on": (up, "turn_on", "Tänt uppe"), "goodnight": (up, "turn_off", "Godnatt – släckt uppe")}.get(a)
    if not plan:
        raise HTTPException(400, "Okänd åtgärd")
    ents, svc, msg = plan
    if not ents:
        raise HTTPException(409, "Inga lampor valda för det här")
    ns = _lights_cfg().get("night_skip") or {}
    if a == "windows_on" and ns.get("entity"):          # en lampa som inte ska tändas nattetid (t.ex. ett barnrum)
        h, f, t = dt.datetime.now(TZ).hour, int(ns.get("from", 18)), int(ns.get("to", 8))
        if (h >= f or h < t) if f > t else (f <= h < t):
            ents = [e for e in ents if e != ns["entity"]]
    want = "on" if svc == "turn_on" else "off"
    cur = lambda e: (states().get(e) or {}).get("state")
    for attempt in range(3):                                   # Zigbee tappar ibland kommandon: kontrollera och försök igen på de som inte följt med (sista försöket en och en)
        todo = [e for e in ents if cur(e) not in (want, *OFFLINE)]
        if not todo:
            break
        try:
            for batch in ([todo] if attempt < 2 else [[e] for e in todo]):
                # homeassistant.turn_on/off: fungerar för både lampor och reläer (switch.*, t.ex. Shelly) i samma anrop
                requests.post(f"{H._BASE}/services/homeassistant/{svc}", headers=H._HEADERS, json={"entity_id": batch}, timeout=15, verify=False).raise_for_status()
        except Exception as e:
            raise HTTPException(502, f"Home Assistant svarade inte: {str(e)[:60]}")
        for _ in range(8):
            time.sleep(0.8)
            _cache["t"] = 0.0
            if all(cur(e) in (want, *OFFLINE) for e in todo):
                break
        _cache["t"] = 0.0
    st = states()
    ok = [e for e in ents if (st.get(e) or {}).get("state") == want]
    bad = [e for e in ents if (st.get(e) or {}).get("state") not in (want, *OFFLINE)]
    off = [((st.get(e) or {}).get("attributes", {}).get("friendly_name") or e) for e in ents if (st.get(e) or {}).get("state") in OFFLINE]
    who_req_log(f"{msg} ({len(ok)}/{len(ents)})")
    extra = (f" – {len(bad)} svarade inte" if bad else "") + (f" · offline: {', '.join(n.replace('Fönsterlampa - ', '') for n in off)}" if off else "")
    return {"ok": not bad, "msg": f"{msg} ({len(ok)} av {len(ents)}){extra}"}


@app.post("/api/lights")
async def lights_action(request: Request):
    import asyncio
    a = (await request.json()).get("action")
    return await asyncio.to_thread(_lights_work, a, lambda t: logact(request, t))               # väntan på Zigbee ska inte blockera övriga anrop (liveströmmen)


# -- Resplan: 'klar kl X till Y %' -> laddschema för rätt dag ------------------------------------------------------------------
@app.post("/api/trip")
async def trip(request: Request):
    b = await request.json()
    car = b.get("car")
    if car not in CARS:
        raise HTTPException(400, "Okänd bil")
    try:
        dt.datetime.strptime(str(b.get("time")), "%H:%M")
    except ValueError:
        raise HTTPException(400, "Ogiltig tid")
    soc = max(20, min(100, intval(b.get("soc") or 80)))
    when = dt.datetime.now(TZ) + (dt.timedelta(days=1) if b.get("day") == "tomorrow" else dt.timedelta())
    wd = when.weekday()
    with ENGINE.begin() as c:
        c.execute(text("""INSERT INTO ev_charging_schedule (car_id, day_of_week, target_time, enabled, target_soc, panic_mode) VALUES (:c, :d, :t, TRUE, :s, FALSE)
                          ON CONFLICT (car_id, day_of_week) DO UPDATE SET target_time = EXCLUDED.target_time, enabled = TRUE, target_soc = EXCLUDED.target_soc"""), {"c": car, "d": wd, "t": b["time"], "s": soc})
    set_override("force_ev_recalc", "true")
    logact(request, f"Resplan {CARS[car]['name']}: klar {b['time']} {'imorgon' if b.get('day') == 'tomorrow' else 'idag'} till {soc} %")
    return {"ok": True, "msg": f"Klar kl {b['time']} {'imorgon' if b.get('day') == 'tomorrow' else 'idag'} – {soc} %"}


# -- Veckorapport ---------------------------------------------------------------------------------------------------------------
@app.get("/api/report")
def report():
    with ENGINE.connect() as c:
        rows = c.execute(text("""SELECT date_trunc('day', timestamp AT TIME ZONE 'Europe/Stockholm') d, sum(COALESCE(house_consumption_w, 0)) / 60000.0, sum(COALESCE(pv_power_w, 0)) / 60000.0, sum(COALESCE(ev_power_kw, 0) + COALESCE(ev_carport_power_kw, 0)) / 60.0,
                                        sum(COALESCE(house_consumption_w, 0) * price) / 60000.0, avg(price)
                                 FROM sensor_log WHERE timestamp >= NOW() - INTERVAL '7 days' AND house_consumption_w IS NOT NULL GROUP BY 1 ORDER BY 1""")).fetchall()
    f = lambda x: 0.0 if x is None else float(x)
    days = [{"d": r[0].strftime("%a %d/%m"), "use": round(f(r[1]), 1), "sun": round(f(r[2]), 1), "ev": round(f(r[3]), 1), "cost": round(f(r[4]), 1)} for r in rows]
    tot = {"use": round(sum(d["use"] for d in days), 1), "sun": round(sum(d["sun"] for d in days), 1), "ev": round(sum(d["ev"] for d in days), 1), "cost": round(sum(d["cost"] for d in days), 1),
           "price": round(float(sum(f(r[5]) for r in rows) / len(rows)), 2) if rows else None}
    return {"days": days, "total": tot}


# -- Spabad: klart till en viss tid -------------------------------------------------------------------------------------------
@app.post("/api/home/spa_ready")
async def spa_ready(request: Request):
    b = await request.json()
    with ENGINE.begin() as c:
        if b.get("off"):
            c.execute(text("UPDATE system_settings SET spa_schedule_enabled = FALSE WHERE id = 1"))
            msg = "Spabadets tidsstyrning av"
        else:
            when = dt.datetime.strptime(str(b.get("when")), "%Y-%m-%dT%H:%M").replace(tzinfo=TZ)
            temp = max(20.0, min(40.0, float(b.get("temp") or 38.0)))
            c.execute(text("UPDATE system_settings SET spa_schedule_enabled = TRUE, spa_target_datetime = :w, spa_target_temp = :t WHERE id = 1"), {"w": when, "t": temp})
            msg = f"Spabadet klart {when.strftime('%a %H:%M')} – {temp:.1f}°"
    logact(request, msg)
    return {"ok": True, "msg": msg}


# -- Liveström: servern säger till när något ändrats (SSE), så appen uppdateras direkt i stället för att fråga var femte sekund ---------
def _stream_sig() -> str:
    st = states()
    parts = []
    for e, s in sorted(st.items()):
        if e.startswith(("light.", "switch.")) or e.startswith("sensor.smartbox") or e in CFG_ENTITIES:
            v = s.get("state")
            try:
                v = str(round(float(v), 1 if "soc" in e or "battery" in e or "temp" in e else 0 if abs(float(v)) > 50 else 1))      # brus under mätnoggrannheten ska inte ge ny uppdatering
            except (TypeError, ValueError):
                v = str(v)
            parts.append(f"{e}={v}")
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:12]


@app.get("/api/stream")
async def stream(request: Request):
    import asyncio
    from fastapi.responses import StreamingResponse

    async def gen():
        last, idle, t0 = None, 0, time.time()
        yield "retry: 3000\n\n"
        while time.time() - t0 < 600 and not await request.is_disconnected():          # klienten ansluter om själv efter 10 min (EventSource gör det automatiskt)
            try:
                sig = await asyncio.to_thread(_stream_sig)
            except Exception:
                sig = last
            if sig != last:
                last, idle = sig, 0
                yield f"data: {json.dumps({'v': sig, 't': int(time.time())})}\n\n"
            else:
                idle += 1
                if idle % 10 == 0:
                    yield ": ping\n\n"                                               # håller anslutningen levande genom nginx
            await asyncio.sleep(2)
    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# -- Bevakning: pushnotiser till telefonerna via Home Assistant (laddning klar, kabel lossnar, saknade sensorer) -----------------------
def _phones() -> dict:
    """Användare -> telefon i Home Assistant (notify.<tjänst>), sparat som "phones" i /data/energywizard.json,
    t.ex. {"owner": "mobile_app_pixel", "elin": "mobile_app_iphone"}. Utan val: telefonen motorn hittar."""
    p = (ew_settings.get("phones") if ew_settings else None) or {}
    if not p:
        try:
            import notifier
            t = notifier.target()
            p = {"owner": t} if t else {}
        except Exception:
            p = {}
    return p
_prev: dict = {"status": {}, "bad": {}}


def push(targets: list, title: str, msg: str, key: str | None = None) -> None:
    try:
        import notify_prefs
        if not notify_prefs.enabled(key, title):        # kategorin avstängd under Inställningar -> Notiser
            _nlog(title, msg, "muted", None, key)
            return
    except Exception:
        pass
    try:                                                 # "bara den som är hemma" - samma regel som motorn (notifier.py)
        import notifier as _nf
        if _nf.home_only():
            _svcs = {t: _phones().get(t) for t in targets if _phones().get(t)}
            _keep = set(_nf.pick_home(list(_svcs.values())))
            targets = [t for t, s in _svcs.items() if s in _keep]
    except Exception:
        pass
    sent_to = 0
    for t in targets:
        _svc = None
        try:
            _svc = _phones().get(t)
            if not _svc:
                continue
            sent_to += 1
            # #202: samma översättning som motorns aviseringar (notifier._localized_payload), på installationens språk
            try:
                import notifier as _nf2
                _pl = _nf2._localized_payload(title, msg, None)
            except Exception:
                _pl = {"title": title, "message": msg}
            requests.post(f"{H._BASE}/services/notify/{_svc}", headers=H._HEADERS, json={"title": _pl["title"], "message": _pl["message"]}, timeout=8, verify=False).raise_for_status()
            _nlog(title, msg, "sent", _svc, key)
        except Exception as e:
            print(f"⚠️ push {t}: {e}", flush=True)
            try:
                import notify_log
                _nlog(title, msg, "failed", _svc, key, notify_log.short_error(e))
            except Exception:
                pass
    if not sent_to:
        _nlog(title, msg, "none", None, key, "Ingen telefon vald, eller ingen hemma med \"bara den som är hemma\"")


def _nlog(title, msg, status, recipient=None, key=None, detail=None):
    """Aviseringshistoriken (smartbox/notify_log.py), samma tabell som motorns aviseringar."""
    try:
        import notify_log
        notify_log.add(title, msg, status, recipient, key, detail, src="appen")
    except Exception:
        pass


def watch_once():
    st = states()
    for key in CARS:
        c = CARS[key]
        cur = (val(st, c["status"]) or "unknown").lower()
        prev = _prev["status"].get(key)
        _prev["status"][key] = cur
        if prev is None:
            continue
        soc = num(st, c["soc"])
        to = c.get("notify") or list(_phones())
        if prev == "charging" and cur in ("completed", "ready_to_charge"):
            push(to, f"{c['name']} är fulladdad", f"Batteri {soc:.0f} %." if soc is not None else "Laddningen är klar.", key="elbil")
        elif prev == "charging" and cur == "disconnected":
            push(to, f"{c['name']}: kabeln lossnade", "Laddningen avbröts – laddkabeln verkar ha kopplats ur.", key="elbil")
    now = time.time()
    _wg = _windows_group()
    for e in list(dict.fromkeys(list(_members(st, _wg)) + _up_lights())):
        key = "light:" + e
        if (st.get(e) or {}).get("state") in (None, "unavailable", "unknown"):
            first = _prev["bad"].setdefault(key, now)
            if now - first > 1800 and _prev["bad"].get(key + "_sent") is None:
                _prev["bad"][key + "_sent"] = now
                push(["owner"], "EnergyWizard: lampa offline", f"{(st.get(e) or {}).get('attributes', {}).get('friendly_name', e)} har varit onåbar i över 30 minuter.", key="lampor")
        else:
            _prev["bad"].pop(key, None); _prev["bad"].pop(key + "_sent", None)
    for e in WATCH:
        bad = val(st, e) is None
        if bad:
            first = _prev["bad"].setdefault(e, now)
            # En sovande Tesla ger inget batterivärde: smartboxen räknar då med senast kända nivå (högst 48 h) och väcker bilen när det är dags. Larma först när det gått längre än så.
            if now - first > WATCH_AFTER_S.get(e, 900) and _prev["bad"].get(e + "_sent") is None:
                _prev["bad"][e + "_sent"] = now
                push(["owner"], "EnergyWizard: sensor saknas", f"{e} har saknat värde i över 15 minuter.", key="system")
        else:
            _prev["bad"].pop(e, None); _prev["bad"].pop(e + "_sent", None)


def _watch_loop():
    import threading
    time.sleep(20)
    while True:
        try:
            watch_once()
        except Exception as e:
            print(f"⚠️ bevakning: {e}", flush=True)
        time.sleep(60)


# -- Home Assistant-bryggan: laddplan och laddläge som vanliga HA-entiteter (för Familjetavlan och andra) -----------------------------------
# Avtalet (samma för alla smartstyrningar, se Familjetavlans docs/SMART-LADDNING.md):
#   sensor.<bilnamn>_laddplan  tillstånd = text ("Laddar nu", "Planerad 01:15", "Pausad", "Ingen plan");
#                              attribut: slots = [{start, end, kw}] (ISO 8601 med tidszon, sammanhängande block), mode, soc, soc_after_plan, planned_kwh
#   input_select.<bilnamn>_laddlage  Auto | Ladda nu | Pausa  (skrivs av Familjetavlan; ger samma överstyrning som appens knappar)
MODE_OPTS = {"auto": "Auto", "now": "Ladda nu", "hold": "Pausa"}


def slug(car: str) -> str:
    """Entitets-id av bilens namn: "Tesla Model Y" -> tesla_model_y."""
    return re.sub(r"[^a-z0-9]+", "_", CARS[car]["name"].lower()).strip("_")


def ew_mode(car: str, ov: dict) -> str:
    if str(ov.get(f"{car}_hold", "off")).lower() == "on":
        return MODE_OPTS["hold"]
    if intval(ov.get(f"{car}_force_amps")) > 0:
        return MODE_OPTS["now"]
    return MODE_OPTS["auto"]


def plan_blocks(car: str) -> list:
    """Planerad laddning som sammanhängande block [{start, end, kw}] i ISO 8601 med tidszon (kvartsslots ur ev_plan_slots)."""
    now = dt.datetime.now(TZ).replace(tzinfo=None)
    try:
        with ENGINE.connect() as c:
            rows = c.execute(text("SELECT t_slot, kw FROM ev_plan_slots WHERE car_id = :c AND t_slot >= :n ORDER BY t_slot"), {"c": car, "n": now - dt.timedelta(minutes=15)}).fetchall()
    except Exception:
        return []
    blocks = []
    for t, kw in rows:
        kw = float(kw)
        if blocks and (t - blocks[-1]["_end"]).total_seconds() <= 60:
            b = blocks[-1]; b["_end"] = t + dt.timedelta(minutes=15); b["_kws"].append(kw)
        else:
            blocks.append({"_start": t, "_end": t + dt.timedelta(minutes=15), "_kws": [kw]})
    return [{"start": b["_start"].replace(tzinfo=TZ).isoformat(timespec="minutes"), "end": b["_end"].replace(tzinfo=TZ).isoformat(timespec="minutes"),
             "kw": round(sum(b["_kws"]) / len(b["_kws"]), 1)} for b in blocks]


def schedule_rows(car: str) -> list:
    """Laddschemat för bilen: sju rader {day 0=måndag, time, soc, enabled} (som i appen)."""
    rows = {d: {"day": d, "time": "07:00", "soc": 100, "enabled": False} for d in range(7)}
    try:
        with ENGINE.connect() as c:
            for day, t, soc, en in c.execute(text("SELECT day_of_week, target_time, target_soc, enabled FROM ev_charging_schedule WHERE car_id = :c"), {"c": car}):
                if 0 <= day <= 6:
                    rows[day] = {"day": day, "time": t.strftime("%H:%M"), "soc": int(soc), "enabled": bool(en)}
    except Exception:
        pass
    return [rows[d] for d in range(7)]


def solar_forecast_attr() -> list:
    """Solprognos per timme kommande dygn [{start (ISO), w}] som valfritt attribut på laddplanssensorn (för grafen i Familjetavlan)."""
    h0 = dt.datetime.now(TZ).replace(minute=0, second=0, microsecond=0)
    hrs = [h0 + dt.timedelta(hours=i) for i in range(PRICE_WINDOW_H)]
    sun = solar_forecast_w(hrs)
    return [{"start": h.isoformat(), "w": sun[int(h.timestamp() * 1000)]} for h in hrs if int(h.timestamp() * 1000) in sun]

def publish_plan(car: str, st: dict, ov: dict) -> tuple:
    c = CARS[car]
    soc = num(st, c["soc"])
    blocks = plan_blocks(car)
    pa = plan_blocks_ui(car, soc, c["cap_kwh"])
    by_start = {(b["day"], b["start"]): b for b in pa["blocks"]}
    now0 = dt.datetime.now(TZ)
    for b in blocks:      # batterinivå före/efter per block (valfria fält i avtalet), matchade på starttid
        t0 = dt.datetime.fromisoformat(b["start"])
        day = "idag" if t0.date() == now0.date() else ("imorgon" if t0.date() == now0.date() + dt.timedelta(days=1) else t0.strftime("%a"))
        m = by_start.get((day, t0.strftime("%H:%M")))
        if m and m["soc0"] is not None:
            b["soc_start"], b["soc_end"] = m["soc0"], m["soc1"]
    mode = ew_mode(car, ov)
    status = (val(st, c["status"]) or "unknown").lower()
    charging = status in ("charging",)
    now = dt.datetime.now(TZ)
    if mode == MODE_OPTS["hold"]:
        state = "Pausad"
    elif charging:
        state = "Laddar nu"
    elif blocks:
        b0 = blocks[0]
        t0 = dt.datetime.fromisoformat(b0["start"])
        state = "Planerad " + (t0.strftime("%H:%M") if t0.date() == now.date() else ("imorgon " if t0.date() == now.date() + dt.timedelta(days=1) else ["mån", "tis", "ons", "tors", "fre", "lör", "sön"][t0.weekday()] + " ") + t0.strftime("%H:%M"))
    else:
        state = "Ingen plan"
    kwh = round(sum(b["kw"] * (dt.datetime.fromisoformat(b["end"]) - dt.datetime.fromisoformat(b["start"])).total_seconds() / 3600 for b in blocks), 1)
    after = None if (soc is None or not blocks or not c["cap_kwh"]) else round(min(100.0, soc + kwh * 0.9 / c["cap_kwh"] * 100.0))      # 90 % verkningsgrad, som i appens plan
    attrs = {"friendly_name": f"{c['name']} laddplan", "icon": "mdi:ev-station", "slots": blocks, "mode": mode, "charging": charging, "soc": None if soc is None else round(soc),
             "soc_after_plan": after, "planned_kwh": kwh, "source": "EnergyWizard", "solar_forecast": solar_forecast_attr(),
             "morning_check": ({"time": pa["floor"]["time"], "soc": pa["floor"]["soc"], "min": 50} if pa.get("floor") else None), "schedule": schedule_rows(car), "schedule_car": car, "updated": now.isoformat(timespec="seconds")}
    return f"sensor.{slug(car)}_laddplan", (state, attrs)


def _ha_get(entity: str):
    r = requests.get(f"{H._BASE}/states/{entity}", headers=H._HEADERS, timeout=4, verify=False)
    return r.json().get("state") if r.status_code == 200 else None


def _ha_select(entity: str, option: str) -> None:
    requests.post(f"{H._BASE}/services/input_select/select_option", headers=H._HEADERS, json={"entity_id": entity, "option": option}, timeout=4, verify=False)


_bridge_last: dict = {}


def _spa_force_heat() -> bool:
    try:
        with ENGINE.connect() as c:
            return bool(c.execute(text("SELECT spa_force_heat FROM system_settings WHERE id = 1")).scalar())
    except Exception:
        return False


def _spa_apply(option: str) -> None:
    """Spabadets lägen (exklusiva): Auto = följer sitt schema, Värm nu = tvångsvärme, Eco = Eco-överstyrning."""
    with ENGINE.begin() as c:
        c.execute(text("UPDATE system_settings SET spa_force_heat = :v WHERE id = 1"), {"v": option == "Värm nu"})
    set_override("spa_force_eco", "on" if option == "Eco" else "auto")


def _house_channels() -> list:
    """Husets lägen som Home Assistant-väljare. Alla har Auto först = följer sitt eget schema (smartstyrningen), samma som knapparna i appen."""
    def three(key, labels):
        names = {"auto": "Auto", "on": labels[0], "off": labels[1]}
        inv = {v: k for k, v in names.items()}
        return (lambda ov: names.get(str(ov.get(key, "auto")).lower(), "Auto"), lambda opt: set_override(key, inv[opt]), ["Auto", labels[0], labels[1]])
    heat, hw = three("heat", ("Varm", "Sänkt")), three("hotwater", ("Till", "Från"))
    return [("input_select.energywizard_varme", "Värme inne läge", *heat),
            ("input_select.energywizard_varmvatten", "Varmvatten läge", *hw),
            ("input_select.energywizard_spabad", "Spabad läge", lambda ov: "Värm nu" if _spa_force_heat() else ("Eco" if ov.get("spa_force_eco") == "on" else "Auto"), _spa_apply, ["Auto", "Värm nu", "Eco"])]


def _channels() -> list:
    """(entitet, namn, läs-funktion, skriv-funktion, alternativ) för bilarna och huset."""
    out = []
    for car in CARS:
        kinds = {"Auto": "auto", "Ladda nu": "start", "Pausa": "stop"}

        def setcar(opt, car=car):
            car_command(car, kinds[opt], {})
        out.append((f"input_select.{slug(car)}_laddlage", f"{CARS[car]['name']} laddläge", lambda ov, car=car: ew_mode(car, ov), setcar, ["Auto", "Ladda nu", "Pausa"]))
    return out + _house_channels()


SCHEDULE_CMD = "input_text.energywizard_laddschema_kommando"


def schedule_command() -> bool:
    """Familjetavlan (eller annan app) ändrar laddschemat genom att skriva JSON i input_text.energywizard_laddschema_kommando:
    {"car": "tesla", "day": 0-6, "time": "07:00", "soc": 80, "enabled": true}. Vi sparar raden som appens schema (slår igenom i smartboxen) och kvitterar genom att tömma fältet."""
    raw = _ha_get(SCHEDULE_CMD)
    if not raw or raw in ("unknown", "unavailable"):
        return False
    try:
        b = json.loads(raw)
        car, day, t = b.get("car"), intval(b.get("day")), str(b.get("time", "07:00"))
        dt.datetime.strptime(t, "%H:%M")
        if car not in CARS or not 0 <= day <= 6:
            raise ValueError("bil eller dag")
        save_schedule_row(car, day, t, bool(b.get("enabled")), intval(b.get("soc") or 100))
        print(f"HA-brygga: laddschema {car} dag {day} {t} {'på' if b.get('enabled') else 'av'}", flush=True)
    except Exception as e:
        print(f"HA-brygga: ogiltigt laddschemakommando ({type(e).__name__})", flush=True)
    requests.post(f"{H._BASE}/services/input_text/set_value", headers=H._HEADERS, json={"entity_id": SCHEDULE_CMD, "value": ""}, timeout=4, verify=False)
    return True


def bridge_tick(publish: bool) -> None:
    """Ett varv: (1) om en Home Assistant-väljare ändrats av någon annan (t.ex. Familjetavlan), gör samma sak som appens knapp; (2) om appen ändrats, uppdatera väljaren; (3) publicera laddplanen."""
    ov = overrides()
    if schedule_command():
        publish = True
    for ent, name, getf, setf, opts in _channels():
        sel = _ha_get(ent)
        mine = getf(ov)
        last = _bridge_last.get(ent)
        if sel in opts and sel != mine and sel != last and last is not None:   # ändrad i Home Assistant: tillämpa som appens knapp (första varvet efter start: appen gäller, väljaren följer)
            try:
                setf(sel)
                print(f"HA-brygga: {ent} -> {sel}", flush=True)
            except HTTPException as e:
                print(f"HA-brygga: {ent} -> {sel} nekades: {e.detail}", flush=True)
            except Exception as e:
                print(f"HA-brygga: {ent} -> {sel} misslyckades: {type(e).__name__}", flush=True)
            ov = overrides(); mine = getf(ov); publish = True
        if sel is not None and sel != mine:
            _ha_select(ent, mine)                                            # appen (eller smartboxen) ändrade: håll väljaren i takt
        _bridge_last[ent] = mine
    if publish:
        st = states()
        H.publish_states(dict(publish_plan(car, st, ov) for car in CARS))


def _bridge_loop():
    n = 0
    while True:
        try:
            bridge_tick(publish=(n % 12 == 0))                              # väljaren var 5:e sekund, planen var minut
        except Exception as e:
            print(f"HA-brygga: {type(e).__name__}: {str(e)[:100]}", flush=True)
        n += 1
        time.sleep(5)


@app.on_event("startup")
def _start_watch():
    import threading
    if os.environ.get("EW_NO_WATCH") == "1":         # testkopia: inga bevakningar, inga notiser, ingen HA-brygga
        return
    threading.Thread(target=_watch_loop, daemon=True, name="ew-watch").start()
    threading.Thread(target=_bridge_loop, daemon=True, name="ew-ha-bridge").start()


@app.get("/api/ping")
def ping():
    return {"ok": True}


app.mount("/icons", StaticFiles(directory="static/icons"), name="icons")


@app.get("/manifest.webmanifest")
def manifest():
    return FileResponse("static/manifest.webmanifest", media_type="application/manifest+json")


@app.get("/sw.js")
def sw():
    # "/" (inte hårdkodat "/m/") - ewapp nås nu under flera olika prefix (nginx stripper
    # prefixet innan det når appen, se /m/ och /energywizard/mobil/), så ett smalare omfång
    # skulle göra service workern verkningslös/trasig under vilket prefix som helst förutom
    # just /m/. En bredare scope än det faktiska sidans path är alltid giltig för webbläsaren.
    return FileResponse("static/sw.js", media_type="application/javascript", headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"})


# Delade översättningar och sponsring ligger i smartbox/ (monterad från värden i compose-driften).
# En äldre kopia av smartbox/ på värden får inte krascha appen: då blir den bara svensk.
try:
    import i18n_routes  # noqa: E402
    i18n_routes.register(app)
    import web_common  # noqa: E402
    web_common.register(app, _role)
except ImportError as _ie:
    print(f"⚠️ Språk/sponsring avstängt (äldre smartbox/ på värden, kör git pull): {_ie}", flush=True)


@app.get("/app.js")
def appjs():
    return FileResponse("static/app.js", media_type="application/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/style.css")
def css():
    return FileResponse("static/style.css", media_type="text/css", headers={"Cache-Control": "no-cache"})


@app.get("/")
def index():
    return FileResponse("static/index.html", media_type="text/html", headers={"Cache-Control": "no-cache"})
