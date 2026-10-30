"""SolarDriver: gränssnitt för en solcellsanläggning, oavsett växelriktarmärke.

Exportstyrning (set_export_limit_pct) är inte ett universellt standardiserat API:
SolarEdges fungerande väg är märkesspecifik (egen SolarEdgeSolarDriver, Fas 1), medan
andra märken bäst nås antingen via en redan existerande HA-entitet (number/switch som
märkets egen integration redan exponerar - föredras när den finns) eller en generisk
SunSpec Modbus-klient (Model 123, den öppna standarden - fallback när ingen bra
HA-entitet finns). supports_curtailment() låter anroparen (Prio 2 i gpm.py) fråga
innan den försöker, istället för att anta att alla växelriktare kan strypas.
"""
from abc import ABC, abstractmethod


class SolarDriver(ABC):
    @abstractmethod
    def read_production(self) -> dict:
        """{'pv_power_w': float|None, 'today_kwh': float|None, 'status': str|None}.
        status är växelriktarens råa statuskod/-ord (för fellarm) - betydelsen är
        märkesspecifik, ingen fast uppsättning värden kan antas."""
        raise NotImplementedError

    @abstractmethod
    def supports_curtailment(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def set_export_limit_pct(self, pct: int) -> bool:
        """No-op (False) om supports_curtailment() är False. Returnerar True om
        kommandot skickades, annars False - main.py:s anropsmönster använder
        returvärdet för att avgöra om senast-skickat-värdet ska uppdateras."""
        raise NotImplementedError

    @abstractmethod
    def get_export_limit_pct(self) -> float | None:
        """Nuvarande exportgräns (%), None om supports_curtailment() är False eller
        värdet inte går att läsa just nu."""
        raise NotImplementedError


class NullSolarDriver(SolarDriver):
    """Ingen solcellsanläggning konfigurerad."""
    def read_production(self) -> dict:
        return {"pv_power_w": None, "today_kwh": None, "status": None}

    def supports_curtailment(self) -> bool:
        return False

    def set_export_limit_pct(self, pct: int) -> bool:
        return False

    def get_export_limit_pct(self) -> float | None:
        return None
