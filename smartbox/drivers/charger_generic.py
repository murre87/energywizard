"""GenericChargerDriver: täcker de flesta laddboxar utan en handbyggd drivrutin per
märke, genom HA:s generiska switch.turn_on/off (samma anrop EaseeChargerDriver redan
använder) och number.set_value (om laddaren exponerar strömgräns som en vanlig
number-entitet). Easees "dynamiska" gräns och fasväxling är äkta märkesspecifika
HA-tjänster (easee.set_charger_dynamic_limit/set_charger_phase_mode) utan generisk
motsvarighet - en laddare utan sån tjänst kan bara få en enklare, direkt strömgräns
via number.set_value, eller ingen alls om ingen number-entitet finns konfigurerad."""
import homeassistant
from drivers.charger import ChargerDriver


class GenericChargerDriver(ChargerDriver):
    """Default för laddare utan egen drivrutin. Kräver bara en switch-entitet
    (på/av) - strömgräns är valfri, fasväxling stöds inte alls (de flesta
    laddarintegrationer saknar HA-stöd för det)."""
    supports_phase_switch = False

    def __init__(self, id: str, entities: dict | None = None):
        self.id = id
        self._e = entities or {}

    def read_state(self) -> dict:
        status_e = self._e.get("status")
        current_e = self._e.get("current_limit")
        return {
            "status": homeassistant._get_raw_state(status_e) if status_e else None,
            "current_a": homeassistant._get_numeric_state(current_e) if current_e else None,
            "phases": None,
        }

    def set_limit_a(self, amps: int, reason: str | None = None) -> bool:
        current_e = self._e.get("current_limit")
        if not current_e:
            return False
        return homeassistant.set_number(current_e, amps)

    def set_phases(self, phases: int) -> None:
        pass

    def turn_on(self) -> None:
        switch_e = self._e.get("switch")
        if switch_e:
            homeassistant.set_switch(switch_e, True)

    def turn_off(self) -> None:
        switch_e = self._e.get("switch")
        if switch_e:
            homeassistant.set_switch(switch_e, False)
