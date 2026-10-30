"""GeckoSpaDriver: tunt omslag kring homeassistant.py:s Gecko-funktioner. Uppdelningen av
tillstånd över climate.*/water_heater.*-domänerna och CT-klämmans teckenvändning hanteras
redan av read_gecko()/read_spa_power() - rörs inte, bara nås via gränssnittet här."""
import homeassistant
from drivers.spa import SpaDriver


class GeckoSpaDriver(SpaDriver):
    def read_state(self) -> dict:
        d = homeassistant.read_gecko() or {}
        return {
            "current_temp": d.get("current_temp"),
            "target_temp": d.get("target_temp"),
            "heating": d.get("heater_state") not in (None, "off", "idle") if d.get("heater_state") is not None else None,
        }

    def set_target_temp(self, temp_c: float) -> None:
        homeassistant.set_gecko_target(temp_c)

    def set_economy(self, enable: bool) -> None:
        homeassistant.set_gecko_economy(enable)

    def read_power_w(self) -> float | None:
        d = homeassistant.read_spa_power() or {}
        return d.get("total_w")
