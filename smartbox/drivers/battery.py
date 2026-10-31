"""BatteryDriver: gränssnitt för ett husbatteri, oavsett märke.

VIKTIGT, läs innan du bygger vidare: det här är bara LÄSNING + en enkel, generisk
lägesstyrning (samma princip Predbat redan bevisat fungerar - via vad batteriets egna
HA-integration exponerar, ingen egen protokollkod). gpm.py importerar INTE den här
kategorin alls - batteriet konkurrerar direkt med sol/nät/elbil om samma watt just nu,
en genuint annan optimeringsfråga än allt annat som redan styrs, och ingen i projektet
har ett riktigt batteri att verifiera automatiserade laddnings-/urladdningsbeslut mot
(se ROADMAP.md). Den gränsen är medveten, inte ett förbiseende.
"""
from abc import ABC, abstractmethod


class BatteryDriver(ABC):
    @abstractmethod
    def read_state(self) -> dict:
        """{'soc_pct': float|None, 'power_w': float|None (+ = laddar, - = laddar ur),
        'capacity_kwh': float|None, 'mode': str|None}. Alla nycklar valfria."""
        raise NotImplementedError

    @abstractmethod
    def supports_control(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def set_mode(self, mode: str) -> bool:
        """No-op (False) om supports_control() är False. mode är en fri sträng som
        vidarebefordras rakt av till batteriets egen select-entitet - ingen normaliserad
        enum än (väntar på ett första riktigt batteri att verifiera mappningen mot,
        samma princip som HeatPumpDriver.set_operating_mode)."""
        raise NotImplementedError


class NullBatteryDriver(BatteryDriver):
    """Inget husbatteri konfigurerat."""
    def read_state(self) -> dict:
        return {"soc_pct": None, "power_w": None, "capacity_kwh": None, "mode": None}

    def supports_control(self) -> bool:
        return False

    def set_mode(self, mode: str) -> bool:
        return False
