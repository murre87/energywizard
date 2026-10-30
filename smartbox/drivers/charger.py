"""ChargerDriver: gränssnitt för en laddbox, oavsett märke (Easee, Zaptec, Wallbox, ...).

Märkesspecifikt beteende (t.ex. Easees separata fasström-attribut och saknade
select-entitet för fasbyte) hör hemma i den konkreta drivrutinen (EaseeChargerDriver,
Fas 1), bakom det här normaliserade gränssnittet.
"""
from abc import ABC, abstractmethod


class ChargerDriver(ABC):
    id: str
    supports_phase_switch: bool = False

    @abstractmethod
    def read_state(self) -> dict:
        """{'status': str|None, 'current_a': float|None, 'phases': int|None}.
        status är laddarens råa statusord (för loggning/felsökning) - ingen fast
        uppsättning värden kan antas, olika integrationer använder olika ord."""
        raise NotImplementedError

    @abstractmethod
    def set_limit_a(self, amps: int, reason: str | None = None) -> bool:
        """Sätter dynamisk strömgräns. Returnerar True om kommandot skickades."""
        raise NotImplementedError

    @abstractmethod
    def set_phases(self, phases: int) -> None:
        """No-op/ignoreras om supports_phase_switch är False."""
        raise NotImplementedError

    @abstractmethod
    def turn_on(self) -> None:
        """Tvingar igång en laddningssession (t.ex. när status är 'awaiting_start'/'paused'
        - se main.py:s stalled-charging-vakt för varför detta inte alltid räcker att anta)."""
        raise NotImplementedError

    @abstractmethod
    def turn_off(self) -> None:
        raise NotImplementedError


class NullChargerDriver(ChargerDriver):
    """Ingen laddare konfigurerad - bilen laddas manuellt eller inte alls av systemet."""
    supports_phase_switch = False

    def __init__(self, id: str = ""):
        self.id = id

    def read_state(self) -> dict:
        return {"status": None, "current_a": None, "phases": None}

    def set_limit_a(self, amps: int, reason: str | None = None) -> bool:
        return False

    def set_phases(self, phases: int) -> None:
        pass

    def turn_on(self) -> None:
        pass

    def turn_off(self) -> None:
        pass
