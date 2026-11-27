"""EaseeChargerDriver: Easee via HA:s Easee-integration.

Allt den behöver kommer från installationen (evs[].charger): laddboxens id (för integrationens tjänster
set_charger_dynamic_limit/set_charger_phase_mode), entiteterna den läser (status, effekt, fasströmmar ...) och
enable_switch (påslaget/avslaget). Easees egna kvirkar (fasströmmar som attribut, fasläget som inte går att
läsa tillbaka) hanteras i homeassistant._read_easee_charger / set_easee_phases.
Inga inbyggda laddboxar: allt kommer ur installationen (2026-11-07)."""
from drivers.host import homeassistant
from drivers import ha_easee
from drivers.charger import ChargerDriver


class EaseeChargerDriver(ChargerDriver):
    supports_phase_switch = True

    def __init__(self, id: str, reader=None, entities: dict | None = None, enable_switch: str | None = None):
        self.id = id
        self.entities = dict(entities or {})
        self.enable_switch = enable_switch
        if self.entities:
            self._reader = lambda: ha_easee.read_charger(self.entities, self.id)
        else:
            self._reader = reader or (lambda: {})

    def read_raw(self) -> dict:
        """Allt laddboxen rapporterar (effekt, fasströmmar, session, status ...) - samma form som förut."""
        return self._reader() or {}

    def read_state(self) -> dict:
        d = self.read_raw()
        return {**d, "status": d.get("status"), "current_a": d.get("current_a"), "phases": d.get("phases")}

    def set_limit_a(self, amps: int, reason: str | None = None) -> bool:
        return bool(ha_easee.set_dynamic_limit(self.id, amps, reason=reason))

    def set_phases(self, phases: int) -> None:
        ha_easee.set_phases(self.id, phases)

    def _switch(self, on: bool) -> bool:
        if not self.enable_switch:                    # utan påslagsbrytare i installationen går det inte
            return bool((ha_easee.turn_on if on else ha_easee.turn_off)(self.id, None))
        try:
            homeassistant.post_service(f"switch/turn_{'on' if on else 'off'}", {"entity_id": self.enable_switch}, 5)
            print(f"⚡ Easee ({self.id}): skickade 'turn_{'on' if on else 'off'}'.")
            return True
        except Exception as e:
            print(f"❌ Easee ({self.id}): fel vid turn_{'on' if on else 'off'}: {e}")
            return False

    def turn_on(self) -> None:
        self._switch(True)

    def turn_off(self) -> None:
        self._switch(False)
