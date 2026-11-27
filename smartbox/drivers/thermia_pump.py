import os
import re
import threading
import time

from drivers.host import homeassistant, shadow
_READ_TRANSPORT_ERRORS = (OSError,)
try:                                # finns i motorns bild men inte i mobilappens (som bara läser installationen)
    from pymodbus.client import ModbusTcpClient
    from pymodbus.exceptions import ConnectionException, ModbusIOException
    _READ_TRANSPORT_ERRORS += (ConnectionException, ModbusIOException)
except ImportError:                 # pragma: no cover
    ModbusTcpClient = None
 
# --- INSTÄLLNINGAR FÖR Thermia Diplomat Optimum G3 via Husdata H66 ---
# Adressen kommer från installationen: PUMP_IP (+ PUMP_IP_FALLBACK) i miljön eller heat_pump.connection.modbus_host
# i house_config.yaml (configure()). Inga inbyggda standardadresser - de var ett enskilt hus adresser, och en
# NIBE-ägare som råkat välja Husdata fick "kunde inte ansluta" mot det huset varje minut (#165, 2026-11-06).
PUMP_IPS = list(dict.fromkeys(ip for ip in (os.environ.get("PUMP_IP", "").strip(), os.environ.get("PUMP_IP_FALLBACK", "").strip()) if ip))
_no_ip_warned = False


def configure(hosts) -> None:
    """Pumpens adress(er) ur installationen (heat_pump.connection.modbus_host, sträng eller lista). Miljön går före."""
    global PUMP_IPS
    if PUMP_IPS:
        return
    hs = [hosts] if isinstance(hosts, str) else list(hosts or [])
    PUMP_IPS = list(dict.fromkeys(str(h).strip() for h in hs if str(h or "").strip() and "XXX" not in str(h)))
PORT = 502
TIMEOUT = int(os.environ.get("PUMP_TIMEOUT", 5))
DEVICE_ID = 1

_active_ip_index = 0

# H66 tar bara EN Modbus-klient åt gången (Husdatas biblioteksdokumentation, och mätt mot en riktig H66 2026-11-20:
# en andra samtidig klient får TCP-anslutning men aldrig något svar, 3 försök och timeout). Därför får inte två
# trådar i motorn prata med gatewayen samtidigt - låset serialiserar all Modbus-trafik i den här processen (#466).
_io_lock = threading.RLock()

# En ej inkopplad temperaturgivare ger ett fast skenvärde. Uppmätt på en Thermia Diplomat via H66: -40,0 °C
# (Cooling-givaren som saknas); Husdatas bibliotek för Rego 600 anger -48,3 °C. Båda blir None så att loggar och
# styrning inte räknar med en temperatur som inte finns (#466). Utetemperaturen får vara -40,0 (kan hända i norr).
_NO_SENSOR_RAW = (-483, -400)


def _serialized(fn):
    """All Modbus-trafik mot pumpen går en i taget (se _io_lock)."""
    import functools

    @functools.wraps(fn)
    def wrapper(*a, **kw):
        with _io_lock:
            return fn(*a, **kw)
    return wrapper

def _connect_client(ip):
    client = ModbusTcpClient(ip, port=PORT, timeout=TIMEOUT)
    connected = False
    try:
        connected = client.connect()
        return client if connected else None
    finally:
        if not connected:
            client.close()

def _get_client():
    """Försöker ansluta till Husdata. Byter automatiskt IP om den primära är nere."""
    global _active_ip_index
    if not PUMP_IPS:
        return None
    _active_ip_index = min(_active_ip_index, len(PUMP_IPS) - 1)
    client = _connect_client(PUMP_IPS[_active_ip_index])
    if client:
        return client
    
    # Om den aktiva IP:n misslyckades, testa de andra
    for i, ip in enumerate(PUMP_IPS):
        if i == _active_ip_index:
            continue
        client = _connect_client(ip)
        if client:
            _active_ip_index = i
            print(f"🔄 Husdata: Bytte aktiv IP-adress till {ip}")
            return client
    return None

def _to_signed(val):
    """
    Konverterar Unsigned 16-bit till Signed 16-bit.
    Krävs för minustemperaturer (t.ex. Brine Out på vintern).
    """
    return val - 65536 if val > 32767 else val

