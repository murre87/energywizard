"""ftw_device.py - Sourcefuls FTW-drivrutiner (Lua, srcfl/device-drivers) som EnergyWizard-drivrutiner.

En FTW-drivrutin pratar direkt med enheten (Modbus TCP, HTTP, MQTT) - utan Home Assistant-integration. Den körs av
lua_host.LuaDriver i en egen tråd som anropar driver_poll() i drivrutinens egen takt och sparar det senaste den
rapporterat (host.emit). Samma enhet kan vara både batteri och solceller (en hybridväxelriktare): instansen delas.

Installationen:

    battery:
      enabled: true
      driver: ftw
      ftw:
        driver: sungrow          # filnamnet i smartbox/ftw_drivers/ (utan .lua)
        host: 192.168.1.50
        port: 502
        unit_id: 1
        config: {}               # skickas till drivrutinens driver_init (t.ex. nominal_w, inloggning)
      control: samarbete         # styr kräver att drivrutinen är verifierad för styrning (FTW_CONTROL_VERIFIED)
                                 # eller control_unverified: true (på egen risk, för den som provar)
    solar:
      enabled: true
      driver: ftw
      ftw: {driver: sungrow, host: 192.168.1.50}

Tecken (Sourcefuls datamodell): battery.w + = laddar (som hos oss), pv.w - = produktion (vänds), meter.w + = import.
Styrning: driver_command("battery", W) med + = ladda och - = ladda ur, driver_default_mode() = växelriktarens eget
läge. FTW:s egen vakthund släpper styrningen efter 60 s utan nytt kommando, så refresh() skickar om varje varv.
"""
import os
import re
import threading
import time

from drivers.battery import BatteryDriver
from drivers.solar import SolarDriver

FTW_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ftw_drivers")
_ERROR_TOKEN = re.compile(r"[^\s:'\"]+")
# Drivrutiner vars styrning provats på riktig hårdvara (FTW:s egen verifiering eller hos oss). Tomt tills vidare:
# all FTW-styrning är avstängd om inte installationen uttryckligen säger control_unverified: true.
FTW_CONTROL_VERIFIED: set = set()
_instances: dict = {}
_lock = threading.Lock()


def available() -> list:
    """FTW-drivrutinerna som följer med (filnamn utan .lua)."""
    try:
        return sorted(f[:-4] for f in os.listdir(FTW_DIR) if f.endswith(".lua"))
    except OSError:
        return []


class FtwDevice:
    """En körande FTW-drivrutin för en enhet. Delas mellan batteri- och solomslaget för samma enhet."""

    def __init__(self, name, host, port=502, unit_id=1, config=None, allow_write=False):
        from lua_host import LuaDriver
        path = os.path.join(FTW_DIR, os.path.basename(str(name)) + ".lua")
        if not os.path.exists(path):
            raise ValueError(f"FTW-drivrutinen '{name}' finns inte (finns: {', '.join(available())})")
        self.name, self.emits, self.ok_at, self.error = name, {}, None, None
        self.host, self.port = host, port
        self.drv = LuaDriver(path, host=host, port=port, unit_id=unit_id, config=config or {}, allow_write=allow_write)
        self._stop = False
        self._cmd_lock = threading.Lock()
        threading.Thread(target=self._loop, daemon=True, name=f"ftw-{name}").start()

    def _loop(self):
        while not self._stop:
            nxt = 5000
            try:
                with self._cmd_lock:
                    em, nxt = self.drv.poll()
                self.emits, self.ok_at, self.error = em, time.time(), None
            except Exception as e:
                self.error = f"{type(e).__name__}: {e}"
                print(f"⚠️ FTW {self.name}: {self.error}")
                note_poll_failure(self.name, self.host, e)
                nxt = 15000
            time.sleep(max(1.0, min(60.0, nxt / 1000.0)))

    def fresh(self, max_age=120):
        return self.ok_at is not None and time.time() - self.ok_at < max_age

    def command(self, action, power_w=0, balance=False):
        import shadow
        if shadow.active():
            shadow.record(f"FTW {self.name}", f"{action} {power_w} W" + (" (balance)" if balance else ""))
            return True
        with self._cmd_lock:
            context = {"source": "energywizard", "duration_ms": 120000}
            if balance:
                context["balance"] = True
            return self.drv.command(action, power_w, context)

    def default_mode(self):
        import shadow
        if shadow.active():
            shadow.record(f"FTW {self.name}", "default mode")
            return True
        with self._cmd_lock:
            f = self.drv.L.globals().driver_default_mode
            return bool(f()) if f is not None else False


def poll_failure_note(name, host, exc) -> str:
    """Sanerad rad till supportutdraget. Lua-texten behövs för att se felet (#297); värd och sökväg följer inte med."""
    import support_bundle
    # Scan each token once; nested path repetitions can backtrack exponentially.
    def strip_lua_path(match):
        token = match.group(0)
        filename = token.rsplit("/", 1)[-1]
        return filename if token.startswith("/") and ".lua" in filename else token

    msg = _ERROR_TOKEN.sub(strip_lua_path, str(exc))
    if host:
        msg = msg.replace(str(host), "<värd>")
    return support_bundle.sanitize(f"FTW {name}.poll: {type(exc).__name__}: {msg}")


def note_poll_failure(name, host, exc) -> None:
    """Spara raden innan felrapporten byggs, så utdraget innehåller Lua-texten och inte bara feltypen."""
    try:
        import support_bundle
        support_bundle.note_error_line(poll_failure_note(name, host, exc))
    except Exception:
        pass
    try:                                     # syns i insamlaren (högst en gång i timmen per feltyp), aldrig osanerad feltext
        import telemetry
        telemetry.report_error({}, f"ftw_{name}.poll", type(exc).__name__)
    except Exception:
        pass


