import os
import math
import time
import re
import requests as _requests_real


class _GuardedRequests:
    """requests, men anrop till HA:s /api/services/ (allt som ändrar något i huset) stoppas och loggas i skuggläget
    (shadow.py). Läsning, mallar och EnergyWizards egna sensorer (/api/states/sensor.smartbox_*) går som vanligt."""
    def __getattr__(self, name):
        return getattr(_requests_real, name)

    @staticmethod
    def post(url, *args, **kwargs):
        if "/services/" in str(url):
            import shadow
            if shadow.active():
                body = kwargs.get("json") or {}
                shadow.record(str(url).split("/services/", 1)[1], ", ".join(f"{k}={v}" for k, v in body.items()))
                return shadow.FakeResponse()
        return _requests_real.post(url, *args, **kwargs)


requests = _GuardedRequests()
import urllib3
import traceback

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- INSTÄLLNINGAR ---
HA_IP    = os.environ.get("HA_IP")
HA_PORT  = 8123
HA_TOKEN = os.environ.get("HA_TOKEN", "").strip("\"'")
# HA_URL (t.ex. http://192.168.1.10:8123) går före HA_IP. Med bara HA_IP gäller det gamla:
# https på port 8123. En adress utan http:// får http://, och utan port får den :8123.
HA_URL = os.environ.get("HA_URL", "").strip().strip("\"'").rstrip("/")

# EnergyWizard Open, Spår B: körd som Home Assistant-tillägg (Supervisor) injicerar
# SUPERVISOR_TOKEN automatiskt - då nås Core API lokalt via Supervisorns egen proxy
# istället för HA_IP/HA_TOKEN, utan att användaren behöver klistra in en token alls.
# Helt bakåtkompatibelt: docker-compose-driften sätter aldrig SUPERVISOR_TOKEN, så den
# faller igenom till exakt samma HA_IP/HA_TOKEN-väg som innan, oförändrat.
SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN")

# Easee-laddboxarnas id och entiteter kommer ur installationen (evs[].charger: id, entities, enable_switch).
# 2026-11-07: förut låg utvecklarens två laddboxar här som standard (serienummer, entiteter, påslagsbrytare).

# Givare väljs av användaren (Inställningar -> Givare, sparas som "sensors" i /data/energywizard.json):
#   {"indoor": [{"key": "in_1", "entity": "sensor.x_temperature", "label": "Vardagsrum",
#                "humidity": "sensor.x_humidity", "offset": -0.6, "esphome_ip": "192.168.1.50"}, ...],
#    "outdoor": "sensor.ute_temperatur"}
# Inget är hårdkodat (2026-11-04: förut låg utvecklarens egna givare här, och alla andra fick ingen innetemperatur
# utom värmepumpens). "key" styr loggkolumnen - indoor_1/matter_1..3/esp har egna kolumner i sensor_log.
def sensor_config() -> dict:
    try:
        import ew_settings
        cfg = ew_settings.get("sensors") or {}
        return cfg if isinstance(cfg, dict) else {}
    except Exception:
        return {}


# Utegivare i listan över innegivare (issue #149: "F750 Utomhustemperatur" 2,4 °C förkryssad bland innegivarna gav
# innetemperaturen (18,2 + 2,4) / 2 = 10,3 °C och larm om kallt hus). Samma mönster som webbens givarlista.
OUTDOOR_HINT = re.compile(r"\bute\b|utomhus|outdoor|outside|(^|[._\s])ute([._\s]|$)", re.I)
_outdoor_skip_warned: set = set()


def is_outdoor_sensor(entity: str | None, label: str | None = None, outdoor_entity: str | None = None) -> bool:
    if entity and outdoor_entity and entity == outdoor_entity:
        return True
    return bool(OUTDOOR_HINT.search(f"{entity or ''} {label or ''}"))


_PUBLISHED: set = set()          # entiteter EnergyWizard själv publicerar (publish_states)
_self_skip_warned: set = set()


def is_own_entity(entity) -> bool:
    """Publicerar EnergyWizard den här entiteten själv? Då får den aldrig läsas tillbaka som mätvärde (2026-11-15:
    sensor.smartbox_inomhustemp låg bland rumsgivarna; medianen läste sitt eget gamla värde och fastnade på 21,1 °C
    medan rummen svalnade)."""
    e = str(entity or "")
    return e in _PUBLISHED or e.startswith("sensor.smartbox_")


def indoor_sensors() -> list:
    out = []
    cfg = sensor_config()
    for i, s in enumerate(cfg.get("indoor") or [], start=1):
        if isinstance(s, dict) and is_own_entity(s.get("entity")):
            if s["entity"] not in _self_skip_warned:
                print(f"⚠️ Givaren {s.get('label') or s['entity']} är EnergyWizards egen publicerade sensor - räknas inte in i "
                      "innetemperaturen. Välj bort den bland rumsgivarna.")
                _self_skip_warned.add(s["entity"])
            continue
        if isinstance(s, dict) and s.get("entity") and is_outdoor_sensor(s.get("entity"), s.get("label"), cfg.get("outdoor")):
            if s["entity"] not in _outdoor_skip_warned:
                print(f"⚠️ Givaren {s.get('label') or s['entity']} är vald som innegivare men är en utegivare - räknas inte in i innetemperaturen.")
                _outdoor_skip_warned.add(s["entity"])
            continue
        if isinstance(s, dict) and (s.get("entity") or s.get("esphome_ip")):
            out.append({**s, "key": str(s.get("key") or f"in_{i}"), "label": s.get("label") or s.get("entity") or f"Givare {i}"})
    return out


def indoor_sensor_labels() -> dict:
    return {s["key"]: s["label"] for s in indoor_sensors()}


# Bilarnas entiteter kommer ur installationen (evs[].entities, drivers/car_generic.py) - inga inbyggda namn.

# --- TIBBER (Ersätter Shelly för husets total) ---
# Elmätaren (nätimport/-export, fasströmmar) kommer från husets config (power_meter: i
# house_config.yaml), satt av main.py via configure_power_meter() vid start. Förut hårdkodad
# till ett enda hus Tibber Pulse - då fick alla andra installationer ingen nätmätning alls.
POWER_METER = {}


