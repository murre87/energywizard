"""Entitetsväljare med auto-discovery - hittar kandidat-entiteter i husets Home
Assistant per EnergyWizard-kategori (bil/värmepump/sol/spa/laddare), så en ny
installation inte behöver leta upp entity-id:n för hand i house_config.yaml.

Mönstret (Jinja2-mall mot HA:s /api/template, kategori-regexer, "hittat men
ingen drivrutin"-flaggning) är portat från /home/emil/opt/Familjetavla/src/
server/src/discovery.ts - ett annat av Emils projekt som redan bevisat
fungera för det här ändamålet. Skiljer sig medvetet där EnergyWizard skiljer
sig: en egen laddar-heuristik (Familjetavla är bilcentrerad, har ingen), och
resultatet används för att GENERERA en nedladdningsbar house_config.yaml,
inte för att skriva direkt till en levande config (se husets house_config.yaml
är read-only-monterad i produktion, kräver en omstart - se planen).
"""
from __future__ import annotations

import os
import re

import requests

import homeassistant
from logger import get_db
from house_config import (
    CAR_DRIVER_REGISTRY, CHARGER_DRIVER_REGISTRY, HEAT_PUMP_DRIVER_REGISTRY,
    SOLAR_DRIVER_REGISTRY, SPA_DRIVER_REGISTRY,
)
# BATTERY_DRIVER_REGISTRY importeras medvetet INTE - ingen märkesspecifik batteri-
# drivrutin finns eller planeras (se drivers/battery.py), så upptäckta batterier
# föreslår alltid "generic" rakt av, aldrig en driver_known-koll mot registret.

# --- Kategori-regexer, portade från Familjetavlas discovery.ts ---
# The official HA integration reports "Škoda Auto"; accept both spellings without a tracker (#225).
CAR_MAKERS = re.compile(r"tesla|nissan|volvo|polestar|kia|hyundai|volkswagen|vw|[sš]koda|audi|bmw|mini|mercedes|renault|peugeot|citro|opel|toyota|lexus|ford|byd|porsche|cupra|seat|fiat|jaguar|zeekr|xpeng|nio|honda|mazda|subaru|smart", re.I)
PHONE_MAKERS = re.compile(r"^(samsung|apple|google|oneplus|xiaomi|huawei|oppo|motorola|sony|nokia|nothing|fairphone|realme|vivo|honor)\b", re.I)
SOLAR = re.compile(r"solar|sol(el|ar)?\b|pv\b|photovolt|inverter|växelriktare|produktion|production|yield", re.I)
INVERTER_MAKERS = re.compile(r"solaredge|huawei|fronius|sma\b|growatt|enphase|goodwe|solis|sungrow|deye|victron|ferroamp|solax|kostal|apsystems", re.I)
HEATPUMP = re.compile(r"husdata|h60|h66|nibe|thermia|ivt|ctc|bosch|daikin|mitsubishi|panasonic|vaillant|viessmann|heat ?pump|värmepump|bergvärme|luft.?vatten|ecoforest|qvantum|nordic", re.I)
SPA = re.compile(r"balboa|gecko|spa\b|spabad|jacuzzi|hot ?tub|bubbelpool|lay-?z|intex|softub|arctic spa|bwa", re.I)
CFOS_POWERBRAIN = re.compile(r"c[ _-]?fos|power[ _-]?brain", re.I)
CHARGER_MAKERS = re.compile(r"easee|zaptec|wallbox|charge ?amps|garo|ctek|go-?e|webasto|ensto|defa", re.I)
# lbbrhzn/ocpp (den vanliga HA-integrationen som kör en OCPP-server inuti Home
# Assistant) namnger entiteterna efter laddarens egen "charge point ID", inte efter
# ett märke - entitets-ID:t, inte enhetens tillverkartext, är den pålitliga signalen.
# Matchar alltså mot entity_id-suffix, inte mot CHARGER_MAKERS/_candidate().
OCPP_SWITCH_SUFFIX = re.compile(r"charge_control$", re.I)
OCPP_NUMBER_SUFFIX = re.compile(r"(maximum_current|session_current_limit)$", re.I)
# Sessionens gräns, inte laddboxens bestående tak (maximum_current) - se drivers/charger_generic.py.
OCPP_SESSION_LIMIT = re.compile(r"session_current_limit$", re.I)
OCPP_STATION_MAX = re.compile(r"maximum_current$", re.I)
# "tesla" ensamt är INTE med här (krockar med CAR_MAKERS - Powerwall kräver "powerwall"
# uttryckligen i texten för att skiljas från en Tesla-bil).
# Stationärt husbatteri, inte en bil: BYD gör både och, och BYD:s batteriintegrationer (bbr111/byd_hvs,
# redpomodoro/byd_battery_box) har tillverkaren "BYD" - förut hamnade BYD HVS bland bilarna (2026-11-03).
STATIONARY_BATTERY = re.compile(r"powerwall|energy site|battery[- ]?box|\bhv[sm]\b|\blv[sl]\b|\bbmu?\b|\bbms\b|cell ?(volt|temp)|soc diagnosis", re.I)
BATTERY_MAKERS = re.compile(r"givenergy|powerwall|huawei luna|luna2000|pytes|fox ?ess|alpha ?ess|sonnen|pylontech|lg (chem|ress)|byd battery|byd hv|battery[- ]?box|solax battery|victron battery|felicity", re.I)
# Nätimport/elmätare: ett hus kan ha Tibber Pulse, en smartmätare (HAN/P1-port) eller
# båda samtidigt - inte antingen-eller (Emils egen poäng, 2026-10-30). Förslaget blir en
# power_meter:-sektion (homeassistant.configure_power_meter): en Tibber Pulse med spänning +
# ström per fas om en sådan finns, annars första nätmätarens effektsensor (power_w).
GRID = re.compile(r"tibber pulse|p1\b|han\b|power ?meter|elmätare|smart ?meter|nätimport|grid import|consumption", re.I)

# Märke -> drivrutinsnyckel, bara för märken som FAKTISKT har en registrerad
# drivrutin idag. Ett hittat märke som inte finns här flaggas som "ingen
# drivrutin än" istället för att tyst väljas fel eller gömmas.
_HEATPUMP_BRAND_TO_DRIVER = {"husdata": "thermia_husdata", "thermia": "thermia_husdata"}
_SOLAR_BRAND_TO_DRIVER = {"solaredge": "solaredge"}
_SOLAREDGE_LEGACY_LIMIT = "number.solaredge_modbus_active_power_limit"   # drivers/solar_solaredge.py:s hårdkodade entitet
_SPA_BRAND_TO_DRIVER = {"gecko": "gecko", "balboa": "balboa"}
_CHARGER_BRAND_TO_DRIVER = {"easee": "easee"}

_TEMPLATE = """{% set ns = namespace(out=[]) %}
{% for s in states %}
  {% set d = device_id(s.entity_id) %}
  {% set ns.out = ns.out + [{
      "e": s.entity_id,
      "n": s.name,
      "a": area_name(s.entity_id),
      "d": d,
      "dn": (device_attr(d, 'name_by_user') or device_attr(d, 'name')) if d else none,
      "m": device_attr(d, 'manufacturer') if d else none,
      "mo": device_attr(d, 'model') if d else none,
      "dc": s.attributes.device_class | default(none),
      "u": s.attributes.unit_of_measurement | default(none),
      "st": s.state,
      "options": s.attributes.options | default(none) if s.entity_id.startswith('select.') else none,
      "ci": s.attributes.id | default(none) if s.entity_id.startswith('sensor.') and (s.attributes.id | default(none)) is string else none
  }] %}
{% endfor %}
{{ ns.out | tojson }}"""


def _easee_mapping(ents: list, status_e: dict) -> dict:
    """Easee-laddboxens entiteter ur dess enhet, oavsett språk och vad användaren döpt boxen till (2026-11-07: guiden
    kopplade bara status och skrev in utvecklarens boxnamn). id = laddboxens serienummer (attributet "id", t.ex.
    EH123456) som integrationens tjänster kräver. Avstängda entiteter finns inte i listan och kopplas inte."""
    def pick(domain, name_rx, dc=None, unit=None):
        rx = re.compile(name_rx, re.I)
        for e in ents:
            if not e["e"].startswith(domain + "."):
                continue
            if dc and e.get("dc") != dc:
                continue
            if unit and e.get("u") not in unit:
                continue
            if rx.search(e.get("n") or "") or rx.search(e["e"]):
                return e["e"]
        return None
    m = {
        "status": status_e["e"],
        "power_kw": pick("sensor", r"effekt|power", dc="power"),
        # Huvudströmmen (med fasströmmarna som attribut), inte krets- eller begränsningsströmmar
        "current_a": next((e["e"] for e in ents if e["e"].startswith("sensor.") and e.get("dc") == "current"
                           and re.search(r"(^|_)(strom|ström|current)$", e["e"], re.I)), None),
        "session_kwh": pick("sensor", r"session", unit=("kWh", "Wh")),
        "lifetime_kwh": pick("sensor", r"livstid|lifetime", unit=("kWh", "Wh")),
        "dynamic_limit": pick("sensor", r"dynamisk.?laddbox|dynamisk.?laddar|dynamic.?charger"),
        "output_limit": pick("sensor", r"total.?begr|output.?limit"),
        "max_limit": pick("sensor", r"max.?laddbox|max.?laddar|max.?charger"),
        "reason_no_current": pick("sensor", r"anledning|reason"),
        "online": pick("binary_sensor", r"online"),
    }
    out = {"easee_entities": {k: v for k, v in m.items() if v}}
    # Laddboxen på/av ("Laddboxen aktiverad" / "Charger enabled") - inte touchknappen, kabellåset eller smart laddning
    sw = pick("switch", r"(laddbox|laddare|charger)\w*.?(aktiverad|enabled)|is.?enabled$")
    if sw:
        out["enable_switch"] = sw
    cid = next((e.get("ci") for e in ents if e.get("ci") and re.fullmatch(r"[A-Z0-9]{6,12}", str(e.get("ci")))), None)
    if cid:
        out["charger_id"] = cid
    return out