_last_read = {"transport_error": False}
_RETRY_PAUSE_S = 1.5
_READ_RETRY = True


@_serialized
def read_sensors():
    """Läser pumpen; vid ett nätverksfel (anslutningen återställd, inget svar) ett enda nytt försök efter en kort paus.
    Gatewayen tar en klient åt gången, så en annan läsare (Home Assistants egen Modbus-anslutning, mobilappen) som
    råkar vara inne samtidigt ger ett sådant fel som försvinner av sig självt (mätt mot en riktig H66, #466). Är
    gatewayen helt nere (kan inte ansluta) görs inget omförsök."""
    _last_read["transport_error"] = False
    res = _read_sensors_once()
    if res is None and _READ_RETRY and _last_read["transport_error"]:
        time.sleep(_RETRY_PAUSE_S)
        res = _read_sensors_once()
    return res


def _read_sensors_once():
    """
    Läser in sensordata direkt från Husdata via Modbus TCP.
    Returnerar en dict med alla värden, eller None vid fel.
    """
    global _no_ip_warned
    if not PUMP_IPS:
        if not _no_ip_warned:
            print("⚠️ Husdata: ingen adress till värmepumpen angiven (PUMP_IP eller heat_pump.connection.modbus_host) - "
                  "läser inte pumpen. Har du inte Thermia/Husdata: välj din värmepump i installationsguiden.")
            _no_ip_warned = True
        return None
    try:
        client = _get_client()
        if not client:
            # Tillfällig nätverks-/anslutningsstörning — ⚠️ (grå i Admin), inte programfel (#299).
            print(f"⚠️ Husdata: Kunde inte ansluta via Modbus TCP på någon IP: {PUMP_IPS}")
            return None

        res_in = None
        res_hold = None
        try:
            try:
                # FIX #18: pymodbus 3.9+/3.12 använder device_id= (verifierat 3.12.1).
                # Provas FÖRST så rätt enhets-id alltid skickas (inte bara default 1).
                res_in = client.read_input_registers(address=0, count=40, device_id=DEVICE_ID)
                res_hold = client.read_holding_registers(address=13, count=11, device_id=DEVICE_ID)
            except TypeError:
                try:
                    # Nyare/mellanvarianter av pymodbus (3.x)
                    res_in = client.read_input_registers(address=0, count=40, slave=DEVICE_ID)
                    res_hold = client.read_holding_registers(address=13, count=11, slave=DEVICE_ID)
                except TypeError:
                    try:
                        # Äldre pymodbus (2.x)
                        res_in = client.read_input_registers(address=0, count=40, unit=DEVICE_ID)
                        res_hold = client.read_holding_registers(address=13, count=11, unit=DEVICE_ID)
                    except TypeError:
                        # Sista fallback: Vissa versioner accepterar inga keywords alls.
                        # OBS: tappar enhets-id (förlitar oss på bibliotekets default).
                        res_in = client.read_input_registers(address=0, count=40)
                        res_hold = client.read_holding_registers(address=13, count=11)
        finally:
            client.close()

        # FIX: Skydda mot None-svar (t.ex. om biblioteket returnerar None) innan isError()
        if res_in is None or res_hold is None:
            print("⚠️ Husdata: Fick inget svar (None) vid läsning av Modbus-register")
            return None

        if res_in.isError() or res_hold.isError():
            print("⚠️ Husdata: Fick felsvar vid läsning av Modbus-register")
            return None

        reg = res_in.registers
        _verify_register_map_once(PUMP_IPS[min(_active_ip_index, len(PUMP_IPS) - 1)])
        hold = res_hold.registers

        def get_temp(idx, allow_minus_40=False):
            """Temperaturer från Husdata är oftast heltal multiplicerat med 10. None för en givare som inte är
            inkopplad (fast skenvärde, se _NO_SENSOR_RAW)."""
            raw = _to_signed(reg[idx])
            if raw in _NO_SENSOR_RAW and not (allow_minus_40 and raw == -400):
                return None
            return raw / 10.0

        return {
            # Temperaturer (Input Registers)
            "return_temp":        get_temp(0),      # 0: Radiator Return
            "forward_temp":       get_temp(1),      # 1: Radiator Forward
            "brine_in_temp":      get_temp(2),      # 2: Brine in
            "brine_out_temp":     get_temp(3),      # 3: Brine out
            "outdoor_temp":       get_temp(4, allow_minus_40=True),      # 4: Outdoor
            "indoor_temp":        get_temp(5),      # 5: Indoor
            "water_temp_top":     get_temp(6),      # 6: Warm water 1 / Top
            "hot_gas_temp":       get_temp(7),      # 7: Pressure tube / Hot gas
            "cooling_temp":       get_temp(8),      # 8: Cooling
            "degree_minutes":     _to_signed(reg[9]), # 9: Degree min/integral
            "calc_forward_temp":  get_temp(10),     # 10: Heating setpoint
            "circ_pump_speed":    reg[11] / 10.0,   # 11: Circ pump speed %
            "brine_pump_speed":   reg[12] / 10.0,   # 12: Brine pump speed %

            # Kompatibilitetsfält (saknas, men skickas som None så logger inte kraschar)
            "water_temp_mid":     None, "suction_gas_temp": None, 
            "compressor_temp": None, "drain_pan_temp": None, "hc_forward_temp": None,
            
            # Inställningar (Holding Registers) offset 0 = register 13. Hela namngivna kartan
            # (Husdata H66 / Thermia Diplomat) exponeras nu så GPM/dashboard kan samverka med
            # pumpens egna inställningar i stället för att gissa/kringgå.
            "water_setpoint":      _to_signed(hold[0]) / 10.0, # 13 (0208): Warm Water stop temp
            # Husdata har ofta Operating Mode inställt som "Temp" (typ 0), vilket gör att 1 blir 10.
            "operating_mode":      int(hold[1] / 10) if hold[1] >= 10 else int(hold[1]),  # 14 (2201)
            "room_temp_setpoint":  _to_signed(hold[2]) / 10.0, # 15 (0203): Room temp setpoint
            "room_sensor_influence": _to_signed(hold[3]) / 10.0, # 16 (2204): Room sensor influence
            "heat_curve_left":     _to_signed(hold[4]) / 10.0, # 17 (0205): Heat set 1, CurveL
            "heat_curve_right":    _to_signed(hold[5]) / 10.0, # 18 (0206): Heat set 2, CurveR
            # 19 (0211) "Heating setpnt./start" = utetemp-tröskel där värmesäsongen startar/stoppar
            # (i praktiken VÄRMESTOPP: över denna utetemp slutar pumpen värma huset i auto-läge).
            "heating_setpnt_start": _to_signed(hold[6]) / 10.0,
            "heat_stop_outdoor":   _to_signed(hold[6]) / 10.0, # alias: tydligare namn för värmestoppet
            "water_start_temp":    _to_signed(hold[7]) / 10.0, # 20 (0212): Warm Water start temp
            "cooling_temp_setpoint": _to_signed(hold[8]) / 10.0, # 21 (0214): Cooling temp setpoint
            "outdoor_temp_offset": _to_signed(hold[9]) / 10.0, # 22 (0217): Outdoor temp offset
            "external_control":    _to_signed(hold[10]) / 10.0, # 23 (0233): External control

            # Historik och Kompressor (Input Registers)
            "compressor_power_kw":  0.0,  # Beräknas via elmätare i main.py ändå
            "compressor_speed_pct": 0.0,
            "compressor_running":   reg[25],        # 25: Compressor
            "pump_heat_running":    reg[29],        # 29: Pump Radiator
            "pump_radiator_running":reg[29],
            "add_heat_1":           reg[26],        # 26 (1A02): Add heat step 1 (0/1), elpatron steg 1
            "add_heat_2":           reg[27],        # 27 (1A03): Add heat step 2 (0/1)
            "add_heat_pct":         reg[31] / 10.0, # 31 (3104): Add heat status, procent
            "hotwater_valve":       reg[30],        # 30: Switch valve 1 (1A07): 0 = husvärme, 1 = varmvatten

            # Larm & Historik
            "alarm_active":         reg[32],        # 32: Alarm
            "alarm_code":           reg[33],        # 33: Alarm Code
            "compressor_runtime_h": reg[34],        # 34: Compr. Runtime
            "compr_kwh_total":      0.0,            # Du mäter VP separat via meter.py ändå
            "aux_runtime_h":        reg[35],        # 35: Aux runtime
            "aux_runtime_2_h":      reg[36],        # 36: Aux runtime 2
            "warm_water_runtime_h": reg[37],        # 37: Warm water runtime
            "power_consumption_w":  reg[38],        # 38: Power consumption
            # H66:ans egen summa av de watt man angett per statusvariabel (kompressor, tillsats, pumpar). 0 = inga watt
            # inställda: då är det inget mätvärde, och motorn använder sin uppskattning ur framledningen (#466).
            "compressor_power_w":   float(reg[38]) if reg[38] > 0 else None,
            "accumulated_consumption_kwh": reg[39] / 10.0, # 39: Accumulated consumption
        }

    except _READ_TRANSPORT_ERRORS as e:
        # Tillfälliga nätverksfel — ⚠️ så Admin räknar dem gråa (#299).
        print(f"⚠️ Husdata: Nätverksfel vid läsning (Modbus): {e}")
        _last_read["transport_error"] = True
        return None
    except Exception as e:
        print(f"❌ Husdata: Oväntat fel vid läsning (Modbus): {e}")
        return None