def configure_power_meter(entities: dict | None):
    """Sätter elmätarens entiteter. Stödda former (se read_power_meter):
      per fas:   voltage_l1..3 + current_l1..3            (t.ex. Tibber Pulse)
      netto:     power_w (+ power_w_invert: true om export är positiv) (+ current_l1..3 valfritt)
      import/export: import_w + export_w                   (t.ex. P1/HAN-mätare) (+ current_l1..3 valfritt)
      active phase power: import_l{1,2,3}_w + export_l{1,2,3}_w (W/kW; optional with totals)
    Valfritt: hour_kwh = förbrukad energi hittills denna timme (effektvakten)."""
    POWER_METER.clear()
    POWER_METER.update({k: v for k, v in (entities or {}).items() if v not in (None, "")})


# Valfri andra mätpunkt: LASTSIDAN (det som en säkring/brytare bakom batteri/sol-anslutningen ser).
# Bara fasströmmar behövs (current_l1..3, alltid positiva) - nettoeffekt och export hanteras av power_meter.
LOAD_METER = {}


def configure_load_meter(entities: dict | None):
    LOAD_METER.clear()
    LOAD_METER.update({k: v for k, v in (entities or {}).items() if v not in (None, "")})


def read_load_meter():
    """{'l1_a','l2_a','l3_a'} från lastsidans mätpunkt, None om den inte är konfigurerad eller inte svarar."""
    e = LOAD_METER
    if not all(e.get(k) for k in ("current_l1", "current_l2", "current_l3")):
        return None
    cur = [_get_numeric_state(e[k]) for k in ("current_l1", "current_l2", "current_l3")]
    if None in cur:
        return None
    return {"l1_a": cur[0], "l2_a": cur[1], "l3_a": cur[2]}

# --- SOLAREDGE / GECKO ---
# Entiteterna kommer ur installationen (solar.entities / spa.entities i house_config.yaml) - inga husspecifika
# namn här. För SolarEdge finns bara de officiella integrationernas egna standardnamn som reserv.
from drivers.ha_solaredge import DEFAULT_PV as SOLAREDGE_DEFAULT_PV, DEFAULT_TODAY as SOLAREDGE_DEFAULT_TODAY, \
    DEFAULT_STATUS as SOLAREDGE_DEFAULT_STATUS, DEFAULT_LIMIT as SOLAREDGE_DEFAULT_LIMIT   # steg 5b: bor hos drivrutinen


def _as_list(v):
    if v in (None, ""):
        return []
    return [x for x in (v if isinstance(v, (list, tuple)) else [v]) if x]


def normalize_ha_url(url: str) -> str:
    """'192.168.1.10' -> 'http://192.168.1.10:8123'. En adress med http:// eller https://
    lämnas som den är (den kan ligga bakom en proxy på port 443)."""
    url = (url or "").strip().rstrip("/")
    if url.endswith("/api"):
        url = url[:-4].rstrip("/")
    if "://" in url:
        return url
    host = url.split("/", 1)[0]
    if ":" not in host.rsplit("]", 1)[-1]:
        url = host + ":8123" + url[len(host):]
    return "http://" + url


def reconfigure():
    """Sätter _BASE/_HEADERS/_VERIFY. Ordning: Supervisor (HA-tillägget), miljövariablerna
    HA_URL/HA_IP + HA_TOKEN, och sist det som sparats i webbens startguide (ew_settings).
    Anropas vid import och igen när guiden sparat en ny anslutning."""
    global _BASE, _HEADERS, _VERIFY, HA_URL, HA_TOKEN
    if SUPERVISOR_TOKEN:
        _BASE = "http://supervisor/core/api"
        _HEADERS = {"Authorization": f"Bearer {SUPERVISOR_TOKEN}", "Content-Type": "application/json"}
        _VERIFY = True   # intern anslutning inom Supervisorns eget nät, ingen TLS-fråga
        return
    url, token = _ENV_URL, _ENV_TOKEN
    if not (url or HA_IP):
        import ew_settings
        st = ew_settings.load()
        url, token = (st.get("ha_url") or "").strip(), (st.get("ha_token") or "").strip()
    HA_URL, HA_TOKEN = url, token
    _BASE = f"{normalize_ha_url(url)}/api" if url else f"https://{HA_IP}:{HA_PORT}/api"
    _HEADERS = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    _VERIFY = False  # oförändrat: självsignerat/okänt cert mot HA_IP, som idag


def configured() -> bool:
    """Finns det någon väg till Home Assistant alls?"""
    return bool(SUPERVISOR_TOKEN or ((HA_URL or HA_IP) and HA_TOKEN))


def test_connection(url: str, token: str, timeout: float = 10.0):
    """(ok, meddelande) för en adress + token, innan den sparas. Rör inte den aktiva anslutningen."""
    base = normalize_ha_url(url)
    try:
        r = requests.get(f"{base}/api/", headers={"Authorization": f"Bearer {token.strip()}"},
                         timeout=timeout, verify=False)
    except requests.exceptions.SSLError:
        return False, f"Kunde inte prata krypterat med {base}. Prova http:// i stället."
    except requests.exceptions.RequestException:
        return False, f"Fick inget svar från {base}. Stämmer adressen, och når servern Home Assistant?"
    if r.status_code == 200:
        return True, f"Kontakt med Home Assistant på {base}."
    if r.status_code in (401, 403):
        return False, "Home Assistant svarade men tog inte emot token. Skapa en ny och klistra in den igen."
    return False, f"Oväntat svar från {base} ({r.status_code}). Är det rätt adress till Home Assistant?"


_ENV_URL, _ENV_TOKEN = HA_URL, HA_TOKEN
reconfigure()

_states_cache = {}

def publish_states(entities: dict):
    """Publicerar smartbox-värden som sensorer i HA (POST /api/states/<entity_id>) så de kan visas i dashboarden.
    entities = {entity_id: (state, attributes)}. Sensorerna är icke-persistenta (finns tills HA startas om) och
    uppdateras varje minut. Körs i egen tråd; avbryter vid första fel så att en nedstängd HA aldrig hindrar något."""
    _PUBLISHED.update(entities.keys())
    for entity_id, (state, attrs) in entities.items():
        if state is None:
            continue
        try:
            r = requests.post(f"{_BASE}/states/{entity_id}", headers=_HEADERS,
                              json={"state": state, "attributes": attrs}, timeout=3, verify=_VERIFY)
            r.raise_for_status()
        except Exception:
            return

