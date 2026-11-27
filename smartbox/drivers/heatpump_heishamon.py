"""HeishaMonHeatPumpDriver: Panasonic Aquarea via HeishaMon (ESP-kort på pumpens CN-CNT-kontakt), lokalt över HTTP.

KÄLLOR (lästa 2026-11-03 i github.com/Egyras/HeishaMon, master):
- MQTT-Topics.md: ämnesnamn, enheter och kommandon med värdeområden.
- HeishaMon/webfunctions.cpp handleJsonOutput: GET /json svarar {"heatpump":[{"Topic":"TOP0","Name":"Heatpump_State",
  "Value":1,"Description":"..."}, ...], ...}. Value är ett tal utom Error (TOP44), som är en sträng.
- HeishaMon/HeishaMon.ino route /command + commands.h: GET /command?<Kommando>=<värde> med samma namn som MQTT
  (SetHeatpump, SetZ1HeatRequestTemperature, SetOperationMode, SetDHWTemp, SetHolidayMode, SetQuietMode).
- decode.h/decode.cpp: Heating_Mode (TOP76) 0 = kompensationskurva, 1 = direkt framledningstemperatur. Error är
  "No error" eller F../H..-kod.

ALDRIG KÖRD MOT EN RIKTIG PUMP. Bara det som källan bekräftar används; resten svarar False/None.

Kurvförskjutning (Matter-lagrets adjust_curve): bara i kurvläge (Heating_Mode 0). Då är Z1_Heat_Request_Temp en
förskjutning -5..5, och vi skriver husets grundförskjutning (heat_pump.base_shift i house_config.yaml, standard 0)
plus vår förskjutning. I direktläge skrivs ingenting (det är en absolut temperatur och skulle tolkas helt fel).
Paus = kurvan till lägsta förskjutningen (-5), INTE SetHeatpump 0 (issue #109: en avstängd Aquarea tappar cirkulation
och frostskydd på vintern, och kompressorn får omstartsskydd efteråt). Pumpen "vilar" men är på. Bara i kurvläge; i
direktläge går det inte att pausa. tick() släpper pausen inom tidsgränsen och skriver tillbaka grund + vår förskjutning.

set_operating_mode tar bara de normaliserade lägena i drivers.heatpump.MODES. main.py skickar idag Thermias råa
heltalskoder; de avvisas här i stället för att gissas om till Panasonics koder.
"""
import requests

from drivers.heatpump import HeatPumpDriver

# Matter-lika lägen -> SetOperationMode (0-6 enligt MQTT-Topics.md). "off" sköts med SetHeatpump.
_MODE_TO_SET = {"heat": 0, "cool": 1, "auto": 2, "dhw": 3, "heat_dhw": 4, "cool_dhw": 5, "auto_dhw": 6}
# Operating_Mode_State (TOP4) 0-8: 0 heat, 1 cool, 2 auto(heat), 3 DHW, 4 heat+DHW, 5 cool+DHW, 6 auto(heat)+DHW,
# 7 auto(cool), 8 auto(cool)+DHW
_STATE_TO_MODE = {0: "heat", 1: "cool", 2: "auto", 3: "dhw", 4: "heat_dhw", 5: "cool_dhw", 6: "auto_dhw",
                  7: "auto", 8: "auto_dhw"}
_TIMEOUT = 5


