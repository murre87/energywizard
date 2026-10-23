"""EnergyWizard Mobil (ewapp): lättviktig mobilsida för laddning (Tesla först), bredvid Streamlit-dashboarden. Delar HA-, databas- och överstyrningslogik med smartbox (monteras från ./smartbox).
Serveras under /m/ (nginx tar bort prefixet). Allt kräver inloggning med samma lösenord som dashboarden. Bil-knapparna skriver samma överstyrningar som dashboarden (overrides) och slår på/av laddaren direkt."""
import base64, hashlib, hmac, json, math, os, re, sys, time, datetime as dt
from zoneinfo import ZoneInfo

sys.path.insert(0, "/smartbox")
import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine, text

import homeassistant as H

TZ = ZoneInfo("Europe/Stockholm")
PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "")
SECRET = hashlib.sha256(("ewapp|" + PASSWORD).encode()).digest()
ENGINE = create_engine(f"postgresql+psycopg://{os.environ['POSTGRES_USER']}:{os.environ['POSTGRES_PASSWORD']}@{os.environ.get('POSTGRES_HOST', 'postgres-smartbox')}/{os.environ['POSTGRES_DB']}", pool_pre_ping=True, pool_size=3)

CARS = {
    "tesla": {"name": "Tesla Model Y", "charger": H.EASEE_CARPORT_ID, "status": "sensor.carport_status", "power": "sensor.carport_effekt", "soc": "sensor.tesla_model_y_battery",
              "tracker": "device_tracker.tesla_model_y_location_tracker", "cap_kwh": 75.0, "phases": 3, "arrival": "sensor.tesla_model_y_arrival_time", "dist": "sensor.tesla_model_y_distance_to_arrival", "online": "binary_sensor.carport_online",
              "climate": "climate.tesla_model_y_hvac_climate_system", "inside": "sensor.tesla_model_y_temperature_inside"},
    "nissan": {"name": "Nissan Leaf", "charger": H.EASEE_LITE_ID, "status": "sensor.easee_lite_status", "power": "sensor.easee_lite_effekt", "soc": "sensor.smartbox_leaf_batteri",
               "tracker": "device_tracker.leaf_location", "cap_kwh": 40.0, "phases": 1, "arrival": None, "dist": None, "online": "binary_sensor.easee_lite_online",
               "climate": "climate.leaf_climate", "inside": "sensor.leaf_internal_temperature"},
}
WATCH = ["sensor.carport_status", "sensor.easee_lite_status", "sensor.tesla_model_y_battery", "sensor.smartbox_leaf_batteri"]

app = FastAPI(title="EnergyWizard Mobil")
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


_fails: dict = {}


@app.post("/api/login")
async def login(request: Request):
    ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "?").split(",")[0].strip()
    if _fails.get(ip, (0, 0))[0] >= 8 and time.time() - _fails[ip][1] < 600:
        raise HTTPException(429, "För många försök – vänta några minuter")
    body = await request.json()
    user, pw = str(body.get("user", "")).strip(), str(body.get("password", ""))
    role = who = None
    if not user and PASSWORD and hmac.compare_digest(pw, PASSWORD):
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
    """Validerade nyckeltal för första sidan (bara sådant som har ett giltigt, färskt värde)."""
    out = []
    if key == "tesla":
        rng, tmp = num(st, "sensor.tesla_model_y_range"), num(st, "sensor.tesla_model_y_temperature_outside")
        tp = [num(st, f"sensor.tesla_model_y_tpms_{p}") for p in ("front_left", "front_right", "rear_left", "rear_right")]
        tp = [x for x in tp if x is not None]
        if rng is not None: out.append(f"Räckvidd {rng:.0f} km")
        if tp: out.append(f"Däck {min(tp) * 0.0689476:.1f} bar".replace(".", ","))
        if tmp is not None: out.append(f"Ute {tmp:.0f}°")
    else:
        rng, dd = num(st, "sensor.leaf_range_ac_off"), num(st, "sensor.leaf_daily_distance")
        if rng is not None: out.append(f"Räckvidd {rng:.0f} km")
        if dd is not None and (age_h(st, "sensor.leaf_daily_distance") or 0) < 3: out.append(f"Idag {dd:.0f} km")
    return out


def car_state(key: str, st: dict, ov: dict) -> dict:
    c = CARS[key]
    status = (val(st, c["status"]) or "unknown").lower()
    plugged = status not in ("disconnected", "offline", "unknown")
    tracker = (val(st, c["tracker"]) or "unknown").lower()
    home = tracker == "home"
    p = num(st, c["power"]) or 0.0
    power_kw = p / 1000.0 if p > 100 else p
    soc = num(st, c["soc"])
    amps, phases = intval(ov.get(f"{key}_force_amps")), intval(ov.get(f"{key}_force_phases"))
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
            dst = (st.get("device_tracker.tesla_model_y_destination_location_tracker") or {}).get("attributes", {}) if key == "tesla" else {}

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
    return {"key": key, "name": c["name"], "soc": None if soc is None else round(soc), "status": status, "plugged": plugged, "home": home, "charging": charging, "power_kw": round(power_kw, 1),
            "mode": mode, "amps": amps, "phases": phases, "eta": eta, "away": away, "online": (val(st, c["online"]) or "off") == "on", "default_phases": c["phases"],
            "climate_on": (val(st, c["climate"]) or "off") not in ("off", "unavailable"), "inside": num(st, c["inside"]),
            "age_h": age_h(st, c["soc"] if key == "tesla" else "sensor.leaf_battery_level"), "facts": car_facts(key, st), "plan": plan_segments(key, soc, c["cap_kwh"]), "solar": solar_info(ov),
            "access": ({"locked": val(st, "lock.tesla_model_y_doors") == "locked", "trunk": val(st, "cover.tesla_model_y_trunk") == "open", "frunk": val(st, "cover.tesla_model_y_frunk") == "open"} if key == "tesla" else None)}


