import asyncio
import json
import time
import threading
import math
import statistics
from datetime import datetime, timedelta
import re
import requests
import zoneinfo
import nordpool  # Hämtar elpriser från Nordpool
import pump      # Styr värmepumpen och läser dess sensorer
import logger    # Sparar logg till databas (varje minut)
import settings  # Hanterar konfigurationsinställningar
import weather   # Hämtar och cachelagrar väderprognos inkl. solprognos
import homeassistant    # Hämtar data från Home Assistant (temperaturer + Easee-laddare)
import notifier         # Skickar push-notiser till Emil
import energy_balance   # Husets energibalans (solgolv ur exporten, rimlig batterieffekt)
import telemetry        # Strikt opt-in: fel + aktiva drivrutinkategorier, se telemetry.py
from urllib.parse import urlsplit, urlunsplit
import decisions        # Besluts- och styrlogik för pump och radiatorer
import gpm              # Global Priority Manager (Master Logic Tree)
import ha_publisher      # Publicerar härledda värden (priser, effektfördelning, COP, besparing) till HA
import health            # Sensor-/länkövervakning (varnar när en sensor tystnat, sammanfattar HA-avbrott)
import learning         # AI-modeller för temperatur och avsvalning
import mpc               # Prediktiv förvärmnings-planerare (skuggläge + veckovis självvalidering)
import house_config      # EnergyWizard Open: drivrutinsarkitektur (bil/laddare/värmepump/sol/spa)
import smart_plugs
import ev_handshake      # Generisk laddar-handskakning (vilken fysisk laddare hör till vilken bil)
import decision_summary  # Vad görs nu och varför, per enhet (ur gpm.py:s logg)
import solar_write_guard # Hur ofta exportgränsen får skrivas (flashminnet i växelriktaren)
import config_watch      # Startar om motorn när house_config.yaml ändras
import battery_control   # Husbatteriet som del av hela systemet (styr / samarbete / av)
import ew_journal
import battery_commands
import battery_follow
import guest_charge
import capacity_tariff
import ev_limits
import car_log
import timed_override  # #397: överstyrningar med tid går tillbaka till Auto
import charger_limit # #385: förklara när laddboxen ger bilen mindre än vi bad om
import charge_now    # #394: "Ladda nu till X %" som avslutas av sig själv
import ramp_budget     # #399: beviljade ökningar som ännu inte syns i mätningen
import water_setpoints  # Varmvattnets start/stopp: stoppet aldrig under normal, kontroll efter skrivning
import hot_water_monitor  # Default-off advisory shadow monitor; no device writes
import ev_heating       # Temperaturberoende baslast för laddplanen (ev_planning.heating_adjustment), natanoj
import battery_plan      # Batteriets dygnsplan (steg 3): ladda billigt, ladda ur dyrt
import battery_balance
import battery_learning  # Planen lär sig batteriets verkliga verkningsgrad, kapacitet, effekt och solprognosens fel
import signal
import spa_bath           # Badtider för spabadet: eco-golv utanför, uppvärmning inför nästa badtid
import car_climate_watch # Följer upp bilens värme från appen tills den faktiskt startar (annars avisering)
import fuse_guard        # Termisk säkringsmodell: elbilarna mot huvudsäkringen (I² med 60 s tidskonstant)
import os

# Tidszon för Sverige
SWE_TZ = zoneinfo.ZoneInfo("Europe/Stockholm")

EV_MIN_CHARGE_AMPS = 6
EV_MAX_CHARGE_AMPS = 20

_cached_ev_profiles = {}
_cached_ev_profiles_time = None

# Tillståndsminne för handskakning (vilken bil står var) - initieras med riktiga
# fysiska laddar-id:n längre ner, efter att house_config.yaml lästs in.
ev_allocations = {}

# Tracker-state för GPS Hemkomst
from collections import defaultdict as _dd
ev_gps_state = _dd(lambda: {'prev_dist': 999.0, 'approaching': False})   # per bil (installationens id)

