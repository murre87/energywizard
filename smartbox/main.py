import asyncio
import time
import threading
import math
import statistics
from datetime import datetime, timedelta
import requests
import zoneinfo
import nordpool  # Hämtar elpriser från Nordpool
import pump      # Styr värmepumpen och läser dess sensorer
import logger    # Sparar logg till databas (varje minut)
import settings  # Hanterar konfigurationsinställningar
import weather   # Hämtar och cachelagrar väderprognos inkl. solprognos
import homeassistant    # Hämtar data från Home Assistant (temperaturer + Easee-laddare)
import notifier         # Skickar push-notiser till Emil
import lawnmower        # Logik för robotgräsklippare
import decisions        # Besluts- och styrlogik för pump och radiatorer
import gpm              # Global Priority Manager (Master Logic Tree)
import ha_publisher      # Publicerar härledda värden (priser, effektfördelning, COP, besparing) till HA
import health            # Sensor-/länkövervakning (varnar när en sensor tystnat, sammanfattar HA-avbrott)
import learning         # AI-modeller för temperatur och avsvalning
import mpc               # Prediktiv förvärmnings-planerare (skuggläge + veckovis självvalidering)
import os

# Tidszon för Sverige
SWE_TZ = zoneinfo.ZoneInfo("Europe/Stockholm")

EV_MIN_CHARGE_AMPS = 6
EV_MAX_CHARGE_AMPS = 20

_cached_ev_profiles = {'nissan': {}, 'tesla': {}}
_cached_ev_profiles_time = None

# Tillståndsminne för handskakning (vilken bil står var)
ev_allocations = {
    'easee_lite': None,
    'carport': None
}

# Tracker-state för GPS Hemkomst
ev_gps_state = {
    'nissan': {'prev_dist': 999.0, 'approaching': False},
    'tesla': {'prev_dist': 999.0, 'approaching': False}
}