class HeishaMonHeatPumpDriver(HeatPumpDriver):
    def __init__(self, host: str | None = None, base_shift: float = 0.0, indoor_from_z1: bool = False, session=None):
        self._host = (host or "").strip().rstrip("/")
        self._base_shift = float(base_shift or 0)
        self._indoor_from_z1 = bool(indoor_from_z1)   # Z1_Temp är rumstemp bara om pumpen har rumsgivare för zon 1
        self._http = session or requests
        self._resting = False                         # pausad = kurvan på -5 (se _write_paused)
        self._warned = set()

    # --- HTTP -----------------------------------------------------------------------------------------------------
    def _url(self, path: str) -> str:
        base = self._host if self._host.startswith("http") else f"http://{self._host}"
        return f"{base}{path}"

    def _values(self) -> dict:
        if not self._host:
            return {}
        try:
            r = self._http.get(self._url("/json"), timeout=_TIMEOUT)
            r.raise_for_status()
            return {t.get("Name"): t.get("Value") for t in (r.json().get("heatpump") or []) if t.get("Name")}
        except (requests.RequestException, ValueError, AttributeError) as e:
            self._warn_once("read", f"⚠️ HeishaMon {self._host}: kunde inte läsa /json ({e})")
            return {}

    def _command(self, name: str, value) -> bool:
        if not self._host:
            return False
        from drivers.host import shadow
        if shadow.active():
            shadow.record("HeishaMon", f"{name}={value}")
            return True
        try:
            r = self._http.get(self._url("/command"), params={name: value}, timeout=_TIMEOUT)
            r.raise_for_status()
            return True
        except requests.RequestException as e:
            print(f"⚠️ HeishaMon {self._host}: {name}={value} misslyckades ({e})")
            return False

    def _warn_once(self, key: str, msg: str):
        if key not in self._warned:
            print(msg)
            self._warned.add(key)

    @staticmethod
    def _num(v):
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        return None if f == -1 else f   # -1 = okänt enligt MQTT-Topics.md

    # --- befintligt lager -------------------------------------------------------------------------------------------
    def read_sensors(self) -> dict:
        v = self._values()
        if not v:
            return {}
        n = self._num
        freq = n(v.get("Compressor_Freq"))
        use = [x for x in (n(v.get("Heat_Power_Consumption")), n(v.get("DHW_Power_Consumption")),
                           n(v.get("Cool_Power_Consumption"))) if x is not None]
        return {
            "indoor_temp": n(v.get("Z1_Temp")) if self._indoor_from_z1 else None,
            "outdoor_temp": n(v.get("Outside_Temp")),
            "forward_temp": n(v.get("Main_Outlet_Temp")),
            "return_temp": n(v.get("Main_Inlet_Temp")),
            "water_temp": n(v.get("DHW_Temp")),
            "degree_minutes": None,
            "compressor_running": None if freq is None else freq > 0,
            "compressor_power_kw": round(sum(use) / 1000, 3) if use else None,
            "compressor_power_w": round(sum(use)) if use else None,    # uppmätt el (#178: används i lastnedbrytningen)
            # operating_mode är Thermias koder i main.py/loggen (0 = av, SMALLINT); Panasonics koder betyder annat
            # (0 = värme), så fältet lämnas tomt. Läget finns i read_state()["mode"].
            "operating_mode": None,
            "_raw": v,
        }

    def set_room_temp(self, target_c: float) -> bool:
        self._warn_once("room", "⚠️ HeishaMon: ingen rumsbörvärdesstyrning (pumpen styr på kurva eller framledning) - "
                                "använd adjust_curve. Ignoreras.")
        return False

    def set_water_stop_temp(self, target_c: float) -> bool:
        """Varmvattnets måltemperatur (SetDHWTemp, 40-75 °C enligt MQTT-Topics.md)."""
        return self._command("SetDHWTemp", int(round(max(40, min(75, float(target_c))))))

    def set_water_start_temp(self, target_c: float) -> bool:
        self._warn_once("dhw_start", "⚠️ HeishaMon: ingen separat starttemperatur för varmvatten - ignoreras.")
        return False

    def set_heating_start_temp(self, target_c: float) -> bool:
        self._warn_once("heat_start", "⚠️ HeishaMon: värmestopp-tröskeln skrivs inte (ej verifierad) - ignoreras.")
        return False

    def set_operating_mode(self, mode) -> bool:
        if mode == "off":
            return self._command("SetHeatpump", 0)
        if isinstance(mode, str) and mode in _MODE_TO_SET:
            return self._command("SetOperationMode", _MODE_TO_SET[mode])
        self._warn_once(f"mode:{mode!r}", f"⚠️ HeishaMon: okänt läge {mode!r} (tar bara {sorted(_MODE_TO_SET)} / 'off') - ignoreras.")
        return False

    # --- Matter-likt lager ------------------------------------------------------------------------------------------
    def _state_extra(self, s: dict) -> dict:
        v = s.get("_raw") or {}
        n = self._num
        on = n(v.get("Heatpump_State"))
        state = n(v.get("Operating_Mode_State"))
        mode = "off" if on == 0 else _STATE_TO_MODE.get(None if state is None else int(state))
        out = [x for x in (n(v.get("Heat_Power_Production")), n(v.get("DHW_Power_Production")),
                           n(v.get("Cool_Power_Production"))) if x is not None]
        heat_w = sum(out) if out else None
        use_w = None if s.get("compressor_power_kw") is None else s["compressor_power_kw"] * 1000
        err = v.get("Error")
        defrost = n(v.get("Defrosting_State"))
        return {"mode": mode, "heat_output_w": heat_w,
                "cop": round(heat_w / use_w, 2) if heat_w is not None and use_w else None,
                "fault": None if err in (None, "", "No error") else str(err),
                "defrosting": None if defrost is None else defrost == 1}

    def _write_curve_offset(self, offset: float) -> bool:
        v = self._values()
        if self._num(v.get("Heating_Mode")) != 0:
            self._warn_once("curve", "⚠️ HeishaMon: kurvförskjutning bara i kurvläge (Heating_Mode 0) - inget skickat.")
            return False
        if self._resting:                             # pausad: skrivs när pausen släpps
            return True
        shift = max(-5, min(5, round(self._base_shift + offset)))
        return self._command("SetZ1HeatRequestTemperature", shift)

    def _write_paused(self, paused: bool) -> bool:
        if self._num(self._values().get("Heating_Mode")) != 0:
            self._warn_once("pause", "⚠️ HeishaMon: paus bara i kurvläge (Heating_Mode 0) - pumpen stängs aldrig av.")
            return False
        if paused:
            if not self._command("SetZ1HeatRequestTemperature", -5):
                return False
            self._resting = True
            return True
        shift = max(-5, min(5, round(self._base_shift + self._curve_offset)))
        if not self._command("SetZ1HeatRequestTemperature", shift):
            return False
        self._resting = False
        return True