def calc_distance(lat1, lon1, lat2, lon2):
    if None in (lat1, lon1, lat2, lon2): return 999.0
    R = 6371.0 # Jordens radie i km
    dLat = math.radians(lat2 - lat1)
    dLon = math.radians(lon2 - lon1)
    a = math.sin(dLat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dLon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def ha_toggle_switch(entity_id, turn_on=True):
    service = "turn_on" if turn_on else "turn_off"
    url = f"{homeassistant._BASE}/services/switch/{service}"
    try:
        homeassistant.requests.post(url, headers=homeassistant._HEADERS, json={"entity_id": entity_id}, timeout=5,
                      verify=homeassistant._VERIFY)
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
# 🔌 EnergyWizard Open: house_config.yaml + drivrutinsinstanser
# ============================================================
# Steg 3-4 av drivrutins-ihopkopplingen: laddar configen och bygger drivrutinsinstanserna
# tidigt vid uppstart (innan UPPSTARTSKONTROLL nedan, som redan behöver spa_driver) -
# resten av styrloopen byts om ett delsystem i taget, med produktionsverifiering mellan
# varje. Fail-safe: om configen saknas/är trasig byggs bara Null-drivrutiner, inget kraschar.
HOUSE_CONFIG_PATH = os.environ.get("HOUSE_CONFIG_PATH", "/house_config.yaml")

# Ny installation: väntar tills startguiden i webben har kopplat Home Assistant.
if not homeassistant.configured():
    import ew_settings
    print("👋 Home Assistant är inte kopplat än. Öppna webben (port 8503) och följ startguiden. Motorn väntar.")
    while not homeassistant.configured():
        time.sleep(10)
        homeassistant.reconfigure()
    print("✅ Home Assistant kopplat via startguiden - startar.")
try:
    house_cfg = house_config.load_house_config(HOUSE_CONFIG_PATH)
except Exception as e:
    print(f"⚠️ Kunde inte ladda house_config.yaml från {HOUSE_CONFIG_PATH} ({e}) - fortsätter med tomt hus (bara Null-drivrutiner).")
    house_cfg = {}
try:
    _smart_plugs = smart_plugs.Controller(house_cfg.get('smart_plugs'))
except ValueError as e:
    print(f"Smart plugs disabled: {e}")
    _smart_plugs = smart_plugs.Controller(None)
car_drivers = house_config.build_car_drivers(house_cfg)
charger_drivers = house_config.build_charger_drivers(house_cfg)
physical_charger_drivers = house_config.build_physical_charger_drivers(house_cfg)
default_car_per_charger = house_config.build_default_car_per_charger(house_cfg)
def _build_or_null(name, build, null):
    """En felaktig inställning för en enhet (t.ex. fel port till NIBE:s lokala API) ska inte stoppa hela motorn i en
    omstartsloop: logga tydligt och kör vidare utan just den enheten."""
    try:
        return build(house_cfg)
    except Exception as _be:
        print(f"❌ {name}: inställningen i house_config.yaml går inte att använda ({type(_be).__name__}: {_be}). "
              f"Kör vidare utan {name.lower()} tills den är rättad.")
        return null()


heat_pump_driver = _build_or_null("Värmepumpen", house_config.build_heat_pump_driver, house_config.NullHeatPumpDriver)
solar_driver = _build_or_null("Solcellerna", house_config.build_solar_driver, house_config.NullSolarDriver)
spa_driver = _build_or_null("Spabadet", house_config.build_spa_driver, house_config.NullSpaDriver)
HAS_SPA = not isinstance(spa_driver, house_config.NullSpaDriver)   # inget spa i installationen: ingen spa-bevakning eller -styrning
battery_driver = _build_or_null("Batteriet", house_config.build_battery_driver, house_config.NullBatteryDriver)


# Laddboxar: skriv via laddarens drivrutin (Easee: samma tjänster som förut; generisk/OCPP: switch +
# sessionens strömgräns, se drivers/charger_generic.py). Utan drivrutin för id:t: Easee-anropen som förut.
def charger_set_limit(cid, amps, reason=None):
    drv = physical_charger_drivers.get(cid)
    return drv.set_limit_a(amps, reason=reason) if drv else homeassistant.set_ev_dynamic_limit(cid, amps, reason=reason)


def charger_turn_on(cid):
    drv = physical_charger_drivers.get(cid)
    return drv.turn_on() if drv else False         # okänd laddbox: inget att slå på


def charger_set_phases(cid, phases):
    drv = physical_charger_drivers.get(cid)
    return drv.set_phases(phases) if drv else homeassistant.set_easee_phases(cid, phases)
battery_cfg = house_config.battery_settings(house_cfg)
_battery = {"last": None, "at": None, "plan": None, "plan_at": None, "model": None, "model_at": None}
_battery_follow = battery_follow.FollowWatch()
_battery_balance = battery_balance.Monitor()
_battery_commands = battery_commands.Tracker()
_guest_state, _guest_price = {}, {}
_cap_cache = {"at": None, "peaks": [], "info": None}   # effektavgift efter högsta timmar (capacity_tariff.py)          # gästbil per bilens laddbox (guest_charge.py)


def _battery_note(model, live):
    """Texten under batteribeslutet: det inlärda, och om dygnet just nu planeras långsammare (#251)."""
    note = ""
    if model:
        note = battery_learning.describe(model)
        saved = model.get("saving_yesterday_kr")
        if saved is not None:
            note += f" Igår sparade batteriet {saved:.0f} {nordpool.cost_settings()['symbol']} (uppmätt)."
    if live:
        note = (note + " " + live).strip()
    return note or None


def _battery_to_auto(reason):
    """Lämna tillbaka batteriet till växelriktarens eget läge (uppstart, avstängning)."""
    if battery_cfg["control"] == "styr" and "auto" in battery_driver.supported_intents():
        try:
            if battery_commands.apply(_battery_commands, battery_driver, "auto", None):
                print(f"🔋 Batteri: tillbaka till växelriktarens eget läge ({reason}).")
        except Exception as _be:
            print(f"⚠️ Batteri: kunde inte återställa läget ({reason}): {_be}")


def _on_sigterm(signum, frame):
    # docker stop / Watchtower-uppdatering: släpp batteriet innan vi går ner, så det aldrig
    # blir kvar i "ladda ur" eller "håll" utan att någon styr det (FTW:s dead-man-princip).
    _battery_to_auto("motorn stängs av")
    raise SystemExit(0)


signal.signal(signal.SIGTERM, _on_sigterm)
config_watch.start(HOUSE_CONFIG_PATH)   # ny house_config.yaml -> omstart som läser in den
import snapshot_status
snapshot_status.start()               # diagnostics only; never waits for storage or database
import ew_settings as _ew_settings
# ny anslutning till HA från startguiden -> omstart (andra inställningar läses utan omstart)
config_watch.start(_ew_settings.PATH, signature=lambda _p: (_ew_settings.get("ha_url"), _ew_settings.get("ha_token")) if _ew_settings.get("ha_url") else None)
_battery_to_auto("uppstart")
print(f"🔋 Batteri: läge '{battery_cfg['control']}', styrbara lägen {sorted(battery_driver.supported_intents()) or '-'}")
homeassistant.configure_power_meter(house_config.power_meter_entities(house_cfg))
# Valfri andra mätpunkt (lastsidan): load_meter.entities.current_l1..3 + fuse.load_side_a i house_config.yaml.
# Utan båda är beteendet exakt som förut.
_load_cfg = house_cfg.get("load_meter") or {}
homeassistant.configure_load_meter(_load_cfg.get("entities"))
LOAD_FUSE_A = float((house_cfg.get("fuse") or {}).get("load_side_a") or 0)
LOAD_GUARD = LOAD_FUSE_A > 0 and all(homeassistant.LOAD_METER.get(_k) for _k in ("current_l1", "current_l2", "current_l3"))
if _load_cfg or LOAD_FUSE_A:
    if LOAD_GUARD:
        print(f"🛡️ Säkringsskydd: lastsidans mätpunkt aktiv (säkring {LOAD_FUSE_A:g} A) - nät- och lastsida räknas var för sig, lägsta taket gäller.")
    else:
        print("⚠️ Lastsidans mätpunkt är bara delvis konfigurerad (kräver load_meter.entities.current_l1..3 OCH fuse.load_side_a) - ignoreras.")
car_ids = [c.id for c in car_drivers]
CAR_SPECS = house_config.car_specs(house_cfg)
# Inlärda faser/maxström per bil (ev_limits.py) - bara där installationen inte själv anger dem
_EV_EXPLICIT = {ev["id"]: {"phases": "phases" in (ev.get("charger") or {}), "max_a": "max_a" in (ev.get("charger") or {})}
                for ev in (house_cfg.get("evs") or []) if ev.get("id")}
_ev_learn = ev_limits.LimitLearner(_ew_settings.get("learned_ev"))
_EV_BY_ID = {ev["id"]: ev for ev in (house_cfg.get("evs") or []) if ev.get("id")}   # bilarna ur installationen per id
_last_ready_sig = [None]
for _c, _chg in _ev_learn.apply(CAR_SPECS, _EV_EXPLICIT).items():
    print(f"🚗 {CAR_SPECS[_c]['name']}: inlärt av laddningarna {_chg} (installationen anger inte detta)")
_ev_learn_saved = {"at": time.time(), "sig": str(_ev_learn.data)}
for _ev in house_cfg.get("evs") or []:     # evs[].charge_block: single | split (standard split) - se ev_block.py
    if _ev.get("id") in CAR_SPECS:
        CAR_SPECS[_ev["id"]]["charge_block"] = str(_ev.get("charge_block") or "split").lower()
settings.set_fuse_size_from_house_config(house_cfg)   # fuse.main_fuse_a i installationen -> inställningen (#129)
# Namnet i HA-sensorn sensor.smartbox_<namn>_batteri: evs[].ha_name, annars bilens id
CAR_HA_NAME = {ev["id"]: re.sub(r"[^a-z0-9_]", "_", str(ev.get("ha_name") or ev["id"]).lower())
               for ev in house_cfg.get("evs", []) or [] if ev.get("id")}   # {bil: {name, max_a, phases}} - laddboxens faser ("1"/"3"/"auto") och maxström
ev_allocations = {physical_id: None for physical_id in physical_charger_drivers}
print(f"✅ house_config.yaml: {len(car_drivers)} bil(ar) ({car_ids}), värmepump={type(heat_pump_driver).__name__}, "
      f"sol={type(solar_driver).__name__}, spa={type(spa_driver).__name__}, laddare={list(physical_charger_drivers.keys())}")

telemetry.send_driver_snapshot(house_cfg)  # obligatorisk telemetri, se telemetry.py och README
import i18n_py
i18n_py.install_print()                  # tilläggsloggen på installationens språk (före loggens och telemetrins krokar)
ew_journal.install("motor")              # installationens logg: allt som skrivs ut, i husets databas (ew_journal.py)
telemetry.install_error_hook(house_cfg)    # "❌"-fel -> modul.funktion + feltyp (aldrig texten), se telemetry.py

# Ny installation (house_config.yaml fortfarande i princip tomt) → EN envägs-notis i HA:s
# eget notisfält (persistent_notification, ligger kvar tills användaren kryssar bort den -
# ingen hourly-timer, ingen ny kanal att hålla koll på) som pekar mot entitetsväljaren.
# Länken härleds från HA:s EGEN internal_url/external_url (redan korrekt ifylld av
# användaren) - vi kan inte pålitligt gissa värdens LAN-IP inifrån en bridge-container.
if not car_drivers and isinstance(heat_pump_driver, house_config.NullHeatPumpDriver) \
        and isinstance(solar_driver, house_config.NullSolarDriver) and isinstance(spa_driver, house_config.NullSpaDriver):
    ha_url = homeassistant.get_own_base_url()
    if ha_url:
        parts = urlsplit(ha_url)
        # webdashboard terminerar ingen egen TLS (bekräftat: bara vanlig uvicorn-HTTP på
        # 8503) - tvinga http:// oavsett HA:s eget schema, annars blir länken trasig.
        dashboard_url = urlunsplit(("http", f"{parts.hostname}:8503", "", "", ""))
        # #271: notisen går inte genom webbläsarens översättare. Länken byts mot URL före
        # uppslagning, annars hamnar värdens siffror i ordliste-nyckeln.
        _lang = i18n_py.language()
        _title = "EnergyWizard: slutför installationen"
        _msg = ("Inget hittat än i din house_config.yaml. Gå till [entitetsväljaren](URL) "
                "för att hitta din värmepump, bilar, solceller m.m. automatiskt.")
        homeassistant.send_persistent_notification(
            "energywizard_setup",
            "🔆 " + i18n_py.tr(_title, _lang),
            i18n_py.tr(_msg, _lang).replace("URL", dashboard_url),
        )
        print(f"🔆 Ny installation upptäckt - skickade en påminnelse till HA:s notisfält ({dashboard_url}).")
    else:
        print("⚠️ Ny installation upptäckt, men kunde inte läsa HA:s internal_url/external_url för att skicka en påminnelse.")

# ============================================================
# 🚀 UPPSTARTSKONTROLL
# ============================================================
print("🤖 Kontrollerar initialt tillstånd för värmepumpen...")
if heat_pump_driver.reset_curve_offset():          # Matter-lagret: en förskjutning från före omstarten ska aldrig ligga kvar
    print("✅ Värmekurvans förskjutning nollställd vid start.")
initial_pump_data = heat_pump_driver.read_sensors()
if initial_pump_data:
    if initial_pump_data.get("operating_mode") == 0:
        print("🚨 UPPSTARTSKONTROLL: Pumpen är i läge 0 (Av). Tvingar omedelbart till 1 (Auto)!")
        notifier.send_emil("🚨 Värmepump i läge 0!", "EnergyWizard upptäckte att pumpen var avstängd vid uppstart. Tvingar igång den till Auto.")
        heat_pump_driver.set_operating_mode(1)
        logger.set_override("pump_operating_mode", "auto")
    else:
        print(f"✅ UPPSTARTSKONTROLL: Pumpen är i läge {initial_pump_data.get('operating_mode')} (OK).")
else:
    print("⚠️ UPPSTARTSKONTROLL: Kunde inte läsa värmepumpen vid uppstart.")

if HAS_SPA:                                   # #156: inget spabad -> ingen spa-rad eller -anrop
    print("🤖 Säkerställer att spabadets smartplug (Shelly) är påslagen...")
    spa_driver.set_plug_power(True)

# Tillståndsvariabler
last_minute          = None
last_quarter         = None
last_weather_update  = None
current_mode         = "EXPENSIVE"
current_decision     = "Startar..."
current_decision_items = []
current_chosen_water = decisions.WATER_OFF
current_chosen_temp  = 200
indoor_temp          = None  # FIX: för-initieras så pumpen offline vid uppstart inte ger NameError
# FIX: borttagna döda variabler last_kwh, solar_water, solar_heat (skrevs aldrig om/lästes aldrig)

last_sent_temp           = None
last_sent_water          = None
water_sp = water_setpoints.WaterSetpoints()
_hot_water_monitor = hot_water_monitor.Monitor()
last_sent_spa_target     = None
last_sent_spa_eco        = None
last_sent_operating_mode = None
last_pump_operating_mode = None

# --- NOTIS-TILLSTÅND ---
last_morning_notify_date = None
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
last_ev_status       = {}          # bil -> laddboxens senaste status (för "laddningen startade"-aviseringen)
last_appliance_running = {}   # hushållsmaskin -> körde den förra varvet (appliances i installationen)
# Säkerhetslarm för kallt inne (auto-värme kan vara avstängd i manuellt pumpläge)
INDOOR_COLD_ALERT_C  = 18.0
indoor_cold_alerted  = False
# Kallt inne räknas först efter 30 min i följd (sustained.py): ingen notis eller tvångsvärme för en vädring
import sustained
_cold_alert_watch = sustained.Sustained()
_cold_gpm_watch = sustained.Sustained()
last_sent_solar_limit = None
last_solar_write_at = None   # när exportgränsen senast skrevs (solar_write_guard.py)
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
_soc_mem = _dd(lambda: (None, None)); _soc_mem.update({"loaded": False})   # bil -> (värde, tid); "<bil>_wake"/"<bil>_poll" -> tid   # (värde, tid för senaste LIVE-värde)
# Stalled-charging-vakt (2026-10-30): om ström beordras men laddaren inte faktiskt drar ström,
# är "status" fastnad på ett ord turn_on-villkoret inte känner igen. Mäter verklig ström istället.
_ev_stall = _dd(lambda: None)   # bil -> tidpunkt sedan vi först sett 0A trots beordrad ström
EV_STALL_RETRY_MIN = 8          # så länge väntar vi innan vi tvingar ett nytt turn_on
EV_STALL_ALERT_MIN = 25         # så länge innan vi varnar Emil (annars tyst retry)
EV_STALL_CURRENT_A = 2.0        # under detta anses laddaren inte dra ström alls
# Morgongolv-larm (2026-10-30): varnar Emil i god tid om en bil riskerar missa 50%-golvet kl 06,
# istället för att han upptäcker det när han redan sitter i bilen. Larmar max en gång/dag/bil.
_morning_floor_alerted = _dd(lambda: None)
MORNING_FLOOR_WARN_MIN = 90     # varna när så här många minuter (eller färre) kvar till 06 och fortfarande under golvet
# Missat morgonmål (2026-11-12): samla varför under natten, larma EN gång efter deadline om SoC fortfarande under målet.
_ev_need_watch = _dd(lambda: {
    "zero_order_min": 0.0, "stall_min": 0.0, "last_ordered": 0.0,
    "last_power": 0.0, "last_status": None, "sibling_power": False,
})
_missed_charge_alerted = _dd(lambda: None)
_EV_NEED_LOOP_MIN = 1.0  # main-loopen är ~1 min; används för att ackumulera minuter
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

_ftw_sig = None


def _publish_ftw_status():
    """Skriver FTW-enheternas läge till inställningsfilen (webben läser den) - bara när läget ändrats."""
    global _ftw_sig
    try:
        from drivers import ftw_device
        st = ftw_device.status()
        sig = str([(s["driver"], s["ok"], s["has"], (s["error"] or "").split(":")[0]) for s in st])
        if sig != _ftw_sig:
            _ftw_sig = sig
            _ew_settings.update(ftw_status=st or None)
    except Exception as e:
        print(f"ℹ️ FTW-status kunde inte sparas: {e}")


_pv_hist = []   # de senaste minutvärdena för solproduktion (för att upptäcka fastfrusna solvärden)
_meter_freeze = health.MeterFreeze()   # upptäcker en nätmätare (Tibber) som står still på samma värden (falsk 'oförklarad last')
_sensor_watch = health.SensorWatch(grace_min=30)   # varnar när en sensor som fungerat tystnat >30 min
_link_watch = health.LinkWatch(min_outage_min=5)   # sammanfattar HA-avbrott >5 min när HA är tillbaka
SENSOR_LABELS = homeassistant.indoor_sensor_labels()   # användarens valda innegivare (uppdateras varje varv)

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
        for _car in car_ids:
            _soc_col = car_log.car_log_column(_car, "soc")
            _stale_col = car_log.car_log_column(_car, "soc_stale")
            if not _soc_col or not _stale_col:
                continue
            try:                                      # en bil vars kolumner inte finns än ska inte stoppa de andra
                with _engine.connect() as _c:
                    _row = _c.execute(_sqltext(
                        f"SELECT {_soc_col}, timestamp FROM sensor_log WHERE {_soc_col} IS NOT NULL "
                        f"AND COALESCE({_stale_col}, 0) = 0 ORDER BY timestamp DESC LIMIT 1")).fetchone()
                if _row and _row[0] is not None:
                    _soc_mem[_car] = (float(_row[0]), _row[1])
            except Exception:
                pass
        _soc_mem["loaded"] = True
        print("🔋 Senast kända batterinivåer inlästa: " + ", ".join(f"{CAR_SPECS.get(c, {}).get('name', c)} {_soc_mem[c][0]} %" for c in car_ids))
    except Exception as _e:
        print(f"⚠️ Kunde inte läsa senast kända batterinivåer: {_e}")

_last_logged_charger_status = _dd(lambda: None)

def _log_charger_status_if_changed(car_id, charger_data):
    """Loggar laddarens råa status varje gång den ändras (inte varje loop), så vi kan se
    exakt vilket statusord som gäller när laddningen fastnar - annars osynligt (main.py 2026-10-30)."""
    status = charger_data.get("status") if charger_data else None
    if status != _last_logged_charger_status.get(car_id):
        print(f"🔌 {car_id.capitalize()}-laddare: status = {status!r}")
        _last_logged_charger_status[car_id] = status

import ev_hold as _ev_hold_mod
import ev_missed as _ev_missed_mod
_goal_risk_alerted = {}   # #390: bil -> mål (klar-tid) som det redan aviserats om
import ev_in_meter
_EV_METER = {"in": None, "at": 0.0}
try:
    import ew_settings as _ews0
    _EV_METER["in"] = _ews0.get("ev_in_meter")
except Exception:
    pass
import control_journal
import shadow
_journal: list = []
_ev_hold = _ev_hold_mod.HoldWatch()
_ev_hold_now: dict = {}
_ev_hold_state = {"stored": None}
_EV_NAMES = {ev.get("id"): ev.get("name") or str(ev.get("id")).capitalize() for ev in (house_cfg.get("evs") or []) if ev.get("id")}


def _check_ev_stall(car_id, amps, charger_data, charger_id, phase_switch_active, now_dt):
    """Stalled-charging-vakt: om vi beordrat ström men laddaren mätbart inte drar någon,
    tvingar vi fram ett nytt turn_on oavsett status-ord (se 2026-10-30, Leaf-incidenten natt
    28/29 okt då bilen stod still hela natten trots 'Laddar enligt schema' i loggen)."""
    if amps <= 0 or phase_switch_active:
        _ev_stall[car_id] = None
        return
    actual_a = charger_data.get("current_a") if charger_data else None
    if actual_a is not None and actual_a >= EV_STALL_CURRENT_A:
        _ev_stall[car_id] = None
        return
    since = _ev_stall.get(car_id)
    if since is None:
        _ev_stall[car_id] = now_dt
        return
    stalled_min = (now_dt - since).total_seconds() / 60.0
    if stalled_min >= EV_STALL_RETRY_MIN:
        status = charger_data.get("status") if charger_data else None
        print(f"⚠️ {car_id.capitalize()}: {amps}A beordrat men laddaren drar ~0A i {stalled_min:.0f} min (status={status!r}). Tvingar turn_on igen.")
        charger_turn_on(charger_id)
        _ev_stall[car_id] = now_dt - timedelta(minutes=EV_STALL_RETRY_MIN - 2)  # försök igen om ~2 min, inte varje loop
        if stalled_min >= EV_STALL_ALERT_MIN:
            notifier.send_emil(
                f"⚠️ {car_id.capitalize()} laddar inte",
                f"{amps}A beordrat i {stalled_min:.0f} minuter men laddaren drar ingen ström "
                f"(status: {status}). EnergyWizard försöker starta om laddningen, men kolla kabeln/laddaren.",
                {"tag": f"ev_stall_{car_id}"},
                key="elbil",
            )

def _check_morning_floor(car_id, soc, plugged_in, now_dt):
    """Oberoende larm-vakt: varnar Emil i god tid om en bil ser ut att missa 50%-golvet kl 06,
    istället för att han upptäcker det när han redan sitter i bilen (Leaf-incidenten natt 28/29 okt).
    Tar INTE över styrningen själv - planeraren (decisions.py) och stalled-vakten sköter det;
    detta är enbart ett larm om de ändå inte räcker."""
    if soc is None or not plugged_in or soc >= decisions.MORNING_MIN_SOC:
        return
    floor_today = now_dt.replace(hour=decisions.MORNING_HOUR, minute=0, second=0, microsecond=0)
    if now_dt >= floor_today:
        floor_today += timedelta(days=1)
    minutes_left = (floor_today - now_dt).total_seconds() / 60.0
    if minutes_left > MORNING_FLOOR_WARN_MIN:
        return
    today_key = floor_today.date()
    if _morning_floor_alerted.get(car_id) == today_key:
        return
    _morning_floor_alerted[car_id] = today_key
    print(f"🚨 Morgongolv-vakt: {car_id} på {soc:.0f}%, {minutes_left:.0f} min kvar till golvet (50% kl {decisions.MORNING_HOUR:02d}:00). Larmar.")
    notifier.send_emil(
        f"🚨 {car_id.capitalize()} riskerar missa 50%-golvet kl 06",
        f"{soc:.0f}% nu, {minutes_left:.0f} min kvar till 06:00. Planen ska tvinga full ström, men kolla gärna att kabeln sitter i och att laddaren faktiskt drar ström.",
        {"tag": f"morning_floor_{car_id}"},
        key="elbil",
    )

def _track_ev_need(car_id, soc, ordered_a, charger_data, sibling_charging, now_dt):
    """Ackumulera varför en bil under morgonmålet inte får ström - underlag till missad-laddning-notisen."""
    if soc is None or soc >= decisions.MORNING_MIN_SOC:
        _ev_need_watch[car_id] = {
            "zero_order_min": 0.0, "stall_min": 0.0, "last_ordered": 0.0,
            "last_power": 0.0, "last_status": None, "sibling_power": False,
        }
        return
    w = _ev_need_watch[car_id]
    power = float((charger_data or {}).get("power_kw") or 0.0)
    status = (charger_data or {}).get("status")
    ordered = float(ordered_a or 0)
    w["last_ordered"] = ordered
    w["last_power"] = power
    w["last_status"] = status
    if sibling_charging:
        w["sibling_power"] = True
    if ordered < 6:
        w["zero_order_min"] = float(w.get("zero_order_min") or 0) + _EV_NEED_LOOP_MIN
    elif power < 0.3:
        w["stall_min"] = float(w.get("stall_min") or 0) + _EV_NEED_LOOP_MIN

def _check_missed_charge(car_id, soc, plugged_in, now_dt):
    """Efter morgondeadline: en notis med ORSAK om bilen fortfarande är under 50 % (Leaf 11/12 nov)."""
    deadline = now_dt.replace(hour=decisions.MORNING_HOUR, minute=0, second=0, microsecond=0)
    # Före kl 06 gäller dagens deadline senare i natt; efter 06 samma morgon.
    if now_dt < deadline:
        return
    if not _ev_missed_mod.due_missed_alert(
        soc=soc, target_soc=decisions.MORNING_MIN_SOC, plugged_in=plugged_in,
        now=now_dt, deadline=deadline, already_key=_missed_charge_alerted.get(car_id),
    ):
        return
    _missed_charge_alerted[car_id] = deadline
    w = _ev_need_watch.get(car_id) or {}
    sibling = next((n for c, n in _EV_NAMES.items() if c != car_id), None)
    why = _ev_missed_mod.explain(
        soc=soc, target_soc=decisions.MORNING_MIN_SOC,
        ordered_a=float(w.get("last_ordered") or 0),
        power_kw=float(w.get("last_power") or 0),
        status=w.get("last_status"),
        minutes_zero_order=float(w.get("zero_order_min") or 0),
        minutes_stalled=float(w.get("stall_min") or 0),
        sibling_name=sibling,
        sibling_got_power=bool(w.get("sibling_power")),
        charger_note=(globals().get("all_overrides") or {}).get(f"{car_id}_limit_note") or None,
    )
    name = _EV_NAMES.get(car_id, car_id.capitalize())
    print(f"🚨 Missad laddning: {car_id} under morgonmålet. {why}")
    notifier.send_emil(
        f"🚨 {name} laddades inte klart inatt",
        why,
        {"tag": f"ev_missed_{car_id}_{deadline.date()}"},
        key="elbil",
    )

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
last_house_neg_warn = None
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

_ramp = ramp_budget.RampBudget()   # #399: bil och husbatteri delar säkringens utrymme vid ökningar


def _battery_fuse_cap_w(battery_w):
    """#399: husbatteriets högsta nätladdning mot säkringen (nät- och ev. lastsidan), elbilens nya ökning avräknad.
    None = ingen färsk mätdata (batteriet styrs då som förut)."""
    caps = []
    if fuse_model.is_fresh():
        caps.append(fuse_model.battery_charge_cap_w(_fuse_cfg["fuse_a"], battery_w, battery_cfg["phases"],
                                                    _fuse_cfg["margin_a"], reserved_a=_ramp.pending_a("battery")))
    if load_model is not None and load_model.is_fresh():
        caps.append(load_model.battery_charge_cap_w(LOAD_FUSE_A, battery_w, battery_cfg["phases"],
                                                    _fuse_cfg["margin_a"], reserved_a=_ramp.pending_a("battery")))
    caps = [c for c in caps if c is not None]
    return min(caps) if caps else None
last_sent_ev_limit = {}  # {car_id: int|None} - ersätter de tidigare hårdkodade _nissan/_tesla-varianterna

_ev_heating_model_cache = {"at": None, "model": None}


def _ev_heating_model(now):
    """Värmemodellen för laddplanen (ev_planning.heating_adjustment i house_config.yaml, standard AV -> None).
    k (kW per grad under balanstemperaturen) lärs ur senaste `window_days` dygnens last och utetemperatur, eller anges
    för hand (kw_per_degree: <tal>). Räknas om var 6:e timme; vid fel eller för litet underlag behålls senaste modell.
    Lasten räknas som i learning.get_base_load_profile (nätimport minus loggad billaddning). Se ev_heating.py."""
    opts = (house_cfg.get("ev_planning") or {}).get("heating_adjustment") or {}
    if not opts.get("enabled"):
        return None
    cache = _ev_heating_model_cache
    if cache["at"] is not None and (now - cache["at"]) < timedelta(hours=6):
        return cache["model"]
    model = cache["model"]
    try:
        import pandas as pd
        balance = float(opts.get("balance_temp_c", 10.0))
        days = int(opts.get("window_days", 30))
        with logger.get_db() as conn:
            loads = pd.read_sql(f"""
                SELECT timestamp AT TIME ZONE 'Europe/Stockholm' AS ts,
                       GREATEST(GREATEST(net_power, 0) / 1000.0 - COALESCE(ev_power_kw, 0) - COALESCE(ev_carport_power_kw, 0), 0) AS other_kw
                FROM sensor_log
                WHERE timestamp >= NOW() - INTERVAL '{days} days' AND net_power > 0
            """, conn)
            temps = pd.read_sql(f"""
                SELECT timestamp AT TIME ZONE 'Europe/Stockholm' AS ts, outdoor_temp AS temp
                FROM sensor_log
                WHERE timestamp >= NOW() - INTERVAL '{days} days' AND outdoor_temp IS NOT NULL
            """, conn)
            if len(temps) < 100:     # ingen utegivare i loggen: använd väderprognosens egna timvärden bakåt i tiden
                temps = pd.read_sql(f"""
                    SELECT timestamp AT TIME ZONE 'Europe/Stockholm' AS ts, temp
                    FROM weather_forecast
                    WHERE timestamp >= NOW() - INTERVAL '{days} days' AND timestamp < NOW() AND temp IS NOT NULL
                """, conn)
        df = ev_heating.hourly_frame(loads, temps)
        manual = opts.get("kw_per_degree", "auto")
        if isinstance(manual, (int, float)) and not isinstance(manual, bool):
            fitted = ev_heating.model_from_slope(df, balance, float(manual))
        else:
            fitted = ev_heating.fit_heating_model(df, balance)
        if fitted:
            fitted["cap_kw"] = float(opts.get("max_base_kw", 10.0))
            model = fitted
            print(f"🌡️ EV-plan: värmemodell k={fitted['k_kw_per_degree']:.3f} kW/°C under {balance:g} °C "
                  f"(referens {fitted['hd_ref']:.1f} gradtimmar/h, {fitted['n']} timmar).")
        else:
            print("ℹ️ EV-plan: värmemodellen saknar underlag (för få timmar eller för jämn temperatur) - ingen justering.")
    except Exception as _he:
        print(f"⚠️ EV-planens värmemodell hoppade över: {_he}")
    cache.update(at=now, model=model)
    return model
last_ev_full_notified = _dd(lambda: False)
raw_ev_schedule = settings.get_ev_schedule(car_ids)
ev_schedule = {}
for car, days in raw_ev_schedule.items():
    ev_schedule[car] = {int(k): v for k, v in days.items() if str(k).isdigit()}
ev_charge_plan = None

ev_connection_state = {c: {'connected': False, 'time': None, 'soc_start': None, 'soc_5min': None, 'charge_completed': False, 'last_status': None} for c in car_ids}

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
        for car in car_ids:
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


# Laddboxens status som betyder att ingen bil är inkopplad - en lista för hela motorn (#174: fem olika listor, ingen
# kände igen Garo/generiska laddboxars 'not_connected', så en frånkopplad bil räknades som inkopplad).
_NOT_PLUGGED = {"disconnected", "not_connected", "notconnected", "unplugged", "available", "offline", "unknown",
                "unavailable", "error", "none", ""}


def charger_connected(charger_data) -> bool:
    if not charger_data:
        return False
    st = charger_data.get("status")
    return st is not None and str(st).strip().lower().replace(" ", "_") not in _NOT_PLUGGED


def update_soc_tracker(car_id, car_data, charger_data, now, schedule):
    state = ev_connection_state[car_id]
    is_connected = charger_connected(charger_data)
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
        last_sent_limit_for_car = last_sent_ev_limit.get(car_id)
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

# Termisk säkringsmodell (fuse_guard.py): matas var 10:e sekund med Tibbers fasströmmar.
# Säkringsstorlek/marginal och laddar-ID:n uppdateras i minutloopen; nödbromsen i 10-sekunders-
# loopen använder senast kända värden (före första minuten: decisions.MAX_FUSE_A, inga laddare).
fuse_model = fuse_guard.FuseThermalModel()
load_model = fuse_guard.FuseThermalModel() if LOAD_GUARD else None   # lastsidans mätpunkt (valfri), samma modell
_sun_cache = {"t": 0.0, "soon": None, "day": None}
_climate_watch = {}             # bil-id -> car_climate_watch.ClimateWatch
_fuse_cfg = {"fuse_a": decisions.MAX_FUSE_A, "margin_a": 0.0}
_fuse_charger_ids = {}
_hour_import = {"h": None, "wh": 0.0, "t": None}
_bat_meter_freeze = battery_control.MeterFreeze()   # samma värde i 10 min = mätaren har fastnat (eget namn: _meter_freeze är health-varianten, rad ~298)
_meter_ok_at = {"t": None}                           # senaste lyckade avläsning av elmätaren   # köpt energi denna timme (reserv när mätaren saknar timsensor)

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

        _trip_grid = {}
        tibber = homeassistant.read_power_meter()
        if tibber is not None and not _bat_meter_freeze.update(tibber["net_power_w"], time.time()):
            _meter_ok_at["t"] = time.time()
            fast_net.append(tibber["net_power_w"])
            # Fasströmmar är valfria (en mätare med bara nettoeffekt har inga) - då får säkrings-
            # modellen ingen data och gpm.py använder den gamla formeln.
            if None not in (tibber["l1_a"], tibber["l2_a"], tibber["l3_a"]):
                fast_hl1.append(tibber["l1_a"])
                fast_hl2.append(tibber["l2_a"])
                fast_hl3.append(tibber["l3_a"])
                fuse_model.update([tibber["l1_a"], tibber["l2_a"], tibber["l3_a"]])
            # Reserv för effektvakten när mätaren saknar en timsensor: köpt energi denna timme,
            # integrerad ur nettoeffekten (10-sekundersloopen).
            _hk = now.replace(minute=0, second=0, microsecond=0)
            if _hour_import.get("h") != _hk:
                _hour_import.update(h=_hk, wh=0.0, t=None)
            _t = time.time()
            if _hour_import["t"] is not None:
                _hour_import["wh"] += max(0.0, tibber["net_power_w"]) * min(60.0, _t - _hour_import["t"]) / 3600.0
            _hour_import["t"] = _t
            # Nödbroms, nätsidan: en fas över 1,2 × säkringen. Beräknas här men skickas först efter lastsidans
            # kontroll nedan, så att båda mätpunkterna ger ETT beslut (lägsta gränsen per bil), inte två avdrag.
            try:
                _trip_grid = fuse_guard.fast_trip_limits(fuse_model, _fuse_cfg["fuse_a"],
                                                         {c: v for c, v in last_sent_ev_limit.items() if c in _fuse_charger_ids},
                                                         margin_a=_fuse_cfg["margin_a"], min_charge_a=EV_MIN_CHARGE_AMPS)
            except Exception as _fe:
                print(f"⚠️ Säkringsskyddets nödbroms (nät) hoppade över: {_fe}")

        # Lastsidans mätpunkt (valfri). Körs oberoende av nätmätaren; en tyst/frusen lastmätare ger ingen nödbroms
        # (bara en färsk avläsning används) och minutloopen faller då tillbaka på ett försiktigt tak.
        _trip_load = {}
        if load_model is not None:
            try:
                _lm = homeassistant.read_load_meter()
                if _lm is not None:
                    load_model.update([_lm["l1_a"], _lm["l2_a"], _lm["l3_a"]])
                    _trip_load = fuse_guard.fast_trip_limits(load_model, LOAD_FUSE_A,
                                                             {c: v for c, v in last_sent_ev_limit.items() if c in _fuse_charger_ids},
                                                             margin_a=_fuse_cfg["margin_a"], min_charge_a=EV_MIN_CHARGE_AMPS)
            except Exception as _le:
                print(f"⚠️ Säkringsskyddets nödbroms (last) hoppade över: {_le}")

        # Gemensam nödbroms för båda mätpunkterna.
        try:
            for _car, _amps in fuse_guard.merge_trip_limits(_trip_grid, _trip_load).items():
                _reason = f"Säkringsskydd: fas över {fuse_guard.TRIP_FACTOR} × säkringen"
                if charger_set_limit(_fuse_charger_ids[_car], _amps, reason=_reason):
                    last_sent_ev_limit[_car] = _amps
                    print(f"🚨 {_reason} - stryper {_car} till {_amps} A direkt.")
        except Exception as _fe:
            print(f"⚠️ Säkringsskyddets nödbroms hoppade över: {_fe}")

        # ============================================================
        # 📝 1-MINUTS-TASK – Samla och Spara data
        # ============================================================
        if current_minute != last_minute:
            if current_minute == 7:      # en gång i timmen: månadens sponsornotis i HA (om den är på och inte skickad)
                try:
                    import sponsor, i18n_routes
                    if sponsor.send_ha_notice(homeassistant.call_service, i18n_routes.default_language(), now.replace(tzinfo=None)):
                        print("❤️ Skickade månadens sponsornotis till Home Assistant (kan stängas av i inställningarna).")
                except Exception as _se:
                    print(f"⚠️ Sponsornotisen hoppades över: {_se}")
            cfg = settings.get_settings()
            all_overrides = logger.get_all_overrides()
            if timed_override.expired(all_overrides, "hotwater", time.time()):     # #397: tiden gick ut -> Auto
                logger.set_override("hotwater", "auto")
                logger.set_override("hotwater_until", "")
                all_overrides.update(hotwater="auto", hotwater_until="")
                print("💧 Varmvatten: tiden gick ut - tillbaka till Auto.")
            ai_thoughts = []

            # Bilens värme från appen: följ upp tills bilen faktiskt värmer, annars säg till (car_climate_watch.py).
            for _ev in house_cfg.get("evs", []) or []:
                _cid, _cent = _ev.get("id"), (_ev.get("entities") or {}).get("climate")
                if not _cid or not _cent:
                    continue
                _key = f"{_cid}_climate"
                try:
                    _w = _climate_watch.setdefault(_cid, car_climate_watch.ClimateWatch())
                    _want = all_overrides.get(_key)
                    _on_req = _want not in (None, "", "off")
                    _res = _w.step(_want, homeassistant._get_raw_state(_cent) if _on_req else None, time.time(),
                                   homeassistant._get_numeric_attribute(_cent, "current_temperature") if _on_req else None)
                    _name = _cid.capitalize()
                    if _res == "resend":
                        _t = float(_want) if str(_want).replace(".", "", 1).isdigit() else 21.0
                        homeassistant.set_car_climate(_cent, "heat_cool", _t)
                        print(f"🚗 {_name}: värmen har inte startat än - skickar igen (försök {_w.tries}).")
                    elif _res == "reheat":
                        # Inte om bilen kört iväg (bilens tracker, samma som klimatschemat; okänd position = hemma)
                        _trk = (_ev.get("entities") or {}).get("tracker")
                        _away = False
                        if _trk:
                            _lat = homeassistant._get_numeric_attribute(_trk, "latitude")
                            _lon = homeassistant._get_numeric_attribute(_trk, "longitude")
                            _d = calc_distance(weather.LATITUDE, weather.LONGITUDE, _lat, _lon) if _lat and _lon else None
                            _away = _d is not None and _d > 0.5
                        if _away:
                            _w._reset()
                            logger.set_override(_key, "off")
                            print(f"🚗 {_name}: bilen har kört iväg - värmer inte igen, uppföljningen avslutad.")
                        else:
                            _t = float(_want) if str(_want).replace(".", "", 1).isdigit() else 21.0
                            homeassistant.set_car_climate(_cent, "heat_cool", _t)
                            print(f"🚗 {_name}: kupén höll inte temperaturen 10 min efter att värmen gick av - värmer igen ({_w.reheats}).")
                    elif _res == "ok":
                        print(f"🚗 {_name}: värmen är igång i bilen - håller temperaturen en timme från knapptrycket.")
                    elif _res == "refresh":
                        # Bilens läge kan vara gammalt (Tesla uppdaterar inte medan den sover): be om en färsk avläsning
                        _rb = (_ev.get("entities") or {}).get("refresh_button") or (_ev.get("entities") or {}).get("update_button")
                        threading.Thread(target=homeassistant.refresh_entity, args=(_cent, _rb), daemon=True).start()
                    elif _res == "done":
                        logger.set_override(_key, "off")
                        print(f"🚗 {_name}: värmen har hållits en timme - uppföljningen avslutad.")
                    elif _res == "give_up":
                        logger.set_override(_key, "off")
                        print(f"🚗 {_name}: värmen startade inte efter flera försök - aviserar.")
                        notifier.send_emil(f"🥶 {_name}: värmen startade inte",
                                           f"Bilen svarade inte på värmekommandot efter {car_climate_watch.MAX_TRIES + 1} försök på 12 minuter "
                                           f"(tillverkarens moln startade aldrig klimatet). Prova igen, eller starta från tillverkarens app.")
                except Exception as _ce:
                    print(f"⚠️ Bilvärmen ({_cid}): {_ce}")
            
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

            raw_ev_schedule = settings.get_ev_schedule(car_ids)
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
            raw_solar_limit = solar_driver.get_export_limit_pct()
            # Bara växelriktare som går att begränsa har en gräns att tappa (#134: förut larmade "SolarEdge Limit Offline"
            # i hus utan SolarEdge - och utan solceller alls)
            if raw_solar_limit is None and not solar_driver.supports_curtailment():
                current_solar_limit_pct = 100.0
            elif raw_solar_limit is None:
                current_solar_limit_pct = 100.0
                if solar_modbus_offline_since is None:
                    solar_modbus_offline_since = now
                elif (now - solar_modbus_offline_since) > timedelta(minutes=10) and not last_solar_modbus_error_notified:
                    notifier.send_emil("⚠️ Solcellernas exportgräns offline", "Kunde inte läsa växelriktarens exportgräns. Antar 100 % produktion.")
                    last_solar_modbus_error_notified = True
            else:
                current_solar_limit_pct = raw_solar_limit
                solar_modbus_offline_since = None
                last_solar_modbus_error_notified = False

            # Bilarna ur installationen (drivrutin per bil, house_config.yaml evs[]) - inga bilnamn i motorn
            car_data = {}
            for _drv in car_drivers:
                try:
                    car_data[_drv.id] = _drv.read_state() or {}
                except Exception as _cde:
                    print(f"❌ Bilen {_drv.id} kunde inte läsas: {_cde}")
                    car_data[_drv.id] = {}
            if not _soc_mem["loaded"]:
                _load_last_known_soc()
                _po = list(physical_charger_drivers)
                ha_publisher.CHARGER_CARS = [(default_car_per_charger.get(_po[k]) if k < len(_po) else None) or f"laddbox_{k + 1}" for k in range(2)]
                ha_publisher.start()   # startar bakgrundstråden en gång
                _seed_sensor_watch()
            car_soc_stale = {c: _remember_soc(c, car_data.get(c), now) for c in car_ids}
            car_soc = {c: (car_data.get(c) or {}).get("soc") for c in car_ids}

            if _cached_ev_profiles_time is None or (now - _cached_ev_profiles_time) > timedelta(hours=6):
                _order = list(physical_charger_drivers)
                for _c in car_ids:
                    # Bilens hemmaladdbox i installationens ordning: första loggas som ev_status, andra ev_carport_status
                    _home = next((p for p, c in default_car_per_charger.items() if c == _c), None)
                    _idx = _order.index(_home) if _home in _order else car_ids.index(_c)
                    _cached_ev_profiles[_c] = learning.get_ev_habit_profile(_c, status_col="ev_status" if _idx == 0 else "ev_carport_status")
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
            heat_pump_driver.tick()                         # släpper en tidsbegränsad paus (Matter-lagret) när tiden gått ut
            telemetry.maybe_send_daily(house_cfg)           # daglig "aktiv"-signal
            _publish_ftw_status()                           # FTW-enheter som inte svarar syns på Översikt (#184-#186)
            try:
                import update_check
                update_check.notify_if_new()                # en avisering per ny version (kollas högst var sjätte timme)
            except Exception:
                pass
            async def fetch_heavy_data():
                return await asyncio.gather(
                    asyncio.to_thread(heat_pump_driver.read_sensors),
                    asyncio.to_thread(nordpool.get_price_info, cfg["cheap_hours_count"])
                )
            pump_data, price_tuple = asyncio.run(fetch_heavy_data())
            current_price, dynamic_limit, strategy, all_prices = price_tuple
            # Explicit nonessential devices only; never switch from yesterday's
            # fallback profile or a missing current interval. Prices use the
            # configured contract's complete import-price calculation.
            if _smart_plugs.devices:
                try:
                    _plug_price = smart_plugs.policy_price(current_price, strategy, now, nordpool.planning_buy_price)
                    smart_plugs.run(_smart_plugs, _plug_price, now.timestamp())
                except Exception as e:
                    print(f"Smart plug policy skipped: {type(e).__name__}")

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
            # Solutsikt för husvärmen (Prio 5): sol de närmaste timmarna och nästa dagsljus värmer huset genom
            # fönstren, så motorn lagrar mindre värme då. Räknas om var 15:e minut (väderprognosen ändras inte oftare).
            if time.time() - _sun_cache["t"] > 900:
                try:
                    _sun_cache["soon"] = weather.sun_outlook(now, 4)
                    _sun_cache["day"] = weather.sun_outlook(now, 16)
                except Exception as _se:
                    print(f"⚠️ Solutsikt: {_se}")
                _sun_cache["t"] = time.time()

            # The forecast already uses the selected HA source or learned fallback.
            # Keep the profile for the clear-sky diagnostics below, without replacing
            # an external forecast with the internal model a second time.
            solar_profile = learning.get_solar_profile()
            
            solar_data   = solar_driver.read_production()
            ha_temps     = homeassistant.read_temperatures()
            # Laddboxarna ur installationen, i installationens ordning (den ordningen styr också loggkolumnerna)
            physical_charger_data = {}
            for _pid, _pdrv in physical_charger_drivers.items():
                try:
                    physical_charger_data[_pid] = _pdrv.read_state()
                except Exception as _ce:
                    print(f"⚠️ Laddbox {_pid}: kunde inte läsas: {_ce}")
                    physical_charger_data[_pid] = None
            _charger_list = [physical_charger_data.get(p) for p in physical_charger_drivers]
            gecko_data   = spa_driver.read_state()
            spa_power_data = spa_driver.read_power_detail() if HAS_SPA else {}
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
            # Hushållsmaskiner ur installationen (appliances: [{name, entity}]) - "startad"-notis, inget fast märke
            appliance_states = {a["name"]: homeassistant._get_raw_state(a["entity"])
                                for a in (house_cfg.get("appliances") or []) if isinstance(a, dict) and a.get("name") and a.get("entity")}
            # Bilarnas position (entities.tracker per bil i installationen)
            trackers = {}
            for _ev in house_cfg.get("evs", []) or []:
                _tr = (_ev.get("entities") or {}).get("tracker")
                if _ev.get("id") and _tr:
                    trackers[f"{_ev['id']}_lat"] = homeassistant._get_numeric_attribute(_tr, "latitude")
                    trackers[f"{_ev['id']}_lon"] = homeassistant._get_numeric_attribute(_tr, "longitude")

            # Spabad Watchdog (bara med ett spabad i installationen - annars såg "inget spa" ut som "spa offline", #123)
            if HAS_SPA and (gecko_data is None or gecko_data.get("current_temp") is None):
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
                        spa_driver.set_plug_power(False)
                        time.sleep(10)
                        spa_driver.set_plug_power(True)
                    threading.Thread(target=reboot_plug_async).start()
            else:
                if spa_offline_since is not None:
                    print("✅ Spabad online igen! Nollställer återstartsekvensen.")
                    if spa_reboot_stage > 0 and all_overrides.get("notify_spa_reconnect", "auto") != "false":
                        notifier.send_emil("✅ Spabad återanslutet", "Anslutningen till spabadet har återupprättats efter omstart!")
                    spa_offline_since = None
                    spa_reboot_stage = 0

            # Handshake och Bilallokering (Steg 4:4 - generisk, se smartbox/ev_handshake.py)
            physical_charger_connected = {p: charger_connected(d) for p, d in physical_charger_data.items()}

            # FIX: Teslans charging_state är platsoberoende (sant även vid supercharger borta) →
            # grinda plugged på GPS-hemma så en bil som laddar BORTA inte snor en hemma-laddare.
            def _gps_home_or_unknown(lat, lon):
                if lat is None or lon is None:
                    return True
                return calc_distance(weather.LATITUDE, weather.LONGITUDE, lat, lon) <= 0.5

            # "Är kabeln i?" är äkta bilspecifikt (olika märken rapporterar det olika) - en liten
            # funktion per KÄNT bilmärke, inte en gissad gemensam formel (se ev_handshake.py:s
            # docstring för varför). Ett bilmärke utan egen detektering byggd ger bara False,
            # overksamt precis som en Null-drivrutin - kraschar inte.
            def _car_cable_plugged(car_id):
                """Kabel i hemma: bilens egen kabelgivare (1.0), laddstatus (charging/stopped/complete) eller - när
                bilintegrationen saknar kabelgivare - att bilens egen laddbox är upptagen och bilen är hemma (GPS).
                Bilens egen laddbox och tracker kommer från installationen. Samma regel som förut för Tesla/Leaf."""
                d = car_data.get(car_id) or {}
                lat, lon = trackers.get(f'{car_id}_lat'), trackers.get(f'{car_id}_lon')
                home = _gps_home_or_unknown(lat, lon)
                own_conn = physical_charger_connected.get(default_physical_for_car.get(car_id), False)
                state = str(d.get("charging_state")).lower()
                cable = (d.get("plugged_in") == 1.0) or (state in ['charging', 'stopped', 'complete']) or (own_conn and home and lat is not None)
                return cable and (home or own_conn)

            default_physical_for_car = {c: p for p, c in default_car_per_charger.items()}
            car_plugged = {car_id: _car_cable_plugged(car_id) for car_id in car_ids}
            ev_allocations = ev_handshake.resolve_charger_allocations(
                physical_charger_connected, car_plugged, ev_allocations, default_car_per_charger
            )

            car_charger_id = {}
            car_charger_data = {}
            swapped = False
            for car_id in car_ids:
                physical_id = next((p for p, c in ev_allocations.items() if c == car_id), None) or default_physical_for_car.get(car_id)
                car_charger_id[car_id] = physical_id
                car_charger_data[car_id] = physical_charger_data.get(physical_id)
                if physical_id != default_physical_for_car.get(car_id, physical_id):
                    swapped = True
            if swapped:
                ai_thoughts.append("🔄 Handskakning aktiv: Bilarna har bytt laddplats med varandra! GPM styr rätt box.")

            for _c in car_ids:
                update_soc_tracker(_c, car_data.get(_c), car_charger_data.get(_c), now, ev_schedule)

            # Smart Hemkomst GPS
            for car in car_ids:
                lat = trackers.get(f'{car}_lat')
                lon = trackers.get(f'{car}_lon')
                dist = calc_distance(weather.LATITUDE, weather.LONGITUDE, lat, lon)
                
                if 0.5 < dist < 15.0 and dist < ev_gps_state[car]['prev_dist'] - 0.2:
                    if not ev_gps_state[car]['approaching']:
                        ev_gps_state[car]['approaching'] = True
                        print(f"📍 GPS: {CAR_SPECS.get(car, {}).get('name', car)} närmar sig hemmet! (Avstånd: {dist:.1f} km). Förallokerar.")
                        force_ev_plan_recalc = True
                elif dist <= 0.5 or dist >= 15.0 or ev_connection_state[car]['connected']:
                    ev_gps_state[car]['approaching'] = False
                    
                ev_gps_state[car]['prev_dist'] = dist
                
                if ev_gps_state[car]['approaching']:
                    ai_thoughts.append(f"📍 GPS: {CAR_SPECS.get(car, {}).get('name', car)} närmar sig hemmet ({dist:.1f} km bort). För-allokerar.")

            # Solinstrålning vs Prognos (CSI)
            # ROBUSTHET: SolarEdge-pv:n (solaredge_aktuell_effekt) fastnar ibland på stale värden
            # (t.ex. 5876 W minuter i rad) medan huset exporterar mer än så. Produktionen kan ALDRIG
            # vara mindre än nätexporten (fysik). Korrigera pv uppåt till minst exporten → räddar
            # house_consumption_w OCH den loggade pv:n (Ekonomi-sol-siffror). net från Tibber (U×I) är pålitlig.
            # Batteriet läses här (inte först vid husets förbrukning nedan): ett batteri som säljer till nätet står för
            # en del av exporten, och den får inte räknas som sol (#175: 7,7 kW "sol" mitt i natten).
            try:
                _battery_early = battery_driver.read_state() or {}
            except Exception:
                _battery_early = {}
            if solar_data is not None:
                _raw_pv = solar_data.get('pv_power_w') or 0
                _bat_pre = energy_balance.plausible_battery_w(_battery_early.get("power_w"),
                                                              getattr(battery_driver, "max_power_w", None))
                _pv_floor = energy_balance.pv_floor_from_export(_raw_pv, avg_net, _bat_pre)
                if _raw_pv < _pv_floor:
                    solar_data['pv_power_w'] = _pv_floor
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

            # Morgongolv-vakt (2026-10-30): oberoende säkerhetsnät för "50% kl 06 varje dag".
            # Körs VARJE loop (inte bara var 15:e min) så vi hinner larma/tvinga i tid om allt annat failat.
            # Missad-laddning-notis (2026-11-12): efter deadline, med orsak (0 A till syskon / awaiting_start).
            for _car_id in car_ids:
                _soc = car_soc.get(_car_id)
                _plugged = ev_connection_state[_car_id]['connected'] or ev_gps_state[_car_id]['approaching']
                _check_morning_floor(_car_id, _soc, _plugged, now)
                _check_missed_charge(_car_id, _soc, _plugged, now)

            # #200: ändras "klar senast" i Home Assistant räknas planen om direkt (inte först vid nästa kvart)
            _ready_sig = str([((_EV_BY_ID.get(_c) or {}).get("entities") or {}).get("ready_by") and
                              homeassistant._get_raw_state(_EV_BY_ID[_c]["entities"]["ready_by"]) for _c in car_ids])
            if _ready_sig != _last_ready_sig[0]:
                if _last_ready_sig[0] is not None:
                    force_ev_plan_recalc = True
                _last_ready_sig[0] = _ready_sig
            # EV Plan
            if ev_charge_plan is None or now.minute % 15 == 0 or force_ev_plan_recalc:
                last_ev_plan_time = now
                print("🧠 Beräknar ny EV-laddningsplan...")
                car_data_for_plan = {}
                for _c in car_ids:
                    car_data_for_plan[f"{_c}_soc"] = car_soc.get(_c)
                    car_data_for_plan[f"{_c}_phases"] = (car_charger_data.get(_c) or {}).get('phases')
                    car_data_for_plan[f"{_c}_plugged_in"] = ev_connection_state[_c]['connected'] or ev_gps_state[_c]['approaching']
                    # #200: "klar senast" ur en valfri HA-entitet (evs[].entities.ready_by / ready_soc)
                    _rents = (_EV_BY_ID.get(_c) or {}).get("entities") or {}
                    car_data_for_plan[f"{_c}_ready_by"] = homeassistant.read_ready_by(_rents.get("ready_by"), now)
                    car_data_for_plan[f"{_c}_ready_soc"] = homeassistant._get_numeric_state(_rents["ready_soc"]) if _rents.get("ready_soc") else None
                car_data_for_plan.update({
                    "car_ids": list(car_ids), "car_specs": CAR_SPECS,     # bilarna ur installationen (laddplanen har inga bilnamn)
                    "heating_model": _ev_heating_model(now),
                })
                ev_charge_plan = decisions.calculate_ev_charge_plan(now, ev_schedule, car_data_for_plan, cfg)
                try:
                    _persist_ev_plan(ev_charge_plan)
                except Exception as _e:
                    print(f"⚠️ Kunde inte spara laddplanen: {_e}")

            # Klimatschema Bil
            outdoor_temp_for_climate = pump_data.get("outdoor_temp") if pump_data else (forecast_temp or 10.0)
            climate_schedules = settings.get_climate_schedule(car_ids)
            away_mode_enabled = cfg.get("away_mode_enabled", False)
            away_return_date = cfg.get("away_return_date")  # FIX: saknades → NameError när bortaläge var på

            def handle_car_climate(car_id, sched, c_data, charger_data, climate_entity, outdoor_temp, dist_to_home):
                if not sched['enabled']: return
                is_connected = charger_connected(charger_data)
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

            # Varje bil med en klimatentitet i installationen (ingen hårdkodad bil, 2026-11-04). Avståndet ur bilens
            # device_tracker om den valts (entities.tracker), annars de gamla trackers-nycklarna.
            for _ev in house_cfg.get("evs", []) or []:
                _cid, _ents = _ev.get("id"), _ev.get("entities") or {}
                _cent = _ents.get("climate")
                if not _cid or not _cent:
                    continue
                try:
                    if _ents.get("tracker"):
                        _lat = homeassistant._get_numeric_attribute(_ents["tracker"], "latitude")
                        _lon = homeassistant._get_numeric_attribute(_ents["tracker"], "longitude")
                    else:
                        _lat, _lon = trackers.get(f"{_cid}_lat"), trackers.get(f"{_cid}_lon")
                    _dist = calc_distance(weather.LATITUDE, weather.LONGITUDE, _lat, _lon)
                    _cstate = {"climate_state": homeassistant._get_raw_state(_cent),
                               "climate_temp": homeassistant._get_numeric_attribute(_cent, "current_temperature")}
                    handle_car_climate(_cid, climate_schedules.get(_cid, {'enabled': False}), _cstate, car_charger_data.get(_cid),
                                       _cent, outdoor_temp_for_climate, _dist)
                except Exception as _hce:
                    print(f"❌ Klimatschemat för {_cid}: {_hce}")

            # Inomhustemperatur
            pump_indoor_temp = pump_data.get("indoor_temp") if pump_data else None
            # Innetemperatur ur användarens valda givare, med varje givares korrigering (t.ex. en givare som
            # visar 0,6 °C för mycket). Råvärdet loggas oförändrat.
            _indoor_sensors = homeassistant.indoor_sensors()
            SENSOR_LABELS = {x["key"]: x["label"] for x in _indoor_sensors}
            sensor_values = [(ha_temps.get(x["key"]) + float(x.get("offset") or 0)) if isinstance(ha_temps.get(x["key"]), (int, float)) else None
                             for x in _indoor_sensors]

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

            try:   # telemetrin: varifrån innetemperaturen kommer + avrundade temperaturer i dygnsrapporten
                telemetry.note_state(
                    indoor=(statistics.median(temps_to_avg) if len(temps_to_avg) >= 3 else sum(temps_to_avg) / len(temps_to_avg))
                    if temps_to_avg else pump_indoor_temp,
                    outdoor=(pump_data or {}).get("outdoor_temp"),
                    indoor_source="ha_sensors" if temps_to_avg else ("heatpump" if pump_indoor_temp is not None else "none"),
                    indoor_sensors=len(temps_to_avg),
                    indoor_entities=[x["entity"] for x in _indoor_sensors
                                     if x.get("entity") and isinstance(ha_temps.get(x["key"]), (int, float)) and ha_temps.get(x["key"]) > 0])
            except Exception:
                pass
            # Pumpen lever om den svarar med något mätvärde - inte bara utetemperatur (#204: en climate-pump utan utegivare
            # räknades som tappad kontakt i all evighet, och vakthunden tvingade 21 °C och visade det som status)
            _pump_ok = bool(pump_data) and any(isinstance(v, (int, float)) and not isinstance(v, bool)
                                               for k, v in pump_data.items() if k != "_ts")
            if _pump_ok:
                last_heartbeat = now
            # Innetemperaturen ur de valda givarna även utan värmepump (issue #128: förut bara när pumpen svarade, så
            # utan pump - eller med en generisk climate-pump utan utegivare - blev den aldrig satt).
            if temps_to_avg:
                # Median (>=3 sensorer) tål en enskild avvikande givare (t.ex. en Timmerflotte i solen/vid värmekälla).
                if len(temps_to_avg) >= 3:
                    indoor_temp = statistics.median(temps_to_avg)
                else:
                    indoor_temp = sum(temps_to_avg) / len(temps_to_avg)
                last_valid_ha_temp_time = now
                ha_temp_alert_sent = False
            elif _pump_ok or pump_indoor_temp is not None:
                indoor_temp = pump_indoor_temp
                # Larma bara om det finns valda innegivare som har tystnat
                if _indoor_sensors and (now - last_valid_ha_temp_time) > timedelta(minutes=15) and not ha_temp_alert_sent:
                    notifier.alert_indoor_temp_sensor_offline()
                    ha_temp_alert_sent = True

            # Thermia ger water_temp_top, övriga drivrutiner (NIBE, HeishaMon, generisk) water_temp (#145)
            water_temp   = (pump_data.get("water_temp_top") if pump_data.get("water_temp_top") is not None
                            else pump_data.get("water_temp")) if pump_data else None
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
                    if heat_pump_driver.set_operating_mode(_recover_mode):
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
                    if heat_pump_driver.set_operating_mode(_target_mode):
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
                        if heat_pump_driver.set_heating_start_temp(_summer_stop):
                            ai_thoughts.append(f"🌞 Sommarläge (Auto): sänker värmestopp {_heat_stop_reg:.1f}→{_summer_stop:.1f}°C.")
                else:
                    # Höst: återställ vinterns sparade värde om vi tidigare sänkt det.
                    _saved = all_overrides.get("winter_heat_stop", "auto")
                    if _saved not in ("auto", ""):
                        try:
                            _wv = float(_saved)
                            if _heat_stop_reg is not None and abs(_heat_stop_reg - _wv) > 0.05:
                                if heat_pump_driver.set_heating_start_temp(_wv):
                                    ai_thoughts.append(f"❄️ Höst: återställer värmestopp till {_wv:.1f}°C.")
                        except ValueError:
                            pass
                        logger.set_override("winter_heat_stop", "auto")

            outdoor_temp = pump_data.get("outdoor_temp") if pump_data else None
            if outdoor_temp is None and isinstance(ha_temps.get("ute"), (int, float)):
                outdoor_temp = ha_temps["ute"]            # vald utegivare när pumpen saknar egen (#128)
            # Huset = sol + nät - batteriets effekt (+ = laddar): laddar batteriet går en del av solen/nätet dit, laddar
            # det ur får huset mer än sol + nät (issue #125: översikten och historiken visade fel med batteri).
            # (_battery_early lästes före solkorrigeringen ovan, samma varv)
            # Orimlig batterieffekt (mer än 1,5 × batteriets max, standard 15 kW) räknas inte in: troligen fel givare,
            # t.ex. energi i kWh eller växelriktarens totala effekt (#139: 18,2 kW "urladdning" gav huset 0)
            _bat_w = _battery_early.get("power_w") or 0.0
            _bat_max = max(float(getattr(battery_driver, "max_power_w", None) or 0), 10000.0) * 1.5
            if abs(_bat_w) > _bat_max:
                if last_house_neg_warn is None or (now - last_house_neg_warn) > timedelta(hours=1):
                    print(f"⚠️ Batteriets effekt {_bat_w / 1000:.1f} kW är orimlig för ett husbatteri - räknas inte in i husets "
                          f"förbrukning. Kontrollera batteriets effektgivare i installationen.", flush=True)
                    last_house_neg_warn = now
                _bat_w = 0.0
            house_consumption_w = solar_prod_w + avg_net - _bat_w
            # Ser mätaren elbilen? (ev_in_meter.py, kollas en gång per dygn) Om inte: bilen läggs till husets förbrukning
            # här, så att allt som drar av bilen längre ner (grundlast, prognoser, vad som drar strömmen) blir rätt.
            if time.time() - _EV_METER["at"] > 86400:
                _EV_METER["at"] = time.time()
                try:
                    _ans, _ratio, _n = ev_in_meter.from_db(logger.get_db)
                    if _ans is not None and _ans != _EV_METER["in"]:
                        print(f"🔌 Mätaren {'ser' if _ans else 'ser INTE'} elbilens laddning (kvot {_ratio}, {_n} laddtimmar).")
                        _ew_settings.update(ev_in_meter=_ans)
                        logger.set_override("ev_in_meter", "ok" if _ans else json.dumps({"text": ev_in_meter.text(_ans, _ratio)}, ensure_ascii=False))
                    if _ans is not None:
                        _EV_METER["in"] = _ans
                except Exception as _me:
                    print(f"⚠️ Kontrollen om mätaren ser elbilen: {_me}")
            if _EV_METER["in"] is False:
                _evk = sum(((d or {}).get("power_kw") or 0.0) for d in _charger_list)
                house_consumption_w += 1000.0 * (_evk / 1000.0 if _evk > 100 else _evk)
            # Ett hus kan inte producera el: kraftigt negativt betyder att någon givare har fel tecken eller enhet (#139).
            # Logga delarna (högst en gång i timmen) och visa 0 i stället för t.ex. -17 kW.
            if house_consumption_w < -300:
                if last_house_neg_warn is None or (now - last_house_neg_warn) > timedelta(hours=1):
                    print(f"⚠️ Husets förbrukning blev {house_consumption_w:.0f} W (sol {solar_prod_w:.0f} + nät {avg_net:.0f} "
                          f"- batteri {(_battery_early.get('power_w') or 0.0):.0f}). Kontrollera batteriets effektsensor: + ska "
                          f"betyda laddar (annars battery.power_invert: true) och enheten W eller kW.", flush=True)
                    last_house_neg_warn = now
                house_consumption_w = 0.0
            grid_import_w = max(0, avg_net) 
            
            pi_p_term, pi_i_term = 0.0, 0.0
            if current_chosen_temp is not None and indoor_temp is not None:
                pi_p_term = round((current_chosen_temp / 10.0) - indoor_temp, 2)
            
            leg_temp = cfg.get("legionella_temp", 60.0)
            leg_max_days = cfg.get("legionella_days", 14)
            wt_norm = cfg.get("water_target_normal", 50.0)
            last_leg = get_last_legionella(leg_temp)
            days_since_leg = (now - last_leg).total_seconds() / 86400.0 if last_leg else 999.0

            consumed_kwh_this_hour = homeassistant.read_hour_kwh()
            if consumed_kwh_this_hour is None:      # mätaren saknar timsensor: integrerat ur nettoeffekten
                consumed_kwh_this_hour = _hour_import["wh"] / 1000.0 if _hour_import.get("h") == now.replace(minute=0, second=0, microsecond=0) else 0.0
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

            # Effektavgift efter månadens högsta timmar (#141): gränsen för timmen = så högt som möjligt utan att snittet
            # av de N högsta timmarna går upp ett trappsteg (capacity_tariff.py). Ersätter den fasta gränsen när påslagen.
            try:
                _ct = _ew_settings.get("capacity_tariff") or {}
                if _ct.get("enabled"):
                    if _cap_cache["at"] is None or (now - _cap_cache["at"]) > timedelta(minutes=10):
                        with logger.get_db() as _c, _c.cursor() as _cur:
                            _cur.execute("""SELECT (h AT TIME ZONE 'Europe/Stockholm')::date, kw FROM (
                                              SELECT date_trunc('hour', timestamp) h, avg(GREATEST(net_power, 0)) / 1000.0 kw
                                              FROM sensor_log WHERE timestamp >= date_trunc('month', now() AT TIME ZONE 'Europe/Stockholm') AT TIME ZONE 'Europe/Stockholm'
                                                AND timestamp < date_trunc('hour', now()) GROUP BY 1) x""")
                            _cap_cache["peaks"] = [(d, float(k or 0)) for d, k in _cur.fetchall()]
                        _cap_cache["at"] = now
                    _lim, _ci = capacity_tariff.limit_kw(_cap_cache["peaks"], now.date(), int(_ct.get("top_n") or 3),
                                                         _ct.get("distinct_days", True) is not False, _ct.get("steps"), _ct.get("target_kw"))
                    if _lim and _lim != float("inf"):
                        current_target_limit = float(_lim)
                    _cap_cache["info"] = _ci
            except Exception as _cte:
                print(f"⚠️ Effektavgiften (högsta timmar): {_cte}")

            power_limit_w = current_target_limit * 1000
            peak_shaving_active = 1 if house_consumption_w > power_limit_w else 0
            force_heating_active = 1 if cfg.get("spa_force_heat", False) else 0
            watchdog_trips = 0 
            
            spa_schedule_active = cfg.get("spa_schedule_enabled", False)
            target_dt = cfg.get("spa_target_datetime")
            _spa_sched_temp = cfg.get("spa_target_temp", 38.0)
            # Badtider (spa_bath.py): utanför dem ligger badet på eco-golvet och värms inför nästa badtid. Ett manuellt
            # schema (spa_schedule_enabled) går före.
            spa_bath_note = None
            if not (spa_schedule_active and target_dt and target_dt > now):
                _in_bath, _next_bath, _bath_end = spa_bath.status(now, _ew_settings.get("spa_bath_windows"))
                if _in_bath:
                    spa_bath_note = f"Badtid till {_bath_end.strftime('%H:%M')} - håller badet varmt."
                elif _next_bath is not None:
                    spa_schedule_active, _spa_sched_temp = True, cfg.get("spa_normal_temp", 38.0)
                    target_dt = _next_bath if (_next_bath - now) <= timedelta(hours=spa_bath.PLAN_AHEAD_H) else None
                    spa_bath_note = f"Nästa badtid {('mån','tis','ons','tor','fre','lör','sön')[_next_bath.weekday()]} {_next_bath.strftime('%H:%M')}"
                    if target_dt is None:
                        spa_should_heat_now = False
            
            if spa_schedule_active and target_dt and target_dt > now:
                if last_spa_schedule_eval_time is None or (now - last_spa_schedule_eval_time) > timedelta(minutes=14):
                    h_intercept, h_slope_out, h_slope_spa = learning.get_heating_rate_model()
                    cooling_k, _ = learning.get_cooling_rate_model()
                    spa_should_heat_now, _ = decisions.check_spa_schedule_plan(
                        now, target_dt, gecko_data.get("current_temp", 38.0) if gecko_data else 38.0, 
                        _spa_sched_temp, h_intercept, h_slope_out, h_slope_spa, cooling_k, 
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
            # Laddboxarnas fasströmmar (alla laddboxar i installationen) dras av från husets last
            ev_l1 = sum(((d or {}).get('current_l1') or 0) for d in _charger_list)
            ev_l2 = sum(((d or {}).get('current_l2') or 0) for d in _charger_list)
            ev_l3 = sum(((d or {}).get('current_l3') or 0) for d in _charger_list)
            if _EV_METER["in"] is False:          # laddboxen sitter inte bakom mätaren: inget att dra av från fasströmmarna
                ev_l1 = ev_l2 = ev_l3 = 0

            hl1_non_ev = max(0, (avg_hl1 or 0) - ev_l1)
            hl2_non_ev = max(0, (avg_hl2 or 0) - ev_l2)
            hl3_non_ev = max(0, (avg_hl3 or 0) - ev_l3)
            house_load_excluding_ev_a = max(hl1_non_ev, hl2_non_ev, hl3_non_ev)

            # Termisk säkringsmodell: tak för bilarnas totala ström (None = ingen färsk Tibber-data,
            # gpm.py använder då den gamla formeln säkring - husets last).
            _fuse_cfg["fuse_a"] = cfg.get('fuse_size_a', decisions.MAX_FUSE_A)
            _fuse_cfg["margin_a"] = float(cfg.get('fuse_safety_margin_a', 0.0) or 0.0)
            _fuse_charger_ids.clear()
            _fuse_charger_ids.update({c: i for c, i in car_charger_id.items() if i})
            _ev_phase_a = [0.0, 0.0, 0.0]
            for _cd in physical_charger_data.values():
                if _cd:
                    for _k, _key in enumerate(("current_l1", "current_l2", "current_l3")):
                        _ev_phase_a[_k] += float(_cd.get(_key) or 0)
            ev_fuse_cap_a = fuse_model.ev_cap_a(_fuse_cfg["fuse_a"], _ev_phase_a, margin_a=_fuse_cfg["margin_a"],
                                                pending_a=_ramp.pending_a("ev"))
            if ev_fuse_cap_a is None and (avg_hl1 is None or avg_hl2 is None or avg_hl3 is None):
                # Elmätaren svarar inte: husets ström är okänd (räknades förut som 0 A = hela säkringen till bilen).
                # Ladda vidare, men försiktigt - inspirerat av FTW:s regel för gammal mätardata, se fuse_guard.py.
                _base_kw = learning.predict_base_load(now, dynamic_base_load_profile)
                ev_fuse_cap_a = fuse_guard.stale_ev_cap_a(_fuse_cfg["fuse_a"], _base_kw, _fuse_cfg["margin_a"])
                ai_thoughts.append(f"⚡ Elmätaren svarar inte: bilarna får högst {ev_fuse_cap_a} A tills mätdata finns igen "
                                   f"(husets last uppskattad till {_base_kw:.1f} kW).")
            elif ev_fuse_cap_a is not None:
                _filt = fuse_model.filtered_a()
                ai_thoughts.append(f"⚡ Säkringsmodell: termisk ström {'/'.join(f'{x:.1f}' for x in _filt)} A, bilarna får {ev_fuse_cap_a} A"
                                   + (" (håller, nyss strypt)" if fuse_model.in_recovery() else "") + ".")

            # Lastsidans mätpunkt (valfri): eget tak mot lastsidans säkring. Bilarna ligger bakom båda
            # mätpunkterna, så samma _ev_phase_a gäller; det lägsta av de två taken används.
            ev_load_cap_a = None
            if load_model is not None:
                ev_load_cap_a = load_model.ev_cap_a(LOAD_FUSE_A, _ev_phase_a, margin_a=_fuse_cfg["margin_a"],
                                                    pending_a=_ramp.pending_a("ev"))
                if ev_load_cap_a is None:
                    # Lastmätaren svarar inte: samma försiktiga reserv som för nätmätaren, mot lastsidans säkring.
                    ev_load_cap_a = fuse_guard.stale_ev_cap_a(LOAD_FUSE_A, learning.predict_base_load(now, dynamic_base_load_profile),
                                                              _fuse_cfg["margin_a"])
                    ai_thoughts.append(f"⚡ Lastsidans mätare svarar inte: bilarna får högst {ev_load_cap_a} A tills mätdata finns igen.")
                else:
                    ai_thoughts.append(f"⚡ Lastsidan: termisk ström {'/'.join(f'{x:.1f}' for x in load_model.filtered_a())} A, taket {ev_load_cap_a} A.")
                ev_fuse_cap_a = fuse_guard.combine_caps(ev_fuse_cap_a, ev_load_cap_a)

            # Dynamisk Peak Shaving
            minutes_left_burn = 60 - now.minute
            historical_base_load_kw = learning.predict_base_load(now, dynamic_base_load_profile)
            
            ev_kw_now = sum(((d or {}).get("power_kw") or 0.0) for d in _charger_list)
            if ev_kw_now > 100: ev_kw_now /= 1000.0 
            spa_kw_now = 3.0 if (gecko_data and str(gecko_data.get("heater_state", "")).lower() in ["heating", "heat"]) else 0.0
            current_actual_base_load_kw = max(0.5, (house_consumption_w / 1000.0) - ev_kw_now - spa_kw_now)
            
            weight_actual = (60 - minutes_left_burn) / 60.0
            weight_historical = 1.0 - weight_actual
            dynamic_predicted_base_load_kw = (current_actual_base_load_kw * weight_actual) + (historical_base_load_kw * weight_historical)
            
            reserve_kwh_needed_now = dynamic_predicted_base_load_kw * (minutes_left_burn / 60.0)
            allowed_kwh_now = current_target_limit - reserve_kwh_needed_now

            # ============================================================
            # 🚗 Bilar som sover (entities.wake_button i installationen, t.ex. Tesla): väck en inkopplad bil när den bara
            # har ett gammalt (minnes)värde för batteriet. Under pågående laddning är bilen vaken av sig själv. Högst en gång
            # per TESLA_WAKE_MIN_INTERVAL_H (även vid misslyckat försök), eller var 30:e minut när laddning är planerad inom
            # en kvart - så att planen räknas om på ett färskt värde.
            # 🚗 Bilar som bara hämtar nytt värde på begäran (entities.update_button, t.ex. Leaf - 24 okt: 12 % trots full):
            # be om uppdatering var 30:e minut medan bilen är inkopplad och inte full, annars var 3:e timme.
            for _ev in house_cfg.get("evs", []) or []:
                _cid, _ents = _ev.get("id"), _ev.get("entities") or {}
                if not _cid or not ev_connection_state.get(_cid, {}).get('connected'):
                    continue
                _name = CAR_SPECS.get(_cid, {}).get("name", _cid)
                if _ents.get("wake_button") and car_soc_stale.get(_cid):
                    try:
                        _plan_soon = False
                        try:
                            from sqlalchemy import text as _wt
                            from database_engine import engine as _weng
                            _n = now.replace(tzinfo=None)
                            with _weng.connect() as _wc:
                                _plan_soon = bool(_wc.execute(_wt("SELECT 1 FROM ev_plan_slots WHERE car_id = :c AND kw > 0 AND t_slot BETWEEN :a AND :b LIMIT 1"),
                                                              {"c": _cid, "a": _n, "b": _n + timedelta(minutes=15)}).fetchone())
                        except Exception as _pe:
                            print(f"⚠️ Kunde inte läsa laddplanen för väckning: {_pe}")
                        _wake_gap = timedelta(minutes=30) if _plan_soon else timedelta(hours=TESLA_WAKE_MIN_INTERVAL_H)
                        _last = _soc_mem.get(f"{_cid}_wake")
                        if _last is None or (now - _last) > _wake_gap:
                            _soc_mem[f"{_cid}_wake"] = now
                            if homeassistant.press_button(_ents["wake_button"]):
                                print(f"🚗 Väckte {_name} (" + ("laddning planerad inom 15 min, batterinivån gammal" if _plan_soon else "inkopplad, batterinivå okänd") + ")")
                    except Exception as _we:
                        print(f"⚠️ Väckning av {_name} misslyckades: {_we}")
                if _ents.get("update_button"):
                    try:
                        _s = car_soc.get(_cid)
                        _gap = timedelta(minutes=30) if (_s is None or _s < 98) else timedelta(hours=3)
                        _last = _soc_mem.get(f"{_cid}_poll")
                        if _last is None or (now - _last) > _gap:
                            _soc_mem[f"{_cid}_poll"] = now
                            # I bakgrunden: tillverkarens moln kan ta en halv minut, huvudloopen ska inte vänta på det
                            threading.Thread(target=homeassistant.press_button, args=(_ents["update_button"], 45),
                                             daemon=True).start()
                    except Exception as _ne:
                        print(f"⚠️ Uppdatering av {_name}s data misslyckades: {_ne}")

            # ============================================================
            # 🧠 GPM UTVÄRDERING
            # ============================================================
            gpm_state = {
                'now': now, 'current_price': current_price, 'all_prices': all_prices,
                'pv_power_w': solar_now, 'avg_net_w': avg_net, 'house_consumption_w': house_consumption_w,
                'predicted_base_load_kw': dynamic_predicted_base_load_kw, 'grid_import_w': grid_import_w,
                'consumed_kwh_this_hour': float(consumed_kwh_this_hour), 'power_limit_kw': current_target_limit,
                'predicted_cooling_rate': predicted_cooling_rate, 'base_load_profile': dynamic_base_load_profile,
                'peak_shaving_enabled': cfg.get("peak_shaving_enabled", True), 'solar_is_shaky': solar_is_shaky,
                'solar_auto_export': str(all_overrides.get("solar_auto_export", "true")).lower() != "false",
                'sun_soon': _sun_cache.get("soon"), 'sun_day': _sun_cache.get("day"),
                'indoor_temp': indoor_temp, 'indoor_humidity': ha_temps.get('indoor_humidity'), 'indoor_min': cfg.get("indoor_min", 19.0),
                'indoor_cold_confirmed': _cold_gpm_watch.update(indoor_temp is not None and indoor_temp < cfg.get("indoor_min", 19.0), now), 'indoor_max': cfg.get("indoor_max", 22.5),
                'water_temp': water_temp or 50.0, 'water_target_normal': wt_norm,
                'brine_out_temp': pump_data.get("brine_out_temp") if pump_data else None,
                'spa_temp': gecko_data.get("current_temp") if gecko_data else None,
                'spa_measured_w': spa_power_w,  # 3-fas-mätt spa-effekt → gpm använder verkligt värde
                'spa_normal_temp': cfg.get("spa_normal_temp", 34.0), 'days_since_legionella': days_since_leg,
                'last_heartbeat': last_heartbeat, 'legionella_max_days': leg_max_days,
                'spa_force_heat': cfg.get("spa_force_heat", False), 'spa_force_eco': all_overrides.get("spa_force_eco") == "on",
                'spa_max_temp': cfg.get("spa_max_temp", 40.0), 'spa_low_temp': cfg.get("spa_low_temp", 15.0),
                'spa_target_scheduled': _spa_sched_temp, 'spa_target_scheduled_active': spa_schedule_active,
                'spa_bath_note': spa_bath_note,
                'spa_should_heat_now': spa_should_heat_now, 'away_mode_active': away_mode_enabled,
                'hw_probability': max_hw_prob, 'away_recovering': away_recovering,
                'temp_cheap': cfg.get("temp_cheap", 22.0), 'temp_expensive': cfg.get("temp_expensive", 20.0),
                'heat_feedback': _ew_settings.get("heat_feedback", "av"), 'heat_feedback_boost': float(_ew_settings.get("heat_feedback_boost", 1.0) or 1.0),
                'heat_feedback_min_sp': _ew_settings.get("heat_feedback_min_sp"), 'heat_feedback_max_sp': _ew_settings.get("heat_feedback_max_sp"),
                'outdoor_avg_5d': _cached_outdoor_avg_5d,  # FIX: saknades → is_summer var alltid False (dött sommarläge)
                'outdoor_temp': outdoor_temp,              # FIX: saknades → Prio 9-watchdog antog alltid "kallt ute"
                'heat_stop_outdoor': (pump_data.get('heat_stop_outdoor') if pump_data else None),  # pumpens egen värmestopp-tröskel (reg 19) → GPM samverkar i stället för hårdkodad gräns
                'hysteresis': strategy.get("hysteresis", 0.10), 'dynamic_limit': dynamic_limit if dynamic_limit else 99.0,
                'all_prices_tou': strategy.get("prices_tou"),    # spot + tidstariff per kvart (#179), för pumpens prisval
                'max_fuse_a': cfg.get('fuse_size_a', decisions.MAX_FUSE_A), 'house_load_a': house_load_excluding_ev_a, 'ev_actual_a': 0,
                'ev_fuse_cap_a': ev_fuse_cap_a, 'ev_load_cap_a': ev_load_cap_a,
                'current_solar_limit_pct': current_solar_limit_pct, 'current_target_limit': current_target_limit,
                'ev_min_charge_a': EV_MIN_CHARGE_AMPS, 'ev_max_charge_a': EV_MAX_CHARGE_AMPS, 'ev_plan': ev_charge_plan,
                # Bilarna ur installationen: vilka som finns och deras laddboxars faser/maxström (gpm har inga bilnamn)
                'car_ids': list(car_ids), 'car_specs': CAR_SPECS, 'has_spa': HAS_SPA,
            }
            for _c in car_ids:      # #394: "Ladda nu till X %" - avsluta vid målet, urdragen kabel eller efter 24 h
                try:
                    _cn_end, _cn_why = charge_now.should_end(all_overrides, _c, car_soc.get(_c),
                                                             bool(ev_connection_state[_c]['connected']), time.time())
                    if _cn_end:
                        _cn_t = charge_now.target(all_overrides, _c)
                        for _k, _v in charge_now.clear_keys(_c).items():
                            logger.set_override(_k, _v)
                            all_overrides[_k] = _v
                        _cn_name = (CAR_SPECS.get(_c) or {}).get("name") or _c
                        _cn_txt = {"target": f"🔌 {_cn_name} har nått {_cn_t} % - Ladda nu är klart och planen tar över.",
                                   "unplugged": f"🔌 {_cn_name}: kabeln drogs ur - Ladda nu avslutades.",
                                   "timeout": f"🔌 {_cn_name}: Ladda nu avslutades efter 24 timmar - planen tar över."}.get(_cn_why)
                        if _cn_txt:
                            print(_cn_txt)
                            if _cn_why == "target":
                                notifier.send_emil("🔌 Ladda nu klart", _cn_txt.split(" ", 1)[1])
                except Exception as _cne:
                    print(f"⚠️ Ladda nu-kontrollen ({_c}): {_cne}")
            for _c in car_ids:      # per bil: <bil>_soc, _connected, _phases ... (samma nycklar gpm alltid läst)
                gpm_state.update({
                    f'{_c}_soc': car_soc.get(_c),
                    f'{_c}_connected': ev_connection_state[_c]['connected'] or ev_gps_state[_c]['approaching'],
                    f'{_c}_charge_completed': ev_connection_state[_c]['charge_completed'],
                    f'{_c}_phases': (car_charger_data.get(_c) or {}).get('phases'),
                    f'{_c}_habit_profile': _cached_ev_profiles.get(_c, {}),
                    f'{_c}_prio': cfg.get(f'ev_{_c}_prio', 2),
                    f'{_c}_force_amps': _override_amps(all_overrides.get(f"{_c}_force_amps", "0")),
                    f'{_c}_force_phases': _override_amps(all_overrides.get(f"{_c}_force_phases", "0")),
                    f'{_c}_hold': all_overrides.get(f"{_c}_hold") == "on",          # EnergyWizard Mobil: manuell paus
                })
            
            gpm_actions = gpm_engine.evaluate(gpm_state)
            if ((house_cfg.get("heat_pump") or {}).get("hot_water_shadow") or {}).get("enabled") is True:
                _hot_water_monitor.submit(house_cfg, pump_data, now=now.timestamp(), shadow=shadow.active(),
                    manual=all_overrides.get("hotwater", "auto") != "auto", away=bool(away_mode_enabled),
                    hygiene=days_since_leg >= leg_max_days or (days_since_leg >= leg_max_days - 2
                        and ((current_price is not None and current_price < 0) or avg_net < -2000)))
            try:
                _persist_solar_state(getattr(gpm_engine, 'ev_solar_charge_active', False), getattr(gpm_engine, 'ev_solar_target_amps', 0), getattr(gpm_engine, 'ev_solar_target_phases', 0), now)
            except Exception as _e:
                print(f"⚠️ Kunde inte spara sol-laddningsläge: {_e}")
            # --- Husbatteriet: beslut med hela husets läge som indata (battery_control.py) ---
            battery_state = {}
            _battery["decision_rule"] = None
            try:
                battery_state = _battery_early or battery_driver.read_state() or {}   # redan läst ovan (husets förbrukning)
                _bplan, _bdec = None, None
                _balance = _battery_balance.update(battery_state, battery_cfg["balance"], time.time(),
                    battery_cfg["control"] == "styr" and battery_cfg.get("plan") and
                    bool(battery_cfg.get("capacity_kwh")) and
                    {"charge", "hold"} <= battery_driver.supported_intents(),
                    active=_battery.get("balance_active", False))
                # A trigger, completion or loss of fresh module data invalidates
                # the cached maintenance plan immediately, not next quarter.
                _balance_key = (_balance["request"], _balance.get("hold_slots"))
                if _battery.get("balance_key") != _balance_key:
                    _battery.update(plan=None, plan_at=None, balance_key=_balance_key)
                if solar_data is not None:
                    solar_data["battery_soc"] = battery_state.get("soc_pct")
                    solar_data["battery_power_w"] = battery_state.get("power_w")
                if battery_cfg["control"] != "av" and battery_state.get("soc_pct") is not None:
                    # Elbilen räknas som laddande när laddboxarna faktiskt drar ström - inte när ström bara är beordrad
                    # (#174: ett laddtvång på en frånkopplad Tesla höll batteriet borta från planens urladdning i timmar)
                    _ev_on = ev_kw_now > 1.0
                    _ev_sol = bool(getattr(gpm_engine, "ev_solar_charge_active", False))
                    _q = now.hour * 4 + now.minute // 15
                    # Dygnsplanen räknas om varje kvart (bara i läget styr, kräver kapacitet)
                    if battery_cfg["control"] == "styr" and battery_cfg.get("plan") and battery_cfg.get("capacity_kwh"):
                        # Lär om var 6:e timme ur historiken (battery_learning.py) - planen använder bara det som
                        # klarat rimlighetskontrollerna, annars configens värden.
                        if _battery["model_at"] is None or (now - _battery["model_at"]) > timedelta(hours=6):
                            try:
                                from database_engine import engine as _leng
                                _battery["model"] = battery_learning.learn_from_db(_leng, battery_cfg)
                                print(f"🔋 Batteri: {battery_learning.describe(_battery['model'])}")
                            except Exception as _le:
                                print(f"⚠️ Batteriinlärningen hoppade över: {_le}")
                            _battery["model_at"] = now
                        if _battery["plan_at"] is None or now.minute % 15 == 0 or (now - _battery["plan_at"]) > timedelta(minutes=16):
                            try:
                                from database_engine import engine as _peng
                                _battery["plan"] = battery_plan.plan_from_db(_peng, now, battery_state.get("soc_pct"),
                                                                             dict(battery_learning.apply(battery_cfg, _battery["model"]), balance_request=_balance),
                                                                             dynamic_base_load_profile, battery_driver.supported_intents())
                                _battery["plan_at"] = now
                            except Exception as _pe:
                                print(f"⚠️ Batteriplanen hoppade över: {_pe}")
                                _battery["plan"] = None
                    _bplan = _battery["plan"] if battery_cfg["control"] == "styr" else None
                    # #396: "Toppa nu till X %" - klart vid målet eller efter maxtiden, sedan tar planen över
                    try:
                        _tu_t = int(str(all_overrides.get("battery_topup_target") or "0") or 0)
                    except ValueError:
                        _tu_t = 0
                    _tu_soc = battery_state.get("soc_pct")
                    if _tu_t and (battery_cfg["control"] != "styr" or (_tu_soc is not None and _tu_soc >= min(_tu_t, battery_cfg.get("max_soc", 100)))
                                  or (timed_override.until(all_overrides, "battery_topup") or 0) <= time.time()):
                        if _tu_soc is not None and _tu_soc >= _tu_t:
                            print(f"🔋 Batteriet är toppat till {_tu_t} % - planen tar över.")
                            notifier.send_emil("🔋 Batteriet är toppat", f"Husbatteriet har nått {_tu_t} %. Planen tar över.")
                        for _k in ("battery_topup_target", "battery_topup_until"):
                            logger.set_override(_k, "")
                            all_overrides[_k] = ""
                        _tu_t = 0
                    _bdec = battery_control.decide({
                        "soc": battery_state.get("soc_pct"), "price": current_price, "avg_net_w": avg_net,
                        "currency_symbol": nordpool.cost_settings()["symbol"],
                        "battery_w": battery_state.get("power_w"),
                        "meter_fresh": _meter_ok_at["t"] is not None and time.time() - _meter_ok_at["t"] < 120,
                        "fuse_state": fuse_model.check(_fuse_cfg["fuse_a"], _fuse_cfg["margin_a"])[0] if fuse_model.is_fresh() else "ok",
                        "fuse_excess_a": fuse_model.check(_fuse_cfg["fuse_a"], _fuse_cfg["margin_a"])[1] if fuse_model.is_fresh() else 0,
                        "peak_reached": bool(cfg.get("peak_shaving_enabled", True)) and float(consumed_kwh_this_hour) >= float(allowed_kwh_now),
                        "ev_charging_grid": _ev_on and not _ev_sol, "ev_solar_active": _ev_on and _ev_sol,
                        "prices_rest_of_day": (all_prices or [])[_q:],
                        "planned_action": (_bplan or {}).get("action_now"), "plan_saving_kr": (_bplan or {}).get("saving_kr"),
                        "planned_power_w": (_bplan or {}).get("power_now_w"),
                        "balance_target_soc": (_bplan or {}).get("balance_target_soc") if _balance["request"] else None,
                        "balance_hold_now": (_bplan or {}).get("balance_hold_now") if _balance["request"] else False,
                        "learned_note": _battery_note(_battery["model"], (_bplan or {}).get("live_charge_note")),
                        "fuse_charge_cap_w": _battery_fuse_cap_w(battery_state.get("power_w")),
                        "topup_target": _tu_t or None,
                    }, battery_cfg, battery_driver.supported_intents())
                    gpm_actions["log"].append(f"🔋 (BATTERI): {_bdec['reason']}")
                    battery_driver.set_balancing(_bdec.get("rule") == "balance")
                    if _bdec.get("rule") not in battery_control.SAFETY_RULES:
                        battery_driver.refresh()       # håller en pågående tvångsladdning vid liv (Solis RC m.fl.)
                    if battery_control.should_apply(_bdec, _battery["last"], _battery["at"], now,
                                                    battery_cfg["min_change_minutes"]):
                        if battery_commands.apply(_battery_commands, battery_driver, _bdec["intent"], _bdec.get("power_w")):
                            if _bdec["intent"] == "charge":     # #399: ökningen räknas mot bilens utrymme tills den syns
                                _ramp.grant("battery", ((_bdec.get("power_w") or battery_cfg["max_power_w"])
                                                        - max(0.0, float(battery_state.get("power_w") or 0.0))) / 230.0 / battery_cfg["phases"])
                            _battery.update(last=_bdec, at=now)
                            print(f"🔋 Batteri: {_bdec['intent']} - {_bdec['reason']}")
                    _battery["decision_rule"] = _bdec.get("rule")
                    if _battery_commands.current:
                        try:
                            _battery_commands.observe(_battery_commands.current["command_id"], battery_state, time.time(),
                                                      battery_cfg.get("reserve_soc"), (_bplan or {}).get("balance_target_soc") or battery_cfg.get("max_soc"))
                        except Exception:
                            pass  # Observability must not change existing follow/control behavior.
                    # Följer batteriet det vi säger åt det? (battery_follow.py) - visas i appen/webben, notis vid avvikelse
                    if battery_cfg["control"] == "styr" and _battery.get("last"):
                        _bl = _battery["last"]
                        _st, _txt, _new = _battery_follow.step(_bl.get("intent"), _bl.get("power_w"), battery_state.get("power_w"),
                                                              battery_state.get("soc_pct"), battery_cfg.get("reserve_soc"), time.time())
                        _stored = json.dumps({"status": _st, "text": _txt}, ensure_ascii=False) if _st in ("not_following",) else "ok"
                        _journal.append(control_journal.check_battery(_st, _txt, _bl.get("intent")))
                        if _stored != _battery.get("follow_stored"):
                            logger.set_override("battery_follow", _stored)
                            _battery["follow_stored"] = _stored
                        if _new:
                            print(f"🔋⚠️ Batteriet följer inte: {_txt}")
                            notifier.send_emil("🔋 Husbatteriet gör inte som det blir tillsagt",
                                               f"{_txt} Batteriet har inte sagt varför - kolla dess app eller display. "
                                               f"EnergyWizard fortsätter försöka.", key="batteri")
                _balance_text = battery_balance.display(_balance, _bplan, _bdec, _battery.get("last")) if battery_cfg["balance"]["enabled"] else ""
                _battery["balance_active"] = _balance_text == battery_balance.MESSAGES["active"]
                if _battery.get("balance_text") != _balance_text:
                    logger.set_override("battery_balance", json.dumps({"text": _balance_text}, ensure_ascii=False))
                    _battery["balance_text"] = _balance_text
            except Exception as _be:
                print(f"⚠️ Batteribeslutet hoppade över: {_be}")
            ai_thoughts_list = gpm_actions["log"].copy()
            # Förut: loggens SISTA rad - nästan alltid effektvaktens "Peak Shaving är inaktiverat". Nu en
            # rubrik + en mening per enhet om vad som görs och varför (decision_summary.py).
            _summary = decision_summary.summarize(gpm_actions["log"], gpm_actions)
            current_decision = _summary["headline"]
            current_decision_items = _summary["items"]
            
            # EV-laddning: generisk loop över car_ids (Steg 4:4) - ersätter de tidigare
            # duplicerade nissan/tesla-blocken. gpm_actions['ev'][car_id] byggs redan
            # generiskt av gpm.py (se gpm.py:s kommentar vid actions['ev']); bara
            # fas-/stall-/laddar-hanteringen nedan var kvar att generalisera.
            ev_amps = {car_id: gpm_actions.get("ev", {}).get(car_id, {}).get("limit_a", 0) for car_id in car_ids}
            ev_set_phases = {car_id: gpm_actions.get("ev", {}).get(car_id, {}).get("set_phases") for car_id in car_ids}

            ev_reason_stop = {}
            for car_id in car_ids:
                if ev_amps[car_id] == 0:
                    for log_msg in reversed(gpm_actions["log"]):
                        if any(k in log_msg for k in ["EV", "PEAK", "Säkring"]) and "inaktiverat" not in log_msg:
                            ev_reason_stop[car_id] = log_msg; break

            # Gästbil (#131): en bil som inte finns i installationen laddas på den här bilens laddbox - kWh och ev.
            # klar-tid från appen (överstyrningen guest_<bil>), billigaste kvartarna, alltid under säkringen.
            for car_id in car_ids:
                try:
                    _g = guest_charge.parse(all_overrides.get(f"guest_{car_id}"))
                    if not _g:
                        _guest_state.pop(car_id, None)
                        continue
                    _st = _guest_state.get(car_id)
                    if not _st or _st["set_at"] != _g.get("set_at"):
                        _st = _guest_state[car_id] = {"kwh": 0.0, "t": time.time(), "set_at": _g.get("set_at"), "seen": False}
                    _cd = car_charger_data.get(car_id) or {}
                    _conn = charger_connected(_cd)
                    _dt = max(0.0, min(300.0, time.time() - _st["t"]))
                    _st["kwh"] += float(_cd.get("power_kw") or 0.0) * _dt / 3600.0
                    _st["t"] = time.time()
                    _st["seen"] = _st["seen"] or _conn
                    _done = (_st["seen"] and not _conn) or guest_charge.expired(_g, now) or _st["kwh"] >= float(_g["kwh"])
                    if _done:
                        logger.set_override(f"guest_{car_id}", "off")
                        _guest_state.pop(car_id, None)
                        print(f"🚗 Gästbilen på {CAR_SPECS.get(car_id, {}).get('name', car_id)}s laddbox är klar ({_st['kwh']:.1f} kWh).")
                        continue
                    _spec = CAR_SPECS.get(car_id, {})
                    _avail = float(_fuse_cfg.get("fuse_a") or 25) - float(house_load_excluding_ev_a or 0)
                    _a, _why = guest_charge.amps(now, _g, _st["kwh"], int(_spec.get("max_a") or 16),
                                                 1 if str(_spec.get("phases")) == "1" else 3, _avail,
                                                 lambda t: _guest_price.setdefault(t, nordpool.get_price_at(t)))
                    ev_amps[car_id], ev_set_phases[car_id], ev_reason_stop[car_id] = _a, None, _why
                    if len(_guest_price) > 400:
                        _guest_price.clear()
                    print(f"🚗 {_why}")
                except Exception as _ge:
                    print(f"⚠️ Gästbilen ({car_id}): {_ge}")

            current_chosen_temp = int(gpm_actions["pump_target_temp"] * 10)
            current_chosen_water = decisions.WATER_ON if gpm_actions.get("pump_run_water") else decisions.WATER_OFF
            current_mode = gpm_actions["pump_mode"]

            # Fasväxling - FIX: flagga pågående fasbyte så det vanliga EV-limit-blocket
            # nedan inte skickar tillbaka ström på laddaren medan fasbytestråden
            # förbereder kontaktorbrytning vid 0A.
            ev_phase_switch_active = {car_id: False for car_id in car_ids}
            cars_switching = [c for c in car_ids if ev_set_phases[c]]
            if cars_switching:
                print("⚡ Fasbyte begärt! Asynkron omstart startad för säker kontaktor-brytning...")
                def phase_switch_async(_cars=cars_switching, _ids=dict(car_charger_id), _phases=dict(ev_set_phases)):
                    for c in _cars:
                        charger_set_limit(_ids[c], 0, reason="Fasbyte förbereds")
                    time.sleep(15)
                    for c in _cars:
                        charger_set_phases(_ids[c], _phases[c])
                threading.Thread(target=phase_switch_async).start()
                for car_id in cars_switching:
                    last_sent_ev_limit[car_id] = 0
                    ev_phase_switch_active[car_id] = True

            # EV Limit
            for car_id in car_ids:
                charger_data = car_charger_data.get(car_id)
                charger_id = car_charger_id.get(car_id)
                connected = charger_connected(charger_data)
                _log_charger_status_if_changed(car_id, charger_data)
                if connected and (charger_data.get("power_kw") or 0) > 0.5:
                    try:                                # lär bilens faser och egen maxström (ev_limits.py)
                        if _ev_learn.observe(car_id, [charger_data.get(k) for k in ("current_l1", "current_l2", "current_l3")], ev_amps[car_id]):
                            _ev_learn.apply(CAR_SPECS, _EV_EXPLICIT)
                        if time.time() - _ev_learn_saved["at"] > 900 and str(_ev_learn.data) != _ev_learn_saved["sig"]:
                            _ew_settings.update(learned_ev=_ev_learn.data)
                            _ev_learn.apply(CAR_SPECS, _EV_EXPLICIT)
                            _ev_learn_saved.update(at=time.time(), sig=str(_ev_learn.data))
                    except Exception as _le:
                        print(f"⚠️ Inlärning av bilens gränser ({car_id}): {_le}")
                if connected:
                    # FIX: hoppa över ström-sättning under pågående fasbyte (laddaren ska ligga på 0A)
                    if not ev_phase_switch_active[car_id]:
                        if ev_amps[car_id] != last_sent_ev_limit.get(car_id):
                            if charger_set_limit(charger_id, ev_amps[car_id], reason=ev_reason_stop.get(car_id)):
                                _ramp.grant("ev", ev_amps[car_id] - (last_sent_ev_limit.get(car_id) or 0))   # #399
                                last_sent_ev_limit[car_id] = ev_amps[car_id]
                        if ev_amps[car_id] > 0 and charger_data.get("status") in ["awaiting_start", "paused", "off"]:
                            charger_turn_on(charger_id)
                        _check_ev_stall(car_id, ev_amps[car_id], charger_data, charger_id, ev_phase_switch_active[car_id], now)
                    try:                    # #385: varför bilen får mindre än vi bad om (visas i appen)
                        _ln = charger_limit.explain(last_sent_ev_limit.get(car_id), charger_data) or ""
                        if _ln != (all_overrides.get(f"{car_id}_limit_note") or ""):
                            logger.set_override(f"{car_id}_limit_note", _ln)
                            all_overrides[f"{car_id}_limit_note"] = _ln
                            if _ln:
                                print(f"🔌 {(CAR_SPECS.get(car_id) or {}).get('name') or car_id}: {_ln}")
                    except Exception as _lne:
                        print(f"⚠️ Förklaring av laddboxens gräns ({car_id}): {_lne}")
                    try:                    # #390: målet i fara - varna innan det är för sent (visas i appen, en avisering per mål)
                        _sp = CAR_SPECS.get(car_id) or {}
                        _cdp = globals().get("car_data_for_plan") or {}
                        _bkwh = float(_sp.get("battery_kwh") or decisions.DEFAULT_BATTERY_KWH)
                        _t_dt, _t_soc, _kwh, _ = decisions.get_car_plan_details(now, car_id, ev_schedule, car_soc.get(car_id), _bkwh,
                                                                              _cdp.get(f"{car_id}_ready_by"), _cdp.get(f"{car_id}_ready_soc"))
                        _ph = charger_data.get("phases") if str(charger_data.get("phases")) in ("1", "3") else _sp.get("phases")
                        _risk = _ev_missed_mod.goal_at_risk(car_soc.get(car_id), _t_soc, _t_dt, now, _bkwh,
                                                            _ev_missed_mod.effective_kw(_sp.get("max_a"), 3 if str(_ph) in ("3", "auto") else 1, charger_data))
                        _rt = _risk[0] if _risk else ""
                        if _rt != (all_overrides.get(f"{car_id}_goal_risk") or ""):
                            logger.set_override(f"{car_id}_goal_risk", _rt)
                            all_overrides[f"{car_id}_goal_risk"] = _rt
                        if _risk and _goal_risk_alerted.get(car_id) != _t_dt:
                            _goal_risk_alerted[car_id] = _t_dt
                            _gname = _sp.get("name") or car_id
                            print(f"⏰ {_gname}: {_rt}")
                            notifier.send_emil(f"⏰ {_gname} hinner inte målet", _rt, {"tag": f"goal_risk_{car_id}"}, key="elbil")
                    except Exception as _gre:
                        print(f"⚠️ Kontroll av laddmålet ({car_id}): {_gre}")
                else:
                    last_sent_ev_limit[car_id] = None
                    if all_overrides.get(f"{car_id}_limit_note"):
                        logger.set_override(f"{car_id}_limit_note", "")
                        all_overrides[f"{car_id}_limit_note"] = ""
                try:
                    _sib = any(
                        ((car_charger_data.get(_o) or {}).get("power_kw") or 0) > 0.5
                        for _o in car_ids if _o != car_id
                    )
                    _track_ev_need(car_id, car_soc.get(car_id), ev_amps.get(car_id, 0),
                                   charger_data if connected else None, _sib, now)
                except Exception as _twe:
                    print(f"⚠️ Missad-laddning-spårning ({car_id}): {_twe}")
                # Laddar bilen långsammare än vi beställt? Säg varför (ev_hold.py) - visas i appen och på webben
                try:
                    _ht = _ev_hold.step(car_id, ev_amps[car_id] if connected and not ev_phase_switch_active[car_id] else 0,
                                        charger_data, time.time())
                    if _ht:
                        _ev_hold_now[_EV_NAMES.get(car_id, car_id.capitalize())] = _ht
                    if connected and not ev_phase_switch_active[car_id]:
                        _journal.append(control_journal.check_ev(_EV_NAMES.get(car_id, car_id.capitalize()), ev_amps[car_id],
                                                                 charger_data, _ht))
                except Exception as _he:
                    print(f"⚠️ Laddförklaringen ({car_id}): {_he}")
            _hs = json.dumps(_ev_hold_now, ensure_ascii=False, sort_keys=True) if _ev_hold_now else "ok"
            if _hs != _ev_hold_state["stored"]:
                if _ev_hold_now:
                    print(f"🚗ℹ️ Laddar långsammare än planen: {'; '.join(_ev_hold_now.values())}")
                logger.set_override("ev_hold", _hs)
                _ev_hold_state["stored"] = _hs
            _ev_hold_now.clear()

            # Pump Setpoint
            ov_smart_mode = all_overrides.get("pump_smart_mode", "auto")
            if ov_smart_mode != "manual":
                ov_heat  = all_overrides.get("heat", "auto")
                if ov_heat == "on": current_chosen_temp = int(cfg["temp_cheap"] * 10)
                elif ov_heat == "off": current_chosen_temp = int(cfg["temp_expensive"] * 10)
                
                actual_pump_setpoint = pump_data.get("room_temp_setpoint") if pump_data else None
                needs_update = False
                _journal.append(control_journal.check_pump(current_chosen_temp / 10.0, actual_pump_setpoint))
                if actual_pump_setpoint is not None:
                    # > 5 tiondelar: pumpar som sparar hela grader (Thermia läser tillbaka 16,5 som 16) ska inte få samma
                    # värde omskrivet varje minut (sett 2026-11-06: 16,5 °C skrevs 07:41-07:51 varje minut)
                    if abs(round(actual_pump_setpoint * 10) - current_chosen_temp) > 5: needs_update = True
                elif last_sent_temp != current_chosen_temp:
                    needs_update = True
                
                if needs_update:
                    print(f"🔧 Sätter pumpens måltemp till {current_chosen_temp/10.0}°C...")
                    # Drivrutinerna tar °C (HeatPumpDriver.set_room_temp); current_chosen_temp är i tiondelar (issue #151:
                    # NIBE/myUplink/climate fick 200 °C i stället för 20,0). Thermia räknar om till tiondelar själv.
                    if heat_pump_driver.set_room_temp(current_chosen_temp / 10.0): last_sent_temp = current_chosen_temp
            else:
                ov_pump_mode = all_overrides.get("pump_operating_mode", "auto")
                try:
                    manual_mode = int(ov_pump_mode)
                    if manual_mode != last_sent_operating_mode:
                        print(f"🔧 Överstyrning: Sätter pump manuellt till {manual_mode}")
                        if heat_pump_driver.set_operating_mode(manual_mode):
                            last_sent_operating_mode = manual_mode
                            pump_operating_mode_from_pump = manual_mode 
                except (ValueError, TypeError):
                    pass

            # Höll vi planen? (control_journal.py) - inget i skuggläge, där beställs ingenting
            if not shadow.active():
                try:                                   # #387: aviseringsrader som inte kunde sparas tidigare
                    import notify_log
                    notify_log.flush()
                except Exception:
                    pass
                control_journal.record(logger.get_db, _journal[-12:], time.time())
            _journal.clear()

            # Solar Limit
            new_solar_limit = gpm_actions.get("solar_limit_pct")
            # Flashminnet i växelriktaren tål begränsat antal skrivningar - start/stopp direkt,
            # finjustering högst var 5:e minut (solar_write_guard.py).
            if isinstance(new_solar_limit, (int, float)) and solar_write_guard.should_write(
                    new_solar_limit, last_sent_solar_limit, last_solar_write_at, now):
                if solar_driver.set_export_limit_pct(int(new_solar_limit)):
                    last_sent_solar_limit = new_solar_limit
                    last_solar_write_at = now
                    
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

            if HAS_SPA and cfg.get('spa_force_heat', False):
                print(f"🔥 [TVÅNGSVÄRME AKTIV] GPM Mål: {new_spa_target}°C, Eco: {new_spa_eco} | Faktiskt i HA: {actual_spa_target}°C")

            if HAS_SPA and (last_sent_spa_target != new_spa_target or last_sent_spa_eco != new_spa_eco or 
                (actual_spa_target is not None and abs(actual_spa_target - new_spa_target) > 0.1) or
                (actual_spa_eco is not None and actual_spa_eco != new_spa_eco)):
                print(f"🛁 => SKICKAR NYA VÄRDEN TILL SPABADET! (Eco: {new_spa_eco}, Target: {new_spa_target}°C)")
                spa_driver.set_economy(new_spa_eco)
                time.sleep(0.5)
                spa_driver.set_target_temp(float(new_spa_target))
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

            for _c in car_ids:                       # "laddningen startade" per bil (förut bara Nissan)
                _cd = car_charger_data.get(_c) or {}
                c_status = _cd.get("status")
                _pw = float(_cd.get("power_kw") or 0.0)
                # 2026-11-12: status kunde bli "charging" med 0 kW (Leaf) och gav falsk startnotis
                # samtidigt som Tesla faktiskt laddade - kräv uppmätt effekt.
                if c_status == "charging" and _pw >= 0.5 and last_ev_status.get(_c) not in (None, "charging"):
                    if cfg.get("notify_ev_start", True):
                        notifier.notify_ev_charging(CAR_SPECS.get(_c, {}).get("name", _c), _pw)
                last_ev_status[_c] = c_status

            for _an, _ast in appliance_states.items():
                _run = str(_ast).lower() not in ("off", "unavailable", "unknown", "none", "idle", "standby", "av", "0", "0.0")
                if _run and last_appliance_running.get(_an) is False and cfg.get("notify_washer_start", True):
                    notifier.send_emil(f"🧺 {_an} har startat", f"{_an} är igång.", key="ovrigt")
                last_appliance_running[_an] = _run

            # --- SÄKERHETSLARM: Kallt inomhus (slår INTE på värmen) ---
            # Viktigt när pumpen står i manuellt läge, då GPM:s automatiska kylskydd är ur spel.
            if indoor_temp is not None:
                _cold_confirmed = _cold_alert_watch.update(indoor_temp < INDOOR_COLD_ALERT_C, now)
                if _cold_confirmed and not indoor_cold_alerted:
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
            avg_tot = energy_balance.pump_el_w(pump_data, _estimate_pump_el_w)   # uppmätt när pumpen ger det (#178)
            if pump_data and pump_data.get("compressor_running") == 1:
                forward = pump_data.get("forward_temp") or 45.0
                brine = pump_data.get("brine_in_temp") or 0.0
                delta_t = max(5.0, forward - brine)
                carnot_efficiency = 0.60 - (forward * 0.0025)
                cop = round(max(1.5, min(6.5, ((forward + 273.15) / delta_t) * carnot_efficiency)), 2)
                pump_data["compressor_power_kw"] = round((avg_tot / 1000.0) * cop, 2)
            else:
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
                
                if HAS_SPA and spa_reboot_stage == 0:
                    spa_driver.set_plug_power(True)
                
                for log_msg in gpm_actions["log"]:
                    print(f"  {log_msg}")

                if ov_smart_mode != "manual":
                    water_sp.apply(heat_pump_driver, gpm_actions["water_target_temp"], sleep=time.sleep)
                        
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
                solar_now, pump_data, dict(solar_data or {}, limit_pct=current_solar_limit_pct,
                    battery_plan_id=((_battery.get("plan") or {}).get("plan_id")
                                     if battery_cfg["control"] == "styr" and battery_cfg.get("plan") else None),
                    battery_plan_rule=_battery.get("decision_rule")), ha_temps,
                # Laddboxarna loggas i installationens ordning (första -> ev_*, andra -> ev_carport_*) och bilarna under
                # sina egna id:n (<bil>_soc, <bil>_soc_stale ...). logger.py skapar kolumnerna och vekar
                # versaler (Volvo_Ex40 -> volvo_ex40), annars syns bilen inte på översikten (#293).
                (_charger_list[0] if _charger_list else None), cop=cop, ev_carport=(_charger_list[1] if len(_charger_list) > 1 else None),
                car_data={k: v for _c in car_ids for k, v in {
                    f"{_c}_soc": car_soc.get(_c),
                    f"{_c}_soc_stale": 1 if car_soc_stale.get(_c) else 0,
                    f"{_c}_climate_temp": (car_data.get(_c) or {}).get("climate_temp"),
                    f"{_c}_climate_state": (car_data.get(_c) or {}).get("climate_state"),
                    f"{_c}_charge_completed": ev_connection_state[_c]['charge_completed'],
                }.items()},
                pump_operating_mode=pump_operating_mode_from_pump,
                shelly_l1_a=avg_hl1, shelly_l2_a=avg_hl2, shelly_l3_a=avg_hl3,
                ev_avail_a=sum(ev_amps.values()),
                forecast_temp=forecast_temp, gecko=gecko_data, spa_power_w=spa_power_w,
                ai_action_log="\n\n".join(ai_thoughts_list),
                active_mode=current_mode, active_decision=current_decision,
                decision_summary=json.dumps(current_decision_items, ensure_ascii=False),
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
                    "sensor.smartbox_elpris": (_r1(current_price, 3), {"friendly_name": "Smartbox Elpris", "unit_of_measurement": f"{nordpool.cost_settings()['symbol']}/kWh", "icon": "mdi:cash", "nasta_pris": _r1(next_price, 3)}),
                    "sensor.smartbox_maltemperatur": (_r1(current_chosen_temp / 10.0), {"friendly_name": "Smartbox Måltemperatur", "unit_of_measurement": "°C", "device_class": "temperature"}),
                    "sensor.smartbox_framledning": (_r1(forward_temp), {"friendly_name": "Smartbox Framledning", "unit_of_measurement": "°C", "device_class": "temperature", "retur": _r1(return_temp), "beraknad": _r1(calc_forward)}),
                    "sensor.smartbox_utetemperatur": (_r1(outdoor_temp), {"friendly_name": "Smartbox Utetemperatur", "unit_of_measurement": "°C", "device_class": "temperature"}),
                    "sensor.smartbox_varmvatten": (_r1(water_temp), {"friendly_name": "Smartbox Varmvatten", "unit_of_measurement": "°C", "device_class": "temperature"}),
                    "sensor.smartbox_cop": (_r1(cop, 2), {"friendly_name": "Smartbox COP", "icon": "mdi:heat-pump"}),
                    "sensor.smartbox_lage": (current_mode, {"friendly_name": "Smartbox Läge", "icon": "mdi:brain"}),
                    "sensor.smartbox_beslut": ((current_decision or "")[:250] or None, {"friendly_name": "Smartbox Beslut", "icon": "mdi:head-cog", "per_enhet": current_decision_items, "fullstandigt": (current_decision or "")[:1500]}),
                    # Per bil: sensor.smartbox_<ha_name eller id>_batteri (Emils Leaf har ha_name: leaf i installationen)
                    **{f"sensor.smartbox_{CAR_HA_NAME.get(_c, _c)}_batteri": (
                        _r1(car_soc.get(_c), 0),
                        {"friendly_name": f"Smartbox {CAR_SPECS.get(_c, {}).get('name', _c)} batteri", "unit_of_measurement": "%",
                         "device_class": "battery", "senast_kand": bool(car_soc_stale.get(_c)),
                         "alder_min": (round((now - _soc_mem[_c][1]).total_seconds() / 60) if car_soc_stale.get(_c) and _soc_mem[_c][1] else 0)})
                       for _c in car_ids},
                    # SpotNav-idé: säg till batterisystemet (Predbat, EMHASS, växelriktarens BESS) när bilen
                    # laddar från NÄTET, så det kan låta bli att tömma batteriet i bilen. Av vid solladdning.
                    "binary_sensor.smartbox_elbil_laddar_fran_natet": (
                        "on" if any((a or 0) >= EV_MIN_CHARGE_AMPS for a in ev_amps.values())
                                and not getattr(gpm_engine, "ev_solar_charge_active", False) else "off",
                        {"friendly_name": "Smartbox Elbil laddar från nätet", "icon": "mdi:transmission-tower-import",
                         "bilar": [c for c, a in ev_amps.items() if (a or 0) >= EV_MIN_CHARGE_AMPS]}),
                    "binary_sensor.smartbox_kompressor": ("on" if (pump_data and pump_data.get("compressor_running") == 1) else "off", {"friendly_name": "Smartbox Kompressor", "device_class": "running"}),
                }
                threading.Thread(target=homeassistant.publish_states, args=(_pub,), daemon=True).start()
            except Exception as _pe:
                print(f"⚠️ Kunde inte publicera till HA: {_pe}")

            # Fas-inlärning: logga per-fas-effekt + spabadets aktiviteter (1/min) → underlag för
            # learnern som lär sig vilken fas som driver värmare/pump/blåsare/…
            try:
                if HAS_SPA:                                   # #156: inget spabad -> ingen fas-loggning
                    _spa_act = spa_driver.read_activities()
                    logger.log_spa_phase(spa_power_data.get('phase_a_w'), spa_power_data.get('phase_b_w'),
                                         spa_power_data.get('phase_c_w'), _spa_act)
            except Exception as _spe:
                print(f"spa_phase-logg hoppade över: {_spe}")

            # ── LAST-NEDBRYTNING: förklara husets effekt med det vi FAKTISKT mäter ────────
            # total = elbil + värmepump + spa + OFÖRKLARAT (ugn/bastu/tvätt/…).
            try:
                _ev_w   = sum(((d or {}).get("power_kw") or 0.0) for d in _charger_list) * 1000.0
                # OBS: compressor_power_kw är VÄRME-uteffekt (el×COP), INTE el. Pumpens faktiska
                # EL-effekt är avg_tot (~2200 W när kompressorn går, annars 0). Använd den här.
                _pump_w = avg_tot if avg_tot else 0.0
                _spa_w  = spa_power_w or 0.0
                # Vilken bil laddar? Publiceras som sensor.smartbox_elbil_laddar (energiflödet i HA visar annars bara "Elbil").
                _laddar = [CAR_SPECS.get(_c, {}).get("name", _c) for _c in car_ids
                           if (d := car_charger_data.get(_c)) and ((d.get("power_kw") or 0.0) > 0.3 or str(d.get("status")) == "charging")]
                _laddar_txt = " + ".join(_laddar) if _laddar else "Ingen"
                if _solar_persist.get("laddar") != _laddar_txt:
                    from database_engine import engine as _eng
                    from sqlalchemy import text as _tx
                    with _eng.begin() as _c:
                        _c.execute(_tx("INSERT INTO overrides (device, mode, updated_at) VALUES ('ev_charging_car', :m, NOW()) ON CONFLICT (device) DO UPDATE SET mode = EXCLUDED.mode, updated_at = NOW()"), {"m": _laddar_txt})
                    _solar_persist["laddar"] = _laddar_txt
                # #192: egna laster (loads: i installationen) räknas som förklarad last och loggas var för sig
                _extra = []
                for _ld in house_config.custom_loads(house_cfg):
                    _vals = [homeassistant.get_power_w(_e) for _e in _ld["entities"]]
                    _vals = [v for v in _vals if isinstance(v, (int, float)) and math.isfinite(v)]
                    if _vals:
                        _extra.append({"name": _ld["name"], "w": round(max(0.0, sum(_vals)))})
                _known_w = _ev_w + _pump_w + _spa_w + sum(x["w"] for x in _extra)
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
                _meter_frozen = _meter_freeze.frozen(avg_net, (avg_hl1, avg_hl2, avg_hl3), time.time())
                _lc = health.load_check(_total_w, _known_w, avg_net, (avg_hl1, avg_hl2, avg_hl3), _pv_frozen, meter_frozen=_meter_frozen)
                _unexpl_w = _lc["unexplained_w"]
                logger.log_load_breakdown(_total_w, _ev_w, _pump_w, _spa_w, _unexpl_w, extra=_extra)
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
        # Kodplatsen (fil:rad i EnergyWizards egen kod), aldrig feltexten - så att felet går att hitta (2026-11-08: Hus 33
        # rapporterade bara "main_loop: TypeError")
        telemetry.report_error(house_cfg, "main_loop@" + telemetry.code_location(e.__traceback__), type(e).__name__)
        time.sleep(10)
