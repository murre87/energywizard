"""ModbusRegisterSolarDriver: exportstyrning via Home Assistants INBYGGDA Modbus-integration.

För växelriktare där ingen integration exponerar en skrivbar gräns som entitet/tjänst - t.ex.
Fronius, där den officiella fronius-integrationen bara läser, och redpomodoro/fronius_modbus
bara har batterigränser. Ingen egen protokollkod: vi anropar HA:s egen tjänst
`modbus.write_register` (fält hub/slave/address/value, enligt HA:s dokumentation) mot en
Modbus-hubb användaren redan satt upp i configuration.yaml.

Skrivsekvens (när enable_register är satt): gräns AV -> nytt procentvärde -> gräns PÅ.
Vid 100 %: bara gräns AV, så växelriktaren lämnas utan begränsning.

Förval "fronius" (SunSpec Model 123, Fronius GEN24/Symo), från HA-communityns tråd
"Automate Fronius Soft Limit": WMaxLimPct = 40232, WMaxLim_Ena = 40236 (dokumentationen anger
40233/40237 - adresserna är ett lägre i praktiken), värde 100-10000 = 1-100 %.
**Overifierat mot riktig hårdvara.** En kommentar i samma tråd hävdar att 40232 bara tar 0/1 i
viss firmware - kontrollera registerkartan för din firmware. Alla adresser går att ändra i
house_config.yaml.

Gränsen går inte att läsa tillbaka via tjänsten - get_export_limit_pct() ger senast SKICKADE
värdet (100 vid start), annars tolkar main.py None som "växelriktaren offline".
"""
from drivers.host import homeassistant
from drivers.solar import SolarDriver

PRESETS = {
    "fronius": {"pct_register": 40232, "enable_register": 40236, "pct_scale": 100},
}


class ModbusRegisterSolarDriver(SolarDriver):
    def __init__(self, entities: dict | None = None, modbus: dict | None = None):
        self._e = entities or {}
        m = dict(PRESETS.get(str((modbus or {}).get("preset", "")).lower(), {}))
        m.update({k: v for k, v in (modbus or {}).items() if k != "preset" and v is not None})
        self._m = m
        self._last_pct = 100.0

    def read_production(self) -> dict:
        power_e = self._e.get("pv_power_w")
        today_e = self._e.get("today_kwh")
        status_e = self._e.get("status")
        return {
            "pv_power_w": homeassistant._get_numeric_state(power_e) if power_e else None,
            "today_kwh": homeassistant._get_numeric_state(today_e) if today_e else None,
            "status": homeassistant._get_raw_state(status_e) if status_e else None,
        }

    def supports_curtailment(self) -> bool:
        return bool(self._m.get("hub") and self._m.get("pct_register") is not None)

    def _write(self, address, value) -> bool:
        return homeassistant.call_service("modbus", "write_register", {
            "hub": self._m["hub"], "slave": int(self._m.get("slave", 1)),
            "address": int(address), "value": int(value),
        })

    def set_export_limit_pct(self, pct: int) -> bool:
        if not self.supports_curtailment():
            return False
        pct = max(0, min(100, int(pct)))
        enable = self._m.get("enable_register")
        scale = float(self._m.get("pct_scale", 1))
        if pct >= 100:
            ok = self._write(enable, 0) if enable is not None else self._write(self._m["pct_register"], round(100 * scale))
        else:
            ok = True
            if enable is not None:
                ok = self._write(enable, 0)
            # Fronius tar 1-100 %, inte 0: lägsta steget (1 % = 100) är det närmaste "ingen export".
            raw = max(round(scale), round(pct * scale)) if scale > 1 else round(pct * scale)
            ok = ok and self._write(self._m["pct_register"], raw)
            if enable is not None:
                ok = ok and self._write(enable, 1)
        if ok:
            self._last_pct = float(pct)
        return ok

    def get_export_limit_pct(self) -> float | None:
        return self._last_pct if self.supports_curtailment() else None