@_serialized
def _write_holding(reg_addr, value, retries=3):
    """Hjälpfunktion för att skriva till ett Modbus Holding-register med retries."""
    if not PUMP_IPS:                          # ingen pump angiven (#172: skuggläget visade skrivningar till en pump som inte finns)
        return False
    try:
        value = int(value)
    except (TypeError, ValueError):
        print(f"❌ Husdata: vägrar skriva '{value}' till register {reg_addr} (inte ett heltal).")
        return False
    if not _write_value_ok(reg_addr, value):
        return False
    if shadow.active():                       # skuggläge: pumpen rörs inte, åtgärden loggas
        shadow.record("Thermia (Husdata) register", f"{reg_addr} = {value}")
        return True
    for attempt in range(retries):
        client = _get_client()
        if client:
            try:
                try:
                    # FIX #18: device_id= provas FÖRST (pymodbus 3.9+/3.12) så rätt enhets-id skrivs.
                    res = client.write_register(address=reg_addr, value=int(value), device_id=DEVICE_ID)
                except TypeError:
                    try:
                        res = client.write_register(address=reg_addr, value=int(value), slave=DEVICE_ID)
                    except TypeError:
                        try:
                            res = client.write_register(address=reg_addr, value=int(value), unit=DEVICE_ID)
                        except TypeError:
                            # Sista fallback utan keywords (tappar enhets-id).
                            res = client.write_register(address=reg_addr, value=int(value))
                if res is None:
                    print(f"⚠️ Husdata: Fick inget svar (None) vid skrivning till register {reg_addr} (Försök {attempt+1})")
                elif not res.isError():
                    return True
                else:
                    print(f"⚠️ Husdata: Fick fel från värmepumpen vid skrivning till register {reg_addr} (Försök {attempt+1})")
            except Exception as e:
                print(f"⚠️ Husdata: Oväntat fel vid skrivning till {reg_addr} (Modbus): {e} (Försök {attempt+1})")
            finally:
                client.close()
        else:
            print(f"⚠️ Husdata: Kunde inte ansluta via Modbus för att skriva till {reg_addr} (Försök {attempt+1})")
        
        if attempt < retries - 1:
            time.sleep(2)
    print(f"❌ Husdata: Misslyckades att skriva till register {reg_addr} efter {retries} försök.")
    return False

