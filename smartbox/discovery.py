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

import re

import requests

import homeassistant
from house_config import (
    CAR_DRIVER_REGISTRY, CHARGER_DRIVER_REGISTRY, HEAT_PUMP_DRIVER_REGISTRY,
    SOLAR_DRIVER_REGISTRY, SPA_DRIVER_REGISTRY,
)

# --- Kategori-regexer, portade från Familjetavlas discovery.ts ---
CAR_MAKERS = re.compile(r"tesla|nissan|volvo|polestar|kia|hyundai|volkswagen|vw|skoda|audi|bmw|mini|mercedes|renault|peugeot|citro|opel|toyota|lexus|ford|byd|porsche|cupra|seat|fiat|jaguar|zeekr|xpeng|nio|honda|mazda|subaru|smart", re.I)
PHONE_MAKERS = re.compile(r"^(samsung|apple|google|oneplus|xiaomi|huawei|oppo|motorola|sony|nokia|nothing|fairphone|realme|vivo|honor)\b", re.I)
SOLAR = re.compile(r"solar|sol(el|ar)?\b|pv\b|photovolt|inverter|växelriktare|produktion|production|yield", re.I)
INVERTER_MAKERS = re.compile(r"solaredge|huawei|fronius|sma\b|growatt|enphase|goodwe|solis|sungrow|deye|victron|ferroamp|solax|kostal|apsystems", re.I)
HEATPUMP = re.compile(r"husdata|h60|h66|nibe|thermia|ivt|ctc|bosch|daikin|mitsubishi|panasonic|vaillant|viessmann|heat ?pump|värmepump|bergvärme|luft.?vatten|ecoforest|qvantum|nordic", re.I)
SPA = re.compile(r"balboa|gecko|spa\b|spabad|jacuzzi|hot ?tub|bubbelpool|lay-?z|intex|softub|arctic spa|bwa", re.I)
CHARGER_MAKERS = re.compile(r"easee|zaptec|wallbox|charge ?amps|garo|ctek|go-?e|webasto|ensto|defa", re.I)
# Nätimport/elmätare: ett hus kan ha Tibber Pulse, en smartmätare (HAN/P1-port) eller
# båda samtidigt - inte antingen-eller (Emils egen poäng, 2026-10-30). Ingen av dem är
# idag en pluggbar drivrutin i EnergyWizard (main.py läser Tibber Pulse hårdkodat via
# TIBBER_ENTITIES i homeassistant.py) - visas här bara informativt tills det blir det.
GRID = re.compile(r"tibber pulse|p1\b|han\b|power ?meter|elmätare|smart ?meter|nätimport|grid import|consumption", re.I)

