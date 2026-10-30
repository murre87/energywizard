import os
import psycopg
import pandas as pd
from datetime import datetime
from contextlib import contextmanager
import zoneinfo
import settings

SWE_TZ = zoneinfo.ZoneInfo("Europe/Stockholm")

DB_HOST = os.environ.get("POSTGRES_HOST", "postgres-smartbox")
DB_USER = os.environ.get("POSTGRES_USER")
DB_PASS = os.environ.get("POSTGRES_PASSWORD")
DB_NAME = os.environ.get("POSTGRES_DB")

from psycopg_pool import ConnectionPool

_pool = None
def get_db_pool():
    global _pool
    if _pool is None:
        _pool = ConnectionPool(f"host={DB_HOST} user={DB_USER} password={DB_PASS} dbname={DB_NAME}", min_size=1, max_size=20)
    return _pool

@contextmanager
def get_db():
    p = get_db_pool()
    with p.connection() as conn:
        yield conn

def init_log_db():
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS sensor_log (
                        timestamp            TIMESTAMP WITH TIME ZONE PRIMARY KEY,
                        price                NUMERIC,
                        indoor_temp          NUMERIC,
                        water_temp           NUMERIC,
                        target_room_temp     NUMERIC,
                        water_mode           INTEGER
                    )
                """)
                # Lägger till solar_forecast_w här!
                cur.execute("""
                    ALTER TABLE sensor_log
                        ADD COLUMN IF NOT EXISTS forward_temp          NUMERIC,
                        ADD COLUMN IF NOT EXISTS return_temp           NUMERIC,
                        ADD COLUMN IF NOT EXISTS calc_forward_temp     NUMERIC,
                        ADD COLUMN IF NOT EXISTS outdoor_temp          NUMERIC,
                        ADD COLUMN IF NOT EXISTS avg_w_l1              NUMERIC,
                        ADD COLUMN IF NOT EXISTS avg_w_l2              NUMERIC,
                        ADD COLUMN IF NOT EXISTS avg_w_l3              NUMERIC,
                        ADD COLUMN IF NOT EXISTS avg_w_tot             NUMERIC,
                        ADD COLUMN IF NOT EXISTS consumed_kwh          NUMERIC,
                        ADD COLUMN IF NOT EXISTS total_kwh             NUMERIC,
                        ADD COLUMN IF NOT EXISTS cloud_cover           NUMERIC,
                        ADD COLUMN IF NOT EXISTS wind_speed            NUMERIC,
                        ADD COLUMN IF NOT EXISTS net_power             NUMERIC,
                        ADD COLUMN IF NOT EXISTS wind_dir              NUMERIC,
                        ADD COLUMN IF NOT EXISTS solar_forecast_w      NUMERIC,
                        ADD COLUMN IF NOT EXISTS water_temp_mid        NUMERIC,
                        ADD COLUMN IF NOT EXISTS hc_forward_temp       NUMERIC,
                        ADD COLUMN IF NOT EXISTS brine_in_temp         NUMERIC,
                        ADD COLUMN IF NOT EXISTS brine_out_temp        NUMERIC,
                        ADD COLUMN IF NOT EXISTS hot_gas_temp          NUMERIC,
                        ADD COLUMN IF NOT EXISTS suction_gas_temp      NUMERIC,
                        ADD COLUMN IF NOT EXISTS compressor_temp       NUMERIC,
                        ADD COLUMN IF NOT EXISTS drain_pan_temp        NUMERIC,
                        ADD COLUMN IF NOT EXISTS compressor_power_kw   NUMERIC,
                        ADD COLUMN IF NOT EXISTS compressor_speed_pct  NUMERIC,
                        ADD COLUMN IF NOT EXISTS compressor_running    SMALLINT,
                        ADD COLUMN IF NOT EXISTS pump_heat_running     SMALLINT,
                        ADD COLUMN IF NOT EXISTS pump_radiator_running SMALLINT,
                        ADD COLUMN IF NOT EXISTS alarm_active          SMALLINT,
                        ADD COLUMN IF NOT EXISTS alarm_code            SMALLINT,
                        ADD COLUMN IF NOT EXISTS compr_kwh_total       NUMERIC,
                        ADD COLUMN IF NOT EXISTS compr_kwh_heating     NUMERIC,
                        ADD COLUMN IF NOT EXISTS compr_kwh_hotwater    NUMERIC,
                        ADD COLUMN IF NOT EXISTS compressor_runtime_h  NUMERIC,
                        ADD COLUMN IF NOT EXISTS compressor_starts     NUMERIC,
                        ADD COLUMN IF NOT EXISTS water_setpoint        NUMERIC,
                        ADD COLUMN IF NOT EXISTS cop                   NUMERIC,
                        ADD COLUMN IF NOT EXISTS pv_power_w            NUMERIC,
                        ADD COLUMN IF NOT EXISTS battery_soc           NUMERIC,
                        ADD COLUMN IF NOT EXISTS battery_power_w       NUMERIC,
                        ADD COLUMN IF NOT EXISTS inverter_status       SMALLINT,
                        ADD COLUMN IF NOT EXISTS solar_today_kwh       NUMERIC,
                        -- Rumstemperaturer från Home Assistant
                        ADD COLUMN IF NOT EXISTS temp_matter_1         NUMERIC,
                        ADD COLUMN IF NOT EXISTS temp_matter_2         NUMERIC,
                        ADD COLUMN IF NOT EXISTS temp_matter_3         NUMERIC,
                        ADD COLUMN IF NOT EXISTS temp_esp              NUMERIC,
                        ADD COLUMN IF NOT EXISTS indoor_humidity       NUMERIC,
                        ADD COLUMN IF NOT EXISTS hum_matter_1          NUMERIC,
                        ADD COLUMN IF NOT EXISTS hum_matter_2          NUMERIC,
                        ADD COLUMN IF NOT EXISTS hum_matter_3          NUMERIC,
                        ADD COLUMN IF NOT EXISTS hum_esp               NUMERIC,
                        -- Easee elbilsladdare
                        ADD COLUMN IF NOT EXISTS ev_power_kw           NUMERIC,
                        ADD COLUMN IF NOT EXISTS ev_current_a          NUMERIC,
                        ADD COLUMN IF NOT EXISTS ev_dynamic_limit_a    NUMERIC,
                        ADD COLUMN IF NOT EXISTS ev_session_kwh        NUMERIC,
                        ADD COLUMN IF NOT EXISTS ev_status             VARCHAR(50),
                        -- Data för bil 2 (Tesla @ Carport)
                        ADD COLUMN IF NOT EXISTS ev_carport_power_kw   NUMERIC,
                        ADD COLUMN IF NOT EXISTS ev_carport_status     VARCHAR(50),
                        -- Batteristatus (SOC) från bilarna
                        ADD COLUMN IF NOT EXISTS nissan_soc            NUMERIC,
                        ADD COLUMN IF NOT EXISTS tesla_soc             NUMERIC,
                        ADD COLUMN IF NOT EXISTS tesla_soc_stale       SMALLINT,
                        ADD COLUMN IF NOT EXISTS nissan_soc_stale      SMALLINT,
                        ADD COLUMN IF NOT EXISTS tesla_climate_temp    NUMERIC,
                        ADD COLUMN IF NOT EXISTS nissan_charge_completed SMALLINT,
                        ADD COLUMN IF NOT EXISTS tesla_charge_completed  SMALLINT,
                        ADD COLUMN IF NOT EXISTS tesla_climate_state   VARCHAR(50),
                        ADD COLUMN IF NOT EXISTS nissan_climate_temp   NUMERIC,
                        ADD COLUMN IF NOT EXISTS nissan_climate_state  VARCHAR(50),
                        -- Shelly 3EM: fasström (A) – för EV-lastbalansering mot 16A-säkringen
                        ADD COLUMN IF NOT EXISTS shelly_l1_a           NUMERIC,
                        ADD COLUMN IF NOT EXISTS shelly_l2_a           NUMERIC,
                        ADD COLUMN IF NOT EXISTS shelly_l3_a           NUMERIC,
                        ADD COLUMN IF NOT EXISTS ev_avail_a            SMALLINT,
                        ADD COLUMN IF NOT EXISTS forecast_temp         NUMERIC,
                        -- Spabad
                        ADD COLUMN IF NOT EXISTS spa_temp              NUMERIC,
                        ADD COLUMN IF NOT EXISTS spa_target            NUMERIC,
                        ADD COLUMN IF NOT EXISTS spa_heater_running    SMALLINT,
                        ADD COLUMN IF NOT EXISTS spa_power_w           REAL,
                        -- Digital Tvilling / AI-simulering
                        ADD COLUMN IF NOT EXISTS ai_action_log         TEXT,
                        -- Övriga pump-värden (Digital Tvilling)
                        ADD COLUMN IF NOT EXISTS operating_mode        SMALLINT,
                        ADD COLUMN IF NOT EXISTS degree_minutes        NUMERIC,
                        ADD COLUMN IF NOT EXISTS circ_pump_speed       NUMERIC,
                        ADD COLUMN IF NOT EXISTS brine_pump_speed      NUMERIC,
                        ADD COLUMN IF NOT EXISTS room_temp_setpoint    NUMERIC,
                        ADD COLUMN IF NOT EXISTS heating_setpnt_start  NUMERIC,
                        ADD COLUMN IF NOT EXISTS water_start_temp      NUMERIC,
                        ADD COLUMN IF NOT EXISTS aux_runtime_h         NUMERIC,
                        ADD COLUMN IF NOT EXISTS aux_runtime_2_h       NUMERIC,
                        ADD COLUMN IF NOT EXISTS warm_water_runtime_h  NUMERIC,
                        ADD COLUMN IF NOT EXISTS power_consumption_w   NUMERIC,
                        ADD COLUMN IF NOT EXISTS accumulated_consumption_kwh NUMERIC,
                        ADD COLUMN IF NOT EXISTS active_mode           VARCHAR(50),
                        ADD COLUMN IF NOT EXISTS active_decision       TEXT,
                        ADD COLUMN IF NOT EXISTS price_forecast        NUMERIC,
                        ADD COLUMN IF NOT EXISTS house_consumption_w   NUMERIC,
                        ADD COLUMN IF NOT EXISTS pi_p_term             NUMERIC,
                        ADD COLUMN IF NOT EXISTS pi_i_term             NUMERIC,
                        ADD COLUMN IF NOT EXISTS peak_shaving_active   SMALLINT,
                        ADD COLUMN IF NOT EXISTS force_heating_active  SMALLINT,
                        ADD COLUMN IF NOT EXISTS watchdog_trips        INTEGER,
                        ADD COLUMN IF NOT EXISTS predicted_cooling_rate NUMERIC,
                        ADD COLUMN IF NOT EXISTS expected_energy_wh    NUMERIC,
                        ADD COLUMN IF NOT EXISTS current_target_limit  NUMERIC,
                        ADD COLUMN IF NOT EXISTS predicted_base_load_kw NUMERIC,
                        ADD COLUMN IF NOT EXISTS allowed_kwh_now       NUMERIC
                """)
                # Robotgräsklippare
                cur.execute("""
                    ALTER TABLE sensor_log
                        ADD COLUMN IF NOT EXISTS mower_status VARCHAR(50),
                        ADD COLUMN IF NOT EXISTS mower_power_w NUMERIC
                """)
            conn.commit()
        print("🗄️ Databas: sensor_log är redo.")
    except Exception as e:
        print(f"❌ Kunde inte initiera sensor_log: {e}")

    # Separat transaktion för device_log så den inte påverkas av fel ovan
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS device_log (
                        timestamp  TIMESTAMP WITH TIME ZONE,
                        device_id  VARCHAR(50),
                        power_w    NUMERIC,
                        total_wh   NUMERIC,
                        is_on      BOOLEAN,
                        PRIMARY KEY (timestamp, device_id)
                    )
                """)
            conn.commit()
        print("🗄️ Databas: device_log är redo.")
    except Exception as e:
        print(f"❌ Kunde inte initiera device_log: {e}")

    # VIEW för digital tvilling – kombinerar sensor_log och device_log i en bred rad per minut
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                # DROP + CREATE i stället för CREATE OR REPLACE – undviker fel när
                # sensor_log får nya kolumner (s.* expanderar annorlunda och PostgreSQL
                # vägrar byta namn på befintliga vykolumner via OR REPLACE).
                cur.execute("DROP VIEW IF EXISTS twin_features")
                cur.execute("""
                    CREATE VIEW twin_features AS
                    SELECT
                        s.*
                    FROM sensor_log s
                """)
            conn.commit()
        print("🗄️ Databas: twin_features-vy är redo.")
    except Exception as e:
        print(f"❌ Kunde inte skapa twin_features-vy: {e}")