# Gränser per skrivbart register (råvärde = värde x 10). Pumpen anger dem själv på H66:ans startsida
# ("Setting between: 30 and 65"); de läses därifrån (_live_limits). Tabellen är reserv när sidan inte går att läsa och
# är avläst på en Thermia Diplomat via H66 (firmware 360301, 2026-11-20). Ett värde utanför går aldrig till pumpen:
# ett fel längre upp (fel enhet, NaN, 0 i stället för 20) ska stoppas här, med en tydlig logg. Husdatas bibliotek
# kontrollerar också intervall före varje skrivning (#466).
_WRITE_LIMITS = {
    13: (300, 650),     # Warm Water stop temp, 30-65 °C
    14: (0, 40),        # Operating mode (x10), 0-4
    15: (100, 290),     # Room temp setpoint, 10-29 °C
    16: (0, 100),       # Room sensor influence, 0-10
    17: (220, 560),     # Heat set 1, CurveL, 22-56 °C
    18: (400, 850),     # Heat set 2, CurveR, 40-85 °C
    19: (0, 410),       # Heating setpnt./start, 0-41 °C
    20: (290, 550),     # Warm Water start temp, 29-55 °C
}
_LIMITS_TTL_S = 3600
_limits_cache = {"at": 0.0, "ip": None, "limits": {}}


