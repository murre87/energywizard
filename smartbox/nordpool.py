import os
import requests
import psycopg
from datetime import datetime, timedelta
from contextlib import contextmanager
import zoneinfo

SWE_TZ = zoneinfo.ZoneInfo("Europe/Stockholm")

DB_HOST = os.environ.get("POSTGRES_HOST", "postgres-smartbox")
DB_USER = os.environ.get("POSTGRES_USER")
DB_PASS = os.environ.get("POSTGRES_PASSWORD")
DB_NAME = os.environ.get("POSTGRES_DB")

from logger import get_db

def init_db():
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS elpriser (
                        time_start TIMESTAMP WITH TIME ZONE PRIMARY KEY,
                        time_end   TIMESTAMP WITH TIME ZONE,
                        sek_per_kwh NUMERIC
                    )
                """)
            conn.commit()
    except Exception as e:
        print(f"❌ Kunde inte initiera databasen: {e}")

def fetch_api_and_save(date_obj):
    date_str = date_obj.strftime("%Y/%m-%d")
    url = f"https://www.elprisetjustnu.se/api/v1/prices/{date_str}_SE3.json"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            records = [
                (item['time_start'], item['time_end'], item['SEK_per_kWh'])
                for item in data
            ]
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.executemany("""
                        INSERT INTO elpriser (time_start, time_end, sek_per_kwh)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (time_start) DO NOTHING
                    """, records)
                conn.commit()
            print(f"📥 Laddade ner {len(records)} rader för {date_str}.")
            return True
    except Exception as e:
        print(f"❌ Fel vid API-hämtning för {date_str}: {e}")
    return False

def ensure_prices_exist():
    now = datetime.now(SWE_TZ)
    today    = now.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow = today + timedelta(days=1)
    day_after = tomorrow + timedelta(days=1)

    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM elpriser WHERE time_start >= %s AND time_start < %s", (today, tomorrow))
                if cur.fetchone()[0] == 0:
                    print("⚠️ Saknar priser för idag. Hämtar från API...")
                    # FIX: Agera på fetch-status så tyst degradering (tom prislista -> dyra
                    # default-lägen) syns i loggen istället för att ignoreras.
                    if not fetch_api_and_save(today):
                        print("❌ KRITISKT: Kunde inte hämta dagens priser – pris-optimering "
                              "(peak shaving/EV/värme/spa) faller tillbaka till default tills priser finns.")

                if (now.hour == 13 and now.minute >= 30) or now.hour >= 14:
                    cur.execute("SELECT COUNT(*) FROM elpriser WHERE time_start >= %s AND time_start < %s", (tomorrow, day_after))
                    if cur.fetchone()[0] == 0:
                        print("📅 Hämtar morgondagens priser...")
                        # FIX: Logga om morgondagens priser inte kunde hämtas (kan ännu inte
                        # vara publicerade) så det inte tystas helt.
                        if not fetch_api_and_save(tomorrow):
                            print("⚠️ Morgondagens priser kunde inte hämtas ännu – försöker igen nästa cykel.")
    except Exception as e:
        print(f"❌ Databasfel vid kontroll av priser: {e}")


def get_price_at(dt):
    """Returnerar elpriset för en given tidpunkt."""
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT sek_per_kwh FROM elpriser
                    WHERE time_start <= %s AND time_end > %s
                """, (dt, dt))
                row = cur.fetchone()
                return float(row[0]) if row else None
    except Exception as e:
        print(f"❌ Fel vid hämtning av pris för tidpunkt: {e}")
    return None

def _recent_actual_price_avg():
    """Senaste 7 dygnens faktiska snittpris (kr/kWh), för nivåjustering av prisprognosen."""
    try:
        with get_db() as conn, conn.cursor() as cur:
            cur.execute("SELECT AVG(sek_per_kwh) FROM elpriser WHERE time_start >= NOW() - INTERVAL '7 days' AND sek_per_kwh IS NOT NULL")
            r = cur.fetchone()
            return float(r[0]) if r and r[0] is not None else None
    except Exception:
        return None

def forecast_price_at(dt):
    """Prisprognos BORTOM Nordpools publicerade horisont.

    Returnerar (pris, är_prognos): publicerat pris om det finns (är_prognos=False), annars en
    MODELLERAD uppskattning (inlärd dygnsform × aktuell prisnivå, är_prognos=True), eller
    (None, True) om varken pris eller modell finns. Modellen fångar dygns-/säsongsmönstret –
    inte exakta toppar – och ska därför användas för PLANERING/visning, inte som facit."""
    published = get_price_at(dt)
    if published is not None:
        return published, False
    try:
        import learning
        shape = learning.get_price_shape_profile()
    except Exception:
        shape = None
    if not shape:
        return None, True
    s = shape.get((dt.month, dt.hour))
    if s is None:
        # Fallback: saknas månadens cell (t.ex. ingen historik för nästa månad ännu) → använd
        # timmens snitt över alla månader (dygnsformen är lik; nivåfaktorn korrigerar nivån).
        hour_cells = [v for (m, h), v in shape.items() if h == dt.hour]
        s = (sum(hour_cells) / len(hour_cells)) if hour_cells else None
    if s is None:
        return None, True
    # Nivåjustering: skala formen så dess snitt för innevarande månad matchar senaste 7 dygns faktiska snitt.
    month_cells = [v for (m, h), v in shape.items() if m == dt.month] or list(shape.values())
    shape_month_avg = (sum(month_cells) / len(month_cells)) if month_cells else None
    actual = _recent_actual_price_avg()
    factor = 1.0
    if shape_month_avg and shape_month_avg > 0 and actual is not None:
        factor = max(0.3, min(3.0, actual / shape_month_avg))
    return round(s * factor, 4), True