last_update_ok = True   # Senaste update_states() lyckades? (används av health.LinkWatch)

_ha_fail = {"n": 0}


def update_states():
    """Hämtar ALLA states från Home Assistant API:et i en enda effektiv request."""
    global _states_cache, last_update_ok
    try:
        r = requests.get(f"{_BASE}/states", headers=_HEADERS, timeout=5, verify=_VERIFY)
        r.raise_for_status()
        _states_cache = {s["entity_id"]: s for s in r.json()}
        last_update_ok = True
        _ha_fail["n"] = 0
        return True
    except Exception as e:
        last_update_ok = False
        _states_cache.clear()
        _ha_fail["n"] += 1
        _ha_fail["at"] = time.time()
        net = isinstance(e, (requests.RequestException, OSError))   # timeout, nekad anslutning, SSL-handskakning ...
        status = getattr(getattr(e, "response", None), "status_code", None)
        if status == 401:                                      # fel eller utgången token: kräver att användaren gör något
            if _ha_fail["n"] in (1, 30) or _ha_fail["n"] % 360 == 0:
                print(f"❌ HA: token godkänns inte (401) - skapa en ny långlivad token i Home Assistant och lägg in den i EnergyWizard")
            return False
        # En enstaka timeout (HA upptagen en stund) är en varning. HTTP-svar som inte är en omstart
        # blir ett fel när de upprepas. Avbrott utan HTTP-svar (ConnectionError, timeout) förblir
        # varning även efter många försök: det är drift, och ❌ blir ett GitHub-ärende (#228).
        # Nätverksfel skrivs utan förlopp - bara oväntade fel får hela tracebacken.
        n = _ha_fail["n"]
        # 502/503/504 = Supervisor-proxyn svarar innan HA är uppe. Även långa avbrott är driftvarningar.
        dropped = net and not isinstance(e, requests.HTTPError)
        restart = status in (502, 503, 504) or dropped
        if restart and n < 30:
            if n in (1, 10, 20):
                print(f"⚠️ HA svarar inte än ({type(e).__name__}{' ' + str(status) if status else ''}) - väntar, troligen en omstart")
            return False
        if restart:
            if n % 10 == 0:
                print(f"⚠️ HA svarar inte ({n} i rad, {type(e).__name__}) - fortsätter försöka")
            return False
        if n < 3 and net:
            print(f"⚠️ HA svarade inte ({type(e).__name__}) - försöker igen")
        elif n == 3 or n % 10 == 0 or not net:
            print(f"❌ HA: Fel vid update_states ({n} i rad): {type(e).__name__}: {str(e)[:160]}")
            if not net:
                traceback.print_exc()
        return False



def _fail(text: str, err) -> None:
    """Fångat undantag i en skrivfunktion: nätverksfel mot HA (nere, omstart, ogiltig adress, timeout) är drift, inte ett
    programfel - ⚠️ så att de inte blir GitHub-ärenden (#588-#595: ConnectionError och InvalidURL i toggle_spa_plug,
    set_gecko_*, set_solaredge_limit). Övriga fel förblir ❌."""
    try:
        net = isinstance(err, (requests.ConnectionError, requests.Timeout, requests.exceptions.InvalidURL,
                               requests.exceptions.InvalidSchema, requests.exceptions.MissingSchema,
                               requests.exceptions.ChunkedEncodingError, ConnectionError, TimeoutError))   # HTTPError (401/500) är OSError, men inte drift
    except Exception:
        net = False
    print(f"{'⚠️' if net else '❌'} {text}")


report_failure = _fail   # steg 5b: drivrutinerna rapporterar fel på samma sätt (⚠️ för drift, ❌ för programfel)


def post_service(service_path: str, payload: dict, timeout: float = 5):
    """POST /services/<domän>/<tjänst> (t.ex. "switch/turn_on") mot HA. Ger svaret, och kastar vid fel (raise_for_status) så att
    anroparen avgör hur felet rapporteras. Går genom skuggläget som alla skrivningar. Generiskt: märkeskunskapen bor i drivrutinerna."""
    r = requests.post(f"{_BASE}/services/{service_path}", headers=_HEADERS, json=payload, timeout=timeout, verify=_VERIFY)
    r.raise_for_status()
    return r


def _get_raw_state(entity_id):
    """Hämtar rå-strängen från en sensor utan att konvertera den till siffror."""
    # Tom cache: hämta - men inte om HA nyss inte svarade. Annars försöker varje enskild avläsning igen och väntar ut sin
    # timeout när HA är nere (2026-11-06: dussintals försök i minuten under en omstart av HA).
    if not _states_cache and time.time() - _ha_fail.get("at", 0) > 30:
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
        v = float(raw)
    except ValueError:
        # Kan vara en status-text (t.ex. 'charging'), skippa varning.
        return None
    # "inf"/"nan" (en mall i HA som delar med noll, #171: laddnivå "inf %") är inget mätvärde
    return v if math.isfinite(v) else None

def room_temps():
    """Rummen = de valda innegivarna (Inställningar -> Givare), live: [{'name', 'temp'}]. Inga fasta rum i koden."""
    out = []
    try:
        chosen = indoor_sensors()
        if chosen:
            update_states()
        for sn in chosen:
            v = _get_numeric_state(sn["entity"]) if sn.get("entity") else None
            if isinstance(v, (int, float)):
                out.append({"name": sn.get("label") or sn["entity"], "temp": round(float(v) + float(sn.get("offset") or 0), 1)})
    except Exception as e:
        print(f"⚠️ Rumstemperaturerna: {e}", flush=True)
    return out


def get_power_w(entity_id):
    """Effekt i watt oavsett vilken enhet sensorn har (W, kW, MW enligt unit_of_measurement). En batteri- eller
    mätarsensor i kW lästes förut som watt (#139)."""
    v = _get_numeric_state(entity_id)
    if v is None:
        return None
    unit = str(((_states_cache.get(entity_id) or {}).get("attributes") or {}).get("unit_of_measurement") or "").strip()
    return v * {"kW": 1000.0, "MW": 1_000_000.0, "mW": 0.001}.get(unit, 1.0)


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
        v = float(raw)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None