def _write_value_ok(reg_addr, value) -> bool:
    lo, hi = _live_limits().get(reg_addr) or _WRITE_LIMITS.get(reg_addr, (-32768, 32767))
    if not lo <= value <= hi:
        print(f"❌ Husdata: vägrar skriva {value} till register {reg_addr} (pumpen tillåter {lo}-{hi}, råvärde x10). "
              f"Pumpen rörs inte.")
        return False
    return True


# --- H66:ans startsida: styrenhet, firmware, registerlista och tillåtna intervall ---
# Biblioteket husdata-h66-modbus läser registerkartan härifrån i stället för att anta den (#466).

_ROW_RE = re.compile(r"<tr[^>]*><td>(.*?)</td><td>(\d+)&nbsp;(Input|Hold)</td><td>(.*?)</td><td>(.*?)</td></tr>", re.S)
_RANGE_RE = re.compile(r"Setting between: (-?[\d.]+) and (-?[\d.]+)")
_TAG_RE = re.compile(r"<[^>]+>")


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", _TAG_RE.sub("", html).replace("&nbsp;", " ")).strip()


def parse_home_page(html: str) -> dict:
    """{"controller", "firmware", "registers": {index: {"kind", "var_id", "name", "range": (lo, hi)|None}}}. Intervallet
    är i pumpens egen enhet (°C); skrivna råvärden är x10."""
    out = {"controller": None, "firmware": None, "registers": {}}
    m = re.search(r"<td>&nbsp;Controller</td><td>(.*?)</td>", html)
    if m:
        out["controller"] = _text(m.group(1))
    m = re.search(r"<td>&nbsp;Version</td><td>(.*?)</td>", html)
    if m:
        out["firmware"] = _text(m.group(1))
    for first, idx, kind, name, _value in _ROW_RE.findall(html):
        rng = _RANGE_RE.search(first)
        out["registers"][int(idx)] = {
            "kind": kind, "var_id": _text(first), "name": _text(name),
            "range": (float(rng.group(1)), float(rng.group(2))) if rng else None,
        }
    return out


# Vad motorn förutsätter om varje register (index -> delar av namnet, små bokstäver). Stämmer inte en rad är det
# en annan styrenhet än Thermia Diplomat (t.ex. IVT/Bosch Rego 600, vars karta är en annan) och värdena skulle bli fel.
_EXPECTED_NAMES = {
    0: "radiator return", 1: "radiator forward", 2: "brine in", 3: "brine out", 4: "outdoor", 5: "indoor",
    6: "warm water", 7: "pressure tube", 8: "cooling", 10: "heating setpoint", 13: "warm water stop",
    14: "operating mode", 15: "room temp setpoint", 16: "room sensor", 17: "curvel", 18: "curver",
    19: "heating setpnt", 20: "warm water start", 25: "compressor", 29: "pump radiator", 30: "switch valve",
    32: "alarm", 34: "runtime",
}


def check_register_map(page: dict) -> list:
    """Avvikelser mellan H66:ans registerlista och det motorn förutsätter. Tom lista = kartan stämmer."""
    regs = page.get("registers") or {}
    if not regs:
        return ["kunde inte läsa registerlistan på H66:ans startsida"]
    bad = []
    for idx, want in _EXPECTED_NAMES.items():
        got = (regs.get(idx) or {}).get("name", "")
        if want not in got.lower():
            bad.append(f"register {idx}: motorn förväntar '{want}', gatewayen har '{got or 'inget'}'")
    return bad


def fetch_home_page(ip: str, timeout: float = 3.0) -> dict | None:
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://{ip}/", timeout=timeout) as r:
            return parse_home_page(r.read().decode("utf-8", "replace"))
    except Exception:
        return None


