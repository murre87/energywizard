import os
import requests
import urllib3
import traceback

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- INSTÄLLNINGAR ---
HA_IP    = os.environ.get("HA_IP")
HA_PORT  = 8123
HA_TOKEN = os.environ.get("HA_TOKEN", "").strip("\"'")

EASEE_LITE_ID = os.environ.get("EASEE_CHARGER_ID") # Nissan
if not EASEE_LITE_ID: EASEE_LITE_ID = "EHLS9NVL"

EASEE_CARPORT_ID = os.environ.get("EASEE_CARPORT_ID") # Tesla
if not EASEE_CARPORT_ID: EASEE_CARPORT_ID = "EHLU7JCT"

TEMPERATURE_ENTITIES = {
    "indoor_1":     "sensor.tempsensor_1_temperatur",
    "ute":          "sensor.tempsensor_2_ute_temperatur",
    "matter_1":     "sensor.timmerflotte_temp_hmd_sensor_temperatur",
    "matter_2":     "sensor.timmerflotte_temp_hmd_sensor_temperatur_2",
    "matter_3":     "sensor.timmerflotte_temp_hmd_sensor_temperatur_3",
    "esp":          "sensor.esp_tempsensor",
}

HUMIDITY_ENTITIES = {
    "indoor_1": "sensor.tempsensor_1_luftfuktighet",
    "matter_1": "sensor.timmerflotte_temp_hmd_sensor_luftfuktighet",
    "matter_2": "sensor.timmerflotte_temp_hmd_sensor_luftfuktighet_2",
    "matter_3": "sensor.timmerflotte_temp_hmd_sensor_luftfuktighet_3",
    "esp":      "sensor.athom_temperature_humidity_sensor_4b73a0_humidity",
}

EASEE_LITE_ENTITIES = {
    "power_kw":        "sensor.easee_lite_effekt",
    "current_a":       "sensor.easee_lite_strom",           # 2026-10-15: uppmätt laddström (aktiverad i HA; max-allowed-sensorn är otillgänglig)
    "circuit_current": "sensor.easee_lite_maximum_allowed_charge_current",
    "dynamic_limit":   "sensor.easee_lite_maximum_allowed_charge_current",
    "output_limit":    "sensor.easee_lite_maximum_allowed_charge_current",
    "max_limit":       "sensor.easee_lite_maximum_allowed_charge_current",
    "session_kwh":     "sensor.easee_lite_energi_laddningssession",
    "lifetime_kwh":    "sensor.easee_lite_livstidsforbrukning",
    "status":          "sensor.easee_lite_status",
    "online":          "binary_sensor.easee_lite_online",
    "phases":          "select.easee_lite_allowed_charging_phases",
    "reason_no_current": "sensor.easee_lite_status",
    "current_l1":      "sensor.easee_lite_strom_l1",
    "current_l2":      "sensor.easee_lite_strom_l2",
    "current_l3":      "sensor.easee_lite_strom_l3",
}

EASEE_CARPORT_ENTITIES = {
    "power_kw":        "sensor.carport_effekt",
    "current_a":       "sensor.carport_strom",              # 2026-10-15: uppmätt laddström (aktiverad i HA)
    "session_kwh":     "sensor.carport_energi_laddningssession",
    "status":          "sensor.carport_status",
    "online":          "binary_sensor.carport_online",
    "phases":          "select.carport_allowed_charging_phases",
    "current_l1":      "sensor.carport_strom_l1",
    "current_l2":      "sensor.carport_strom_l2",
    "current_l3":      "sensor.carport_strom_l3",
}

NISSAN_ENTITIES = {
    "soc": "sensor.leaf_battery_level",
    "climate": "climate.leaf_climate",
    "plugged_in": "binary_sensor.leaf_plugged_in"
}

TESLA_ENTITIES = {
    "soc": "sensor.tesla_model_y_battery", # Kommer börja fungera tyst och automatiskt på måndag!
    "amps": "number.tesla_model_y_charging_amps",
    "charging": "binary_sensor.tesla_model_y_charging",
    "plugged_in": "binary_sensor.tesla_model_y_charger",
    "charging_state": "sensor.tesla_model_y_charging_state"
}