def read_all_entities() -> list[dict]:
    """POST:ar Jinja2-mallen mot HA:s /api/template. Om svaret blir för stort
    (HA svarar 400) hämtas det i bitar istället, om 150 åt gången - samma
    fallback discovery.ts redan bevisat behövs för hus med många entiteter."""
    try:
        r = requests.post(f"{homeassistant._BASE}/template", headers=homeassistant._HEADERS,
                           json={"template": _TEMPLATE}, timeout=30, verify=homeassistant._VERIFY)
        if r.status_code == 200:
            import json
            return json.loads(r.text)
    except Exception as e:
        print(f"⚠️ discovery: fullständig /api/template-hämtning misslyckades ({e}), provar i bitar.")

    out = []
    batch = 150
    i = 0
    import json
    while True:
        chunk_template = _TEMPLATE.replace(
            "{% for s in states %}", f"{{% for s in (states | list)[{i}:{i + batch}] %}}"
        )
        try:
            r = requests.post(f"{homeassistant._BASE}/template", headers=homeassistant._HEADERS,
                               json={"template": chunk_template}, timeout=30, verify=homeassistant._VERIFY)
            r.raise_for_status()
            rows = json.loads(r.text)
        except Exception as e:
            print(f"⚠️ discovery: hämtning av entiteter {i}-{i + batch} misslyckades: {e}")
            break
        if not rows:
            break
        out.extend(rows)
        i += batch
    return out


def _has(text, pattern) -> bool:
    return bool(text and pattern.search(text))


def _candidate(e: dict) -> str:
    return f"{e.get('m') or ''} {e.get('mo') or ''} {e.get('n') or ''} {e.get('dn') or ''}"


# NIBE:s givarkoder i entiteternas namn - samma på alla språk (myUplink- och nibe_heatpump-integrationerna i HA).
# \b efter siffran: BT1 får inte matcha BT10/BT11.
# #162: myUplink-entiteter saknar ibland BT-koden men har pumpens parameternummer i namnet ("F750 Cu Utomhustemperatur
# (40004)"). Samma nummer på alla NIBE-modeller med myUplink (40004 ute, 40008 framledning, 40012 retur, 40013/40014
# varmvatten, 40033 rum).
_NIBE_BT = {"outdoor_temp": [r"\bBT1\b", r"[(_]40004\b"], "forward_temp": [r"\bBT2\b", r"[(_]40008\b"],
            "return_temp": [r"\bBT3\b", r"[(_]40012\b"], "water_temp": [r"\bBT7\b", r"[(_]40013\b", r"\bBT6\b", r"[(_]40014\b"],
            "indoor_temp": [r"\bBT50\b", r"[(_]40033\b"]}
_DEGREE_MIN = re.compile(r"degree.?minutes|gradminuter|gradminutter|astemin|[(_](40940|43005)\b", re.I)


def _nibe_bt_entities(ents) -> dict:
    """#158: värmepumpens entiteter ur NIBE:s givarkoder (BT1 ute, BT2 framledning, BT3 retur, BT7/BT6 varmvatten,
    BT50 rum) och gradminuter. Bara sensor-entiteter för temperaturerna. Tom dict om färre än två hittas."""
    out = {}
    for key, pats in _NIBE_BT.items():
        for pat in pats:
            hit = next((x["e"] for x in ents if x["e"].startswith("sensor.")
                        and re.search(pat, f"{x.get('n') or ''} {x['e']}", re.I)), None)
            if hit:
                out[key] = hit
                break
    dm = next((x["e"] for x in ents if x["e"].split(".")[0] in ("sensor", "number")
               and _DEGREE_MIN.search(f"{x.get('n') or ''} {x['e']}")), None)
    if dm:
        out["degree_minutes"] = dm
    # #184: kompressorns frekvens eller status (myUplink: "Kompressorfrekvens, aktuell" / "Compressor frequency" /
    # "Compressor status"), så att flödet vet om pumpen går. Frekvens > 0 = går (heatpump_ha_entities.py).
    comp = next((x["e"] for x in ents if x["e"].split(".")[0] in ("sensor", "binary_sensor")
                 and re.search(r"kompressor|compressor", f"{x.get('n') or ''} {x['e']}", re.I)
                 and re.search(r"frekvens|frequency|hz|status|drift|running|state", f"{x.get('n') or ''} {x['e']} {x.get('u') or ''}", re.I)
                 and not re.search(r"start|tid|time|hours|timmar|count|antal|max|min\b|setpoint|börvärde", f"{x.get('n') or ''} {x['e']}", re.I)), None)
    if comp:
        out["compressor"] = comp
    # #200: värmekurvans förskjutning (NIBE 47011 / "Heating offset climate system 1" / "Värmeförskjutning") - styr
    # pumpen när det inte finns något rumsbörvärde
    off = next((x["e"] for x in ents if x["e"].startswith("number.")
                and re.search(r"47011|heat(ing)?.?offset|v[äa]rmef[öo]rskjutning|kurvf[öo]rskjutning|offset.{0,20}(climate|klimat).?system.?1|f[öo]rskjutning.{0,12}v[äa]rmekurva",
                              f"{x.get('n') or ''} {x['e']}", re.I)), None)
    if off:
        out["curve_offset"] = off
    return out if len([k for k in out if k not in ("degree_minutes", "compressor", "curve_offset")]) >= 2 else {}


def _is_temperature(x) -> bool:
    return x.get("dc") == "temperature" or x.get("u") in ("°C", "°F")