def log_status(
    price, indoor, water, target_room, water_mode,
    forward, retur, calc_forward, outdoor,
    avg_l1, avg_l2, avg_l3, avg_tot,
    consumed_kwh, total_kwh,
    cloud_cover, wind_speed, net_power, wind_dir,
    solar_forecast_w,
    pump: dict,
    solar: dict = None,
    ha_temps: dict = None,   # Rumstemperaturer från Home Assistant
    ev: dict = None,         # Easee elbilsladdare från Home Assistant
    mower_data: dict = None, # Robotgräsklippare
    cop: float = None,       # Beräknad COP (kompressoreffekt / elmätareffekt)
    pump_operating_mode: int = None, # Pumpens faktiska driftläge
    ev_carport: dict = None, # Easee (Carport)
    car_data: dict = None,   # SOC från bilar
    shelly_l1_a: float = None,   # Fasström L1 (A) från Shelly 3EM
    shelly_l2_a: float = None,   # Fasström L2 (A) från Shelly 3EM
    shelly_l3_a: float = None,   # Fasström L3 (A) från Shelly 3EM
    ev_avail_a: int = None,      # Beräknad tillgänglig laddström (A) skickad till Easee
    forecast_temp: float = None, # Prognostemperatur från SMHI (°C) – jämför mot outdoor_temp
    gecko: dict = None,          # Spabad
    spa_power_w: float = None,   # Uppmätt spa-effekt (3-fas Shelly 'Spabad', total W)
    ai_action_log: str = None,   # Text som beskriver vad AI:n skulle ha gjort
    active_mode: str = None,     # Det aktiva driftläget (t.ex. EXPENSIVE)
    active_decision: str = None, # Den senaste beslutstexten
    price_forecast: float = None,
    house_consumption_w: float = None,
    pi_p_term: float = None,
    pi_i_term: float = None,
    peak_shaving_active: int = 0,
    force_heating_active: int = 0,
    watchdog_trips: int = 0,
    predicted_cooling_rate: float = None,
    expected_energy_wh: float = None,
    current_target_limit: float = None,
    predicted_base_load_kw: float = None,
    allowed_kwh_now: float = None
):
    try:
        now = datetime.now(SWE_TZ)
        p   = pump     or {}
        s   = solar    or {}
        t   = ha_temps or {}
        e   = ev       or {}
        g   = gecko    or {}
        ec  = ev_carport or {}
        mower = mower_data or {}
        cd  = car_data or {}

        se_status_map = {
            "I_STATUS_OFF": 0, "I_STATUS_SLEEPING": 1, "I_STATUS_WAKEUP": 2,
            "I_STATUS_MPPT": 4, "I_STATUS_THROTTLED": 5, "I_STATUS_SHUTTING_DOWN": 6,
            "I_STATUS_FAULT": 7, "I_STATUS_STANDBY": 8
        }
        raw_inv = s.get("status")
        if isinstance(raw_inv, str):
            if raw_inv.isdigit():
                inv_status = int(raw_inv)
            else:
                inv_status = se_status_map.get(raw_inv, 0)
        else:
            inv_status = raw_inv if raw_inv is not None else 0

        # Skapa en ordlista (dictionary) där nyckeln är kolumnens namn i databasen
        # Python kommer dynamiskt bygga SQL-frågan utifrån detta, så det alltid matchar perfekt.
        data = {
            "timestamp": now,
            "price": price,
            "indoor_temp": indoor,
            "water_temp": water,
            "target_room_temp": target_room,
            "water_mode": water_mode,
            "forward_temp": forward,
            "return_temp": retur,
            "calc_forward_temp": calc_forward,
            "outdoor_temp": outdoor,
            "avg_w_l1": avg_l1,
            "avg_w_l2": avg_l2,
            "avg_w_l3": avg_l3,
            "avg_w_tot": avg_tot,
            "consumed_kwh": consumed_kwh,
            "total_kwh": total_kwh,
            "cloud_cover": cloud_cover,
            "wind_speed": wind_speed,
            "net_power": net_power,
            "wind_dir": wind_dir,
            "solar_forecast_w": solar_forecast_w,
            "water_temp_mid": p.get("water_temp_mid"),
            "hc_forward_temp": p.get("hc_forward_temp"),
            "brine_in_temp": p.get("brine_in_temp"),
            "brine_out_temp": p.get("brine_out_temp"),
            "hot_gas_temp": p.get("hot_gas_temp"),
            "suction_gas_temp": p.get("suction_gas_temp"),
            "compressor_temp": p.get("compressor_temp"),
            "drain_pan_temp": p.get("drain_pan_temp"),
            "compressor_power_kw": p.get("compressor_power_kw"),
            "compressor_speed_pct": p.get("compressor_speed_pct"),
            "compressor_running": p.get("compressor_running"),
            "pump_heat_running": p.get("pump_heat_running"),
            "pump_radiator_running": p.get("pump_radiator_running"),
            "alarm_active": p.get("alarm_active"),
            "alarm_code": p.get("alarm_code"),
            "compr_kwh_total": p.get("compr_kwh_total"),
            "compr_kwh_heating": p.get("compr_kwh_heating"),
            "compr_kwh_hotwater": p.get("compr_kwh_hotwater"),
            "compressor_runtime_h": p.get("compressor_runtime_h"),
            "compressor_starts": p.get("compressor_starts"),
            "pv_power_w": s.get("pv_power_w"),
            "battery_soc": s.get("battery_soc"),
            "battery_power_w": s.get("battery_power_w"),
            "inverter_status": inv_status,
            "solar_today_kwh": s.get("today_kwh"),
            "temp_garage": t.get("garage"),
            "temp_matter_1": t.get("matter_1"),
            "temp_matter_2": t.get("matter_2"),
            "temp_matter_3": t.get("matter_3"),
            "temp_esp": t.get("esp"),
            "indoor_humidity": t.get("indoor_humidity"),
            "hum_matter_1": t.get("hum_matter_1"),
            "hum_matter_2": t.get("hum_matter_2"),
            "hum_matter_3": t.get("hum_matter_3"),
            "hum_esp": t.get("hum_esp"),
            "ev_power_kw": e.get("power_kw"),
            "ev_current_a": e.get("current_a"),
            "ev_dynamic_limit_a": e.get("dynamic_limit_a"),
            "ev_session_kwh": e.get("session_kwh"),
            "ev_status": e.get("status"),
            "ev_carport_power_kw": ec.get("power_kw"),
            "mower_power_w": mower.get("power_w"),
            "mower_status": mower.get("status"),
            "ev_carport_status": ec.get("status"),
            "nissan_soc": cd.get("nissan_soc"),
            "tesla_soc": cd.get("tesla_soc"),
            "tesla_soc_stale": cd.get("tesla_soc_stale"),
            "nissan_soc_stale": cd.get("nissan_soc_stale"),
            "nissan_charge_completed": 1 if cd.get("nissan_charge_completed") else 0,
            "tesla_charge_completed": 1 if cd.get("tesla_charge_completed") else 0,
            "water_setpoint": p.get("water_setpoint"),
            "cop": cop,
            "tesla_climate_temp": cd.get("tesla_climate_temp"),
            "tesla_climate_state": cd.get("tesla_climate_state"),
            "shelly_l1_a": shelly_l1_a,
            "shelly_l2_a": shelly_l2_a,
            "shelly_l3_a": shelly_l3_a,
            "ev_avail_a": ev_avail_a,
            "forecast_temp": forecast_temp,
            "spa_temp": g.get("current_temp"),
            "spa_target": g.get("target_temp"),
            "spa_power_w": spa_power_w,
            # Prefer den 3-fas-MÄTTA effekten för värmar-status; fall tillbaka på Gecko-state.
            "spa_heater_running": (1 if (spa_power_w is not None and spa_power_w > 500)
                                   else (1 if str(g.get("heater_state", "")).lower() == "heating" else 0)),
            "ai_action_log": ai_action_log,
            "operating_mode": pump_operating_mode,
            "degree_minutes": p.get("degree_minutes"),
            "circ_pump_speed": p.get("circ_pump_speed"),
            "brine_pump_speed": p.get("brine_pump_speed"),
            "room_temp_setpoint": p.get("room_temp_setpoint"),
            "heating_setpnt_start": p.get("heating_setpnt_start"),
            "water_start_temp": p.get("water_start_temp"),
            "aux_runtime_h": p.get("aux_runtime_h"),
            "aux_runtime_2_h": p.get("aux_runtime_2_h"),
            "warm_water_runtime_h": p.get("warm_water_runtime_h"),
            "power_consumption_w": p.get("power_consumption_w"),
            "accumulated_consumption_kwh": p.get("accumulated_consumption_kwh"),
            "active_mode": active_mode,
            "active_decision": active_decision,
            "price_forecast": price_forecast,
            "house_consumption_w": house_consumption_w,
            "pi_p_term": pi_p_term,
            "pi_i_term": pi_i_term,
            "peak_shaving_active": peak_shaving_active,
            "force_heating_active": force_heating_active,
            "watchdog_trips": watchdog_trips,
            "predicted_cooling_rate": float(predicted_cooling_rate) if predicted_cooling_rate is not None else None,
            "expected_energy_wh": expected_energy_wh,
            "current_target_limit": current_target_limit,
            "predicted_base_load_kw": predicted_base_load_kw,
            "allowed_kwh_now": allowed_kwh_now
        }
        
        # Generera strängarna dynamiskt oavsett mängden data
        columns = ", ".join(data.keys())
        placeholders = ", ".join(["%s"] * len(data))
        values = tuple(data.values())

        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(f"INSERT INTO sensor_log ({columns}) VALUES ({placeholders})", values)
            conn.commit()
        print("💾 1-minutslogg sparad.")
    except Exception as e:
        print(f"❌ Fel vid loggning till databas: {e}")