def _live_limits() -> dict:
    """Pumpens egna intervall som råvärden (x10) per register, en timmes cache. Tom dict om sidan inte går att läsa."""
    if not PUMP_IPS:
        return {}
    ip = PUMP_IPS[min(_active_ip_index, len(PUMP_IPS) - 1)]
    c = _limits_cache
    if c["ip"] == ip and time.time() - c["at"] < _LIMITS_TTL_S:
        return c["limits"]
    page = fetch_home_page(ip)
    limits = {}
    if page:
        for idx, r in page["registers"].items():
            if r["kind"] == "Hold" and r["range"]:
                limits[idx] = (int(round(r["range"][0] * 10)), int(round(r["range"][1] * 10)))
    c.update(at=time.time(), ip=ip, limits=limits)
    return limits


_map_checked = set()


def _verify_register_map_once(ip: str) -> None:
    """Efter första lyckade läsningen mot en adress: stämmer H66:ans registerlista med det motorn förutsätter?"""
    if ip in _map_checked:
        return
    _map_checked.add(ip)
    page = fetch_home_page(ip)
    if not page:
        _map_checked.discard(ip)           # försök igen nästa gång
        return
    bad = check_register_map(page)
    ctrl = page.get("controller") or "okänd"
    if not bad:
        print(f"✅ Husdata: registerkartan stämmer med EnergyWizards (styrenhet: {ctrl}, firmware {page.get('firmware')}).")
    else:
        print(f"⚠️ Husdata: styrenhet '{ctrl}' har en annan registerkarta än Thermia Diplomat som motorn förutsätter - "
              f"värdena kan vara fel. {'; '.join(bad[:4])}")


def set_room_temp(target_temp):
    """
    Skriver ny måltemperatur för rummet.
    (target_temp skickas in som int multiplicerat med 10 från main.py).
    Register 15 (0203) är Room temp setpoint.
    """
    return _write_holding(15, target_temp)

@_serialized
def _read_holding(reg_addr, count=1):
    """Läser holding-register (råvärden) eller None."""
    client = _get_client()
    if not client:
        return None
    try:
        try:
            res = client.read_holding_registers(address=reg_addr, count=count, device_id=DEVICE_ID)
        except TypeError:
            try:
                res = client.read_holding_registers(address=reg_addr, count=count, slave=DEVICE_ID)
            except TypeError:
                try:
                    res = client.read_holding_registers(address=reg_addr, count=count, unit=DEVICE_ID)
                except TypeError:
                    res = client.read_holding_registers(address=reg_addr, count=count)
        if res is None or res.isError():
            return None
        return list(res.registers)
    except Exception:
        return None
    finally:
        try:
            client.close()
        except Exception:
            pass

def read_water_setpoints():
    """(stopp, start) för varmvattnet i °C som pumpen faktiskt har, eller None."""
    if not PUMP_IPS:
        return None
    if shadow.active():                       # skuggläge: inget skrivs, alltså inget att kontrollera
        return None
    for attempt in range(2):                  # gatewayen släpper ibland anslutningen direkt efter en skrivning
        regs = _read_holding(13, count=8)     # 13 = stopp, 20 = start, i en läsning
        if regs and len(regs) >= 8:
            return _to_signed(regs[0]) / 10.0, _to_signed(regs[7]) / 10.0
        time.sleep(1)
    return None

def read_room_setpoint():
    """Rumsbörvärdet (Holding 15) i °C, eller None. Läser bara det enda registret, inte hela kartan: systemtestet frågar
    var tionde sekund medan motorn själv läser pumpen, och H66-gatewayen tål bara en klient åt gången."""
    if not PUMP_IPS:
        return None
    if shadow.active():
        return None
    for attempt in range(2):
        regs = _read_holding(15, count=1)
        if regs:
            return _to_signed(regs[0]) / 10.0
        time.sleep(1)
    return None


def set_water_stop_temp(target_temp):
    """Sätter maxtemperatur för Varmvatten (Holding 13)."""
    return _write_holding(13, int(target_temp * 10))

def set_water_start_temp(target_temp):
    """Sätter starttemperatur för Varmvatten (Holding 20)."""
    return _write_holding(20, int(target_temp * 10))

def set_operating_mode(mode_value: int):
    """Sätter pumpens övergripande driftläge (Holding register 14)."""
    mode_val = int(mode_value)
    if mode_val == 0:
        print("🛑 SÄKERHETSSPÄRR: Vägrar sätta pumpen i läge 0 (Av). Tvingar till 1 (Auto).")
        mode_val = 1

    # Eftersom Husdata H66 tror att registret är en Temperatur, multiplicerar vi med 10
    return _write_holding(14, mode_val * 10)

