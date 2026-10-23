import os
import psycopg
import pandas as pd
from contextlib import contextmanager

# Hämta inloggningsuppgifter från Docker-miljön
DB_HOST = "postgres-smartbox"  # Namnet på databastjänsten i docker-compose.yml
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

def is_high_load_time(dt):
    """
    Standardiserad kontroll för Jönköping Energis Höglasttariff.
    Gäller vardagar (Mån-Fre) kl 07:00-19:59 under månaderna Nov-Mar.
    """
    return dt.month in [11, 12, 1, 2, 3] and dt.weekday() <= 4 and 7 <= dt.hour < 20

def init_settings_db():
    """Skapar inställningstabellen och lägger in standardvärden om den är tom."""
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS system_settings (
                        id INTEGER PRIMARY KEY,
                        cheap_hours_count INTEGER,
                        temp_cheap NUMERIC,
                        temp_expensive NUMERIC,
                        indoor_max NUMERIC,
                        indoor_min NUMERIC
                    )
                """)
                # Lägg in standardvärdena (id=1) om tabellen precis skapades
                cur.execute("""
                    INSERT INTO system_settings (id, cheap_hours_count, temp_cheap, temp_expensive, indoor_max, indoor_min)
                    VALUES (1, 8, 22.0, 20.0, 22.5, 19.0)
                    ON CONFLICT (id) DO NOTHING
                """)
                # Lägg till radiatorkolumner om de saknas (bakåtkompatibelt)
                for col, default in [
                    ("friggebod_target", 5.0),
                    ("friggebod_frost",  1.0),
                    ("garage_target",   12.0),
                    ("garage_frost",     4.0),
                    ("radiator_solar_w", 300),
                    ("spa_max_temp",    40.0),
                    ("spa_normal_temp", 34.0),
                    ("spa_low_temp",    15.0),
                    ("fuse_size_a",     25.0),
                ]:
                    cur.execute(f"""
                        ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS {col} NUMERIC DEFAULT {default}
                    """)
                    cur.execute(f"""
                        UPDATE system_settings SET {col} = {default} WHERE {col} IS NULL
                    """)

                for col in ["notify_spa_ready", "notify_ev_start", "notify_washer_start", "spa_force_heat", "notify_spa_open"]:
                    default_val = 'FALSE' if col == 'spa_force_heat' else 'TRUE'
                    cur.execute(f"ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS {col} BOOLEAN DEFAULT {default_val}")
                    cur.execute(f"UPDATE system_settings SET {col} = {default_val} WHERE {col} IS NULL")
                
                # Nya kolumner för spabad-schema
                cur.execute("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS spa_schedule_enabled BOOLEAN DEFAULT FALSE")
                cur.execute("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS spa_target_datetime TIMESTAMPTZ")
                cur.execute("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS spa_target_temp NUMERIC")
                cur.execute("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS spa_model_intercept NUMERIC")
                cur.execute("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS spa_model_slope NUMERIC")
                cur.execute("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS spa_cooling_model_intercept NUMERIC")
                cur.execute("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS spa_cooling_model_slope NUMERIC")
                cur.execute("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS power_limit_kw NUMERIC DEFAULT 10.0")
                cur.execute("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS power_limit_kw_bas NUMERIC DEFAULT 0.0")
                cur.execute("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS power_limit_kw_hog NUMERIC DEFAULT 0.0")
                cur.execute("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS ev_nissan_prio INTEGER DEFAULT 2")
                cur.execute("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS ev_tesla_prio INTEGER DEFAULT 1")
                cur.execute("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS away_mode_enabled BOOLEAN DEFAULT FALSE")
                cur.execute("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS away_return_date TIMESTAMPTZ")
                cur.execute("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS away_lights_on_return TEXT DEFAULT ''")
                cur.execute("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS legionella_temp NUMERIC DEFAULT 60.0")
                cur.execute("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS legionella_days INTEGER DEFAULT 14")
                cur.execute("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS water_target_normal NUMERIC DEFAULT 50.0")
                cur.execute("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS peak_shaving_enabled BOOLEAN DEFAULT TRUE")
                cur.execute("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS gemini_api_key TEXT DEFAULT ''")
                cur.execute("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS roi_hardware_cost NUMERIC DEFAULT 0.0")
                # Robotgräsklippare
                cur.execute("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS mower_mowing_threshold_w NUMERIC DEFAULT 3.2")
                cur.execute("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS mower_charging_threshold_w NUMERIC DEFAULT 10.0")
                cur.execute("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS notify_mower_start BOOLEAN DEFAULT TRUE")
                cur.execute("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS notify_mower_charging BOOLEAN DEFAULT TRUE")
                cur.execute("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS notify_mower_idle BOOLEAN DEFAULT TRUE")
                cur.execute("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS notify_mower_manual_toggle BOOLEAN DEFAULT TRUE")
                cur.execute("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS notify_mower_weather_toggle BOOLEAN DEFAULT TRUE")
                
                cur.execute("UPDATE system_settings SET notify_mower_start = TRUE WHERE notify_mower_start IS NULL")
                cur.execute("UPDATE system_settings SET notify_mower_charging = TRUE WHERE notify_mower_charging IS NULL")

            conn.commit()
        print("🗄️ Databas: Inställningstabellen är redo.")
    except Exception as e:
        print(f"❌ Kunde inte initiera inställnings-databasen: {e}")

def get_settings():
    """Hämtar de aktuella inställningarna från databasen."""
    # Failsafe: Om databasen strular, använd dessa standardvärden
    defaults = {
        "cheap_hours_count":  8,
        "temp_cheap":         22.0,
        "temp_expensive":     20.0,
        "indoor_max":         22.5,
        "indoor_min":         19.0,
        "spa_max_temp":       40.0,
        "spa_normal_temp":    34.0,
        "notify_spa_ready":   True,
        "notify_ev_start":    True,
        "notify_washer_start":True,
        "notify_spa_open":    True,
        "spa_low_temp":       15.0,
        "spa_force_heat":     False,
        "spa_schedule_enabled": False,
        "spa_target_datetime": None,
        "spa_target_temp":    None,
        "spa_model_intercept": None,
        "spa_model_slope":    None,
        "power_limit_kw":     10.0,
        "power_limit_kw_bas": 0.0,
        "power_limit_kw_hog": 0.0,
        "fuse_size_a":        25.0,
        "ev_nissan_prio":     2,
        "ev_tesla_prio":      1,
        "away_mode_enabled":  False,
        "away_return_date":   None,
        "away_lights_on_return": "",
        "peak_shaving_enabled": True,
        "gemini_api_key": "",
        "roi_hardware_cost": 0.0,
        "mower_mowing_threshold_w": 3.2,
        "mower_charging_threshold_w": 10.0,
        "notify_mower_start": True,
        "notify_mower_charging": True,
        "notify_mower_idle": True,
        "notify_mower_manual_toggle": True,
        "notify_mower_weather_toggle": True,
    }
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT *
                    FROM system_settings WHERE id = 1
                """)
                row = cur.fetchone()
                db_settings = {}
                if row:
                    colnames = [desc[0] for desc in cur.description]
                    db_settings = dict(zip(colnames, row))

                # Använd värden från databasen, men fall tillbaka på defaults om en nyckel saknas
                result = defaults.copy()
                if db_settings:
                    for k, v in db_settings.items():
                        if v is not None:
                            result[k] = v
                
                # Vissa värden behöver typomvandlas för main.py
                result["cheap_hours_count"] = int(result["cheap_hours_count"])
                result["temp_cheap"]        = float(result["temp_cheap"])
                result["temp_expensive"]    = float(result["temp_expensive"])
                result["indoor_max"]        = float(result["indoor_max"])
                result["indoor_min"]        = float(result["indoor_min"])
                result["power_limit_kw"]    = float(result["power_limit_kw"])
                result["power_limit_kw_bas"]= float(result["power_limit_kw_bas"]) if result.get("power_limit_kw_bas") is not None else 0.0
                result["power_limit_kw_hog"]= float(result["power_limit_kw_hog"]) if result.get("power_limit_kw_hog") is not None else 0.0
                result["fuse_size_a"]       = float(result["fuse_size_a"]) if result.get("fuse_size_a") is not None else 25.0
                
                result["spa_target_temp"]   = float(result["spa_target_temp"]) if result.get("spa_target_temp") is not None else None
                result["spa_max_temp"]      = float(result["spa_max_temp"]) if result.get("spa_max_temp") is not None else 40.0
                result["spa_normal_temp"]   = float(result["spa_normal_temp"]) if result.get("spa_normal_temp") is not None else 34.0
                result["spa_low_temp"]      = float(result["spa_low_temp"]) if result.get("spa_low_temp") is not None else 15.0
                result["water_target_normal"]= float(result["water_target_normal"]) if result.get("water_target_normal") is not None else 50.0
                result["legionella_temp"]   = float(result["legionella_temp"]) if result.get("legionella_temp") is not None else 60.0
                result["ev_nissan_prio"]    = int(result.get("ev_nissan_prio", 2))
                result["ev_tesla_prio"]     = int(result.get("ev_tesla_prio", 1))
                result["away_mode_enabled"] = bool(result.get("away_mode_enabled", False))
                result["away_return_date"]  = result.get("away_return_date")
                result["away_lights_on_return"] = result.get("away_lights_on_return", "")
                result["peak_shaving_enabled"] = bool(result.get("peak_shaving_enabled", True))
                result["gemini_api_key"] = db_settings.get("gemini_api_key", "")
                result["roi_hardware_cost"] = float(db_settings.get("roi_hardware_cost", 0.0)) if db_settings.get("roi_hardware_cost") is not None else 0.0
                result["mower_mowing_threshold_w"] = float(db_settings.get("mower_mowing_threshold_w", 3.2))
                result["mower_charging_threshold_w"] = float(db_settings.get("mower_charging_threshold_w", 10.0))
                result["notify_mower_start"] = bool(db_settings.get("notify_mower_start", True))
                result["notify_mower_charging"] = bool(db_settings.get("notify_mower_charging", True))
                result["notify_mower_idle"] = bool(db_settings.get("notify_mower_idle", True))
                result["notify_mower_manual_toggle"] = bool(db_settings.get("notify_mower_manual_toggle", True))
                result["notify_mower_weather_toggle"] = bool(db_settings.get("notify_mower_weather_toggle", True))
                
                return result
    except Exception as e:
        print(f"❌ Fel vid läsning av inställningar: {e}")

    return defaults