def _check_configured_heat_pump() -> dict | None:
    """Pumpen kan redan prata Modbus DIREKT med smartbox (husets PUMP_IP) utan att gå via
    HA alls - main.py anropar redan pump.read_sensors() varje cykel och loggar resultatet
    till sensor_log. Läser BARA den loggen (ingen ny Modbus-anslutning härifrån - en andra,
    parallell anslutning till samma pump skulle riskera att störa den körande styrningen).
    Returnerar None om ingen färsk rad finns, annars ett fynd i samma form som HA-sökningen.

    #162 (2026-11-06): förut räckte en färsk innetemperatur i sensor_log - men den kommer lika gärna från rumsgivare i
    HA, så en NIBE-ägare fick "Husdata redan ansluten". Nu krävs att installationen faktiskt kör Husdata-drivrutinen
    och att pumpen själv loggat framledning de senaste 10 minuterna."""
    try:
        import os
        import house_config
        hp = (house_config.load_house_config(os.environ.get("HOUSE_CONFIG_PATH", "/house_config.yaml")).get("heat_pump") or {})
    except Exception:
        hp = {}
    if not hp.get("enabled") or hp.get("driver") != "thermia_husdata":
        return None
    try:
        with get_db() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT 1 FROM sensor_log
                WHERE forward_temp IS NOT NULL AND timestamp > NOW() - INTERVAL '10 minutes'
                ORDER BY timestamp DESC LIMIT 1
            """)
            if cur.fetchone() is None:
                return None
    except Exception as e:
        print(f"⚠️ discovery: kunde inte kolla sensor_log för redan konfigurerad värmepump: {e}")
        return None
    return {
        "device_name": "Husdata (redan ansluten)", "maker": "Husdata",
        "driver": "thermia_husdata", "driver_known": True,
        "source": "modbus_configured_on_server",
        "note": "Redan ansluten via Modbus direkt på den här servern (PUMP_IP) - går inte via Home Assistant.",
    }


def _find(ents, domain, rx):
    return next((x for x in ents if x["e"].startswith(domain + ".") and _has(x.get("n") or x["e"], rx)), None)


# Use measurement names, not the device's shared "inverter" label: hybrid
# inverters expose grid, battery and load sensors on the very same device.
_NOT_PV = re.compile(r"\b(grid|import|export|feed|battery|batteri|storage|charge|charging|discharge|discharging|load|consumption|reactive|apparent)\b", re.I)
_PV_INPUT = re.compile(r"\b(pv|solar|sol|solel|photovolt\w*|mppt|dc|string)\b", re.I)
_PV_TOTAL = re.compile(r"\b(total|combined|sum)\b", re.I)


def _measurement_name(entity):
    return re.sub(r"[_\W]+", " ", entity["e"].split(".", 1)[-1] + " " + (entity.get("n") or ""))


def _solar_rank(entity):
    name = _measurement_name(entity)
    # Prefer explicit PV inputs, then retain the existing known-maker fallback.
    # Stable ordering prevents HA's entity order from changing the suggestion.
    return (bool(_PV_INPUT.search(name)), bool(_has(_candidate(entity), INVERTER_MAKERS)),
            bool(_PV_TOTAL.search(name)), entity["e"])


# Nummer före "power": mppt_module_0_dc_power. "pv_power_1" (siffran sist) är ingen modul.
_PV_MODULE = re.compile(r"(mppt.?module.?|mppt.?|pv.?|string.?)(\d+).*(dc.?)?power", re.I)
_TODAY_ENERGY = re.compile(r"today|idag|dag", re.I)


def _pv_module(entity):
    return _PV_MODULE.search(entity["e"])


def _explicit_pv(entity) -> bool:
    name = _measurement_name(entity)
    return bool(_PV_INPUT.search(name) or _PV_TOTAL.search(name))


def _pv_power_selection(candidates: list[dict]) -> list[dict]:
    """En avläsning per växelriktare. Strängar och MPPT-moduler tas bara med när växelriktaren
    saknar en egen solgivare, så en total och dess strängar inte räknas två gånger."""
    groups: dict = {}
    for entity in candidates:
        key = ("d", entity["d"]) if entity.get("d") else ("dn", entity.get("dn") or "")
        groups.setdefault(key, []).append(entity)
    chosen = []
    for ents in groups.values():
        whole = [e for e in ents if _explicit_pv(e) and not _pv_module(e)]
        mods = [e for e in ents if _pv_module(e)]
        if whole:
            chosen.append(max(whole, key=_solar_rank))
        elif len(mods) > 1:
            best = max(mods, key=_solar_rank)
            prefix = _pv_module(best).group(1).lower()
            chosen.extend(e for e in mods if _pv_module(e).group(1).lower() == prefix)
        else:
            chosen.append(max(ents, key=_solar_rank))
    by_id = {}
    for entity in chosen:
        by_id.setdefault(entity["e"], entity)
    return [by_id[key] for key in sorted(by_id)]


def _today_energy(entities: list[dict], device) -> dict | None:
    """Dagens solenergi på en växelriktare. Nät, batteri och last räknas inte."""
    if not device:
        return None
    cands = [e for e in entities if e["e"].startswith("sensor.") and e.get("u") in ("kWh", "Wh")
             and e.get("d") == device and not _NOT_PV.search(_measurement_name(e))
             and _has(e.get("n"), _TODAY_ENERGY)]
    return max(cands, key=_solar_rank) if cands else None


_CHG_W = re.compile(r"(storage|battery|batteri|batt)\w*[ _](charging|charge|laddning|laddar)[ _]power$|(storage|battery)_charging_power$", re.I)
_DIS_W = re.compile(r"(storage|battery|batteri|batt)\w*[ _](discharging|discharge|urladdning|laddar[ _]ur)[ _]power$|(storage|battery)_discharging_power$", re.I)
_NOT_W = re.compile(r"max|limit|rate|setpoint|target|total|energy|kwh", re.I)


def _split_battery_power(ents) -> dict:
    """#139: batterier som har EN givare för laddeffekt och EN för urladdningseffekt (båda positiva, t.ex. Fronius GEN24
    "Storage charging power"/"Storage discharging power") - då används de i stället för en ensam effektgivare, som
    annars kan bli fel givare. {} om inte båda finns."""
    def pick(rx):
        return next((x["e"] for x in ents if x["e"].startswith("sensor.") and x.get("u") in ("W", "kW")
                     and rx.search(x["e"]) and not _NOT_W.search(x["e"])), None)
    chg, dis = pick(_CHG_W), pick(_DIS_W)
    return {"power_charge": chg, "power_discharge": dis} if chg and dis else {}


def _battery_control_preset(ents, all_ents=None):
    """Känner igen batteristyrning från wills106/homeassistant-solax-modbus och föreslår hela
    lägesmappningen (drivers/battery_generic.py). Lägesnamnen är integrationens egna (plugin_solax.py /
    plugin_growatt.py), inte gissade."""
    # Felicity Solar via partach/ha_felicity: BARA avläsning. Integrationen har en egen prisstyrning (EMS) som
    # skriver växelriktarens Economic-regler, och dess "Operating Mode"-val skriver Economic (2) även när man väljer
    # Backup (1) på T-REX 5/10K (type_specific.py _handle_operating_mode, läst 2026-11-03). Att styra därifrån vore
    # att slåss med EMS:en och få fel läge, så EnergyWizard visar SOC/effekt och låter ha_felicity styra.
    if any(_has(x.get("m"), re.compile(r"felicity", re.I)) for x in ents):
        return {"name": "felicity_monitor", "entities": {}, "modes": {},
                "note": "Styrs av ha_felicity:s egen EMS. EnergyWizard läser bara. Kontrollera effektens tecken "
                        "(+ ska vara laddning, annars power_invert: true)."}
    # Solis hybrid (S6-EH1P/EH3P m.fl.) via Pho3niX90/solis_modbus: "RC Force Charge/Discharge" (register 43135)
    # med alternativen None / Solis RC Force Battery Charge / Solis RC Force Battery Discharge, och effekten i W
    # (43136/43129). Läst i integrationens källa 2026-11-03 (sensor_data/select_sensors.py, hybrid_sensors.py).
    # Fjärrstyrningen släpper efter RC Timeout (43282, standard 5 min) - därför keepalive_s. "Storage Mode"
    # (växelriktarens eget läge, sparas i flash) rörs aldrig: auto = None = det läge användaren valt.
    # Ingen ren "håll"-motsvarighet finns, så den utelämnas hellre än gissas.
    rc = _find(ents, "select", re.compile(r"rc force charge/discharge$", re.I))
    if rc:
        r = rc["e"]
        out = {"name": "solis_modbus", "entities": {}, "keepalive_s": 180,
               "modes": {"auto": {r: "None"}, "charge": {r: "Solis RC Force Battery Charge"},
                         "discharge": {r: "Solis RC Force Battery Discharge"}}}
        cp = _find(ents, "number", re.compile(r"rc force battery charge power$", re.I))
        dp = _find(ents, "number", re.compile(r"rc force battery discharge power$", re.I))
        if cp:
            out["entities"]["charge_power"] = cp["e"]
        if dp:
            out["entities"]["discharge_power"] = dp["e"]
        return out
    # Fronius Gen24 (Primo/Symo) via redpomodoro/fronius_modbus, t.ex. med BYD HVS: "Storage Control Mode"
    # (Auto, Charge from Grid, Discharge to Grid, Block Discharging ...) och effekten i W (Grid charge/discharge
    # power). Läst i integrationens källa 2026-11-03 (const.py STORAGE_EXT_CONTROL_MODE). Läget ligger kvar tills
    # något annat väljs - EnergyWizard sätter Auto vid start och avstängning, som för alla batterier.
    scm = _find(ents, "select", re.compile(r"storage control mode$", re.I))
    if scm and not _find(ents, "select", re.compile(r"storage command mode$", re.I)):     # SolarEdge har båda (nedan)
        s = scm["e"]
        out = {"name": "fronius_modbus", "entities": {"mode_select": s},
               "modes": {"auto": "Auto", "hold": "Block Discharging", "charge": "Charge from Grid",
                         "discharge": "Discharge to Grid"}}
        gc = _find(ents, "number", re.compile(r"grid charge power$", re.I))
        gd = _find(ents, "number", re.compile(r"grid discharge power$", re.I))
        if gc:
            out["entities"]["charge_power"] = gc["e"]
        if gd:
            out["entities"]["discharge_power"] = gd["e"]
        out["entities"].update(_split_battery_power(all_ents or ents))       # #139: laddning/urladdning var för sig
        return out
    # HomeWizard Plug-In Battery (HA:s inbyggda homewizard-integration): "Battery group charging strategy" ligger på
    # P1-/kWh-mätaren, inte på batteriet - därför letas den bland alla entiteter (all_ents). Alternativen är HA:s
    # interna nycklar ur homeassistant/components/homewizard (select.py + strings.json), inte visningsnamnen:
    # zero = Net zero, zero_charge_only, zero_discharge_only, to_full = One-time full charge, standby.
    # "Ladda ur" utelämnas: närmast vore zero_discharge_only, men den säljer aldrig till nätet - auto täcker huset ändå.
    if any(_has(x.get("m"), re.compile(r"homewizard", re.I)) for x in ents):
        hw = _find(all_ents or ents, "select", re.compile(r"battery group (charging strategy|mode)$", re.I))
        if hw:
            return {"name": "homewizard", "entities": {"mode_select": hw["e"]},
                    "modes": {"auto": "zero", "hold": "zero_charge_only", "idle": "standby", "charge": "to_full"}}
    # Solax Gen4-6: "Charger Use Mode" + "Manual Mode Select"
    use = _find(ents, "select", re.compile(r"charger use mode$", re.I))
    manual = _find(ents, "select", re.compile(r"manual mode select$", re.I))
    if use and manual:
        u, m = use["e"], manual["e"]
        return {"name": "solax_modbus_solax", "entities": {}, "modes": {
            "auto": {u: "Self Use Mode"}, "hold": {u: "Back Up Mode"},
            "idle": {u: "Manual Mode", m: "Stop Charge and Discharge"},
            "charge": {u: "Manual Mode", m: "Force Charge"}, "discharge": {u: "Manual Mode", m: "Force Discharge"}}}
    # Solax Gen2 (t.ex. SK-SU5000E): samma "Charger Use Mode" men utan "Manual Mode Select" och med andra val:
    # Self Use Mode / Force Time Use / Back Up Mode. Gen2 känns igen på sina urladdningsfönster (discharge_start_1,
    # finns bara på Gen2). Uppgifterna kommer från MJP-76 (issue #86), verifierade mot två riktiga SK-SU5000E och
    # solax-modbus-källan. Bara lägesbyte: tidsfönstren skrivs aldrig om - de ska stå vidöppna (t.ex. laddfönster 2
    # 00:01-23:59), och Force Time Use laddar då från nätet. Ingen urladdning: Gen2 har inget sådant läge utan att
    # programmera om fönstren, och Self Use täcker huset ändå. Flera Gen2-växelriktare (vanligt, en per batteribank)
    # byter läge tillsammans.
    if use and not manual and _find(ents, "time", re.compile(r"discharge start 1$", re.I)):
        gen2 = [use["e"]] + sorted({x["e"] for x in (all_ents or []) if x["e"] != use["e"] and x["e"].startswith("select.")
                                    and _has(x.get("n") or x["e"], re.compile(r"charger use mode$", re.I))
                                    and any(y.get("d") == x.get("d") and y["e"].startswith("time.")
                                            and _has(y.get("n") or y["e"], re.compile(r"discharge start 1$", re.I))
                                            for y in all_ents)})
        both = lambda opt: {e: opt for e in gen2}
        return {"name": "solax_modbus_gen2", "entities": {},
                "modes": {"auto": both("Self Use Mode"), "hold": both("Back Up Mode"), "charge": both("Force Time Use")},
                "note": "Solax Gen2: laddfönstren ska stå vidöppna i växelriktaren (t.ex. 00:01-23:59) - EnergyWizard "
                        "byter bara Charger Use Mode och skriver aldrig om tiderna."}
    # FoxESS via nathanmarlor/foxess_modbus (lokalt, Modbus): "Work Mode" har Force Charge/Force
    # Discharge när integrationens fjärrstyrning är påslagen, och effekten sätts i kW.
    work = _find(ents, "select", re.compile(r"work mode$", re.I))
    fcp = _find(ents, "number", re.compile(r"force charge power$", re.I))
    fdp = _find(ents, "number", re.compile(r"force discharge power$", re.I))
    if work and (fcp or fdp):
        w = work["e"]
        out = {"name": "foxess_modbus", "entities": {"mode_select": w},
               "modes": {"auto": "Self Use", "hold": "Back-up", "charge": "Force Charge", "discharge": "Force Discharge"}}
        if fcp:
            out["entities"]["charge_power"] = fcp["e"]
        if fdp:
            out["entities"]["discharge_power"] = fdp["e"]
        return out
    # FoxESS via macxq/foxess-ha (FoxESS Cloud): bara lägena. Molnet har en daglig anropsgräns,
    # och EnergyWizard byter läge högst var femte minut. Laddning från nätet styrs inte här.
    cloud = next((x for x in ents if x["e"].startswith("select.") and "fox" in str(x.get("m") or "").lower()
                  and _has(x.get("n") or x["e"], re.compile(r" - work mode$", re.I))), None)
    if cloud:
        return {"name": "foxess_cloud", "entities": {"mode_select": cloud["e"]},
                "modes": {"auto": "Self-Use", "hold": "Backup"}}
    # Growatt via Solax Modbus: "Time 1 Mode" (sparas lokalt) + knappen "Time 1 Update"
    tmode = _find(ents, "select", re.compile(r"time 1 mode$", re.I))
    tbtn = _find(ents, "button", re.compile(r"time 1 update$", re.I))
    if tmode and tbtn:
        out = {"name": "solax_modbus_growatt", "entities": {"mode_select": tmode["e"], "mode_apply_button": tbtn["e"]},
               "modes": {"auto": "Load First", "hold": "Battery First", "charge": "Battery First", "discharge": "Grid First"}}
        chg = _find(ents, "sensor", re.compile(r"battery charge power$", re.I))
        dis = _find(ents, "sensor", re.compile(r"battery discharge power$", re.I))
        if chg and dis:
            out["entities"].update(power_charge=chg["e"], power_discharge=dis["e"])
        return out
    # --- Fler förinställningar (2026-11-05). Lägesnamnen är integrationernas egna, lästa i källkoden samma dag. ---
    # GoodWe (HA:s inbyggda goodwe-integration, select.py): "Inverter operation mode" med de interna nycklarna
    # general / eco_charge / eco_discharge (backup laddar också från nätet, så den används inte som "håll").
    gw = _find(ents, "select", re.compile(r"inverter operation mode$", re.I))
    if gw:
        g = gw["e"]
        options = gw.get("options")
        if not isinstance(options, list) or not all(isinstance(x, str) for x in options):
            options = []
        # #181: exposed alternatives vary by integration/firmware. Never invent
        # eco modes, and do not suggest forcing a mode without a known return path.
        known = {"auto": "general", "charge": "eco_charge", "discharge": "eco_discharge"}
        modes = {intent: option for intent, option in known.items() if option in options} if "general" in options else {}
        note = ("GoodWe: endast lägen som Home Assistant erbjuder föreslås. "
                "Eco-lägenas funktion och effekt-/SOC-gränser måste verifieras för din integration och firmware.")
        if not modes:
            note = ("GoodWe: lägeslistan eller normalläget general saknas. "
                    "Läsning utan styrning föreslås tills lägena har verifierats i Home Assistant.")
        return {"name": "goodwe", "entities": {"mode_select": g}, "modes": modes, "note": note}
    # SolarEdge med batteri via WillCodeForCats/solaredge-modbus-multi (const.py STORAGE_CONTROL_MODE / STORAGE_MODE):
    # "Storage Control Mode" = Remote Control + "Storage Command Mode". Urladdning = "Discharge to Minimize Import"
    # (säljer aldrig från batteriet). Laddning från nätet kräver att AC Charge Policy tillåter det i växelriktaren.
    scm2 = _find(ents, "select", re.compile(r"storage control mode$", re.I))
    cmd = _find(ents, "select", re.compile(r"storage command mode$", re.I))
    if scm2 and cmd:
        c, m = scm2["e"], cmd["e"]
        out = {"name": "solaredge_modbus_multi", "entities": {}, "keepalive_s": 600,
               "modes": {"auto": {c: "Maximize Self Consumption"},
                         "hold": {c: "Remote Control", m: "Charge from Solar Power"},
                         "idle": {c: "Remote Control", m: "Solar Power Only (Off)"},
                         "charge": {c: "Remote Control", m: "Charge from Solar Power and Grid"},
                         "discharge": {c: "Remote Control", m: "Discharge to Minimize Import"}},
               "note": "SolarEdge: laddning från nätet kräver att 'AC Charge Policy' är 'Always Allowed'. Fjärrstyrningen "
                       "släpper efter 'Storage Command Timeout' - EnergyWizard skriver om kommandot var tionde minut."}
        cl = _find(ents, "number", re.compile(r"storage charge limit$", re.I))
        dl = _find(ents, "number", re.compile(r"storage discharge limit$", re.I))
        if cl:
            out["entities"]["charge_power"] = cl["e"]
        if dl:
            out["entities"]["discharge_power"] = dl["e"]
        return out
    # Huawei SUN2000 + LUNA2000 via wlcrs/huawei_solar (services.yaml): forcible_charge / forcible_discharge med
    # batteriets enhet, effekt (W) och varaktighet (min), stop_forcible_charge släpper till batteriets eget läge.
    # Ingen "håll": 0 W i Huawei betyder att tvångsläget släpps (samma fallgrop som FTW:s huawei-drivrutin beskriver).
    # Varaktigheten 30 min + omskrivning var 15:e min: tystnar EnergyWizard återgår batteriet av sig själv.
    if any(_has(x.get("m"), re.compile(r"huawei", re.I)) for x in ents) and _find(ents, "sensor", re.compile(r"state of capacity$|battery.*soc$", re.I)):
        dev = ents[0].get("d")
        if dev:
            data = {"device_id": dev, "duration": 30}
            return {"name": "huawei_solar", "entities": {}, "keepalive_s": 900,
                    "modes": {"auto": {"service": "huawei_solar.stop_forcible_charge", "data": {"device_id": dev}},
                              "charge": {"service": "huawei_solar.forcible_charge", "data": data, "power_field": "power"},
                              "discharge": {"service": "huawei_solar.forcible_discharge", "data": data, "power_field": "power"}},
                    "note": "Huawei LUNA2000: styrs med integrationens tjänster (tvångsladdning 30 min i taget). Provad mot "
                            "källkoden, inte på riktig hårdvara - börja i skuggläge."}
    # --- 2026-11-06: Sonnen, Victron och Kostal (integrationernas källkod lästa samma dag) ---
    # Sonnen via weltmeyer/ha_sonnenbatterie (services.yaml/service.py): charge_battery/discharge_battery(device_id, power)
    # skriver API:ets börvärde, som bara gäller i manuellt läge - därför först set_operating_mode manual. Auto = automatic.
    if any(_has(x.get("m"), re.compile(r"sonnen", re.I)) for x in ents) and ents[0].get("d"):
        dev = ents[0]["d"]
        manual = {"service": "sonnenbatterie.set_operating_mode", "data": {"device_id": dev, "mode": "manual"}}
        return {"name": "sonnenbatterie", "entities": {}, "keepalive_s": 600,
                "modes": {"auto": {"service": "sonnenbatterie.set_operating_mode", "data": {"device_id": dev, "mode": "automatic"}},
                          "charge": [manual, {"service": "sonnenbatterie.charge_battery", "data": {"device_id": dev}, "power_field": "power"}],
                          "discharge": [manual, {"service": "sonnenbatterie.discharge_battery", "data": {"device_id": dev}, "power_field": "power"}]},
                "note": "Sonnen: styrs med integrationens tjänster (manuellt läge + börvärde). Provad mot källkoden, inte på "
                        "riktig hårdvara - börja i skuggläge."}
    # Victron via sfstar/hass-victron (const.py): settings_ess_acpowersetpoint (register 2700, W, + = köp från nätet).
    # Ladda = börvärde +effekt (batteriet laddas med det huset inte använder), ladda ur = -effekt (matar ut), auto = 0.
    vsp = next((x["e"] for x in (all_ents or ents) if re.fullmatch(r"number\.victron_settings_ess_acpowersetpoint(_\d+)?", x["e"])), None)
    if vsp:
        return {"name": "victron_ess", "entities": {},
                "modes": {"auto": {"number": vsp, "value": 0}, "charge": {"number": vsp, "sign": 1},
                          "discharge": {"number": vsp, "sign": -1}},
                "note": "Victron ESS: styrs med nätets börvärde (ESS-läge 'Optimized'/'Keep charged' i GX). Laddning från nätet = "
                        "börvärde + effekt minus husets förbrukning. Provad mot källkoden - börja i skuggläge."}
    # Kostal Plenticore (HA:s inbyggda kostal_plenticore, number.py): "Battery min SoC" (Battery:MinSoc). Integrationen
    # kan inte tvinga laddning/urladdning - men "håll" går: lägsta laddnivån höjs till nuvarande, så sparas batteriet
    # till de dyra timmarna. Auto = tillbaka till 5 %.
    if any(_has(x.get("m"), re.compile(r"kostal", re.I)) for x in ents):
        ms = _find(all_ents or ents, "number", re.compile(r"battery min soc$", re.I))
        if ms:
            return {"name": "kostal_plenticore", "entities": {},
                    "modes": {"auto": {"number": ms["e"], "value": 5}, "hold": {"number": ms["e"], "value": "soc"}},
                    "note": "Kostal Plenticore: bara 'håll' (lägsta laddnivå = nuvarande), ingen tvingad laddning/urladdning "
                            "i integrationen. Auto sätter tillbaka lägsta nivån till 5 %."}
    # Tesla Powerwall via HA:s teslemetry / tesla_fleet (select.py): "Operation mode" med self_consumption / backup /
    # autonomous. backup laddar batteriet fullt (från nätet om nätladdning är tillåten i Tesla-appen). Ingen
    # tvingad urladdning finns i Teslas API.
    if any(_has(x.get("m"), re.compile(r"tesla", re.I)) for x in ents) and not any(x["e"].startswith("device_tracker.") for x in ents):
        op = _find(ents, "select", re.compile(r"operation mode$", re.I))
        if op:
            return {"name": "tesla_powerwall", "entities": {"mode_select": op["e"]},
                    "modes": {"auto": "self_consumption", "charge": "backup"},
                    "note": "Powerwall: 'charge' = Backup (laddar fullt). Ingen tvingad urladdning i Teslas API. Byt läge "
                            "sparsamt - Teslas moln har anropsgränser."}
    # Enphase IQ Battery via HA:s enphase_envoy (select.py storage_mode): self_consumption / backup / savings.
    if any(_has(x.get("m"), re.compile(r"enphase", re.I)) for x in ents):
        st = _find(ents, "select", re.compile(r"storage mode$", re.I))
        if st:
            return {"name": "enphase", "entities": {"mode_select": st["e"]},
                    "modes": {"auto": "self_consumption", "charge": "backup"},
                    "note": "Enphase: 'charge' = Full backup. Ingen tvingad urladdning via integrationen."}
    return None


def _sungrow_mkaiser(all_ents):
    """Sungrow SH* via mkaiser/Sungrow-SHx-Inverter-Modbus-Home-Assistant (modbus_sungrow.yaml): mallentiteterna saknar
    enhet i HA, så de hittas bland alla entiteter. "EMS mode" + "Battery forced charge discharge", effekten i
    "Battery forced charge discharge power" (W), nivån i "Battery level" och effekten i "Battery charging power signed"
    (+ = laddar). Lägesnamnen ur yaml-filens egna kartor (läst 2026-11-05)."""
    ems = _find(all_ents, "select", re.compile(r"^ems mode$", re.I))
    fcd = _find(all_ents, "select", re.compile(r"^battery forced charge discharge$", re.I))
    soc = _find(all_ents, "sensor", re.compile(r"^battery level$", re.I))
    if not (ems and fcd and soc):
        return None
    e, f = ems["e"], fcd["e"]
    ents = {"soc": soc["e"]}
    pw = _find(all_ents, "sensor", re.compile(r"^battery charging power signed$", re.I))
    if pw:
        ents["power"] = pw["e"]
    num = _find(all_ents, "number", re.compile(r"^battery forced charge discharge power$", re.I))
    if num:
        ents["charge_power"] = ents["discharge_power"] = num["e"]
    return {"device_name": "Sungrow", "maker": "Sungrow", "soc_entity": soc["e"], "power_entity": ents.get("power"),
            "driver": None, "driver_known": False, "control_preset": "sungrow_mkaiser",
            "generic_suggestion": {"driver": "generic", "preset": "sungrow_mkaiser", "entities": ents,
                                   "modes": {"auto": {e: "Self-consumption mode (default)", f: "Stop (default)"},
                                             "idle": {e: "Forced mode", f: "Stop (default)"},
                                             "charge": {e: "Forced mode", f: "Forced charge"},
                                             "discharge": {e: "Forced mode", f: "Forced discharge"}}},
            "note": "Sungrow (mkaiser): provad mot yaml-filen, inte på riktig hårdvara - börja i skuggläge."}


def _cfos_charger_entities(ents):
    """mb-software/homeassistant-powerbrain: session override in A, not rule switches (#226)."""
    def pick(domain, suffix, units=None):
        rx = re.compile(r"(?:^|_)" + re.escape(suffix) + r"$", re.I)
        return next((e for e in ents if e["e"].startswith(domain + ".")
                     and (units is None or e.get("u") in units)
                     and any(rx.search(re.sub(r"[ -]+", "_", value))
                             for value in (e["e"].split(".", 1)[1], e.get("n") or ""))), None)
    status = pick("sensor", "state")
    enabled = pick("switch", "charging_enabled")
    limit = pick("number", "current_limit_override", {"A"})
    if not (status and enabled and limit):
        return None
    out = {"status": status["e"], "switch": enabled["e"], "current_limit": limit["e"]}
    power = pick("sensor", "charging_power", {"W", "kW"})
    current = pick("sensor", "current_l1", {"A"})
    if power:
        out["power"] = power["e"]
    if current:
        out["current_import"] = current["e"]
    return out


# HA kan läsa de här märkena men inte styra batteriet. Guiden namnger FTW-drivrutinen
# och väljer den inte själv: användaren fyller i IP, och styrning förblir av.
_FTW_WHEN_HA_CANNOT_CONTROL = (
    (re.compile(r"deye|sunsynk", re.I), "deye", True),
    (re.compile(r"sigenergy|sigenstor", re.I), "sigenergy", True),
    (re.compile(r"solinteg", re.I), "solinteg", True),
    (re.compile(r"pixii", re.I), "pixii", False),
)


def ftw_control_suggestion(battery, solar):
    """Drivrutin att nämna i guiden, eller None när HA redan kan styra.

    Returnerar driver, om den också läser sol, och en notis. Ingen config skrivs här.
    """
    if (battery or {}).get("control_preset") or ((battery or {}).get("generic_suggestion") or {}).get("modes"):
        return None
    parts = []
    for obj in (battery, solar):
        if not isinstance(obj, dict):
            continue
        for key in ("maker", "device_name", "soc_entity", "power_entity", "pv_power_entity"):
            if obj.get(key):
                parts.append(str(obj[key]))
    blob = " ".join(parts)
    folder = os.path.join(os.path.dirname(__file__), "ftw_drivers")
    for rx, driver, also_solar in _FTW_WHEN_HA_CANNOT_CONTROL:
        if not rx.search(blob):
            continue
        if not re.fullmatch(r"[a-z0-9_]{1,40}", driver) or not os.path.isfile(os.path.join(folder, driver + ".lua")):
            return None
        return {"driver": driver, "battery": True, "solar": also_solar, "note": (
            f"Home Assistant kan läsa den här enheten men inte styra batteriet. "
            f"Välj FTW-drivrutinen {driver} nedan och fyll i IP-adressen om EnergyWizard ska läsa den direkt. "
            f"Styrning är av tills du kryssar i den. Drivrutinen är inte provad på riktig hårdvara, så börja i skuggläge.")}
    return None


def discover_house(entities: list[dict] | None = None) -> dict:
    """Returnerar kandidater per EnergyWizard-kategori. `entities` kan skickas
    in (t.ex. i tester mot ett syntetiskt svar) - annars hämtas de live."""
    if entities is None:
        entities = read_all_entities()

    by_device: dict[str, list[dict]] = {}
    for e in entities:
        if e.get("d"):
            by_device.setdefault(e["d"], []).append(e)

    # --- Bilar: enhet med battery-% + (device_tracker eller känt bilmärke) ---
    cars = []
    car_device_ids = set()
    for device_id, ents in by_device.items():
        battery = next((x for x in ents if x["e"].startswith("sensor.") and x.get("u") == "%"
                         and (x.get("dc") == "battery" or _has(x.get("n"), re.compile(r"battery|batteri|state of charge|soc\b|laddniv", re.I)))), None)
        if not battery:
            continue
        maker = ents[0].get("m") or ""
        if _has(maker, PHONE_MAKERS):
            continue
        tracker = next((x for x in ents if x["e"].startswith("device_tracker.")), None)
        stationary = tracker is None and any(_has(f"{x.get('n') or ''} {x.get('dn') or ''} {x.get('mo') or ''}", STATIONARY_BATTERY)
                                             for x in ents)
        is_car = not stationary and ((tracker is not None) or _has(maker, CAR_MAKERS) or _has(ents[0].get("mo"), CAR_MAKERS))
        if not is_car:
            continue
        plugged = next((x for x in ents if x["e"].startswith("binary_sensor.") and (x.get("dc") == "plug" or _has(x.get("n"), re.compile(r"plugged|ansluten", re.I)))), None)
        climate = next((x for x in ents if x["e"].startswith("climate.")), None)
        driver = "nissan" if _has(maker, re.compile("nissan", re.I)) else "tesla" if _has(maker, re.compile("tesla", re.I)) else "generic_ev"
        car_device_ids.add(device_id)
        cars.append({
            "device_name": ents[0].get("dn") or maker, "maker": maker or None,
            "soc_entity": battery["e"], "plugged_in_entity": plugged["e"] if plugged else None,
            "climate_entity": climate["e"] if climate else None,
            "driver": driver, "driver_known": driver in CAR_DRIVER_REGISTRY,
        })

    # --- Sol: power-sensor som matchar SOLAR och/eller en känd växelriktartillverkare ---
    power = [e for e in entities if e["e"].startswith("sensor.") and e.get("dc") == "power"]
    # Elmätarnas "production"/"produktion" (Tibber Pulse, HomeWizard P1, Husdata ...) är exporten till nätet, inte solen
    # (telemetri 2026-11-07: solar:generic_number@Tibber#Price Sensor). Bara givare från en växelriktartillverkare
    # får komma från en sådan enhet.
    _meter_dev = re.compile(r"tibber|homewizard|husdata|easee equalizer|\bp1\b|\bhan\b|kaifa|aidon|kamstrup|landis", re.I)
    power_sol = [e for e in power
                 if not (_has(_candidate(e), _meter_dev) and not _has(_candidate(e), INVERTER_MAKERS))
                 and not _NOT_PV.search(_measurement_name(e))
                 and (_has(e.get("n"), SOLAR) or _PV_INPUT.search(_measurement_name(e))
                      or _has(_candidate(e), INVERTER_MAKERS))]
    solar_e = max(power_sol, key=_solar_rank, default=None)
    solar = None
    if solar_e:
        selected = _pv_power_selection(power_sol)
        solar_e = max(selected, key=_solar_rank)
        power_ids = [e["e"] for e in selected]
        multi = len(power_ids) > 1
        today_rows = []
        seen_today = set()
        for src in selected:
            row = _today_energy(entities, src.get("d"))
            if row and row["e"] not in seen_today:
                seen_today.add(row["e"])
                today_rows.append(row)
        today_rows.sort(key=lambda e: e["e"])
        today_ids = [e["e"] for e in today_rows]
        today_kwh = today_rows[0] if len(today_rows) == 1 else None
        brand = next((b for b in _SOLAR_BRAND_TO_DRIVER if _has(_candidate(solar_e), re.compile(b, re.I))), None)
        driver = _SOLAR_BRAND_TO_DRIVER.get(brand)
        if multi:
            # Märkesdrivrutinen läser en växelriktare. Flera stycken summeras av den generiska.
            driver = None
        if driver == "solaredge" and not any(e["e"] == _SOLAREDGE_LEGACY_LIMIT for e in entities):
            # Den handbyggda SolarEdge-drivrutinen pekar på entitetsnamn från en äldre HACS-integration.
            # Utan dem: den officiella solaredge_modbus (HA 2026.10+) har "Active power limit" i % på
            # växelriktarens enhet - den generiska drivrutinen nedan räcker och följer entiteterna som finns.
            driver = None
        solar = {
            "pv_power_entity": ", ".join(power_ids) if multi else power_ids[0],
            "today_kwh_entity": (", ".join(today_ids) if len(today_ids) > 1 else today_ids[0]) if today_ids else None,
            "maker": solar_e.get("m"), "driver": driver, "driver_known": driver in SOLAR_DRIVER_REGISTRY,
        }
        if multi:
            solar["note"] = "Flera växelriktare: effekten summeras. En växelriktares strängar tas inte med när den har en egen solgivare."
        if driver is None:
            # Känt märke saknas, men finns en number-entitet för exportgräns på samma
            # enhet kan grundläggande strypning ändå fungera via GenericNumberSolarDriver.
            # Bara en gräns i PROCENT: GenericNumberSolarDriver skriver 0-100 %. En gräns i watt
            # (t.ex. Sungrow-Modbus "Export power limit", Huawei "maximum feed grid power") skulle
            # annars få värdet 0-100 och strypa exporten till ~100 W.
            limit_e = next((e for e in entities if e["e"].startswith("number.") and e.get("d") == solar_e.get("d")
                             and e.get("u") == "%"
                             and _has(e.get("n"), re.compile("export|limit|gräns|power.?limit", re.I))), None)
            suggested = {"pv_power_w": power_ids if multi else power_ids[0]}
            if multi:
                suggested["sum_inverters"] = True
            # En växelriktare: MPPT-moduler summeras när det inte finns en hel solgivare (#139).
            # Flera växelriktare: en givare var, aldrig sträng + total på samma enhet.
            if len(today_ids) > 1:
                suggested["today_kwh"] = today_ids
            elif today_kwh:
                suggested["today_kwh"] = today_kwh["e"]
            if not multi and limit_e:
                suggested["export_limit_pct"] = limit_e["e"]
            elif not multi:
                # Gräns i WATT (t.ex. Sungrow-Modbus): GenericNumberSolarDriver räknar om procent
                # mot entitetens 'max'-attribut, eller mot export_limit_max_w i configen.
                limit_w = next((e for e in entities if e["e"].startswith("number.") and e.get("d") == solar_e.get("d")
                                and e.get("u") == "W"
                                and _has(e.get("n"), re.compile("export|feed|gräns|power.?limit", re.I))), None)
                if limit_w:
                    suggested["export_limit_w"] = limit_w["e"]
            if not multi and _has(_candidate(solar_e), re.compile("huawei", re.I)) and solar_e.get("d"):
                # wlcrs/huawei_solar: exportgränsen styrs via integrationens tjänster mot
                # växelriktarens enhet (drivers/solar_huawei.py), inte via en entitet.
                suggested = {k: v for k, v in suggested.items() if k in ("pv_power_w", "today_kwh")}
                suggested["device_id"] = solar_e["d"]
                solar["generic_suggestion"] = {"driver": "huawei_solar", "entities": suggested}
            else:
                solar["generic_suggestion"] = {"driver": "generic_number", "entities": suggested}

    # --- Elmätare/nätimport: Pulse, smartmätare, eller BÅDA samtidigt (inte
    # antingen-eller) - alla matchande power-sensorer listas, inte bara den första.
    grid_meters = []
    # Delsensorer på samma mätare (t.ex. HomeWizard P1: "Power phase 1", "Battery group power", "Average demand")
    # är inte husets nettoeffekt - förut kunde den första av dem väljas.
    not_total = re.compile(r"phase|fas\b|l[123]\b|battery|batteri|production|produktion|reactive|apparent|average|peak|demand|target", re.I)
    for e in power:
        if e is solar_e or not _has(_candidate(e) + " " + (e.get("n") or ""), GRID) or _has(e.get("n"), not_total):
            continue
        kind = "pulse" if _has(_candidate(e), re.compile("tibber", re.I)) else "smartmätare"
        grid_meters.append({"power_entity": e["e"], "maker": e.get("m"), "kind": kind})
    from homeassistant import detect_tibber_pulse
    pulse = detect_tibber_pulse([e["e"] for e in entities])
    if pulse:
        power_meter = {"driver": "tibber_pulse", "entities": pulse}
    elif grid_meters:
        power_meter = {"driver": "power_w", "entities": {"power_w": grid_meters[0]["power_entity"]}}
        # Strömmen per fas på samma mätare (HomeWizard P1/kWh-mätare: "Current phase 1-3", avstängda som standard
        # i HA) ger säkringsskyddet riktiga ampere. HomeWizard: effekten är + vid köp, - vid export (som vi vill).
        dev = next((e.get("d") for e in entities if e["e"] == grid_meters[0]["power_entity"]), None)
        for ph in (1, 2, 3):
            cur = next((e for e in entities if dev and e.get("d") == dev and e["e"].startswith("sensor.") and e.get("u") == "A"
                        and _has(e.get("n"), re.compile(rf"(current|ström).*(phase|fas|l) ?{ph}\b", re.I))), None)
            if cur:
                power_meter["entities"][f"current_l{ph}"] = cur["e"]
    else:
        power_meter = None

    # --- Värmepump: enhet vars tillverkare/modell/namn matchar HEATPUMP ---
    heat_pump = None
    # Thermia via ThermIQ (thermiq/thermiq_mqtt-ha): entity_id "sensor.thermiq_mqtt_<id>_outdoor_t" m.fl. Känns igen
    # på namnet (integrationen sätter entity_id själv), oavsett enhet - drivers/heatpump_thermiq.py.
    _tiq = next((m.group(1) for m in (re.fullmatch(r"sensor\.(thermiq_mqtt_[a-z0-9_]+?)_outdoor_t", e["e"])
                                       for e in entities) if m), None)
    if _tiq:
        heat_pump = {"device_name": "Thermia (ThermIQ)", "maker": "ThermIQ", "driver": "thermiq",
                     "driver_known": True, "prefix": _tiq,
                     "entity_count": sum(1 for e in entities if f".{_tiq}_" in e["e"]),
                     "note": "Läser och styr via ThermIQ:s HA-integration. Ej verifierad mot en riktig pump - kör i skuggläge först."}
    for device_id, ents in ([] if heat_pump else by_device.items()):
        head = ents[0]
        # #158: en värmepump har temperaturgivare eller en climate-entitet. Nätverksskannrar (t.ex. NetAlertX) gör en
        # "enhet" per pryl i nätverket döpt efter nätverkskortets tillverkare ("Nibe") - den är ingen värmepump.
        if not any(_is_temperature(x) or x["e"].startswith(("climate.", "water_heater.")) for x in ents):
            continue
        # #198/#221: these HA climate controllers have manufacturer metadata rather
        # than a heat-pump brand in the device name. Require climate: these makers
        # also expose fans, air-quality sensors and other non-heating devices.
        known_climate = (_has(head.get("m"), re.compile(r"^(midea|innova|sensibo)\b", re.I))
                         and any(x["e"].startswith("climate.") for x in ents))
        if _has(_candidate(head), HEATPUMP) or known_climate:
            brand = next((b for b in _HEATPUMP_BRAND_TO_DRIVER if _has(_candidate(head), re.compile(b, re.I))), None)
            driver = _HEATPUMP_BRAND_TO_DRIVER.get(brand)
            heat_pump = {
                "device_name": head.get("dn") or head.get("m"), "maker": head.get("m"),
                "driver": driver, "driver_known": driver in HEAT_PUMP_DRIVER_REGISTRY,
                "entity_count": len(ents),
            }
            bt = _nibe_bt_entities(ents) if driver is None else {}
            if bt:
                # NIBE via HA-integration (myUplink, nibe_heatpump): läses via entiteterna, #158
                heat_pump.update({"driver": "ha_entities", "driver_known": True, "entities": bt,
                                  "note": f"{heat_pump['device_name']} via Home Assistant ({len(ents)} entiteter). Läser "
                                          f"{', '.join(sorted(bt))}. Rumsbörvärdet väljs för hand för att styra."})
            elif driver is None:
                # Känt märke saknas, men finns en climate-entitet kan grundläggande
                # prisstyrning ändå fungera via GenericClimateHeatPumpDriver - föreslå
                # det istället för en ren återvändsgränd.
                climate_e = next((e for e in ents if e["e"].startswith("climate.")), None)
                if climate_e:
                    heat_pump["generic_suggestion"] = {"driver": "generic_climate", "entities": {"climate": climate_e["e"]}}
            break
    if heat_pump is None:
        # #162: NIBE-entiteterna kan ligga på en enhet vars namn/tillverkare inte avslöjar en värmepump - leta givarkoder
        # och myUplink-parameternummer bland ALLA temperaturgivare innan vi ger upp
        bt = _nibe_bt_entities([x for x in entities if _is_temperature(x) or x["e"].startswith("number.")])
        if bt:
            heat_pump = {"device_name": "NIBE (Home Assistant)", "maker": "NIBE", "driver": "ha_entities",
                         "driver_known": True, "entities": bt, "entity_count": len(bt),
                         "note": f"NIBE via Home Assistant. Läser {', '.join(sorted(bt))}. Rumsbörvärdet väljs för hand för att styra."}
    if heat_pump is None:
        # HA-skanningen gav inget, men pumpen kan redan prata Modbus DIREKT med smartbox
        # (husets PUMP_IP, går aldrig via HA) - kolla om den faktiskt svarar innan vi ger
        # upp, istället för att visa en onödig återvändsgränd.
        heat_pump = _check_configured_heat_pump()

    # --- Spa: climate/water_heater-entitet, eller enhet, som matchar SPA ---
    spa = None
    spa_e = next((e for e in entities if (e["e"].startswith("climate.") or e["e"].startswith("water_heater.")) and _has(_candidate(e), SPA)), None)
    if spa_e:
        brand = next((b for b in _SPA_BRAND_TO_DRIVER if _has(_candidate(spa_e), re.compile(b, re.I))), None)
        power_e = next((e for e in entities if e["e"].startswith("sensor.") and e.get("dc") == "power" and _has(e.get("n"), SPA)), None)
        driver = _SPA_BRAND_TO_DRIVER.get(brand)
        spa = {
            "current_temp_entity": spa_e["e"], "power_entity": power_e["e"] if power_e else None,
            "maker": spa_e.get("m"), "driver": driver, "driver_known": driver in SPA_DRIVER_REGISTRY,
        }

    # --- Laddare: enhet vars tillverkare/modell/namn matchar kända laddarmärken ---
    chargers = []
    for device_id, ents in by_device.items():
        head = ents[0]
        is_ocpp = (
            any(e["e"].startswith("switch.") and OCPP_SWITCH_SUFFIX.search(e["e"]) for e in ents)
            and any(e["e"].startswith("number.") and OCPP_NUMBER_SUFFIX.search(e["e"]) for e in ents)
        )
        is_cfos = not is_ocpp and _has(_candidate(head), CFOS_POWERBRAIN)
        if not (_has(_candidate(head), CHARGER_MAKERS) or is_ocpp or is_cfos):
            continue
        cfos_entities = _cfos_charger_entities(ents) if is_cfos else None
        if is_cfos and not cfos_entities:
            continue  # do not classify a cFos meter/hub or guess incomplete control mappings
        status_e = next((e for e in ents if e["e"].startswith("sensor.") and _has(e.get("n"), re.compile("status", re.I))), None)
        if cfos_entities:
            status_e = next(e for e in ents if e["e"] == cfos_entities["status"])
        if not status_e:
            # Ingen statussensor = sannolikt integrationens egen konto-/hubb-enhet (t.ex.
            # Easees molnkonto som en egen "enhet" i HA:s register), inte en fysisk laddare -
            # en riktig laddare har alltid en statussensor. Bekräftat live: en sån hubb-enhet
            # hade bara 1 entitet totalt, mot 19-20 för de riktiga laddarna.
            continue
        brand = next((b for b in _CHARGER_BRAND_TO_DRIVER if _has(_candidate(head), re.compile(b, re.I))), None)
        driver = _CHARGER_BRAND_TO_DRIVER.get(brand)
        charger = {
            "device_name": head.get("dn") or head.get("m"), "maker": head.get("m"),
            "status_entity": status_e["e"] if status_e else None,
            "driver": driver, "driver_known": driver in CHARGER_DRIVER_REGISTRY,
        }
        if cfos_entities:
            charger["generic_suggestion"] = {"driver": "generic", "entities": cfos_entities}
            chargers.append(charger)
            continue
        if driver == "easee":
            charger.update(_easee_mapping(ents, status_e))
        if driver is None:
            # Känt märke saknas, men finns en switch-entitet kan grundläggande på/av-
            # styrning ändå fungera via GenericChargerDriver - föreslå det istället för
            # en ren återvändsgränd. Strömgräns (number) är valfri, inte ett krav.
            switch_e = next((e for e in ents if e["e"].startswith("switch.")), None)
            if switch_e:
                suggested = {"switch": switch_e["e"]}
                if status_e:
                    suggested["status"] = status_e["e"]
                if is_ocpp:
                    # OCPP: sessionens strömgräns - ALDRIG laddboxens bestående maximum_current (SpotNav-lärdom).
                    number_e = next((e for e in ents if e["e"].startswith("number.") and OCPP_SESSION_LIMIT.search(e["e"])), None)
                    imp = next((e for e in ents if e["e"].startswith("sensor.") and re.search(r"current_import$", e["e"])), None)
                    if imp:
                        suggested["current_import"] = imp["e"]
                    sw = next((e for e in ents if e["e"].startswith("switch.") and OCPP_SWITCH_SUFFIX.search(e["e"])), None)
                    if sw:
                        suggested["switch"] = sw["e"]
                    st = next((e for e in ents if e["e"].startswith("sensor.") and re.search(r"status_connector$", e["e"])), None)
                    if st:
                        suggested["status"] = st["e"]
                else:
                    number_e = next((e for e in ents if e["e"].startswith("number.")
                                      and _has(e.get("n"), re.compile("current|ström|limit|gräns", re.I))
                                      and not OCPP_STATION_MAX.search(e["e"])), None)
                if number_e:
                    suggested["current_limit"] = number_e["e"]
                charger["generic_suggestion"] = {"driver": "generic", "entities": suggested}
        chargers.append(charger)

    # --- Husbatteri: känt märke, ELLER en battery-%-sensor på en enhet som inte redan
    # är en bil (viktig avgränsning - en bils batteriprocent ska aldrig feltolkas som
    # ett husbatteri). Ingen märkesspecifik drivrutin finns eller planeras (Predbat
    # underhåller redan den kompatibiliteten) - föreslår alltid "generic".
    battery, battery_candidates = None, []
    for device_id, ents in by_device.items():
        if device_id in car_device_ids:
            continue
        head = ents[0]
        maker = head.get("m") or ""
        _has_bat_power = any(x["e"].startswith("sensor.") and x.get("dc") == "power" and _has(x.get("n"), re.compile(r"battery|batteri", re.I))
                             for x in ents)
        if _has(maker, PHONE_MAKERS) and not _has_bat_power:   # Huawei gör både telefoner och LUNA-batterier
            continue
        is_known_brand = _has(_candidate(head), BATTERY_MAKERS)
        soc_e = next((x for x in ents if x["e"].startswith("sensor.") and x.get("u") == "%"
                      and (x.get("dc") == "battery" or _has(x.get("n"), re.compile(r"battery|batteri|state of charge|soc\b", re.I)))), None)
        power_e = next((x for x in ents if x["e"].startswith("sensor.") and x.get("dc") == "power"
                        and _has(x.get("n"), re.compile(r"battery|batteri", re.I))), None) \
            or next((x for x in ents if x["e"].startswith("sensor.") and x.get("dc") == "power"), None)
        # Ett eget batteri-%-värde räcker INTE ensamt (bekräftat live: en vanlig
        # temperatur-/fuktgivare med eget myntcellsbatteri gav en falsk träff) - kräver
        # också en effektsensor, om inget känt husbatterimärke redan matchat.
        if not is_known_brand and not (soc_e and power_e):
            continue
        # Bekräftat live: SolarEdges integration skapar ALLTID en "Lagringsnivå"-sensor
        # (på en egen enhet, inte ens växelriktarens - ett antagande om samma enhet
        # höll INTE) oavsett om man faktiskt har batteri - state blir "unknown" utan
        # ett. Ett SOC-värde vi inte ens kan läsa är inget att visa som "hittat".
        if soc_e and soc_e.get("st") in (None, "unknown", "unavailable"):
            continue
        battery = {
            "device_name": head.get("dn") or maker, "maker": maker or None,
            "soc_entity": soc_e["e"] if soc_e else None, "power_entity": power_e["e"] if power_e else None,
            "driver": None, "driver_known": False,
        }
        if soc_e or power_e:
            suggested = {}
            if soc_e:
                suggested["soc"] = soc_e["e"]
            if power_e:
                suggested["power"] = power_e["e"]
            battery["generic_suggestion"] = {"driver": "generic", "entities": suggested}
            split = _split_battery_power(ents)
            if split:                                       # laddning/urladdning var för sig går före en ensam effekt
                battery["generic_suggestion"]["entities"].pop("power", None)
                battery["generic_suggestion"]["entities"].update(split)
            preset = _battery_control_preset(ents, entities)
            if preset:
                if "power_charge" in preset["entities"]:
                    battery["generic_suggestion"]["entities"].pop("power", None)
                battery["generic_suggestion"]["entities"].update(preset["entities"])
                battery["generic_suggestion"]["modes"] = preset["modes"]
                battery["generic_suggestion"]["preset"] = preset["name"]
                battery["control_preset"] = preset["name"]
                if preset.get("note"):
                    battery["note"] = preset["note"]
                if preset.get("keepalive_s"):
                    battery["generic_suggestion"]["keepalive_s"] = preset["keepalive_s"]
        # En hybridväxelriktare utan inkopplat batteri (t.ex. Growatt/Solax med bara solceller) visar ofta
        # batterisensorer som står på 0 % och 0 W. Det är inget batteri att föreslå (samma fel som srcfl/ftw#1669).
        def _num(x):
            try:
                return float(x.get("st")) if x else None
            except (TypeError, ValueError):
                return None
        if not is_known_brand and soc_e and _num(soc_e) == 0 and _num(power_e) in (0, None):
            battery["maybe_absent"] = True
            battery["note"] = "Laddnivå 0 % och ingen effekt - troligen inget batteri inkopplat på den här växelriktaren."
        battery_candidates.append(battery)
    # Kandidater som troligen saknar batteri föreslås inte
    battery_candidates = [b for b in battery_candidates if not b.get("maybe_absent")]
    if not battery_candidates:
        sg = _sungrow_mkaiser(entities)
        if sg:
            battery_candidates.append(sg)
    # Flera träffar (t.ex. Solis/Fronius-växelriktaren OCH en BYD-integration som bara läser): välj den som går att
    # styra - batteriet laddas alltid via växelriktaren. Annars den första, som förut.
    battery = next((b for b in battery_candidates if (b.get("generic_suggestion") or {}).get("modes")),
                   battery_candidates[0] if battery_candidates else None)
    # Flera växelriktare/batteribankar av samma märke (issue #86: två Solax Gen2 med var sitt Pylontech-batteri) blir ETT
    # batteri: laddnivån vägs ihop, effekten summeras (drivers/battery_generic.py). Förinställningen styr redan alla
    # växelriktarnas lägen (t.ex. Gen2 byter Charger Use Mode på båda); bankarnas storlek fylls i av användaren.
    if battery and battery.get("maker") and battery.get("soc_entity"):
        same = [b for b in battery_candidates if b is not battery and b.get("maker") == battery["maker"] and b.get("soc_entity")
                and b.get("control_preset") == battery.get("control_preset")]
        if same:
            banks = [battery] + same
            gs = battery.setdefault("generic_suggestion", {"driver": "generic", "entities": {}})
            ents = gs.setdefault("entities", {})
            ents["soc"] = [b["soc_entity"] for b in banks]
            pw = [b.get("power_entity") for b in banks]
            if all(pw) and "power_charge" not in ents:
                ents["power"] = pw
            battery["banks"] = [b.get("device_name") for b in banks]
            battery["soc_entity"] = ", ".join(ents["soc"])
            if isinstance(ents.get("power"), list):
                battery["power_entity"] = ", ".join(ents["power"])
            battery["note"] = ((battery.get("note") or "") + f" {len(banks)} växelriktare/batteribankar räknas som ett batteri "
                               f"({', '.join(battery['banks'])}). Fyll i varje banks storlek (bank_kwh) så vägs laddnivån rätt.").strip()

    # Alla effektsensorer, för fritt val av elmätare (issue #86: en IAMMETER för hela huset hittas inte som "nätmätare")
    power_sensors = sorted(({"entity": e["e"], "name": e.get("n") or e["e"], "unit": e.get("u"), "state": e.get("st")}
                            for e in entities if e["e"].startswith("sensor.") and (e.get("dc") == "power" or e.get("u") in ("W", "kW"))),
                           key=lambda x: x["name"].lower())
    hint = ftw_control_suggestion(battery, solar)
    if hint:
        target = battery if battery is not None else solar
        if isinstance(target, dict):
            prev = str(target.get("note") or "").strip()
            target["note"] = (prev + " " + hint["note"]).strip()
    # Status sensors can contain text (e.g. NIBE "Kör"/"Från"). They must not
    # be limited to numeric temperature/power candidates in the setup wizard.
    compressor_sensors = sorted((
        {"entity": e["e"], "name": e.get("n") or e["e"], "state": e.get("st")}
        for e in entities if e["e"].split(".")[0] in ("sensor", "binary_sensor")
        and re.search(r"kompressor|compressor|43427", f"{e.get('n') or ''} {e['e']}", re.I)
    ), key=lambda e: e["name"].lower())
    found = {"cars": cars, "heat_pump": heat_pump, "solar": solar, "spa": spa, "chargers": chargers,
             "compressor_sensors": compressor_sensors,
             "grid_meters": grid_meters, "power_meter": power_meter, "battery": battery, "power_sensors": power_sensors}
    if hint:
        found["ftw_suggestion"] = hint
    return found
