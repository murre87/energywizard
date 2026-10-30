"""GeckoSpaDriver: tunt omslag kring homeassistant.py:s Gecko-funktioner. Uppdelningen av
tillstånd över climate.*/water_heater.*-domänerna och CT-klämmans teckenvändning hanteras
redan av read_gecko()/read_spa_power() - rörs inte, bara nås via gränssnittet här.

read_state() returnerar homeassistant.read_gecko()s fält rakt av (current_temp,
target_temp, heater_state, economy_mode) - main.py:s egna villkor (t.ex.
str(heater_state).lower() in ["heating","heat"]) flyttas INTE hit, de bor kvar i
main.py tills ett andra spamärke finns att verifiera en gemensam normalisering mot."""
import homeassistant
from drivers.spa import SpaDriver


class GeckoSpaDriver(SpaDriver):
    def read_state(self) -> dict:
        d = homeassistant.read_gecko() or {}
        return {
            "current_temp": d.get("current_temp"),
            "target_temp": d.get("target_temp"),
            "heater_state": d.get("heater_state"),
            "economy_mode": d.get("economy_mode"),
        }

    def set_target_temp(self, temp_c: float) -> None:
        homeassistant.set_gecko_target(temp_c)

    def set_economy(self, enable: bool) -> None:
        homeassistant.set_gecko_economy(enable)

    def read_power_w(self) -> float | None:
        d = homeassistant.read_spa_power() or {}
        return d.get("total_w")

    def read_activities(self) -> dict:
        return homeassistant.read_spa_activities() or {}

    def set_plug_power(self, on: bool) -> bool:
        return homeassistant.toggle_spa_plug(on)
