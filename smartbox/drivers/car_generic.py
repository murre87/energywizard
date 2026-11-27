"""Konkreta CarDriver-implementationer. Fas 1: tunna omslag kring homeassistant.py:s
befintliga läsfunktioner - samma kod, bara flyttad bakom gränssnittet, inte omskriven."""
from drivers.host import homeassistant
from drivers import ha_car
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
        """Samma form som de gamla read_nissan_data/read_tesla_data, men ur installationens entiteter:
        plugged_in som tal (1.0/0.0/None, binary_sensor on/off -> 1/0), charging_state "charging" när bilens
        laddningsgivare (entities.charging) är på, annars entities.charging_state som den står."""
        soc_e = self._e.get("soc")
        plugged_e = self._e.get("plugged_in")
        climate_e = self._e.get("climate")
        out = {
            "soc": homeassistant._get_numeric_state(soc_e) if soc_e else None,
            "plugged_in": homeassistant._get_numeric_state(plugged_e) if plugged_e else None,
            "climate_temp": homeassistant._get_numeric_attribute(climate_e, "current_temperature") if climate_e else None,
            "climate_state": homeassistant._get_raw_state(climate_e) if climate_e else None,
        }
        ch_e, cs_e = self._e.get("charging"), self._e.get("charging_state")
        if ch_e or cs_e:
            on = ch_e and homeassistant._get_raw_state(ch_e) == "on"
            out["charging_state"] = "charging" if on else (homeassistant._get_raw_state(cs_e) if cs_e else None)
        return out

    def set_climate(self, hvac_mode: str, temperature: float | None = None) -> None:
        climate_e = self._e.get("climate")
        if climate_e:
            ha_car.set_climate(climate_e, hvac_mode, temperature)


class NissanCarDriver(GenericEvCarDriver):
    """Samma som GenericEvCarDriver (entiteterna kommer från installationen). Leafs batterivärde hämtas bara när
    man ber om det: entities.update_button trycks av main.py."""


class TeslaCarDriver(GenericEvCarDriver):
    """Samma som GenericEvCarDriver. En sovande Tesla rapporterar inget batterivärde: entities.wake_button trycks
    av main.py när den är inkopplad men värdet är gammalt."""