# --- TIBBER (Ersätter Shelly för husets total) ---
TIBBER_ENTITIES = {
    "v1": "sensor.tibber_pulse_malmgatan_34_spanning_fas1",
    "v2": "sensor.tibber_pulse_malmgatan_34_spanning_fas2",
    "v3": "sensor.tibber_pulse_malmgatan_34_spanning_fas3",
    "i1": "sensor.tibber_pulse_malmgatan_34_strom_fas1",
    "i2": "sensor.tibber_pulse_malmgatan_34_strom_fas2",
    "i3": "sensor.tibber_pulse_malmgatan_34_strom_fas3",
}

# --- SOLAREDGE (Från HA) ---
SOLAREDGE_ENTITIES = {
    "pv_power_w": "sensor.solaredge_aktuell_effekt",
    "today_kwh": "sensor.solaredge_el_i_dag",
}

# --- GECKO SPABAD ---
GECKO_ENTITIES = {
    "current_temp": "sensor.spa_malmgatan_34_current_temperature",
    "target_temp":  "sensor.spa_malmgatan_34_target_temperature",
    "economy_mode": "switch.spabad_economy_mode",
}

# --- SPABADETS SMARTPLUGG ---
# Spabadets Shelly Plug S Gen3 (enheten "Spabadsplugg" i Shelly-integrationen). Tidigare pekade koden på Matter-entiteten
# switch.shelly_plug_s_gen3, men den noden finns inte längre i Matter-servern (otillgänglig sedan dess), så omstarten av spabadet fungerade aldrig.
SPA_PLUG = "switch.shelly2"

# --- ROBOTGRÄSKLIPPARE ---
# Shelly-plugg som matar klipparens laddstation.
# Entitets-id verifierade direkt mot Home Assistant (live).
MOWER_ENTITIES = {
    "power_w": "sensor.shellyb1_effekt",
    "is_on":   "switch.shellyb1",
    "energy":  "sensor.shellyb1_energi",
}

_BASE = f"https://{HA_IP}:{HA_PORT}/api"
_HEADERS = {
    "Authorization": f"Bearer {HA_TOKEN}",
    "Content-Type": "application/json",
}

_states_cache = {}

def publish_states(entities: dict):
    """Publicerar smartbox-värden som sensorer i HA (POST /api/states/<entity_id>) så de kan visas i dashboarden.
    entities = {entity_id: (state, attributes)}. Sensorerna är icke-persistenta (finns tills HA startas om) och
    uppdateras varje minut. Körs i egen tråd; avbryter vid första fel så att en nedstängd HA aldrig hindrar något."""
    for entity_id, (state, attrs) in entities.items():
        if state is None:
            continue
        try:
            r = requests.post(f"{_BASE}/states/{entity_id}", headers=_HEADERS,
                              json={"state": state, "attributes": attrs}, timeout=3, verify=False)
            r.raise_for_status()
        except Exception:
            return

last_update_ok = True   # Senaste update_states() lyckades? (används av health.LinkWatch)

def update_states():
    """Hämtar ALLA states från Home Assistant API:et i en enda effektiv request."""
    global _states_cache, last_update_ok
    try:
        r = requests.get(f"{_BASE}/states", headers=_HEADERS, timeout=5, verify=False)
        r.raise_for_status()
        _states_cache = {s["entity_id"]: s for s in r.json()}
        last_update_ok = True
        return True
    except Exception as e:
        last_update_ok = False
        _states_cache.clear()
        print(f"❌ HA: Fel vid update_states: {e}")
        traceback.print_exc()
        return False


def _get_raw_state(entity_id):
    """Hämtar rå-strängen från en sensor utan att konvertera den till siffror."""
    if not _states_cache:
        update_states()
    s = _states_cache.get(entity_id)
    if not s:
        return None
    state = s.get("state", "unavailable")
    return state if state not in ("unavailable", "unknown", "") else None


def _get_numeric_state(entity_id):
    """
    Hämtar tillstånd och konverterar allt till siffror.
    'on'/'open' -> 1
    'off'/'closed' -> 0
    Returnerar float om möjligt, annars str/None.
    """
    raw = _get_raw_state(entity_id)
    if raw is None:
        return None
        
    # Översätt ord till 1 eller 0 för ML
    if raw.lower() in ("on", "open", "true"):
        return 1.0
    if raw.lower() in ("off", "closed", "false"):
        return 0.0
        
    try:
        return float(raw)
    except ValueError:
        # Kan vara en status-text (t.ex. 'charging'), skippa varning.
        return None

