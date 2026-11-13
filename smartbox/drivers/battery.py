"""BatteryDriver: gränssnitt för ett husbatteri, oavsett märke.

Läsning + styrning via det batteriets egen HA-integration redan exponerar (samma princip som
Predbat bevisat fungerar) - ingen egen protokollkod. Besluten fattas i battery_control.py,
som ser HELA huset (elbil, effekttak, säkring, elpris, sol) - batteriet jobbar inte på egen hand.

Styrningen uttrycks som fem märkesoberoende avsikter (INTENTS). Varje drivrutin mappar dem
till det batteriets integration kallar sina lägen; en avsikt utan mappning stöds inte och
används aldrig av battery_control.py.
"""
from abc import ABC, abstractmethod


class BatteryDriver(ABC):
    def set_balancing(self, active):
        """Optional transient maintenance context; never changes vendor SOC settings."""
        return None

    @abstractmethod
    def read_state(self) -> dict:
        """{'soc_pct': float|None, 'power_w': float|None (+ = laddar, - = laddar ur),
        'capacity_kwh': float|None, 'mode': str|None,
        'power_sample_at': float|None (UTC epoch of source measurement, never cache-read time)}. Alla nycklar valfria."""
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


    def supported_intents(self) -> set:
        """Vilka av INTENTS drivrutinen kan utföra. Tom mängd = bara läsning."""
        return set()

    def apply_intent(self, intent: str, power_w: float | None = None) -> bool:
        """Utför en avsikt (se INTENTS). False om den inte stöds eller inte gick att skicka."""
        return False

    def refresh(self, now: float | None = None) -> bool:
        """Anropas varje varv: skriver om en pågående laddning/urladdning för växelriktare vars
        fjärrstyrning släpper av sig själv efter en tidsgräns (t.ex. Solis RC). Standard: inget."""
        return False


# Märkesoberoende avsikter (battery_control.py fattar besluten, drivrutinen översätter):
INTENTS = {
    "auto": "Växelriktarens eget läge (självförbrukning) - alltid säkra reservläget",
    "hold": "Ingen urladdning (får ladda från solen)",
    "idle": "Varken ladda eller ladda ur (solöverskottet går vidare, t.ex. till elbilen)",
    "charge": "Ladda, även från nätet",
    "discharge": "Ladda ur, även när huset inte drar så mycket",
}


class NullBatteryDriver(BatteryDriver):
    """Inget husbatteri konfigurerat."""
    def read_state(self) -> dict:
        return {"soc_pct": None, "power_w": None, "capacity_kwh": None, "mode": None}

    def supports_control(self) -> bool:
        return False

    def set_mode(self, mode: str) -> bool:
        return False