def get_climate_schedule():
    """Hämtar klimatschemat från databasen."""
    schedule = {
        'nissan': {'enabled': False, 'target_time': '07:00', 'target_temp': 21.0},
        'tesla': {'enabled': False, 'target_time': '07:00', 'target_temp': 21.0}
    }
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS climate_schedule (
                        car_id VARCHAR(20) PRIMARY KEY,
                        target_time TIME,
                        target_temp NUMERIC,
                        enabled BOOLEAN DEFAULT FALSE
                    )
                """)
            conn.commit()
            df = pd.read_sql("SELECT * FROM climate_schedule", conn)
            for _, row in df.iterrows():
                car = row['car_id']
                if car in schedule:
                    schedule[car] = {
                        'enabled': row['enabled'],
                        'target_time': row['target_time'].strftime('%H:%M'),
                        'target_temp': float(row['target_temp'])
                    }
    except Exception as e:
        print(f"❌ Kunde inte ladda klimatschema: {e}")
    return schedule

def get_ev_schedule():
    """Hämtar laddningsschemat från databasen."""
    schedule = {
        'nissan': {i: {'enabled': False, 'target_time': '07:00', 'target_soc': 100, 'panic_mode': False} for i in range(7)},
        'tesla': {i: {'enabled': False, 'target_time': '07:00', 'target_soc': 100, 'panic_mode': False} for i in range(7)}
    }
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS ev_charging_schedule (
                        car_id VARCHAR(20),
                        day_of_week INTEGER,
                        target_time TIME,
                        target_soc INTEGER DEFAULT 100,
                        enabled BOOLEAN DEFAULT FALSE,
                        panic_mode BOOLEAN DEFAULT FALSE,
                        PRIMARY KEY (car_id, day_of_week)
                    )
                """)
                cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='ev_charging_schedule' AND column_name='panic_mode'")
                if cur.fetchone() is None:
                    cur.execute("ALTER TABLE ev_charging_schedule ADD COLUMN panic_mode BOOLEAN DEFAULT FALSE")
            conn.commit()

            df = pd.read_sql("SELECT * FROM ev_charging_schedule", conn)
            for _, row in df.iterrows():
                car = row['car_id']
                day = row['day_of_week']
                if car in schedule and 0 <= day <= 6:
                    schedule[car][day] = {
                        'enabled': row['enabled'],
                        'target_time': row['target_time'].strftime('%H:%M'),
                        'target_soc': int(row['target_soc']),
                        'panic_mode': bool(row.get('panic_mode', False))
                    }
    except psycopg.errors.UndefinedTable:
        # Tabellen finns inte, returnera default. Den skapas av app.py eller nästa körning.
        print("⚠️ Tabellen ev_charging_schedule finns inte, använder standardschema.")
    except Exception as e:
        print(f"❌ Kunde inte ladda EV-schema: {e}")
    return schedule

