"""Gecko-spabadet via Home Assistant (steg 5b av uppdelningen): temperaturer, effekt, aktiviteter, måltemperatur, Economy Mode och
smartpluggen. Förut låg koden i homeassistant.py."""
from drivers.host import homeassistant as ha


def _as_list(v):
    if v in (None, ""):
        return []
    return [x for x in (v if isinstance(v, (list, tuple)) else [v]) if x]


def read(entities=None):
    """Spabadets temperaturer och värmarens läge. entities (spa.entities): current_temp, target_temp (sensorer),
    climate (climate-entiteten - dess temperature-attribut är den sanna måltemperaturen), water_heater, economy_mode."""
    e = entities or {}
    data = {k: (ha._get_numeric_state(e[k]) if e.get(k) else None) for k in ("current_temp", "target_temp", "economy_mode")}
    # En climate- eller water_heater-entitet som "temperatur" (så skrev upptäckten förut, #570): dess tillstånd är text ("heat"),
    # temperaturen ligger i attributen current_temperature (vattnet) och temperature (målet).
    for _key, _attr in (("current_temp", "current_temperature"), ("target_temp", "temperature")):
        if e.get(_key) and str(e[_key]).split(".", 1)[0] in ("climate", "water_heater"):
            _v = ha._get_numeric_attribute(e[_key], _attr)
            data[_key] = float(_v) if _v is not None else None
    if e.get("climate"):
        t = ha._get_numeric_attribute(e["climate"], "temperature")
        if t is not None:
            data["target_temp"] = float(t)
        if data["current_temp"] is None:
            data["current_temp"] = ha._get_numeric_attribute(e["climate"], "current_temperature")
    data["heater_state"] = ha._get_raw_state(e["water_heater"]) if e.get("water_heater") else None
    return data


def read_power(entities=None):
    """Spabadets effekt. entities: power_phases (lista med en sensor per fas) eller power_w (en sensor). Värdena tas
    som belopp (en CT-klämma åt fel håll ger negativt). safety: {nyckel: binary_sensor} - overcurrent, overvoltage,
    overheated, power_exceeded. Returnerar per-fas + total effekt (W) och säkerhetsflaggorna."""
    e = entities or {}

    def _abs(eid):
        v = ha._get_numeric_state(eid) if eid else None
        return abs(float(v)) if v is not None else None
    phases = [_abs(x) for x in _as_list(e.get("power_phases"))[:3]]
    phases += [None] * (3 - len(phases))
    present = [x for x in phases if x is not None]
    total = sum(present) if present else (_abs(e.get("power_w")) if e.get("power_w") else None)
    safety = e.get("safety") or {}
    out = {'phase_a_w': phases[0], 'phase_b_w': phases[1], 'phase_c_w': phases[2], 'total_w': total}
    for k in ('overcurrent', 'overvoltage', 'overheated', 'power_exceeded'):
        out[k] = bool(safety.get(k)) and str(ha._get_raw_state(safety[k])).lower() == 'on'
    return out


def read_activities(entities=None):
    """Vilka av spabadets funktioner som är PÅ just nu - entities.activities: {namn: entitet}, t.ex. heating,
    circ_pump, pump1, blower, waterfall, lights, ozone. Används för att lära sig vilken fas som driver vad."""
    def _on(eid):
        return str(ha._get_raw_state(eid)).lower() in ('on', 'heating', 'true')
    return {k: _on(v) for k, v in ((entities or {}).get("activities") or {}).items() if v}


def set_economy(enable: bool, entity: str | None = None):
    """Slår på eller av Economy Mode för Spabadet via HA (spa.entities.economy_mode)."""
    if not entity:
        return False
    try:
        ha.post_service(f"switch/turn_{'on' if enable else 'off'}", {"entity_id": entity}, 5)
        print(f"🛁 Spabad: Economy Mode {'AKTIVERAT' if enable else 'AVAKTIVERAT'}")
        return True
    except Exception as e:
        ha.report_failure(f"Spabad: Fel vid ändring av Economy Mode: {e}", e)
        return False


def set_target(temp: float, entity: str | None = None):
    """Sätter spabadets måltemperatur via HA (spa.entities.climate)."""
    if not entity:
        return False
    try:
        ha.post_service("climate/set_temperature", {"entity_id": entity, "temperature": float(temp)}, 5)
        print(f"🛁 Spabad: Måltemperatur satt till {temp}°C")
        return True
    except Exception as e:
        ha.report_failure(f"Spabad: Fel vid sättning av temp: {e}", e)
        return False


def toggle_plug(turn_on: bool, entity: str | None = None):
    """Slår på eller av strömmen till spabadets smartplug (spa.entities.smart_plug)."""
    if not entity:
        return False
    service = "turn_on" if turn_on else "turn_off"
    try:
        ha.post_service(f"switch/{service}", {"entity_id": entity}, 5)
        return True
    except Exception as e:
        ha.report_failure(f"Fel vid styrning av spabadets plugg: {e}", e)
        return False
