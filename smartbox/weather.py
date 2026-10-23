import os
import math
import requests
import urllib3
# Tysta varning om självsignerat HA-cert (verify=False) – samma mönster som homeassistant.py.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from datetime import datetime, timedelta
from contextlib import contextmanager
import zoneinfo

SWE_TZ = zoneinfo.ZoneInfo("Europe/Stockholm")

DB_HOST = "postgres-smartbox"
DB_USER = os.environ.get("POSTGRES_USER")
DB_PASS = os.environ.get("POSTGRES_PASSWORD")
DB_NAME = os.environ.get("POSTGRES_DB")

# 🌍 Koordinater för Taberg
LATITUDE  = 57.6797
LONGITUDE = 14.1293

# Robotgräsklippare: SMHI rapporterar åska som en sannolikhet i procent (parametern "tstm").
# Över denna gräns betraktar vi det som åska och stänger av klipparens plugg.
THUNDER_PROB_THRESHOLD = 20.0

from logger import get_db, get_db_pool
import learning

def init_weather_db():
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS weather_forecast (
                        timestamp   TIMESTAMP WITH TIME ZONE PRIMARY KEY,
                        temp        NUMERIC,
                        cloud_cover NUMERIC,
                        wind_speed  NUMERIC,
                        wind_dir    NUMERIC,
                        precipitation_category NUMERIC,
                        rain_probability       NUMERIC,
                        thunder_probability    NUMERIC
                    )
                """)
            conn.commit()
        _add_precip_column()
        print("🌤️ Databas: Vädertabellen är redo.")
    except Exception as e:
        print(f"❌ Kunde inte initiera väder-databasen: {e}")

def _add_precip_column():
    """Lägger till nederbörds-, regn- och åskkolumnerna om de saknas (idempotent)."""
    try:
        with get_db() as conn, conn.cursor() as cur:
            cur.execute("ALTER TABLE weather_forecast ADD COLUMN IF NOT EXISTS precipitation_category NUMERIC")
            cur.execute("ALTER TABLE weather_forecast ADD COLUMN IF NOT EXISTS rain_probability NUMERIC")
            cur.execute("ALTER TABLE weather_forecast ADD COLUMN IF NOT EXISTS thunder_probability NUMERIC")
    except Exception: pass

# FIX (audit critical #1): SMHI:s gamla pmp3g-endpoint är nedlagd (404) sedan 2026-03-31,
# och HA:s SMHI-integration var 'unavailable'. Vi hämtar därför prognosen direkt från
# Open-Meteo (gratis, ingen API-nyckel, aktivt underhållen). DB-schema och publika
# funktioner är oförändrade.
OPEN_METEO_URL = (
    "https://api.open-meteo.com/v1/forecast"
    f"?latitude={LATITUDE}&longitude={LONGITUDE}"
    "&hourly=temperature_2m,cloudcover,windspeed_10m,winddirection_10m,"
    "precipitation,precipitation_probability,weathercode"
    "&forecast_days=3&timezone=UTC&windspeed_unit=ms"
)

# WMO weathercode: regn/dugg/skurar (-> nederbördskategori 3) och åska.
_RAIN_WMO    = {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99}
_THUNDER_WMO = {95, 96, 99}

def update_forecast():
    """Hämtar timväderprognos från Open-Meteo och skriver över gamla värden.

    DB-schemat (weather_forecast) och övriga publika funktioner är oförändrade.
    Tider kommer i UTC och konverteras till svensk tid.
    """
    try:
        _add_precip_column()
        response = requests.get(OPEN_METEO_URL, timeout=15)
        if response.status_code != 200:
            print(f"❌ Fel vid Open-Meteo väder-API: HTTP {response.status_code}")
            return False

        h = response.json().get("hourly", {})
        times = h.get("time", [])
        temps = h.get("temperature_2m", [])
        clouds = h.get("cloudcover", [])
        winds = h.get("windspeed_10m", [])
        wind_dirs = h.get("winddirection_10m", [])
        precips = h.get("precipitation", [])
        rain_probs = h.get("precipitation_probability", [])
        wcodes = h.get("weathercode", [])

        def _at(arr, i):
            return arr[i] if i < len(arr) else None

        records = []
        for i, t_raw in enumerate(times):
            temp = _at(temps, i)
            if temp is None:
                continue
            # Open-Meteo med timezone=UTC ger naiva UTC-tider ("2026-06-29T14:00").
            dt = datetime.fromisoformat(t_raw).replace(tzinfo=zoneinfo.ZoneInfo("UTC")).astimezone(SWE_TZ)

            cloud_pct = _at(clouds, i)            # redan procent (0–100)
            wind      = _at(winds, i)             # m/s (windspeed_unit=ms)
            wind_dir  = _at(wind_dirs, i)
            precip    = _at(precips, i)           # mm under timmen
            rain_prob = _at(rain_probs, i)        # procent (kan saknas)
            wcode     = _at(wcodes, i)

            is_rain = (wcode in _RAIN_WMO) or (precip is not None and precip > 0)
            precip_cat = 3 if is_rain else 0      # behåller gamla SMHI-semantiken: 3 = regn
            if rain_prob is None:
                rain_prob = 100.0 if is_rain else 0.0
            thunder = 100.0 if wcode in _THUNDER_WMO else 0.0

            records.append((dt, temp, cloud_pct, wind, wind_dir, precip_cat, rain_prob, thunder))

        if not records:
            print("❌ Open-Meteo: tom prognos.")
            return False

        with get_db() as conn:
            with conn.cursor() as cur:
                cur.executemany("""
                    INSERT INTO weather_forecast (timestamp, temp, cloud_cover, wind_speed, wind_dir, precipitation_category, rain_probability, thunder_probability)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (timestamp) DO UPDATE
                    SET temp        = EXCLUDED.temp,
                        cloud_cover = EXCLUDED.cloud_cover,
                        wind_speed  = EXCLUDED.wind_speed,
                        wind_dir    = EXCLUDED.wind_dir,
                        precipitation_category = EXCLUDED.precipitation_category,
                        rain_probability       = EXCLUDED.rain_probability,
                        thunder_probability    = EXCLUDED.thunder_probability
                """, records)
            conn.commit()
        print(f"📥 Väderprognos hämtad från Open-Meteo ({len(records)} timmar).")
        return True
    except Exception as e:
        print(f"❌ Fel vid Open-Meteo väder-API: {e}")
    return False

def get_weather_at(dt):
    hour = dt.replace(minute=0, second=0, microsecond=0)
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT cloud_cover, wind_speed, temp, wind_dir FROM weather_forecast WHERE timestamp = %s",
                    (hour,)
                )
                row = cur.fetchone()
                if row:
                    wind_d = float(row[3]) if row[3] is not None else 0.0
                    temp = float(row[2])
                    # FIX (ML-korrekthet): Applicera INTE väder-biasen här. Den loggade
                    # Vi returnerar RÅ prognostemp (ingen bias-korrigering här). En ev. framtida
                    # korrigering bör ske i en separat get_weather_at_corrected() hos de konsumenter
                    # som vill ha den – inte här – annars riskeras en återkopplingsloop mot den egna
                    # träningsdatan (forecast_temp loggas ju och används som träningssignal).
                    return float(row[0]), float(row[1]), temp, wind_d
    except Exception as e:
        print(f"❌ Fel vid läsning av väder från DB: {e}")
    return 0.0, 0.0, 0.0, 0.0

def get_current_weather():
    cloud, wind, temp, wind_dir = get_weather_at(datetime.now(SWE_TZ))
    return cloud, wind, wind_dir, temp

def estimate_solar_w(cloud_cover_pct, dt):
    """
    Skräddarsydd modell för 16 kWp, 45° takvinkel, rakt söderläge.
    Helt utan skuggning.
    """
    month = dt.month
    hour = dt.hour + dt.minute / 60.0

    sun_times = {
        1: (8.5, 15.5), 2: (7.5, 17.0), 3: (6.2, 18.0), 4: (5.0, 20.0),
        5: (4.5, 21.5), 6: (4.0, 22.0), 7: (4.5, 21.7), 8: (5.5, 20.5),
        9: (6.5, 19.0), 10: (7.5, 17.5), 11: (8.0, 15.5), 12: (8.7, 15.0)
    }
    sunrise, sunset = sun_times[month]

    if hour < sunrise or hour >= sunset:
        return 0.0

    day_progress = (hour - sunrise) / (sunset - sunrise)

    monthly_efficiency = {
        1: 0.35, 2: 0.50, 3: 0.70, 4: 0.85,
        5: 0.95, 6: 1.00, 7: 0.95, 8: 0.85,
        9: 0.75, 10: 0.55, 11: 0.40, 12: 0.30,
    }
    peak_w = 16000 * monthly_efficiency[month]
    
    # Perfekt sinuskurva för sydligt läge
    clear_sky_prod = math.sin(day_progress * math.pi) * peak_w
    
    cloud_factor = 1.0 - (cloud_cover_pct / 100.0) * 0.85

    return round(clear_sky_prod * cloud_factor, 1)

def get_smart_solar_w(cloud_cover_pct, dt, solar_profile=None):
    """Använder husets digitala tvilling (inlärd maxproduktion per månad/timme) om den finns."""
    if solar_profile is None:
        solar_profile = learning.get_solar_profile()
    if solar_profile:
        roof_max = solar_profile.get((dt.month, dt.hour))
        if roof_max is not None:
            return max(0.0, roof_max * (1.0 - (cloud_cover_pct / 100.0) * 0.85))
    return estimate_solar_w(cloud_cover_pct, dt)

def get_solar_forecast_now_and_next():
    now       = datetime.now(SWE_TZ)
    next_hour = now.replace(minute=0, second=0, microsecond=0)
    next_hour = next_hour.replace(hour=next_hour.hour + 1) if next_hour.hour < 23 else next_hour

    cloud_now,  _, _, _ = get_weather_at(now)
    cloud_next, _, _, _ = get_weather_at(next_hour)

    solar_now  = get_smart_solar_w(cloud_now,  now)
    solar_next = get_smart_solar_w(cloud_next, next_hour)

    return solar_now, solar_next

def is_raining_soon(hours_ahead=2):
    """
    Kollar om det regnar (eller kommer regna inom `hours_ahead` timmar).
    Returnerar True om regn (kategori 3, 4, 5, 6) detekteras.
    """
    try:
        with get_db() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT 1 FROM weather_forecast
                WHERE timestamp >= NOW() AND timestamp < NOW() + (%s * INTERVAL '1 hour')
                AND precipitation_category >= 3
                LIMIT 1
            """, (hours_ahead,))
            return cur.fetchone() is not None
    except Exception:
        return False

