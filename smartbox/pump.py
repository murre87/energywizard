import os
import time
from pymodbus.client import ModbusTcpClient
 
# --- INSTÄLLNINGAR FÖR Thermia Diplomat Optimum G3 via Husdata H66 ---
# FIX: Gör fallback-IP konfigurerbar via env (PUMP_IP_FALLBACK) men behåll
# nuvarande default (.106) så befintligt beteende är oförändrat om env saknas.
PUMP_IPS = [os.environ.get("PUMP_IP", "192.168.1.179"), os.environ.get("PUMP_IP_FALLBACK", "192.168.1.106")]
PUMP_IPS = list(dict.fromkeys(PUMP_IPS)) # Tar bort dubbletter om miljövariabeln är .106
PORT = 502
TIMEOUT = int(os.environ.get("PUMP_TIMEOUT", 5))
DEVICE_ID = 1

_active_ip_index = 0

def _get_client():
    """Försöker ansluta till Husdata. Byter automatiskt IP om den primära är nere."""
    global _active_ip_index
    client = ModbusTcpClient(PUMP_IPS[_active_ip_index], port=PORT, timeout=TIMEOUT)
    if client.connect():
        return client
    client.close()
    
    # Om den aktiva IP:n misslyckades, testa de andra
    for i, ip in enumerate(PUMP_IPS):
        if i == _active_ip_index:
            continue
        client = ModbusTcpClient(ip, port=PORT, timeout=TIMEOUT)
        if client.connect():
            _active_ip_index = i
            print(f"🔄 Husdata: Bytte aktiv IP-adress till {ip}")
            return client
        client.close()
    return None

def _to_signed(val):
    """
    Konverterar Unsigned 16-bit till Signed 16-bit.
    Krävs för minustemperaturer (t.ex. Brine Out på vintern).
    """
    return val - 65536 if val > 32767 else val

def read_sensors():
    """
    Läser in sensordata direkt från Husdata via Modbus TCP.
    Returnerar en dict med alla värden, eller None vid fel.
    """
    try:
        client = _get_client()
        if not client:
            print(f"❌ Husdata: Kunde inte ansluta via Modbus TCP på någon IP: {PUMP_IPS}")
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
            print("❌ Husdata: Fick inget svar (None) vid läsning av Modbus-register")
            return None

        if res_in.isError() or res_hold.isError():
            print("❌ Husdata: Fick felsvar vid läsning av Modbus-register")
            return None

        reg = res_in.registers
        hold = res_hold.registers

        def get_temp(idx):
            """Temperaturer från Husdata är oftast heltal multiplicerat med 10."""
            return _to_signed(reg[idx]) / 10.0

        return {
            # Temperaturer (Input Registers)
            "return_temp":        get_temp(0),      # 0: Radiator Return
            "forward_temp":       get_temp(1),      # 1: Radiator Forward
            "brine_in_temp":      get_temp(2),      # 2: Brine in
            "brine_out_temp":     get_temp(3),      # 3: Brine out
            "outdoor_temp":       get_temp(4),      # 4: Outdoor
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

            # Larm & Historik
            "alarm_active":         reg[32],        # 32: Alarm
            "alarm_code":           reg[33],        # 33: Alarm Code
            "compressor_runtime_h": reg[34],        # 34: Compr. Runtime
            "compr_kwh_total":      0.0,            # Du mäter VP separat via meter.py ändå
            "aux_runtime_h":        reg[35],        # 35: Aux runtime
            "aux_runtime_2_h":      reg[36],        # 36: Aux runtime 2
            "warm_water_runtime_h": reg[37],        # 37: Warm water runtime
            "power_consumption_w":  reg[38],        # 38: Power consumption
            "accumulated_consumption_kwh": reg[39] / 10.0, # 39: Accumulated consumption
        }

    except Exception as e:
        print(f"❌ Husdata: Nätverksfel vid läsning (Modbus): {e}")
        return None

def _write_holding(reg_addr, value, retries=3):
    """Hjälpfunktion för att skriva till ett Modbus Holding-register med retries."""
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

def set_room_temp(target_temp):
    """
    Skriver ny måltemperatur för rummet.
    (target_temp skickas in som int multiplicerat med 10 från main.py).
    Register 15 (0203) är Room temp setpoint.
    """
    return _write_holding(15, target_temp)

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