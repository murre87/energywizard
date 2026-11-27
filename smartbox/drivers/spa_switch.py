"""SwitchSpaDriver: spabad vars värmare sitter på ett relä (t.ex. en Shelly) i Home Assistant.

Ett sådant bad har ingen egen termostat som EnergyWizard kan prata med, så drivrutinen är
termostaten: den slår på reläet när vattnet är under målet och av när målet är nått.

  entities:
    heater_switch: switch.shelly_spa        # krävs: reläet som driver värmaren
    temperature: sensor.spa_vatten          # valfri men rekommenderas (t.ex. Shelly Add-on + DS18B20)
    power: sensor.shelly_spa_power          # valfri: värmarens effekt i W

Skydd:
  - Högst ett byte per 5 minuter (reläet och värmeelementet slits av täta byten).
  - Aldrig över MAX_TEMP_C, oavsett vad motorn ber om.
  - Har badet en temperaturgivare som slutar svara stängs värmaren av (värm aldrig i blindo).
  - Utan givare alls värmer badet när motorn inte har valt eco (pris- och solstyrning), och
    står av i eco-läge.
"""
import time

from drivers.host import homeassistant
from drivers.spa import SpaDriver

HYSTERESIS_C = 0.5
MIN_SWITCH_INTERVAL_S = 300
MAX_TEMP_C = 40.0


class SwitchSpaDriver(SpaDriver):
    def __init__(self, entities: dict | None = None):
        self._e = entities or {}
        self._target = None
        self._eco = False
        self._on = None             # senast skickat läge
        self._switched_at = 0.0

    # --- avläsning (anropas varje minut av motorn) -> här sker regleringen ---
    def read_state(self) -> dict:
        temp = self._read_temp()
        self._regulate(temp)
        on = self._relay_on()
        return {
            "current_temp": temp,
            "target_temp": self._target,
            "heater_state": "heating" if on else "idle",
            "economy_mode": 1.0 if self._eco else 0.0,
        }

    def set_target_temp(self, temp_c: float) -> None:
        self._target = min(float(temp_c), MAX_TEMP_C) if temp_c is not None else None
        self._regulate(self._read_temp())

    def set_economy(self, enable: bool) -> None:
        self._eco = bool(enable)
        self._regulate(self._read_temp())

    def read_power_w(self) -> float | None:
        e = self._e.get("power")
        return homeassistant._get_numeric_state(e) if e else None

    def read_activities(self) -> dict:
        on = self._relay_on()
        return {} if on is None else {"heater": bool(on)}

    def set_plug_power(self, on: bool) -> bool:
        return False                 # reläet är värmaren; det styrs av termostaten här

    # --- intern termostat ---
    def _read_temp(self):
        e = self._e.get("temperature")
        return homeassistant._get_numeric_state(e) if e else None

    def _relay_on(self):
        e = self._e.get("heater_switch")
        if not e:
            return None
        raw = homeassistant._get_raw_state(e)
        return None if raw is None else str(raw).lower() == "on"

    def want_on(self, temp) -> bool:
        """Ska värmaren gå? (Ren logik, utan tidsspärren.)"""
        if self._eco or self._target is None:
            return False
        if self._e.get("temperature"):
            if temp is None:
                return False         # givaren svarar inte: värm inte i blindo
            if temp >= min(self._target, MAX_TEMP_C):
                return False
            if temp <= self._target - HYSTERESIS_C:
                return True
            return bool(self._on)    # inom hysteresen: behåll läget
        return True                  # ingen givare: följ motorns val (eco = av)

    def _regulate(self, temp):
        e = self._e.get("heater_switch")
        if not e:
            return
        want = self.want_on(temp)
        if want == self._on:
            return
        safety_off = not want and (temp is not None and temp >= MAX_TEMP_C)
        if self._on is not None and not safety_off and time.time() - self._switched_at < MIN_SWITCH_INTERVAL_S:
            return                   # för tätt - försök igen nästa minut
        if homeassistant.set_switch(e, want) is not False:
            self._on = want
            self._switched_at = time.time()
