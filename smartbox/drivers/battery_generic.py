"""GenericBatteryDriver: läser/styr ett husbatteri via vad batteriets egna HA-
integration redan exponerar - exakt den väg Predbat (github.com/springfall2008/batpred)
redan bevisat fungerar för GivEnergy/Huawei/Solis/Powerwall m.fl. Ingen märkesspecifik
drivrutin planeras - Predbat underhåller redan den kompatibiliteten, ingen anledning att
duplicera den. set_mode() finns men anropas aldrig av gpm.py i det här steget (se
drivers/battery.py:s modulkommentar för varför)."""
import homeassistant
from drivers.battery import BatteryDriver


class GenericBatteryDriver(BatteryDriver):
    """Default för batterier utan egen drivrutin. Alla entiteter valfria - supports_control()
    är bara True om en mode_select-entitet är konfigurerad."""
    def __init__(self, capacity_kwh: float | None = None, entities: dict | None = None):
        self.capacity_kwh = capacity_kwh
        self._e = entities or {}

    def read_state(self) -> dict:
        soc_e = self._e.get("soc")
        power_e = self._e.get("power")
        mode_e = self._e.get("mode_select")
        return {
            "soc_pct": homeassistant._get_numeric_state(soc_e) if soc_e else None,
            "power_w": homeassistant._get_numeric_state(power_e) if power_e else None,
            "capacity_kwh": self.capacity_kwh,
            "mode": homeassistant._get_raw_state(mode_e) if mode_e else None,
        }

    def supports_control(self) -> bool:
        return bool(self._e.get("mode_select"))

    def set_mode(self, mode: str) -> bool:
        mode_e = self._e.get("mode_select")
        if not mode_e:
            return False
        return homeassistant.set_select(mode_e, mode)
