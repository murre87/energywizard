"""SolarEdgeSolarDriver: SolarEdge via Home Assistant och den märkesspecifika exportgränsen (solaredge_modbus-
integrationens number.*_active_power_limit). Inte generisk SunSpec - SolarEdges fungerande väg är proprietär, se
smartbox/drivers/solar.py.

Entiteterna kommer ur installationen (solar.entities): pv_power_w, today_kwh, status (en entitet eller en lista,
första med värde vinner) och exportgränsen i solar.curtailment.entity (eller entities.limit). Utan egna entiteter
används integrationernas standardnamn."""
from drivers.host import homeassistant
from drivers.solar import SolarDriver


class SolarEdgeSolarDriver(SolarDriver):
    def __init__(self, entities: dict | None = None, limit_entity: str | None = None):
        self._e = entities or {}
        self._limit = limit_entity or self._e.get("limit")

    def read_production(self) -> dict:
        d = homeassistant.read_solaredge(self._e) or {}
        return {"pv_power_w": d.get("pv_power_w"), "today_kwh": d.get("today_kwh"), "status": d.get("status")}

    def supports_curtailment(self) -> bool:
        return True

    def set_export_limit_pct(self, pct: int) -> bool:
        return bool(homeassistant.set_solaredge_limit(pct, self._limit))

    def get_export_limit_pct(self) -> float | None:
        return homeassistant.get_solaredge_limit(self._limit)
