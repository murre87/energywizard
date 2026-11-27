"""GeckoSpaDriver: Gecko-spabad (in.touch2 via HA:s gecko-integration). Entiteterna kommer ur installationen
(spa.entities) - inga husspecifika namn i koden:

  current_temp, target_temp   sensorer för vatten- och måltemperatur
  climate                     climate-entiteten (måltemperatur läses/sätts här)
  water_heater                värmarens läge (heating/idle)
  economy_mode                switch för Economy Mode
  power_phases / power_w      effekt per fas (lista) eller total - tas som belopp (CT-klämmans riktning)
  safety                      {overcurrent|overvoltage|overheated|power_exceeded: binary_sensor}
  activities                  {heating|circ_pump|pump1|blower|...: entitet} - för fasinlärningen
  smart_plug                  switch som bryter strömmen (omstart när spat tappat kontakten)

En ofullständig konfiguration (t.ex. skriven av den äldre upptäckten, som bara kopplade climate-entiteten som "temperatur",
#570) kompletteras ur HA:s entiteter via badets namnstam (spa_entities.complete_gecko); det som användaren valt ändras aldrig.

read_state() returnerar rådata (heater_state som HA visar den) - main.py:s villkor bor kvar där."""
import time

from drivers.host import homeassistant
from drivers import ha_gecko
from drivers.host import spa_entities
from drivers.spa import SpaDriver

_REFRESH_S = 900          # entiteterna i HA ändras sällan; kolla igen med några minuters mellanrum om något fortfarande saknas


class GeckoSpaDriver(SpaDriver):
    def __init__(self, entities: dict | None = None):
        self._e = entities or {}
        self._full = None
        self._full_at = 0.0

    def _ents(self) -> dict:
        """Konfigurationen, kompletterad ur HA. Räknas om först efter _REFRESH_S om något viktigt fortfarande saknas."""
        missing = [k for k in ("climate", "economy_mode") if not (self._full or {}).get(k)]
        if self._full is None or (missing and time.time() - self._full_at > _REFRESH_S):
            try:
                done = spa_entities.complete_gecko(self._e, homeassistant.all_entity_names())
            except Exception as ex:
                print(f"⚠️ Gecko: kunde inte komplettera spabadets entiteter: {ex}")
                done = dict(self._e)
            added = sorted(k for k, v in done.items() if v and not self._e.get(k))
            if added and (self._full is None or any(k not in (self._full or {}) for k in added)):
                print(f"🛁 Gecko: kompletterade spabadets entiteter ur HA ({', '.join(added)}).")
            self._full, self._full_at = done, time.time()
        return self._full

    def read_state(self) -> dict:
        d = ha_gecko.read(self._ents()) or {}
        return {
            "current_temp": d.get("current_temp"),
            "target_temp": d.get("target_temp"),
            "heater_state": d.get("heater_state"),
            "economy_mode": d.get("economy_mode"),
        }

    def set_target_temp(self, temp_c: float) -> None:
        ha_gecko.set_target(temp_c, self._ents().get("climate"))

    def set_economy(self, enable: bool) -> None:
        ha_gecko.set_economy(enable, self._ents().get("economy_mode"))

    def read_power_w(self) -> float | None:
        return (self.read_power_detail() or {}).get("total_w")

    def read_power_detail(self) -> dict:
        return ha_gecko.read_power(self._ents()) or {}

    def read_activities(self) -> dict:
        return ha_gecko.read_activities(self._ents()) or {}

    def set_plug_power(self, on: bool) -> bool:
        return ha_gecko.toggle_plug(on, self._ents().get("smart_plug"))