# FIX: Tog bort get_upcoming_prices() – död kod (verifierat med grep: inga referenser i
# smartbox/ eller smartdashboard/ utanför denna fil).


def calculate_day_strategy(all_prices, cheap_hours_count):
    """
    Räknar ut dagens regleringsstrategi baserat på prisbilden.

    Logik:
    - Billig dag (snitt < 0.50 kr, spread < 0.30 kr): kör komfort, ingen optimering
    - Annars: skala hysteres efter dagens spread så värmepumpen slipper fladdra
      vid små prisrörelser men reagerar på stora.

    Returns dict med:
      mode        : "comfort" | "optimize"
      hysteresis  : float (kr/kWh) – dead zone runt dynamic_limit
      dynamic_limit: float (kr/kWh)
      comfort_temp: int (pumpvärde, t.ex. 210 = 21.0°C) vid comfort-mode
      description : läsbar förklaring
    """
    if not all_prices:
        return {
            "mode": "optimize",
            "hysteresis": 0.10,
            "dynamic_limit": None,
            "comfort_temp": 210,
            "description": "Ingen prisdata – fallback hysteres 10 öre"
        }

    min_p  = min(all_prices)
    max_p  = max(all_prices)
    spread = max_p - min_p
    avg_p  = sum(all_prices) / len(all_prices)

    cheap_quarters = cheap_hours_count * 4
    dynamic_limit = sorted(all_prices)[cheap_quarters - 1] if len(all_prices) >= cheap_quarters else None

    # Billig dag – kör bara ett fast komfortvärde, spara compressorn
    if avg_p < 0.50 and spread < 0.30:
        return {
            "mode": "comfort",
            "hysteresis": 0.0,
            "dynamic_limit": dynamic_limit,
            "comfort_temp": 210,
            "description": f"Billig dag (snitt {avg_p:.2f} kr, spread {spread:.2f} kr) – kör 21°C komfort"
        }

    # Skala hysteres: 15 % av spreaden, clampat 5–20 öre
    hysteresis = round(min(max(spread * 0.15, 0.05), 0.20), 3)

    return {
        "mode": "optimize",
        "hysteresis": hysteresis,
        "dynamic_limit": dynamic_limit,
        "comfort_temp": 210,
        "description": f"Optimerar (snitt {avg_p:.2f} kr, spread {spread:.2f} kr → hysteres {hysteresis:.2f} kr)"
    }

def get_price_info(cheap_hours_count=8):
    """Huvudfunktion: returnerar (current_price, dynamic_limit, strategy, all_prices)."""
    init_db()
    ensure_prices_exist()

    now = datetime.now(SWE_TZ)
    today_start    = now.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_start = today_start + timedelta(days=1)
    cheap_quarters_count = cheap_hours_count * 4

    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                # Aktuellt pris
                cur.execute("""
                    SELECT sek_per_kwh FROM elpriser
                    WHERE time_start <= %s AND time_end > %s
                """, (now, now))
                row = cur.fetchone()
                current_price = float(row[0]) if row else None

                # FIX: Hämta alla kvarterspriser idag i TIDSORDNING (inte prisordning).
                # Konsumenter (gpm.py prediktiv överladdning, notifier morgontips) indexerar
                # all_prices per kvart (t.ex. all_prices[hour*4 + minute//15]), så listan MÅSTE
                # vara tidssorterad. Prisrankning (cheap hours / dynamic_limit) görs separat via
                # sorted(...) i calculate_day_strategy och är därför opåverkad.
                cur.execute("""
                    SELECT sek_per_kwh FROM elpriser
                    WHERE time_start >= %s AND time_start < %s
                    ORDER BY time_start ASC
                """, (today_start, tomorrow_start))
                raw_prices = [float(r[0]) for r in cur.fetchall()]

                # FALLBACK (#2): saknas dagens priser helt → använd GÅRDAGENS prisprofil som
                # approximation (in-memory, skrivs EJ till DB så riktiga priser kan ta över direkt).
                # Mycket bättre än platt default-hysteres när elprisetjustnu.se tillfälligt är nere.
                price_fallback = False
                if not raw_prices:
                    cur.execute("""
                        SELECT sek_per_kwh FROM elpriser
                        WHERE time_start >= %s AND time_start < %s
                        ORDER BY time_start ASC
                    """, (today_start - timedelta(days=1), today_start))
                    y_prices = [float(r[0]) for r in cur.fetchall()]
                    if y_prices:
                        raw_prices = y_prices
                        price_fallback = True
                        print("⚠️ Dagens priser saknas – använder GÅRDAGENS prisprofil som fallback.")

                # Konvertera till 15-minuters array (96 slots) oavsett källa
                all_prices = []
                if 0 < len(raw_prices) <= 24:
                    for p in raw_prices:
                        all_prices.extend([p, p, p, p])
                else:
                    all_prices = raw_prices

                # Härled aktuellt pris ur fallback-profilen om realtidspriset saknas
                if current_price is None and price_fallback and all_prices:
                    idx = now.hour * 4 + now.minute // 15
                    current_price = all_prices[idx] if idx < len(all_prices) else all_prices[-1]

        strategy = calculate_day_strategy(all_prices, cheap_hours_count)
        strategy["price_fallback"] = price_fallback  # main.py notiserar (deduppat) vid fallback
        dynamic_limit = strategy.get("dynamic_limit")
        return current_price, dynamic_limit, strategy, all_prices

    except Exception as e:
        print(f"❌ Fel vid läsning från databas: {e}")
        return None, None, {"mode": "optimize", "hysteresis": 0.10, "comfort_temp": 210, "description": "DB-fel"}, []