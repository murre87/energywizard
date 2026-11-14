"""HaEntitiesHeatPumpDriver: värmepump som redan finns i Home Assistant via en integration (t.ex. HA:s egen myUplink-
integration för NIBE, eller nibe_heatpump), läst via dess entiteter.

Issue #158 (2026-11-06): en NIBE F750 via HA:s myUplink-integration hittades inte. Vår drivrutin "myuplink" pratar
direkt med molnet (eget OAuth-konto), så den kunde inte använda integrationen som redan fanns. Den här drivrutinen
läser i stället de entiteter installationsguiden kopplat (heat_pump.entities i house_config.yaml):

  indoor_temp, outdoor_temp, forward_temp, return_temp, water_temp, degree_minutes  (sensor-/number-entiteter)
  compressor   (valfri, binary_sensor/sensor: på/av eller frekvens > 0 = går)
  room_target  (valfri, number-entitet för rumsbörvärdet)
  curve_offset (valfri, number-entitet för värmekurvans förskjutning, t.ex. NIBE 47011 "Heating offset climate system 1",
               #200 Jonas: F730 via nibegw). Används när rumsbörvärde saknas: önskad innetemp -> förskjutning med
               offset_steps_per_c steg per grad kring offset_base_c (standard 2 steg/°C kring 20,5 °C), inom
               offset_min..offset_max (standard -5..+5).

Guiden kopplar NIBE:s givarkoder i entiteternas namn (BT1 ute, BT2 framledning, BT3 retur, BT7/BT6 varmvatten, BT50
rum), som är desamma på alla språk (discovery.py, _nibe_bt_entities). room_target kopplas aldrig automatiskt: vilket
börvärde som är rätt skiljer mellan modeller, och myUplink kräver premiumabonnemang för att skriva. Utan den läser
drivrutinen bara, och styrningen svarar ärligt False.
"""
import re

import homeassistant
from drivers.heatpump import HeatPumpDriver

_READ = ("indoor_temp", "outdoor_temp", "forward_temp", "return_temp", "water_temp", "degree_minutes")


class HaEntitiesHeatPumpDriver(HeatPumpDriver):
    def __init__(self, entities: dict | None = None, cfg: dict | None = None):
        self._e = {k: v for k, v in (entities or {}).items() if isinstance(v, str) and "." in v}
        self._cfg = cfg or {}                     # offset_steps_per_c, offset_base_c, offset_min, offset_max (#200)
        self._warned = set()

    def _num(self, key):
        ent = self._e.get(key)
        if not ent:
            return None
        v = homeassistant._get_numeric_state(ent)
        return float(v) if isinstance(v, (int, float)) else None

    def _warn_once(self, key, msg):
        if key not in self._warned:
            print(msg)
            self._warned.add(key)

    def read_sensors(self) -> dict:
        if not self._e:
            return {}
        out = {k: self._num(k) for k in _READ}
        out["compressor_running"] = compressor_running(self._e.get("compressor"), self._num("compressor"),
                                                       lambda: homeassistant._get_raw_state(self._e["compressor"]))
        out["compressor_power_kw"] = None
        from hot_water_observation import temperature
        raw = homeassistant._states_cache.get(self._e.get("water_temp")) or {}
        out["water_temp_observation"] = temperature(
            out.get("water_temp"), raw.get("last_reported") or raw.get("last_updated"), "ha_report")
        return out

    def set_room_temp(self, target_c: float) -> bool:
        ent = self._e.get("room_target")
        if not ent and self._e.get("curve_offset"):
            return self._set_offset_for(target_c)
        if not ent:
            self._warn_once("room", "ℹ️ Värmepumpen (Home Assistant-entiteter): inget rumsbörvärde valt "
                                    "(heat_pump.entities.room_target) - läser bara, styr inte.")
            return False
        v = round(min(max(float(target_c), 5.0), 30.0), 1)
        import shadow
        if shadow.active():
            shadow.record("Värmepump (HA)", f"{ent}={v}")
            return True
        return homeassistant.set_number(ent, v)

    def _set_offset_for(self, target_c: float) -> bool:
        def num(k, d):
            try:
                return float(self._cfg.get(k, d))
            except (TypeError, ValueError):
                return d
        steps = num("offset_steps_per_c", 2.0) * (float(target_c) - num("offset_base_c", 20.5))
        off = int(round(min(max(steps, num("offset_min", -5.0)), num("offset_max", 5.0))))
        ent = self._e["curve_offset"]
        import shadow
        if shadow.active():
            shadow.record("Värmepump (HA, kurva)", f"{ent}={off}")
            return True
        return homeassistant.set_number(ent, off)

    def set_water_stop_temp(self, target_c: float) -> bool:
        return False

    def set_water_start_temp(self, target_c: float) -> bool:
        return False

    def set_heating_start_temp(self, target_c: float) -> bool:
        return False

    def set_operating_mode(self, mode) -> bool:
        return False


_ON = ("on", "true", "running", "runs", "run", "drift", "går", "kör", "körs", "startar", "starting", "heating", "värme",
       "hot water", "varmvatten")
_OFF = ("off", "false", "idle", "stopped", "stoppad", "stopping", "stoppar", "av", "vilar", "standby", "från")
_NIBE_STATUS = {20: False, 40: True, 60: True, 100: False}     # NIBE 43427 "Status kompressor": stoppad/startar/går/stoppar


def compressor_running(entity, num, raw_fn):
    """Går kompressorn? Frekvens > 0 = går. NIBE:s statusgivare 43427 (#184) ger koder i stället för frekvens:
    20 stoppad, 40 startar, 60 går, 100 stoppar - och i HA ibland som text ("Running", "Stopped"). None = vet inte."""
    if not entity:
        return None
    is_status = bool(re.search(r"43427|status", str(entity), re.I))
    if num is not None:
        if is_status and int(num) in _NIBE_STATUS and float(num) == int(num):
            return _NIBE_STATUS[int(num)]
        return num > 0
    raw = str(raw_fn() or "").strip().lower()
    return True if raw in _ON else False if raw in _OFF else None