def downsample_old_data(months_old=6):
    """Rensar upp gammal data (behåller bara 15-minutersintervall) för att spara utrymme."""
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(f"""
                    DELETE FROM sensor_log
                    WHERE timestamp < NOW() - INTERVAL '{months_old} months'
                      AND EXTRACT(MINUTE FROM timestamp) NOT IN (0, 15, 30, 45)
                """)
                deleted = cur.rowcount
            conn.commit()
        if deleted > 0:
            print(f"🧹 Databas-städning: Rensade {deleted} gamla 1-minutsrader (äldre än {months_old} månader).")
    except Exception as e:
        print(f"❌ Fel vid databas-gallring: {e}")

    # De nya minut-logg-tabellerna (1 rad/min) saknade retention → skulle växa obegränsat.
    # Rensa rader äldre än months_old i EGNA transaktioner (ett fel poisonar inte det ovan).
    for _tbl in ("spa_phase_log", "load_breakdown"):
        try:
            with get_db() as conn, conn.cursor() as cur:
                cur.execute(f"DELETE FROM {_tbl} WHERE timestamp < NOW() - INTERVAL '{months_old} months'")
                conn.commit()
        except Exception as e:
            print(f"❌ Gallring av {_tbl}: {e}")

def init_overrides_db():
    """Skapar overrides-tabellen och seedar standardvärden (auto) om den inte finns."""
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS overrides (
                        device     VARCHAR(50) PRIMARY KEY,
                        mode       VARCHAR(64) NOT NULL DEFAULT 'auto',
                        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                    )
                """)
                cur.execute("ALTER TABLE overrides ALTER COLUMN mode TYPE VARCHAR(64)")        # 2026-10-30: 10 räckte inte för tidsstämplar ('2026-10-30 08:57'), vilket fällde hela sol-laddningens sparande
                cur.execute("""
                    INSERT INTO overrides (device, mode) VALUES
                        ('heat',             'auto'),
                        ('hotwater',         'auto'),
                        ('pump_operating_mode', 'auto'),
                        ('notify_solar_limit', 'true')
                    ON CONFLICT (device) DO NOTHING
                """)
            conn.commit()
        print("🗄️ Databas: overrides är redo.")
    except Exception as e:
        print(f"❌ Kunde inte initiera overrides: {e}")


def log_comfort_event(event_type: str, detail: str = "", indoor_temp=None,
                      outdoor_temp=None, price=None, active_mode=None):
    """#3-förberedelse: loggar en KOMFORT-signal (användaren tvingar värme, justerar temp,
    byter läge osv) + kontext, så vi senare kan LÄRA oss personliga komfortgränser per rum/tid.
    Skapar tabellen vid behov. Sväljer fel tyst – får aldrig störa styrningen."""
    try:
        with get_db() as conn, conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS comfort_events (
                    id           SERIAL PRIMARY KEY,
                    timestamp    TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    event_type   VARCHAR(60) NOT NULL,
                    detail       TEXT,
                    indoor_temp  REAL, outdoor_temp REAL, price REAL, active_mode VARCHAR(20)
                )
            """)
            cur.execute("""
                INSERT INTO comfort_events (event_type, detail, indoor_temp, outdoor_temp, price, active_mode)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (event_type, detail, indoor_temp, outdoor_temp, price, active_mode))
            conn.commit()
        return True
    except Exception as e:
        print(f"❌ log_comfort_event: {e}")
        return False


def log_spa_phase(phase_a_w, phase_b_w, phase_c_w, activities: dict):
    """Loggar per-fas-effekt + spabadets aktiviteter varje minut → underlag för fas-INLÄRNINGEN
    (vilken fas driver värmare/pump/blåsare/…). Skapar tabellen vid behov, sväljer fel tyst."""
    try:
        a = activities or {}
        with get_db() as conn, conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS spa_phase_log (
                    id BIGSERIAL PRIMARY KEY,
                    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    phase_a_w REAL, phase_b_w REAL, phase_c_w REAL,
                    heating BOOLEAN, circ_pump BOOLEAN, pump1 BOOLEAN,
                    blower BOOLEAN, waterfall BOOLEAN, lights BOOLEAN, ozone BOOLEAN
                )
            """)
            cur.execute("""
                INSERT INTO spa_phase_log
                    (phase_a_w, phase_b_w, phase_c_w, heating, circ_pump, pump1, blower, waterfall, lights, ozone)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (phase_a_w, phase_b_w, phase_c_w,
                  a.get('heating'), a.get('circ_pump'), a.get('pump1'),
                  a.get('blower'), a.get('waterfall'), a.get('lights'), a.get('ozone')))
            conn.commit()
        return True
    except Exception as e:
        print(f"❌ log_spa_phase: {e}")
        return False


def log_load_breakdown(total_w, ev_w, pump_w, spa_w, unexplained_w):
    """Loggar last-nedbrytningen varje minut → dashboarden visar 'vad drar just nu' + historik,
    och den oförklarade lasten kan larmas på. Skapar tabellen vid behov, sväljer fel tyst."""
    try:
        with get_db() as conn, conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS load_breakdown (
                    id BIGSERIAL PRIMARY KEY,
                    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    total_w REAL, ev_w REAL, pump_w REAL, spa_w REAL, unexplained_w REAL
                )
            """)
            cur.execute("""
                INSERT INTO load_breakdown (total_w, ev_w, pump_w, spa_w, unexplained_w)
                VALUES (%s,%s,%s,%s,%s)
            """, (total_w, ev_w, pump_w, spa_w, unexplained_w))
            conn.commit()
        return True
    except Exception as e:
        print(f"❌ log_load_breakdown: {e}")
        return False


