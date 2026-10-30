"""HeatPumpDriver: gränssnitt för en värmepump, oavsett märke/protokoll.

pump.py:s nuvarande implementation (Thermia Diplomat Optimum G3 via en Husdata H66
Modbus-gateway) blir ThermiaHusdataHeatPumpDriver i Fas 1 - exakt samma register-
läsning/skrivning, bara flyttad bakom det här normaliserade gränssnittet istället för
att vara den enda möjliga värmepumpen. En Nibe-drivrutin (eller annat märke) är ett
separat, senare tillägg (Fas 5) - egen Modbus-/API-karta, isolerad från den här filen.
"""
from abc import ABC, abstractmethod


class HeatPumpDriver(ABC):
    @abstractmethod
    def read_sensors(self) -> dict:
        """Normaliserade nycklar, alla valfria (None om värmepumpen/protokollet saknar dem):
        indoor_temp, outdoor_temp, forward_temp, return_temp, water_temp, degree_minutes,
        compressor_running (bool), compressor_power_kw, operating_mode."""
        raise NotImplementedError

    @abstractmethod
    def set_room_temp(self, target_c: float) -> None:
        raise NotImplementedError

    @abstractmethod
    def set_water_stop_temp(self, target_c: float) -> None:
        raise NotImplementedError

    @abstractmethod
    def set_water_start_temp(self, target_c: float) -> None:
        raise NotImplementedError

    @abstractmethod
    def set_heating_start_temp(self, target_c: float) -> None:
        """Värmestopp / värmesäsong-tröskel (utetemperatur över vilken uppvärmning
        pausas i auto-läge) - inte en del av det dagliga pris-/komfortflödet, men
        används för säsongsjusteringar (sommar/höst)."""
        raise NotImplementedError

    @abstractmethod
    def set_operating_mode(self, mode) -> None:
        """Målbilden är en normaliserad enum-sträng (t.ex. 'heat'/'off'), inte ett råttal
        specifikt för en viss tillverkares register - men riktig normalisering väntar
        till Fas 5 (ett andra värmepumpsmärke) så mappningen går att verifiera mot något.
        ThermiaHusdataHeatPumpDriver tar idag samma råa heltalskod som innan."""
        raise NotImplementedError


class NullHeatPumpDriver(HeatPumpDriver):
    """Ingen värmepump att styra på den här platsen - husvärmelogiken (Prio 5 m.fl.
    i gpm.py) blir då overksam utan att krascha, precis som idag när sensordata saknas."""
    def read_sensors(self) -> dict:
        return {}

    def set_room_temp(self, target_c: float) -> None:
        pass

    def set_water_stop_temp(self, target_c: float) -> None:
        pass

    def set_water_start_temp(self, target_c: float) -> None:
        pass

    def set_heating_start_temp(self, target_c: float) -> None:
        pass

    def set_operating_mode(self, mode) -> None:
        pass
