"""GenericClimateHeatPumpDriver: grundläggande prisbaserad rumstemperaturstyrning för
VILKEN värmepump/termostat som helst exponerad som en HA climate-entitet - utan att
kräva en handbyggd, registernivå-drivrutin per märke. Husdata/Thermia-drivrutinens
finlir (vattenstopp-temp, värmekurva, rumsgivarinflytande) har ingen generisk
motsvarighet i HA:s climate-domän - de metoderna returnerar ärligt False istället för
att gissa eller tyst ignorera, med en lograd varning EN gång (inte varje minut)."""
from drivers.host import homeassistant
from drivers.heatpump import HeatPumpDriver


class GenericClimateHeatPumpDriver(HeatPumpDriver):
    """Default för värmepumpar/termostater utan egen drivrutin. Kräver bara en
    climate-entitet - all styrning går via HA:s generiska climate.set_temperature."""
    _EXTRA = ("outdoor_temp", "forward_temp", "return_temp", "water_temp", "degree_minutes")

    def __init__(self, entity_id: str | None = None, entities: dict | None = None):
        self._entity = entity_id
        self._warned = set()
        # #577: övriga givare som användaren lagt under heat_pump.entities (ute, framledning, retur, varmvatten, effekt) lästes
        # aldrig, trots att de stod i konfigurationen. De läses nu när de finns; utan dem är beteendet som förut.
        e = {k: v for k, v in (entities or {}).items() if isinstance(v, str) and "." in v}
        self._extra = {k: e[k] for k in self._EXTRA if k in e}
        if e.get("indoor_temp"):
            self._extra["indoor_temp"] = e["indoor_temp"]
        pw = (entities or {}).get("power_w")
        self._power = [x.strip() for x in (pw if isinstance(pw, list) else str(pw or "").split(",")) if "." in str(x)]

    def _power_w(self):
        """Summan av effektgivarna i W (W eller kW enligt givarens enhet), eller None om ingen svarar."""
        total, seen = 0.0, False
        for ent in self._power:
            v = homeassistant._get_numeric_state(ent)
            if not isinstance(v, (int, float)) or v != v:
                continue
            unit = str(((homeassistant._states_cache.get(ent) or {}).get("attributes") or {}).get("unit_of_measurement") or "").lower()
            total += v * 1000.0 if unit == "kw" else v
            seen = True
        return round(total, 1) if seen else None

    def _warn_unsupported(self, method: str):
        if method not in self._warned:
            print(f"⚠️ GenericClimateHeatPumpDriver: {method} stöds inte för en generisk "
                  f"climate-entitet (ingen registernivå-åtkomst) - ignoreras.")
            self._warned.add(method)

    def read_room_target(self):
        """Climate-entitetens börvärde (attributet temperature)."""
        if not self._entity:
            return None
        v = homeassistant._get_numeric_attribute(self._entity, "temperature")
        return float(v) if isinstance(v, (int, float)) and v == v else None

    def _num(self, key):
        v = homeassistant._get_numeric_state(self._extra[key]) if key in self._extra else None
        return float(v) if isinstance(v, (int, float)) and v == v else None

    def read_sensors(self) -> dict:
        if not self._entity:
            return {}
        out = {
            "indoor_temp": homeassistant._get_numeric_attribute(self._entity, "current_temperature"),
            "outdoor_temp": None,
            "forward_temp": None,
            "return_temp": None,
            "water_temp": None,
            "degree_minutes": None,
            "compressor_running": None,
            "compressor_power_kw": None,
            "operating_mode": homeassistant._get_raw_state(self._entity),
        }
        for key in self._extra:
            v = self._num(key)
            if v is not None:
                out[key] = v
        if self._power:
            out["compressor_power_w"] = self._power_w()
        return out

    # HA:s hvac-lägen -> Matter-lika lägen (drivers.heatpump.MODES); dry/fan_only har ingen motsvarighet
    _HA_MODES = {"off": "off", "heat": "heat", "cool": "cool", "auto": "auto", "heat_cool": "auto"}

    def _state_extra(self, sensors: dict) -> dict:
        return {"mode": self._HA_MODES.get(sensors.get("operating_mode"))}

    def set_room_temp(self, target_c: float) -> bool:
        if not self._entity:
            return False
        return homeassistant.set_climate_temperature(self._entity, target_c)

    def set_water_stop_temp(self, target_c: float) -> bool:
        self._warn_unsupported("set_water_stop_temp")
        return False

    def set_water_start_temp(self, target_c: float) -> bool:
        self._warn_unsupported("set_water_start_temp")
        return False

    def set_heating_start_temp(self, target_c: float) -> bool:
        self._warn_unsupported("set_heating_start_temp")
        return False

    def set_operating_mode(self, mode) -> bool:
        self._warn_unsupported("set_operating_mode")
        return False
