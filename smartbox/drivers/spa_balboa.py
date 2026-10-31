"""BalboaSpaDriver: för HA:s officiella `balboa`-integration (home-assistant.io/
integrations/balboa/) - till skillnad från Gecko använder den uteslutande STANDARD
HA-domäner (climate/select/switch/fan), inte en egen rå protokolltolkning. Byggd mot
integrationens EGEN dokumenterade entitetsform (climate för temp, select för låg/hög
temperaturområde, switch för filtercykel, fan för pumpar/jets) - inte reverse-
engineerad eller gissad.

VIKTIGT, ärligt: aldrig verifierad mot ett riktigt Balboa-system (ingen betatestare
har ett) - bara mockade tester mot integrationens dokumenterade entitetsformer. Samma
osäkerhet som den generiska värmepump-/laddar-/batteridrivrutinen, inte en anledning
att inte bygga den, men en anledning att vara tydlig om det.

set_economy() mappar till Balboa:s låg/hög-temperaturområde-select (närmaste analog
till "economy" i den officiella integrationen) - en rimlig tolkning av dokumentationens
egen terminologi, inte en gissning på rått protokollnivå som Gecko-misstagen var."""
import homeassistant
from drivers.spa import SpaDriver


class BalboaSpaDriver(SpaDriver):
    def __init__(self, entities: dict | None = None):
        self._e = entities or {}

    def read_state(self) -> dict:
        climate_e = self._e.get("climate")
        range_e = self._e.get("range_select")
        return {
            "current_temp": homeassistant._get_numeric_attribute(climate_e, "current_temperature") if climate_e else None,
            "target_temp": homeassistant._get_numeric_attribute(climate_e, "temperature") if climate_e else None,
            "heater_state": homeassistant._get_raw_state(climate_e) if climate_e else None,
            "economy_mode": homeassistant._get_raw_state(range_e) if range_e else None,
        }

    def set_target_temp(self, temp_c: float) -> None:
        climate_e = self._e.get("climate")
        if climate_e:
            homeassistant.set_climate_temperature(climate_e, temp_c)

    def set_economy(self, enable: bool) -> None:
        range_e = self._e.get("range_select")
        if range_e:
            homeassistant.set_select(range_e, "Low" if enable else "High")

    def read_power_w(self) -> float | None:
        power_e = self._e.get("power")
        return homeassistant._get_numeric_state(power_e) if power_e else None

    def read_activities(self) -> dict:
        out = {}
        for key in ("filter_switch", "pump1", "pump2", "light"):
            entity = self._e.get(key)
            if entity:
                out[key] = homeassistant._get_raw_state(entity)
        return out

    def set_plug_power(self, on: bool) -> bool:
        plug_e = self._e.get("plug")
        if not plug_e:
            return False
        return homeassistant.set_switch(plug_e, on)
