"""HuaweiSolarServiceDriver: Huawei SUN2000 via HACS-integrationen wlcrs/huawei_solar (lokal Modbus).

Integrationen exponerar inte exportgränsen som en entitet att skriva till, utan som tjänster.
Bekräftat mot integrationens egen services.yaml och services.py (inte gissat):

  huawei_solar.set_maximum_feed_grid_power_percent  {device_id, power_percentage: 0-100}
      sätter läget "Active Power Control" till en gräns för MATNINGEN TILL NÄTET i procent
  huawei_solar.reset_maximum_feed_grid_power        {device_id}
      läget "Unlimited" - ingen gräns

Det begränsar exporten vid anslutningspunkten, inte produktionen: vid 0 % håller växelriktaren
själv exporten på noll medan huset (och batteriet) fortfarande får solel. 100 % = reset.

device_id: växelriktarens HA-enhets-ID - eller, om anläggningen har en EMMA, EMMA-enhetens.
Integrationen registrerar då samma tjänster mot EMMA:n istället (services.py, manager "emma").

Produktion läses via vanliga sensor-entiteter (samma nycklar som GenericNumberSolarDriver).
Gränsen går inte att läsa tillbaka via tjänsterna, så get_export_limit_pct() returnerar senast
SKICKADE värdet (100 vid start) - main.py tolkar annars None som "växelriktaren offline".
"""
from drivers.host import homeassistant
from drivers.solar import SolarDriver


class HuaweiSolarServiceDriver(SolarDriver):
    def __init__(self, entities: dict | None = None):
        self._e = entities or {}
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
        return bool(self._e.get("device_id"))

    def set_export_limit_pct(self, pct: int) -> bool:
        device_id = self._e.get("device_id")
        if not device_id:
            return False
        pct = max(0, min(100, int(pct)))
        if pct >= 100:
            ok = homeassistant.call_service("huawei_solar", "reset_maximum_feed_grid_power", {"device_id": device_id})
        else:
            ok = homeassistant.call_service("huawei_solar", "set_maximum_feed_grid_power_percent",
                                            {"device_id": device_id, "power_percentage": pct})
        if ok:
            self._last_pct = float(pct)
        return ok

    def get_export_limit_pct(self) -> float | None:
        return self._last_pct if self.supports_curtailment() else None