def prices() -> dict:
    now = dt.datetime.now(TZ)
    h0 = now.replace(minute=0, second=0, microsecond=0)
    try:
        with ENGINE.connect() as c:
            rows = c.execute(text("SELECT time_start, sek_per_kwh FROM elpriser WHERE time_start >= :a AND time_start < :b ORDER BY time_start"), {"a": h0, "b": h0 + dt.timedelta(hours=14)}).fetchall()
    except Exception:
        rows = []
    byh: dict = {}
    for t, p in rows:
        byh.setdefault(t.astimezone(TZ).replace(minute=0, second=0, microsecond=0), []).append(float(p))
    hours = [{"t": h.strftime("%H"), "p": round(sum(v) / len(v), 2), "now": h == h0} for h, v in sorted(byh.items())]
    cur = next((h["p"] for h in hours if h["now"]), None)
    allp = sorted(h["p"] for h in hours) or [0]
    lvl = None if cur is None else ("billigt" if cur <= allp[len(allp) // 3] else ("dyrt" if cur >= allp[2 * len(allp) // 3] else "normalt"))
    return {"now": cur, "level": lvl, "hours": hours}


@app.get("/api/state")
def state(request: Request):
    try:
        st = states()
    except Exception as e:
        return {"ok": False, "role": _role(request), "error": f"Kan inte nå Home Assistant: {e}", "cars": [], "price": {}, "health": [f"Home Assistant svarar inte ({str(e)[:60]})"]}
    ov = overrides()
    health = []
    for e in WATCH:
        v = val(st, e)
        if v is None:
            health.append(("Saknas i Home Assistant: " if e not in st else "Otillgänglig: ") + e)
    return {"ok": True, "role": _role(request), "user": _session(request)[1], "ts": int(time.time()), "cars": [car_state("tesla", st, ov), car_state("nissan", st, ov)], "price": prices(), "health": health,
            "solar_w": num(st, "sensor.solaredge_aktuell_effekt")}


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
        amps = 16 if kind == "max" else max(6, min(16, intval(body.get("amps") or 16)))
        phases = intval(body.get("phases")) if intval(body.get("phases")) in (1, 3) else 0
        if car == "nissan":
            phases = 1 if phases == 0 else phases
        set_override(f"{car}_hold", "off")
        set_override(f"{car}_force_amps", str(amps))
        set_override(f"{car}_force_phases", str(phases))
        ok = H.set_ev_dynamic_limit(c["charger"], amps)
        if status in ("awaiting_start", "paused", "off", "ready_to_charge", "completed"):
            H.turn_on_charger(c["charger"])
        return {"ok": bool(ok), "msg": (f"Startar laddning, {amps} A" + (f" ({phases}-fas)" if phases else "") + " – det kan ta en halv minut innan bilen börjar") if ok else "Laddaren svarade inte – försök igen"}
    if kind == "stop":
        set_override(f"{car}_force_amps", "0")
        set_override(f"{car}_force_phases", "0")
        set_override(f"{car}_hold", "on")
        H.set_ev_dynamic_limit(c["charger"], 0)
        H.turn_off_charger(c["charger"])
        return {"ok": True, "msg": "Laddning stoppad (håller tills du väljer Auto)"}
    if kind == "auto":
        set_override(f"{car}_hold", "off")
        set_override(f"{car}_force_amps", "0")
        set_override(f"{car}_force_phases", "0")
        set_override("force_ev_recalc", "true")
        return {"ok": True, "msg": "Auto – AI:n styr igen"}
    return None


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
        ok = H.set_car_climate(c["climate"], "heat_cool" if on else "off", 21.0 if on else None)
        if car == "nissan":                                   # samma som dashboarden: Nissans 'vakthund' följer överstyrningen
            set_override("nissan_climate", "21.0" if on else "off")
        _cache["t"] = 0.0
        if not ok:
            raise HTTPException(502, "Bilen svarade inte på klimatkommandot")
        return {"ok": True, "msg": ("Värmekommando skickat (21 °C)" if on else "Stoppkommando skickat") + (" – Nissan kan ta någon minut på sig" if car == "nissan" else "")}
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
    ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "?").split(",")[0].strip()
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


@app.post("/api/tesla/access")
async def tesla_access(request: Request):
    """Teslas lås och luckor. what: lock | unlock | trunk | frunk. Allt utom 'lock' kräver /api/secure (lösenord) de senaste 10 minuterna. Alla anrop loggas."""
    body = await request.json()
    what = body.get("what")
    if what not in ("lock", "unlock", "trunk", "frunk"):
        raise HTTPException(400, "Okänd åtgärd")
    if what != "lock" and not _secure_ok(request):
        raise HTTPException(403, "secure")                     # appen ber om lösenord och försöker igen
    st = states()
    try:
        if what == "lock":
            _ha_call("lock", "lock", "lock.tesla_model_y_doors"); msg = "Bilen låst"
        elif what == "unlock":
            _ha_call("lock", "unlock", "lock.tesla_model_y_doors"); msg = "Bilen upplåst"
        else:
            ent = "cover.tesla_model_y_trunk" if what == "trunk" else "cover.tesla_model_y_frunk"
            is_open = val(st, ent) == "open"
            _ha_call("cover", "close_cover" if is_open else "open_cover", ent)
            msg = ("Baklucka" if what == "trunk" else "Framlucka") + (" stängs" if is_open else " öppnas")
    except Exception as e:
        print(f"🔐 Tesla {what} MISSLYCKADES: {e}", flush=True)
        raise HTTPException(502, "Bilen svarade inte (den kan sova – försök igen om en stund)")
    print(f"🔐 Tesla {what} OK ({request.headers.get('x-forwarded-for', '?').split(',')[0]})", flush=True)
    logact(request, f"Tesla: {msg}")
    _cache["t"] = 0.0
    return {"ok": True, "msg": msg}


# -- Hus: värme, varmvatten, spabad, gräsklippare, effekt ----------------------------------------------------------------
SETTING_RULES = {  # kolumn: (typ, min, max, steg)
    "peak_shaving_enabled": ("bool",), "power_limit_kw": ("float", 3.0, 25.0, 0.5), "fuse_size_a": ("float", 16.0, 63.0, 1.0),
    "temp_cheap": ("float", 17.0, 25.0, 0.5), "temp_expensive": ("float", 15.0, 24.0, 0.5), "spa_normal_temp": ("float", 20.0, 40.0, 0.5), "spa_max_temp": ("float", 30.0, 42.0, 0.5),
    "notify_spa_ready": ("bool",), "notify_ev_start": ("bool",), "notify_washer_start": ("bool",), "notify_spa_open": ("bool",),
}


def get_settings_row() -> dict:
    with ENGINE.connect() as c:
        row = c.execute(text("SELECT " + ", ".join(SETTING_RULES) + ", spa_force_heat, spa_schedule_enabled, spa_target_datetime, spa_target_temp FROM system_settings WHERE id = 1")).mappings().first()
    return dict(row) if row else {}


def mower_info() -> dict:
    try:
        with ENGINE.connect() as c:
            r = c.execute(text("SELECT mower_status, mower_power_w, timestamp FROM sensor_log WHERE mower_status IS NOT NULL ORDER BY timestamp DESC LIMIT 1")).first()
        return {"status": r[0], "power_w": r[1], "ts": r[2].astimezone(TZ).strftime("%H:%M")} if r else {}
    except Exception:
        return {}


def net_now():
    """Nettoeffekt mot elnätet i W: plus = köper, minus = säljer (senaste raden i smartboxens logg)."""
    try:
        with ENGINE.connect() as c:
            r = c.execute(text("SELECT net_power FROM sensor_log WHERE net_power IS NOT NULL AND timestamp > NOW() - INTERVAL '10 minutes' ORDER BY timestamp DESC LIMIT 1")).first()
        return None if r is None else float(r[0])
    except Exception:
        return None


@app.get("/api/home")
def home():
    st = states()
    ov = overrides()
    cfg = get_settings_row()
    mower = mower_info()
    plug = val(st, "switch.shelly_plug_s_gen3")
    return {"ok": True,
            "heat": {"inside": num(st, "sensor.smartbox_inomhustemp"), "target": num(st, "sensor.smartbox_maltemperatur"), "outside": num(st, "sensor.smartbox_utetemperatur"), "mode": ov.get("heat", "auto"),
                     "pump_w": num(st, "sensor.smartbox_effekt_varmepump"), "price_mode": val(st, "sensor.smartbox_lage"), "cop": num(st, "sensor.smartbox_cop"), "temp_cheap": cfg.get("temp_cheap"), "temp_expensive": cfg.get("temp_expensive")},
            "water": {"temp": num(st, "sensor.smartbox_varmvatten"), "mode": ov.get("hotwater", "auto")},
            "spa": {"temp": num(st, "sensor.spa_malmgatan_34_current_temperature"), "target": num(st, "sensor.spa_malmgatan_34_target_temperature"), "heater": val(st, "water_heater.spa_malmgatan_34_heater"),
                    "force_heat": bool(cfg.get("spa_force_heat")), "eco": ov.get("spa_force_eco") == "on",
                    "ready_at": (cfg["spa_target_datetime"].astimezone(TZ).strftime("%a %H:%M") if cfg.get("spa_schedule_enabled") and cfg.get("spa_target_datetime") else None), "ready_temp": cfg.get("spa_target_temp") if cfg.get("spa_schedule_enabled") else None, "power_w": num(st, "sensor.smartbox_effekt_spa"), "error": val(st, "sensor.spa_malmgatan_34_error_s")},
            "mower": {"status": mower.get("status"), "since": mower.get("ts"), "power_w": mower.get("power_w"), "plug": plug},
            "power": {"total_w": num(st, "sensor.smartbox_effekt_total"), "ev_w": num(st, "sensor.smartbox_effekt_elbil"), "limit_kw": cfg.get("power_limit_kw"), "peak": bool(cfg.get("peak_shaving_enabled")),
                      "solar_w": num(st, "sensor.solaredge_aktuell_effekt"), "solar_forecast_w": num(st, "sensor.smartbox_solprognos"), "saving_today": num(st, "sensor.smartbox_besparing_idag"),
                      "net_w": net_now(), "solar_limit_pct": num(st, "number.solaredge_modbus_active_power_limit"), "price_now": prices().get("now")}}


@app.post("/api/home/{what}")
async def home_action(what: str, request: Request):
    body = await request.json()
    v = body.get("value")
    logact(request, f"Hus: {what} → {v}")
    if what in ("heat", "hotwater"):
        if v not in ("auto", "on", "off"):
            raise HTTPException(400, "Ogiltigt läge")
        set_override(what, v)
        return {"ok": True, "msg": {"auto": "Auto", "on": "Tvingar PÅ", "off": "Tvingar FRÅN"}[v] + (" – värme" if what == "heat" else " – varmvatten")}
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
    if what == "mower":
        if v not in ("on", "off"):
            raise HTTPException(400, "Ogiltigt")
        st = states()
        if val(st, "switch.shelly_plug_s_gen3") is None:
            raise HTTPException(409, "Klipparens eluttag (Shelly) är offline – kolla ström och wifi")
        if v == "off" and (mower_info().get("status") == "Klipper"):
            raise HTTPException(409, "Säkerhetsspärr: klipparen klipper just nu")
        ok = H.toggle_mower_plug(v == "on")
        if not ok:
            raise HTTPException(502, "Kunde inte slå om strömmen")
        return {"ok": True, "msg": "Klipparens ström " + ("på" if v == "on" else "av")}
    raise HTTPException(404, "Okänd åtgärd")


@app.get("/api/settings")
def get_settings():
    cfg = get_settings_row()
    return {"values": {k: cfg.get(k) for k in SETTING_RULES}, "rules": {k: list(v) for k, v in SETTING_RULES.items()}}


@app.post("/api/settings")
async def set_setting(request: Request):
    body = await request.json()
    key, v = body.get("key"), body.get("value")
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
    out = {k: {d: {"enabled": False, "time": "07:00", "soc": 100} for d in range(7)} for k in ("nissan", "tesla")}
    with ENGINE.connect() as c:
        for car, day, t, soc, en in c.execute(text("SELECT car_id, day_of_week, target_time, target_soc, enabled FROM ev_charging_schedule")):
            if car in out and 0 <= day <= 6:
                out[car][day] = {"enabled": bool(en), "time": t.strftime("%H:%M"), "soc": int(soc)}
    return out


@app.post("/api/schedule")
async def set_schedule(request: Request):
    b = await request.json()
    car, day = b.get("car"), intval(b.get("day"))
    if car not in ("nissan", "tesla") or not 0 <= day <= 6:
        raise HTTPException(400, "Ogiltigt")
    t = str(b.get("time", "07:00"))
    try:
        dt.datetime.strptime(t, "%H:%M")
    except ValueError:
        raise HTTPException(400, "Ogiltig tid")
    soc = max(20, min(100, intval(b.get("soc") or 100)))
    with ENGINE.begin() as c:
        c.execute(text("""INSERT INTO ev_charging_schedule (car_id, day_of_week, target_time, enabled, target_soc, panic_mode) VALUES (:c, :d, :t, :e, :s, FALSE)
                          ON CONFLICT (car_id, day_of_week) DO UPDATE SET target_time = EXCLUDED.target_time, enabled = EXCLUDED.enabled, target_soc = EXCLUDED.target_soc"""),
                  {"c": car, "d": day, "t": t, "e": bool(b.get("enabled")), "s": soc})
    set_override("force_ev_recalc", "true")                    # smartbox räknar om laddplanen direkt
    logact(request, f"Schema {car} dag {day}: {'på' if b.get('enabled') else 'av'} {t} {soc} %")
    return {"ok": True}


# -- Grafer ----------------------------------------------------------------------------------------------------------------
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


PREFIX = {"tesla": ("tesla_model_y",), "nissan": ("leaf", "nissan")}
GROUPS = [("Batteri & laddning", ("battery", "charg", "energy", "soc", "state_of_charge", "plugged", "range", "charge_time", "scheduled_charging", "charge_limit", "charge_port")), ("Klimat & temperatur", ("climate", "temperature", "heated", "overheat", "hvac")),
          ("Plats", ("location", "tracker", "arrival", "destination", "distance_to")), ("Lås & luckor", ("lock", "frunk", "trunk", "door", "window", "valet", "sentry", "charger_door")),
          ("Körning & däck", ("odometer", "tpms", "shift", "parking", "speed", "trip", "efficiency", "user_present", "daily", "monthly")), ("System", ("update", "polling", "asleep", "online", "last_", "data_last"))]
BUTTONS = {"tesla": {"flash": "button.tesla_model_y_flash_lights", "horn": "button.tesla_model_y_horn", "wake": "button.tesla_model_y_wake_up", "refresh": "button.tesla_model_y_force_data_update"},
           "nissan": {"flash": "button.leaf_flash_lights", "horn": "button.leaf_honk_horn", "refresh": "button.leaf_update_data", "start_charge": "button.leaf_start_charge"}}


def _group(eid: str) -> str:
    n = eid.split(".", 1)[1]
    for g, keys in GROUPS:
        if any(k in n for k in keys):
            return g
    return "Övrigt"


@app.get("/api/car/{car}/entities")
def car_entities(car: str):
    """Alla Home Assistant-entiteter för en bil, grupperade, med validering (giltigt värde + färskhet). Visas bara på begäran (Alla data); nyckeltal på första sidan kommer ur de validerade."""
    if car not in PREFIX:
        raise HTTPException(404, "Okänd bil")
    st = states()
    now = dt.datetime.now(dt.timezone.utc)
    rows = []
    for eid, s_ in st.items():
        dom, name = eid.split(".", 1)
        if dom not in ("sensor", "binary_sensor", "switch", "button", "lock", "cover", "climate", "number", "select", "device_tracker", "update") or not any(p in name for p in PREFIX[car]):
            continue
        if car == "nissan" and ("smartbox" in name or "automation" in eid):
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
    return {"car": car, "rows": rows, "valid": sum(1 for r in rows if r["valid"]), "total": len(rows), "buttons": list(BUTTONS[car])}


@app.post("/api/car/{car}/press")
async def car_press(car: str, request: Request):
    """Bilens knappar (blinka, tuta, väck, uppdatera data, start laddning i bilen). Fjärrstart/övrigt kräver inte lösenord; lås/luckor har egen spärr."""
    if car not in BUTTONS:
        raise HTTPException(404, "Okänd bil")
    which = (await request.json()).get("button")
    ent = BUTTONS[car].get(which)
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
    hrs = pr.get("hours") or []
    if pr.get("now") is not None:
        t = f"Elpriset är {pr['now']:.2f} kr/kWh ({pr.get('level') or '–'})."
        fut = [h for h in hrs if not h["now"]]
        if fut and len(hrs) >= 4:
            m = min(fut, key=lambda h: h["p"])
            i = fut.index(m)
            j = i
            while j + 1 < len(fut) and fut[j + 1]["p"] <= m["p"] + 0.08:
                j += 1
            t += f" Billigast {m['t']}–{(int(fut[j]['t']) + 1) % 24:02d} ({m['p']:.2f} kr)." if m["p"] < pr["now"] else " Det blir inte billigare de närmaste timmarna."
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
    for key in ("tesla", "nissan"):
        c = CARS[key]
        seg = plan_segments(key, num(st, c["soc"]), c["cap_kwh"])
        if seg:
            g = seg[0]
            out.append({"i": "🔌", "t": f"{c['name'].split()[0]} laddas {g['day']} {g['start']}–{g['end']}" + (f" ({g['soc0']}→{g['soc1']} %)" if g.get("soc0") is not None else "") + "."})
            break
    sol = num(st, "sensor.smartbox_solprognos")
    today = num(st, "sensor.solaredge_el_i_dag")
    ev_sun = num(st, "sensor.smartbox_elbil_solel")
    if today is not None or sol is not None:
        t = (f"Solen har gett {today:.0f} kWh idag" if today is not None else "Sol") + (f", prognos nu {sol / 1000:.1f} kW" if sol is not None else "")
        if ev_sun:
            t += f". Elbilarna har laddats {ev_sun:.0f} kWh på solel"
        out.append({"i": "☀️", "t": t + "."})
    sv = num(st, "sensor.smartbox_besparing_idag")
    if sv is not None and sv > 0.5:
        out.append({"i": "💰", "t": f"AI:n har sparat {sv:.1f} kr idag mot att köra på timpris utan styrning."})
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
    raw_lim = val(st, "number.solaredge_modbus_active_power_limit")
    return {"ok": True,
            "solar": {"w": num(st, "sensor.solaredge_aktuell_effekt"), "today_kwh": num(st, "sensor.solaredge_el_i_dag"), "forecast_w": num(st, "sensor.smartbox_solprognos"), "status": SE_STATUS.get(val(st, "sensor.solaredge_i1_status"), val(st, "sensor.solaredge_i1_status")),
                      "limit_pct": None if raw_lim is None else num(st, "number.solaredge_modbus_active_power_limit"), "ai_limit": str(ov.get("ai_solar_limit_active", "false")).lower() == "true",
                      "export_price_floor": float(ov.get("solar_export_price_limit", -1.0) or -1.0), "notify": str(ov.get("notify_solar_limit", "true")).lower() == "true"},
            "grid": {"net_w": net_now(), "price": pr.get("now"), "level": pr.get("level")},
            "peaks": month_peaks(), "today_kwh": num(st, "sensor.smartbox_forbrukning_idag"), "saving_today": num(st, "sensor.smartbox_besparing_idag"), "decision": val(st, "sensor.smartbox_beslut"),
            "solar_ev_kwh": num(st, "sensor.smartbox_elbil_solel"), "insights": safe_insights(st, ov, pr), "log": val(st, "sensor.smartbox_beslut")}


@app.post("/api/energy/{what}")
async def energy_action(what: str, request: Request):
    v = (await request.json()).get("value")
    logact(request, f"Energi: {what} → {v}")
    if what == "limit":
        pct = max(0, min(100, intval(v)))
        if str(overrides().get("ai_solar_limit_active", "false")).lower() == "true":
            raise HTTPException(409, "AI:n styr exportbegränsningen just nu (minuspris) – manuell ändring är spärrad")
        if not H.set_solaredge_limit(pct):
            raise HTTPException(502, "SolarEdge svarade inte")
        return {"ok": True, "msg": f"SolarEdge-gräns satt till {pct} %"}
    if what == "floor":
        f = round(max(-1.0, min(5.0, float(v))), 2)
        set_override("solar_export_price_limit", str(f))
        return {"ok": True, "msg": f"Begränsar export under {f:.2f} kr/kWh"}
    if what == "notify":
        set_override("notify_solar_limit", "true" if v else "false")
        return {"ok": True, "msg": "Avisering " + ("på" if v else "av")}
    raise HTTPException(404, "Okänd åtgärd")


ROOMS = [("temp_vardagsrum", "Vardagsrum"), ("temp_masterbedroom", "Sovrum"), ("temp_barnrum_nere", "Barnrum nere"), ("temp_cesars_rum", "Cesars rum"), ("temp_isacs_rum", "Isacs rum"), ("temp_utbyggnad", "Utbyggnad"),
         ("temp_tvattstuga", "Tvättstuga"), ("temp_friggebod", "Friggebod"), ("temp_garage", "Garage"), ("temp_matter_1", "Sensor Matter 1"), ("temp_matter_2", "Sensor Matter 2"), ("temp_matter_3", "Sensor Matter 3"), ("temp_esp", "ESP-sensor")]


@app.get("/api/rooms")
def rooms():
    cols = ", ".join(c for c, _ in ROOMS)
    try:
        with ENGINE.connect() as c:
            r = c.execute(text(f"SELECT timestamp, {cols}, indoor_humidity FROM sensor_log ORDER BY timestamp DESC LIMIT 1")).first()
    except Exception:
        r = None
    if not r:
        return {"rows": [], "ts": None}
    ts = r[0]
    out = [{"name": n, "temp": None if r[i + 1] is None else round(float(r[i + 1]), 1)} for i, (_, n) in enumerate(ROOMS)]
    return {"rows": [x for x in out if x["temp"] is not None], "humidity": None if r[-1] is None else round(float(r[-1])), "ts": ts.astimezone(TZ).strftime("%H:%M")}


# -- Hälsning, väder och dagens peppord ----------------------------------------------------------------------------------------
COND = {"clear-night": "Klart", "cloudy": "Molnigt", "fog": "Dimma", "hail": "Hagel", "lightning": "Åska", "lightning-rainy": "Åska och regn", "partlycloudy": "Halvklart", "pouring": "Spöregn", "rainy": "Regn", "snowy": "Snö",
        "snowy-rainy": "Snöblandat regn", "sunny": "Soligt", "windy": "Blåsigt", "windy-variant": "Blåsigt", "exceptional": "Extremt väder"}
NAMES = {"owner": "Emil", "elin": "Elin"}
PEP_ELIN = ["Du ser fräsh ut idag.", "Din rumpa är fortfarande världsklass.", "Du är dagens finaste i hela huset.", "Ditt leende laddar batterier snabbare än 16 ampere.", "Charmig utan att anstränga sig – det är du.",
            "Jag är glad att du är min. Teslan är bara glad att du kör den.", "Idag klarar du precis allt du tar i.", "Du är sjukt snygg, bara så du vet.", "Världen är lite bättre med dig i den.", "Du har den där glöden som får solpanelerna att jobba hårdare.",
            "Någon här tänker på dig just nu. Gissa vem.", "Du är en total raket – och dessutom jättesnygg.", "Ta det lugnt, du förtjänar en mysig stund idag."]
PEP_EMIL = ["Dagens energichef har anlänt.", "Elpriset darrar när du loggar in.", "Du ser stark ut idag, chefen.", "Systemet jobbar. Du behöver bara vara du.", "Allt är under kontroll – eller så ser det i alla fall ut så.",
            "Smart hus, smartare ägare.", "Din rumpa är också fortfarande otroligt snygg.", "Du har byggt något riktigt coolt här.", "Dagens mål: ladda billigt, leva gott.", "Kilowattimmarna lyder dig."]
PROVERBS = ["Det som inte dödar dig gör dig starkare – men dyr el gör dig bara fattigare.", "Borta bra men hemma bäst.", "Den som väntar på något gott väntar ofta på billig el.", "Ordning och reda ger laddade batterier.",
            "Små steg varje dag tar en långt.", "Gör det du kan, med det du har, där du är.", "Lyckan ler mot den som laddar på natten.", "Bättre en sparad kilowattimme än tio planerade."]


COND_EN = {"clear-night": "Clear", "cloudy": "Cloudy", "fog": "Fog", "hail": "Hail", "lightning": "Thunder", "lightning-rainy": "Thunder and rain", "partlycloudy": "Partly cloudy", "pouring": "Pouring rain", "rainy": "Rain", "snowy": "Snow",
           "snowy-rainy": "Sleet", "sunny": "Sunny", "windy": "Windy", "windy-variant": "Windy", "exceptional": "Extreme weather"}
PEP_ELIN_EN = ["You look fresh today.", "Your backside is still world class.", "You are the finest one in the whole house today.", "Your smile charges batteries faster than 16 amps.", "Charming without even trying – that's you.",
               "I'm happy you're mine. The Tesla is just happy you drive it.", "Today you can handle anything you take on.", "You are seriously good looking, just so you know.", "The world is a little better with you in it.", "You have that glow that makes the solar panels work harder.",
               "Someone here is thinking of you right now. Guess who.", "You're a total rocket – and gorgeous too.", "Take it easy, you deserve a cozy moment today."]
PEP_EMIL_EN = ["Today's energy chief has arrived.", "The electricity price trembles when you log in.", "You look strong today, boss.", "The system is working. You just need to be you.", "Everything is under control – or at least it looks that way.",
               "Smart home, smarter owner.", "Your backside is also still incredibly good looking.", "You've built something really cool here.", "Today's goal: charge cheaply, live well.", "The kilowatt hours obey you."]
PROVERBS_EN = ["What doesn't kill you makes you stronger – but expensive electricity just makes you poorer.", "Away is good but home is best.", "Those who wait for something good often wait for cheap electricity.", "Order and tidiness give charged batteries.",
               "Small steps every day take you far.", "Do what you can, with what you have, where you are.", "Luck smiles on those who charge at night.", "Better one saved kilowatt hour than ten planned."]


def forecast_today(st: dict):
    try:
        r = requests.post(f"{H._BASE}/services/weather/get_forecasts?return_response", headers=H._HEADERS, json={"entity_id": "weather.malmgatan_34", "type": "daily"}, timeout=8, verify=False)
        f = r.json()["service_response"]["weather.malmgatan_34"]["forecast"][0]
        return f.get("temperature"), f.get("templow"), f.get("precipitation")
    except Exception:
        return None, None, None


@app.get("/api/greeting")
def greeting(request: Request):
    role, user = _session(request)
    if role == "owner" and request.query_params.get("as") == "family":      # ägarens förhandsvisning av Elins vy
        role, user = "family", "elin"
    elif role == "owner" and request.query_params.get("as") == "guest":
        role, user = "guest", "klanten87"
    now = dt.datetime.now(TZ)
    name = NAMES.get(user or "", ("guest" if request.query_params.get("lang") == "en" else "gäst") if role == "guest" else ("you" if request.query_params.get("lang") == "en" else "du"))
    en = request.query_params.get("lang") == "en"
    part = ("Good night" if now.hour < 5 else "Good morning" if now.hour < 10 else "Hello" if now.hour < 17 else "Good evening") if en else ("God natt" if now.hour < 5 else "God morgon" if now.hour < 10 else "Hej" if now.hour < 17 else "God kväll")
    st = states()
    w = st.get("weather.malmgatan_34") or {}
    wa = w.get("attributes", {})
    hi, lo, rain = forecast_today(st)
    bits = [(COND_EN if en else COND).get(w.get("state"), (w.get("state") or "").capitalize())]
    if wa.get("temperature") is not None:
        bits.append(f"{wa['temperature']:.0f}°" + (f" ({lo:.0f}–{hi:.0f}°)" if hi is not None and lo is not None else ""))
    if wa.get("wind_speed") is not None:
        bits.append(f"{'wind' if en else 'vind'} {wa['wind_speed'] / 3.6:.0f} m/s")
    if rain:
        bits.append(f"{'rain' if en else 'regn'} {rain:.0f} mm")
    pool = ((PEP_ELIN_EN if user == "elin" else PEP_EMIL_EN if user == "owner" else []) + PROVERBS_EN) if en else ((PEP_ELIN if user == "elin" else PEP_EMIL if user == "owner" else []) + PROVERBS)
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
    return "Emil" if u == "owner" else u.capitalize()


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
        msg = f"{str(b.get('m'))[:300]} @ {str(b.get('s'))[:120]} | {str(b.get('ua'))[:80]}"
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


# -- Ljus: fönsterlampor och godnatt (samma lampor som sovrumsknappen: trapp, balkong, Esther) ------------------------------------
WINDOWS_GROUP = "light.fonsterlampor"
UP_LIGHTS = ["light.trapp", "light.fonsterlampa_balkong", "light.fonsterlampa_esther"]


def _members(st: dict, group: str) -> list:
    return (st.get(group) or {}).get("attributes", {}).get("entity_id") or [group]


def _light_summary(st: dict, ents: list) -> dict:
    on = sum(1 for e in ents if (st.get(e) or {}).get("state") == "on")
    off = sum(1 for e in ents if (st.get(e) or {}).get("state") == "off")
    bad = [((st.get(e) or {}).get("attributes", {}).get("friendly_name") or e) for e in ents if (st.get(e) or {}).get("state") in (None, "unavailable", "unknown")]
    return {"on": on, "off": off, "total": len(ents), "offline": bad}


@app.get("/api/lights")
def lights():
    st = states()
    return {"windows": _light_summary(st, _members(st, WINDOWS_GROUP)), "up": _light_summary(st, UP_LIGHTS)}


def _lights_work(a, who_req_log):
    OFFLINE = (None, "unavailable", "unknown")
    plan = {"windows_on": (_members(states(), WINDOWS_GROUP), "turn_on", "Fönsterlampor tända"), "windows_off": (_members(states(), WINDOWS_GROUP), "turn_off", "Fönsterlampor släckta"),
            "up_on": (UP_LIGHTS, "turn_on", "Tänt uppe"), "goodnight": (UP_LIGHTS, "turn_off", "Godnatt – släckt uppe")}.get(a)
    if not plan:
        raise HTTPException(400, "Okänd åtgärd")
    ents, svc, msg = plan
    want = "on" if svc == "turn_on" else "off"
    cur = lambda e: (states().get(e) or {}).get("state")
    for attempt in range(3):                                   # Zigbee tappar ibland kommandon: kontrollera och försök igen på de som inte följt med (sista försöket en och en)
        todo = [e for e in ents if cur(e) not in (want, *OFFLINE)]
        if not todo:
            break
        try:
            for batch in ([todo] if attempt < 2 else [[e] for e in todo]):
                requests.post(f"{H._BASE}/services/light/{svc}", headers=H._HEADERS, json={"entity_id": batch}, timeout=15, verify=False).raise_for_status()
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
    if car not in ("nissan", "tesla"):
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
        if e.startswith(("light.", "switch.")) or (e.startswith(("sensor.", "binary_sensor.", "device_tracker.")) and any(k in e for k in ("easee", "leaf", "tesla_model_y", "smartbox", "spa", "nibe", "solaredge"))):
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
NOTIFY = {"emil": "mobile_app_emils_telefon", "elin": "mobile_app_iphone_134"}
_prev: dict = {"status": {}, "bad": {}}


def push(targets: list, title: str, msg: str) -> None:
    for t in targets:
        try:
            requests.post(f"{H._BASE}/services/notify/{NOTIFY[t]}", headers=H._HEADERS, json={"title": title, "message": msg}, timeout=8, verify=False).raise_for_status()
        except Exception as e:
            print(f"⚠️ push {t}: {e}", flush=True)


def watch_once():
    st = states()
    for key in ("tesla", "nissan"):
        c = CARS[key]
        cur = (val(st, c["status"]) or "unknown").lower()
        prev = _prev["status"].get(key)
        _prev["status"][key] = cur
        if prev is None:
            continue
        soc = num(st, c["soc"])
        to = ["emil", "elin"] if key == "tesla" else ["emil"]
        if prev == "charging" and cur in ("completed", "ready_to_charge"):
            push(to, f"{c['name']} är fulladdad", f"Batteri {soc:.0f} %." if soc is not None else "Laddningen är klar.")
        elif prev == "charging" and cur == "disconnected":
            push(to, f"{c['name']}: kabeln lossnade", "Laddningen avbröts – laddkabeln verkar ha kopplats ur.")
    now = time.time()
    for e in list(_members(st, WINDOWS_GROUP)) + UP_LIGHTS:
        if e == WINDOWS_GROUP:
            continue
        key = "light:" + e
        if (st.get(e) or {}).get("state") in (None, "unavailable", "unknown"):
            first = _prev["bad"].setdefault(key, now)
            if now - first > 1800 and _prev["bad"].get(key + "_sent") is None:
                _prev["bad"][key + "_sent"] = now
                push(["emil"], "EnergyWizard: lampa offline", f"{(st.get(e) or {}).get('attributes', {}).get('friendly_name', e)} har varit onåbar i över 30 minuter.")
        else:
            _prev["bad"].pop(key, None); _prev["bad"].pop(key + "_sent", None)
    for e in WATCH:
        bad = val(st, e) is None
        if bad:
            first = _prev["bad"].setdefault(e, now)
            if now - first > 900 and _prev["bad"].get(e + "_sent") is None:
                _prev["bad"][e + "_sent"] = now
                push(["emil"], "EnergyWizard: sensor saknas", f"{e} har saknat värde i över 15 minuter.")
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


def publish_plan(car: str, st: dict, ov: dict) -> tuple:
    c = CARS[car]
    soc = num(st, c["soc"])
    blocks = plan_blocks(car)
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
        state = "Planerad " + (t0.strftime("%H:%M") if t0.date() == now.date() else t0.strftime("%a %H:%M"))
    else:
        state = "Ingen plan"
    kwh = round(sum(b["kw"] * (dt.datetime.fromisoformat(b["end"]) - dt.datetime.fromisoformat(b["start"])).total_seconds() / 3600 for b in blocks), 1)
    after = None if (soc is None or not blocks or not c["cap_kwh"]) else round(min(100.0, soc + kwh * 0.9 / c["cap_kwh"] * 100.0))      # 90 % verkningsgrad, som i appens plan
    attrs = {"friendly_name": f"{c['name']} laddplan", "icon": "mdi:ev-station", "slots": blocks, "mode": mode, "charging": charging, "soc": None if soc is None else round(soc),
             "soc_after_plan": after, "planned_kwh": kwh, "source": "EnergyWizard", "updated": now.isoformat(timespec="seconds")}
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


def bridge_tick(publish: bool) -> None:
    """Ett varv: (1) om en Home Assistant-väljare ändrats av någon annan (t.ex. Familjetavlan), gör samma sak som appens knapp; (2) om appen ändrats, uppdatera väljaren; (3) publicera laddplanen."""
    ov = overrides()
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
    return FileResponse("static/sw.js", media_type="application/javascript", headers={"Service-Worker-Allowed": "/m/", "Cache-Control": "no-cache"})


@app.get("/i18n.js")
def i18n_js():
    return FileResponse("static/i18n.js", media_type="application/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/app.js")
def appjs():
    return FileResponse("static/app.js", media_type="application/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/style.css")
def css():
    return FileResponse("static/style.css", media_type="text/css", headers={"Cache-Control": "no-cache"})


@app.get("/")
def index():
    return FileResponse("static/index.html", media_type="text/html", headers={"Cache-Control": "no-cache"})
