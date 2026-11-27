"""GenericChargerDriver: täcker de flesta laddboxar utan en handbyggd drivrutin per
märke, genom HA:s generiska switch.turn_on/off och number.set_value (om laddaren
exponerar strömgräns som en vanlig number-entitet). Easees "dynamiska" gräns och
fasväxling är äkta märkesspecifika HA-tjänster utan generisk motsvarighet.

OCPP (lbbrhzn/ocpp, HA:s OCPP-integration) - lärdomar från SpotNav (henrikekblad/spotnav-home-
assistant, MIT, bekräftat mot riktig hårdvara: Charge Amps HALO):
  - Strömgränsen skrivs till sessionens gräns (number.<cp>_session_current_limit eller
    ..._connector_<n>_session_current_limit), ALDRIG till number.<cp>_maximum_current - den är
    laddboxens bestående tak. Sessionens gräns är 'unavailable' utan pågående laddning; det är normalt.
  - IEC 61851-laddare levererar inte under 6 A: en gräns mellan 0 och 6 A höjs till 6 A, och 0 A
    betyder "stäng av" (switch av), inte en gräns på 0 som laddboxen kan avvisa.
  - Högst en skrivning per 10 s per laddbox.
  - Statusen normaliseras till samma ord som Easee-drivrutinen (connector-statusen i OCPP 1.6),
    så resten av motorn (anslutning, laddstopp-vakten) fungerar likadant.

Strömgräns via tjänst (current_limit_service): vissa integrationer har ingen number-entitet för
laddströmmen utan en egen tjänst - t.ex. Charge Amps molnintegration (kirei/hass-chargeamps:
chargeamps.set_max_current). Då anges tjänsten på laddarnivå i husets config:

    charger:
      driver: generic
      current_limit_service:
        service: chargeamps.set_max_current   # domän.tjänst
        field: max_current                     # fältet som får amperetalet (standard: max_current)
        data: {charge_point: "2012...", connector: 1}   # valfria fasta fält
      entities: {switch: ..., status: ...}

Finns både current_limit (number) och current_limit_service används number-entiteten.
"""
import time

from drivers.host import homeassistant
from drivers.charger import ChargerDriver

MIN_CHARGE_A = 6
MIN_WRITE_INTERVAL_S = 10.0

# OCPP 1.6 connector-status (och vanliga generiska ord) -> samma ord som Easee-drivrutinen använder.
_STATUS = {
    # cFos Powerbrain sensor.py publishes numbered display values, not OCPP words (#226).
    "1:standby": "disconnected", "2:carconnected": "awaiting_start",
    "3:charging": "charging", "4:charging/vent": "charging",
    "5:error": "offline", "6:offline": "offline",
    "available": "disconnected", "preparing": "awaiting_start", "charging": "charging",
    "suspendedev": "completed", "suspendedevse": "paused", "finishing": "completed",
    "reserved": "awaiting_start", "unavailable": "offline", "faulted": "offline",
    "disconnected": "disconnected", "connected": "awaiting_start", "ready": "awaiting_start",
    "completed": "completed", "paused": "paused", "offline": "offline", "error": "offline",
}


def normalize_status(raw):
    if raw is None:
        return None
    key = str(raw).strip().lower().replace(" ", "").replace("_", "").replace("-", "")
    for k, v in _STATUS.items():
        if key == k.replace("_", ""):
            return v
    return str(raw).strip().lower()


def _parse_service(cfg) -> tuple | None:
    """{service: 'domän.tjänst', field?, data?} -> (domän, tjänst, fält, data). None om ogiltig/saknas."""
    if not isinstance(cfg, dict):
        return None
    name = str(cfg.get("service") or "").strip()
    if name.count(".") != 1 or not all(name.split(".")):
        if name:
            print(f"⚠️ current_limit_service: ogiltig tjänst '{name}' - ange domän.tjänst, t.ex. chargeamps.set_max_current")
        return None
    domain, service = name.split(".")
    data = cfg.get("data") if isinstance(cfg.get("data"), dict) else {}
    return domain, service, str(cfg.get("field") or "max_current"), dict(data)


class GenericChargerDriver(ChargerDriver):
    """Default för laddare utan egen drivrutin. Kräver bara en switch-entitet
    (på/av) - strömgräns är valfri, fasväxling stöds inte."""
    supports_phase_switch = False

    def __init__(self, id: str, entities: dict | None = None, current_limit_service: dict | None = None):
        self.id = id
        self._e = entities or {}
        self._svc = _parse_service(current_limit_service)
        self._last_write = {"amps": None, "t": 0.0}

    def read_state(self) -> dict:
        status_e = self._e.get("status")
        current_e = self._e.get("current_limit")
        import_e = self._e.get("current_import")
        raw = homeassistant._get_raw_state(status_e) if status_e else None
        # Laddeffekt (#140): entities.power_kw eller power - i kW eller W (enheten ur HA, annars > 100 = W)
        power_e = self._e.get("power_kw") or self._e.get("power")
        power_kw = None
        if power_e:
            w = homeassistant.get_power_w(power_e)
            unit = str(((homeassistant._states_cache.get(power_e) or {}).get("attributes") or {}).get("unit_of_measurement") or "")
            if w is not None:
                power_kw = w / 1000.0 if unit in ("W", "kW", "MW") or w > 100 else w
        return {
            "status": normalize_status(raw),
            "status_raw": raw,
            # current_a = uppmätt laddström (current_import); saknas den används den inställda gränsen (current_limit)
            "current_a": homeassistant._get_numeric_state(import_e) if import_e else
                         (homeassistant._get_numeric_state(current_e) if current_e else None),
            "current_is_limit": not import_e and bool(current_e),
            "power_kw": round(power_kw, 3) if power_kw is not None else None,
            "phases": None,
        }

    def set_limit_a(self, amps: int, reason: str | None = None) -> bool:
        amps = int(amps or 0)
        if amps <= 0:
            self.turn_off()
            self._last_write = {"amps": 0, "t": time.time()}
            return True
        amps = max(MIN_CHARGE_A, amps)
        current_e = self._e.get("current_limit")
        if not current_e and not self._svc:
            return False
        now = time.time()
        if self._last_write["amps"] == amps:
            return True
        if now - self._last_write["t"] < MIN_WRITE_INTERVAL_S:
            return False                                  # försök igen nästa varv
        if current_e:
            ok = homeassistant.set_number(current_e, amps)
        else:
            domain, service, field, data = self._svc
            ok = homeassistant.call_service(domain, service, {**data, field: amps})
        if ok:
            self._last_write = {"amps": amps, "t": now}
        return ok

    def set_phases(self, phases: int) -> None:
        pass

    def turn_on(self) -> None:
        switch_e = self._e.get("switch")
        if switch_e:
            homeassistant.set_switch(switch_e, True)

    def turn_off(self) -> None:
        switch_e = self._e.get("switch")
        if switch_e:
            homeassistant.set_switch(switch_e, False)