def _get_numeric_attribute(entity_id, attribute):
    """Hämtar ett specifikt attribut från en entitet och konverterar till float."""
    if not _states_cache:
        update_states()
    s = _states_cache.get(entity_id)
    if not s:
        return None
    raw = s.get("attributes", {}).get(attribute)
    
    if raw in ("unavailable", "unknown", "", None):
        return None
        
    try:
        return float(raw)
    except ValueError:
        return None

def read_temperatures():
    return {key: _get_numeric_state(entity) for key, entity in TEMPERATURE_ENTITIES.items()}

def read_humidities():
    """Luftfuktighet (%) per inomhussensor, samma nycklar som TEMPERATURE_ENTITIES."""
    return {key: _get_numeric_state(entity) for key, entity in HUMIDITY_ENTITIES.items()}

# Fasläge: HA:s Easee-integration (0.9.74, efter HA-uppdateringen 2026-10-14) har inga select-entiteter längre (select.*_allowed_charging_phases finns inte),
# så fasläget går inte att läsa. Vi minns det senast satta värdet per laddare; utan minne (efter omstart) returneras None (okänt).
_PHASE_STATE: dict = {}


def _phase_key(charger_id=None, entities=None):
    if entities is not None:
        return "lite" if entities is EASEE_LITE_ENTITIES else "carport"
    return "lite" if charger_id == EASEE_LITE_ID else "carport"


def _read_easee_charger(entities: dict):
    try:
        result = {}
        for key, entity in entities.items(): 
            if key in ("status", "reason_no_current"):
                result[key] = _get_raw_state(entity)
            else:
                result[key] = _get_numeric_state(entity)

        # Fasströmmar: integrationen har en enda ström-sensor; fasernas strömmar ligger som attribut (T3/T4/T5 = L1/L2/L3).
        _ce = entities.get("current_a")
        if _ce:
            for _k, _a in (("current_l1", "inCurrentT3"), ("current_l2", "inCurrentT4"), ("current_l3", "inCurrentT5")):
                if result.get(_k) is None:
                    result[_k] = _get_numeric_attribute(_ce, _a)

        raw_power = result.get("power_kw")
        power_kw = (raw_power / 1000.0) if raw_power is not None and raw_power > 100 else raw_power

        # FIX #9 (konservativ, bakåtkompatibel): faktiskt uppmätt fasström.
        # current_l1/l2/l3 lästes tidigare in i result men returnerades aldrig,
        # trots att main.py (rad 953-958) hämtar dem för lastbalansering -> de blev alltid None.
        # Vi inkluderar dem nu i return-dicten (för BÅDA laddarna; saknas entiteten blir den None).
        cur_l1 = result.get("current_l1")
        cur_l2 = result.get("current_l2")
        cur_l3 = result.get("current_l3")

        # current_a pekade på maximum_allowed_charge_current (gränsvärde, ej uppmätt ström).
        # Om en faktisk strömsensor finns (current_l1/l2/l3) använder vi den uppmätta strömmen
        # (max över faserna) så att loggad ev_current_a speglar verkligheten.
        # Saknas mätsensorer behålls det gamla beteendet (gränsvärdet) -> inget bryts.
        measured_phases = [c for c in (cur_l1, cur_l2, cur_l3) if c is not None]
        current_a = max(measured_phases) if measured_phases else result.get("current_a")

        return {
            "power_kw":        power_kw,
            "current_a":       current_a,
            "current_l1":      cur_l1,
            "current_l2":      cur_l2,
            "current_l3":      cur_l3,
            "dynamic_limit_a": result.get("dynamic_limit"),
            "output_limit_a":  result.get("output_limit"),
            "max_limit_a":     result.get("max_limit"),
            "session_kwh":     result.get("session_kwh"),
            "lifetime_kwh":    result.get("lifetime_kwh"),
            "status":          result.get("status"),
            "online":          bool(result.get("online")),
            "reason_no_current": result.get("reason_no_current"),
            "phases":          _get_raw_state(entities.get("phases")) or _PHASE_STATE.get(_phase_key(entities=entities))
        }
    except Exception as e:
        print(f"❌ HA: Fel vid läsning av laddare: {e}")        
        return None