def get_override(device: str) -> str:
    """Returnerar aktuellt läge ('auto', 'on', 'off') för en enhet."""
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT mode FROM overrides WHERE device = %s", (device,))
                row = cur.fetchone()
                return row[0] if row else "auto"
    except Exception as e:
        print(f"❌ get_override({device}): {e}")
        return "auto"

def get_all_overrides() -> dict:
    """Hämtar alla överstyrningar i en enda databasfråga."""
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT device, mode FROM overrides")
                return {row[0]: row[1] for row in cur.fetchall()}
    except Exception as e:
        print(f"❌ get_all_overrides(): {e}")
        return {}


def set_override(device: str, mode: str):
    """Sätter överstyrningsläge ('auto', 'on', 'off') för en enhet."""
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO overrides (device, mode, updated_at)
                    VALUES (%s, %s, NOW())
                    ON CONFLICT (device) DO UPDATE SET mode = EXCLUDED.mode, updated_at = NOW()
                """, (device, mode))
            conn.commit()
    except Exception as e:
        print(f"❌ set_override({device}, {mode}): {e}")


def get_storage_info():
    """
    Returnerar disk- och databasstatistik.

    disk_pct        : Diskfyllnad i procent (0–100)
    disk_used_gb    : Använt utrymme (GB)
    disk_free_gb    : Ledigt utrymme (GB)
    disk_total_gb   : Total diskstorlek (GB)
    db_total_gb     : Total databasstorlek (GB)
    sensor_log_gb   : Storleken på sensor_log-tabellen (GB)
    """
    import shutil
    disk            = shutil.disk_usage("/")
    disk_total_gb   = disk.total / 1e9
    disk_used_gb    = disk.used  / 1e9
    disk_free_gb    = disk.free  / 1e9
    disk_pct        = disk.used  / disk.total * 100

    db_total_gb     = None
    sensor_log_gb   = None
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_database_size(current_database())")
                db_total_gb = cur.fetchone()[0] / 1e9
                cur.execute("SELECT pg_total_relation_size('sensor_log')")
                sensor_log_gb = cur.fetchone()[0] / 1e9
    except Exception as e:
        print(f"❌ Kunde inte hämta DB-storlek: {e}")

    return {
        "disk_pct":      disk_pct,
        "disk_used_gb":  disk_used_gb,
        "disk_free_gb":  disk_free_gb,
        "disk_total_gb": disk_total_gb,
        "db_total_gb":   db_total_gb,
        "sensor_log_gb": sensor_log_gb,
    }


def get_outdoor_temp_avg_5d():
    """Returnerar 5-dygnsmedel av utomhustemperaturen (°C) eller None vid fel."""
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT AVG(outdoor_temp)
                    FROM sensor_log
                    WHERE timestamp >= NOW() - INTERVAL '5 days'
                    AND outdoor_temp BETWEEN -40 AND 50
                """)
                row = cur.fetchone()
                return float(row[0]) if row and row[0] is not None else None
    except Exception as e:
        print(f"❌ Kunde inte hämta 5-dygnsmedel för utetemp: {e}")
        return None