def read_temperatures():
    """Råvärden per vald innegivare (nyckel = givarens key) + "ute". Korrigeringen (offset) läggs på i main.py,
    så att loggen behåller givarens eget värde. ESPHome-adressen används när entiteten saknar värde."""
    out = {}
    for s in indoor_sensors():
        v = _get_numeric_state(s["entity"]) if s.get("entity") else None
        if v is None and s.get("esphome_ip"):
            v = read_esphome_temp(s["esphome_ip"])
        out[s["key"]] = v
    ute = sensor_config().get("outdoor")
    out["ute"] = _get_numeric_state(ute) if ute else None
    return out

def read_humidities():
    """Luftfuktighet (%) per innegivare som har en fuktentitet, samma nycklar som read_temperatures."""
    return {s["key"]: _get_numeric_state(s["humidity"]) for s in indoor_sensors() if s.get("humidity") and not is_own_entity(s["humidity"])}



def _read_easee_charger(entities: dict, charger_id: str | None = None):
    """Vidarekoppling: koden bor i drivers/ha_easee.py (steg 5b)."""
    from drivers import ha_easee
    return ha_easee.read_charger(entities, charger_id)





# Prefixet är fritt: äldre Tibber-integrationer döpte entiteterna "tibber_pulse_<hem>_...", nyare efter hemmets namn
# ("sensor.hemma_power"). Med bara "tibber_pulse_" hittades spänning/ström men inte köp/sälj hos de nyare, och då blev
# försäljning köp (U x I saknar tecken, #171: "Köper 6,2 kW" när huset sålde 6 kW från batteriet).
_PULSE_PATTERNS = {
    "voltage": re.compile(r"^sensor\.(.+?)_(?:spanning_fas|voltage_phase|voltage_l)([123])$"),
    "current": re.compile(r"^sensor\.(.+?)_(?:strom_fas|current_phase|current_l)([123])$"),
    "hour": re.compile(r"^sensor\.(.+?)_(?:ackumulerad_forbrukning_under_aktuell_timme|accumulated_consumption_current_hour)$"),
    # Verklig köp- och säljeffekt (W). Pulsens fasström saknar tecken, så U x I kan inte se export (issue #114).
    "import": re.compile(r"^sensor\.(.+?)_(?:power|effekt)$"),
    "export": re.compile(r"^sensor\.(.+?)_(?:power_production|effekt_produktion|produktionseffekt|production_power)$"),
}


def detect_tibber_pulse(entity_ids) -> dict:
    """Hittar en Tibber Pulse bland HA:s entiteter efter namnmönster (svenska eller engelska namn).
    Kräver spänning + ström på alla tre faser från SAMMA Pulse. {} om ingen hittas."""
    found = {}
    for eid in entity_ids:
        for kind, rx in _PULSE_PATTERNS.items():
            m = rx.match(eid)
            if m:
                key = {"hour": "hour_kwh", "import": "import_w", "export": "export_w"}.get(kind) or f"{kind}_l{m.group(2)}"
                found.setdefault(m.group(1), {})[key] = eid
    for prefix in sorted(found):
        e = found[prefix]
        if all(f"{k}_l{n}" in e for k in ("voltage", "current") for n in (1, 2, 3)):
            if not ("import_w" in e and "export_w" in e):       # köp utan sälj räcker inte - då U x I som förut
                e.pop("import_w", None)
                e.pop("export_w", None)
            return e
    # #171: många Pulse-installationer har bara köp- och säljeffekt (ingen spänning/ström per fas) - det räcker
    for prefix in sorted(found):
        e = found[prefix]
        if "import_w" in e and "export_w" in e:
            return {k: v for k, v in e.items() if k in ("import_w", "export_w", "hour_kwh")}
    return {}


def _setting(key):
    try:
        import ew_settings
        return bool(ew_settings.get(key, False))
    except Exception:
        return False


def read_power_meter():
    """{'net_power_w': W (+ köper, - säljer), 'l1_a'/'l2_a'/'l3_a': A eller None} - None om mätaren
    inte är konfigurerad eller inte svarar. Utan power_meter: i configen letas en Tibber Pulse
    upp automatiskt (en gång), så befintliga installationer fortsätter fungera.
    Configured active phase pairs also return signed l1_w/l2_w/l3_w (None if unavailable)."""
    e = POWER_METER
    if e.get('frame_timestamp'):
        import meter_frame
        return meter_frame.read(e, _states_cache, time.time())
    if not e:
        if not _states_cache:
            update_states()
        auto = detect_tibber_pulse(_states_cache.keys())
        if not auto:
            return None
        POWER_METER.update(auto)
        how = (f"köp {auto['import_w']}, sälj {auto['export_w']}" if auto.get("import_w") else
               "spänning × ström - kan inte se försäljning; välj elmätarens köp- och säljeffekt i installationen")
        print(f"🔌 Elmätare: ingen power_meter i house_config.yaml - hittade en Tibber Pulse automatiskt ({how}).")
        e = POWER_METER
    try:
        cur = [_get_numeric_state(e[k]) if e.get(k) else None for k in ("current_l1", "current_l2", "current_l3")]
        phase_power = {}
        for ph in (1, 2, 3):
            imp_key, exp_key = f"import_l{ph}_w", f"export_l{ph}_w"
            if e.get(imp_key) or e.get(exp_key):
                imp = get_power_w(e[imp_key]) if e.get(imp_key) else None
                exp = get_power_w(e[exp_key]) if e.get(exp_key) else None
                # Missing/unavailable measurements must not become zero power.
                phase_power[f"l{ph}_w"] = imp - exp if imp is not None and exp is not None else None
        if e.get("import_w") and e.get("export_w"):
            # Verklig köp- och säljeffekt går före U x I: fasströmmen (t.ex. Tibber Pulse) saknar ofta tecken, så
            # export syns inte, och U x I är skenbar effekt (issue #114).
            imp, exp = get_power_w(e["import_w"]), get_power_w(e["export_w"])
            if imp is None and exp is None:
                return None
            net = (imp or 0.0) - (exp or 0.0)
        elif not e.get("power_w") and not e.get("import_w") and phase_power:
            if len(phase_power) != 3 or any(v is None for v in phase_power.values()):
                return None
            net = sum(phase_power.values())
        elif all(e.get(k) for k in ("voltage_l1", "voltage_l2", "voltage_l3", "current_l1", "current_l2", "current_l3")):
            volt = [_get_numeric_state(e[k]) for k in ("voltage_l1", "voltage_l2", "voltage_l3")]
            if None in volt or None in cur:
                return None
            net = sum(v * i for v, i in zip(volt, cur))          # P = U × I, negativ ström = export
        elif e.get("power_w"):
            net = get_power_w(e["power_w"])
            if net is None:
                return None
            if str(e.get("power_w_invert", "")).lower() in ("1", "true", "yes", "ja"):
                net = -net
            elif "power_w_invert" not in e and _setting("grid_power_invert"):     # valet i webben (#171)
                net = -net
        elif e.get("import_w"):
            imp = get_power_w(e["import_w"])
            exp = get_power_w(e["export_w"]) if e.get("export_w") else 0.0
            if imp is None:
                return None
            net = imp - (exp or 0.0)
        else:
            return None
        return {"net_power_w": net, "l1_a": cur[0], "l2_a": cur[1], "l3_a": cur[2], **phase_power}
    except Exception as ex:
        _fail(f"Fel vid läsning av elmätaren: {ex}", ex)
        return None