def read_easee_lite():
    return _read_easee_charger(EASEE_LITE_ENTITIES)

def read_easee_carport():
    return _read_easee_charger(EASEE_CARPORT_ENTITIES)

def read_nissan_data():
    return {
        "soc": _get_numeric_state(NISSAN_ENTITIES["soc"]),
        "climate_temp": _get_numeric_attribute(NISSAN_ENTITIES["climate"], "current_temperature"),
        "climate_state": _get_raw_state(NISSAN_ENTITIES["climate"]),
        "plugged_in": _get_numeric_state(NISSAN_ENTITIES["plugged_in"])
    }

def read_tesla_data():
    return {
        "soc": _get_numeric_state(TESLA_ENTITIES["soc"]),
        "plugged_in": _get_numeric_state(TESLA_ENTITIES["plugged_in"]),
        "charging_state": ("charging" if _get_raw_state("binary_sensor.tesla_model_y_charging") == "on" else _get_raw_state(TESLA_ENTITIES["charging_state"]))   # sensor.tesla_model_y_charging_state finns inte längre
    }

def read_tibber_data():

    """Hämtar spänning och ström från Tibber och beräknar nettoeffekt."""
    try:
        v1 = _get_numeric_state(TIBBER_ENTITIES["v1"])
        v2 = _get_numeric_state(TIBBER_ENTITIES["v2"])
        v3 = _get_numeric_state(TIBBER_ENTITIES["v3"])
        i1 = _get_numeric_state(TIBBER_ENTITIES["i1"])
        i2 = _get_numeric_state(TIBBER_ENTITIES["i2"])
        i3 = _get_numeric_state(TIBBER_ENTITIES["i3"])

        if None in (v1, v2, v3, i1, i2, i3):
            return None

        # P = U * I. Negativ ström i Tibber betyder export.
        p1 = v1 * i1
        p2 = v2 * i2
        p3 = v3 * i3
        net_power = p1 + p2 + p3

        return {
            "net_power_w": net_power,
            "l1_a": i1,
            "l2_a": i2,
            "l3_a": i3,
    }
    except Exception as e:
        print(f"❌ Fel vid Tibber-läsning: {e}")
        return None


def read_solaredge():
    """Hämtar solproduktion från SolarEdge via Home Assistant, med fallback till moln-integrationen om Modbus strular."""
    def get_first_numeric(entities):
        for e in entities:
            val = _get_numeric_state(e)
            if val is not None: return val
        return None

    def get_first_raw(entities):
        for e in entities:
            val = _get_raw_state(e)
            if val is not None: return val
        return None
        
    # CLEANUP: använd SOLAREDGE_ENTITIES som primär källa i fallback-listorna så att
    # det bara finns EN sanningskälla för entitets-id (dicten var tidigare oanvänd/vilseledande).
    # Samma primära entiteter som förut -> oförändrat beteende.
    return {
        # Live-värdet från Modbus (uppdateras var några sekunder) FÖRST. Moln-integrationen (solaredge_aktuell_effekt)
        # uppdateras bara var 15:e minut och kan därför ligga flera kW fel när det växlar molnigt/soligt
        # (2026-09-20: 6865 W kvar från molnet medan inverterns riktiga effekt var ~270 W -> falsk "oförklarad last").
        # Moln-värdet används bara om Modbus saknas/är otillgänglig.
        "pv_power_w": get_first_numeric(["sensor.solaredge_i1_ac_power", SOLAREDGE_ENTITIES["pv_power_w"], "sensor.solaredge_current_power", "sensor.solaredge_ac_power"]),
        "today_kwh": get_first_numeric([SOLAREDGE_ENTITIES["today_kwh"], "sensor.solaredge_energy_today"]),
        "status": get_first_raw(["sensor.solaredge_i1_status", "sensor.solaredge_status"])
    }

def read_gecko():
    """Läs av spabadets nuvarande och måltemperatur."""
    data = {key: _get_numeric_state(entity) for key, entity in GECKO_ENTITIES.items()}
    
    # Läs den sanna måltemperaturen direkt från climate-entitetens attribut om möjligt
    try:
        r = requests.get(f"{_BASE}/states/climate.spabad_heater", headers=_HEADERS, timeout=5, verify=False)
        if r.status_code == 200:
            attrs = r.json().get("attributes", {})
            if "temperature" in attrs and attrs["temperature"] is not None:
                data["target_temp"] = float(attrs["temperature"])
    except Exception:
        pass

    data["heater_state"] = _get_raw_state("water_heater.spa_malmgatan_34_heater")
    return data

