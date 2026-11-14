"""BatteryDriver: gränssnitt för ett husbatteri, oavsett märke.

Läsning + styrning via det batteriets egen HA-integration redan exponerar (samma princip som
Predbat bevisat fungerar) - ingen egen protokollkod. Besluten fattas i battery_control.py,
som ser HELA huset (elbil, effekttak, säkring, elpris, sol) - batteriet jobbar inte på egen hand.

Styrningen uttrycks som fem märkesoberoende avsikter (INTENTS). Varje drivrutin mappar dem
till det batteriets integration kallar sina lägen; en avsikt utan mappning stöds inte och
används aldrig av battery_control.py.
"""
from abc import ABC, abstractmethod
import math


def soc_input_quality(soc_pct, evidence, now):
    """Diagnostic provenance only; never grants control or changes planner inputs."""
    result = {"source": "battery", "known": soc_pct is not None, "age_s": None}
    if not isinstance(evidence, dict):
        return result
    source = evidence.get("soc_source")
    if not isinstance(source, str) or source not in {"ha_reported", "ha_updated", "ferroamp_mqtt_received", "modbus_received"}:
        return result
    try:
        value, stamp = evidence.get("soc_pct"), evidence.get("soc_sample_at")
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
               for v in (value, soc_pct, stamp, now)):
            return result
        if value != soc_pct or not 0 <= value <= 100 or not 0 < stamp <= now:
            return result
        result.update(source=source, age_s=now - stamp)
    except (TypeError, ValueError, OverflowError):
        pass
    return result


class BatteryDriver(ABC):
    def set_balancing(self, active):
        """Optional transient maintenance context; never changes vendor SOC settings."""
        return None

    @abstractmethod
    def read_state(self) -> dict:
        """{'soc_pct': float|None, 'power_w': float|None (+ = laddar, - = laddar ur),
        'capacity_kwh': float|None, 'mode': str|None,
        'power_sample_at': float|None (UTC epoch of source measurement/receipt, never cache-read time),
        'soc_sample_at': float|None, 'soc_source': str|None (SOC timestamp origin; see soc_input_quality).
        Alla nycklar valfria. Receipt/report time is not a device measurement clock."""
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