def read_hour_kwh():
    """Förbrukad energi denna timme från mätarens egen sensor, None om den inte är konfigurerad."""
    k = POWER_METER.get("hour_kwh")
    return _get_numeric_state(k) if k else None


read_tibber_data = read_power_meter      # gammalt namn, kvar för bakåtkompatibilitet


def read_solaredge(entities=None):
    """Vidarekoppling: koden bor i drivers/ha_solaredge.py (steg 5b)."""
    from drivers import ha_solaredge
    return ha_solaredge.read(entities)

def read_gecko(entities=None):
    """Vidarekoppling: koden bor i drivers/ha_gecko.py (steg 5b)."""
    from drivers import ha_gecko
    return ha_gecko.read(entities)

def all_entity_names():
    """{entity_id: friendly_name} för alla entiteter i HA:s tillståndscache (hämtar den om den är tom)."""
    if not _states_cache:
        update_states()
    return {eid: str((s.get("attributes") or {}).get("friendly_name") or "") for eid, s in _states_cache.items()}


def read_spa_power(entities=None):
    """Vidarekoppling: koden bor i drivers/ha_gecko.py (steg 5b)."""
    from drivers import ha_gecko
    return ha_gecko.read_power(entities)

def read_spa_activities(entities=None):
    """Vidarekoppling: koden bor i drivers/ha_gecko.py (steg 5b)."""
    from drivers import ha_gecko
    return ha_gecko.read_activities(entities)

def set_gecko_economy(enable: bool, entity: str | None = None):
    """Vidarekoppling: koden bor i drivers/ha_gecko.py (steg 5b)."""
    from drivers import ha_gecko
    return ha_gecko.set_economy(enable, entity)

def set_gecko_target(temp: float, entity: str | None = None):
    """Vidarekoppling: koden bor i drivers/ha_gecko.py (steg 5b)."""
    from drivers import ha_gecko
    return ha_gecko.set_target(temp, entity)

def set_ev_dynamic_limit(charger_id: str, ampere: int, reason: str = None):
    """Vidarekoppling: koden bor i drivers/ha_easee.py (steg 5b)."""
    from drivers import ha_easee
    return ha_easee.set_dynamic_limit(charger_id, ampere, reason)

def set_easee_phases(charger_id: str, phases: int):
    """Vidarekoppling: koden bor i drivers/ha_easee.py (steg 5b)."""
    from drivers import ha_easee
    return ha_easee.set_phases(charger_id, phases)

def turn_on_charger(charger_id: str, entity_id: str | None = None):
    """Vidarekoppling: koden bor i drivers/ha_easee.py (steg 5b)."""
    from drivers import ha_easee
    return ha_easee.turn_on(charger_id, entity_id)

def turn_off_charger(charger_id: str, entity_id: str | None = None):
    """Vidarekoppling: koden bor i drivers/ha_easee.py (steg 5b)."""
    from drivers import ha_easee
    return ha_easee.turn_off(charger_id, entity_id)

def get_solaredge_limit(entity: str | None = None):
    """Vidarekoppling: koden bor i drivers/ha_solaredge.py (steg 5b)."""
    from drivers import ha_solaredge
    return ha_solaredge.get_limit(entity)

def set_solaredge_limit(limit: int, entity: str | None = None):
    """Vidarekoppling: koden bor i drivers/ha_solaredge.py (steg 5b)."""
    from drivers import ha_solaredge
    return ha_solaredge.set_limit(limit, entity)

def press_button(entity_id: str, timeout: float = 5):
    """Trycker på en knapp i HA (t.ex. button.tesla_model_y_wake_up). Returnerar True om anropet gick igenom."""
    try:
        r = requests.post(f"{_BASE}/services/button/press", headers=_HEADERS,
                          json={"entity_id": entity_id}, timeout=timeout, verify=_VERIFY)
        r.raise_for_status()
        return True
    except requests.exceptions.ReadTimeout:
        # Knappen är tryckt; HA svarar först när tillverkarens moln svarat (Nissan tar ofta 10-30 s). Normalt - ingen
        # varning (2026-11-06: en ⚠️ var 30:e minut för Leafens uppdateringsknapp).
        print(f"ℹ️ {entity_id}: tryckt, svaret från bilens moln dröjer")
        return False
    except Exception as e:
        _fail(f"Kunde inte trycka på {entity_id}: {e}", e)
        return False

from drivers.ha_car import CLIMATE_TIMEOUT_S as CAR_CLIMATE_TIMEOUT_S


def refresh_entity(entity_id: str, button: str | None = None) -> bool:
    """Vidarekoppling: koden bor i drivers/ha_car.py (steg 5b)."""
    from drivers import ha_car
    return ha_car.refresh_entity(entity_id, button)


def _climate_now(entity_id: str):
    """Entitetens läge direkt från HA (inte ur cachen)."""
    try:
        r = requests.get(f"{_BASE}/states/{entity_id}", headers=_HEADERS, verify=_VERIFY, timeout=10)
        r.raise_for_status()
        return r.json().get("state")
    except Exception:
        return None


