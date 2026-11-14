"""GenericBatteryDriver: läser/styr ett husbatteri via vad batteriets egna HA-integration
redan exponerar - samma väg Predbat (github.com/springfall2008/batpred) bevisat fungerar för
GivEnergy/Huawei/Solis/Powerwall m.fl.

Styrning (valfri): en select-entitet för läget och en mappning från EnergyWizards avsikter till
batteriets egna lägesnamn, t.ex. för SolarEdge Modbus (HA 2026.10) "Storage command mode":

    battery:
      entities:
        soc: sensor.batteri_soc
        power: sensor.batteri_effekt          # + = laddar
        mode_select: select.solaredge_storage_command_mode
        charge_power: number.batteri_laddeffekt          # valfri, W eller kW (läses ur entiteten)
        discharge_power: number.batteri_urladdningseffekt # valfri, W eller kW
      modes:
        auto: "Maximize self-consumption"
        hold: "Charge from solar power"
        idle: "Off"
        charge: "Charge from solar power and grid"
        discharge: "Maximize export"

Växelriktare där lägesvalet bara sparas lokalt tills en knapp trycks (t.ex. Growatt via
wills106/homeassistant-solax-modbus: "Time 1 Mode" + knappen "Time 1 Update") anger knappen
som mode_apply_button - den trycks efter varje lägesbyte:

    battery:
      entities:
        mode_select: select.growatt_time_1_mode
        mode_apply_button: button.growatt_time_1_update
      modes:
        auto: "Load First"
        hold: "Battery First"        # utan AC-laddning: tar solen, laddar inte ur
        charge: "Battery First"      # kräver att AC-laddning är påslagen i växelriktaren
        discharge: "Grid First"
    (Ställ in Time 1 till 00:00-23:59 och Aktiv en gång i HA - sedan byter EnergyWizard bara läget.)

Ett läge kan också kräva FLERA val samtidigt - då anges det som {select-entitet: alternativ}.
T.ex. Solax (Gen4-6) via wills106/homeassistant-solax-modbus:

    modes:
      auto:      {select.solax_charger_use_mode: "Self Use Mode"}
      hold:      {select.solax_charger_use_mode: "Back Up Mode"}
      idle:      {select.solax_charger_use_mode: "Manual Mode", select.solax_manual_mode_select: "Stop Charge and Discharge"}
      charge:    {select.solax_charger_use_mode: "Manual Mode", select.solax_manual_mode_select: "Force Charge"}
      discharge: {select.solax_charger_use_mode: "Manual Mode", select.solax_manual_mode_select: "Force Discharge"}

Effekt: antingen en tecknad sensor (power, + = laddar) eller två positiva (power_charge och
power_discharge, som Growatt via Solax Modbus har).

Lägesnamnen ovan är EXEMPEL - skriv exakt de alternativ din egen select-entitet visar i
Home Assistant (Utvecklarverktyg -> Tillstånd -> entiteten -> attributet options).
Bara de avsikter som finns under modes: används.
"""
import math
import homeassistant
from drivers.battery import BatteryDriver, INTENTS


