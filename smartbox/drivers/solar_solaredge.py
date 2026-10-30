"""SolarEdgeSolarDriver: tunt omslag kring homeassistant.read_solaredge() och den
märkesspecifika exportgränsen (number.solaredge_modbus_active_power_limit). Inte generisk
SunSpec - SolarEdges fungerande väg är proprietär, se smartbox/drivers/solar.py."""
import homeassistant
from drivers.solar import SolarDriver


class SolarEdgeSolarDriver(SolarDriver):
    def read_production(self) -> dict:
        d = homeassistant.read_solaredge() or {}
        return {"pv_power_w": d.get("pv_power_w"), "today_kwh": d.get("today_kwh")}

    def supports_curtailment(self) -> bool:
        return True

    def set_export_limit_pct(self, pct: int) -> None:
        homeassistant.set_solaredge_limit(pct)

    def get_export_limit_pct(self) -> float | None:
        return homeassistant.get_solaredge_limit()