def status() -> list:
    """Läget för varje FTW-enhet, för Översikt (#184-#186): en växelriktare som inte svarar gav tomma flikar utan
    förklaring. {"driver", "host", "port", "ok", "error", "has": [pv/battery/meter som drivrutinen faktiskt ger]}."""
    out = []
    with _lock:
        devs = list(_instances.values())
    for d in devs:
        out.append({"driver": d.name, "host": d.host, "port": d.port, "ok": d.fresh(),
                    "error": None if d.fresh() else (d.error or "inget svar än"),
                    "has": sorted(k for k in ("pv", "battery", "meter") if (d.emits or {}).get(k))})
    return out


def device(cfg: dict, allow_write=False) -> FtwDevice:
    """Delad instans per (drivrutin, host, port, unit_id)."""
    key = (cfg.get("driver"), cfg.get("host"), int(cfg.get("port") or 502), int(cfg.get("unit_id") or 1))
    with _lock:
        d = _instances.get(key)
        if d is None:
            d = FtwDevice(cfg.get("driver"), cfg.get("host"), key[2], key[3], cfg.get("config") or {}, allow_write=allow_write)
            _instances[key] = d
        elif allow_write and not d.drv.allow_write:
            d.drv.allow_write = True
        return d


class FtwBatteryDriver(BatteryDriver):
    def __init__(self, ftw: dict, capacity_kwh=None, control="samarbete", control_unverified=False, max_power_w=5000):
        self.capacity_kwh = capacity_kwh
        self._name = (ftw or {}).get("driver")
        self._control = control == "styr" and (self._name in FTW_CONTROL_VERIFIED or bool(control_unverified))
        self._dev = device(ftw or {}, allow_write=self._control)
        self._pmax = float(max_power_w or 5000)
        self._last = None
        self._balance = False

    def read_state(self) -> dict:
        b = self._dev.emits.get("battery") or {}
        if not self._dev.fresh():
            return {"soc_pct": None, "power_w": None, "capacity_kwh": self.capacity_kwh, "mode": None}
        soc = b.get("soc")
        if isinstance(soc, (int, float)) and soc <= 1.0 and soc > 0:
            soc = soc * 100.0                                # FTW skickar <= 1 % som andel
        cap = b.get("capacity_wh")
        return {"soc_pct": soc, "power_w": b.get("w", b.get("W")), "mode": None,
                "power_sample_at": b.get("power_sample_at"),
                "soc_sample_at": b.get("soc_sample_at") if getattr(self, "_name", None) == "ferroamp" else None,
                "soc_source": "ferroamp_mqtt_received" if getattr(self, "_name", None) == "ferroamp" else None,
                "modules": b.get("modules") or {},
                "capacity_kwh": self.capacity_kwh or (cap / 1000.0 if isinstance(cap, (int, float)) and cap > 0 else None)}

    def set_balancing(self, active):
        self._balance = bool(active)

    def supports_control(self) -> bool:
        return self._control

    def set_mode(self, mode: str) -> bool:
        return False

    def supported_intents(self) -> set:
        return {"auto", "charge", "discharge", "idle", "hold"} if self._control else set()

    def apply_intent(self, intent: str, power_w: float | None = None) -> bool:
        if not self._control:
            return False
        p = abs(float(power_w)) if power_w else self._pmax
        if intent == "auto":
            ok = self._dev.default_mode()
        elif intent == "charge":
            ok = self._dev.command("battery", p, balance=True) if self._balance else self._dev.command("battery", p)
        elif intent == "discharge":
            ok = self._dev.command("battery", -p)
        elif intent in ("idle", "hold"):
            ok = self._dev.command("battery", 0)
        else:
            return False
        import shadow
        # Simulated requests must not become keepalive authority when shadow
        # mode is later disabled; a fresh controller decision is required.
        self._last = (intent, p) if ok and not shadow.active() else None
        return bool(ok)

    def refresh(self, now: float | None = None) -> bool:
        """FTW:s vakthund släpper efter 60 s - skicka om pågående kommando varje varv."""
        if self._control and self._last and self._last[0] != "auto":
            return self.apply_intent(*self._last)
        return False


class FtwSolarDriver(SolarDriver):
    def __init__(self, ftw: dict, control_unverified=False):
        self._name = (ftw or {}).get("driver")
        # Begränsningen i FTW tar watt: kräver växelriktarens märkeffekt (ftw.config.nominal_w)
        self._nominal = float(((ftw or {}).get("config") or {}).get("nominal_w") or 0)
        self._curtail = self._nominal > 0 and (self._name in FTW_CONTROL_VERIFIED or bool(control_unverified))
        self._dev = device(ftw or {}, allow_write=self._curtail)
        self._limit = None

    def read_production(self) -> dict:
        pv = self._dev.emits.get("pv") or {}
        if not self._dev.fresh():
            return {"pv_power_w": None, "today_kwh": None, "status": None}
        w = pv.get("w", pv.get("W"))
        return {"pv_power_w": abs(w) if isinstance(w, (int, float)) else None,          # FTW: negativt = produktion
                "today_kwh": None, "status": None}

    def supports_curtailment(self) -> bool:
        return self._curtail

    def set_export_limit_pct(self, pct: int) -> bool:
        if not self._curtail:
            return False
        ok = self._dev.command("curtail_disable", 0) if pct >= 100 else self._dev.command("curtail", self._nominal * max(0, pct) / 100.0)
        if ok:
            self._limit = float(pct)
        return bool(ok)

    def get_export_limit_pct(self) -> float | None:
        return self._limit if self._curtail else None
