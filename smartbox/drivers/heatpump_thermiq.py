"""ThermIQHeatPumpDriver: Thermia (Diplomat/Atec/Atlas/BVP m.fl.) via ThermIQ-MQTT/ThermIQ-ROOM och ThermIQ:s egen
Home Assistant-integration (github.com/thermiq/thermiq_mqtt-ha, HACS, domän thermiq_mqtt).

KÄLLOR (lästa 2026-11-06 i thermiq/thermiq_mqtt-ha, HEAD):
- custom_components/thermiq_mqtt/sensor.py / binary_sensor.py / number.py: entity_id = "<plattform>.thermiq_mqtt_<id>_<nyckel>",
  där <id> är det namn användaren gav pumpen i integrationens konfiguration (t.ex. "vp1").
- heatpump/thermiq_regs.py: nycklarna. outdoor_t (r00), indoor_t (r01), indoor_dec_t (r02, tiondelar), supplyline_t (r05),
  returnline_t (r06), boiler_t (r07, varmvatten), compressor_on (r10 bit 2), alarm_indication_on (r11 bit 6),
  integral1 (r19, gradminuter), indoor_requested_t (r32, number 0-50 °C), hotwater_start_t (r44) och hotwater_stop_t
  (r54) som number.

ALDRIG KÖRD MOT EN RIKTIG PUMP. Bara det källan bekräftar används; övrigt svarar False/None. Skriver bara via
number.set_value på integrationens egna number-entiteter (integrationen skriver registret till pumpen över MQTT).
Skuggläge: inget skickas, bara loggas.
"""
from drivers.host import homeassistant
from drivers.heatpump import HeatPumpDriver


class ThermIQHeatPumpDriver(HeatPumpDriver):
    def __init__(self, prefix: str | None = None):
        # prefix = "thermiq_mqtt_<id>"; ett bart id ("vp1") godtas också
        p = (prefix or "").strip()
        self._prefix = p if not p or p.startswith("thermiq_mqtt_") else f"thermiq_mqtt_{p}"
        self._warned = set()

    def _e(self, platform: str, key: str) -> str:
        return f"{platform}.{self._prefix}_{key}"

    def _num(self, key: str):
        v = homeassistant._get_numeric_state(self._e("sensor", key))
        return v if isinstance(v, (int, float)) else None

    def _warn_once(self, key: str, msg: str):
        if key not in self._warned:
            print(msg)
            self._warned.add(key)

    def read_sensors(self) -> dict:
        if not self._prefix:
            return {}
        indoor = self._num("indoor_t")
        dec = self._num("indoor_dec_t")
        if indoor is not None and dec is not None and 0 <= dec < 10 and float(indoor).is_integer():
            indoor = indoor + dec / 10.0          # r01 hela grader + r02 tiondelar
        comp = homeassistant._get_numeric_state(self._e("binary_sensor", "compressor_on"))
        alarm = homeassistant._get_numeric_state(self._e("binary_sensor", "alarm_indication_on"))
        return {
            "indoor_temp": indoor,
            "outdoor_temp": self._num("outdoor_t"),
            "forward_temp": self._num("supplyline_t"),
            "return_temp": self._num("returnline_t"),
            "water_temp": self._num("boiler_t"),
            "degree_minutes": self._num("integral1"),
            "compressor_running": None if comp is None else bool(comp),
            "compressor_power_kw": None,
            "alarm_active": None if alarm is None else int(bool(alarm)),
        }

    def _state_extra(self, sensors: dict) -> dict:
        a = sensors.get("alarm_active")
        return {"fault": None if a is None else bool(a)}

    def _set(self, key: str, value: float, lo: float, hi: float) -> bool:
        if not self._prefix:
            return False
        v = round(min(max(float(value), lo), hi), 1)
        ent = self._e("number", key)
        from drivers.host import shadow
        if shadow.active():
            shadow.record("ThermIQ", f"{ent}={v}")
            return True
        return homeassistant.set_number(ent, v)

    def set_room_temp(self, target_c: float) -> bool:
        return self._set("indoor_requested_t", target_c, 5, 30)

    def set_water_stop_temp(self, target_c: float) -> bool:
        return self._set("hotwater_stop_t", target_c, 40, 65)

    def set_water_start_temp(self, target_c: float) -> bool:
        return self._set("hotwater_start_t", target_c, 35, 60)

    def set_heating_start_temp(self, target_c: float) -> bool:
        self._warn_once("heat_start", "⚠️ ThermIQ: set_heating_start_temp stöds inte (inget motsvarande register) - ignoreras.")
        return False

    def set_operating_mode(self, mode) -> bool:
        # main_mode (r33) har Thermias egna lägeskoder, olika mellan modeller - skrivs inte förrän en testare bekräftat
        self._warn_once("mode", "⚠️ ThermIQ: driftläge skrivs inte ännu (lägeskoderna skiljer mellan modeller) - ignoreras.")
        return False
