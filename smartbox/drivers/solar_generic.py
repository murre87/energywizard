"""GenericNumberSolarDriver: täcker växelriktare utan egen drivrutin, genom att läsa/
skriva entiteter husets egen HA-integration redan exponerar - exakt den väg
SolarDriver:s ABC-docstring själv föreslår ("en redan existerande HA-entitet
(number/switch) ... föredras när den finns"). Exportgräns som en vanlig
number-entitet är vanligt hos flera märken, inte bara SolarEdge."""
import homeassistant
from drivers.solar import SolarDriver


class GenericNumberSolarDriver(SolarDriver):
    """Default för växelriktare utan egen drivrutin. Effekt/dagsenergi är valfria
    sensor-entiteter; exportgräns kräver en number-entitet för att stödjas alls."""
    def __init__(self, entities: dict | None = None):
        self._e = entities or {}

    def read_production(self) -> dict:
        power_e = self._e.get("pv_power_w")
        today_e = self._e.get("today_kwh")
        status_e = self._e.get("status")
        return {
            "pv_power_w": homeassistant._get_numeric_state(power_e) if power_e else None,
            "today_kwh": homeassistant._get_numeric_state(today_e) if today_e else None,
            "status": homeassistant._get_raw_state(status_e) if status_e else None,
        }

    def supports_curtailment(self) -> bool:
        return bool(self._e.get("export_limit_pct"))

    def set_export_limit_pct(self, pct: int) -> bool:
        limit_e = self._e.get("export_limit_pct")
        if not limit_e:
            return False
        return homeassistant.set_number(limit_e, pct)

    def get_export_limit_pct(self) -> float | None:
        limit_e = self._e.get("export_limit_pct")
        return homeassistant._get_numeric_state(limit_e) if limit_e else None