def read_spa_power():
    """Läser 3-fas-mätaren på spabadet (Shelly 'Spabad'). Effekten rapporteras NEGATIV pga
    CT-klämmans riktning → vi tar beloppet. Returnerar per-fas + total effekt (W) samt
    säkerhetsflaggorna från spa-pluggen (shelly2). None om mätaren inte svarar."""
    def _p(ph):
        v = _get_numeric_state(f"sensor.spabad_phase_{ph}_effekt")
        return abs(float(v)) if v is not None else None
    pa, pb, pc = _p('a'), _p('b'), _p('c')
    present = [x for x in (pa, pb, pc) if x is not None]
    total = sum(present) if present else None
    def _flag(eid):
        return str(_get_raw_state(eid)).lower() == 'on'
    return {
        'phase_a_w': pa, 'phase_b_w': pb, 'phase_c_w': pc, 'total_w': total,
        'overcurrent':   _flag('binary_sensor.shelly2_overstrom'),
        'overvoltage':   _flag('binary_sensor.shelly2_overspanning'),
        'overheated':    _flag('binary_sensor.shelly2_overhettad'),
        'power_exceeded':_flag('binary_sensor.shelly2_effekt_overskrids'),
    }

def read_spa_activities():
    """Läser spabadets AKTIVITETS-states (Gecko) — vilken funktion som är PÅ just nu. Används för
    att LÄRA sig vilken fas som driver vad genom att korrelera mot per-fas-effekten."""
    def _on(eid):
        return str(_get_raw_state(eid)).lower() in ('on', 'heating', 'true')
    return {
        'heating':   _on('binary_sensor.spa_malmgatan_34_heating'),
        'circ_pump': _on('binary_sensor.spabad_circulating_pump'),
        'pump1':     _on('fan.spabad_pump_1'),
        'blower':    _on('fan.spa_malmgatan_34_blower'),
        'waterfall': _on('fan.spabad_waterfall'),
        'lights':    _on('light.spabad_lights'),
        'ozone':     _on('binary_sensor.spabad_ozone'),
    }

def read_mower_data():
    """Läser av robotgräsklipparens smart plug.

    Returnerar dict med 'power_w' (W), 'is_on' (bool) och 'energy_kwh' (kWh),
    eller None om avläsningen helt misslyckas. 'is_on' baseras på switchens
    rå-tillstånd ('on'/'off') – inte på effekten – så att en klippare som är ute
    och drar 0 W ändå räknas som påslagen plugg."""
    try:
        return {
            "power_w":    _get_numeric_state(MOWER_ENTITIES["power_w"]),
            "is_on":      _get_raw_state(MOWER_ENTITIES["is_on"]) == "on",
            "energy_kwh": _get_numeric_state(MOWER_ENTITIES["energy"]),
        }
    except Exception:
        return None

def read_ev_trackers():
    """Läser av GPS-positioner för bilarna för Smart Hemkomst-prognos."""
    return {
        "nissan_lat": _get_numeric_attribute("device_tracker.leaf_location", "latitude"),
        "nissan_lon": _get_numeric_attribute("device_tracker.leaf_location", "longitude"),
        "tesla_lat": _get_numeric_attribute("device_tracker.tesla_model_y_location_tracker", "latitude"),
        "tesla_lon": _get_numeric_attribute("device_tracker.tesla_model_y_location_tracker", "longitude"),
    }

def read_miele():
    """Läs av Miele tvättmaskin."""
    return {
        "status":     _get_raw_state("sensor.tvattmaskin"),
        "phase":      _get_raw_state("sensor.tvattmaskin_programfas"),
        "remote":     _get_numeric_state("binary_sensor.tvattmaskin_fjarrkontroll"),
    }

def set_gecko_economy(enable: bool):
    """Slår på eller av Economy Mode för Spabadet via HA."""
    try:
        r = requests.post(
            f"{_BASE}/services/switch/turn_{'on' if enable else 'off'}",
            headers=_HEADERS,
            json={"entity_id": "switch.spabad_economy_mode"},
            timeout=5,
            verify=False,
        )
        r.raise_for_status()
        print(f"🛁 Spabad: Economy Mode {'AKTIVERAT' if enable else 'AVAKTIVERAT'}")
        return True
    except Exception as e:
        print(f"❌ Spabad: Fel vid ändring av Economy Mode: {e}")
        return False