# Märke -> drivrutinsnyckel, bara för märken som FAKTISKT har en registrerad
# drivrutin idag. Ett hittat märke som inte finns här flaggas som "ingen
# drivrutin än" istället för att tyst väljas fel eller gömmas.
_HEATPUMP_BRAND_TO_DRIVER = {"husdata": "thermia_husdata", "thermia": "thermia_husdata"}
_SOLAR_BRAND_TO_DRIVER = {"solaredge": "solaredge"}
_SPA_BRAND_TO_DRIVER = {"gecko": "gecko", "balboa": "gecko"}  # Gecko-drivrutinen är byggd mot Balboa-liknande styrsystem
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
      "st": s.state
  }] %}
{% endfor %}
{{ ns.out | tojson }}"""


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
    for device_id, ents in by_device.items():
        battery = next((x for x in ents if x["e"].startswith("sensor.") and x.get("u") == "%"
                         and (x.get("dc") == "battery" or _has(x.get("n"), re.compile(r"battery|batteri|state of charge|soc\b|laddniv", re.I)))), None)
        if not battery:
            continue
        maker = ents[0].get("m") or ""
        if _has(maker, PHONE_MAKERS):
            continue
        tracker = next((x for x in ents if x["e"].startswith("device_tracker.")), None)
        is_car = (tracker is not None) or _has(maker, CAR_MAKERS) or _has(ents[0].get("mo"), CAR_MAKERS)
        if not is_car:
            continue
        plugged = next((x for x in ents if x["e"].startswith("binary_sensor.") and (x.get("dc") == "plug" or _has(x.get("n"), re.compile(r"plugged|ansluten", re.I)))), None)
        climate = next((x for x in ents if x["e"].startswith("climate.")), None)
        driver = "nissan" if _has(maker, re.compile("nissan", re.I)) else "tesla" if _has(maker, re.compile("tesla", re.I)) else "generic_ev"
        cars.append({
            "device_name": ents[0].get("dn") or maker, "maker": maker or None,
            "soc_entity": battery["e"], "plugged_in_entity": plugged["e"] if plugged else None,
            "climate_entity": climate["e"] if climate else None,
            "driver": driver, "driver_known": driver in CAR_DRIVER_REGISTRY,
        })

    # --- Sol: power-sensor som matchar SOLAR och/eller en känd växelriktartillverkare ---
    power = [e for e in entities if e["e"].startswith("sensor.") and e.get("dc") == "power"]
    solar_e = next((e for e in power if _has(e.get("n"), SOLAR) and _has(_candidate(e), INVERTER_MAKERS)), None) \
        or next((e for e in power if _has(e.get("n"), SOLAR) or _has(_candidate(e), INVERTER_MAKERS)), None)
    solar = None
    if solar_e:
        brand = next((b for b in _SOLAR_BRAND_TO_DRIVER if _has(_candidate(solar_e), re.compile(b, re.I))), None)
        today_kwh = next((e for e in entities if e["e"].startswith("sensor.") and e.get("u") in ("kWh", "Wh")
                           and e.get("d") == solar_e.get("d") and _has(e.get("n"), re.compile("today|idag|dag", re.I))), None)
        driver = _SOLAR_BRAND_TO_DRIVER.get(brand)
        solar = {
            "pv_power_entity": solar_e["e"], "today_kwh_entity": today_kwh["e"] if today_kwh else None,
            "maker": solar_e.get("m"), "driver": driver, "driver_known": driver in SOLAR_DRIVER_REGISTRY,
        }

    # --- Elmätare/nätimport: Pulse, smartmätare, eller BÅDA samtidigt (inte
    # antingen-eller) - alla matchande power-sensorer listas, inte bara den första.
    grid_meters = []
    for e in power:
        if e is solar_e or not _has(_candidate(e) + " " + (e.get("n") or ""), GRID):
            continue
        kind = "pulse" if _has(_candidate(e), re.compile("tibber", re.I)) else "smartmätare"
        grid_meters.append({"power_entity": e["e"], "maker": e.get("m"), "kind": kind})

    # --- Värmepump: enhet vars tillverkare/modell/namn matchar HEATPUMP ---
    heat_pump = None
    for device_id, ents in by_device.items():
        head = ents[0]
        if _has(_candidate(head), HEATPUMP):
            brand = next((b for b in _HEATPUMP_BRAND_TO_DRIVER if _has(_candidate(head), re.compile(b, re.I))), None)
            driver = _HEATPUMP_BRAND_TO_DRIVER.get(brand)
            heat_pump = {
                "device_name": head.get("dn") or head.get("m"), "maker": head.get("m"),
                "driver": driver, "driver_known": driver in HEAT_PUMP_DRIVER_REGISTRY,
                "entity_count": len(ents),
            }
            break

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
        if not _has(_candidate(head), CHARGER_MAKERS):
            continue
        status_e = next((e for e in ents if e["e"].startswith("sensor.") and _has(e.get("n"), re.compile("status", re.I))), None)
        brand = next((b for b in _CHARGER_BRAND_TO_DRIVER if _has(_candidate(head), re.compile(b, re.I))), None)
        driver = _CHARGER_BRAND_TO_DRIVER.get(brand)
        chargers.append({
            "device_name": head.get("dn") or head.get("m"), "maker": head.get("m"),
            "status_entity": status_e["e"] if status_e else None,
            "driver": driver, "driver_known": driver in CHARGER_DRIVER_REGISTRY,
        })

    return {"cars": cars, "heat_pump": heat_pump, "solar": solar, "spa": spa, "chargers": chargers, "grid_meters": grid_meters}