def calc_distance(lat1, lon1, lat2, lon2):
    if None in (lat1, lon1, lat2, lon2): return 999.0
    R = 6371.0 # Jordens radie i km
    dLat = math.radians(lat2 - lat1)
    dLon = math.radians(lon2 - lon1)
    a = math.sin(dLat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dLon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def ha_toggle_switch(entity_id, turn_on=True):
    ha_ip = os.environ.get("HA_IP")
    ha_token = os.environ.get("HA_TOKEN", "").strip("\"'")
    service = "turn_on" if turn_on else "turn_off"
    url = f"https://{ha_ip}:8123/api/services/switch/{service}"
    headers = {"Authorization": f"Bearer {ha_token}", "Content-Type": "application/json"}
    try:
        requests.post(url, headers=headers, json={"entity_id": entity_id}, timeout=5, verify=False)
    except Exception as e:
        print(f"HA Switch Toggle Error: {e}")

# Initiera databaser och skriv ut startmeddelande
print("🤖 Startar Smartbox (v8.0) – ML-Optimerad (1-minutslogg, 15-min-styrning, AsyncIO)...")
logger.init_log_db()
logger.init_overrides_db()
settings.init_settings_db()
weather.init_weather_db()

# Initiera GPM Motorn och Watchdog-heartbeat
gpm_engine = gpm.GlobalPriorityManager()
last_heartbeat = datetime.now(SWE_TZ)

# ============================================================
# 🚀 UPPSTARTSKONTROLL
# ============================================================
print("🤖 Kontrollerar initialt tillstånd för värmepumpen...")
initial_pump_data = pump.read_sensors()
if initial_pump_data:
    if initial_pump_data.get("operating_mode") == 0:
        print("🚨 UPPSTARTSKONTROLL: Pumpen är i läge 0 (Av). Tvingar omedelbart till 1 (Auto)!")
        notifier.send_emil("🚨 Värmepump i läge 0!", "EnergyWizard upptäckte att pumpen var avstängd vid uppstart. Tvingar igång den till Auto.")
        pump.set_operating_mode(1)
        logger.set_override("pump_operating_mode", "auto")
    else:
        print(f"✅ UPPSTARTSKONTROLL: Pumpen är i läge {initial_pump_data.get('operating_mode')} (OK).")
else:
    print("⚠️ UPPSTARTSKONTROLL: Kunde inte läsa värmepumpen vid uppstart.")

print("🤖 Säkerställer att spabadets smartplug (Shelly) är påslagen...")
ha_toggle_switch(homeassistant.SPA_PLUG, turn_on=True)

# Tillståndsvariabler
last_minute          = None
last_quarter         = None
last_weather_update  = None
current_mode         = "EXPENSIVE"
current_decision     = "Startar..."
current_chosen_water = decisions.WATER_OFF
current_chosen_temp  = 200
indoor_temp          = None  # FIX: för-initieras så pumpen offline vid uppstart inte ger NameError
# FIX: borttagna döda variabler last_kwh, solar_water, solar_heat (skrevs aldrig om/lästes aldrig)

last_sent_temp           = None
last_sent_water          = None
last_sent_water_target   = None
last_sent_spa_target     = None
last_sent_spa_eco        = None
last_sent_operating_mode = None
last_pump_operating_mode = None

# --- NOTIS-TILLSTÅND ---
last_morning_notify_date = None
APPLIANCE_NOTIFY = ["diskmaskin", "tvattmaskin"]
APPLIANCE_ON_W   = 50
APPLIANCE_MIN_RUNTIME_MIN = 10
appliance_active_since = {}

last_price_state = "normal"
last_price_fallback_notify_date = None  # dedup: max en fallback-notis per dygn
DISK_WARN_PCT        = 80
last_disk_check_date = None
last_pump_alarm_code  = None
last_solar_error_sent = False
last_spa_reached     = True
last_ev_status       = "unknown"
last_washer_running  = True
# Säkerhetslarm för kallt inne (auto-värme kan vara avstängd i manuellt pumpläge)
INDOOR_COLD_ALERT_C  = 18.0
indoor_cold_alerted  = False
last_sent_solar_limit = None 
last_solar_notified_state = False
solar_limit_debounce_counter = 0 
last_solar_notify_time = None
# FIX: init till dagens datum så midnattsreset av spa-tvångsvärme INTE triggas direkt vid uppstart
last_midnight_reset_date = datetime.now(SWE_TZ).date()
last_spa_open_alert_time = None
spa_reboot_stage = 0
spa_offline_since = None
last_pump_zero_notify_time = None
last_peak_shaving_notify_time = None
last_valid_ha_temp_time = datetime.now(SWE_TZ)

# Senast kända batterinivå per bil. En sovande bil ger 'unknown' i HA (och HA glömmer värdet vid omstart),
# men bilen har samma nivå tills den körs/laddas. Värdet sparas i sensor_log (tesla_soc/nissan_soc + *_soc_stale)
# och läses tillbaka vid start. Används max CAR_SOC_MAX_AGE_H timmar.
CAR_SOC_MAX_AGE_H = 48
_soc_mem = {"loaded": False, "tesla": (None, None), "nissan": (None, None), "last_wake": None}   # (värde, tid för senaste LIVE-värde)
# Kalibrerad kurva: (framledning °C, pumpens el W). Medianer per framledningsintervall från 60 nätter (sol ~0),
# 1687 minuter med kompressorn på: husets last minus elbil, spa och grundlast (657 W).
_PUMP_EL_CURVE = [(25.0, 2000.0), (32.5, 2480.0), (37.5, 2655.0), (42.5, 2865.0), (50.0, 3460.0), (60.0, 4180.0)]

def _estimate_pump_el_w(forward_c):
    """Värmepumpens elförbrukning (W) när kompressorn går, uppskattad från framledningstemperaturen (mjuksensor).
    Värmepumpens Husdata-modul har ingen elmätare (register 38/39 = 0), så effekten kan inte läsas direkt.
    Interpolerar linjärt mellan kalibreringspunkterna. Medianfel ~140 W mot tidigare hårdkodade 2200 W (~450 W, bias -350 W)."""
    if forward_c is None:
        return 2700.0
    pts = _PUMP_EL_CURVE
    if forward_c <= pts[0][0]:
        return pts[0][1]
    if forward_c >= pts[-1][0]:
        return pts[-1][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= forward_c <= x1:
            return round(y0 + (y1 - y0) * (forward_c - x0) / (x1 - x0), 0)
    return 2700.0

_pv_hist = []   # de senaste minutvärdena för solproduktion (för att upptäcka fastfrusna solvärden)
_sensor_watch = health.SensorWatch(grace_min=30)   # varnar när en sensor som fungerat tystnat >30 min
_link_watch = health.LinkWatch(min_outage_min=5)   # sammanfattar HA-avbrott >5 min när HA är tillbaka
SENSOR_LABELS = {"indoor_1": "Tempsensor 1 (Zigbee)", "matter_1": "Timmerflotte 1", "matter_2": "Timmerflotte 2",
                 "matter_3": "Timmerflotte 3", "esp": "ESP-sensorn"}

def _seed_sensor_watch():
    """Läser när varje sensor senast rapporterade (databasen) så att en redan död sensor varnar direkt efter start."""
    try:
        from sqlalchemy import text as _sqltext
        from database_engine import engine as _engine
        with _engine.connect() as _c:
            for _col, _name in (("temp_matter_1", "matter_1"), ("temp_matter_2", "matter_2"), ("temp_matter_3", "matter_3"), ("temp_esp", "esp")):
                _r = _c.execute(_sqltext(f"SELECT max(timestamp) FROM sensor_log WHERE {_col} IS NOT NULL AND timestamp > now() - interval '3 days'")).fetchone()
                if _r and _r[0]:
                    _sensor_watch.seed(_name, _r[0])
    except Exception as _e:
        print(f"⚠️ Kunde inte initiera sensorövervakning: {_e}")

TESLA_WAKE_MIN_INTERVAL_H = 6   # väck en inkopplad Tesla med gammalt batterivärde högst så här ofta

def _load_last_known_soc():
    """Läser senaste LIVE-värdet (stale=0) per bil från databasen. Körs en gång efter att logger skapat kolumnerna."""
    try:
        from sqlalchemy import text as _sqltext
        from database_engine import engine as _engine
        with _engine.connect() as _c:
            for _car in ("tesla", "nissan"):
                _row = _c.execute(_sqltext(
                    f"SELECT {_car}_soc, timestamp FROM sensor_log WHERE {_car}_soc IS NOT NULL "
                    f"AND COALESCE({_car}_soc_stale, 0) = 0 ORDER BY timestamp DESC LIMIT 1")).fetchone()
                if _row and _row[0] is not None:
                    _soc_mem[_car] = (float(_row[0]), _row[1])
        _soc_mem["loaded"] = True
        print(f"🔋 Senast kända batterinivåer inlästa: Tesla {_soc_mem['tesla'][0]} %, Nissan {_soc_mem['nissan'][0]} %")
    except Exception as _e:
        print(f"⚠️ Kunde inte läsa senast kända batterinivåer: {_e}")

def _remember_soc(car, data, now_dt):
    """Ersätter saknad SOC (unknown) med senast kända värde. Returnerar True om värdet är föråldrat/ersatt."""
    if data is None:
        return False
    live = data.get("soc")
    if live is not None:
        _soc_mem[car] = (float(live), now_dt)
        return False
    val, ts = _soc_mem[car]
    if val is not None and ts is not None and (now_dt - ts) < timedelta(hours=CAR_SOC_MAX_AGE_H):
        data["soc"] = val
        return True
    return False
last_ev_plan_time = None
pump_offline_since = None
last_pump_offline_notify_time = None
last_anomaly_notify_time = None
last_spa_schedule_eval_time = None
last_away_recovery_notified = None
ha_temp_alert_sent = False
last_solar_modbus_error_notified = False
solar_modbus_offline_since = None
# FIX: väder-watchdog – räknar misslyckade SMHI-hämtningar och dedupar notisen
weather_update_fail_count = 0
weather_update_alerted = False
last_spa_ready_notify_time = None
pump_zero_read_count = 0
_cached_outdoor_avg_5d = 10.0
_cached_outdoor_avg_time = None
last_summer_switch_notify = None  # strypning av sommarläge-notiser
last_spa_safety_notify = None     # strypning av spa-säkerhetsnotiser
last_unexplained_start = None     # oförklarad last: när den började överstiga tröskeln
last_unexplained_notify = None    # strypning av oförklarad-last-notiser
last_spa_solar_boost_active = False
last_spa_boost_start_time = None
last_spa_boost_stop_time = None
spa_solar_boost_grace_counter = 0
spa_should_heat_now = False

last_sent_ev_limit_nissan = None
last_sent_ev_limit_tesla = None
last_ev_full_notified = {"nissan": False, "tesla": False}
raw_ev_schedule = settings.get_ev_schedule()
ev_schedule = {}
for car, days in raw_ev_schedule.items():
    ev_schedule[car] = {int(k): v for k, v in days.items() if str(k).isdigit()}
ev_charge_plan = None

ev_connection_state = {
    'nissan': {'connected': False, 'time': None, 'soc_start': None, 'soc_5min': None, 'charge_completed': False, 'last_status': None},
    'tesla':  {'connected': False, 'time': None, 'soc_start': None, 'soc_5min': None, 'charge_completed': False, 'last_status': None}
}

def _override_amps(val):
    """Tolka en force-amps/phases-override SÄKERT: 'auto'/'0'/tomt/icke-numeriskt → 0, annars int.
    Skyddar huvudloopen mot ValueError om dashboarden skriver en ogiltig override."""
    s = str(val).strip()
    return int(s) if s.isdigit() else 0

# --- EnergyWizard Mobil: spara laddplanen och sol-laddningens start/slut så att mobilappen kan visa dem -------------------------------
_solar_persist = {"active": None}


def _persist_ev_plan(df):
    """Sparar planerade laddslots (kW > 0) per bil i ev_plan_slots (ersätts vid varje omräkning)."""
    from database_engine import engine
    from sqlalchemy import text as _t
    rows = []
    if df is not None and len(df):
        for car in ("nissan", "tesla"):
            kc, sc, ec = f"{car}_kw", f"{car}_start_soc", f"{car}_end_soc"
            if kc not in df.columns:
                continue
            for _, r in df[df[kc] > 0.05].iterrows():
                ts = r["t_slot"]
                rows.append({"c": car, "t": ts.to_pydatetime().replace(tzinfo=None) if hasattr(ts, "to_pydatetime") else ts, "kw": float(r[kc]),
                             "s": float(r[sc]) if sc in df.columns and r[sc] == r[sc] else None, "e": float(r[ec]) if ec in df.columns and r[ec] == r[ec] else None})
    with engine.begin() as c:
        c.execute(_t("CREATE TABLE IF NOT EXISTS ev_plan_slots (car_id TEXT, t_slot TIMESTAMP, kw DOUBLE PRECISION, start_soc DOUBLE PRECISION, end_soc DOUBLE PRECISION, updated_at TIMESTAMPTZ DEFAULT NOW(), PRIMARY KEY (car_id, t_slot))"))
        c.execute(_t("DELETE FROM ev_plan_slots"))
        if rows:
            c.execute(_t("INSERT INTO ev_plan_slots (car_id, t_slot, kw, start_soc, end_soc) VALUES (:c, :t, :kw, :s, :e)"), rows)


def _persist_solar_state(active, amps, phases, now):
    """Skriver sol-laddningens läge till overrides (bara vid ändring): solar_ev_active/amps/phases/since/last_start/last_end."""
    from database_engine import engine
    from sqlalchemy import text as _t
    key = (bool(active), int(amps or 0), int(phases or 0))
    if _solar_persist.get("key") == key:
        return
    _solar_persist["key"] = key
    ts = now.strftime("%Y-%m-%d %H:%M")
    kv = {"solar_ev_active": "on" if active else "off", "solar_ev_amps": str(key[1]), "solar_ev_phases": str(key[2])}
    if active and _solar_persist.get("active") is not True:
        kv["solar_ev_last_start"] = ts
    if not active and _solar_persist.get("active") is True:
        kv["solar_ev_last_end"] = ts
    _solar_persist["active"] = bool(active)
    with engine.begin() as c:
        for k, v in kv.items():
            c.execute(_t("INSERT INTO overrides (device, mode, updated_at) VALUES (:d, :m, NOW()) ON CONFLICT (device) DO UPDATE SET mode = EXCLUDED.mode, updated_at = NOW()"), {"d": k, "m": v})


mower_state = {
    'status': 'Okänd',
    'status_candidate': None,
    'status_candidate_since': None,
    'power_off_by_weather': False,
    'power_off_since': None,
    'weather_recovery_notified': False,  # Dedup för väder-på-notisen (en per väderhändelse)
    'long_offline_notified': False,  # Dedup för 15-minuterslarmet (en notis per av-händelse)
    'failsafe_notified': False,      # Dedup för 5-min-failsafe-notisen (en per av-händelse)
    'prev_is_on': None,              # Föregående pluggstatus – för att upptäcka manuella av/på
    'last_command_power': None,      # Senaste strömkommando vi själva skickade ('on'/'off'/None)
    'low_power_since': None,         # FIX (symmetri): sätts/läses av lawnmower laddcykel-detektorn
}

# Återställ failsafe-/larmtimern över omstarter: om pluggen redan varit av en stund
# ska vi inte nollställa 5-/15-minutersklockorna bara för att processen startat om.
try:
    _mower_off_since = logger.get_mower_power_off_since()
    if _mower_off_since is not None:
        if _mower_off_since.tzinfo is None:
            _mower_off_since = _mower_off_since.replace(tzinfo=zoneinfo.ZoneInfo("UTC"))
        mower_state['power_off_since'] = _mower_off_since.astimezone(SWE_TZ)
        print(f"🤖 Återställde klipparens av-tid från DB: {mower_state['power_off_since']}")
except Exception as e:
    print(f"⚠️ Kunde inte återställa klipparens av-tid: {e}")



def _learned_departure_time(car_id, target_day, default="07:00"):
    """ML/data-förbättring #3: härled typisk avfärdstid ur den inlärda vaneprofilen
    (get_ev_habit_profile, {(veckodag,timme): sannolikhet_hemma}) i stället för fast 07:00.
    Används bara som fallback-deadline när användaren inte lagt in ett laddschema.
    Konservativ: laddar klart 1h före typisk avfärd, och faller tillbaka på `default`
    om profilen är gles/otydlig (så vi aldrig missar laddning)."""
    prof = _cached_ev_profiles.get(car_id, {})
    if not prof:
        return default
    for h in range(4, 19):  # leta morgon/dag-avfärd
        p = prof.get((target_day, h), 1.0)
        if p < 0.4:  # bilen brukar ha lämnat vid denna timme
            dep = max(0, h - 1)  # 1h säkerhetsmarginal
            return f"{dep:02d}:00"
    return default


def update_soc_tracker(car_id, car_data, charger_data, now, schedule):
    state = ev_connection_state[car_id]
    is_connected = charger_data and charger_data.get('status') not in ['disconnected', 'offline', 'error', None]
    current_status = charger_data.get('status') if charger_data else None
    
    if is_connected and not state['connected']:
        state['connected'] = True
        state['time'] = now
        state['soc_start'] = car_data.get('soc') if car_data else None
        state['soc_5min'] = None
        state['charge_completed'] = False
        print(f"🚗 {car_id.capitalize()} ansluten. SOC: {state['soc_start']}%")
        
        has_future_schedule = False
        today_weekday = now.weekday()
        for i in range(7):
            day_offset = i
            check_day = (today_weekday + day_offset) % 7
            day_schedule = schedule.get(car_id, {}).get(check_day, {})
            if day_schedule.get('enabled'):
                t_str = day_schedule.get('target_time', '07:00')
                t_hour, t_min = map(int, t_str.split(':'))
                test_dt = (now + timedelta(days=day_offset)).replace(hour=t_hour, minute=t_min, second=0, microsecond=0)
                if test_dt > now:
                    has_future_schedule = True
                    break
        
        if not has_future_schedule:
            try:
                target_day = now.weekday() if now.hour < 7 else (now.weekday() + 1) % 7
                dep_time = _learned_departure_time(car_id, target_day, default='07:00')
                settings.save_ev_schedule_day(car_id, target_day, dep_time, 100, True)
                print(f"📅 Auto-skapade nytt laddschema för {car_id.capitalize()} till kl {dep_time} (inlärd avfärd, fallback 07:00).")
            except Exception as e:
                print(f"❌ Fel vid auto-schema: {e}")
        else:
            print(f"✅ Hittade befintligt framtida schema för {car_id.capitalize()}.")

    elif not is_connected and state['connected']:
        state['connected'] = False
        state['time'], state['soc_start'], state['soc_5min'] = None, None, None
        state['charge_completed'] = False
        print(f"🚗 {car_id.capitalize()} frånkopplad.")
        gpm_engine.ev_charging_since[car_id] = None

    elif is_connected and state['time'] and (now - state['time']) > timedelta(minutes=5) and state['soc_5min'] is None:
        state['soc_5min'] = car_data.get('soc') if car_data else None
        print(f"🚗 {car_id.capitalize()} SOC efter 5 min: {state['soc_5min']}%")

    if state['charge_completed'] and car_data:
        soc = car_data.get("soc")
        if soc is not None and soc < 95:
            state['charge_completed'] = False
            print(f"🚗 {car_id.capitalize()} SOC sjönk till {soc}%. Återställer laddningsstatus.")

    if state['last_status'] == 'charging' and current_status != 'charging' and is_connected:
        last_sent_limit_for_car = last_sent_ev_limit_nissan if car_id == 'nissan' else last_sent_ev_limit_tesla
        if last_sent_limit_for_car is None or last_sent_limit_for_car > 0:
             soc = car_data.get("soc") if car_data else 0
             if soc is not None and soc >= 98:
                 state['charge_completed'] = True
                 print(f"🚗 {car_id.capitalize()} avslutade laddningen själv (SOC: {soc}%). Antar fulladdad.")
                 if not last_ev_full_notified.get(car_id, False) and logger.get_override("notify_ev_full") != "false":
                    notifier.notify_ev_full(car_id.capitalize(), soc)
                    last_ev_full_notified[car_id] = True

    state['last_status'] = current_status

fast_net  = []
fast_hl1, fast_hl2, fast_hl3 = [], [], []

def get_last_legionella(target_temp):
    try:
        with logger.get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT MAX(timestamp) FROM sensor_log WHERE water_temp >= %s", (target_temp - 0.5,))
                row = cur.fetchone()
        if row and row[0]:
            return row[0].replace(tzinfo=zoneinfo.ZoneInfo("UTC")).astimezone(SWE_TZ) if row[0].tzinfo is None else row[0].astimezone(SWE_TZ)
    except Exception as e:
        print(f"Kunde inte hämta legionellahistorik: {e}")
    return None

while True:
    try:
        now = datetime.now(SWE_TZ)
        current_minute = now.minute
        current_quarter = now.minute // 15

        # ============================================================
        # 🏃 SNABB TASK – var 10:e sekund
        # ============================================================
        homeassistant.update_states()

        tibber = homeassistant.read_tibber_data()
        if tibber is not None:
            fast_net.append(tibber["net_power_w"])
            fast_hl1.append(tibber["l1_a"])
            fast_hl2.append(tibber["l2_a"])
            fast_hl3.append(tibber["l3_a"])

        # ============================================================
        # 📝 1-MINUTS-TASK – Samla och Spara data
        # ============================================================
        if current_minute != last_minute:
            cfg = settings.get_settings()
            all_overrides = logger.get_all_overrides()
            ai_thoughts = []
            
            def should_notify(key, default=True):
                val = all_overrides.get(key, "auto")
                if val == "auto": return default
                return val != "false"

            # --- OMLADDNINGSKNAPP ---
            force_ev_plan_recalc = False
            if all_overrides.get("force_ev_recalc") == "true":
                gpm_engine.ev_charging_since = {}
                force_ev_plan_recalc = True
                logger.set_override("force_ev_recalc", "false")
                print("🔄 Manuell omladdning (Tvingad av användare). Bygger om schemat!")

            # --- SÄKERSTÄLL TVÅNGSVÄRME (Midnattsreset) ---
            try:
                with logger.get_db() as conn_main, conn_main.cursor() as cur_main:
                    cur_main.execute("SELECT spa_force_heat FROM system_settings WHERE id = 1")
                    row = cur_main.fetchone()
                    if row:
                        is_force = bool(row[0])
                        # FIX: spegla alltid DB-värdet först så cfg inte ärver gammalt get_settings()-värde
                        cfg["spa_force_heat"] = is_force
                        # FIX: nollställ tvångsvärmen en gång per dygn baserat på datum istället för exakt 23:59,
                        # så återställningen inte missas om minut 59 hoppas över (tung iteration/omstart).
                        if last_midnight_reset_date != now.date():
                            last_midnight_reset_date = now.date()
                            if is_force:
                                cur_main.execute("UPDATE system_settings SET spa_force_heat = FALSE WHERE id = 1")
                                conn_main.commit()
                                cfg["spa_force_heat"] = False
                                print("🌙 Midnattsåterställning: Stänger av spabadets Tvångsvärme för det nya dygnet.")
            except Exception as e:
                print(f"❌ Kunde inte läsa spa_force_heat från databasen: {e}")

            raw_ev_schedule = settings.get_ev_schedule()
            ev_schedule = {car: {int(k): v for k, v in days.items() if str(k).isdigit()} for car, days in raw_ev_schedule.items()}

            # Uppdatera väderprognos var 4:e timme
            if last_weather_update is None or (now.hour % 4 == 0 and last_weather_update != now.hour):
                # FIX: fånga returvärdet och larma vid upprepade misslyckanden (likt SolarEdge/pump-offline)
                weather_ok = False
                try:
                    weather_ok = asyncio.run(asyncio.to_thread(weather.update_forecast))
                except Exception as e:
                    print(f"❌ Fel vid väderuppdatering: {e}")
                last_weather_update = now.hour
                if weather_ok:
                    if weather_update_alerted:
                        notifier.send_emil("✅ Väderprognos Online", "SMHI-prognosen uppdateras igen.")
                    weather_update_fail_count = 0
                    weather_update_alerted = False
                else:
                    weather_update_fail_count += 1
                    # Två misslyckade försök i rad = prognosen ~8h gammal → larma en gång (dedup)
                    if weather_update_fail_count >= 2 and not weather_update_alerted:
                        notifier.send_emil("⚠️ Väderprognos Offline", "Kunde inte hämta SMHI-prognosen vid upprepade försök. Sol-/värmeoptimering kan vara baserad på gammal data.")
                        weather_update_alerted = True

            # Solcellsgräns Watchdog
            raw_solar_limit = homeassistant.get_solaredge_limit()
            if raw_solar_limit is None:
                current_solar_limit_pct = 100.0
                if solar_modbus_offline_since is None:
                    solar_modbus_offline_since = now
                elif (now - solar_modbus_offline_since) > timedelta(minutes=10) and not last_solar_modbus_error_notified:
                    notifier.send_emil("⚠️ SolarEdge Limit Offline", "Kunde inte nå SolarEdge via Modbus. Antar 100% produktion.")
                    last_solar_modbus_error_notified = True
            else:
                current_solar_limit_pct = raw_solar_limit
                solar_modbus_offline_since = None
                last_solar_modbus_error_notified = False

            nissan_data = homeassistant.read_nissan_data()
            tesla_data  = homeassistant.read_tesla_data()
            if not _soc_mem["loaded"]:
                _load_last_known_soc()
                ha_publisher.start()   # startar bakgrundstråden en gång
                _seed_sensor_watch()
            nissan_soc_stale = _remember_soc("nissan", nissan_data, now)
            tesla_soc_stale  = _remember_soc("tesla", tesla_data, now)
            nissan_soc = nissan_data.get("soc") if nissan_data else None
            tesla_soc = tesla_data.get("soc") if tesla_data else None

            if _cached_ev_profiles_time is None or (now - _cached_ev_profiles_time) > timedelta(hours=6):
                _cached_ev_profiles['nissan'] = learning.get_ev_habit_profile('nissan')
                _cached_ev_profiles['tesla'] = learning.get_ev_habit_profile('tesla')
                _cached_ev_profiles_time = now

            if _cached_outdoor_avg_time is None or (now - _cached_outdoor_avg_time) > timedelta(hours=4):
                _cached_outdoor_avg_5d = logger.get_outdoor_temp_avg_5d() or 10.0
                _cached_outdoor_avg_time = now

            p_peaks = logger.get_monthly_power_peaks()

            # Beräkna minutsnitt
            avg_net = round(sum(fast_net)  / len(fast_net),  1) if fast_net  else 0.0
            avg_hl1 = round(sum(fast_hl1) / len(fast_hl1), 1) if fast_hl1 else None
            avg_hl2 = round(sum(fast_hl2) / len(fast_hl2), 1) if fast_hl2 else None
            avg_hl3 = round(sum(fast_hl3) / len(fast_hl3), 1) if fast_hl3 else None
            fast_net.clear(); fast_hl1.clear(); fast_hl2.clear(); fast_hl3.clear()

            consumed_kwh = 0.0
            current_kwh = None

            # Asynkron inhämtning av pump och pris
            async def fetch_heavy_data():
                return await asyncio.gather(
                    asyncio.to_thread(pump.read_sensors),
                    asyncio.to_thread(nordpool.get_price_info, cfg["cheap_hours_count"])
                )
            pump_data, price_tuple = asyncio.run(fetch_heavy_data())
            current_price, dynamic_limit, strategy, all_prices = price_tuple

            # Notis (deduppad per dygn) om vi kör på gårdagens prisprofil pga prisbortfall
            if strategy and strategy.get("price_fallback") and last_price_fallback_notify_date != now.date():
                if should_notify("notify_price_tip", True):
                    notifier.alert_price_fallback()
                last_price_fallback_notify_date = now.date()

            next_quarter_time = now + timedelta(minutes=15)
            next_price = nordpool.get_price_at(next_quarter_time)

            # Husdata Watchdog
            if pump_data is None:
                if pump_offline_since is None:
                    pump_offline_since = now
                elif (now - pump_offline_since).total_seconds() >= 60:
                    if last_pump_offline_notify_time is None or (now - last_pump_offline_notify_time) > timedelta(hours=2):
                        notifier.alert_offline("Husdata / Värmepump")
                        last_pump_offline_notify_time = now
            else:
                if pump_offline_since is not None:
                    if last_pump_offline_notify_time is not None:
                        notifier.send_emil("✅ Husdata Online", "Anslutningen till värmepumpen via Husdata har återupprättats!")
                    pump_offline_since = None
                    last_pump_offline_notify_time = None

            cloud_cover, wind_speed, wind_dir, forecast_temp = weather.get_current_weather()
            solar_now, solar_next = weather.get_solar_forecast_now_and_next()

            # Byt ut statisk solprognos mot ML-Tvillingen
            solar_profile = learning.get_solar_profile()
            if solar_profile:
                roof_max_now = solar_profile.get((now.month, now.hour))
                if roof_max_now is not None:
                    solar_now = max(0.0, roof_max_now * (1.0 - (cloud_cover / 100.0) * 0.85))
                next_dt = now + timedelta(minutes=15)
                roof_max_next = solar_profile.get((next_dt.month, next_dt.hour))
                if roof_max_next is not None:
                    solar_next = max(0.0, roof_max_next * (1.0 - (cloud_cover / 100.0) * 0.85))
            
            solar_data   = homeassistant.read_solaredge()
            ha_temps     = homeassistant.read_temperatures()
            ev_lite_data = homeassistant.read_easee_lite()
            ev_carport_data = homeassistant.read_easee_carport()
            gecko_data   = homeassistant.read_gecko()
            spa_power_data = homeassistant.read_spa_power()
            spa_power_w  = spa_power_data.get('total_w')
            # Spa-säkerhet: larma (strypt 1/timme) om skyddssensorerna slår till.
            _spa_faults = [k for k in ('overcurrent', 'overvoltage', 'overheated', 'power_exceeded')
                           if spa_power_data.get(k)]
            if _spa_faults and (last_spa_safety_notify is None or (now - last_spa_safety_notify) > timedelta(hours=1)):
                _fmap = {'overcurrent': 'överström', 'overvoltage': 'överspänning',
                         'overheated': 'överhettning', 'power_exceeded': 'effekt överskriden'}
                notifier.send_emil("🛁⚠️ Spabad-säkerhet",
                                   f"Spabadets skyddssensor(er) har löst ut: {', '.join(_fmap[f] for f in _spa_faults)}.")
                last_spa_safety_notify = now
            miele_data   = homeassistant.read_miele()
            mower_data   = homeassistant.read_mower_data()
            trackers     = homeassistant.read_ev_trackers()

            # ============================================================
            # 🤖 ROBOTGRÄSKLIPPARE – Status, säkerhet & väderstyrning
            # ============================================================
            if mower_data is not None:
                try:
                    mower_power_w = mower_data.get("power_w")
                    mower_is_on   = bool(mower_data.get("is_on"))

                    # Väderstyrning kan slås av/på i dashboarden (override 'mower_weather_control').
                    # Är den av matar vi in "inget oväder", så väderregeln aldrig stänger av – och
                    # en plugg som redan stängts av p.g.a. väder slås på igen nästa varv.
                    if all_overrides.get("mower_weather_control", "auto") != "false":
                        mower_raining, mower_thunder = weather.get_mower_weather_block(now)
                    else:
                        mower_raining, mower_thunder = False, False
                    # Separat regnreglage ('mower_rain_control'): av = regn ignoreras, åska styrs fortfarande av väderstyrningen.
                    if all_overrides.get("mower_rain_control", "auto") == "false":
                        mower_raining = False

                    new_mower_state, mower_actions = lawnmower.update_status_and_decide_action(
                        mower_state, mower_power_w, mower_is_on,
                        mower_raining, mower_thunder, cfg, now
                    )
                    mower_state.update(new_mower_state)

                    # Gör statusen tillgänglig för minutloggen (sensor_log) → dashboarden
                    mower_data["status"] = mower_state["status"]

                    # --- Manuell av/på-detektering (förändring vi inte själva beordrade) ---
                    prev_is_on = mower_state.get("prev_is_on")
                    last_cmd   = mower_state.get("last_command_power")
                    if prev_is_on is not None and mower_is_on != prev_is_on:
                        changed_to = "on" if mower_is_on else "off"
                        if last_cmd != changed_to:  # inte vårt eget kommando → manuellt/externt
                            if should_notify("notify_mower_manual", True):
                                notifier.notify_mower_manual_toggle(mower_is_on)

                    # --- Statusbyte-notiser (max 1 per händelse, styrs av växlar) ---
                    new_status = mower_actions.get("new_lawnmower_status")
                    status_notify_keys = {
                        "Klipper": ("notify_mower_mowing", True),
                        "Laddar":  ("notify_mower_charging", True),
                        "Vilar":   ("notify_mower_idle", False),  # "Vilar" är av som standard (matchar dashboarden)
                    }
                    if new_status in status_notify_keys:
                        _key, _default = status_notify_keys[new_status]
                        if should_notify(_key, _default):
                            notifier.notify_mower_status_change(new_status, mower_power_w or 0.0)

                    # --- Väderstyrning slog av/på strömmen ---
                    if mower_actions.get("notify_weather_off") and should_notify("notify_mower_weather", True):
                        notifier.notify_mower_weather_change(False)
                    if mower_actions.get("notify_weather_on") and should_notify("notify_mower_weather", True):
                        notifier.notify_mower_weather_change(True)

                    # --- 5-minuters failsafe slog på strömmen igen (bara en notis per av-händelse) ---
                    if mower_actions.get("notify_failsafe_on") and not mower_state.get("failsafe_notified"):
                        if should_notify("notify_mower_failsafe", True):
                            notifier.notify_mower_failsafe_reboot()
                        mower_state["failsafe_notified"] = True

                    # --- 15-minuterslarm: skickas ALLTID, men bara en gång per av-händelse ---
                    if mower_actions.get("notify_long_offline"):
                        if not mower_state.get("long_offline_notified"):
                            notifier.notify_mower_long_offline()
                            mower_state["long_offline_notified"] = True
                    if mower_is_on:
                        mower_state["long_offline_notified"] = False
                        mower_state["failsafe_notified"] = False

                    # --- Verkställ strömkommando (absolut förbud mot avstängning under
                    #     "Klipper" är redan inbakat i lawnmower.update_status_and_decide_action) ---
                    cmd = mower_actions.get("power")
                    toggle_ok = True
                    if cmd == "off":
                        toggle_ok = homeassistant.toggle_mower_plug(False)
                    elif cmd == "on":
                        toggle_ok = homeassistant.toggle_mower_plug(True)

                    # Spara tillstånd inför nästa varv (för manuell-detekteringen). Registrera
                    # bara kommandot om det faktiskt gick fram – annars skulle ett misslyckat
                    # kommando dölja en efterföljande manuell omkoppling i samma riktning.
                    mower_state["last_command_power"] = cmd if (cmd and toggle_ok) else None
                    mower_state["prev_is_on"]         = mower_is_on

                    # Logga till klipparens egen historik-tabell
                    logger.log_mower_status(mower_state["status"], mower_power_w, mower_is_on)
                except Exception as e:
                    print(f"🔥 Fel i gräsklipparlogiken: {e}")

            # Spabad Watchdog
            if gecko_data is None or gecko_data.get("current_temp") is None:
                if spa_offline_since is None:
                    spa_offline_since = now
                    print("📡 Spabad verkar offline. Startar 15-minuters timer för återstart...")
                elif (now - spa_offline_since) >= timedelta(minutes=15):
                    print("📡 Spabad offline > 15 min. Initierar omstart av smartpluggen!")
                    spa_offline_since = now 
                    if spa_reboot_stage == 0:
                        notifier.send_emil("📡 Spabad frånkopplat", "Spabadet har tappat anslutningen i över 15 minuter. Påbörjar automatisk återstart.")
                    elif spa_reboot_stage == 2:
                        notifier.send_emil("🚨 Spabad Offline", "Kunde fortfarande inte återställa kontakten med spabadet efter flera omstarter.")
                    spa_reboot_stage += 1
                    
                    def reboot_plug_async():
                        ha_toggle_switch(homeassistant.SPA_PLUG, turn_on=False)
                        time.sleep(10)
                        ha_toggle_switch(homeassistant.SPA_PLUG, turn_on=True)
                    threading.Thread(target=reboot_plug_async).start()
            else:
                if spa_offline_since is not None:
                    print("✅ Spabad online igen! Nollställer återstartsekvensen.")
                    if spa_reboot_stage > 0 and all_overrides.get("notify_spa_reconnect", "auto") != "false":
                        notifier.send_emil("✅ Spabad återanslutet", "Anslutningen till spabadet har återupprättats efter omstart!")
                    spa_offline_since = None
                    spa_reboot_stage = 0

            # Handshake och Bilallokering
            lite_status = ev_lite_data.get("status") if ev_lite_data else "offline"
            carport_status = ev_carport_data.get("status") if ev_carport_data else "offline"
            lite_conn = lite_status not in ['disconnected', 'offline', 'unknown', 'none', None, '']
            carport_conn = carport_status not in ['disconnected', 'offline', 'unknown', 'none', None, '']
            
            if not lite_conn: ev_allocations['easee_lite'] = None
            if not carport_conn: ev_allocations['carport'] = None

            # FIX: borttagen DÖD logik – read_nissan_data/read_tesla_data returnerar ALLTID en dict,
            # så villkoret (not nissan_data or not tesla_data) kunde aldrig bli True. EV-styrningen
            # körs alltid; saknad bildata (SOC=None m.m.) hanteras direkt i EV-logiken nedan.
            handshake_error = False

            t_plug = tesla_data.get("plugged_in") if tesla_data else 0
            t_state = str(tesla_data.get("charging_state")).lower() if tesla_data else ""
            # FIX: Teslans charging_state är platsoberoende (sant även vid supercharger borta) →
            # grinda plugged på GPS-hemma så en bil som laddar BORTA inte snor en hemma-laddare och
            # blockerar den andra bilens anslutning (och därmed dess schema-justering). GPS EXKLUDERAR
            # bara när den säkert säger borta; saknas GPS-koordinater litar vi på plugg-sensorn.
            def _gps_home_or_unknown(lat, lon):
                if lat is None or lon is None:
                    return True
                return calc_distance(weather.LATITUDE, weather.LONGITUDE, lat, lon) <= 0.5
            _t_home = _gps_home_or_unknown(trackers.get('tesla_lat'), trackers.get('tesla_lon'))
            _n_home = _gps_home_or_unknown(trackers.get('nissan_lat'), trackers.get('nissan_lon'))
            # FIX: Inkopplad i hemma-Easee ⟹ hemma, oavsett (stale) GPS. lite_conn/carport_conn =
            # kabel sitter i den fysiska hemma-laddaren (easee_lite=Nissan, carport=Tesla).
            _tesla_cable  = (t_plug == 1.0) or (t_state in ['charging', 'stopped', 'complete']) or (carport_conn and _t_home and trackers.get('tesla_lat') is not None)
            # 2026-10-15: bilintegrationerna har inga kabelsensorer längre → upptagen hemma-laddare + bilens GPS hemma = kabel i (annars blev Nissans laddare 'guest')
            _nissan_cable = (nissan_data.get("plugged_in") == 1.0 if nissan_data else False) or (lite_conn and _n_home and trackers.get('nissan_lat') is not None)
            tesla_plugged  = _tesla_cable  and (_t_home or carport_conn)
            nissan_plugged = _nissan_cable and (_n_home or lite_conn)

            if lite_conn and ev_allocations['easee_lite'] is None:
                if nissan_plugged and ev_allocations['carport'] != 'nissan':
                    ev_allocations['easee_lite'] = 'nissan'
                elif tesla_plugged and ev_allocations['carport'] != 'tesla':
                    ev_allocations['easee_lite'] = 'tesla'
                else:
                    ev_allocations['easee_lite'] = 'guest'
                    
            if carport_conn and ev_allocations['carport'] is None:
                if tesla_plugged and ev_allocations['easee_lite'] != 'tesla':
                    ev_allocations['carport'] = 'tesla'
                elif nissan_plugged and ev_allocations['easee_lite'] != 'nissan':
                    ev_allocations['carport'] = 'nissan'
                else:
                    ev_allocations['carport'] = 'guest'

            nissan_charger_id = homeassistant.EASEE_LITE_ID
            nissan_charger_data = ev_lite_data
            tesla_charger_id = homeassistant.EASEE_CARPORT_ID
            tesla_charger_data = ev_carport_data
            
            if not handshake_error:
                if ev_allocations['easee_lite'] == 'tesla':
                    tesla_charger_id = homeassistant.EASEE_LITE_ID
                    tesla_charger_data = ev_lite_data
                elif ev_allocations['easee_lite'] == 'nissan':
                    nissan_charger_id = homeassistant.EASEE_LITE_ID
                    nissan_charger_data = ev_lite_data
                    
                if ev_allocations['carport'] == 'nissan':
                    nissan_charger_id = homeassistant.EASEE_CARPORT_ID
                    nissan_charger_data = ev_carport_data
                elif ev_allocations['carport'] == 'tesla':
                    tesla_charger_id = homeassistant.EASEE_CARPORT_ID
                    tesla_charger_data = ev_carport_data
                    
                if ev_allocations['easee_lite'] == 'tesla' or ev_allocations['carport'] == 'nissan':
                    ai_thoughts.append("🔄 Handskakning aktiv: Bilarna har bytt laddplats med varandra! GPM styr rätt box.")
            elif (lite_conn or carport_conn):
                ai_thoughts.append("⚠️ Handskakning misslyckades: Bilarnas API-data saknas. Antar standard-parkering.")

            update_soc_tracker('nissan', nissan_data, nissan_charger_data, now, ev_schedule)
            update_soc_tracker('tesla', tesla_data, tesla_charger_data, now, ev_schedule)

            # Smart Hemkomst GPS
            for car in ['nissan', 'tesla']:
                lat = trackers.get(f'{car}_lat')
                lon = trackers.get(f'{car}_lon')
                dist = calc_distance(weather.LATITUDE, weather.LONGITUDE, lat, lon)
                
                if 0.5 < dist < 15.0 and dist < ev_gps_state[car]['prev_dist'] - 0.2:
                    if not ev_gps_state[car]['approaching']:
                        ev_gps_state[car]['approaching'] = True
                        print(f"📍 GPS: {car.capitalize()} närmar sig hemmet! (Avstånd: {dist:.1f} km). Förallokerar.")
                        force_ev_plan_recalc = True
                elif dist <= 0.5 or dist >= 15.0 or ev_connection_state[car]['connected']:
                    ev_gps_state[car]['approaching'] = False
                    
                ev_gps_state[car]['prev_dist'] = dist
                
                if ev_gps_state[car]['approaching']:
                    ai_thoughts.append(f"📍 GPS: {car.capitalize()} närmar sig hemmet ({dist:.1f} km bort). För-allokerar.")

            # Solinstrålning vs Prognos (CSI)
            # ROBUSTHET: SolarEdge-pv:n (solaredge_aktuell_effekt) fastnar ibland på stale värden
            # (t.ex. 5876 W minuter i rad) medan huset exporterar mer än så. Produktionen kan ALDRIG
            # vara mindre än nätexporten (fysik). Korrigera pv uppåt till minst exporten → räddar
            # house_consumption_w OCH den loggade pv:n (Ekonomi-sol-siffror). net från Tibber (U×I) är pålitlig.
            if solar_data is not None:
                _raw_pv = solar_data.get('pv_power_w') or 0
                _grid_export_w = max(0.0, -avg_net)
                if _raw_pv < _grid_export_w:
                    solar_data['pv_power_w'] = _grid_export_w
            solar_prod_w = (solar_data.get('pv_power_w') or 0) if solar_data else 0  # pv kan vara None → 0
            solar_is_shaky = False
            
            clear_sky_w = solar_profile.get((now.month, now.hour)) if solar_profile else None
            if clear_sky_w is None:
                clear_sky_w = weather.estimate_solar_w(0.0, now)
            
            if clear_sky_w > 1000:
                csi = solar_prod_w / clear_sky_w
                expected_csi = 1.0 - (cloud_cover / 100.0) * 0.85
                
                if abs(csi - expected_csi) > 0.30:
                    if last_ev_plan_time is None or (now - last_ev_plan_time) > timedelta(minutes=15):
                        force_ev_plan_recalc = True
                        print(f"☀️ Clear Sky Index Avvikelse! CSI={csi:.2f}, Prognos={expected_csi:.2f}. Tvingar omladdning.")
                
                try:
                    with logger.get_db() as conn_main, conn_main.cursor() as cur_main:
                        cur_main.execute("SELECT MAX(pv_power_w), MIN(pv_power_w) FROM sensor_log WHERE timestamp >= NOW() - INTERVAL '15 minutes'")
                        row = cur_main.fetchone()
                        if row and row[0] is not None and row[1] is not None:
                            solar_diff = row[0] - row[1]
                            if solar_diff > max(clear_sky_w * 0.35, 1500.0):
                                solar_is_shaky = True
                        if solar_prod_w >= 5000.0:
                            solar_is_shaky = False
                except Exception as e:
                    print(f"❌ Fel vid CSI-varians-koll: {e}")

            # EV Plan
            if ev_charge_plan is None or now.minute % 15 == 0 or force_ev_plan_recalc:
                last_ev_plan_time = now
                print("🧠 Beräknar ny EV-laddningsplan...")
                car_data_for_plan = {
                    "nissan_soc": nissan_soc,
                    "tesla_soc": tesla_soc,
                    "nissan_phases": nissan_charger_data.get('phases') if nissan_charger_data else None,
                    "tesla_phases": tesla_charger_data.get('phases') if tesla_charger_data else None,
                    "nissan_plugged_in": ev_connection_state['nissan']['connected'] or ev_gps_state['nissan']['approaching'],
                    "tesla_plugged_in": ev_connection_state['tesla']['connected'] or ev_gps_state['tesla']['approaching'],
                }
                ev_charge_plan = decisions.calculate_ev_charge_plan(now, ev_schedule, car_data_for_plan, cfg)
                try:
                    _persist_ev_plan(ev_charge_plan)
                except Exception as _e:
                    print(f"⚠️ Kunde inte spara laddplanen: {_e}")

            # Klimatschema Bil
            outdoor_temp_for_climate = pump_data.get("outdoor_temp") if pump_data else (forecast_temp or 10.0)
            climate_schedules = settings.get_climate_schedule()
            away_mode_enabled = cfg.get("away_mode_enabled", False)
            away_return_date = cfg.get("away_return_date")  # FIX: saknades → NameError när bortaläge var på

            def handle_car_climate(car_id, sched, c_data, charger_data, climate_entity, outdoor_temp, dist_to_home):
                if not sched['enabled']: return
                is_connected = charger_data and charger_data.get('status') not in ['disconnected', 'offline', 'error', None]
                is_home = dist_to_home <= 0.5
                if not is_connected and not is_home: return
                if away_mode_enabled: return 
                try:
                    target_time = datetime.strptime(sched['target_time'], "%H:%M").time()
                    target_dt = datetime.combine(now.date(), target_time).replace(tzinfo=SWE_TZ)
                    if now.hour > 12 and target_dt.hour < 12: 
                        target_dt += timedelta(days=1)
                    
                    preheat_window_mins = learning.estimate_preheat_minutes(outdoor_temp)
                    mins_until = (target_dt - now).total_seconds() / 60.0
                    c_state = c_data.get("climate_state") if c_data else "off"
                    c_temp = c_data.get("climate_temp") if c_data else 0.0
                    
                    if 0 <= mins_until <= preheat_window_mins:
                        if c_state == "off" and (c_temp is None or c_temp < sched['target_temp']):
                            homeassistant.set_car_climate(climate_entity, "heat_cool", sched['target_temp'])
                        elif c_state != "off" and c_temp is not None and c_temp >= sched['target_temp']:
                            homeassistant.set_car_climate(climate_entity, "off")
                except Exception as e:
                    print(f"❌ Fel i klimatschema för {car_id}: {e}")

            n_lat = trackers.get('nissan_lat')
            n_lon = trackers.get('nissan_lon')
            n_dist = calc_distance(weather.LATITUDE, weather.LONGITUDE, n_lat, n_lon)
            handle_car_climate('nissan', climate_schedules.get('nissan', {'enabled':False}), nissan_data, nissan_charger_data, "climate.leaf_climate", outdoor_temp_for_climate, n_dist)

            # Inomhustemperatur
            pump_indoor_temp = pump_data.get("indoor_temp") if pump_data else None
            if ha_temps.get("esp") is None:
                ha_temps["esp"] = homeassistant.read_esphome_temp("192.168.1.125")
                
            # ESP-sensorn mäter ~0.6°C högre än husets medel (uppmätt mot Zigbee-sensorn t.o.m. 16 sep).
            # Är Zigbee-sensorn borta består medelvärdet bara av ESP -> korrigera så att Prio 5
            # inte felaktigt tror att det är för varmt inne.
            esp_temp = ha_temps.get("esp")
            if esp_temp is not None and ha_temps.get("indoor_1") is None:
                esp_temp -= 0.6

            sensor_values = [
                ha_temps.get("indoor_1"),
                ha_temps.get("matter_1"),
                ha_temps.get("matter_2"),
                ha_temps.get("matter_3"),
                esp_temp,
            ]
            
            temps_to_avg = [t for t in sensor_values if t is not None and isinstance(t, (int, float)) and t > 0]

            # Luftfuktighet: median (>=3 sensorer) annars medel; sparas i ha_temps så loggern tar med den.
            ha_hums = homeassistant.read_humidities()
            hums = [h for h in ha_hums.values() if isinstance(h, (int, float)) and 0 < h <= 100]
            if hums:
                ha_temps["indoor_humidity"] = round(statistics.median(hums) if len(hums) >= 3 else sum(hums) / len(hums), 1)
            for _k in ("matter_1", "matter_2", "matter_3", "esp"):
                ha_temps[f"hum_{_k}"] = ha_hums.get(_k)

            # Hälsokoll: varna när en sensor tystnat, och sammanfatta HA-avbrott när HA är tillbaka.
            try:
                if homeassistant.last_update_ok:   # ingen sensorvarning medan HA själv är nere (alla värden saknas då)
                    for _kind, _sname, _age in _sensor_watch.update({k: ha_temps.get(k) for k in SENSOR_LABELS}, now):
                        _lbl = SENSOR_LABELS[_sname]
                        if _kind == "lost":
                            notifier.send_emil("📡 Sensor har tystnat", f"{_lbl} har inte rapporterat på {health.fmt_duration(_age)}. Kontrollera batteri/anslutning. Medelvärdet för inomhustemperatur använder de sensorer som fungerar.")
                        else:
                            notifier.send_emil("✅ Sensor tillbaka", f"{_lbl} rapporterar igen (borta i {health.fmt_duration(_age)}).")
                _lev = _link_watch.update(homeassistant.last_update_ok, now)
                if _lev:
                    notifier.send_emil("🔌 Home Assistant var onåbar", f"Home Assistant var borta i {health.fmt_duration(_lev[1])} (från kl {_lev[2].astimezone(SWE_TZ):%H:%M}). Under tiden kunde smartbox inte läsa sensorer eller styra bilklimat, spa och notiser via HA. Nu fungerar det igen.")
            except Exception as _he:
                print(f"⚠️ Hälsokoll misslyckades: {_he}")

            if pump_data and pump_data.get("outdoor_temp") is not None:
                last_heartbeat = now
                if temps_to_avg:
                    # Median (>=3 sensorer) tål en enskild avvikande givare (t.ex. en Timmerflotte i solen/vid värmekälla).
                    if len(temps_to_avg) >= 3:
                        indoor_temp = statistics.median(temps_to_avg)
                    else:
                        indoor_temp = sum(temps_to_avg) / len(temps_to_avg)
                    last_valid_ha_temp_time = now
                    ha_temp_alert_sent = False
                else:
                    indoor_temp = pump_indoor_temp
                    if (now - last_valid_ha_temp_time) > timedelta(minutes=15) and not ha_temp_alert_sent:
                        notifier.alert_indoor_temp_sensor_offline()
                        ha_temp_alert_sent = True

            water_temp   = pump_data.get("water_temp_top")    if pump_data else None
            forward_temp = pump_data.get("forward_temp")      if pump_data else None
            return_temp  = pump_data.get("return_temp")       if pump_data else None
            calc_forward = pump_data.get("calc_forward_temp") if pump_data else None
            pump_operating_mode_from_pump = pump_data.get("operating_mode") if pump_data else None

            # ── SOMMARLÄGE-kontext (styr failsafe-återhämtning + växling nedan) ──────────
            # Strategi väljs på pumpens dashboard (override "summer_mode_strategy"):
            #   "hot_water" (default) = växla pumpen till Endast varmvatten (läge 4) på sommaren
            #   "heat_stop"           = behåll Auto men sänk Thermias värmestopp (reg 19)
            #   "off"                 = rör inget (manuellt läge)
            # is_summer via pumpens EGEN värmestopp-tröskel (samverkar med Thermia).
            summer_strategy = all_overrides.get("summer_mode_strategy", "hot_water")
            _heat_stop_reg  = pump_data.get('heat_stop_outdoor') if pump_data else None
            _summer_thr     = _heat_stop_reg if (_heat_stop_reg is not None and _heat_stop_reg > 0) else 14.0
            is_summer_now   = (_cached_outdoor_avg_5d is not None) and (_cached_outdoor_avg_5d >= _summer_thr)
            # Vid läge 0-failsafe: återställ till sommar-läget (4) om strategi A + sommar, annars Auto (1).
            _recover_mode   = 4 if (summer_strategy == "hot_water" and is_summer_now) else 1

            if pump_operating_mode_from_pump == 0:
                pump_zero_read_count += 1
                if pump_zero_read_count >= 3:
                    if last_pump_zero_notify_time is None or (now - last_pump_zero_notify_time) > timedelta(minutes=15):
                        _rn = notifier.PUMP_MODE_MAP.get(_recover_mode, str(_recover_mode))
                        notifier.send_emil("🚨 Värmepump i läge 0!", f"EnergyWizard upptäckte att pumpen var avstängd. Tvingar igång ({_rn}).")
                        last_pump_zero_notify_time = now
                    if pump.set_operating_mode(_recover_mode):
                        pump_operating_mode_from_pump = _recover_mode
                        last_sent_operating_mode = _recover_mode
                        logger.set_override("pump_operating_mode", "auto")
            elif pump_operating_mode_from_pump is not None:
                pump_zero_read_count = 0

            # FIX: borttagna döda läsningar ov_smart/ov_pump_mode (logiken nedan använder all_overrides)
            if pump_operating_mode_from_pump is not None and last_pump_operating_mode is not None and pump_operating_mode_from_pump != last_pump_operating_mode:
                ai_thoughts.append(f"⚙️ Pumpens driftläge ändrades från '{notifier.PUMP_MODE_MAP.get(last_pump_operating_mode, 'Okänt')}' till '{notifier.PUMP_MODE_MAP.get(pump_operating_mode_from_pump, 'Okänt')}'.")
            last_pump_operating_mode = pump_operating_mode_from_pump

            # ── SOMMARLÄGE-verkställighet ────────────────────────────────────────────────
            if summer_strategy != "off" and pump_data is not None:
                # Sommarautomatiken är auktoritativ → nollställ ev. gammalt manuellt pumpläge
                # så den manuella overriden (längre ned) inte krigar mot växlingen.
                if all_overrides.get("pump_operating_mode", "auto") not in ("auto", ""):
                    logger.set_override("pump_operating_mode", "auto")
                    all_overrides["pump_operating_mode"] = "auto"

            if summer_strategy == "hot_water" and pump_operating_mode_from_pump is not None:
                # A: Sommar → Endast varmvatten (läge 4). Ej sommar → Auto (läge 1).
                _target_mode = 4 if is_summer_now else 1
                if pump_operating_mode_from_pump != _target_mode:
                    if pump.set_operating_mode(_target_mode):
                        _mn = notifier.PUMP_MODE_MAP.get(_target_mode, str(_target_mode))
                        ai_thoughts.append(f"🌞 Sommarläge: växlar pump till '{_mn}' (5-dygnsmedel ute {_cached_outdoor_avg_5d:.1f}°C, tröskel {_summer_thr:.1f}°C).")
                        pump_operating_mode_from_pump = _target_mode
                        last_sent_operating_mode = _target_mode
                        if last_summer_switch_notify is None or (now - last_summer_switch_notify) > timedelta(hours=1):
                            notifier.send_emil("🌞 Sommarläge", f"EnergyWizard växlade pumpen till '{_mn}' (5-dygnsmedel ute {_cached_outdoor_avg_5d:.1f}°C).")
                            last_summer_switch_notify = now

            elif summer_strategy == "heat_stop":
                # B: Behåll Auto men styr Thermias värmestopp (reg 19). Mindre vattentätt än A.
                _summer_stop = float(cfg.get("summer_heat_stop_c", 13.0))
                if is_summer_now:
                    if _heat_stop_reg is not None and _heat_stop_reg > _summer_stop + 0.05:
                        # Spara vinterns värde första gången vi sänker, sänk sedan tröskeln.
                        if all_overrides.get("winter_heat_stop", "auto") in ("auto", ""):
                            logger.set_override("winter_heat_stop", f"{_heat_stop_reg:.1f}")
                        if pump.set_heating_start_temp(_summer_stop):
                            ai_thoughts.append(f"🌞 Sommarläge (Auto): sänker värmestopp {_heat_stop_reg:.1f}→{_summer_stop:.1f}°C.")
                else:
                    # Höst: återställ vinterns sparade värde om vi tidigare sänkt det.
                    _saved = all_overrides.get("winter_heat_stop", "auto")
                    if _saved not in ("auto", ""):
                        try:
                            _wv = float(_saved)
                            if _heat_stop_reg is not None and abs(_heat_stop_reg - _wv) > 0.05:
                                if pump.set_heating_start_temp(_wv):
                                    ai_thoughts.append(f"❄️ Höst: återställer värmestopp till {_wv:.1f}°C.")
                        except ValueError:
                            pass
                        logger.set_override("winter_heat_stop", "auto")

            outdoor_temp = pump_data.get("outdoor_temp") if pump_data else None
            house_consumption_w = solar_prod_w + avg_net
            grid_import_w = max(0, avg_net) 
            
            pi_p_term, pi_i_term = 0.0, 0.0
            if current_chosen_temp is not None and indoor_temp is not None:
                pi_p_term = round((current_chosen_temp / 10.0) - indoor_temp, 2)
            
            leg_temp = cfg.get("legionella_temp", 60.0)
            leg_max_days = cfg.get("legionella_days", 14)
            wt_norm = cfg.get("water_target_normal", 50.0)
            last_leg = get_last_legionella(leg_temp)
            days_since_leg = (now - last_leg).total_seconds() / 86400.0 if last_leg else 999.0

            consumed_kwh_this_hour = homeassistant._get_numeric_state("sensor.tibber_pulse_malmgatan_34_ackumulerad_forbrukning_under_aktuell_timme") or 0.0
            if now.minute == 0:
                consumed_kwh_this_hour = 0.0

            is_high_load = settings.is_high_load_time(now)
            bas_limit, hog_limit = 0.0, 0.0
            old_limit = cfg.get("power_limit_kw", 0.0)
            try:
                with logger.get_db() as conn_main, conn_main.cursor() as cur_main:
                    cur_main.execute("SELECT column_name FROM information_schema.columns WHERE table_name='system_settings' AND column_name='power_limit_kw_bas'")
                    if cur_main.fetchone() is not None:
                        cur_main.execute("SELECT power_limit_kw_bas, power_limit_kw_hog FROM system_settings WHERE id = 1")
                        lim_row = cur_main.fetchone()
                        if lim_row:
                            bas_limit = float(lim_row[0] or 0.0)
                            hog_limit = float(lim_row[1] or 0.0)
            except Exception:
                pass

            if bas_limit == 0.0 and hog_limit == 0.0 and old_limit > 0:
                bas_limit, hog_limit = old_limit, old_limit
                
            power_limit_setting = hog_limit if is_high_load else bas_limit
            
            if power_limit_setting and power_limit_setting > 0:
                current_target_limit = float(power_limit_setting)
            else:
                bas_p1 = p_peaks.get('bas_p1', 0.0)
                bas_p2 = p_peaks.get('bas_p2', 0.0)
                bas_avg = (bas_p1 + bas_p2) / 2.0 if bas_p2 > 0 else bas_p1
                if bas_avg == 0: bas_avg = 10.0
                
                if is_high_load:
                    hog_p1 = p_peaks.get('hog_p1', 0.0)
                    hog_p2 = p_peaks.get('hog_p2', 0.0)
                    hog_avg = (hog_p1 + hog_p2) / 2.0 if hog_p2 > 0 else hog_p1
                    if hog_avg == 0: hog_avg = bas_avg
                    current_target_limit = hog_avg
                else:
                    current_target_limit = bas_avg

            power_limit_w = current_target_limit * 1000
            peak_shaving_active = 1 if house_consumption_w > power_limit_w else 0
            force_heating_active = 1 if cfg.get("spa_force_heat", False) else 0
            watchdog_trips = 0 
            
            spa_schedule_active = cfg.get("spa_schedule_enabled", False)
            target_dt = cfg.get("spa_target_datetime")
            
            if spa_schedule_active and target_dt and target_dt > now:
                if last_spa_schedule_eval_time is None or (now - last_spa_schedule_eval_time) > timedelta(minutes=14):
                    h_intercept, h_slope_out, h_slope_spa = learning.get_heating_rate_model()
                    cooling_k, _ = learning.get_cooling_rate_model()
                    spa_should_heat_now, _ = decisions.check_spa_schedule_plan(
                        now, target_dt, gecko_data.get("current_temp", 38.0) if gecko_data else 38.0, 
                        cfg.get("spa_target_temp", 38.0), h_intercept, h_slope_out, h_slope_spa, cooling_k, 
                        cfg.get("spa_max_temp", 40.0),
                        outdoor_temp or 0.0, cfg.get("spa_low_temp", 15.0)
                    )
                    last_spa_schedule_eval_time = now
            else:
                spa_should_heat_now = False

            solar_w_roll_3h = 0.0
            try:
                with logger.get_db() as conn_main, conn_main.cursor() as cur_main:
                    cur_main.execute("SELECT AVG(pv_power_w) FROM sensor_log WHERE timestamp >= NOW() - INTERVAL '3 hours'")
                    row = cur_main.fetchone()
                    if row and row[0] is not None:
                        solar_w_roll_3h = float(row[0])
            except Exception:
                pass

            house_model = learning.get_house_cooling_rate_model()
            predicted_cooling_rate = learning.predict_house_cooling_rate(
                outdoor_temp or 0.0, wind_speed or 2.0, solar_prod_w, solar_w_roll_3h, now.hour, house_model
            )
            expected_energy_wh = house_consumption_w * 1.0
            
            # --- BORTALÄGE ---
            away_recovering = False
            if away_mode_enabled and away_return_date:
                if away_return_date.tzinfo is None:
                    away_return_date = away_return_date.replace(tzinfo=SWE_TZ)
                    
                if now < away_return_date:
                    indoor_target = cfg.get("temp_cheap", 21.0)
                    current_indoor = indoor_temp if indoor_temp else 15.0
                    delta_t = max(0.0, indoor_target - current_indoor)
                    
                    heating_model = learning.get_house_heating_model()
                    if heating_model is not None:
                        heating_rate = learning.predict_house_heating_rate(
                            outdoor_temp or 0.0, wind_speed or 2.0, current_indoor, heating_model
                        )
                    else:
                        heating_rate = 0.3
                    t_heat_house = delta_t / heating_rate if heating_rate > 0 else 0
                    
                    if heating_model is None and wind_speed and wind_speed > 7.0:
                        t_heat_house *= 1.15

                    total_recovery_hours = t_heat_house + 1.0
                    t_start = away_return_date - timedelta(hours=total_recovery_hours)
                    
                    # Använd prisprognosen (publicerat pris om det finns, annars modellerad form)
                    # så att en återhämtning som planeras BORTOM Nordpools horisont inte faller
                    # tillbaka på platt 0.5 kr utan får dygnsformen.
                    t_start_price = (nordpool.forecast_price_at(t_start)[0] or 0.5)
                    best_early_start = t_start
                    best_early_price = t_start_price

                    for offset in range(1, 7):
                        check_time = t_start - timedelta(hours=offset)
                        if check_time < now: break
                        p = nordpool.forecast_price_at(check_time)[0]
                        if p is not None and p < best_early_price:
                            best_early_price, best_early_start = p, check_time
                            
                    if best_early_price <= t_start_price * 0.75:
                        t_start = best_early_start
                        
                    if now >= t_start:
                        away_recovering = True
                        if last_away_recovery_notified != away_return_date.date():
                            notifier.notify_away_recovery_started(t_start, away_return_date)
                            last_away_recovery_notified = away_return_date.date()
                else:
                    try:
                        with logger.get_db() as conn_main, conn_main.cursor() as cur_main:
                            cur_main.execute("UPDATE system_settings SET away_mode_enabled = FALSE WHERE id = 1")
                            conn_main.commit()
                        
                        lights_str = cfg.get("away_lights_on_return", "")
                        if lights_str:
                            light_entities = [l.strip() for l in lights_str.split(",") if l.strip()]
                            if light_entities:
                                homeassistant.turn_on_lights(light_entities)
                                notifier.send_emil("💡 Välkommen hem!", "Bortaläget har avaktiverats och dina utvalda lampor har tänts.")
                    except Exception as e:
                        print(f"Fel vid inaktivering av bortaläge: {e}")
                    away_mode_enabled = False
            
            dynamic_base_load_profile = learning.get_base_load_profile()

            # Varmvatten AI
            hw_profile = learning.get_hot_water_habit_profile()
            hw_prob_now = hw_profile.get((now.weekday(), now.hour), 0.0)
            next_hr = now + timedelta(hours=1)
            hw_prob_next = hw_profile.get((next_hr.weekday(), next_hr.hour), 0.0)
            max_hw_prob = max(hw_prob_now, hw_prob_next)

            # Säkring Matematik
            n1 = ev_lite_data.get('current_l1') or 0 if ev_lite_data else 0
            n2 = ev_lite_data.get('current_l2') or 0 if ev_lite_data else 0
            n3 = ev_lite_data.get('current_l3') or 0 if ev_lite_data else 0
            t1 = ev_carport_data.get('current_l1') or 0 if ev_carport_data else 0
            t2 = ev_carport_data.get('current_l2') or 0 if ev_carport_data else 0
            t3 = ev_carport_data.get('current_l3') or 0 if ev_carport_data else 0

            hl1_non_ev = max(0, (avg_hl1 or 0) - n1 - t1)
            hl2_non_ev = max(0, (avg_hl2 or 0) - n2 - t2)
            hl3_non_ev = max(0, (avg_hl3 or 0) - n3 - t3)
            house_load_excluding_ev_a = max(hl1_non_ev, hl2_non_ev, hl3_non_ev)

            # Dynamisk Peak Shaving
            minutes_left_burn = 60 - now.minute
            historical_base_load_kw = learning.predict_base_load(now, dynamic_base_load_profile)
            
            ev_kw_now = (ev_lite_data.get("power_kw") or 0.0 if ev_lite_data else 0.0) + (ev_carport_data.get("power_kw") or 0.0 if ev_carport_data else 0.0)
            if ev_kw_now > 100: ev_kw_now /= 1000.0 
            spa_kw_now = 3.0 if (gecko_data and str(gecko_data.get("heater_state", "")).lower() in ["heating", "heat"]) else 0.0
            current_actual_base_load_kw = max(0.5, (house_consumption_w / 1000.0) - ev_kw_now - spa_kw_now)
            
            weight_actual = (60 - minutes_left_burn) / 60.0
            weight_historical = 1.0 - weight_actual
            dynamic_predicted_base_load_kw = (current_actual_base_load_kw * weight_actual) + (historical_base_load_kw * weight_historical)
            
            reserve_kwh_needed_now = dynamic_predicted_base_load_kw * (minutes_left_burn / 60.0)
            allowed_kwh_now = current_target_limit - reserve_kwh_needed_now

            # ============================================================
            # 🚗 Väck Teslan när den är inkopplad men bara har ett gammalt (minnes)värde för batteriet.
            # Under pågående laddning är bilen vaken av sig själv; styrningen sker via Easee, så detta gäller bara
            # avläsningen av batterinivån. Högst en gång per TESLA_WAKE_MIN_INTERVAL_H (även vid misslyckat försök).
            try:
                if (ev_connection_state['tesla']['connected'] and tesla_soc_stale
                        and (_soc_mem["last_wake"] is None or (now - _soc_mem["last_wake"]) > timedelta(hours=TESLA_WAKE_MIN_INTERVAL_H))):
                    _soc_mem["last_wake"] = now
                    if homeassistant.press_button("button.tesla_model_y_wake_up"):
                        print("🚗 Väckte Teslan (inkopplad, batterinivå okänd)")
            except Exception as _we:
                print(f"⚠️ Väckning av Tesla misslyckades: {_we}")

            # 🧠 GPM UTVÄRDERING
            # ============================================================
            gpm_state = {
                'now': now, 'current_price': current_price, 'all_prices': all_prices,
                'pv_power_w': solar_now, 'avg_net_w': avg_net, 'house_consumption_w': house_consumption_w,
                'predicted_base_load_kw': dynamic_predicted_base_load_kw, 'grid_import_w': grid_import_w,
                'consumed_kwh_this_hour': float(consumed_kwh_this_hour), 'power_limit_kw': current_target_limit,
                'predicted_cooling_rate': predicted_cooling_rate, 'base_load_profile': dynamic_base_load_profile,
                'peak_shaving_enabled': cfg.get("peak_shaving_enabled", True), 'solar_is_shaky': solar_is_shaky,
                'indoor_temp': indoor_temp, 'indoor_humidity': ha_temps.get('indoor_humidity'), 'indoor_min': cfg.get("indoor_min", 19.0), 'indoor_max': cfg.get("indoor_max", 22.5),
                'water_temp': water_temp or 50.0, 'water_target_normal': wt_norm,
                'brine_out_temp': pump_data.get("brine_out_temp") if pump_data else None,
                'spa_temp': gecko_data.get("current_temp") if gecko_data else None,
                'spa_measured_w': spa_power_w,  # 3-fas-mätt spa-effekt → gpm använder verkligt värde
                'spa_normal_temp': cfg.get("spa_normal_temp", 34.0), 'days_since_legionella': days_since_leg,
                'last_heartbeat': last_heartbeat, 'legionella_max_days': leg_max_days,
                'spa_force_heat': cfg.get("spa_force_heat", False), 'spa_force_eco': all_overrides.get("spa_force_eco") == "on",
                'spa_max_temp': cfg.get("spa_max_temp", 40.0), 'spa_low_temp': cfg.get("spa_low_temp", 15.0),
                'spa_target_scheduled': cfg.get("spa_target_temp", 38.0), 'spa_target_scheduled_active': cfg.get("spa_schedule_enabled", False),
                'spa_should_heat_now': spa_should_heat_now, 'away_mode_active': away_mode_enabled,
                'hw_probability': max_hw_prob, 'away_recovering': away_recovering,
                'temp_cheap': cfg.get("temp_cheap", 22.0), 'temp_expensive': cfg.get("temp_expensive", 20.0),
                'outdoor_avg_5d': _cached_outdoor_avg_5d,  # FIX: saknades → is_summer var alltid False (dött sommarläge)
                'outdoor_temp': outdoor_temp,              # FIX: saknades → Prio 9-watchdog antog alltid "kallt ute"
                'heat_stop_outdoor': (pump_data.get('heat_stop_outdoor') if pump_data else None),  # pumpens egen värmestopp-tröskel (reg 19) → GPM samverkar i stället för hårdkodad gräns
                'hysteresis': strategy.get("hysteresis", 0.10), 'dynamic_limit': dynamic_limit if dynamic_limit else 99.0,
                'max_fuse_a': cfg.get('fuse_size_a', decisions.MAX_FUSE_A), 'house_load_a': house_load_excluding_ev_a, 'ev_actual_a': 0,
                'current_solar_limit_pct': current_solar_limit_pct, 'current_target_limit': current_target_limit,
                'nissan_soc': nissan_soc, 'tesla_soc': tesla_data.get('soc') if tesla_data else None,
                'nissan_connected': ev_connection_state['nissan']['connected'] or ev_gps_state['nissan']['approaching'],
                'tesla_connected': ev_connection_state['tesla']['connected'] or ev_gps_state['tesla']['approaching'],
                'ev_min_charge_a': EV_MIN_CHARGE_AMPS, 'ev_max_charge_a': EV_MAX_CHARGE_AMPS,
                'nissan_charge_completed': ev_connection_state['nissan']['charge_completed'],
                'tesla_charge_completed': ev_connection_state['tesla']['charge_completed'],
                'nissan_phases': nissan_charger_data.get('phases') if nissan_charger_data else None,
                'tesla_phases': tesla_charger_data.get('phases') if tesla_charger_data else None,
                'nissan_habit_profile': _cached_ev_profiles.get('nissan', {}),
                'tesla_habit_profile': _cached_ev_profiles.get('tesla', {}),
                'ev_plan': ev_charge_plan, 'nissan_prio': cfg.get('ev_nissan_prio', 2), 'tesla_prio': cfg.get('ev_tesla_prio', 1),
                'nissan_force_amps': _override_amps(all_overrides.get("nissan_force_amps", "0")),
                'nissan_force_phases': _override_amps(all_overrides.get("nissan_force_phases", "0")),
                'tesla_force_amps': _override_amps(all_overrides.get("tesla_force_amps", "0")),
                'tesla_force_phases': _override_amps(all_overrides.get("tesla_force_phases", "0")),
                'nissan_hold': all_overrides.get("nissan_hold") == "on", 'tesla_hold': all_overrides.get("tesla_hold") == "on",     # EnergyWizard Mobil: manuell paus (håller 0A tills Auto väljs)
            }
            
            gpm_actions = gpm_engine.evaluate(gpm_state)
            try:
                _persist_solar_state(getattr(gpm_engine, 'ev_solar_charge_active', False), getattr(gpm_engine, 'ev_solar_target_amps', 0), getattr(gpm_engine, 'ev_solar_target_phases', 0), now)
            except Exception as _e:
                print(f"⚠️ Kunde inte spara sol-laddningsläge: {_e}")
            ai_thoughts_list = gpm_actions["log"].copy()
            current_decision = gpm_actions["log"][-1] if gpm_actions["log"] else "Utvärderad"
            
            nissan_amps = gpm_actions.get("nissan_limit_a", 0)
            tesla_amps = gpm_actions.get("tesla_limit_a", 0)
            
            nissan_reason_stop, tesla_reason_stop = None, None
            if nissan_amps == 0:
                for log_msg in reversed(gpm_actions["log"]):
                    if any(k in log_msg for k in ["EV", "PEAK", "Säkring"]) and "inaktiverat" not in log_msg:
                        nissan_reason_stop = log_msg; break
            if tesla_amps == 0:
                for log_msg in reversed(gpm_actions["log"]):
                    if any(k in log_msg for k in ["EV", "PEAK", "Säkring"]) and "inaktiverat" not in log_msg:
                        tesla_reason_stop = log_msg; break

            current_chosen_temp = int(gpm_actions["pump_target_temp"] * 10)
            current_chosen_water = decisions.WATER_ON if gpm_actions.get("pump_run_water") else decisions.WATER_OFF
            current_mode = gpm_actions["pump_mode"]

            # Fasväxling
            nissan_set_phases = gpm_actions.get("nissan_set_phases")
            tesla_set_phases = gpm_actions.get("tesla_set_phases")
            
            # FIX: flagga pågående fasbyte så det vanliga EV-limit-blocket nedan inte skickar
            # tillbaka ström på laddaren medan fasbytestråden förbereder kontaktorbrytning vid 0A.
            nissan_phase_switch_active = False
            tesla_phase_switch_active = False
            if nissan_set_phases or tesla_set_phases:
                print("⚡ Fasbyte begärt! Asynkron omstart startad för säker kontaktor-brytning...")
                def phase_switch_async():
                    if nissan_set_phases: homeassistant.set_ev_dynamic_limit(nissan_charger_id, 0, reason="Fasbyte förbereds")
                    if tesla_set_phases: homeassistant.set_ev_dynamic_limit(tesla_charger_id, 0, reason="Fasbyte förbereds")
                    time.sleep(15)
                    if nissan_set_phases: homeassistant.set_easee_phases(nissan_charger_id, nissan_set_phases)
                    if tesla_set_phases: homeassistant.set_easee_phases(tesla_charger_id, tesla_set_phases)
                threading.Thread(target=phase_switch_async).start()
                if nissan_set_phases:
                    last_sent_ev_limit_nissan = 0
                    nissan_phase_switch_active = True
                if tesla_set_phases:
                    last_sent_ev_limit_tesla = 0
                    tesla_phase_switch_active = True

            # EV Limit
            nissan_charger_connected = nissan_charger_data and nissan_charger_data.get("status") not in ["disconnected", "offline", "unknown", None]
            tesla_charger_connected = tesla_charger_data and tesla_charger_data.get("status") not in ["disconnected", "offline", "unknown", None]

            if nissan_charger_connected:
                # FIX: hoppa över ström-sättning under pågående fasbyte (laddaren ska ligga på 0A)
                if not nissan_phase_switch_active:
                    if nissan_amps != last_sent_ev_limit_nissan:
                        if homeassistant.set_ev_dynamic_limit(nissan_charger_id, nissan_amps, reason=nissan_reason_stop):
                            last_sent_ev_limit_nissan = nissan_amps
                    if nissan_amps > 0 and nissan_charger_data.get("status") in ["awaiting_start", "paused", "off"]:
                        homeassistant.turn_on_charger(nissan_charger_id)
            else:
                last_sent_ev_limit_nissan = None
                
            if tesla_charger_connected:
                # FIX: hoppa över ström-sättning under pågående fasbyte (laddaren ska ligga på 0A)
                if not tesla_phase_switch_active:
                    if tesla_amps != last_sent_ev_limit_tesla:
                        if homeassistant.set_ev_dynamic_limit(tesla_charger_id, tesla_amps, reason=tesla_reason_stop):
                            last_sent_ev_limit_tesla = tesla_amps
                    if tesla_amps > 0 and tesla_charger_data.get("status") in ["awaiting_start", "paused", "off"]:
                        homeassistant.turn_on_charger(tesla_charger_id)
            else:
                last_sent_ev_limit_tesla = None

            # Pump Setpoint
            ov_smart_mode = all_overrides.get("pump_smart_mode", "auto")
            if ov_smart_mode != "manual":
                ov_heat  = all_overrides.get("heat", "auto")
                if ov_heat == "on": current_chosen_temp = int(cfg["temp_cheap"] * 10)
                elif ov_heat == "off": current_chosen_temp = int(cfg["temp_expensive"] * 10)
                
                actual_pump_setpoint = pump_data.get("room_temp_setpoint") if pump_data else None
                needs_update = False
                if actual_pump_setpoint is not None:
                    if abs(int(actual_pump_setpoint * 10) - current_chosen_temp) >= 5: needs_update = True
                elif last_sent_temp != current_chosen_temp:
                    needs_update = True
                
                if needs_update:
                    print(f"🔧 Sätter pumpens måltemp till {current_chosen_temp/10.0}°C...")
                    if pump.set_room_temp(current_chosen_temp): last_sent_temp = current_chosen_temp
            else:
                ov_pump_mode = all_overrides.get("pump_operating_mode", "auto")
                try:
                    manual_mode = int(ov_pump_mode)
                    if manual_mode != last_sent_operating_mode:
                        print(f"🔧 Överstyrning: Sätter pump manuellt till {manual_mode}")
                        if pump.set_operating_mode(manual_mode):
                            last_sent_operating_mode = manual_mode
                            pump_operating_mode_from_pump = manual_mode 
                except (ValueError, TypeError):
                    pass

            # Solar Limit
            new_solar_limit = gpm_actions.get("solar_limit_pct")
            if new_solar_limit is not None and new_solar_limit != last_sent_solar_limit and isinstance(new_solar_limit, (int, float)):
                if homeassistant.set_solaredge_limit(int(new_solar_limit)):
                    last_sent_solar_limit = new_solar_limit
                    
            if new_solar_limit is not None:
                is_limiting = new_solar_limit < 100
                if is_limiting and not last_solar_notified_state:
                    if last_solar_notify_time is None or (now - last_solar_notify_time) > timedelta(hours=2):
                        if should_notify("notify_solar_limit"): notifier.notify_solar_limit_start(new_solar_limit)
                        last_solar_notified_state = True
                        last_solar_notify_time = now
                    solar_limit_debounce_counter = 0
                elif not is_limiting and last_solar_notified_state:
                    solar_limit_debounce_counter += 1
                    if solar_limit_debounce_counter >= 15:
                        if should_notify("notify_solar_limit"): notifier.notify_solar_limit_stop()
                        last_solar_notified_state = False
                        last_solar_notify_time = now
                        solar_limit_debounce_counter = 0
                elif is_limiting and last_solar_notified_state:
                    solar_limit_debounce_counter = 0

            # Spabad
            new_spa_target = gpm_actions["spa_target"]
            new_spa_eco = gpm_actions["spa_eco"]
            actual_spa_target = gecko_data.get("target_temp") if gecko_data else None
            actual_spa_eco = gecko_data.get("economy_mode") == 1.0 if gecko_data else None

            if cfg.get('spa_force_heat', False):
                print(f"🔥 [TVÅNGSVÄRME AKTIV] GPM Mål: {new_spa_target}°C, Eco: {new_spa_eco} | Faktiskt i HA: {actual_spa_target}°C")

            if (last_sent_spa_target != new_spa_target or last_sent_spa_eco != new_spa_eco or 
                (actual_spa_target is not None and abs(actual_spa_target - new_spa_target) > 0.1) or
                (actual_spa_eco is not None and actual_spa_eco != new_spa_eco)):
                print(f"🛁 => SKICKAR NYA VÄRDEN TILL SPABADET! (Eco: {new_spa_eco}, Target: {new_spa_target}°C)")
                homeassistant.set_gecko_economy(new_spa_eco)
                time.sleep(0.5)
                homeassistant.set_gecko_target(float(new_spa_target))
                last_sent_spa_target = new_spa_target
                last_sent_spa_eco = new_spa_eco

            # Notifieringsblock
            if current_target_limit > 0 and consumed_kwh_this_hour > allowed_kwh_now * 0.95 and allowed_kwh_now > 0:
                if last_peak_shaving_notify_time is None or (now - last_peak_shaving_notify_time) > timedelta(hours=2):
                    if should_notify("notify_peak_shaving"):
                        notifier.alert_peak_shaving_warning(consumed_kwh_this_hour, current_target_limit)
                    last_peak_shaving_notify_time = now

            if current_minute % 5 == 0:
                is_pump_running = pump_data and (pump_data.get("compressor_running", 0) == 1 or pump_data.get("pump_heat_running", 0) == 1)
                is_spa_heating = gecko_data and str(gecko_data.get("heater_state", "")).lower() == "heating"
                if not is_pump_running and not is_spa_heating and ev_kw_now < 0.5:
                    actual_base_load_kw = house_consumption_w / 1000.0
                    predicted_base_kw = learning.predict_base_load(now, dynamic_base_load_profile)
                    if actual_base_load_kw > (predicted_base_kw * 1.5) and actual_base_load_kw > (predicted_base_kw + 1.0):
                        if last_anomaly_notify_time is None or (now - last_anomaly_notify_time) > timedelta(hours=24):
                            notifier.send_emil("🚨 Onormal Baslast Upptäckt!", f"Huset drar {actual_base_load_kw:.1f} kW.")
                            last_anomaly_notify_time = now

            weekday = now.weekday()
            notify_hour = 9 if weekday == 6 else 7
            today_date = now.date()
            if now.hour == notify_hour and now.minute == 0 and last_morning_notify_date != today_date:
                if all_prices and should_notify("notify_price_tip"):
                    notifier.morning_price_tip(all_prices, cfg["cheap_hours_count"], weekday)
                last_morning_notify_date = today_date

            if now.hour == 8 and now.minute == 0 and last_disk_check_date != today_date:
                asyncio.run(asyncio.to_thread(logger.downsample_old_data, 6))
                storage = logger.get_storage_info()
                last_disk_check_date = today_date
                if storage["disk_pct"] >= DISK_WARN_PCT:
                    notifier.alert_disk_warning(storage["disk_pct"], storage["disk_free_gb"], storage["db_total_gb"] or 0, storage["sensor_log_gb"] or 0)
                else:
                    print(f"💾 Disk OK: {storage['disk_pct']:.0f}%")

            if current_price is not None and all_prices:
                new_price_state = "normal"
                if decisions.is_price_high(current_price, all_prices): new_price_state = "high"
                elif decisions.is_price_low(current_price): new_price_state = "low"
                
                if new_price_state != last_price_state:
                    if new_price_state == "high" and should_notify("notify_high_low"):
                        notifier.alert_high_price(current_price, sum(all_prices)/len(all_prices) * decisions.PRICE_HIGH_MULTIPLIER)
                    elif new_price_state == "low" and should_notify("notify_high_low"):
                        notifier.alert_low_price(current_price)
                    last_price_state = new_price_state

            if pump_data and pump_data.get("alarm_active") == 1:
                alarm_code = pump_data.get("alarm_code", 0)
                if alarm_code != last_pump_alarm_code:
                    if should_notify("notify_pump_alarm"): notifier.alert_pump_alarm(alarm_code)
                    last_pump_alarm_code = alarm_code
            elif pump_data:
                last_pump_alarm_code = None

            if solar_data:
                inv_status = solar_data.get("status")
                if inv_status == 3 and not last_solar_error_sent:
                    if should_notify("notify_solar_error"): notifier.alert_solar_error(inv_status)
                    last_solar_error_sent = True
                elif inv_status != 3:
                    last_solar_error_sent = False

            if gecko_data:
                c_temp = gecko_data.get("current_temp")
                t_temp = gecko_data.get("target_temp")
                if c_temp is not None and t_temp is not None:
                    is_reached = c_temp >= t_temp
                    if is_reached and not last_spa_reached:
                        if cfg.get("notify_spa_ready", True) and (last_spa_ready_notify_time is None or (now - last_spa_ready_notify_time) > timedelta(hours=4)):
                            notifier.notify_spa_ready(c_temp)
                            last_spa_ready_notify_time = now
                    last_spa_reached = is_reached

            if ev_lite_data:
                c_status = ev_lite_data.get("status")
                if c_status == "charging" and last_ev_status != "charging":
                    if cfg.get("notify_ev_start", True): notifier.notify_ev_charging("Nissan", ev_lite_data.get("power_kw") or 0.0)
                last_ev_status = c_status

            if miele_data:
                is_running = miele_data.get("status") not in ["off", "unavailable", "unknown", None]
                if is_running and not last_washer_running:
                    if cfg.get("notify_washer_start", True): notifier.notify_washing_machine()
                last_washer_running = is_running

            # --- SÄKERHETSLARM: Kallt inomhus (slår INTE på värmen) ---
            # Viktigt när pumpen står i manuellt läge, då GPM:s automatiska kylskydd är ur spel.
            if indoor_temp is not None:
                if indoor_temp < INDOOR_COLD_ALERT_C and not indoor_cold_alerted:
                    pump_is_manual = all_overrides.get("pump_smart_mode") == "manual"
                    notifier.alert_indoor_cold(indoor_temp, INDOOR_COLD_ALERT_C, pump_is_manual)
                    indoor_cold_alerted = True
                elif indoor_temp >= INDOOR_COLD_ALERT_C + 1.0:
                    indoor_cold_alerted = False  # Återställ när vi stigit tydligt över golvet

            if gecko_data and cfg.get("notify_spa_open", True) and current_minute % 15 == 0:
                c_temp = gecko_data.get("current_temp")
                if c_temp is not None and outdoor_temp is not None:
                    temp_1h_ago = logger.get_spa_temp_ago(60)
                    if temp_1h_ago is not None:
                        actual_drop = temp_1h_ago - c_temp
                        if actual_drop > 0:
                            c_intercept, c_slope = learning.get_cooling_rate_model()
                            expected_drop = learning.predict_cooling_rate(outdoor_temp or 0.0, c_temp, c_intercept)
                            if actual_drop >= (expected_drop + 1.0) and actual_drop >= 1.5:
                                if last_spa_open_alert_time is None or (now - last_spa_open_alert_time) > timedelta(hours=4):
                                    if should_notify("notify_spa_open"): notifier.alert_spa_cover(actual_drop, expected_drop)
                                    last_spa_open_alert_time = now

            if gecko_data:
                solar_boost_now = gpm_actions.get("spa_solar_boost_active", False)
                if solar_boost_now and not last_spa_solar_boost_active:
                    if last_spa_boost_start_time is None or (now - last_spa_boost_start_time) > timedelta(hours=4):
                        if should_notify("notify_spa_boost"): notifier.notify_spa_solar_boost_start()
                        last_spa_boost_start_time = now
                    last_spa_solar_boost_active = True
                    spa_solar_boost_grace_counter = 0
                elif not solar_boost_now and last_spa_solar_boost_active:
                    spa_solar_boost_grace_counter += 1
                    if spa_solar_boost_grace_counter >= 15:
                        if last_spa_boost_stop_time is None or (now - last_spa_boost_stop_time) > timedelta(hours=4):
                            c_temp = gecko_data.get("current_temp")
                            if c_temp is not None and should_notify("notify_spa_boost"):
                                notifier.notify_spa_solar_boost_stop(c_temp)
                            last_spa_boost_stop_time = now
                        last_spa_solar_boost_active = False
                        spa_solar_boost_grace_counter = 0
                elif solar_boost_now and last_spa_solar_boost_active:
                    spa_solar_boost_grace_counter = 0

            # COP Estimering
            cop = None
            if pump_data and pump_data.get("compressor_running") == 1:
                forward = pump_data.get("forward_temp") or 45.0
                avg_tot = _estimate_pump_el_w(pump_data.get("forward_temp"))
                brine = pump_data.get("brine_in_temp") or 0.0
                delta_t = max(5.0, forward - brine)
                carnot_efficiency = 0.60 - (forward * 0.0025)
                cop = round(max(1.5, min(6.5, ((forward + 273.15) / delta_t) * carnot_efficiency)), 2)
                pump_data["compressor_power_kw"] = round((avg_tot / 1000.0) * cop, 2)
            else:
                avg_tot = 0.0
                if pump_data: pump_data["compressor_power_kw"] = 0.0

            # ============================================================
            # 🔧 KVARTS-TASK – Exekvera modbus & tyngre uppgifter
            # ============================================================
            if current_quarter != last_quarter:
                if pump_operating_mode_from_pump == 0 and last_sent_operating_mode is not None and last_sent_operating_mode != 0:
                    warning_msg = f"🚨 VARNING: Pumpens driftläge är 0 (All off) men förväntade {last_sent_operating_mode}."
                    print(warning_msg)
                    ai_thoughts_list.append(warning_msg)

                print(f"\n{'='*55}")
                print(f"  GPM Master Logic Tree Utvärderad: {now.strftime('%H:%M:%S')}")
                print(f"{'='*55}")
                
                if spa_reboot_stage == 0:
                    ha_toggle_switch(homeassistant.SPA_PLUG, turn_on=True)
                
                for log_msg in gpm_actions["log"]:
                    print(f"  {log_msg}")

                if ov_smart_mode != "manual":
                    water_target = gpm_actions["water_target_temp"]
                    if last_sent_water_target != water_target:
                        pump.set_water_stop_temp(water_target)
                        time.sleep(2)
                        pump.set_water_start_temp(water_target - 5)
                        last_sent_water_target = water_target
                        
                    ov_water = all_overrides.get("hotwater", "auto")
                    if ov_water == "on": print("🔧 Överstyrning: Varmvatten TILL")
                    elif ov_water == "off": print("🔧 Överstyrning: Varmvatten FRÅN")

                last_quarter = current_quarter

            # ============================================================
            # 💾 SPARA TILL DATABASEN (Varje minut)
            # ============================================================
            logger.log_status(
                current_price, indoor_temp, water_temp,
                current_chosen_temp / 10.0, current_chosen_water,
                forward_temp, return_temp, calc_forward, outdoor_temp,
                avg_hl1, avg_hl2, avg_hl3, avg_tot,  # Använder Tibber faser för loggning här
                consumed_kwh, current_kwh,
                cloud_cover, wind_speed, avg_net, wind_dir,
                solar_now, pump_data, solar_data, ha_temps,
                nissan_charger_data, cop=cop, ev_carport=tesla_charger_data,
                car_data={
                    "nissan_soc": nissan_data.get("soc") if nissan_data else None,
                    "tesla_soc": tesla_data.get("soc") if tesla_data else None,
                    "nissan_soc_stale": 1 if nissan_soc_stale else 0,
                    "tesla_soc_stale": 1 if tesla_soc_stale else 0,
                    "nissan_climate_temp": nissan_data.get("climate_temp") if nissan_data else None,
                    "nissan_climate_state": nissan_data.get("climate_state") if nissan_data else None,
                    "nissan_charge_completed": ev_connection_state['nissan']['charge_completed'],
                    "tesla_charge_completed": ev_connection_state['tesla']['charge_completed'],
                },
                pump_operating_mode=pump_operating_mode_from_pump,
                shelly_l1_a=avg_hl1, shelly_l2_a=avg_hl2, shelly_l3_a=avg_hl3,
                ev_avail_a=nissan_amps + tesla_amps,
                forecast_temp=forecast_temp, gecko=gecko_data, spa_power_w=spa_power_w,
                mower_data=mower_data,
                ai_action_log="\n\n".join(ai_thoughts_list),
                active_mode=current_mode, active_decision=current_decision,
                price_forecast=next_price, house_consumption_w=house_consumption_w,
                pi_p_term=pi_p_term, pi_i_term=pi_i_term,
                peak_shaving_active=peak_shaving_active, force_heating_active=force_heating_active,
                watchdog_trips=watchdog_trips, predicted_cooling_rate=predicted_cooling_rate,
                expected_energy_wh=expected_energy_wh, current_target_limit=current_target_limit,
                predicted_base_load_kw=dynamic_predicted_base_load_kw, allowed_kwh_now=allowed_kwh_now
            )

            last_minute = current_minute

            # Publicera smartbox-värden till Home Assistant (för dashboard-kort). Egen tråd, fel ignoreras.
            try:
                _r1 = lambda v, n=1: round(float(v), n) if v is not None else None
                _pub = {
                    "sensor.smartbox_inomhustemp": (_r1(indoor_temp), {"friendly_name": "Smartbox Inomhustemperatur", "unit_of_measurement": "°C", "device_class": "temperature", "state_class": "measurement"}),
                    "sensor.smartbox_luftfuktighet": (_r1(ha_temps.get("indoor_humidity")), {"friendly_name": "Smartbox Luftfuktighet", "unit_of_measurement": "%", "device_class": "humidity", "state_class": "measurement"}),
                    "sensor.smartbox_elpris": (_r1(current_price, 3), {"friendly_name": "Smartbox Elpris", "unit_of_measurement": "kr/kWh", "icon": "mdi:cash", "nasta_pris": _r1(next_price, 3)}),
                    "sensor.smartbox_maltemperatur": (_r1(current_chosen_temp / 10.0), {"friendly_name": "Smartbox Måltemperatur", "unit_of_measurement": "°C", "device_class": "temperature"}),
                    "sensor.smartbox_framledning": (_r1(forward_temp), {"friendly_name": "Smartbox Framledning", "unit_of_measurement": "°C", "device_class": "temperature", "retur": _r1(return_temp), "beraknad": _r1(calc_forward)}),
                    "sensor.smartbox_utetemperatur": (_r1(outdoor_temp), {"friendly_name": "Smartbox Utetemperatur", "unit_of_measurement": "°C", "device_class": "temperature"}),
                    "sensor.smartbox_varmvatten": (_r1(water_temp), {"friendly_name": "Smartbox Varmvatten", "unit_of_measurement": "°C", "device_class": "temperature"}),
                    "sensor.smartbox_cop": (_r1(cop, 2), {"friendly_name": "Smartbox COP", "icon": "mdi:heat-pump"}),
                    "sensor.smartbox_lage": (current_mode, {"friendly_name": "Smartbox Läge", "icon": "mdi:brain"}),
                    "sensor.smartbox_beslut": ((current_decision or "")[:250] or None, {"friendly_name": "Smartbox Beslut", "icon": "mdi:head-cog", "fullstandigt": (current_decision or "")[:1500]}),
                    "sensor.smartbox_tesla_batteri": (_r1(tesla_data.get("soc"), 0) if tesla_data else None, {"friendly_name": "Smartbox Tesla batteri", "unit_of_measurement": "%", "device_class": "battery", "senast_kand": bool(tesla_soc_stale), "alder_min": (round((now - _soc_mem["tesla"][1]).total_seconds() / 60) if tesla_soc_stale and _soc_mem["tesla"][1] else 0)}),
                    "sensor.smartbox_leaf_batteri": (_r1(nissan_data.get("soc"), 0) if nissan_data else None, {"friendly_name": "Smartbox Leaf batteri", "unit_of_measurement": "%", "device_class": "battery", "senast_kand": bool(nissan_soc_stale), "alder_min": (round((now - _soc_mem["nissan"][1]).total_seconds() / 60) if nissan_soc_stale and _soc_mem["nissan"][1] else 0)}),
                    "binary_sensor.smartbox_kompressor": ("on" if (pump_data and pump_data.get("compressor_running") == 1) else "off", {"friendly_name": "Smartbox Kompressor", "device_class": "running"}),
                }
                threading.Thread(target=homeassistant.publish_states, args=(_pub,), daemon=True).start()
            except Exception as _pe:
                print(f"⚠️ Kunde inte publicera till HA: {_pe}")

            # Fas-inlärning: logga per-fas-effekt + spabadets aktiviteter (1/min) → underlag för
            # learnern som lär sig vilken fas som driver värmare/pump/blåsare/…
            try:
                _spa_act = homeassistant.read_spa_activities()
                logger.log_spa_phase(spa_power_data.get('phase_a_w'), spa_power_data.get('phase_b_w'),
                                     spa_power_data.get('phase_c_w'), _spa_act)
            except Exception as _spe:
                print(f"spa_phase-logg hoppade över: {_spe}")

            # ── LAST-NEDBRYTNING: förklara husets effekt med det vi FAKTISKT mäter ────────
            # total = elbil + värmepump + spa + OFÖRKLARAT (ugn/bastu/tvätt/…).
            try:
                _ev_w   = (((ev_lite_data.get("power_kw") or 0.0) if ev_lite_data else 0.0)
                           + ((ev_carport_data.get("power_kw") or 0.0) if ev_carport_data else 0.0)) * 1000.0
                # OBS: compressor_power_kw är VÄRME-uteffekt (el×COP), INTE el. Pumpens faktiska
                # EL-effekt är avg_tot (~2200 W när kompressorn går, annars 0). Använd den här.
                _pump_w = avg_tot if avg_tot else 0.0
                _spa_w  = spa_power_w or 0.0
                _known_w = _ev_w + _pump_w + _spa_w
                # Robust total: aldrig mindre än de uppmätta lasterna (skyddar mot glitchande
                # pv-sensor som annars kan göra house_consumption_w falskt negativ → 0).
                _total_w = max(_known_w, max(0.0, house_consumption_w))
                # Oförklarad last är bara meningsfull vid nätimport; vid export täcker solen lasten
                # och den (glitchiga) pv-sensorn kan annars ge falsk "oförklarad" last.
                # EXTRA KONTROLL med fasströmmarna (oberoende av solsensorn): nätimporten är alltid verklig
                # förbrukning -> solfri nedre gräns. Fastfryst solvärde (oförändrat 5 min) -> använd bara fas-gränsen.
                _pv_hist.append(round(solar_prod_w or 0))
                del _pv_hist[:-5]
                _pv_frozen = len(_pv_hist) == 5 and len(set(_pv_hist)) == 1 and _pv_hist[0] > 0
                _lc = health.load_check(_total_w, _known_w, avg_net, (avg_hl1, avg_hl2, avg_hl3), _pv_frozen)
                _unexpl_w = _lc["unexplained_w"]
                logger.log_load_breakdown(_total_w, _ev_w, _pump_w, _spa_w, _unexpl_w)
                # Oförklarad-last-notis – OBEROENDE av peak-shaving. >2 kW oförklarat i 10+ min,
                # men BARA vid nätimport (net>0): då är hög last relevant OCH beräkningen pålitlig
                # (vid export täcker solen lasten och pv-sensorbrus kan annars ge falsklarm).
                if _lc["alert"]:
                    if last_unexplained_start is None:
                        last_unexplained_start = now
                    elif (now - last_unexplained_start) >= timedelta(minutes=10):
                        if last_unexplained_notify is None or (now - last_unexplained_notify) > timedelta(hours=2):
                            notifier.alert_unexplained_load(_unexpl_w/1000, _total_w/1000, _ev_w/1000, _pump_w/1000, _spa_w/1000,
                                                            phases=(avg_hl1, avg_hl2, avg_hl3), gross_import_kw=_lc["gross_import_w"]/1000,
                                                            grid_lb_kw=_lc["grid_lb_w"]/1000, pv_frozen=_pv_frozen)
                            last_unexplained_notify = now
                else:
                    last_unexplained_start = None
            except Exception as _lbe:
                print(f"last-nedbrytning hoppade över: {_lbe}")

            # Veckovis MPC-skugg-backtest (systemets självvalidering). Åldern kollas billigt varje
            # minut; själva backtesten (som tränar modeller) körs bara om senaste är >7 dygn gammal.
            try:
                _mpc_age = mpc.last_backtest_age_days()
                if _mpc_age is None or _mpc_age >= 7.0:
                    print("🔮 Kör veckovis MPC-backtest (skuggläge, självvalidering)...")
                    mpc.run_and_store_backtest(days=30)
            except Exception as _mpce:
                print(f"MPC-backtest hoppade över: {_mpce}")

        time.sleep(10)
    except Exception as e:
        print(f"🔥 KRITISKT FEL I HUVUDLOOPEN: {e}")
        import traceback
        traceback.print_exc()
        time.sleep(10)