def set_gecko_target(temp: float):
    """Sätter spabadets måltemperatur via HA."""
    try:
        r = requests.post(
            f"{_BASE}/services/climate/set_temperature",
            headers=_HEADERS,
            json={"entity_id": "climate.spabad_heater", "temperature": float(temp)},
            timeout=5,
            verify=False,
        )
        r.raise_for_status()
        print(f"🛁 Spabad: Måltemperatur satt till {temp}°C")
        return True
    except Exception as e:
        print(f"❌ Spabad: Fel vid sättning av temp: {e}")
        return False

def set_ev_dynamic_limit(charger_id: str, ampere: int, reason: str = None):
    if int(ampere) > 0:
        ampere = max(6, min(int(ampere), 32)) 
    else:
        ampere = 0
    try:
        r = requests.post(
            f"{_BASE}/services/easee/set_charger_dynamic_limit",
            headers=_HEADERS,
            json={"charger_id": charger_id, "current": ampere},
            timeout=5,
            verify=False,
        )
        r.raise_for_status()
        if ampere == 0 and reason:
            print(f"⚡ Easee: Dynamisk gräns satt till 0 A. Anledning: {reason}")
        else:
            print(f"⚡ Easee: Dynamisk gräns satt till {ampere} A")
        return True
    except requests.exceptions.HTTPError as e:
        print(f"❌ Easee: Fick 500 Server Error. Är Laddar-ID '{charger_id}' korrekt? Lägg in EASEE_CHARGER_ID=ditt_id i .env filen! Felet var: {e}")
        return False
    except Exception as e:
        print(f"❌ Easee: Fel vid sättning av strömgräns: {e}")
        return False

def set_easee_phases(charger_id: str, phases: int):
    """Sätter laddaren till 1-fas eller 3-fas via Easee-integrationens tjänst easee.set_charger_phase_mode (select-entiteten finns inte längre).
    Lyckas bara om HA svarar OK; då sparas det nya läget som 'nuvarande' (det går inte att läsa tillbaka), så att GPM inte begär samma byte varje minut."""
    if phases not in [1, 3]:
        print(f"❌ Easee: Ogiltigt fasval: {phases}. Måste vara 1 eller 3.")
        return False
    mode = "3_phase" if phases == 3 else "1_phase"
    try:
        r = requests.post(
            f"{_BASE}/services/easee/set_charger_phase_mode",
            headers=_HEADERS,
            json={"charger_id": charger_id, "phase_mode": mode},
            timeout=10, verify=False)
        r.raise_for_status()
        _PHASE_STATE[_phase_key(charger_id)] = "ThreePhase" if phases == 3 else "SinglePhase"
        print(f"⚡ Easee ({charger_id}): Fasläge satt till {phases}-fas (tjänst, {mode}).")
        return True
    except Exception as e:
        print(f"❌ Easee ({charger_id}): Fel vid sättning av fasläge: {e}")
        return False

def turn_on_charger(charger_id: str):
    """Tvingar laddaren att starta om den står i awaiting_start eller paused."""
    entity_id = "switch.easee_lite_laddboxen_aktiverad" if charger_id == EASEE_LITE_ID else "switch.carport_laddare_aktiverad"
    try:
        r = requests.post(
            f"{_BASE}/services/switch/turn_on",
            headers=_HEADERS,
            json={"entity_id": entity_id},
            timeout=5,
            verify=False,
        )
        r.raise_for_status()
        print(f"⚡ Easee ({charger_id}): Skickade 'turn_on' för att tvinga igång laddningen.")
        return True
    except Exception as e:
        print(f"❌ Easee ({charger_id}): Fel vid turn_on: {e}")
        return False

def turn_off_charger(charger_id: str):
    """Tvingar laddaren att stanna."""
    entity_id = "switch.easee_lite_laddboxen_aktiverad" if charger_id == EASEE_LITE_ID else "switch.carport_laddare_aktiverad"
    try:
        r = requests.post(
            f"{_BASE}/services/switch/turn_off",
            headers=_HEADERS,
            json={"entity_id": entity_id},
            timeout=5,
            verify=False,
        )
        r.raise_for_status()
        print(f"⚡ Easee ({charger_id}): Skickade 'turn_off' för att stoppa laddningen.")
        return True
    except Exception as e:
        print(f"❌ Easee ({charger_id}): Fel vid turn_off: {e}")
        return False