def set_car_climate(entity_id: str, hvac_mode: str, temperature: float = None):
    """Vidarekoppling: koden bor i drivers/ha_car.py (steg 5b)."""
    from drivers import ha_car
    return ha_car.set_climate(entity_id, hvac_mode, temperature)


def turn_on_lights(entity_ids: list):
    """Tänder en lista med lampor i Home Assistant."""
    if not entity_ids: return False
    try:
        r = requests.post(
            f"{_BASE}/services/light/turn_on",
            headers=_HEADERS,
            json={"entity_id": entity_ids},
            timeout=5,
            verify=_VERIFY,
        )
        r.raise_for_status()
        print(f"💡 Tände lampor: {', '.join(entity_ids)}")
        return True
    except Exception as e:
        _fail(f"Fel vid tändning av lampor i HA: {e}", e)
        return False

def toggle_spa_plug(turn_on: bool, entity: str | None = None):
    """Vidarekoppling: koden bor i drivers/ha_gecko.py (steg 5b)."""
    from drivers import ha_gecko
    return ha_gecko.toggle_plug(turn_on, entity)


def set_climate_temperature(entity_id: str, target_c: float) -> bool:
    """Genuint generisk climate.set_temperature på en valfri entitet - samma
    HA-tjänst set_car_climate() redan använder, men utan bilspecifik loggning/
    hvac_mode-växling. Återanvänds av generiska drivrutiner (t.ex. värmepump)."""
    try:
        r = requests.post(
            f"{_BASE}/services/climate/set_temperature",
            headers=_HEADERS,
            json={"entity_id": entity_id, "temperature": target_c},
            timeout=10,
            verify=_VERIFY,
        )
        r.raise_for_status()
        return True
    except Exception as e:
        _fail(f"Fel vid climate.set_temperature på {entity_id}: {e}", e)
        return False


def set_switch(entity_id: str, turn_on: bool) -> bool:
    """Genuint generisk switch.turn_on/turn_off på en valfri entitet - samma HA-anrop
    som toggle_spa_plug/turn_on_charger redan gör var för sig mot
    hårdkodade entiteter, men återanvändbar av GENERISKA drivrutiner (laddare m.fl.)
    som får sin entitet från husets config istället."""
    service = "turn_on" if turn_on else "turn_off"
    try:
        r = requests.post(
            f"{_BASE}/services/switch/{service}",
            headers=_HEADERS,
            json={"entity_id": entity_id},
            timeout=5,
            verify=_VERIFY,
        )
        r.raise_for_status()
        return True
    except Exception as e:
        _fail(f"Fel vid switch.{service} på {entity_id}: {e}", e)
        return False


def get_attribute(entity_id: str, attribute: str):
    """Ett attribut från senast hämtade states (t.ex. en number-entitets 'max'). None om det saknas."""
    if not entity_id:
        return None
    if not _states_cache:
        update_states()
    s = _states_cache.get(entity_id)
    return (s.get("attributes") or {}).get(attribute) if s else None


def call_service(domain: str, service: str, data: dict) -> bool:
    """Genuint generiskt tjänsteanrop (POST /api/services/<domain>/<service>) för drivrutiner som
    styrs via en integrations egna tjänster istället för en entitet - t.ex. huawei_solar:s
    exportgräns eller HA:s inbyggda modbus.write_register."""
    try:
        r = requests.post(
            f"{_BASE}/services/{domain}/{service}",
            headers=_HEADERS,
            json=data,
            timeout=10,
            verify=_VERIFY,
        )
        r.raise_for_status()
        return True
    except Exception as e:
        _fail(f"Fel vid {domain}.{service}: {e}", e)
        return False


def _already(entity_id: str, want) -> bool:
    """Läs före skriv (#194): står entiteten redan på värdet skrivs det inte igen. Många växelriktare och batterier
    sparar number/select-värden i flashminne som tål ett begränsat antal skrivningar."""
    try:
        r = requests.get(f"{_BASE}/states/{entity_id}", headers=_HEADERS, timeout=5, verify=_VERIFY)
        if r.status_code != 200:
            return False
        cur = r.json().get("state")
        if isinstance(want, (int, float)) and not isinstance(want, bool):
            c = float(cur)
            return abs(c - float(want)) <= max(0.01, abs(float(want)) * 0.005)
        return str(cur) == str(want)
    except Exception:
        return False


_SERVICE_TIMEOUT_S = 20      # skrivningar mot molnintegrationer (Tesla, myUplink) kan ta över 10 s (#568)


def _landed(entity_id: str, payload: dict) -> bool:
    """Står entiteten nu på det vi bad om? (efter en read-timeout på själva skrivningen)"""
    try:
        time.sleep(3)
        if "value" in payload:
            return _already(entity_id, float(payload["value"]))
        if "option" in payload:
            return _already(entity_id, payload["option"])
    except (TypeError, ValueError):
        pass
    return False


def _call_service(entity_id: str, service: str, payload: dict) -> bool:
    """POST /services/<service> med en omprövning vid transient drift: read-timeout,
    avbrott eller 502/503/504 från Supervisor-proxyn medan HA är upptagen eller startar om.
    En enstaka sådan avbrott är drift (⚠️) och förtjänar en omprövning, inte ett ❌ som
    tappad styrsignal (#486: "skriv fel myUplink" - en enstaka read-timeout mot supervisor
    tappade värmepumpens kurvförskjutning number.offset_47011). timeout=10 som övriga
    skrivningar i den här filen (reads använder 5). Riktiga fel (401/404/...) är kvar
    som ❌ utan omprövning."""
    for attempt in (1, 2):
        try:
            r = requests.post(
                f"{_BASE}/services/{service}",
                headers=_HEADERS,
                json=payload,
                timeout=_SERVICE_TIMEOUT_S,
                verify=_VERIFY,
            )
            r.raise_for_status()
            return True
        except requests.HTTPError as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status in (502, 503, 504) and attempt == 1:
                print(f"⚠️ {service} på {entity_id}: HA svarade inte än (HTTP {status}) - försöker igen")
                time.sleep(2)
                continue
            _fail(f"Fel vid {service} på {entity_id}: {e}", e)
            return False
        except requests.RequestException as e:
            if attempt == 1:
                print(f"⚠️ {service} på {entity_id} svarade inte ({type(e).__name__}) - försöker igen")
                time.sleep(2)
                continue
            if isinstance(e, (requests.ReadTimeout, requests.ConnectionError)) and _landed(entity_id, payload):
                # Integrationer som ringer ett moln (Tesla, myUplink) svarar ibland efter timeout fast kommandot gick
                # igenom (#568): står entiteten redan på värdet var det ingen tappad styrsignal.
                print(f"⚠️ {service} på {entity_id}: svaret dröjde men värdet gick igenom")
                return True
            _fail(f"Fel vid {service} på {entity_id}: {e}", e)
            return False
        except Exception as e:
            _fail(f"Fel vid {service} på {entity_id}: {e}", e)
            return False
    return False