def save_ev_schedule_db(car_id, schedule_data):
    """Sparar en hel veckas EV-schema för en specifik bil."""
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                for day, data in schedule_data.items():
                    cur.execute("""
                        INSERT INTO ev_charging_schedule (car_id, day_of_week, target_time, enabled, target_soc, panic_mode)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (car_id, day_of_week) DO UPDATE SET
                            target_time = EXCLUDED.target_time,
                            enabled = EXCLUDED.enabled,
                            target_soc = EXCLUDED.target_soc,
                            panic_mode = EXCLUDED.panic_mode
                    """, (car_id, day, data['target_time'], data['enabled'], data['target_soc'], data.get('panic_mode', False)))
            conn.commit()
    except Exception as e:
        print(f"❌ Kunde inte spara schema för {car_id}: {e}")

def save_ev_schedule_day(car_id, day_of_week, target_time, target_soc, enabled, panic_mode=False):
    """Sparar eller uppdaterar en enskild dag i EV-schemat."""
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO ev_charging_schedule (car_id, day_of_week, target_time, target_soc, enabled, panic_mode)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (car_id, day_of_week) DO UPDATE SET 
                        target_time = EXCLUDED.target_time, 
                        target_soc = EXCLUDED.target_soc, 
                        enabled = EXCLUDED.enabled,
                        panic_mode = EXCLUDED.panic_mode
                """, (car_id, day_of_week, target_time, target_soc, enabled, panic_mode))
            conn.commit()
    except Exception as e:
        print(f"❌ Fel vid auto-schema för {car_id}: {e}")

def save_climate_schedule_db(car_id, enabled, target_time, target_temp):
    """Sparar klimatschemat för en elbil."""
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO climate_schedule (car_id, target_time, target_temp, enabled)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (car_id) DO UPDATE SET target_time = EXCLUDED.target_time, target_temp = EXCLUDED.target_temp, enabled = EXCLUDED.enabled
                """, (car_id, target_time, target_temp, enabled))
            conn.commit()
    except Exception as e:
        print(f"❌ Fel vid sparning av klimatschema för {car_id}: {e}")