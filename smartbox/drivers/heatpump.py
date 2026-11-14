"""HeatPumpDriver: gränssnitt för en värmepump, oavsett märke/protokoll.

pump.py:s nuvarande implementation (Thermia Diplomat Optimum G3 via en Husdata H66
Modbus-gateway) blir ThermiaHusdataHeatPumpDriver i Fas 1 - exakt samma register-
läsning/skrivning, bara flyttad bakom det här normaliserade gränssnittet istället för
att vara den enda möjliga värmepumpen. En Nibe-drivrutin (eller annat märke) är ett
separat, senare tillägg (Fas 5) - egen Modbus-/API-karta, isolerad från den här filen.
"""
import time
from abc import ABC, abstractmethod
from hot_water_observation import temperature

# Matter-lika lägen (Thermostat-klustrets SystemMode + varmvatten). Drivrutiner översätter till/från sina egna koder.
MODES = ("off", "heat", "cool", "auto", "dhw", "heat_dhw", "cool_dhw", "auto_dhw")
CURVE_OFFSET_MAX = 5.0        # ±n grader på värmekurvan (Panasonics shift-område är -5..5)
PAUSE_MAX_MIN = 240           # en paus släpper alltid av sig själv inom 4 h


class HeatPumpDriver(ABC):
    """Två lager:
    1. read_sensors/set_* (abstrakta): det main.py styr med idag, oförändrat.
    2. Matter-likt lager (frivilligt, med standardsvar): read_state(), capabilities(), adjust_curve(±n),
       pause(min)/resume() med tidsgräns och tick(). En drivrutin slår på en förmåga genom att implementera
       _write_curve_offset / _write_paused; utan dem svarar metoderna False och ingenting skickas till pumpen.
    Kurvförskjutningen hålls i minnet och nollställs vid start (reset_curve_offset() från main.py, som batteriet),
    så en krasch aldrig lämnar pumpen förskjuten."""

    _curve_offset = 0.0
    _paused_until = None

    # --- Matter-likt lager -------------------------------------------------------------------------------------
    def capabilities(self) -> frozenset:
        caps = set()
        if type(self)._write_curve_offset is not HeatPumpDriver._write_curve_offset:
            caps.add("curve_offset")
        if type(self)._write_paused is not HeatPumpDriver._write_paused:
            caps.add("pause")
        return frozenset(caps)

    def read_state(self) -> dict:
        """Normaliserad bild (alla fält valfria, None = okänt): mode (ur MODES), indoor_temp, outdoor_temp,
        running, power_w, energy_kwh, fault, plus tillägg curve_offset, heat_output_w, cop, defrosting,
        dhw_temp, forward_temp, return_temp, paused_until. Standard: härlett ur read_sensors()."""
        s = self.read_sensors() or {}
        kw = s.get("compressor_power_kw")
        st = {"mode": None, "indoor_temp": s.get("indoor_temp"), "outdoor_temp": s.get("outdoor_temp"),
              "running": s.get("compressor_running"), "power_w": None if kw is None else round(kw * 1000),
              "energy_kwh": None, "fault": None, "heat_output_w": None, "cop": None, "defrosting": None,
              "dhw_temp": s.get("water_temp"), "forward_temp": s.get("forward_temp"), "return_temp": s.get("return_temp")}
        st.update(self._state_extra(s))
        st["dhw_temp_observation"] = s.get("water_temp_observation") or temperature(s.get("water_temp"))
        st["curve_offset"] = self._curve_offset
        st["paused_until"] = self._paused_until
        return st

    def adjust_curve(self, delta: float) -> bool:
        """Höj/sänk värmekurvan delta grader relativt husets grundinställning (summan begränsas till ±5)."""
        return self.set_curve_offset(self._curve_offset + float(delta))

    def set_curve_offset(self, offset: float) -> bool:
        if "curve_offset" not in self.capabilities():
            return False
        offset = max(-CURVE_OFFSET_MAX, min(CURVE_OFFSET_MAX, round(float(offset), 1)))
        if not self._write_curve_offset(offset):
            return False
        self._curve_offset = offset
        return True

    def reset_curve_offset(self) -> bool:
        """Anropas vid start: tillbaka till grundinställningen oavsett vad som gällde före en omstart."""
        if "curve_offset" not in self.capabilities():
            return False
        if not self._write_curve_offset(0.0):
            return False
        self._curve_offset = 0.0
        return True

    def pause(self, minutes: float, now: float | None = None) -> bool:
        """Stoppa uppvärmningen en begränsad tid (högst PAUSE_MAX_MIN). tick() återupptar när tiden gått ut."""
        if "pause" not in self.capabilities() or minutes <= 0:
            return False
        now = time.time() if now is None else now
        if not self._write_paused(True):
            return False
        self._paused_until = now + min(float(minutes), PAUSE_MAX_MIN) * 60
        return True

    def resume(self) -> bool:
        if "pause" not in self.capabilities():
            return False
        if not self._write_paused(False):
            return False
        self._paused_until = None
        return True

    def tick(self, now: float | None = None) -> None:
        """Anropas varje varv i huvudloopen: släpper en paus vars tid gått ut (försöker igen nästa varv om det misslyckas)."""
        now = time.time() if now is None else now
        if self._paused_until is not None and now >= self._paused_until:
            self.resume()

    # --- krokar för drivrutinerna ---------------------------------------------------------------------------------
    def _state_extra(self, sensors: dict) -> dict:
        """Drivrutinsspecifika fält till read_state() (t.ex. mode, fault, cop). Standard: inga."""
        return {}

    def _write_curve_offset(self, offset: float) -> bool:
        """Skicka total förskjutning (relativt grundinställningen) till pumpen. Implementeras bara där det är verifierat."""
        return False

    def _write_paused(self, paused: bool) -> bool:
        return False

    # --- befintligt lager (main.py) -----------------------------------------------------------------------------
    @abstractmethod
    def read_sensors(self) -> dict:
        """Normaliserade nycklar, alla valfria (None om värmepumpen/protokollet saknar dem):
        indoor_temp, outdoor_temp, forward_temp, return_temp, water_temp, degree_minutes,
        compressor_running (bool), compressor_power_kw, operating_mode."""
        raise NotImplementedError

    @abstractmethod
    def set_room_temp(self, target_c: float) -> bool:
        """Returnerar True om kommandot skickades - main.py:s anropsmönster
        (if driver.set_room_temp(...):) använder returvärdet."""
        raise NotImplementedError

    @abstractmethod
    def set_water_stop_temp(self, target_c: float) -> bool:
        raise NotImplementedError

    @abstractmethod
    def set_water_start_temp(self, target_c: float) -> bool:
        raise NotImplementedError

    @abstractmethod
    def set_heating_start_temp(self, target_c: float) -> bool:
        """Värmestopp / värmesäsong-tröskel (utetemperatur över vilken uppvärmning
        pausas i auto-läge) - inte en del av det dagliga pris-/komfortflödet, men
        används för säsongsjusteringar (sommar/höst)."""
        raise NotImplementedError

    @abstractmethod
    def set_operating_mode(self, mode) -> bool:
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

    def set_room_temp(self, target_c: float) -> bool:
        return False

    def set_water_stop_temp(self, target_c: float) -> bool:
        return False

    def set_water_start_temp(self, target_c: float) -> bool:
        return False

    def set_heating_start_temp(self, target_c: float) -> bool:
        return False

    def set_operating_mode(self, mode) -> bool:
        return False