def is_thundering_soon(hours_ahead=2):
    """
    Kollar om åska rapporteras nu eller inom `hours_ahead` timmar.
    Returnerar True om åsk-sannolikheten överstiger THUNDER_PROB_THRESHOLD.
    """
    try:
        with get_db() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT 1 FROM weather_forecast
                WHERE timestamp >= NOW() AND timestamp < NOW() + (%s * INTERVAL '1 hour')
                AND thunder_probability >= %s
                LIMIT 1
            """, (hours_ahead, THUNDER_PROB_THRESHOLD))
            return cur.fetchone() is not None
    except Exception:
        return False

def get_mower_weather_block(now=None):
    """
    Avgör om robotgräsklipparen bör skyddas mot vädret just nu.

    Tittar på aktuell timmes prognos (och nästa timme, för att hinna parkera innan
    ovädret är framme). Returnerar tupeln (is_raining, is_thunder).

    FAIL-SAFE: Om prognosdata saknas eller är inaktuell returneras (False, False),
    dvs. klipparen tillåts köra. Vi vill hellre missa en avstängning än att felaktigt
    parkera klipparen p.g.a. en trasig/inaktuell väderkälla.
    """
    if now is None:
        now = datetime.now(SWE_TZ)
    this_hour = now.replace(minute=0, second=0, microsecond=0)
    next_hour = this_hour + timedelta(hours=1)
    try:
        with get_db() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT precipitation_category, thunder_probability
                FROM weather_forecast
                WHERE timestamp IN (%s, %s)
                """,
                (this_hour, next_hour),
            )
            rows = cur.fetchall()
        if not rows:
            return False, False
        is_raining = any(r[0] is not None and float(r[0]) >= 3 for r in rows)
        is_thunder = any(r[1] is not None and float(r[1]) >= THUNDER_PROB_THRESHOLD for r in rows)
        return is_raining, is_thunder
    except Exception as e:
        print(f"❌ Fel vid väderkoll för gräsklippare: {e}")
        return False, False