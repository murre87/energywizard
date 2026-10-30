"""EaseeChargerDriver: tunt omslag kring homeassistant.py:s Easee-funktioner.
Easees egna kvirkar (separata fasström-attribut, saknad select-entitet för fasbyte vid
vissa integrationsversioner) hör redan hemma i de underliggande funktionerna - flyttas
inte om här, bara nås via det normaliserade gränssnittet."""
import homeassistant
from drivers.charger import ChargerDriver


class EaseeChargerDriver(ChargerDriver):
    supports_phase_switch = True

    def __init__(self, id: str, reader=None):
        self.id = id
        # reader: homeassistant.read_easee_lite eller read_easee_carport (vilken av de
        # två fysiska boxarna configen pekar ut) - sparas som referens, inte kopierad kod.
        self._reader = reader or (lambda: {})

    def read_state(self) -> dict:
        d = self._reader() or {}
        return {"status": d.get("status"), "current_a": d.get("current_a"), "phases": d.get("phases")}

    def set_limit_a(self, amps: int, reason: str | None = None) -> bool:
        return bool(homeassistant.set_ev_dynamic_limit(self.id, amps, reason=reason))

    def set_phases(self, phases: int) -> None:
        homeassistant.set_easee_phases(self.id, phases)

    def turn_on(self) -> None:
        homeassistant.turn_on_charger(self.id)

    def turn_off(self) -> None:
        homeassistant.turn_off_charger(self.id)