def get_solaredge_limit():
    """Hämtar Active Power Limit (%) för SolarEdge."""
    return _get_numeric_state("number.solaredge_modbus_active_power_limit")

def set_solaredge_limit(limit: int):
    """Sätter Active Power Limit (%) för SolarEdge."""
    try:
        r = requests.post(
            f"{_BASE}/services/number/set_value",
            headers=_HEADERS,
            json={"entity_id": "number.solaredge_modbus_active_power_limit", "value": str(limit)},
            timeout=5,
            verify=False,
        )
        r.raise_for_status()
        print(f"☀️ SolarEdge: Active Power Limit satt till {limit} %")
        return True
    except Exception as e:
        print(f"❌ SolarEdge: Fel vid sättning av limit: {e}")
        return False

def press_button(entity_id: str):
    """Trycker på en knapp i HA (t.ex. button.tesla_model_y_wake_up). Returnerar True om anropet gick igenom."""
    try:
        r = requests.post(f"{_BASE}/services/button/press", headers=_HEADERS,
                          json={"entity_id": entity_id}, timeout=5, verify=False)
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"❌ Kunde inte trycka på {entity_id}: {e}")
        return False

def set_car_climate(entity_id: str, hvac_mode: str, temperature: float = None):
    """Startar eller stoppar klimatanläggningen i bilen."""
    try:
        url = f"{_BASE}/services/climate/set_hvac_mode"
        # FIX #7: fånga responsen och anropa raise_for_status så att HTTP 4xx/5xx
        # (t.ex. okänd entity) propageras och funktionen returnerar False vid fel.
        r = requests.post(url, headers=_HEADERS, json={"entity_id": entity_id, "hvac_mode": hvac_mode}, verify=False, timeout=10)
        r.raise_for_status()

        if temperature is not None and hvac_mode != "off":
            url_temp = f"{_BASE}/services/climate/set_temperature"
            # FIX #7: samma felkontroll för temperatur-anropet.
            r_temp = requests.post(url_temp, headers=_HEADERS, json={"entity_id": entity_id, "temperature": temperature}, verify=False, timeout=10)
            r_temp.raise_for_status()

        print(f"🚗 Klimat: {entity_id} satt till {hvac_mode} ({temperature}°C)")
        return True
    except Exception as e:
        print(f"❌ Fel vid inställning av bilklimat: {e}")
        return False


def turn_on_lights(entity_ids: list):
    """Tänder en lista med lampor i Home Assistant."""
    if not entity_ids: return False
    try:
        r = requests.post(
            f"{_BASE}/services/light/turn_on",
            headers=_HEADERS,
            json={"entity_id": entity_ids},
            timeout=5,
            verify=False,
        )
        r.raise_for_status()
        print(f"💡 Tände lampor: {', '.join(entity_ids)}")
        return True
    except Exception as e:
        print(f"❌ Fel vid tändning av lampor i HA: {e}")
        return False

def toggle_mower_plug(turn_on: bool):
    """Slår på eller av strömmen till robotgräsklipparen."""
    service = "turn_on" if turn_on else "turn_off"
    try:
        r = requests.post(
            f"{_BASE}/services/switch/{service}",
            headers=_HEADERS,
            json={"entity_id": MOWER_ENTITIES["is_on"]},
            timeout=5,
            verify=False,
        )
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"❌ Fel vid styrning av robotgräsklipparens plugg: {e}")
        return False



def read_esphome_temp(ip="192.168.1.125"):
    """Försöker läsa temperaturen direkt från ESPHome:s inbyggda webbserver som fallback."""
    endpoints = ["temperature", "temperatur", "esp_tempsensor_temperature"]
    for ep in endpoints:
        try:
            r = requests.get(f"http://{ip}/sensor/{ep}", timeout=2)
            if r.status_code == 200:
                val = r.json().get("value")
                if val is not None:
                    return float(val)
        except Exception:
            continue
    return None

if __name__ == "__main__":
    print("Home Assistant Modul laddad.")