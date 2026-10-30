"""Konkreta CarDriver-implementationer. Fas 1: tunna omslag kring homeassistant.py:s
befintliga läsfunktioner - samma kod, bara flyttad bakom gränssnittet, inte omskriven."""
import homeassistant
from drivers.car import CarDriver


class GenericEvCarDriver(CarDriver):
    """Default för praktiskt taget vilken bilmodell som helst: bara SOC + plugged-in +
    (valfri) kupévärme krävs. Läser direkt från de HA-entiteter husets config anger,
    istället för homeassistant.py:s hårdkodade NISSAN_ENTITIES/TESLA_ENTITIES-dictar."""
    def __init__(self, id: str, battery_kwh: float, entities: dict | None = None):
        self.id = id
        self.battery_kwh = battery_kwh
        self._e = entities or {}

    def read_state(self) -> dict:
        soc_e = self._e.get("soc")
        plugged_e = self._e.get("plugged_in")
        climate_e = self._e.get("climate")
        return {
            "soc": homeassistant._get_numeric_state(soc_e) if soc_e else None,
            "plugged_in": bool(homeassistant._get_numeric_state(plugged_e)) if plugged_e else None,
            "climate_temp": homeassistant._get_numeric_attribute(climate_e, "current_temperature") if climate_e else None,
            "climate_state": homeassistant._get_raw_state(climate_e) if climate_e else None,
        }

    def set_climate(self, hvac_mode: str, temperature: float | None = None) -> None:
        climate_e = self._e.get("climate")
        if climate_e:
            homeassistant.set_car_climate(climate_e, hvac_mode, temperature)


class NissanCarDriver(GenericEvCarDriver):
    """Samma som GenericEvCarDriver idag - egen klass så Nissan-specifika kvirkar
    (t.ex. button.leaf_update_data-uppdatering) har en naturlig plats att landa i
    senare utan att påverka GenericEvCarDriver eller andra bilar."""
    def read_state(self) -> dict:
        return homeassistant.read_nissan_data()


class TeslaCarDriver(GenericEvCarDriver):
    """Tesla har egna kvirkar (sover och slutar rapportera, se homeassistant.py:s
    stale-tolerans) som homeassistant.read_tesla_data() redan hanterar - återanvänd den
    istället för att läsa om logiken här."""
    def read_state(self) -> dict:
        return homeassistant.read_tesla_data()
