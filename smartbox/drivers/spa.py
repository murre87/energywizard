"""SpaDriver: gränssnitt för ett spabad, oavsett styrsystem (Gecko, Balboa, ...).

Varje enskild funktion är individuellt valfri inom en konkret drivrutin - en
installation kan t.ex. sakna säkringsskåpets effekt-/säkerhetssensorer men ändå vilja
styra uppvärmningen. read_power_w() returnerar då bara None istället för att hela
spa-delsystemet behöver vara allt-eller-inget. Geckos uppdelning av tillstånd över två
HA-domäner (climate.* + water_heater.*) och en fysisk CT-klämmas teckenvändning hör
hemma i GeckoSpaDriver (Fas 1), bakom det här gränssnittet.
"""
from abc import ABC, abstractmethod


class SpaDriver(ABC):
    @abstractmethod
    def read_state(self) -> dict:
        """{'current_temp': float|None, 'target_temp': float|None, 'heating': bool|None}."""
        raise NotImplementedError

    @abstractmethod
    def set_target_temp(self, temp_c: float) -> None:
        raise NotImplementedError

    @abstractmethod
    def set_economy(self, enable: bool) -> None:
        raise NotImplementedError

    @abstractmethod
    def read_power_w(self) -> float | None:
        """None om ingen effektsensor finns konfigurerad för spat."""
        raise NotImplementedError

    @abstractmethod
    def read_activities(self) -> dict:
        """Vilka delfunktioner som är PÅ just nu (värme, cirkulationspump, bubbel m.fl.)
        - används för att lära sig vilken fas som driver vad. Tomt dict om spat saknar
        stöd för detaljerad aktivitetsavläsning."""
        raise NotImplementedError

    @abstractmethod
    def set_plug_power(self, on: bool) -> bool:
        """Slår på/av spats smartplug, om en sådan finns konfigurerad (strömtillförsel-
        tillförlitlighet, inte termisk styrning). Returnerar False utan effekt om spat
        saknar en styrbar plugg."""
        raise NotImplementedError


class NullSpaDriver(SpaDriver):
    """Inget spa konfigurerat - spa-logiken (Prio 4, 5.5, 11, 11.2, 12 i gpm.py)
    blir overksam utan att krascha, precis som idag när sensordata saknas."""
    def read_state(self) -> dict:
        return {"current_temp": None, "target_temp": None, "heating": None}

    def set_target_temp(self, temp_c: float) -> None:
        pass

    def set_economy(self, enable: bool) -> None:
        pass

    def read_power_w(self) -> float | None:
        return None

    def read_activities(self) -> dict:
        return {}

    def set_plug_power(self, on: bool) -> bool:
        return False