# --- Justerbara Thermia/Husdata-inställningar (skriv med sanity-gränser) ---
# OBS: dessa anropas inte automatiskt; de finns för manuell/framtida styrning. Värden lagras ×10.

def set_heating_start_temp(celsius):
    """Värmestopp / värmesäsong-tröskel (utetemp, reg 19/0211). Över denna utetemp slutar pumpen
    värma huset i auto-läge. Sanity 5–25°C."""
    return _write_holding(19, int(max(5.0, min(25.0, float(celsius))) * 10))

def set_heat_curve(left_c=None, right_c=None):
    """Värmekurva: CurveL (reg 17/0205, mild ute) / CurveR (reg 18/0206, kallt ute). Sanity 20–60°C."""
    ok = True
    if left_c is not None:
        ok = _write_holding(17, int(max(20.0, min(60.0, float(left_c))) * 10)) and ok
    if right_c is not None:
        ok = _write_holding(18, int(max(20.0, min(60.0, float(right_c))) * 10)) and ok
    return ok

def set_room_sensor_influence(value):
    """Rumsgivarens inflytande på värmekurvan (reg 16/2204). Sanity 0–10."""
    return _write_holding(16, int(max(0.0, min(10.0, float(value))) * 10))


# --- Nätverksskanning efter en okonfigurerad Husdata-pump (entitetsväljaren, opt-in) ---
# Läser bara - skriver aldrig något. Eget, valfritt steg i wizardern, ALDRIG en del av
# den vanliga HA-skanningen eftersom detta faktiskt probear andra enheter på
# användarens LAN (till skillnad från resten av discovery.py, som bara pratar med HA).

import socket
from concurrent.futures import ThreadPoolExecutor


def _probe_modbus_port(ip: str, timeout: float = 0.3) -> bool:
    try:
        with socket.create_connection((ip, PORT), timeout=timeout):
            return True
    except OSError:
        return False


def _confirm_husdata(ip: str, timeout: float = 3.0) -> bool:
    """Läser en liten, ofarlig delmängd av Husdatas kända inputregister (samma tolkning
    som read_sensors()) och kontrollerar att utomhus-/inomhustemp ligger i ett fysiskt
    rimligt intervall - skiljer en riktig Husdata-pump från vilken Modbus-enhet som helst
    som råkar svara på port 502."""
    try:
        client = ModbusTcpClient(ip, port=PORT, timeout=timeout)
    except Exception:
        return False
    try:
        if not client.connect():
            return False
        try:
            res = client.read_input_registers(address=0, count=6, device_id=DEVICE_ID)
        except TypeError:
            try:
                res = client.read_input_registers(address=0, count=6, slave=DEVICE_ID)
            except TypeError:
                res = client.read_input_registers(address=0, count=6)
        if res is None or res.isError():
            return False
        reg = res.registers
        outdoor = _to_signed(reg[4]) / 10.0
        indoor = _to_signed(reg[5]) / 10.0
        return -40.0 <= outdoor <= 50.0 and 5.0 <= indoor <= 35.0
    except Exception:
        return False
    finally:
        client.close()


def _local_subnet() -> str:
    """Härleder husets /24 från en redan känd, riktig LAN-adress (PUMP_IP om satt, annars
    HA_IP) - ingen gissning om användarens nätverk."""
    base = os.environ.get("PUMP_IP") or homeassistant.HA_IP or "192.168.1.1"
    return ".".join(base.split(".")[:3])


def scan_for_husdata(subnet: str | None = None) -> list[dict]:
    """Söker efter en Husdata-värmepump på det lokala nätverket, för installationer som
    inte har PUMP_IP satt alls. Hela skanningen (254 adresser, port 502) tar normalt
    under en minut. Returnerar kandidat-IP(er) utan att skriva något."""
    subnet = subnet or _local_subnet()
    candidates = [f"{subnet}.{i}" for i in range(1, 255)]

    with ThreadPoolExecutor(max_workers=64) as pool:
        open_ips = [ip for ip, is_open in zip(candidates, pool.map(_probe_modbus_port, candidates)) if is_open]

    return [{"ip": ip, "driver": "thermia_husdata"} for ip in open_ips if _confirm_husdata(ip)]