class GenericBatteryDriver(BatteryDriver):
    """Default för batterier utan egen drivrutin. Alla entiteter valfria - supports_control()
    är bara True om en mode_select-entitet OCH minst en lägesmappning finns."""
    def __init__(self, capacity_kwh: float | None = None, entities: dict | None = None, modes: dict | None = None,
                 power_invert: bool | None = None, keepalive_s: float | None = None, max_power_w: float | None = None):
        self.capacity_kwh = capacity_kwh
        self.max_power_w = max_power_w
        # battery.keepalive_s: växelriktare vars tvångsladdning släpper efter en tidsgräns (Solis RC Timeout,
        # standard 5 min) får kommandot omskrivet så här ofta medan det laddar/laddar ur. Dör EnergyWizard
        # släpper växelriktaren själv - det är det säkra hållet.
        self._keepalive = float(keepalive_s) if keepalive_s else None
        self._last = None                       # (avsikt, effekt, tid) för senaste lyckade skrivning
        # battery.power_invert: true om sensorn visar + vid URladdning. Saknas den i house_config.yaml gäller valet
        # "Vänd tecknet" i webben (ew_settings battery_power_invert, #166) - läses vid varje avläsning, ingen omstart.
        self._invert_cfg = power_invert
        self._e = entities or {}
        self._modes = {k: v for k, v in (modes or {}).items() if k in INTENTS and v}

    @staticmethod
    def _as_list(v):
        return [x for x in v if x] if isinstance(v, (list, tuple)) else ([v] if v else [])

    def _soc(self):
        """Laddnivå. Flera batteribankar (t.ex. två växelriktare med var sitt batteri, issue #86): soc är en lista,
        och nivån vägs efter bankarnas storlek (bank_kwh, samma ordning) - utan storlekar lika vikt."""
        ents = self._as_list(self._e.get("soc"))
        if len(ents) <= 1:
            return homeassistant._get_numeric_state(ents[0]) if ents else None
        kwh = self._e.get("bank_kwh") or []
        vals = []
        for i, e in enumerate(ents):
            v = homeassistant._get_numeric_state(e)
            if v is not None:
                w = float(kwh[i]) if i < len(kwh) and kwh[i] else 1.0
                vals.append((v, w))
        if not vals:
            return None
        return round(sum(v * w for v, w in vals) / sum(w for _, w in vals), 1)

    def _sum(self, key):
        ents = self._as_list(self._e.get(key))
        read = homeassistant.get_power_w if key.startswith("power") else homeassistant._get_numeric_state
        vals = [read(e) for e in ents]
        vals = [v for v in vals if v is not None]
        return sum(vals) if vals else None

    def _soc_evidence(self, soc):
        """Date the same configured SOC aggregate, conservatively requiring every bank."""
        from datetime import datetime
        stamps, values, sources = [], [], []
        weights = self._e.get("bank_kwh") or []
        try:
            for i, entity in enumerate(self._as_list(self._e.get("soc"))):
                raw = homeassistant._states_cache.get(entity) or {}
                value = float(raw.get("state"))
                if not math.isfinite(value) or not 0 <= value <= 100:
                    return None, None
                field = "last_reported" if raw.get("last_reported") else "last_updated"
                stamp = datetime.fromisoformat(raw[field].replace("Z", "+00:00"))
                if stamp.utcoffset() is None:
                    return None, None
                stamps.append(stamp.timestamp())
                sources.append("ha_reported" if field == "last_reported" else "ha_updated")
                weight = float(weights[i]) if i < len(weights) and weights[i] else 1.0
                if not math.isfinite(weight) or weight <= 0:
                    return None, None
                values.append((value, weight))
            if not values:
                return None, None
            observed = values[0][0] if len(values) == 1 else round(sum(v * w for v, w in values) / sum(w for _, w in values), 1)
            if observed != soc:
                return None, None
            return min(stamps), "ha_updated" if "ha_updated" in sources else "ha_reported"
        except (KeyError, ValueError, TypeError, AttributeError, OverflowError):
            return None, None

    @property
    def _invert(self) -> bool:
        if self._invert_cfg is not None:
            return bool(self._invert_cfg)
        try:
            import ew_settings
            return bool(ew_settings.get("battery_power_invert", False))
        except Exception:
            return False

    def read_state(self) -> dict:
        mode_e = self._e.get("mode_select")
        soc = self._soc()
        soc_sample_at, soc_source = self._soc_evidence(soc)
        power = self._sum("power")
        keys = ("power",)
        if power is not None and self._invert:
            power = -power
        if power is None and (self._e.get("power_charge") or self._e.get("power_discharge")):
            keys = ("power_charge", "power_discharge")
            pc = self._sum("power_charge") if self._e.get("power_charge") else 0.0
            pd = self._sum("power_discharge") if self._e.get("power_discharge") else 0.0
            power = None if pc is None and pd is None else (pc or 0.0) - (pd or 0.0)
        # Source timestamps, not cache-read time: constant/stale HA values must not
        # become fresh command evidence merely because this method was called.
        stamps = []
        try:
            from datetime import datetime
            for key in keys:
                for entity in self._as_list(self._e.get(key)):
                    raw = homeassistant._states_cache.get(entity) or {}
                    if not math.isfinite(float(raw.get("state"))):
                        raise ValueError("Missing source measurement")
                    value = raw.get("last_reported") or raw.get("last_updated")
                    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
                    if stamp.utcoffset() is None:
                        raise ValueError("Missing source timestamp offset")
                    stamps.append(stamp.timestamp())
            power_sample_at = min(stamps) if stamps else None
        except (ValueError, TypeError, AttributeError):
            power_sample_at = None
        return {
            "soc_pct": soc,
            "soc_sample_at": soc_sample_at,
            "soc_source": soc_source,
            "power_w": power,
            "power_sample_at": power_sample_at,
            "capacity_kwh": self.capacity_kwh,
            "mode": homeassistant._get_raw_state(mode_e) if mode_e else None,
        }

    def supports_control(self) -> bool:
        if not self._modes:
            return False
        return bool(self._e.get("mode_select")) or all(isinstance(v, dict) for v in self._modes.values())

    def supported_intents(self) -> set:
        return set(self._modes) if self.supports_control() else set()

    def set_mode(self, mode: str) -> bool:
        mode_e = self._e.get("mode_select")
        if not mode_e:
            return False
        return homeassistant.set_select(mode_e, mode)

    @staticmethod
    def _power_value(entity: str, watts: float):
        """Watt -> reglagets egen enhet (W eller kW, t.ex. FoxESS Force Charge Power), högst dess max."""
        unit = homeassistant.get_attribute(entity, "unit_of_measurement")
        unit = unit.strip().lower() if isinstance(unit, str) else "w"
        value = watts / 1000.0 if unit == "kw" else watts
        top = homeassistant.get_attribute(entity, "max")
        if isinstance(top, (int, float, str)) and not isinstance(top, bool):
            try:
                top = float(top)
                value = min(value, top) if top > 0 else value
            except ValueError:
                pass
        return round(value, 3) if unit == "kw" else int(round(value))

    def refresh(self, now: float | None = None) -> bool:
        import time as _t
        if not self._keepalive or not self._last or self._last[0] not in ("charge", "discharge"):
            return False
        now = _t.time() if now is None else now
        if now - self._last[2] < self._keepalive:
            return False
        return self.apply_intent(self._last[0], self._last[1], now=now, force=True)   # håll vid liv: skriv även samma värde

    def apply_intent(self, intent: str, power_w: float | None = None, now: float | None = None, force: bool = False) -> bool:
        import time as _t
        self._force = force
        try:
            ok = self._apply(intent, power_w)
        finally:
            self._force = False
        if ok:
            self._last = (intent, power_w, _t.time() if now is None else now)
        return ok

    def _fkw(self) -> dict:
        """force bara när det behövs (håll-vid-liv), annars läs-före-skriv i homeassistant.set_number/set_select."""
        return {"force": True} if getattr(self, "_force", False) else {}

    def _step(self, step: dict, power_w: float | None) -> bool:
        p = int(round(abs(power_w))) if power_w is not None else int(self.max_power_w or 2500)
        if step.get("service"):
            domain, _, svc = str(step["service"]).partition(".")
            data = dict(step.get("data") or {})
            if step.get("power_field"):
                data[step["power_field"]] = p
            return bool(domain and svc) and bool(homeassistant.call_service(domain, svc, data))
        if step.get("number"):
            v = step.get("value")
            if v == "soc":                                   # håll: lägsta laddnivå = nuvarande (t.ex. Kostal min SoC)
                soc = self._soc()
                if soc is None:
                    return False
                v = int(round(soc))
            elif v is None:
                v = p * (1 if step.get("sign", 1) >= 0 else -1)
                if step.get("power_units") is True:
                    unit = str(homeassistant.get_attribute(step["number"], "unit_of_measurement") or "").lower()
                    if unit not in ("w", "kw"):
                        return False
                    v /= 1000.0 if unit == "kw" else 1.0
                    try:
                        lower = float(homeassistant.get_attribute(step["number"], "min"))
                        upper = float(homeassistant.get_attribute(step["number"], "max"))
                    except (TypeError, ValueError):
                        return False
                    if not (math.isfinite(lower) and math.isfinite(upper) and lower < 0 < upper):
                        return False
                    v = max(lower, min(upper, v))
            return bool(homeassistant.set_number(step["number"], v, **self._fkw()))
        return False

    def _apply(self, intent: str, power_w: float | None = None) -> bool:
        option = self._modes.get(intent)
        if not option or (not isinstance(option, (dict, list)) and not self._e.get("mode_select")):
            return False
        ok = True
        if power_w is not None:
            num = self._e.get("charge_power" if intent == "charge" else "discharge_power" if intent == "discharge" else "")
            if num:
                ok = homeassistant.set_number(num, self._power_value(num, abs(power_w)), **self._fkw())
        if isinstance(option, list) or (isinstance(option, dict) and (option.get("service") or option.get("number"))):
            # Ett eller flera steg i tur och ordning (2026-11-06): tjänsteanrop {service, data, power_field} (t.ex.
            # huawei_solar.forcible_charge, eller sonnenbatterie: först manuellt läge, sedan charge_battery) och
            # nummerfält {number, sign | value} (t.ex. Victrons ESS-börvärde: +effekt = ladda från nätet).
            for step in (option if isinstance(option, list) else [option]):
                ok = ok and self._step(step, power_w)
        elif isinstance(option, dict):                   # flera val i tur och ordning (t.ex. Solax)
            for entity, opt in option.items():
                ok = ok and homeassistant.set_select(entity, opt, **self._fkw())
        else:
            ok = ok and self.set_mode(option)
        btn = self._e.get("mode_apply_button")
        if ok and btn:
            ok = bool(homeassistant.press_button(btn))
        return ok
