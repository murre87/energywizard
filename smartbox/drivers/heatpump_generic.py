"""GenericClimateHeatPumpDriver: grundläggande prisbaserad rumstemperaturstyrning för
VILKEN värmepump/termostat som helst exponerad som en HA climate-entitet - utan att
kräva en handbyggd, registernivå-drivrutin per märke. Husdata/Thermia-drivrutinens
finlir (vattenstopp-temp, värmekurva, rumsgivarinflytande) har ingen generisk
motsvarighet i HA:s climate-domän - de metoderna returnerar ärligt False istället för
att gissa eller tyst ignorera, med en lograd varning EN gång (inte varje minut)."""
import homeassistant
from drivers.heatpump import HeatPumpDriver


class GenericClimateHeatPumpDriver(HeatPumpDriver):
    """Default för värmepumpar/termostater utan egen drivrutin. Kräver bara en
    climate-entitet - all styrning går via HA:s generiska climate.set_temperature."""
    def __init__(self, entity_id: str | None = None):
        self._entity = entity_id
        self._warned = set()

    def _warn_unsupported(self, method: str):
        if method not in self._warned:
            print(f"⚠️ GenericClimateHeatPumpDriver: {method} stöds inte för en generisk "
                  f"climate-entitet (ingen registernivå-åtkomst) - ignoreras.")
            self._warned.add(method)

    def read_sensors(self) -> dict:
        if not self._entity:
            return {}
        return {
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
