"""spa_entities.py - Gecko-spabadets entiteter ur Home Assistants entiteter (#570).

HA:s Gecko-integration ger ett bad flera entiteter med samma namnstam: climate.<bad>_heater (måltemperaturen och, som
attribut, vattnets temperatur), sensor.<bad>_current_temperature, sensor.<bad>_target_temperature, water_heater.<bad>_heater
och switch.<bad>_economy_mode. Upptäckten kopplade förut bara en av dem (climate-entiteten som "temperatur") och drivrutinen
behöver flera, så ett bad som upptäcktes automatiskt visade ingen temperatur och gick inte att styra.

complete_gecko() fyller i det som saknas ur HA:s entiteter via namnstammen, och skriver aldrig över något som redan är valt
(en användares egen konfiguration vinner). Ren logik, testas i tests/test_spa_entities.py. Entiteter EnergyWizard själv
publicerar (smartbox_*, energywizard_*) är aldrig kandidater: de är vår egen utdata, inte badets."""
from __future__ import annotations

import re

_STEM_SUFFIX = re.compile(r"_(heater|climate|thermostat|water_heater)$")
_CURRENT = re.compile(r"(current|water|actual).*temp|^temp(erature)?$|aktuell|vattentemp", re.I)
_TARGET = re.compile(r"(target|set_?point|desired).*temp|^target|^set_?point|mål ?temp|börvärde", re.I)
_ECONOMY = re.compile(r"econom|^eco(_|$)|ekonomi", re.I)
_IN_USE = re.compile(r"in_use|spa in use|i bruk", re.I)
_ERROR = re.compile(r"(^|_)error(_|s|$)|^fel|alarm|fault", re.I)       # Gecko: sensor.<bad>_error_s (felkod som text)
OWN_PREFIXES = ("smartbox_", "energywizard_")


_ID_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_")


def valid_entity_id(value) -> bool:
    """domän.objekt med små bokstäver, siffror och understreck, högst 120 tecken. Linjär kontroll i stället för ett reguljärt
    uttryck: värdet kommer från webbläsaren, och ``[a-z_]+\\.[a-z0-9_]+`` på en lång sträng utan punkt tar polynomisk tid
    (CodeQL, #574)."""
    if not isinstance(value, str) or not 3 <= len(value) <= 120 or value.count(".") != 1:
        return False
    domain, obj = value.split(".")
    return bool(domain) and bool(obj) and set(domain) <= _ID_CHARS and not domain[0].isdigit() and set(obj) <= _ID_CHARS


def domain_of(entity_id: str) -> str:
    return entity_id.split(".", 1)[0] if "." in (entity_id or "") else ""


def object_id(entity_id: str) -> str:
    return entity_id.split(".", 1)[1] if "." in (entity_id or "") else (entity_id or "")


def is_own(entity_id: str) -> bool:
    """EnergyWizards egna publicerade entiteter (de får aldrig väljas som en källa)."""
    return object_id(entity_id).startswith(OWN_PREFIXES)


def _without_own(value):
    """EnergyWizards egna entiteter tas bort ur en konfiguration (en sträng eller en lista): en äldre upptäckt kan ha valt
    sensor.smartbox_effekt_spa som spabadets effektkälla, och då matas vår egen utdata tillbaka in som indata."""
    if isinstance(value, str):
        return None if is_own(value) else value
    if isinstance(value, list):
        return [v for v in value if not (isinstance(v, str) and is_own(v))]
    return value


def stem_of(entity_id: str) -> str:
    """climate.erik_spa_heater -> erik_spa"""
    return _STEM_SUFFIX.sub("", object_id(entity_id))


def complete_gecko(entities: dict | None, names: dict | None, devices: dict | None = None) -> dict:
    """entities: spa.entities (kan vara ofullständig). names: {entity_id: friendly_name} för alla entiteter i HA.
    devices: {entity_id: enhets-id} när det är känt (upptäckten har det): entiteter i SAMMA enhet som climate-entiteten är
    syskon även om någon döpt om dem så att namnstammarna skiljer (en fungerande installation har climate.spabad_heater men
    sensor.spa_xxx_current_temperature). Utan enhets-id, och som komplement, används namnstammen.
    Returnerar en kopia där climate, current_temp, target_temp, water_heater, economy_mode och error (felkodssensorn) är ifyllda när de går att
    hitta. En entitet som redan är vald ändras aldrig, utom att en current_temp som är en climate-entitet (en text, inte en
    siffra) ersätts av en riktig temperatursensor om en finns."""
    e = {k: _without_own(v) for k, v in (entities or {}).items()}
    e = {k: v for k, v in e.items() if v not in (None, "", [])}
    names = names or {}
    anchor = e.get("climate") or next((e[k] for k in ("current_temp", "water_heater") if domain_of(e.get(k) or "") in ("climate", "water_heater")), None)
    if not anchor:
        return e
    if not e.get("climate") and domain_of(anchor) == "climate":
        e["climate"] = anchor
    stem = stem_of(anchor)
    if not stem:
        return e
    dev = (devices or {}).get(anchor)
    same_device = [i for i in names if dev and (devices or {}).get(i) == dev and i != anchor and not is_own(i)]
    by_stem = [i for i in names if object_id(i).startswith(stem + "_") and not is_own(i) and i not in same_device]
    siblings = same_device + by_stem

    def rest(i: str) -> str:
        oid = object_id(i)
        return oid[len(stem) + 1:] if oid.startswith(stem + "_") else oid      # en omdöpt entitet: hela id:t

    def pick(domain: str, want: re.Pattern, avoid: re.Pattern | None = None):
        for i in siblings:
            if domain_of(i) != domain:
                continue
            text = f"{rest(i)} {names.get(i) or ''}"[:300]          # namnen kan döpas fritt i HA: korta dem före matchningen
            if avoid and avoid.search(text):
                continue
            if want.search(text):
                return i
        return None

    cur = e.get("current_temp")
    if not cur or domain_of(cur) != "sensor":
        found = pick("sensor", _CURRENT, _TARGET)
        if found:
            e["current_temp"] = found
    if not e.get("target_temp"):
        found = pick("sensor", _TARGET)
        if found:
            e["target_temp"] = found
    if not e.get("water_heater"):
        found = next((i for i in siblings if domain_of(i) == "water_heater"), None)
        if found:
            e["water_heater"] = found
    if not e.get("economy_mode"):
        found = pick("switch", _ECONOMY)
        if found:
            e["economy_mode"] = found
    if not e.get("in_use"):
        found = pick("binary_sensor", _IN_USE)
        if found:
            e["in_use"] = found
    if not e.get("error"):
        found = pick("sensor", _ERROR)
        if found:
            e["error"] = found
    return e