def get_spa_temp_ago(minutes: int):
    """Hämtar spabadets temperatur för cirka X minuter sedan."""
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT spa_temp 
                    FROM sensor_log 
                    WHERE timestamp <= NOW() - INTERVAL '1 minute' * %s
                      AND timestamp >= NOW() - INTERVAL '1 minute' * (%s + 30)
                      AND spa_temp IS NOT NULL 
                    ORDER BY timestamp DESC 
                    LIMIT 1
                """, (minutes, minutes))
                row = cur.fetchone()
                return float(row[0]) if row else None
    except Exception as e:
        print(f"❌ Fel vid hämtning av spa temp historik: {e}")
        return None

_cached_monthly_peaks = None
_cached_monthly_peaks_time = None

def get_monthly_power_peaks():
    """
    Hämtar månadens två officiella effektoppar (från två olika dagar)
    enligt Jönköping Energis regelverk.
    Returnerar dict med de olika topparna (Baslast och Höglast).
    """
    global _cached_monthly_peaks, _cached_monthly_peaks_time
    now = datetime.now(SWE_TZ)
    
    if _cached_monthly_peaks and _cached_monthly_peaks_time and (now - _cached_monthly_peaks_time).total_seconds() < 900:
        return _cached_monthly_peaks
        
    try:
        with get_db() as conn:
            df_peaks = pd.read_sql("""
                WITH hourly_data AS (
                    SELECT 
                        DATE_TRUNC('hour', timestamp AT TIME ZONE 'Europe/Stockholm') as hour_ts,
                        DATE(timestamp AT TIME ZONE 'Europe/Stockholm') as day_date,
                        AVG(GREATEST(net_power, 0)) / 1000.0 as hr_consumed
                    FROM sensor_log
                    WHERE timestamp >= DATE_TRUNC('month', NOW() AT TIME ZONE 'Europe/Stockholm')
                      AND net_power IS NOT NULL
                    GROUP BY 1, 2
                )
                SELECT * FROM hourly_data
            """, conn)
            
            res = {'bas_p1': 0.0, 'bas_p2': 0.0, 'hog_p1': 0.0, 'hog_p2': 0.0}
            if not df_peaks.empty:
                df_peaks['hour_ts'] = pd.to_datetime(df_peaks['hour_ts']).dt.tz_localize(None)
                df_peaks['dow'] = df_peaks['hour_ts'].dt.dayofweek
                df_peaks['hour'] = df_peaks['hour_ts'].dt.hour
                df_peaks['month'] = df_peaks['hour_ts'].dt.month
                
                # Baslast (året runt, dygnet runt)
                idx_bas = df_peaks.groupby('day_date')['hr_consumed'].idxmax()
                max_bas = df_peaks.loc[idx_bas].sort_values('hr_consumed', ascending=False)
                if len(max_bas) > 0: res['bas_p1'] = float(max_bas.iloc[0]['hr_consumed'])
                if len(max_bas) > 1: res['bas_p2'] = float(max_bas.iloc[1]['hr_consumed'])
                
                # Höglast (Nov-Mar, Mån-Fre 07-20)
                mask_hog = df_peaks['hour_ts'].apply(settings.is_high_load_time)
                df_hog = df_peaks[mask_hog]
                if not df_hog.empty:
                    idx_hog = df_hog.groupby('day_date')['hr_consumed'].idxmax()
                    max_hog = df_hog.loc[idx_hog].sort_values('hr_consumed', ascending=False)
                    if len(max_hog) > 0: res['hog_p1'] = float(max_hog.iloc[0]['hr_consumed'])
                    if len(max_hog) > 1: res['hog_p2'] = float(max_hog.iloc[1]['hr_consumed'])
            
            _cached_monthly_peaks = res
            _cached_monthly_peaks_time = now
            return res
    except Exception as e:
        print(f"❌ Fel vid hämtning av månadstoppar: {e}")
        if _cached_monthly_peaks:
            return _cached_monthly_peaks
    return {'bas_p1': 0.0, 'bas_p2': 0.0, 'hog_p1': 0.0, 'hog_p2': 0.0}

def log_mower_status(status: str, power_w: float, is_on: bool):
    """Loggar robotgräsklipparens status till en separat tabell."""
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS mower_log (
                        timestamp TIMESTAMPTZ PRIMARY KEY,
                        status VARCHAR(50),
                        power_w NUMERIC,
                        is_on BOOLEAN
                    )
                """)
                cur.execute("INSERT INTO mower_log (timestamp, status, power_w, is_on) VALUES (NOW(), %s, %s, %s)", (status, power_w, is_on))
            conn.commit()
    except Exception as e:
        print(f"❌ Fel vid loggning av robotgräsklippare: {e}")

def get_mower_power_off_since():
    """Returnerar tidpunkten då klipparens plugg senast slogs av (om den fortfarande är av),
    annars None. Används för att återställa failsafe-/larmtimern korrekt efter en omstart,
    så att en plugg som redan varit av i >15 min larmar direkt i stället för att nollställas."""
    try:
        with get_db() as conn, conn.cursor() as cur:
            cur.execute("SELECT is_on FROM mower_log ORDER BY timestamp DESC LIMIT 1")
            row = cur.fetchone()
            if not row or row[0]:   # ingen historik, eller senast PÅ → ingen pågående av-period
                return None
            # Första av-loggen efter den senaste på-loggen = när den faktiskt slogs av.
            cur.execute("""
                SELECT MIN(timestamp) FROM mower_log
                WHERE timestamp > COALESCE(
                    (SELECT MAX(timestamp) FROM mower_log WHERE is_on = TRUE), 'epoch')
            """)
            r = cur.fetchone()
            return r[0] if r and r[0] else None
    except Exception as e:
        print(f"❌ Kunde inte läsa klipparens av-tidpunkt: {e}")
        return None