def set_number(entity_id: str, value: float, force: bool = False) -> bool:
    """Genuint generisk number.set_value på en valfri entitet - samma mönster som
    set_solaredge_limit redan gör mot en hårdkodad entitet, återanvändbar av generiska
    drivrutiner (laddström, exportgräns m.fl.). force=True skriver även om värdet redan stämmer (håll-vid-liv)."""
    if not force and _already(entity_id, value):
        return True
    return _call_service(entity_id, "number/set_value",
                         {"entity_id": entity_id, "value": str(value)})


def set_select(entity_id: str, option: str, force: bool = False) -> bool:
    """Genuint generisk select.select_option på en valfri entitet - de flesta
    batteriintegrationers lägesväljare (ladda/ladda ur/auto/vila) är en select-entitet,
    inte number/switch. Återanvänds av generiska drivrutiner. Läs före skriv som set_number (#194)."""
    if not force and _already(entity_id, option):
        return True
    return _call_service(entity_id, "select/select_option",
                         {"entity_id": entity_id, "option": option})




def read_esphome_temp(ip):
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

# Nordpool-integrationens egna schema-defaults (config_flow.py:async_step_user) för de fält
# som INTE går att läsa tillbaka på något sätt (varken via REST-config-entries, som bara ger
# metadata - inte entry.data - eller via sensorns publika attribut). Bekräftat: HA:s
# GET /api/config/config_entries/entry exponerar medvetet aldrig entry.data (integrationer
# kan ha tokens där), och nordpool saknar diagnostics.py som annars brukar erbjuda en
# säker väg till den sortens config-innehåll.
_NORDPOOL_DEFAULT_PRECISION = 3
_NORDPOOL_DEFAULT_LOW_PRICE_CUTOFF = 1.0
_NORDPOOL_DEFAULT_ADDITIONAL_COSTS = "{{0.0|float}}"
_NORDPOOL_DEFAULT_PRICE_TYPE = "kWh"


def _nordpool_entry_id() -> str | None:
    """Live-läsning av entry_id mot HA - vi speglar aldrig det här i vår egen databas."""
    try:
        r = requests.get(f"{_BASE}/config/config_entries/entry", params={"domain": "nordpool"},
                          headers=_HEADERS, timeout=5, verify=_VERIFY)
        r.raise_for_status()
        entries = r.json()
        if not entries:
            print("❌ Nordpool-integrationen hittades inte i Home Assistant.")
            return None
        return entries[0].get("entry_id")
    except Exception as e:
        print(f"❌ Kunde inte läsa nordpool-integrationens config: {e}")
        return None


def get_nordpool_config() -> dict:
    """Bästa möjliga (INTE garanterat kompletta) bild av nordpool-integrationens
    inställningar - entry_id + region/currency/price_in_cents rekonstruerat från
    sensor.nordpool:s publika attribut. VAT:s NUVARANDE värde går inte att läsa tillbaka
    på något sätt (varken config entry eller sensorattribut avslöjar det), så fältet
    saknas helt i svaret - anroparen måste visa "okänt", aldrig gissa ett värde."""
    entry_id = _nordpool_entry_id()
    if not entry_id:
        return {}
    try:
        r = requests.get(f"{_BASE}/states/sensor.nordpool", headers=_HEADERS, timeout=5, verify=_VERIFY)
        r.raise_for_status()
        attrs = r.json().get("attributes", {})
    except Exception as e:
        print(f"❌ Kunde inte läsa sensor.nordpool för att rekonstruera konfigurationen: {e}")
        return {}
    return {
        "entry_id": entry_id,
        "region": attrs.get("region"),
        "currency": attrs.get("currency"),
        "price_in_cents": bool(attrs.get("price_in_cents", False)),
        "additional_costs_current_hour": attrs.get("additional_costs_current_hour"),
    }


