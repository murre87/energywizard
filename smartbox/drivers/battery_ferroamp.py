"""Opt-in local EnergyHub battery control; unverified on hardware.

Only auto/charge/discharge are advertised. RevD's default-mode description is
ambiguous; writes require explicit confirmation that mode 0 releases control on
the installation's firmware. Neither solar-only hold nor exact idle is assumed.
"""
import math
import time

from drivers.battery import BatteryDriver
from drivers.ferroamp_modbus import (
    EnergyHubConnection, read_float, read_words, shadow_write, write_float, write_word,
)


class FerroampBatteryDriver(BatteryDriver):
    def __init__(self, modbus=None, control_enabled=False, default_mode_verified=False,
                 max_power_w=5000.0, reserve_soc=20.0, max_soc=100.0):
        self._bus = EnergyHubConnection(modbus)
        self._enabled = control_enabled is True and default_mode_verified is True
        self._max_power = float(max_power_w)
        self._reserve, self._max_soc = float(reserve_soc), float(max_soc)
        if not math.isfinite(self._max_power) or not 0 < self._max_power <= 1e9:
            raise ValueError("EnergyHub max_power_w must be finite and positive")
        if not 0 <= self._reserve < self._max_soc <= 100:
            raise ValueError("EnergyHub SOC limits must satisfy 0 <= reserve < max <= 100")

    def supports_control(self):
        return bool(self._bus.host) and self._enabled

    def supported_intents(self):
        return {"auto", "charge", "discharge"} if self.supports_control() else set()

    def read_state(self):
        state = {"soc_pct": None, "power_w": None, "capacity_kwh": None, "mode": None}
        unit = self._bus.unit_id
        with self._bus.connect() as client:
            if client is None:
                return state
            soc = read_float(client, 6016, unit)
            state["soc_pct"] = soc if soc is not None and 0 <= soc <= 100 else None
            state["soc_sample_at"] = time.time() if state["soc_pct"] is not None else None
            state["soc_source"] = "modbus_received"
            power = read_float(client, 6100, unit)
            state["power_w"] = -power * 1000 if power is not None else None
            state["power_sample_at"] = time.time() if power is not None else None
            capacity = read_float(client, 6008, unit)
            state["capacity_kwh"] = capacity if capacity is not None and capacity > 0 else None
            mode = read_words(client, 6104, 1, unit)
            state["mode"] = str(mode[0]) if mode is not None else None
        return state

    def set_mode(self, mode):
        return self.apply_intent(mode)

    def apply_intent(self, intent, power_w=None):
        self.command_reference_verified = False
        if intent not in self.supported_intents():
            return False
        power = 0.0
        if intent != "auto":
            if isinstance(power_w, bool):
                return False
            try:
                watts = self._max_power if power_w is None else float(power_w)
            except (TypeError, ValueError):
                return False
            if not math.isfinite(watts) or watts <= 0:
                return False
            power = min(watts, self._max_power) / 1000
            if intent == "charge":
                power = -power
        if shadow_write(f"battery {intent}, reference={power:g} kW"):
            return True
        unit = self._bus.unit_id
        with self._bus.connect() as client:
            if client is None:
                return False
            if intent == "auto":
                self.command_reference_verified = self._release(client)
                return self.command_reference_verified
            # Fresh device SOC on every forced request; never rely on an old plan.
            soc = read_float(client, 6016, unit)
            if soc is None or not 0 <= soc <= 100:
                return False
            if (intent == "discharge" and soc <= self._reserve) or (intent == "charge" and soc >= self._max_soc):
                return False
            if not write_float(client, 6064, power, unit):
                return False
            if write_word(client, 6000, 1, unit) and self._bus.verify(lambda: self._matches(client, power)):
                self.command_reference_verified = True
                return True
            # If activation/verification failed, try to release, never report success.
            self._release(client)
        return False

    def _matches(self, client, power):
        mode = read_words(client, 6104, 1, self._bus.unit_id)
        reference = read_float(client, 6106, self._bus.unit_id)
        return mode == [1] and reference is not None and abs(reference - power) <= 0.001

    def _release(self, client):
        return write_word(client, 6000, 0, self._bus.unit_id) and self._bus.verify(
            lambda: read_words(client, 6104, 1, self._bus.unit_id) == [0])
