"""CarDriver: gränssnitt för en elbil, oavsett märke/modell.

Default-implementationen (GenericEvCarDriver, tillkommer i Fas 1) kräver bara SOC +
plugged-in - det räcker för praktiskt taget vilken bilintegration som helst i Home
Assistant. Märkesspecifika drivrutiner (Tesla m.fl.) är tillägg för extra finlir
(lås/TPMS/fasbyte), inte ett krav.

En bil helt utan HA-entitet (SOC matas in manuellt av användaren, t.ex. en smart
laddare utan bilintegration) är bara ytterligare en konkret CarDriver vars
read_state() alltid returnerar soc=None eller ett manuellt inmatat värde från
inställningarna - ingen särskild ABC-metod behövs för det fallet.
"""
from abc import ABC, abstractmethod


class CarDriver(ABC):
    id: str
    battery_kwh: float

    @abstractmethod
    def read_state(self) -> dict:
        """{'soc': float|None, 'plugged_in': bool, 'climate_temp': float|None, 'climate_state': str|None}.
        Varje nyckel kan vara None/saknas om bilen/integrationen inte exponerar den."""
        raise NotImplementedError

    @abstractmethod
    def set_climate(self, hvac_mode: str, temperature: float | None = None) -> None:
        """No-op om bilen saknar fjärrstyrd kupévärme."""
        raise NotImplementedError


class NullCarDriver(CarDriver):
    """Ingen bil konfigurerad på den här platsen i husets config."""
    def __init__(self, id: str = "", battery_kwh: float = 0.0):
        self.id = id
        self.battery_kwh = battery_kwh

    def read_state(self) -> dict:
        return {"soc": None, "plugged_in": False, "climate_temp": None, "climate_state": None}

    def set_climate(self, hvac_mode: str, temperature: float | None = None) -> None:
        pass
