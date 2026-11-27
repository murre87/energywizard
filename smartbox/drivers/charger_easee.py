"""EaseeChargerDriver: Easee via HA:s Easee-integration.

Allt den behöver kommer från installationen (evs[].charger): laddboxens id (för integrationens tjänster
set_charger_dynamic_limit/set_charger_phase_mode), entiteterna den läser (status, effekt, fasströmmar ...) och
enable_switch (påslaget/avslaget). Easees egna kvirkar (fasströmmar som attribut, fasläget som inte går att
läsa tillbaka) hanteras i homeassistant._read_easee_charger / set_easee_phases.
Inga inbyggda laddboxar: allt kommer ur installationen (2026-11-07)."""
import requests

from drivers.host import homeassistant
from drivers.charger import ChargerDriver


class EaseeChargerDriver(ChargerDriver):
    supports_phase_switch = True

    def __init__(self, id: str, reader=None, entities: dict | None = None, enable_switch: str | None = None):
        self.id = id
        self.entities = dict(entities or {})
        self.enable_switch = enable_switch
        if self.entities:
            self._reader = lambda: homeassistant._read_easee_charger(self.entities, self.id)
        else:
            self._reader = reader or (lambda: {})

    def read_raw(self) -> dict:
        """Allt laddboxen rapporterar (effekt, fasströmmar, session, status ...) - samma form som förut."""
        return self._reader() or {}

    def read_state(self) -> dict:
        d = self.read_raw()
        return {**d, "status": d.get("status"), "current_a": d.get("current_a"), "phases": d.get("phases")}

    def set_limit_a(self, amps: int, reason: str | None = None) -> bool:
        return bool(homeassistant.set_ev_dynamic_limit(self.id, amps, reason=reason))

    def set_phases(self, phases: int) -> None:
        homeassistant.set_easee_phases(self.id, phases)

    def _switch(self, on: bool) -> bool:
        if not self.enable_switch:                    # utan påslagsbrytare i installationen går det inte
            return bool((homeassistant.turn_on_charger if on else homeassistant.turn_off_charger)(self.id, None))
        try:
            r = requests.post(f"{homeassistant._BASE}/services/switch/turn_{'on' if on else 'off'}", headers=homeassistant._HEADERS,
                              json={"entity_id": self.enable_switch}, timeout=5, verify=homeassistant._VERIFY)
            r.raise_for_status()
            print(f"⚡ Easee ({self.id}): skickade 'turn_{'on' if on else 'off'}'.")
            return True
        except Exception as e:
            print(f"❌ Easee ({self.id}): fel vid turn_{'on' if on else 'off'}: {e}")
            return False

    def turn_on(self) -> None:
        self._switch(True)

    def turn_off(self) -> None:
        self._switch(False)