def set_nordpool_vat(enabled: bool) -> bool:
    """Växlar momsinställningen i HA:s RIKTIGA nordpool-integration, istället för att
    EnergyWizard underhåller egen på/av-momslogik (se smartbox/gpm.py:s IMPORT_PROFIT_SPOT
    för exemplet på just den sortens kod vi vill slippa duplicera).

    Integrationen saknar OptionsFlow/reconfigure (verifierat i dess egen config_flow.py) -
    enda vägen att ändra ett redan satt fält är att radera config entry och skapa en ny via
    HA:s riktiga config-flow-REST-API. Sätter inget unique_id, så ny MÅSTE skapas efter att
    gamla raderats, annars blir det sensor.nordpool_2 istället för sensor.nordpool och allt
    som redan pekar på det namnet (i och utanför EnergyWizard) går sönder.

    BEST EFFORT (inte en exakt spegling - se get_nordpool_config): region/currency/
    price_in_cents rekonstrueras från sensor.nordpool:s publika attribut, resten (precision/
    low_price_cutoff/additional_costs/price_type) sätts till integrationens egna schema-
    defaults. Om additional_costs_current_hour != 0 just nu finns sannolikt en anpassad
    avgiftsmall vi INTE kan bevara - vägrar växla då istället för att tyst nolla ut den.

    Ger en kort lucka (några sekunder) där sensor.nordpool inte finns - EnergyWizards egen
    prishämtning (nordpool.fetch_ha_nordpool_and_save) faller automatiskt tillbaka till
    elprisetjustnu.se om den hinner träffa luckan."""
    cfg = get_nordpool_config()
    entry_id = cfg.get("entry_id")
    if not entry_id or not cfg.get("region") or not cfg.get("currency"):
        print("❌ Kan inte ändra moms: nordpool-integrationens inställningar kunde inte rekonstrueras.")
        return False

    extra_costs = cfg.get("additional_costs_current_hour")
    if extra_costs not in (None, 0, 0.0):
        print(f"❌ Vägrar växla moms: additional_costs_current_hour = {extra_costs} (≠ 0) tyder på "
              f"en anpassad avgiftsmall som INTE kan bevaras vid återskapning - ändra manuellt i HA istället.")
        return False

    data = {
        "region": cfg["region"],
        "currency": cfg["currency"],
        "VAT": bool(enabled),
        "precision": _NORDPOOL_DEFAULT_PRECISION,
        "low_price_cutoff": _NORDPOOL_DEFAULT_LOW_PRICE_CUTOFF,
        "price_in_cents": cfg["price_in_cents"],
        "price_type": _NORDPOOL_DEFAULT_PRICE_TYPE,
        "additional_costs": _NORDPOOL_DEFAULT_ADDITIONAL_COSTS,
    }

    try:
        r_del = requests.delete(f"{_BASE}/config/config_entries/entry/{entry_id}",
                                 headers=_HEADERS, timeout=10, verify=_VERIFY)
        r_del.raise_for_status()
    except Exception as e:
        print(f"❌ Kunde inte radera nordpool-integrationens gamla config: {e}")
        return False

    try:
        r_flow = requests.post(f"{_BASE}/config/config_entries/flow", headers=_HEADERS,
                                json={"handler": "nordpool"}, timeout=10, verify=_VERIFY)
        r_flow.raise_for_status()
        flow_id = r_flow.json()["flow_id"]

        r_create = requests.post(f"{_BASE}/config/config_entries/flow/{flow_id}",
                                  headers=_HEADERS, json=data, timeout=10, verify=_VERIFY)
        r_create.raise_for_status()
    except Exception as e:
        # KRITISKT: gamla entryn är redan raderad och nya kunde inte skapas - sensor.nordpool
        # saknas nu helt tills någon lägger till integrationen manuellt i HA:s UI.
        print(f"❌ KRITISKT: Nordpool-integrationen raderad men kunde INTE skapas om "
              f"(VAT={enabled}): {e}. Lägg till den manuellt i Home Assistant igen.")
        return False

    for _ in range(6):
        try:
            r_check = requests.get(f"{_BASE}/states/sensor.nordpool", headers=_HEADERS,
                                    timeout=5, verify=_VERIFY)
            if r_check.status_code == 200:
                print(f"✅ Nordpool-integrationen återskapad med VAT={enabled}, sensor.nordpool svarar.")
                return True
        except Exception:
            pass
        time.sleep(2)

    print(f"⚠️ Nordpool-integrationen återskapad (VAT={enabled}) men sensor.nordpool "
          f"svarade inte inom 12 s - kan dyka upp strax, kolla HA manuellt.")
    return False


def get_own_base_url(retries: int = 0, wait_s: float = 5.0) -> str | None:
    """HA:s egen, redan korrekt ifyllda internal_url/external_url (Inställningar →
    System → Nätverk) - mer pålitligt än att gissa värdens LAN-IP inifrån en
    bridge-nätverkad container (containerns egen IP är inte samma sak som värdens,
    skulle bli missvisande). Föredrar internal_url (lokalt nät, samma plats de flesta
    kör EnergyWizard ifrån)."""
    # #434: vid start svarar HA ofta 502 eller inte alls medan den själv startar om. Det är inget fel i EnergyWizard:
    # försök igen (retries) och logga som varning - bara oväntade fel (t.ex. 401/404) blir ❌ och når telemetrin.
    import time as _t
    for attempt in range(retries + 1):
        try:
            r = requests.get(f"{_BASE}/config", headers=_HEADERS, timeout=5, verify=_VERIFY)
            r.raise_for_status()
            d = r.json()
            return d.get("internal_url") or d.get("external_url")
        except (requests.ConnectionError, requests.Timeout) as e:
            transient = e
        except requests.HTTPError as e:
            if e.response is None or e.response.status_code < 500:
                _fail(f"Kunde inte läsa HA:s egen internal_url/external_url: {e}", e)
                return None
            transient = e
        except Exception as e:
            _fail(f"Kunde inte läsa HA:s egen internal_url/external_url: {e}", e)
            return None
        if attempt < retries:
            _t.sleep(wait_s)
    print(f"⚠️ HA svarar inte än (läser internal_url/external_url): {type(transient).__name__}")
    return None


def send_persistent_notification(notification_id: str, title: str, message: str) -> bool:
    """Genuint generisk persistent_notification.create - ligger kvar synlig i HA:s eget
    notisfält tills användaren själv kryssar bort den (samma mekanism HACS och många
    tillägg använder för "kräver uppmärksamhet"). notification_id gör anropet
    idempotent - samma id uppdaterar/ersätter istället för att stapla dubbletter."""
    try:
        r = requests.post(
            f"{_BASE}/services/persistent_notification/create",
            headers=_HEADERS,
            json={"notification_id": notification_id, "title": title, "message": message},
            timeout=5,
            verify=_VERIFY,
        )
        r.raise_for_status()
        return True
    except Exception as e:
        _fail(f"Fel vid persistent_notification.create: {e}", e)
        return False


if __name__ == "__main__":
    print("Home Assistant Modul laddad.")

def read_ready_by(entity_id: str | None, now=None):
    """#200 (Jonas): "klar senast" för bilen ur en valfri HA-entitet. input_datetime med datum och tid
    ("2026-11-08 15:30:00"), bara tid ("15:30:00" -> nästa gång klockan blir det) eller en sensor med tidsstämpel
    (ISO, med tidszon). Returnerar en tidszonsmedveten tid i framtiden, annars None."""
    if not entity_id:
        return None
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    swe = ZoneInfo("Europe/Stockholm")
    now = now or datetime.now(swe)
    raw = str(_get_raw_state(entity_id) or "").strip()
    if raw in ("", "unknown", "unavailable", "None"):
        return None
    try:
        if len(raw) <= 8 and ":" in raw:                       # bara tid
            h, m = (int(x) for x in raw.split(":")[:2])
            dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
            return dt if dt > now else dt + timedelta(days=1)
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        dt = dt.replace(tzinfo=swe) if dt.tzinfo is None else dt.astimezone(swe)
        return dt if dt > now else None
    except (ValueError, TypeError):
        return None
