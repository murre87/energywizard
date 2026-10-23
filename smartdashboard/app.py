import streamlit as st
import os
import hmac
import hashlib
import math
import time
import requests
import urllib3
urllib3.disable_warnings()

import altair as alt
import pandas as pd
from streamlit_echarts import st_echarts
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import zoneinfo
import sys

# --- Delad Plotly-render (fix: enhetlig, polerad chart-presentation 2026) ---
# Döljer Plotly-logga/lasso, svensk locale, responsiv. Alla diagram går via plot().
DEFAULT_PLOTLY_CONFIG = {
    "displaylogo": False,
    "locale": "sv",
    "responsive": True,
    "modeBarButtonsToRemove": ["lasso2d", "select2d"],
}

def plot(fig, **kwargs):
    """Wrapper runt st.plotly_chart: sätter width='stretch' + delad config som default
    men respekterar explicit angivna värden (t.ex. scrollZoom för kartan)."""
    kwargs.setdefault("width", "stretch")
    kwargs.setdefault("config", DEFAULT_PLOTLY_CONFIG)
    return st.plotly_chart(fig, **kwargs)

# Super-robust path-hantering för att hitta 'smartbox' oavsett Docker-mount
_base_dir = os.path.dirname(os.path.abspath(__file__))

# Lista över alla tänkbara sökvägar i prioritetsordning
# De mest troliga mapparna (t.ex. /smartbox) listas först för att säkerställa
# att de genomsöks före /app och eventuella installerade pip-paket.
_smartbox_paths = [
    os.path.abspath(os.path.join(_base_dir, '..', 'smartbox')),
    '/smartbox',
    '/app/smartbox',
    '/home/emil/opt/Energywizz/smartbox',
    '/opt/Energywizz/smartbox',
    os.path.join(_base_dir, 'smartbox'),
    _base_dir,
    '/app',
]

# Tvinga in alla mappar i sys.path utan os.path.isdir()-kontrollen.
# Detta förhindrar att Docker missar din folder och råkar ladda in pip-paket istället!
for _p in reversed(_smartbox_paths):
    while _p in sys.path:
        sys.path.remove(_p)
    sys.path.insert(0, _p)

try:
    import predictor as pred
    import learning
    import nordpool
    import weather
    import settings as settings_module
    import homeassistant
except ModuleNotFoundError as e:
    st.error(f"🚨 Kritiskt importfel: {e}")
    st.info("Systemet kan inte hitta `smartbox`-mappen. Detta beror sannolikt på att mappen inte är korrekt monterad som en volym i Docker.")
    st.write("**Aktuella sökvägar (sys.path):**", sys.path)
    st.write("**Filer i /app:**", os.listdir('/app') if os.path.exists('/app') else "Kunde inte läsa /app")
    st.stop()

# Mappning för värmepumpens driftläge (register 2201) - Kopierad från notifier.py
PUMP_MODE_MAP = {
    0: "All off",
    1: "Auto (Värme + Varmvatten)",
    2: "Normal (Endast värme)",
    3: "Endast tillsatsvärme",
    4: "Endast varmvatten",
}

SWE_TZ = zoneinfo.ZoneInfo("Europe/Stockholm")

DB_HOST = "postgres-smartbox"
DB_USER = os.environ.get("POSTGRES_USER")
DB_PASS = os.environ.get("POSTGRES_PASSWORD")
DB_NAME = os.environ.get("POSTGRES_DB")

from database_engine import SessionLocal, engine
from models import SystemSettings, Note, Override, MowerActivity
from sqlalchemy import select, text

# --- EKONOMI OCH EFFEKTTARIFF-HJÄLPARE ---
def calculate_peaks_for_month(month_start_dt):
    import pandas as pd
    df_hourly = pd.read_sql(text("""
        SELECT 
            DATE_TRUNC('hour', timestamp AT TIME ZONE 'Europe/Stockholm') as hour_ts,
            AVG(GREATEST(net_power, 0)) / 1000.0 as hr_consumed
        FROM sensor_log
        WHERE timestamp >= :start
          AND net_power IS NOT NULL
        GROUP BY 1
    """), engine, params={"start": month_start_dt})
    
    res = {
        "p1_bas": 0.0, "t1_bas": "Saknas", "p2_bas": 0.0, "t2_bas": "Saknas", "avg_bas": 0.0,
        "p1_hog": 0.0, "t1_hog": "Saknas", "p2_hog": 0.0, "t2_hog": "Saknas", "avg_hog": 0.0
    }
    
    if not df_hourly.empty:
        df_hourly['hour_ts'] = pd.to_datetime(df_hourly['hour_ts']).dt.tz_localize(None)
        df_hourly['day_date'] = df_hourly['hour_ts'].dt.date
        df_hourly['dow'] = df_hourly['hour_ts'].dt.dayofweek
        df_hourly['hour'] = df_hourly['hour_ts'].dt.hour
        df_hourly['month'] = df_hourly['hour_ts'].dt.month

        # Baslast (Dygnet runt, året runt)
        idx_bas = df_hourly.groupby('day_date')['hr_consumed'].idxmax()
        max_bas = df_hourly.loc[idx_bas].sort_values('hr_consumed', ascending=False)
        
        if len(max_bas) > 0:
            res["p1_bas"] = max_bas.iloc[0]['hr_consumed']
            res["t1_bas"] = max_bas.iloc[0]['hour_ts'].strftime('%d/%m kl %H:00')
        if len(max_bas) > 1:
            res["p2_bas"] = max_bas.iloc[1]['hr_consumed']
            res["t2_bas"] = max_bas.iloc[1]['hour_ts'].strftime('%d/%m kl %H:00')
        res["avg_bas"] = (res["p1_bas"] + res["p2_bas"]) / 2 if res["p2_bas"] > 0 else res["p1_bas"]

        # Höglast (Nov-Mar, Mån-Fre 07-20)
        import settings as settings_module
        mask_hog = df_hourly['hour_ts'].apply(settings_module.is_high_load_time)
        df_hog = df_hourly[mask_hog]
        if not df_hog.empty:
            idx_hog = df_hog.groupby('day_date')['hr_consumed'].idxmax()
            max_hog = df_hog.loc[idx_hog].sort_values('hr_consumed', ascending=False)
            
            if len(max_hog) > 0:
                res["p1_hog"] = max_hog.iloc[0]['hr_consumed']
                res["t1_hog"] = max_hog.iloc[0]['hour_ts'].strftime('%d/%m kl %H:00')
            if len(max_hog) > 1:
                res["p2_hog"] = max_hog.iloc[1]['hr_consumed']
                res["t2_hog"] = max_hog.iloc[1]['hour_ts'].strftime('%d/%m kl %H:00')
            res["avg_hog"] = (res["p1_hog"] + res["p2_hog"]) / 2 if res["p2_hog"] > 0 else res["p1_hog"]
            
    return res

def plot_monthly_peaks(month_start_dt, month_end_dt):
    """Hämtar och ritar upp månadens effektoppar per dag med orsak och fakturagrundande toppar."""
    df_hourly = pd.read_sql(text("""
        SELECT 
            DATE_TRUNC('hour', timestamp AT TIME ZONE 'Europe/Stockholm') as hour_ts,
            AVG(GREATEST(net_power, 0)) / 1000.0 as hr_consumed,
            AVG(COALESCE(ev_power_kw, 0)) as nissan_kw,
            AVG(COALESCE(ev_carport_power_kw, 0)) as tesla_kw,
            AVG(COALESCE(avg_w_tot, 0)) / 1000.0 as pump_kw,
            AVG(COALESCE(spa_heater_running, 0)) as spa_ratio
        FROM sensor_log
        WHERE timestamp >= :start AND timestamp < :end
          AND net_power IS NOT NULL
        GROUP BY 1
    """), engine, params={"start": month_start_dt, "end": month_end_dt})

    if df_hourly.empty:
        st.info("Ingen förbrukningsdata hittades för den valda månaden.")
        return

    df_hourly['day'] = df_hourly['hour_ts'].dt.day
    df_hourly['hour'] = df_hourly['hour_ts'].dt.hour
    df_hourly['dow'] = df_hourly['hour_ts'].dt.dayofweek
    df_hourly['month'] = df_hourly['hour_ts'].dt.month

    # Analysera orsak till effekttoppen
    def get_contributors(row):
        contribs = []
        if row['tesla_kw'] > 0.5: contribs.append(f"🚗 Tesla ({row['tesla_kw']:.1f} kW)")
        if row['nissan_kw'] > 0.5: contribs.append(f"🚙 Leaf ({row['nissan_kw']:.1f} kW)")
        if row['pump_kw'] > 0.5: contribs.append(f"♨️ Värmepump ({row['pump_kw']:.1f} kW)")
        if row['spa_ratio'] > 0.1: contribs.append(f"🛁 Spabad")
        if not contribs: return "🏠 Övrig Hushållsel"
        return " + ".join(contribs)

    df_hourly['contributors'] = df_hourly.apply(get_contributors, axis=1)

    # Dela upp i Baslast och Höglast enligt Jönköping Energis tider (Nov-Mar, Vardagar 07-19:59)
    mask_hog = df_hourly['hour_ts'].apply(settings_module.is_high_load_time)
    
    df_bas = df_hourly[~mask_hog]
    df_hog = df_hourly[mask_hog]

    # Hitta dagliga toppar och färgkodning
    bas_peaks = pd.DataFrame()
    if not df_bas.empty:
        bas_peaks = df_bas.loc[df_bas.groupby('day')['hr_consumed'].idxmax()].copy()
        bas_peaks['type'] = 'Baslasteffekt'
        bas_peaks['color'] = '#D3D3D3' # Ljusgrå

    hog_peaks = pd.DataFrame()
    if not df_hog.empty:
        hog_peaks = df_hog.loc[df_hog.groupby('day')['hr_consumed'].idxmax()].copy()
        hog_peaks['type'] = 'Höglasteffekt'
        hog_peaks['color'] = '#696969' # Mörkgrå

    # Markera de fakturagrundande topparna (De 2 högsta i månaden)
    top2_bas = pd.DataFrame()
    if not bas_peaks.empty:
        top2_bas = bas_peaks.nlargest(2, 'hr_consumed')
        bas_peaks.loc[top2_bas.index, 'color'] = '#87CEFA' # Ljusblå
        
    top2_hog = pd.DataFrame()
    if not hog_peaks.empty:
        top2_hog = hog_peaks.nlargest(2, 'hr_consumed')
        hog_peaks.loc[top2_hog.index, 'color'] = '#4682B4' # Mörkblå

    df_plot = pd.concat([bas_peaks, hog_peaks])
    df_plot.sort_values('day', inplace=True)

    # Skapa läsbar text för Datum och Tooltip
    sv_days = {0: "Måndag", 1: "Tisdag", 2: "Onsdag", 3: "Torsdag", 4: "Fredag", 5: "Lördag", 6: "Söndag"}
    sv_months = {1: "Januari", 2: "Februari", 3: "Mars", 4: "April", 5: "Maj", 6: "Juni", 7: "Juli", 8: "Augusti", 9: "September", 10: "Oktober", 11: "November", 12: "December"}
    
    df_plot['dow_name'] = df_plot['dow'].map(sv_days)
    df_plot['month_name'] = df_plot['month'].map(sv_months)
    
    df_plot['hover_text'] = df_plot.apply(
        lambda r: f"<b>{r['dow_name']} {r['day']} {r['month_name'].lower()}</b><br>"
                  f"{r['type']}<br>"
                  f"<b>{r['hr_consumed']:.2f} kW</b> Kl. {r['hour']:02d}-{(r['hour']+1)%24:02d}<br>"
                  f"Orsak: {r['contributors']}", 
        axis=1
    )

    fig = go.Figure()
    for t_name, data in df_plot.groupby('type'):
        fig.add_trace(go.Bar(
            x=data['day'],
            y=data['hr_consumed'],
            name="Baslast" if t_name == "Baslasteffekt" else "Höglast",
            marker_color=data['color'],
            customdata=data['hover_text'],
            hovertemplate="%{customdata}<extra></extra>"
        ))

    fig.update_layout(
        template="plotly_dark",
        title=f"Effekttoppar per dag för {sv_months[month_start_dt.month]} {month_start_dt.year}",
        xaxis_title="Dag i månaden",
        yaxis_title="Högsta tim-medeleffekt (kW)",
        barmode='group',
        legend_title="Kategori",
        yaxis=dict(dtick=5, rangemode='tozero'),
        hovermode="closest"
    )
    plot(fig, width="stretch")

    # --- SUMMERINGSKORT (Cards) ---
    st.markdown("### 📊 Sammanställning Månadens Fakturagrundande Toppar")
    c1, c2 = st.columns(2)
    
    with c1:
        with st.container(border=True):
            st.markdown("#### 🟢 Effekttoppar - Baslast")
            if not top2_bas.empty:
                for _, r in top2_bas.iterrows():
                    st.markdown(f"**{r['day']} {sv_months[r['month']].lower()} {r['hour']:02d}:00**<br>{r['hr_consumed']:.2f} kW", unsafe_allow_html=True)
                st.divider()
                st.markdown(f"**Medelvärde: {top2_bas['hr_consumed'].mean():.2f} kW**")
            else:
                st.write("Ingen baslast-data denna månad.")
                
    with c2:
        with st.container(border=True):
            st.markdown("#### 🔴 Effekttoppar - Höglast")
            if not top2_hog.empty:
                for _, r in top2_hog.iterrows():
                    st.markdown(f"**{r['day']} {sv_months[r['month']].lower()} {r['hour']:02d}:00**<br>{r['hr_consumed']:.2f} kW", unsafe_allow_html=True)
                st.divider()
                st.markdown(f"**Medelvärde: {top2_hog['hr_consumed'].mean():.2f} kW**")
            else:
                if month_start_dt.month not in [11, 12, 1, 2, 3]:
                    st.success("Höglast tillämpas ej under denna månad (Sommarhalvår).")
                else:
                    st.write("Ingen höglast-data ännu denna månad.")

def get_fixed_network_fee(dt):
    if dt.date() >= datetime(2026, 4, 1).date(): return 393.43
    return 351.00

def full_buy_cost(spot_ex_vat):
    # Formel: (Spot_ex * 1.25) + (Tibber fast 6.0 öre + Tibber rörlig 3.28 öre + Överföring 4.86 öre + Skatt 36.0 öre) * 1.25
    # 50.14 öre ex moms * 1.25 = 62.675 öre ink moms (0.62675 kr/kWh)
    return (spot_ex_vat * 1.25) + 0.62675

def full_sell_income(spot_ex_vat):
    # Formel: Spot_ex_vat + Jönköping Energi Nätnytta (1.7 öre ex moms * 1.25 = 2.125 öre ink moms)
    return spot_ex_vat + 0.02125

def load_storage_info():
    """Hämtar disk- och databasstorlek."""
    import shutil
    disk = shutil.disk_usage("/")
    result = {
        "disk_pct":      disk.used / disk.total * 100,
        "disk_used_gb":  disk.used  / 1e9,
        "disk_free_gb":  disk.free  / 1e9,
        "disk_total_gb": disk.total / 1e9,
        "db_total_gb":   None,
        "sensor_log_gb": None,
    }
    try:
        with engine.connect() as conn:
            db_size = conn.execute(text("SELECT pg_database_size(current_database())")).fetchone()[0]
            result["db_total_gb"] = db_size / 1e9
            log_size = conn.execute(text("SELECT pg_total_relation_size('sensor_log')")).fetchone()[0]
            result["sensor_log_gb"] = log_size / 1e9
    except Exception:
        pass
    return result


def load_settings():
    defaults = {
        "cheap_hours_count": 8, "temp_cheap": 22.0, "temp_expensive": 20.0,
        "indoor_max": 22.5, "indoor_min": 19.0,
        "friggebod_target": 5.0, "friggebod_frost": 1.0, "garage_target": 12.0, 
        "garage_frost": 4.0, "radiator_solar_w": 300, "spa_max_temp": 40.0, 
        "spa_normal_temp": 34.0, "notify_spa_ready": True, "notify_ev_start": True, 
        "notify_washer_start": True, "notify_spa_open": True, "spa_low_temp": 15.0, 
        "spa_force_heat": False, "spa_target_datetime": None, "spa_target_temp": None, 
        "spa_schedule_enabled": False, "legionella_temp": 60.0, "legionella_days": 14,
        "water_target_normal": 50.0, "power_limit_kw": 10.0, "fuse_size_a": 25.0,
    }
    try:
        with SessionLocal() as db:
            settings_obj = db.query(SystemSettings).filter(SystemSettings.id == 1).first()
            if settings_obj:
                return {
                    "cheap_hours_count": int(settings_obj.cheap_hours_count or 8),
                    "temp_cheap":        float(settings_obj.temp_cheap or 22.0),
                    "temp_expensive":    float(settings_obj.temp_expensive or 20.0),
                    "indoor_max":        float(settings_obj.indoor_max or 22.5),
                    "indoor_min":        float(settings_obj.indoor_min or 19.0),
                    "friggebod_target":  float(settings_obj.friggebod_target or 5.0),
                    "friggebod_frost":   float(settings_obj.friggebod_frost or 1.0),
                    "garage_target":     float(settings_obj.garage_target or 12.0),
                    "garage_frost":      float(settings_obj.garage_frost or 4.0),
                    "radiator_solar_w":  int(settings_obj.radiator_solar_w or 300),
                    "spa_max_temp":      float(settings_obj.spa_max_temp or 40.0),
                    "spa_normal_temp":   float(settings_obj.spa_normal_temp or 34.0),
                    "notify_spa_ready":    bool(settings_obj.notify_spa_ready if settings_obj.notify_spa_ready is not None else True),
                    "notify_ev_start":     bool(settings_obj.notify_ev_start if settings_obj.notify_ev_start is not None else True),
                    "notify_washer_start": bool(settings_obj.notify_washer_start if settings_obj.notify_washer_start is not None else True),
                    "notify_spa_open":     bool(settings_obj.notify_spa_open if settings_obj.notify_spa_open is not None else True),
                    "spa_low_temp":        float(settings_obj.spa_low_temp or 15.0),
                    "spa_force_heat":      bool(settings_obj.spa_force_heat or False),
                    "spa_target_datetime": settings_obj.spa_target_datetime,
                    "spa_target_temp":     float(settings_obj.spa_target_temp) if settings_obj.spa_target_temp is not None else None,
                    "spa_schedule_enabled": bool(settings_obj.spa_schedule_enabled or False),
                    "legionella_temp":     float(settings_obj.legionella_temp or 60.0),
                    "legionella_days":     int(settings_obj.legionella_days or 14),
                    "water_target_normal": float(settings_obj.water_target_normal or 50.0),
                    "power_limit_kw":      float(settings_obj.power_limit_kw or 10.0),
                    "power_limit_kw_bas":  float(settings_obj.power_limit_kw_bas or 0.0),
                    "power_limit_kw_hog":  float(settings_obj.power_limit_kw_hog or 0.0),
                    "fuse_size_a":         float(settings_obj.fuse_size_a or 25.0),
                    "peak_shaving_enabled": bool(settings_obj.peak_shaving_enabled if settings_obj.peak_shaving_enabled is not None else True),
                    "ev_nissan_prio": int(settings_obj.ev_nissan_prio or 2),
                    "ev_tesla_prio":  int(settings_obj.ev_tesla_prio or 1),
                    "away_mode_enabled": bool(settings_obj.away_mode_enabled or False),
                    "away_return_date": settings_obj.away_return_date,
                    "away_lights_on_return": settings_obj.away_lights_on_return or "",
                }
    except Exception as e:
        if "does not exist" in str(e):
            st.warning("⏳ Väntar på att Smartbox ska bygga upp databasen...")
        else:
            st.error(f"Kunde inte hämta inställningar: {e}")
    return defaults

def save_settings(cheap_hours, t_cheap, t_exp, i_max, i_min, leg_temp, leg_days, wt_norm):
    try:
        with SessionLocal() as db:
            settings_obj = db.query(SystemSettings).filter(SystemSettings.id == 1).first()
            if settings_obj:
                settings_obj.cheap_hours_count = cheap_hours
                settings_obj.temp_cheap = t_cheap
                settings_obj.temp_expensive = t_exp
                settings_obj.indoor_max = i_max
                settings_obj.indoor_min = i_min
                settings_obj.legionella_temp = leg_temp
                settings_obj.legionella_days = leg_days
                settings_obj.water_target_normal = wt_norm
                db.commit()
        st.success("✅ Inställningarna har sparats!")
        log_comfort_event("settings:temp", f"cheap={t_cheap} exp={t_exp} min={i_min} max={i_max}")
    except Exception as e:
        st.error(f"Kunde inte spara: {e}")




def get_overrides():
    defaults = {"heat": "auto", "hotwater": "auto", "garage_radiator": "auto", "pump_operating_mode": "auto"}
    try:
        with SessionLocal() as db:
            rows = db.query(Override).all()
            res = defaults.copy()
            for r in rows:
                res[r.device] = r.mode
            return res
    except Exception:
        return defaults

_COMFORT_DEVICES = {"heat", "hotwater", "pump_operating_mode", "pump_smart_mode",
                    "summer_mode_strategy", "spa_force_eco", "spa_force_heat", "garage_radiator"}

def log_comfort_event(event_type, detail=""):
    """#3-förberedelse: fångar en KOMFORT-signal + kontext (senaste sensor_log) så vi senare kan
    LÄRA oss personliga komfortgränser. Sväljer fel tyst – får aldrig störa UI:t."""
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS comfort_events (
                    id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    event_type VARCHAR(60) NOT NULL, detail TEXT,
                    indoor_temp REAL, outdoor_temp REAL, price REAL, active_mode VARCHAR(20)
                )
            """))
            conn.execute(text("""
                INSERT INTO comfort_events (event_type, detail, indoor_temp, outdoor_temp, price, active_mode)
                SELECT :et, :d, indoor_temp, outdoor_temp, price, active_mode
                FROM sensor_log ORDER BY timestamp DESC LIMIT 1
            """), {"et": event_type, "d": str(detail)[:200]})
    except Exception:
        pass

def set_override_db(device, mode):
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO overrides (device, mode, updated_at)
                VALUES (:device, :mode, NOW())
                ON CONFLICT (device) DO UPDATE SET mode = EXCLUDED.mode, updated_at = NOW()
            """), {"device": device, "mode": mode})
        if device in _COMFORT_DEVICES:
            log_comfort_event(f"override:{device}", f"→ {mode}")
    except Exception as e:
        st.error(f"Kunde inte spara överstyrning: {e}")

def load_latest():
    try:
        df = pd.read_sql(text("SELECT *, timestamp AT TIME ZONE 'Europe/Stockholm' AS sthlm_time FROM sensor_log ORDER BY timestamp DESC LIMIT 1"), engine)
        return df.iloc[0] if not df.empty else None
    except Exception:
        return None

def format_kr_ore(val):
    """Formaterar pris till kr eller öre beroende på om det är under 1 kr."""
    if val is None: return "–"
    if abs(val) < 1.0 and val != 0: return f"{val*100:.0f} öre"
    return f"{val:.2f} kr"

# --- HÄLPER FÖR SPABADETS ML OCH SCHEMA-GRAFIK ---
def get_spa_heating_rate(outdoor_temp, current_spa_temp=38.0):
    """Hämtar maskininlärningsparametrarna för spabadet."""
    try:
        intercept, slope_out, slope_spa = learning.get_heating_rate_model()
        return learning.predict_heating_rate(outdoor_temp, current_spa_temp, intercept, slope_out, slope_spa)
    except Exception:
        return 2.0


# --- EV LADDNINGSPLANERING FÖR GRAF ---
def get_car_plan_details(car_id, schedule, current_soc, battery_kwh):
    """Hjälpfunktion som beräknar nästa mål och energibehov för en bil."""
    now_dt = datetime.now(SWE_TZ)
    target_dt, panic_mode = None, False
    target_soc = 100
    today_weekday = now_dt.weekday()
    
    for i in range(7):
        day_offset = i
        check_day = (today_weekday + day_offset) % 7
        day_schedule = schedule.get(car_id, {}).get(check_day, {})
        if not day_schedule:
            day_schedule = schedule.get(car_id, {}).get(str(check_day), {})

        if day_schedule.get('enabled'):
            t_str = day_schedule.get('target_time', '07:00')
            try:
                t_hour, t_min = map(int, str(t_str).split(':'))
            except (ValueError, AttributeError):
                t_hour, t_min = 7, 0
            test_dt = (now_dt + timedelta(days=day_offset)).replace(hour=t_hour, minute=t_min, second=0, microsecond=0)
            if test_dt > now_dt:
                target_dt = test_dt
                target_soc = day_schedule.get('target_soc', 100)
                panic_mode = day_schedule.get('panic_mode', False)
                break
    
    if not target_dt or current_soc is None or current_soc >= target_soc:
        return None, target_soc, 0, False
        
    kwh_needed = max(0, (target_soc - current_soc) / 100.0 * battery_kwh)
    return target_dt, target_soc, kwh_needed, panic_mode

def detect_ev_allocations():
    """
    Utför en 'handshake' mellan laddarna och bilarnas egna API:er via HA.
    Returnerar en dictionary som mappar varje bil ('nissan', 'tesla', 'guest1', 'guest2')
    till den laddare (Easee-entitet) de är anslutna till, eller None om de inte är hemma.
    """
    # Definiera laddare och deras status
    chargers = {
        'easee_lite': 'sensor.easee_lite_status',
        'carport': 'sensor.carport_status'
    }
    
    # Kontrollera om bilarna själva anser sig vara inpluggade (Kräver entiteter som visar kabelstatus)
    # OBS: Ersätt dessa med de faktiska entiteterna för kabelanslutning för dina bilar!
    # Fallback till 'charging' om specifik kabel-sensor saknas, men kabel-sensor är bäst.
    # FIX: En bil kan bara sitta i en HEMMA-laddare om den faktiskt är hemma (GPS). Bilarnas egna
    # charging/plugged-sensorer är platsoberoende (Teslan rapporterar "charging/stopped/complete"
    # även vid en supercharger borta, och stale-värden) → vi grindar dem på GPS-hemma. Annars
    # snor en bil som laddar borta en hemma-laddare och visar felaktigt "Laddar".
    _ns, _nd, _ = get_car_location_info('nissan'); nissan_gps_home = (_ns.lower() == 'home') or (_nd <= 0.5)
    _ts, _td, _ = get_car_location_info('tesla');  tesla_gps_home  = (_ts.lower() == 'home') or (_td <= 0.5)

    # FIX: Är bilen inkopplad i sin HEMMA-Easee är den bevisligen hemma – laddaren står ju här.
    # Leafens/Teslans egna GPS kan slöa/vara stale, så vi låter en UPPTAGEN hemma-laddare (status
    # != disconnected) tillsammans med bilens egen kabel-sensor bevisa "hemma", oberoende av GPS.
    # (En bil som laddar BORTA – GPS borta OCH hemma-laddaren tom – grindas fortfarande bort.)
    _easee_lite_occ = str(ha_state('sensor.easee_lite_status', 'disconnected')).lower() not in ['disconnected', 'offline', 'none', '']
    _carport_occ    = str(ha_state('sensor.carport_status', 'disconnected')).lower() not in ['disconnected', 'offline', 'none', '']
    # 2026-10-15: bilintegrationerna har inga kabel-sensorer längre (binary_sensor.leaf_plugged_in finns inte). Laddarens egen status är facit för kabeln: upptagen laddare + bilen hemma (GPS) = ansluten.
    _nissan_cable = str(ha_state('binary_sensor.leaf_plugged_in', 'off')) == 'on' or (_easee_lite_occ and nissan_gps_home)
    _tesla_cable  = (str(ha_state('binary_sensor.tesla_model_y_charger', 'off')) == 'on'
                     or str(ha_state('sensor.tesla_model_y_charging_state', '')).lower() in ['charging', 'stopped', 'complete']
                     or (_carport_occ and tesla_gps_home)
                     or str(ha_state('binary_sensor.tesla_model_y_charging', 'off')) == 'on')

    nissan_home = nissan_gps_home or (_easee_lite_occ and _nissan_cable)
    tesla_home  = tesla_gps_home  or (_carport_occ and _tesla_cable)
    nissan_plugged = _nissan_cable and nissan_home
    tesla_plugged  = _tesla_cable  and tesla_home

    allocations = {
        'nissan': {'charger': None, 'is_connected': False, 'is_guest': False},
        'tesla': {'charger': None, 'is_connected': False, 'is_guest': False},
        'guest': {'charger': None, 'is_connected': False, 'is_guest': True}
    }

    charger_power = {'easee_lite': 'sensor.easee_lite_effekt', 'carport': 'sensor.carport_effekt'}
    for charger_id, entity in chargers.items():
        status = str(ha_state(entity, 'disconnected')).lower()
        if status in ['disconnected', 'offline', 'none', '']:
            continue
        pw = safe_float(charger_power.get(charger_id)) or 0.0
        if pw > 100: pw /= 1000.0
        is_charging = status == 'charging' or pw >= 0.2

        if tesla_plugged and allocations['tesla']['charger'] is None:
            allocations['tesla'].update(charger=charger_id, is_connected=True); tesla_plugged = False
        elif nissan_plugged and allocations['nissan']['charger'] is None:
            allocations['nissan'].update(charger=charger_id, is_connected=True); nissan_plugged = False
        elif is_charging:
            # Laddaren LADDAR de facto men ingen bils kabel-sensor tog på sig den (t.ex. opålitlig
            # leaf_plugged_in). Tilldela den hemmavarande bilen vars sensor fallerat; annars gäst.
            if nissan_home and allocations['nissan']['charger'] is None:
                allocations['nissan'].update(charger=charger_id, is_connected=True)
            elif tesla_home and allocations['tesla']['charger'] is None:
                allocations['tesla'].update(charger=charger_id, is_connected=True)
            else:
                allocations['guest'].update(charger=charger_id, is_connected=True)
        # Ansluten men laddar ej och ingen hemma-bil → lämna oallokerad (kvarglömd kabel/gäst-standby).

    return allocations

def forecast_charge_complete(car_id):
    """Prognos för när bilen är FULLADDAD – oavsett var den laddar (hemma ELLER borta).
    Tesla: använder bilens egen completion-sensor (gäller även supercharger), annars beräknat.
    Nissan: beräknat ur hemma-laddarens effekt + SOC. Returnerar markdown-sträng eller None."""
    now = datetime.now(SWE_TZ)

    def _fmt(dt):
        if dt is None or dt <= now:
            return None
        mins = int((dt - now).total_seconds() / 60)
        return f"🔋 Fulladdad ca **{dt.strftime('%H:%M')}** (om {mins // 60} h {mins % 60} min)"

    def _compute(soc, target, cap_kwh, power_kw):
        if soc is None or power_kw is None or power_kw < 0.2 or soc >= target:
            return None
        hours = ((target - soc) / 100.0 * cap_kwh) / power_kw
        return _fmt(now + timedelta(hours=hours))

    if car_id == 'tesla':
        car_pw = safe_float('sensor.tesla_model_y_charger_power') or 0.0
        if ha_state('binary_sensor.tesla_model_y_charging', 'off') != 'on' and car_pw < 0.2:
            return None
        raw = ha_state('sensor.tesla_model_y_time_charge_complete', None)
        if raw and str(raw).lower() not in ['unknown', 'unavailable', 'none', '']:
            try:
                dt = datetime.fromisoformat(str(raw).replace('Z', '+00:00')).astimezone(SWE_TZ)
                r = _fmt(dt)
                if r:
                    return r
            except Exception:
                pass
        soc = safe_float('sensor.tesla_model_y_battery')
        target = safe_float('number.tesla_model_y_charge_limit') or 100.0
        return _compute(soc, target, 75.0, car_pw)

    if car_id == 'nissan':
        pw = safe_float('sensor.easee_lite_effekt') or 0.0
        pw = pw / 1000.0 if pw > 100 else pw
        if ha_state('binary_sensor.leaf_charging', 'off') != 'on' and pw < 0.2:
            return None
        soc = safe_float('sensor.leaf_battery_level')
        return _compute(soc, 100.0, 40.0, pw)
    return None


def create_joint_ev_plan(ev_schedule, nissan_soc, tesla_soc):
    """Skapar en gemensam, sammanhängande och långsam laddningsplan ("Spread & Smooth")."""
    row = load_latest()
    # Normalisera schemats nycklar från JSON-textsträngar till heltal så kärnmotorn förstår dem
    norm_schedule = {}
    for car, days in ev_schedule.items():
        norm_schedule[car] = {int(k): v for k, v in days.items() if str(k).isdigit()}
    ev_schedule = norm_schedule

    nissan_target_dt, nissan_target_soc, nissan_kwh, _ = get_car_plan_details('nissan', ev_schedule, nissan_soc, 40.0)
    tesla_target_dt, tesla_target_soc, tesla_kwh, _ = get_car_plan_details('tesla', ev_schedule, tesla_soc, 75.0)
    climate_schedule = settings_module.get_climate_schedule()
    now_dt = datetime.now(SWE_TZ)
    cfg = load_settings()
    
    # Gör en handshake för att se vem som står var
    allocations = detect_ev_allocations()
    
    nissan_phases = 1
    tesla_phases = 3 if ha_state('select.carport_allowed_charging_phases') == 'ThreePhase' else 1
    # FIX: Planen ska ALLTID visa vad AI:n TÄNKER ladda (prognos baserad på SOC + klar-tid +
    # elpris + husets förbrukning + sol), oavsett om bilen är hemma just nu. Annars ser grafen
    # ut att stå still/tom så fort bilen är borta. Den FAKTISKA laddningen styrs separat i
    # backend (main.py/gpm.py) utifrån verklig anslutning – den här planen är ren visning/prognos.
    df_plan = pred.simulate_ev_soc_plan(
        now_dt, ev_schedule, nissan_soc, tesla_soc, cfg, nissan_phases, tesla_phases,
        nissan_plugged_in=True, tesla_plugged_in=True
    )

    def get_fallback_info():
        p_info = {}
        for cid, c_soc, t_soc in [('nissan', nissan_soc, nissan_target_soc), ('tesla', tesla_soc, tesla_target_soc)]:
            is_conn = allocations[cid]['is_connected']
            
            c_text = ""
            if cid == 'nissan':
                c_sched = climate_schedule.get(cid)
                if c_sched and c_sched.get('enabled'):
                    th, tm = map(int, c_sched['target_time'].split(':'))
                    cdt = now_dt.replace(hour=th, minute=tm, second=0, microsecond=0)
                    if cdt <= now_dt: cdt += timedelta(days=1)
                    out_t_fallback = df_plan.loc[(df_plan['t_slot'] - cdt.replace(tzinfo=None)).abs().idxmin(), 'temp'] if ('temp' in df_plan.columns and not df_plan.empty) else 10.0
                    pmins = learning.estimate_preheat_minutes(out_t_fallback)
                    pstart = cdt - timedelta(minutes=pmins)
                    if pstart > now_dt:
                        c_text = f" 🔥 Klimatanläggning startar ca **{pstart.strftime('%H:%M')}**."
                        
            if not is_conn: p_info[cid] = {'text': '🔌 Bilen ej ansluten.' + c_text}
            elif c_soc is None: p_info[cid] = {'text': '⏳ Väntar på batteridata...' + c_text}
            elif c_soc >= (t_soc - 0.5): p_info[cid] = {'text': '✅ Fulladdad enligt schema.' + c_text}
            else: p_info[cid] = {'text': '⏸️ Inget aktivt schema (eller prisdata saknas).' + c_text}
        return p_info

    if df_plan.empty:
        return pd.DataFrame(), get_fallback_info()

    plan_info = {}
    for car_id, soc, target_soc_val in [('nissan', nissan_soc, nissan_target_soc), ('tesla', tesla_soc, tesla_target_soc)]:
        is_connected = allocations[car_id]['is_connected']
        assigned_charger = allocations[car_id]['charger']
            
        state, dist, city = get_car_location_info(car_id)
        # Inkopplad i hemma-laddaren ⟹ hemma (GPS kan slöa; laddaren står ju fysiskt här).
        is_home = state.lower() == 'home' or dist <= 0.5 or is_connected

        # --- Lägg till klimatinformation (Gemensam för alla lägen) ---
        climate_text = ""
        if car_id == 'nissan':
            car_climate_sched = climate_schedule.get(car_id)
            if car_climate_sched and car_climate_sched.get('enabled'):
                t_hour, t_min = map(int, car_climate_sched['target_time'].split(':'))
                climate_target_dt = now_dt.replace(hour=t_hour, minute=t_min, second=0, microsecond=0)
                if climate_target_dt <= now_dt:
                    climate_target_dt += timedelta(days=1)
                target_dt_naive = climate_target_dt.replace(tzinfo=None)
                
                if 'temp' in df_plan.columns and not df_plan.empty:
                    time_diffs = (df_plan['t_slot'] - target_dt_naive).abs()
                    closest_row_idx = time_diffs.idxmin()
                    outdoor_temp_at_departure = df_plan.loc[closest_row_idx, 'temp']
                else:
                    outdoor_temp_at_departure = 10.0
                preheat_mins = learning.estimate_preheat_minutes(outdoor_temp_at_departure)
                preheat_start_dt = climate_target_dt - timedelta(minutes=preheat_mins)
                if preheat_start_dt > now_dt:
                    if is_connected or is_home:
                        climate_text = f" 🔥 Klimatanläggning startar ca **{preheat_start_dt.strftime('%H:%M')}**."
                    else:
                        climate_text = f" ❄️ Klimatschema kl **{preheat_start_dt.strftime('%H:%M')}** (Pausat då bilen är bortrest)."

        if not is_connected:
            if is_home:
                plan_info[car_id] = {'text': '🔌 Bilen står parkerad hemma men laddkabeln är ej ansluten.' + climate_text}
            else:
                loc_str = f"(Befinner sig i: {city})" if city else (f"(Befinner sig i: {state.title()})" if state.lower() not in ['not_home', 'unknown', 'unavailable', 'away'] else f"({dist:.1f} km bort)")
                plan_info[car_id] = {'text': f'📍 Bilen är bortrest {loc_str}. AI-prognosen förväntar sig hemkomst senare.' + climate_text}
            continue
        if soc is None:
            plan_info[car_id] = {'text': '⏳ Väntar på batteridata...' + climate_text}
            continue
        # Använd en liten buffert för att undvika att den visar "Fulladdad" vid 99.9%
        if soc >= (target_soc_val - 0.5):
            plan_info[car_id] = {'text': '✅ Fulladdad enligt schema.' + climate_text}
            continue

        current_slot_minute = (now_dt.minute // 15) * 15
        now_slot_ts = now_dt.replace(minute=current_slot_minute, second=0, microsecond=0, tzinfo=None)
        car_plan_df = df_plan[df_plan[f"{car_id}_kw"] > 0].sort_values('t_slot')
        
        current_slot = car_plan_df[car_plan_df['t_slot'] == now_slot_ts]
        future_slots = car_plan_df[car_plan_df['t_slot'] > now_slot_ts]
        
        # Kontrollera om bilen faktiskt laddar just nu (pga realtids-solöverskott, scheman etc)
        actual_status_entity = f"sensor.{assigned_charger}_status" if assigned_charger else None
        actual_power_entity = f"sensor.{assigned_charger}_effekt" if assigned_charger else None
        actual_limit_entity = f"sensor.{assigned_charger}_maximum_allowed_charge_current" if assigned_charger else None
        
        actual_status = str(ha_state(actual_status_entity, '')).lower() if actual_status_entity else ''
        actual_power = safe_float(actual_power_entity) if actual_power_entity else 0.0
        if actual_power > 100: actual_power /= 1000.0
        actual_limit = safe_float(actual_limit_entity) if actual_limit_entity else 0.0
        
        # Lita på det faktiska effektuttaget. Om effekten är över 0.2 kW så laddar bilen de facto,
        # oavsett om API:et påstår att den är "pausad" eller inställd på 0A.
        is_actually_charging = actual_power >= 0.2
        is_commanded_to_charge = actual_limit >= 6 or is_actually_charging
        
        ai_log = row.get("ai_action_log", "") if row is not None else ""
        is_solar_charging = "Prio 3.5 (SOLAR EV)" in ai_log
        is_battery_protection = "BATTERISKYDD" in ai_log and car_id.capitalize() in ai_log
        
        override_amps = get_overrides().get(f"{car_id}_force_amps", "0")
        is_forced = str(override_amps) != "auto" and str(override_amps) != "0"
        netto_live = get_live_net_power()
        
        if is_forced:
            charge_text = f"⚡ **Manuell tvångsladdning aktiv** med ca **{actual_power:.1f} kW** (Inställd: {actual_limit}A)."
            plan_info[car_id] = {'text': charge_text + climate_text}
            continue
            
        if is_commanded_to_charge and (is_solar_charging or netto_live < -100):
            charge_text = f"☀️ **Laddar på solöverskott!** AI:n styr strömmen dynamiskt (Tillåten gräns: **{actual_limit}A**, Nuvarande effekt: **{actual_power:.1f} kW**)."
            if not future_slots.empty:
                start_time = future_slots.iloc[0]['t_slot'].strftime('%H:%M')
                charge_text += f" *(Ordinarie prisschema planerar att starta senast kl {start_time}).*"
            plan_info[car_id] = {'text': charge_text + climate_text}
            continue
            
        if is_commanded_to_charge and is_battery_protection:
            charge_text = f"🛡️ **Batteriskydd Aktivt:** AI:n tvingar bilen att ladda klart sin 30-minuterscykel för att skona reläerna (Nuvarande effekt: **{actual_power:.1f} kW**)."
            plan_info[car_id] = {'text': charge_text + climate_text}
            continue

        if not current_slot.empty:
            all_charge_slots = car_plan_df[car_plan_df['t_slot'] >= now_slot_ts]
            avg_kw = all_charge_slots[f"{car_id}_kw"].mean()
            total_kwh = (all_charge_slots[f"{car_id}_kw"] / 4.0).sum()
            start_soc = all_charge_slots.iloc[0][f'{car_id}_start_soc']
            end_soc = min(100.0, all_charge_slots.iloc[-1][f'{car_id}_end_soc'])
            end_time = (all_charge_slots.iloc[-1]['t_slot'] + timedelta(minutes=15)).strftime('%H:%M')
            
            if is_commanded_to_charge:
                status_prefix = f"⚡ **Laddar enligt schema** (Tillåten: {actual_limit}A, Nu: {actual_power:.1f} kW)"
            else:
                if cfg.get("peak_shaving_enabled", True):
                    status_prefix = "⏳ **Planerad att ladda nu** *(men pausad av effektvakten/säkringen)*"
                else:   # effektvakten är avstängd: den kan inte vara orsaken (säkringsskyddet och ev. fasbyte kan fortfarande hålla igen)
                    status_prefix = "⏳ **Planerad att ladda nu** *(pausad av säkringsskydd eller pågående fasbyte – effektvakten är avstängd)*"
                
            plan_info[car_id] = {'text': f"{status_prefix} och förväntas vara klar kl **{end_time}**. (Fyller totalt {total_kwh:.1f} kWh, **{start_soc:.1f}% → {end_soc:.1f}%** med snitt {avg_kw:.1f} kW)." + climate_text}
            continue
            
        if not future_slots.empty:
            start_time = future_slots.iloc[0]['t_slot'].strftime('%H:%M')
            end_time = (future_slots.iloc[-1]['t_slot'] + timedelta(minutes=15)).strftime('%H:%M')
            avg_kw = future_slots[f"{car_id}_kw"].mean()
            total_kwh = (future_slots[f"{car_id}_kw"] / 4.0).sum()
            
            # Korrekt uträkning beroende på om det är 1-fas (Nissan) eller potentiellt 3-fas (Tesla)
            c_phases = 1 if car_id == 'nissan' else (3 if ha_state('select.carport_allowed_charging_phases', 'SinglePhase') == 'ThreePhase' else 1)
            amps_estimate = max(6, round((avg_kw * 1000) / (230 * c_phases)))
            start_soc = future_slots.iloc[0][f'{car_id}_start_soc']
            end_soc = min(100.0, future_slots.iloc[-1][f'{car_id}_end_soc'])
            
            solar_slots = len(future_slots[future_slots['solar_w'] > 1500])
            if solar_slots > len(future_slots) / 2:
                reason = "☀️ övervägande solel"
            else:
                avg_price = future_slots['price'].mean()
                reason = f"💰 lågt snittpris ({avg_price:.2f} kr)"
            
            charge_text = f"⏳ Startar **{start_time}** och laddar fram till kl **{end_time}** med ca **{avg_kw:.1f} kW** (~{amps_estimate}A) pga {reason}. (Fyller totalt {total_kwh:.2f} kWh, **{start_soc:.1f}% → {end_soc:.1f}%**)."
            
            plan_info[car_id] = {'text': charge_text + climate_text}
        elif (car_id == 'nissan' and nissan_kwh > 0) or (car_id == 'tesla' and tesla_kwh > 0):
             plan_info[car_id] = {'text': '⏳ Väntar på optimalt tillfälle...' + climate_text}
        else:
             plan_info[car_id] = {'text': '⏸️ Inget aktivt schema.' + climate_text}

    return df_plan, plan_info

# --- HÄMTA LIVE-DATA FRÅN HOME ASSISTANT ---
@st.cache_data(ttl=2)
def fetch_ha_data():
    ha_ip = os.environ.get("HA_IP")
    ha_token = os.environ.get("HA_TOKEN", "").strip("\"'")
    if not ha_ip or not ha_token: return {}
    url = f"https://{ha_ip}:8123/api/states"
    headers = {"Authorization": f"Bearer {ha_token}", "Content-Type": "application/json"}
    try:
        r = requests.get(url, headers=headers, timeout=5, verify=False)
        if r.status_code == 200:
            return {s["entity_id"]: s for s in r.json()}
    except Exception:
        pass
    return {}

ha_data = fetch_ha_data()

def ha_state(entity_id, default="–"):
    val = ha_data.get(entity_id, {}).get("state", default)
    return val if val not in ("unavailable", "unknown") else default

def ha_attribute(entity_id, attr_name, default="–"):
    val = ha_data.get(entity_id, {}).get("attributes", {}).get(attr_name, default)
    return val if val is not None else default

@st.cache_data(ttl=60)
def get_historical_dataframe(limit_hours, log_cols, wants_price_forecast):
    dfs_to_join = []
    try:
        with engine.connect() as conn:
            if log_cols:
                q_cols = "timestamp, " + ", ".join(log_cols)
                df_log = pd.read_sql(text(f"SELECT {q_cols} FROM sensor_log WHERE timestamp >= NOW() - INTERVAL '1 hour' * :hours"), conn, params={"hours": limit_hours})
            if wants_price_forecast:
                df_price = pd.read_sql(text("SELECT time_start AS timestamp, sek_per_kwh AS price_forecast FROM elpriser WHERE time_start >= NOW() - INTERVAL '1 hour' * :hours"), conn, params={"hours": limit_hours})
        if log_cols and not df_log.empty:
            df_log['timestamp'] = pd.to_datetime(df_log['timestamp'], utc=True).dt.tz_convert('Europe/Stockholm')
            df_log.set_index('timestamp', inplace=True)
            dfs_to_join.append(df_log)
        if wants_price_forecast and not df_price.empty:
            df_price['timestamp'] = pd.to_datetime(df_price['timestamp'], utc=True).dt.tz_convert('Europe/Stockholm')
            df_price.set_index('timestamp', inplace=True)
            dfs_to_join.append(df_price)
        if dfs_to_join:
            df_final = pd.concat(dfs_to_join, axis=1).sort_index()
            if wants_price_forecast and 'price_forecast' in df_final.columns:
                df_final['price_forecast'] = df_final['price_forecast'].ffill()
            return df_final.round(3)
    except Exception as e:
        print(f"Error fetching history: {e}")
    return pd.DataFrame()

def _num_or0(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def safe_float(entity_id):
    val = ha_state(entity_id)
    try: return float(val)
    except: return 0.0

def car_soc(entity_id, col):
    """Batterinivå: live från HA, annars senast kända värde som smartbox sparat (bilen sover/HA har startat om).
    Returnerar (värde eller None, är_gammalt)."""
    v = ha_state(entity_id)
    try:
        return float(v), False
    except (TypeError, ValueError):
        pass
    try:
        if row is not None and row.get(col) is not None and not pd.isna(row.get(col)):
            return float(row.get(col)), True
    except Exception:
        pass
    return None, False

def get_live_net_power():
    return sum([
        safe_float(f"sensor.tibber_pulse_malmgatan_34_spanning_fas{i}") *
        safe_float(f"sensor.tibber_pulse_malmgatan_34_strom_fas{i}")

        for i in (1, 2, 3)
    ])

def calc_dist(lat1, lon1, lat2, lon2):
    if None in (lat1, lon1, lat2, lon2): return 999.0
    try:
        R = 6371.0 # Jordradie i km
        dLat, dLon = math.radians(float(lat2) - float(lat1)), math.radians(float(lon2) - float(lon1))
        a = math.sin(dLat/2)**2 + math.cos(math.radians(float(lat1)))*math.cos(math.radians(float(lat2)))*math.sin(dLon/2)**2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    except (ValueError, TypeError):
        return 999.0

def render_refresh_button(tab_name):
    if st.button("🔄 Uppdatera värden från Home Assistant", key=f"refresh_{tab_name}"):
        fetch_ha_data.clear()
        st.rerun()


@st.cache_data(ttl=3600)
def get_city_from_coords(lat, lon):
    if lat is None or lon is None: return None
    try:
        url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json&zoom=10"
        headers = {'User-Agent': 'EnergyWizard/1.0 (HomeAutomation)'}
        r = requests.get(url, headers=headers, timeout=2)
        if r.status_code == 200:
            data = r.json()
            addr = data.get("address", {})
            return addr.get("city") or addr.get("town") or addr.get("village") or addr.get("municipality") or addr.get("county")
    except Exception:
        pass
    return None

def get_car_location_info(car_id):
    if car_id == 'nissan':
        state = str(ha_state('device_tracker.leaf_location', 'unknown'))
        lat = ha_attribute('device_tracker.leaf_location', 'latitude', None)
        lon = ha_attribute('device_tracker.leaf_location', 'longitude', None)
    else:
        state = str(ha_state('device_tracker.tesla_model_y_location_tracker', 'unknown'))
        lat = ha_attribute('device_tracker.tesla_model_y_location_tracker', 'latitude', None)
        lon = ha_attribute('device_tracker.tesla_model_y_location_tracker', 'longitude', None)
    dist = calc_dist(weather.LATITUDE, weather.LONGITUDE, lat, lon) if lat and lon else 999.0
    return state, dist, get_city_from_coords(lat, lon) if dist > 0.5 else None

def init_mower_db():
    """Skapar databastabellen för gräsklipparens aktivitetslogg om den inte finns."""
    MowerActivity.__table__.create(bind=engine, checkfirst=True)

# Låt settings_module säkerställa att tabellerna är initialiserade konsekvent
settings_module.init_settings_db()
init_mower_db()

# ── Sidinställningar ───────────────────────────────────────────────────────────
st.set_page_config(page_title="EnergyWizard", page_icon="⚡", layout="wide")

# ── Lösenordsskydd ─────────────────────────────────────────────────────────────
# Lösenordet ligger i miljövariabeln DASHBOARD_PASSWORD (från .env). Är den tom/saknas är skyddet AV.
# Inloggningen sparas 30 dagar i en cookie (ew_auth) så man slipper logga in vid varje omladdning.
# Cookien är en HMAC av lösenordet -> ändras lösenordet i .env slutar alla gamla cookies att gälla.
# Cookies delas mellan portar på samma värd, så en app med samma lösenord/salt känner igen inloggningen.
def _auth_token(pw):
    return hmac.new(pw.encode(), b"energywizard-dashboard-v1", hashlib.sha256).hexdigest()

def _require_password():
    pw = os.environ.get("DASHBOARD_PASSWORD", "")
    if not pw:
        return
    token = _auth_token(pw)
    import streamlit.components.v1 as _components
    if st.session_state.get("_auth_ok"):
        if st.session_state.pop("_set_cookie", False):
            _components.html(f"<script>document.cookie='ew_auth={token}; max-age=2592000; path=/; SameSite=Strict';</script>", height=0)
        if st.sidebar.button("🔒 Logga ut", key="_logout_btn"):
            st.session_state["_auth_ok"] = False
            st.session_state["_logged_out"] = True   # ignorera cookien tills den hunnit raderas
            st.rerun()
        return
    if st.session_state.get("_logged_out"):
        # Radera inloggningscookien i webbläsaren (förfaller direkt).
        _components.html("<script>document.cookie='ew_auth=; max-age=0; path=/; SameSite=Strict';</script>", height=0)
    else:
        cookie = st.context.cookies.get("ew_auth", "")
        if isinstance(cookie, str) and cookie and hmac.compare_digest(cookie, token):
            st.session_state["_auth_ok"] = True
            return
    st.title("🔒 EnergyWizard")
    entered = st.text_input("Lösenord", type="password")
    if entered:
        if hmac.compare_digest(entered.encode(), pw.encode()):
            st.session_state["_auth_ok"] = True
            st.session_state["_set_cookie"] = True
            st.session_state.pop("_logged_out", None)
            st.rerun()
        else:
            time.sleep(2)  # bromsar gissningsattacker
            st.error("Fel lösenord.")
    st.stop()

_require_password()
st.title("⚡ EnergyWizard")

# ── Strategibanner ─────────────────────────────────────────────────────────────
now          = datetime.now(SWE_TZ)
today_start  = now.replace(hour=0, minute=0, second=0, microsecond=0)
tomorrow_start = today_start + timedelta(days=1)
settings     = load_settings()
current_live_price = None

# current_live_price behövs nedströms (rad ~1148/2263/3604) → beräkna på modulnivå.
try:
    with engine.connect() as _conn:
        _row = _conn.execute(text("SELECT sek_per_kwh FROM elpriser WHERE time_start <= :now AND time_end > :now"), {"now": now}).fetchone()
        current_live_price = float(_row[0]) if _row else None
except Exception:
    pass

@st.fragment(run_every="30s")
def render_strategy_banner():
    """Fix 6: partiell live-omritning. Bannern uppdaterar sig själv var 30:e sekund
    (pris, nästa kvart, sol nu/+1h) utan att hela sidan görs om."""
    _now = datetime.now(SWE_TZ)
    _t0  = _now.replace(hour=0, minute=0, second=0, microsecond=0)
    _t1  = _t0 + timedelta(days=1)
    _settings = load_settings()
    try:
        _df_p = pd.read_sql(text("""
            SELECT sek_per_kwh FROM elpriser WHERE time_start >= :start AND time_start < :end
        """), engine, params={"start": _t0, "end": _t1})
        _all_prices = _df_p['sek_per_kwh'].tolist() if not _df_p.empty else []

        with engine.connect() as _conn:
            _next_qt = _now + timedelta(minutes=15)
            _nxt_row = _conn.execute(text("SELECT sek_per_kwh FROM elpriser WHERE time_start <= :next AND time_end > :next"), {"next": _next_qt}).fetchone()
            _next_price = float(_nxt_row[0]) if _nxt_row else None

            _cur_hour  = _now.replace(minute=0, second=0, microsecond=0)
            _next_hour = _cur_hour + timedelta(hours=1)
            _nw = _conn.execute(text("SELECT cloud_cover FROM weather_forecast WHERE timestamp = :nex"), {"nex": _next_hour}).fetchone()
            _cloud_next = float(_nw[0]) if _nw else 50.0

            _pv_row = _conn.execute(text("SELECT pv_power_w FROM sensor_log ORDER BY timestamp DESC LIMIT 1")).fetchone()
            _pv_now = float(_pv_row[0]) if _pv_row and _pv_row[0] is not None else None

        _solar_prof = learning.get_solar_profile()
        _solar_next = pred.get_smart_solar_w(_cloud_next, _now + timedelta(hours=1), _solar_prof)

        if _settings and _all_prices:
            _strat = nordpool.calculate_day_strategy(_all_prices, _settings["cheap_hours_count"])
            _banner_cols = st.columns([3, 2, 2, 2])
            _banner_cols[0].info(f"**Dagens strategi:** {_strat['description']}")
            if _next_price is not None:
                _dyn_lim = _strat.get("dynamic_limit")
                _h       = _strat.get("hysteresis", 0)
                if _strat["mode"] == "comfort":
                    _next_label = "😌 Nästa kvart: Komfort"
                elif _dyn_lim is not None and _next_price <= _dyn_lim - _h:
                    _next_label = f"🟢 Nästa kvart: Billigt ({_next_price:.3f} kr)"
                elif _dyn_lim is not None and _next_price >= _dyn_lim + _h:
                    _next_label = f"🔴 Nästa kvart: Dyrt ({_next_price:.3f} kr)"
                else:
                    _next_label = f"⏸️ Nästa kvart: Gråzon ({_next_price:.3f} kr)"
                _banner_cols[1].info(f"**{_next_label}**")
            _sol_nu_text = f"{_pv_now:.0f} W" if _pv_now is not None else "–"
            _banner_cols[2].info(f"**☀️ Sol nu:** {_sol_nu_text}")
            _banner_cols[3].info(f"**☀️ Sol +1h:** ~{_solar_next:.0f} W")
    except Exception:
        pass

render_strategy_banner()

st.divider()

# ── Sidor via st.navigation (fix 8: bara AKTIV sida körs per rerun, inte alla 13) ──
# Varje f.d. flik är nu en page_*-funktion (definieras nedan). Navigeringsmenyn + de
# nästlade föräldrasidorna (Temperaturer/Prognos/System) byggs sist i filen.
# Delad data som varje sida läser (row) beräknas här, FÖRE navigeringen körs.
row = load_latest()

# ══════════════════════════════════════════════════════════════════════════════
# 📊 ÖVERSIKT
# ══════════════════════════════════════════════════════════════════════════════
def page_overview():
    render_refresh_button("overview")

    # ── Beslutsrad: vad gör systemet just nu och varför (förbättring: tydlig topprad) ──
    if row is not None:
        _mode = str(row.get('active_mode') or '').upper()
        _emoji = "🟢" if _mode == "CHEAP" else ("🔴" if _mode == "EXPENSIVE" else "⏸️")
        _decision = row.get('active_decision') or "Utvärderar…"
        _bits = []
        _price = row.get('price')
        if _price is not None and not pd.isna(_price):
            _bits.append(f"💸 {float(_price):.2f} kr/kWh")
        _inroom = row.get('indoor_temp')
        if _inroom is not None and not pd.isna(_inroom):
            _tgt = settings.get('temp_cheap', 21.0) if _mode == 'CHEAP' else settings.get('temp_expensive', 20.0)
            _bits.append(f"🌡️ Inne {float(_inroom):.1f}°C (mål {_tgt:.0f})")
        _outt = row.get('outdoor_temp')
        if _outt is not None and not pd.isna(_outt):
            _bits.append(f"🌳 Ute {float(_outt):.1f}°C")
        with st.container(border=True):
            st.markdown(f"### {_emoji} {_decision}")
            if _bits:
                st.caption("  ·  ".join(_bits))
    st.divider()

    away_enabled = settings.get("away_mode_enabled", False)
    with st.expander(f"✈️ Bortaläge (Semesterläge) - {'AKTIVT' if away_enabled else 'Avstängt'}", expanded=away_enabled):
        st.markdown("När bortaläge är aktivt sänks husets temperatur till 15°C (frostskydd). Spabadet tvingas till Economy Mode (Lågtemp) och **varmvattenproduktionen stängs av helt** för att spara maximalt med energi. Systemet övervakar väder och vind för att automatiskt starta uppvärmningen i precis rätt tid så att huset når din inställda komforttemperatur lagom till din hemkomst.")
        
        away_ret_val = settings.get("away_return_date")
        if not away_ret_val:
            away_ret_val = (datetime.now(SWE_TZ) + timedelta(days=7)).replace(second=0, microsecond=0)
        else:
            if away_ret_val.tzinfo is None:
                away_ret_val = away_ret_val.replace(tzinfo=SWE_TZ)
            else:
                away_ret_val = away_ret_val.astimezone(SWE_TZ)
            
            # Säkerställ att sekunder/mikrosekunder nollställs, annars skapas en oändlig omladdnings-loop!
            away_ret_val = away_ret_val.replace(second=0, microsecond=0)
                
        with st.container(border=True):
            a_c1, a_c2, a_c3 = st.columns(3)
            with a_c1:
                new_away = st.toggle("Aktivera Bortaläge", value=away_enabled, key="ov_away_toggle")
            with a_c2:
                new_ret_date = st.date_input("Hemkomst Datum", value=away_ret_val.date() if hasattr(away_ret_val, 'date') else away_ret_val, key="ov_away_date")
            with a_c3:
                new_ret_time = st.time_input("Hemkomst Tid", value=away_ret_val.time() if hasattr(away_ret_val, 'time') else away_ret_val, key="ov_away_time")
                
            all_lights = {k: v.get("attributes", {}).get("friendly_name", k) for k, v in ha_data.items() if k.startswith("light.")}
            saved_lights_str = settings.get("away_lights_on_return", "")
            saved_lights = [l.strip() for l in saved_lights_str.split(",") if l.strip() in all_lights]
            new_lights = st.multiselect("💡 Tänd dessa lampor vid hemkomst (När tiden passerats)", options=list(all_lights.keys()), default=saved_lights, format_func=lambda x: all_lights[x], key="ov_away_lights")
                
            new_dt = datetime.combine(new_ret_date, new_ret_time).replace(tzinfo=SWE_TZ)
            new_lights_str = ",".join(new_lights)
            
            if new_away != away_enabled or new_dt != away_ret_val or sorted(new_lights) != sorted(saved_lights):
                with SessionLocal() as db:
                    sett = db.query(SystemSettings).filter(SystemSettings.id == 1).first()
                    if sett:
                        sett.away_mode_enabled = new_away
                        sett.away_return_date = new_dt
                        sett.away_lights_on_return = new_lights_str
                        db.commit()
                st.success("✅ Bortaläge uppdaterat!")
                time.sleep(1)
                st.rerun()

            if away_enabled:
                curr_indoor = row.get('indoor_temp') if row is not None else 15.0
                target_indoor = settings.get("temp_cheap", 21.0)
                delta_t = max(0.0, target_indoor - curr_indoor)
                recovery_model = learning.get_vp_recovery_model()
                out_t = row.get('outdoor_temp') if row is not None else 0.0
                if recovery_model is not None:
                    predicted_gm_h = recovery_model.predict(pd.DataFrame({'outdoor_temp': [out_t]}))[0]
                    heating_rate = max(0.1, predicted_gm_h / 100.0)
                else:
                    heating_rate = 0.3
                heat_hours = (delta_t / heating_rate)
                wind_s = row.get('wind_speed') if row is not None else 2.0
                if wind_s > 7.0: heat_hours *= 1.15
                total_recovery_h = heat_hours + 1.0 # 1h säkerhetsmarginal
                
                est_start = away_ret_val - timedelta(hours=total_recovery_h)
                
                st.info(f"🔥 **Beräknad uppvärmningsstart:** Huset börjar värmas ca **{est_start.strftime('%d/%m kl %H:%M')}** för att hinna nå {target_indoor}°C till din hemkomst.\n\n*(Estimerad uppvärmningstid är {total_recovery_h:.1f} timmar baserat på nuvarande innetemp {curr_indoor:.1f}°C och utomhusvind)*.")
                
                fig_away = go.Figure()
                if now < est_start:
                    x_vals = [now, est_start, away_ret_val]
                    y_vals = [curr_indoor, curr_indoor, target_indoor]
                else:
                    x_vals = [now, away_ret_val]
                    interp_temp = curr_indoor + (target_indoor - curr_indoor) * ((now - est_start).total_seconds() / (away_ret_val - est_start).total_seconds()) if (away_ret_val - est_start).total_seconds() > 0 else target_indoor
                    y_vals = [interp_temp, target_indoor]

                fig_away.add_trace(go.Scatter(x=x_vals, y=y_vals, mode='lines+markers', name='Inomhustemperatur', line=dict(color='#ff6b6b', width=3)))
                fig_away.add_trace(go.Scatter(x=[now, away_ret_val], y=[target_indoor, target_indoor], mode='lines', name='Måltemperatur', line=dict(color='#27ae60', width=2, dash='dot')))
                fig_away.update_layout(template="plotly_dark", title="Beräknad temperaturkurva för hemkomst", height=250, margin=dict(l=20, r=20, t=40, b=20), yaxis_title="Temperatur (°C)")
                fig_away.update_yaxes(range=[min(10, curr_indoor - 2), max(25, target_indoor + 2)])
                plot(fig_away, width="stretch")

    st.divider()

    # Visa Bas/Höglast info (Alltid synlig oavsett loggdata)
    n_month = now.month
    n_hour = now.hour
    n_wd = now.weekday()
    is_high_load = settings_module.is_high_load_time(now)
    load_type = "🔴 Höglast" if is_high_load else "🟢 Baslast"
    if is_high_load:
        load_reason = "Just nu är det vardag mellan kl 07-20 (November-Mars), vilket innebär att nätbolaget debiterar den dyrare höglasttariffen."
    else:
        if n_month in [11, 12, 1, 2, 3]:
            load_reason = "Just nu debiteras den billigare baslasttariffen (Gäller helger, samt vardagar kl 20-07 under vintern)."
        else:
            load_reason = "Sommarhalvår (April-Oktober) innebär att den billigare baslasttariffen gäller dygnet runt."
    st.info(f"⚡ **Aktuell Effekttariff:** {load_type} — {load_reason}")

    if row is not None:
        # 🧠 Visa Digitala Tvillingens tankar överst!

        display_price = current_live_price if current_live_price is not None else row.get('price', 0)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("⚡ Elpris just nu",   f"{format_kr_ore(display_price)}/kWh", help="Hämtas från Nordpool API (SE3)")
        _hum = row.get('indoor_humidity')
        _hum_txt = f" · 💧 {_hum:.0f} %" if _hum is not None and not pd.isna(_hum) else ""
        c2.metric("🌡️ Inne",             f"{row.get('indoor_temp') or 0:.1f} °C",
                  f"Mål: {row.get('target_room_temp') or 0:.1f} °C{_hum_txt}", delta_color="off", help="Median/medel av inomhussensorerna (samma värde som styrningen använder). 💧 = luftfuktighet inne.")
        c3.metric("🌲 Ute (Pump)",       f"{row.get('outdoor_temp') or 0:.1f} °C", help="Från värmepumpens utegivare (Modbus via Husdata)")
        netto = row.get('net_power')
        if netto is not None and not pd.isna(netto):
            label = "☀️ Netto (Säljer!)" if netto < 0 else "🔌 Netto (Köper)"
            c4.metric(label, f"{netto / 1000:.2f} kW", help="Beräknad live från Home Assistant (Tibber Pulse: Fas 1+2+3 Volt × Ampere).")

        st.divider()
        c5, c6, c7, c8 = st.columns(4)
        pv_w = row.get('pv_power_w')
        c5.metric("☀️ PV-effekt", f"{pv_w / 1000:.2f} kW" if pv_w is not None else "–", help="Direkt från SolarEdge växelriktare via Home Assistant")

        c6.metric("🛁 Varmvatten", f"{row.get('water_temp') or 0:.1f} °C", help="Temperaturgivare i värmepumpens beredare (Modbus via Husdata)")
        ev_pw = row.get('ev_power_kw')
        c7.metric("🚗 EV Laddning", f"{ev_pw:.1f} kW" if ev_pw is not None else "–", help="Aktuell laddeffekt från Easee laddbox (Home Assistant)")
        c8.write("")

        tid_str = pd.to_datetime(row['sthlm_time']).strftime('%Y-%m-%d %H:%M:%S')
        st.caption(f"Senast mätt: {tid_str}")

        # Diskmonitor
        with st.expander("💽 System-lagring"):
            stor = load_storage_info()
            disk_pct = stor.get("disk_pct", 0)
            
            st.markdown(f"**Disk:** {stor.get('disk_used_gb', 0):.1f} / {stor.get('disk_total_gb', 0):.1f} GB ({stor.get('disk_free_gb', 0):.1f} GB kvar)")
            st.progress(int(disk_pct))

            db_str  = f"{stor.get('db_total_gb'):.2f} GB"   if stor.get("db_total_gb")   is not None else "–"
            log_str = f"{stor.get('sensor_log_gb'):.2f} GB" if stor.get("sensor_log_gb") is not None else "–"
            if db_str != "–":
                st.caption(f"**Databas:** {db_str} (varav `sensor_log`: {log_str})")

        st.divider()
        _OPT       = ["Auto", "Till", "FRÅN"]
        _OPT_TO_DB = {"Auto": "auto", "Till": "on", "FRÅN": "off"}
        _DB_TO_OPT = {"auto": "Auto", "on": "Till", "off": "FRÅN"}

        with st.expander("🔧 Överstyrning – Värme / Varmvatten"):
            st.caption("Auto = systemet bestämmer. Manuell override gäller tills du väljer Auto igen.")
            _ovr = get_overrides()
            _oc1, _oc2 = st.columns(2)

            with _oc1:
                _sel_heat = st.radio("♨️ Värme", _OPT,
                    index=_OPT.index(_DB_TO_OPT.get(_ovr.get("heat", "auto"), "Auto")),
                    key="ov_heat", horizontal=True)
                if _OPT_TO_DB[_sel_heat] != _ovr.get("heat"):
                    set_override_db("heat", _OPT_TO_DB[_sel_heat])
                    st.rerun()

            with _oc2:
                _sel_hw = st.radio("🚿 Varmvatten", _OPT,
                    index=_OPT.index(_DB_TO_OPT.get(_ovr.get("hotwater", "auto"), "Auto")),
                    key="ov_hotwater", horizontal=True)
                if _OPT_TO_DB[_sel_hw] != _ovr.get("hotwater"):
                    set_override_db("hotwater", _OPT_TO_DB[_sel_hw])
                    st.rerun()

        st.divider()
        st.subheader("🤖 Senaste dygnets smarta händelser")
        st.caption("Visar när AI:n ändrat sin analys eller gjort ett aktivt val under de senaste 24 timmarna.")
        try:
            df_ai = pd.read_sql(text("""
                SELECT timestamp AT TIME ZONE 'Europe/Stockholm' AS sthlm_time, ai_action_log
                FROM sensor_log
                WHERE timestamp >= NOW() - INTERVAL '24 hours'
                  AND ai_action_log IS NOT NULL
                  AND ai_action_log != ''
                ORDER BY timestamp ASC
            """), engine)
            
            if not df_ai.empty:
                events = []
                last_msg = None
                # Filtrera fram enbart de tidpunkter då AI:ns meddelande ändrades
                for _, r in df_ai.iterrows():
                    msg = r['ai_action_log']
                    if msg != last_msg:
                        events.append((r['sthlm_time'], msg))
                        last_msg = msg
                
                # Visa de senaste 10 händelserna, nyast först
                for tid, msg in reversed(events[-10:]):
                    tid_str = pd.to_datetime(tid).strftime('%H:%M')
                    if "Allt är optimalt" in msg:
                        st.markdown(f"**{tid_str}** — 🟢 *Återgick till normal övervakning.*")
                    else:
                        st.info(f"**{tid_str}** — {msg}")
            else:
                st.info("Inga smarta beslut loggade under det senaste dygnet.")
        except Exception as e:
            if "does not exist" in str(e):
                pass
            else:
                st.error(f"Kunde inte ladda smarta händelser: {e}")
                
        # --- NY SEKTION: FRAMTIDSPROGNOS ---
        st.divider()
        st.subheader("🔮 AI:ns plan för det närmaste dygnet")
        st.caption("Visar hur systemet planerar att styra huset de kommande timmarna baserat på elpriser, solprognos och dina inställda regler.")
        
        # Kolla om ett spabadsschema ligger aktivt i bakgrunden
        spa_target_dt = settings.get("spa_target_datetime")
        spa_sched_enabled = settings.get("spa_schedule_enabled")
        if spa_sched_enabled and spa_target_dt:
            if spa_target_dt.tzinfo is None:
                spa_target_dt = spa_target_dt.replace(tzinfo=SWE_TZ)
            else:
                spa_target_dt = spa_target_dt.astimezone(SWE_TZ)
            if spa_target_dt > now:
                st.info(f"🛁 **Spabad:** ML-kalkylering planerar och optimerar uppvärmning mot **{settings.get('spa_target_temp')}°C** till **{spa_target_dt.strftime('%d/%m kl %H:%M')}** i bakgrunden.")

        try:
            cheap_h = settings.get("cheap_hours_count", 8)
            predictions = pred.predict_schedule(cheap_hours_count=cheap_h)
            if predictions:
                now_local = datetime.now(SWE_TZ).replace(minute=0, second=0, microsecond=0)
                # Kollar upp till 24h framåt
                future_preds = [p for p in predictions if p["time"] >= now_local][:24] 
                
                if future_preds:
                    planned_blocks = []
                    current_block = None
                    # Slå ihop konsekutiva 15-minutersblock med samma handling
                    for p in future_preds:
                        if current_block is None:
                            current_block = {"start": p["time"], "end": p["time_end"], "reason": p["reason"], "label": p["reason_label"]}
                        elif p["reason"] == current_block["reason"]:
                            current_block["end"] = p["time_end"]
                        else:
                            planned_blocks.append(current_block)
                            current_block = {"start": p["time"], "end": p["time_end"], "reason": p["reason"], "label": p["reason_label"]}
                    if current_block:
                        planned_blocks.append(current_block)
                    
                    for b in planned_blocks[:6]: # Visar de kommande 6 faserna för att inte ta för mycket plats
                        start_str = b['start'].strftime('%H:%M')
                        end_str = b['end'].strftime('%H:%M')
                        
                        if b['start'].date() > now_local.date():
                            start_str += " (imorgon)"
                        elif b['end'].date() > b['start'].date():
                            end_str += " (imorgon)"
                            
                        # Välj färg/ikon baserat på anledning
                        if b['reason'] in ["solar_heat", "solar_water"]: icon = "☀️"
                        elif b['reason'] in ["cheap", "comfort"]: icon = "🟢"
                        elif b['reason'] == "expensive": icon = "🔴"
                        else: icon = "⏸️"
                            
                        st.markdown(f"**{start_str} – {end_str}** {icon} {b['label']}")
                        
                    if len(planned_blocks) > 6:
                        st.caption("*...se fliken '📅 Prognos' för det fullständiga och mer detaljerade schemat.*")
                else:
                    st.info("Ingen prognosdata tillgänglig framåt i tiden just nu.")
            else:
                st.info("Kunde inte generera prognos (priser/väder saknas).")
                
        except Exception as e:
            st.error(f"Kunde inte ladda framtidsplan: {e}")

    else:
        st.info("Ingen data i loggen ännu.")

# ══════════════════════════════════════════════════════════════════════════════
# 🗺️ VÄRMEKARTA
# ══════════════════════════════════════════════════════════════════════════════
def page_heatmap():
    render_refresh_button("heatmap")
    st.subheader("🗺️ Live Värmekarta (Digital Tvilling)")
    st.caption("Visuell översikt över temperaturer och status i ditt smarta hem.")
    
    if row is not None:
        fig_map = go.Figure()
        
        # Enkel grafisk layout
        # Hus
        fig_map.add_shape(type="rect", x0=2, y0=2, x1=8, y1=8, fillcolor="rgba(52, 152, 219, 0.1)", line=dict(color="#3498db", width=2))
        fig_map.add_annotation(x=5, y=8.5, text="🏠 Huvudbyggnad", showarrow=False, font=dict(size=16, color="white"))
        
        # Garage / Carport
        fig_map.add_shape(type="rect", x0=8.5, y0=3, x1=11, y1=7, fillcolor="rgba(149, 165, 166, 0.1)", line=dict(color="#95a5a6", width=2))
        fig_map.add_annotation(x=9.75, y=7.5, text="🚗 Garage / Carport", showarrow=False, font=dict(size=14, color="white"))
        
        # Spabad
        fig_map.add_shape(type="rect", x0=6, y0=0.5, x1=7.5, y1=2, fillcolor="rgba(46, 204, 113, 0.1)", line=dict(color="#2ecc71", width=2))
        fig_map.add_annotation(x=6.75, y=0.1, text="🛁 Spabad", showarrow=False, font=dict(size=14, color="white"))

        # Samla in data för punkter (Temperaturer)
        nodes = []
        nodes.append({"x": 5, "y": 5, "name": "Vardagsrum", "temp": row.get('indoor_temp', 0)})
        nodes.append({"x": 9.75, "y": 5, "name": "Garage", "temp": safe_float('sensor.sensor_garage_enhetens_temperatur')})
        nodes.append({"x": 6.75, "y": 1.25, "name": "Spabad", "temp": safe_float('sensor.spa_malmgatan_34_current_temperature')})
        nodes.append({"x": 3, "y": 6, "name": "Matter 1", "temp": safe_float('sensor.timmerflotte_temp_hmd_sensor_temperatur')})
        nodes.append({"x": 4, "y": 3, "name": "Matter 2", "temp": safe_float('sensor.timmerflotte_temp_hmd_sensor_temperatur_2')})
        nodes.append({"x": 7, "y": 6, "name": "Matter 3", "temp": safe_float('sensor.timmerflotte_temp_hmd_sensor_temperatur_3')})
        nodes.append({"x": 1, "y": 9, "name": "Utomhus", "temp": row.get('outdoor_temp', 0)})
        
        df_nodes = pd.DataFrame(nodes)
        df_nodes = df_nodes[df_nodes['temp'] > -50] # Filtrera bort otillgängliga
        
        fig_map.add_trace(go.Scatter(
            x=df_nodes['x'], y=df_nodes['y'],
            mode='markers+text',
            marker=dict(size=40, color=df_nodes['temp'], colorscale='RdYlBu_r', cmin=0, cmax=40, showscale=True, colorbar=dict(title="°C")),
            text=df_nodes['temp'].apply(lambda x: f"{x:.1f}°C"),
            textposition="middle center",
            textfont=dict(color='white', size=12, family="Arial Black"),
            customdata=df_nodes['name'],
            hovertemplate="<b>%{customdata}</b><br>Temp: %{text}<extra></extra>"
        ))
        
        fig_map.update_layout(template="plotly_dark", xaxis=dict(visible=False, range=[0, 12]), yaxis=dict(visible=False, range=[0, 10]), height=600, margin=dict(l=0, r=0, t=30, b=0))
        plot(fig_map, width="stretch")
    else:
        st.warning("Väntar på sensordata...")

# ══════════════════════════════════════════════════════════════════════════════
# 🔌 ELFÖRBRUKNING (Live via Tibber & SolarEdge)
# ══════════════════════════════════════════════════════════════════════════════
def page_power():
    render_refresh_button("power")

    # ⚡ Vad drar just nu? — last-nedbrytning som förklarar husets effekt med det vi mäter.
    st.subheader("⚡ Vad drar just nu?")
    try:
        _lb = pd.read_sql(text("SELECT * FROM load_breakdown ORDER BY id DESC LIMIT 1"), engine)
    except Exception:
        _lb = pd.DataFrame()
    if _lb.empty:
        st.info("Samlar data — last-nedbrytningen visas när backend loggat en stund.")
    else:
        _r = _lb.iloc[0]
        _tot=float(_r['total_w'] or 0); _ev=float(_r['ev_w'] or 0); _pu=float(_r['pump_w'] or 0)
        _sp=float(_r['spa_w'] or 0); _un=float(_r['unexplained_w'] or 0)
        _c = st.columns(5)
        _c[0].metric("🏠 Totalt", f"{_tot/1000:.2f} kW")
        _c[1].metric("🚗 Elbil", f"{_ev/1000:.2f} kW")
        _c[2].metric("♨️ Värmepump", f"{_pu/1000:.2f} kW")
        _c[3].metric("🛁 Spa", f"{_sp/1000:.2f} kW")
        _c[4].metric("🔍 Oförklarat", f"{_un/1000:.2f} kW",
                     delta="okänd last" if _un > 1500 else None, delta_color="inverse")
        if _un > 2000:
            st.warning(f"🔍 **{_un/1000:.1f} kW är oförklarat** just nu (inte elbil/värmepump/spa) — kolla t.ex. ugn, bastu, tvätt/tork, laddare eller element.")
        st.caption("Husets totala effekt uppdelad på det vi mäter. **Oförklarat** = allt annat (spis, bastu, tvätt, laddare, element …).")
    st.divider()

    st.subheader("⚡ Prediktiv Peak Shaving & Elförbrukning")
    
    peak_shaving_enabled = settings.get("peak_shaving_enabled", True)
    new_ps_enabled = st.toggle("Aktivera Peak Shaving (Effektvakt)", value=peak_shaving_enabled, help="Stänger automatiskt av elbil och spabad för att inte överskrida effekttaket.")
    if new_ps_enabled != peak_shaving_enabled:
        with SessionLocal() as db:
            sett = db.query(SystemSettings).filter(SystemSettings.id == 1).first()
            if sett:
                sett.peak_shaving_enabled = new_ps_enabled
                db.commit()
        st.rerun()
        
    if not peak_shaving_enabled:
        st.warning("⚠️ **Peak Shaving är inaktiverat.** Systemet kommer inte att försöka begränsa dina effekttoppar eller påverka elbilsladdningen.")

    st.caption("Nätbolagen debiterar effekttariff baserat på ditt högsta timsnitt (energi förbrukad under en kalendertimme). AI:n övervakar ständigt den innevarande timmen och stryper laster proaktivt om prognosen hotar din maxgräns.")

    # --- LÄS MÅNADENS TOPPAR TIDIGT FÖR BERÄKNINGAR ---
    p_peak1_bas, p_peak2_bas = 0.0, 0.0
    p_peak1_hog, p_peak2_hog = 0.0, 0.0
    try:
        month_start_db = datetime.now(SWE_TZ).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        peaks_data = calculate_peaks_for_month(month_start_db)
        p_peak1_bas = peaks_data["p1_bas"]
        p_peak2_bas = peaks_data["p2_bas"]
        p_peak1_hog = peaks_data["p1_hog"]
        p_peak2_hog = peaks_data["p2_hog"]
    except Exception:
        pass

    # --- REALTIDSDATA (Variabler) ---
    v1 = safe_float("sensor.tibber_pulse_malmgatan_34_spanning_fas1")
    v2 = safe_float("sensor.tibber_pulse_malmgatan_34_spanning_fas2")
    v3 = safe_float("sensor.tibber_pulse_malmgatan_34_spanning_fas3")
    i1 = safe_float("sensor.tibber_pulse_malmgatan_34_strom_fas1")
    i2 = safe_float("sensor.tibber_pulse_malmgatan_34_strom_fas2")
    i3 = safe_float("sensor.tibber_pulse_malmgatan_34_strom_fas3")
    p1, p2, p3 = (v1 * i1), (v2 * i2), (v3 * i3)
    netto_w = p1 + p2 + p3
    sol_w = safe_float("sensor.solaredge_aktuell_effekt")
    husets_forbrukning = max(0.0, sol_w + netto_w)
    grid_import_kw = max(0.0, netto_w) / 1000.0

    # --- PREDIKTIV PEAK SHAVING MATEMATIK ---
    consumed_kwh_this_hour = safe_float("sensor.tibber_pulse_malmgatan_34_ackumulerad_forbrukning_under_aktuell_timme")
    minutes_left = 60 - now.minute
    
    power_limit_kw_bas_setting = settings.get("power_limit_kw_bas", 0.0)
    power_limit_kw_hog_setting = settings.get("power_limit_kw_hog", 0.0)
    old_limit = settings.get("power_limit_kw", 0.0)
    
    # Burn-down chart logik
    base_load_profile = learning.get_base_load_profile()
    historical_base_load_kw = learning.predict_base_load(now, base_load_profile)
    
    ev_kw_now = safe_float('sensor.easee_lite_effekt') + safe_float('sensor.carport_effekt')
    if ev_kw_now > 100: ev_kw_now /= 1000.0 # Justera ifall den läser ut W istället för kW
    spa_state = ha_state('water_heater.spa_malmgatan_34_heater', '–').lower()
    spa_kw_now = 3.0 if spa_state in ['heating', 'heat'] else 0.0
    
    current_actual_base_load_kw = max(0.5, (husets_forbrukning / 1000.0) - ev_kw_now - spa_kw_now)
    weight_actual = (60 - minutes_left) / 60.0
    weight_historical = 1.0 - weight_actual
    
    assumed_base_load_kw = (current_actual_base_load_kw * weight_actual) + (historical_base_load_kw * weight_historical)
    reserve_kwh_needed = assumed_base_load_kw * (minutes_left / 60.0)
    
    # Övergång från gamla variablen
    if power_limit_kw_bas_setting == 0 and power_limit_kw_hog_setting == 0 and old_limit > 0:
        power_limit_kw_bas_setting = old_limit
        power_limit_kw_hog_setting = old_limit
        
    is_high_load = settings_module.is_high_load_time(now)
    active_setting = power_limit_kw_hog_setting if is_high_load else power_limit_kw_bas_setting
    
    if active_setting > 0:
        current_target_limit = float(active_setting)
    else:
        if is_high_load and p_peak1_hog > 0:
            current_target_limit = (p_peak1_hog + p_peak2_hog) / 2.0 if p_peak2_hog > 0 else p_peak1_hog
        elif p_peak1_bas > 0:
            current_target_limit = (p_peak1_bas + p_peak2_bas) / 2.0 if p_peak2_bas > 0 else p_peak1_bas
        else:
            current_target_limit = 10.0
            
    allowed_kwh_now = current_target_limit - reserve_kwh_needed
    projected_pct = (consumed_kwh_this_hour / current_target_limit) * 100 if current_target_limit > 0 else 0

    # --- ANIMERAD PROGRESS BAR ---
    pulse_speed = max(0.3, 2.0 - (projected_pct / 50.0)) if projected_pct > 0 else 2.0
    st.markdown(f"""
        <style>
        @keyframes slide-stripes {{
            0% {{ background-position: 0 0; }}
            100% {{ background-position: 50px 50px; }}
        }}
        .stProgress > div > div > div {{
            background-image: linear-gradient(45deg, rgba(255,255,255,0.15) 25%, transparent 25%, transparent 50%, rgba(255,255,255,0.15) 50%, rgba(255,255,255,0.15) 75%, transparent 75%, transparent);
            background-size: 40px 40px;
            animation: slide-stripes {pulse_speed}s linear infinite;
        }}
        </style>
    """, unsafe_allow_html=True)

    # --- HUVUD-KPI:ER ---
    col1, col2, col3 = st.columns(3)
    col1.metric("🏠 Husets Totala Bruttolast", f"{husets_forbrukning / 1000:.2f} kW", help="Vad hela huset drar just nu (Solel + Nätimport).")
    if netto_w < 0:
        col2.metric("📤 Säljer till nätet", f"{abs(netto_w) / 1000:.2f} kW", delta_color="normal")
    else:
        col2.metric("📥 Import från nätet (Realtid)", f"{grid_import_kw:.2f} kW", delta_color="inverse", help="Detta är vad som bygger upp din effekttariff.")
    
    col3.metric("⏱️ Återstår av timmen", f"{minutes_left} min", help="Tid kvar tills snittet nollställs och en ny timme börjar.")

    # --- INTEGRERINGS-MÄTAREN (Mitten av skärmen) ---
    st.markdown("### 🎯 Prognos för aktuell timme (Timsnitt)")
    
    p_col1, p_col2 = st.columns([3, 1])
    with p_col1:
        st.progress(min(100, max(0, int(projected_pct))))
        if consumed_kwh_this_hour > allowed_kwh_now:
            st.error(f"🚨 **KRITISKT:** Energibudgeten ({consumed_kwh_this_hour:.2f} > {allowed_kwh_now:.2f} kWh) är överkredriden. AI:n har strypt spabad och elbil!")
        elif consumed_kwh_this_hour > allowed_kwh_now * 0.90:
            st.warning(f"🟡 **VARNING:** Närmar sig brist i budgeten. Kommer strax pausa bil/bad.")
        else:
            st.success(f"🟢 **LUGNT:** Förbrukat {consumed_kwh_this_hour:.2f} kWh hittills. Taket för denna minut är {allowed_kwh_now:.2f} kWh.")
            
    with p_col2:
        st.markdown(f"<h3 style='text-align: right; margin: 0;'>{consumed_kwh_this_hour:.2f} / {current_target_limit:.2f} kWh</h3>", unsafe_allow_html=True)

    st.caption(f"**Matematiken bakom:** Bilen tillåts maximera ('bursta') uppladdningen fritt i början av timmen för att utnyttja billiga kvartar. Vi reserverar dock {reserve_kwh_needed:.2f} kWh för att klara husets grundförbrukning resten av timmen.")

    st.divider()

    if not peak_shaving_enabled:
        st.info("ℹ️ **Detta styr just nu ingenting.** Effekttariff-taket nedan används bara när Peak Shaving är aktiverat (toggeln högst upp). Har du **ingen effekttariff** hos ditt elnätsbolag längre kan du strunta i den här sektionen helt. Letar du efter din **huvudsäkring** (25A) — den ställer du in längre ned under '⚖️ Fysisk lastsäkring'.")

    with st.form("power_limit_form"):
        st.markdown("#### ⚙️ Ställ in din acceptabla Effekttariff (Tak)")
        st.caption("Sätt till **0.0** för att låta systemet automatiskt följa Jönköping Energis beräkning (snittet av månadens två högsta toppar). **OBS:** detta är inte din huvudsäkring — det är taket nätbolaget debiterar effekttariff på. Aktiv bara när Peak Shaving är på.")
                
        power_limit_kw_bas_setting = settings.get("power_limit_kw_bas", 0.0)
        power_limit_kw_hog_setting = settings.get("power_limit_kw_hog", 0.0)
        old_limit = settings.get("power_limit_kw", 0.0)
        if power_limit_kw_bas_setting == 0 and power_limit_kw_hog_setting == 0 and old_limit > 0:
            power_limit_kw_bas_setting = old_limit
            power_limit_kw_hog_setting = old_limit
                
        c1, c2 = st.columns(2)
        with c1:
            new_power_limit_bas = st.number_input("Smärtgräns Baslasttid (kW) [0.0 = Auto]", min_value=0.0, max_value=20.0, value=float(power_limit_kw_bas_setting), step=0.5, help="Gäller normalt året runt utom vardagar 07-20 på vintern.")
        with c2:
            new_power_limit_hog = st.number_input("Smärtgräns Höglasttid (kW) [0.0 = Auto]", min_value=0.0, max_value=20.0, value=float(power_limit_kw_hog_setting), step=0.5, help="Gäller Nov-Mar, Mån-Fre 07:00-20:00. Oftast dyrare!")
        submitted = st.form_submit_button("💾 Spara effektgräns")
        if submitted:
            try:
                with SessionLocal() as db:
                    sett = db.query(SystemSettings).filter(SystemSettings.id == 1).first()
                    if sett:
                        sett.power_limit_kw_bas = new_power_limit_bas
                        sett.power_limit_kw_hog = new_power_limit_hog
                        db.commit()
                st.success("✅ Effektgräns sparad! AI:n anpassar sig omedelbart.")
                time.sleep(1)
                st.rerun()
            except Exception as e:
                st.error(f"Fel: {e}")
                
        power_lim_bas = float(settings.get("power_limit_kw_bas", 0.0))
        power_lim_hog = float(settings.get("power_limit_kw_hog", 0.0))
        if (0 < power_lim_bas < 7.0) or (0 < power_lim_hog < 7.0):
            st.warning("⚠️ **Tajt marginal:** Många elbilar (på 3-fas) drar absolut minimum **4.14 kW** (och på 1-fas ca 1.38 kW). Om ditt tak är satt under 7 kW finns väldigt lite utrymme kvar för värmepumpen och hushållsel. Risken är stor att AI:n (Peak Shaving) ofta tvingas pausa laddningen för att skydda taket.")

    st.divider()

    # --- FASBALANSERING ---
    st.markdown("#### ⚖️ Fysisk lastsäkring (Huvudsäkring)")
    fuse_size_setting = float(settings.get("fuse_size_a", 25.0))
    st.caption(f"Håller koll på att ingen enskild fas överskrider din fysiska huvudsäkring (**{fuse_size_setting:.0f} A**). Elbilsladdaren balanseras automatiskt mot den fas som har högst last. Detta gäller ALLTID — oavsett om Peak Shaving/effekttariff är på eller av, eftersom det skyddar mot att säkringen löser ut.")

    with st.form("fuse_size_form"):
        new_fuse_size = st.number_input("Din huvudsäkring (A)", min_value=10.0, max_value=63.0,
                                        value=fuse_size_setting, step=1.0,
                                        help="Hur många ampere din huvudsäkring klarar per fas (vanligt: 16, 20, 25 eller 35 A). Detta är en fysisk gräns — sätt den till exakt vad det står på din elcentral.")
        if st.form_submit_button("💾 Spara säkringsstorlek"):
            try:
                with SessionLocal() as db:
                    sett = db.query(SystemSettings).filter(SystemSettings.id == 1).first()
                    if sett:
                        sett.fuse_size_a = new_fuse_size
                        db.commit()
                st.success("✅ Säkringsstorlek sparad!")
                time.sleep(1)
                st.rerun()
            except Exception as e:
                st.error(f"Fel: {e}")

    f1, f2, f3 = st.columns(3)

    def render_phase_gauge(val, max_val, title):
        option = {
            "tooltip": {"formatter": "{a} <br/>{b} : {c}A"},
            "series": [{
                "name": title,
                "type": "gauge",
                "max": max_val,
                "axisLine": {
                    "lineStyle": {
                        "width": 10,
                        "color": [[0.6, "#2ecc71"], [0.8, "#f1c40f"], [1, "#e74c3c"]]
                    }
                },
                "detail": {"valueAnimation": True, "formatter": "{value} A"},
                "data": [{"value": round(val, 1), "name": title}]
            }]
        }
        return option

    with f1:
        st_echarts(options=render_phase_gauge(i1, fuse_size_setting, "Fas 1"), height="250px", key="gauge_l1")
    with f2:
        st_echarts(options=render_phase_gauge(i2, fuse_size_setting, "Fas 2"), height="250px", key="gauge_l2")
    with f3:
        st_echarts(options=render_phase_gauge(i3, fuse_size_setting, "Fas 3"), height="250px", key="gauge_l3")

    st.divider()

    # --- NYTT DIAGRAM FÖR MÅNADSÖVERSIKT ---
    st.subheader("📅 Månadsöversikt Effekttoppar")
    st.caption("Välj en månad för att se de dagliga topparna för baslast och höglast. De två staplar som ligger till grund för din faktura är markerade med en avvikande färg.")

    # Skapa en lista över månader som finns i databasen
    try:
        df_months = pd.read_sql(text("SELECT DISTINCT DATE_TRUNC('month', timestamp) as month FROM sensor_log ORDER BY month DESC"), engine)
        if not df_months.empty:
            month_options = {dt.strftime('%B %Y'): dt for dt in df_months['month']}
            selected_month_str = st.selectbox("Välj månad", options=list(month_options.keys()))
            
            if selected_month_str:
                selected_month_dt = month_options[selected_month_str]
                month_end_dt = selected_month_dt + pd.DateOffset(months=1)
                plot_monthly_peaks(selected_month_dt, month_end_dt)
    except Exception as e:
        st.error(f"Kunde inte ladda månadsdata för diagram: {e}")

    st.divider()
    
    # --- NY DIAGRAM FÖR DETALJERAD DYGNSANALYS (15 MIN UPPÖSNING) ---
    st.subheader("🕰️ Detaljerad Dygnsanalys")
    st.caption("Välj en specifik dag och upplösning för att se exakt hur effekten fördelades över dygnet. Perfekt för att felsöka Peak Shaving.")

    col_date, col_res = st.columns(2)
    with col_date:
        selected_date = st.date_input("Välj datum för analys", value=now.date())
    with col_res:
        res_choice = st.selectbox("Upplösning", ["15 minuter", "60 minuter"], index=0)
        
    res_rule = '15min' if "15" in res_choice else '60min'
    
    if selected_date:
        start_of_selected_day = datetime.combine(selected_date, datetime.min.time()).replace(tzinfo=SWE_TZ)
        end_of_selected_day = start_of_selected_day + timedelta(days=1)
        
        try:
            df_daily_hist = pd.read_sql(text("""
                SELECT 
                    timestamp AT TIME ZONE 'Europe/Stockholm' as ts,
                    GREATEST(net_power, 0) / 1000.0 as grid_import_kw,
                    COALESCE(ev_power_kw, 0) as nissan_kw,
                    COALESCE(ev_carport_power_kw, 0) as tesla_kw,
                    COALESCE(avg_w_tot, 0) / 1000.0 as pump_kw
                FROM sensor_log
                WHERE timestamp >= :start AND timestamp < :end
            """), engine, params={"start": start_of_selected_day, "end": end_of_selected_day})
                
            if not df_daily_hist.empty:
                # Gruppera datan baserat på vald upplösning och beräkna medelvärdet
                df_daily_hist['ts'] = pd.to_datetime(df_daily_hist['ts']).dt.tz_localize(None)
                df_daily_hist = df_daily_hist.drop_duplicates(subset=['ts'])
                df_1min = df_daily_hist.set_index('ts').resample('1min').ffill(limit=5).fillna(0)
                df_resampled = df_1min.resample(res_rule).mean().reset_index()
                
                # Räkna ut övrig hushållsel (Total importerad - Bilar - Värmepump)
                df_resampled['other_kw'] = (df_resampled['grid_import_kw'] - df_resampled['nissan_kw'] - df_resampled['tesla_kw'] - df_resampled['pump_kw']).clip(lower=0)
                
                # Beräkna det faktiska timsnittet (det som nätbolaget debiterar efter)
                df_resampled['hour'] = df_resampled['ts'].dt.floor('h')
                hourly_avg = df_resampled.groupby('hour')['grid_import_kw'].mean().reset_index().rename(columns={'grid_import_kw': 'hourly_mean_kw'})
                df_resampled = pd.merge(df_resampled, hourly_avg, on='hour', how='left')
                
                # Beräkna vilken gräns som gällde historiskt för de olika tiderna på det valda dygnet
                def get_historical_limit(ts):
                    if settings_module.is_high_load_time(ts):
                        return power_limit_kw_hog_setting if power_limit_kw_hog_setting > 0 else 10.0
                    return power_limit_kw_bas_setting if power_limit_kw_bas_setting > 0 else 10.0
                
                df_resampled['limit_kw'] = df_resampled['ts'].apply(get_historical_limit)
                
                fig_day = go.Figure()
                fig_day.add_trace(go.Bar(x=df_resampled['ts'], y=df_resampled['other_kw'], name="Övrig Hushållsel", marker_color='#95a5a6'))
                fig_day.add_trace(go.Bar(x=df_resampled['ts'], y=df_resampled['pump_kw'], name="Värmepump", marker_color='#3498db'))
                fig_day.add_trace(go.Bar(x=df_resampled['ts'], y=df_resampled['nissan_kw'], name="Nissan Leaf", marker_color='#2ecc71'))
                fig_day.add_trace(go.Bar(x=df_resampled['ts'], y=df_resampled['tesla_kw'], name="Tesla Model Y", marker_color='#e74c3c'))
                fig_day.add_trace(go.Scatter(x=df_resampled['ts'], y=df_resampled['limit_kw'], name="Effekttak (Beräknat)", mode='lines', line=dict(color='red', width=2, dash='dot')))
                fig_day.add_trace(go.Scatter(x=df_resampled['ts'], y=df_resampled['hourly_mean_kw'], name="Faktiskt Timsnitt", mode='lines', line=dict(color='#d35400', width=3, shape='hv'), hovertemplate="Timsnitt: %{y:.2f} kW<extra></extra>"))
                
                res_title_str = "15-min" if "15" in res_choice else "60-min"
                fig_day.update_layout(template="plotly_dark", barmode='stack', hovermode='x unified', title=f"Effektuttag från elnätet den {selected_date.strftime('%Y-%m-%d')} ({res_title_str} upplösning)", yaxis_title="Genomsnittlig Effekt (kW)", xaxis_title="Tid", legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5))
                fig_day.update_yaxes(rangemode="tozero")
                plot(fig_day, width="stretch")
            else:
                st.info("Ingen loggdata hittades för detta datum i databasen.")
        except Exception as e:
            st.error(f"Kunde inte ladda dygnsdata: {e}")

    st.divider()
    
    # --- NY DIAGRAM: MÅNADSANALYS (60-min upplösning) ---
    st.subheader("📅 Månadsanalys - Förbrukning per timme")
    st.caption("Visar din genomsnittliga förbrukning timme för timme över en hel vald månad. Perfekt för att hitta mönster och identifiera när på dygnet ditt hus drar mest el.")
    
    try:
        df_months = pd.read_sql(text("SELECT DISTINCT DATE_TRUNC('month', timestamp) as month FROM sensor_log ORDER BY month DESC"), engine)
        if not df_months.empty:
            month_options = {dt.strftime('%B %Y').title(): dt for dt in df_months['month']}
            selected_analysis_month = st.selectbox("Välj månad för djupanalys", options=list(month_options.keys()), key="monthly_analysis_dd")
            
            if selected_analysis_month:
                start_dt = month_options[selected_analysis_month]
                end_dt = start_dt + pd.DateOffset(months=1)
                
                df_monthly_analysis = pd.read_sql(text("""
                    SELECT 
                        EXTRACT(HOUR FROM timestamp AT TIME ZONE 'Europe/Stockholm') as hour,
                        AVG(GREATEST(net_power, 0)) / 1000.0 as grid_import_kw,
                        AVG(COALESCE(ev_power_kw, 0)) as nissan_kw,
                        AVG(COALESCE(ev_carport_power_kw, 0)) as tesla_kw,
                        AVG(COALESCE(avg_w_tot, 0)) / 1000.0 as pump_kw
                    FROM sensor_log
                    WHERE timestamp >= :start AND timestamp < :end
                    GROUP BY 1 ORDER BY 1
                """), engine, params={"start": start_dt, "end": end_dt})
                
                if not df_monthly_analysis.empty:
                    df_monthly_analysis['other_kw'] = (df_monthly_analysis['grid_import_kw'] - df_monthly_analysis['nissan_kw'] - df_monthly_analysis['tesla_kw'] - df_monthly_analysis['pump_kw']).clip(lower=0)
                    
                    fig_heat = go.Figure()
                    fig_heat.add_trace(go.Bar(x=df_monthly_analysis['hour'], y=df_monthly_analysis['other_kw'], name="Övrig Hushållsel", marker_color='#95a5a6'))
                    fig_heat.add_trace(go.Bar(x=df_monthly_analysis['hour'], y=df_monthly_analysis['pump_kw'], name="Värmepump", marker_color='#3498db'))
                    fig_heat.add_trace(go.Bar(x=df_monthly_analysis['hour'], y=df_monthly_analysis['nissan_kw'], name="Nissan Leaf", marker_color='#2ecc71'))
                    fig_heat.add_trace(go.Bar(x=df_monthly_analysis['hour'], y=df_monthly_analysis['tesla_kw'], name="Tesla Model Y", marker_color='#e74c3c'))
                    
                    fig_heat.update_layout(template="plotly_dark", barmode='stack', title=f"Genomsnittlig profil per timme ({selected_analysis_month})", xaxis_title="Klockslag (0-23)", yaxis_title="Snitteffekt (kW)")
                    plot(fig_heat, width="stretch")
    except Exception as e:
        st.error(f"Kunde inte ladda månadsanalys: {e}")

    st.divider()
    # --- MÅNADSHISTORIK & EFFEKTTARIFF ---
    st.subheader("📊 Elförbrukning & Effekttariff (Jönköping Energi)")
    st.caption("Visar dina dagliga toppnoteringar (timsnitt) denna månad enligt Jönköping Energis regelverk (medelvärdet av de två högsta timmarna från två olika dygn).")

    p_peak1 = 0.0
    p_peak2 = 0.0
    t_peak1 = "Saknas"
    t_peak2 = "Saknas"
    
    try:
        month_start_db = datetime.now(SWE_TZ).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        p_data = calculate_peaks_for_month(month_start_db)
        
        p_peak1_bas = p_data['p1_bas']
        p_peak2_bas = p_data['p2_bas']
        t_peak1_bas = p_data['t1_bas']
        t_peak2_bas = p_data['t2_bas']
        
        p_peak1_hog = p_data['p1_hog']
        p_peak2_hog = p_data['p2_hog']
        t_peak1_hog = p_data['t1_hog']
        t_peak2_hog = p_data['t2_hog']
                
        # Beräkna Live-värden
        now_minute = now.minute
        elapsed_h = max(now_minute, 1) / 60.0
        live_avg_kw = consumed_kwh_this_hour / elapsed_h
        
        # Beräkna säsong och tid (Jönköping Energi: Höglast = Nov-Mar Mån-Fre 07:00-20:00)
        month = now.month
        weekday = now.weekday()
        hour = now.hour
        is_high_load = settings_module.is_high_load_time(now)
        season_text = "Höglastsäsong (Nov-Mar)" if month in [11, 12, 1, 2, 3] else "Baslastsäsong (Apr-Okt)"
        load_status_text = "🔴 **Höglasttid aktiv** (Mån-Fre 07-20)" if is_high_load else "🟢 **Låglasttid** (Baslast)"
            
        # Rita graf
        fig_a = go.Figure()
        
        x_vals = [f"Bas 1<br>{t_peak1_bas}", f"Bas 2<br>{t_peak2_bas}"]
        y_vals = [p_peak1_bas, p_peak2_bas]
        colors = ['#27ae60', '#27ae60']
        texts = [f"{p_peak1_bas:.2f} kW", f"{p_peak2_bas:.2f} kW"]
        
        if is_high_load or p_peak1_hog > 0:
            x_vals.extend([f"Hög 1<br>{t_peak1_hog}", f"Hög 2<br>{t_peak2_hog}"])
            y_vals.extend([p_peak1_hog, p_peak2_hog])
            colors.extend(['#ff6b6b', '#ff6b6b'])
            texts.extend([f"{p_peak1_hog:.2f} kW", f"{p_peak2_hog:.2f} kW"])
            
        x_vals.append(f"⚡ Live<br>{now.strftime('%H:%M')}")
        y_vals.append(live_avg_kw)
        live_color = '#d35400' if is_high_load else '#e67e22'
        colors.append(live_color)
        texts.append(f"{live_avg_kw:.2f} kW")

        fig_a.add_trace(go.Bar(
            x=x_vals, y=y_vals, marker_color=colors, text=texts, textposition='auto', width=[0.4]*len(x_vals)
        ))
        fig_a.update_layout(
            template="plotly_dark",
            title="Effekttariff: Månadens toppar vs Realtid",
            yaxis_title="Tim-medeleffekt (kW)",
            showlegend=False,
            margin=dict(t=40, b=20)
        )
        plot(fig_a, width="stretch")
        
        # Textförklaring
        months_sv = ["", "Januari", "Februari", "Mars", "April", "Maj", "Juni", "Juli", "Augusti", "September", "Oktober", "November", "December"]
        
        st.info(f"💡 **Status just nu:** Vi är **{now_minute} minuter** in i aktuell timme. Din beräknade medeleffekt (tim-snitt) landar på **{live_avg_kw:.2f} kW** om huset fortsätter förbruka i denna takt.")
        
        st.markdown(f"**Information om din Effekttariff (Jönköping Energi)**")
        st.markdown(f"- Just nu befinner vi oss i **{season_text}**. Aktuell tidszon: {load_status_text}.")
        st.markdown(f"**Detaljerad Kostnad för {months_sv[month]} {now.year} (Hittills)**")
        st.markdown(f"- **Baslast (27.70 kr/kW):** Snitt av {p_peak1_bas:.2f} kW och {p_peak2_bas:.2f} kW = **{p_data['avg_bas']:.2f} kW** ➔ **{p_data['avg_bas']*27.70:.0f} kr**")
        if p_data['avg_hog'] > 0:
            st.markdown(f"- **Höglast (65.66 kr/kW):** Snitt av {p_peak1_hog:.2f} kW och {p_peak2_hog:.2f} kW = **{p_data['avg_hog']:.2f} kW** ➔ **{p_data['avg_hog']*65.66:.0f} kr**")
            
        warn_threshold = p_peak2_hog if is_high_load else p_peak2_bas
        if live_avg_kw > warn_threshold and warn_threshold > 0:
            st.warning(f"⚠️ **VARNING:** Om nuvarande förbrukningstakt håller i sig kommer denna timme slå din Topp 2 och **öka din effekttariff!**")
            
    except Exception as e:
        st.error(f"Kunde inte ladda effekttariff-modul: {e}")
        
    st.divider()
    st.markdown("### 🧺 Husgeråd")
    m_status = ha_state('sensor.tvattmaskin')
    m_phase  = ha_state('sensor.tvattmaskin_programfas').replace("_", " ").title()
    st.metric("Tvättmaskin (Miele)", m_status.capitalize() if m_status != "–" else "–", m_phase if m_phase not in ("–", "Not Running") else "Viloläge", delta_color="off")

# ══════════════════════════════════════════════════════════════════════════════
# ♨️ VÄRMEPUMP
# ══════════════════════════════════════════════════════════════════════════════
@st.cache_data(ttl=600)
def _solar_free_cached():
    import pump_runtime as _pr
    with engine.connect() as _c:
        return _pr.solar_free(_c)


def render_solar_free():
    """Timmar som är gratis tack vare solen: ingen nätimport medan solen producerar."""
    st.markdown("#### ☀️ Gratis tack vare solen")
    try:
        sf = _solar_free_cached()
    except Exception as e:
        st.info(f"Kunde inte räkna solgratis-timmar ({e}).")
        return
    if not sf["manader"]:
        st.info("Ingen data ännu.")
        return
    dm = pd.DataFrame(sf["manader"])
    dm["Månad"] = pd.to_datetime(dm["manad"]).dt.strftime("%Y-%m")
    cur = dm.iloc[-1]
    yr = dm[pd.to_datetime(dm["manad"]).dt.year == pd.to_datetime(cur["manad"]).year]
    e1, e2, e3, e4 = st.columns(4)
    e1.metric("Pumpens solel denna månad", f"{int(cur['komp_sol_kwh'])} kWh", f"av {int(cur['komp_kwh'])} kWh totalt", delta_color="off")
    e2.metric("Sparad inköpskostnad denna månad", f"{int(cur['sparat_kr'])} kr")
    e3.metric(f"Pumpens solel {pd.to_datetime(cur['manad']).year}", f"{int(yr['komp_sol_kwh'].sum())} kWh", f"{100 * yr['komp_sol_kwh'].sum() / max(1, yr['komp_kwh'].sum()):.0f} % av {int(yr['komp_kwh'].sum())} kWh", delta_color="off")
    e4.metric(f"Sparat {pd.to_datetime(cur['manad']).year}", f"{int(yr['sparat_kr'].sum())} kr")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Kompressor på solel (denna månad)", f"{cur['komp_gratis_h']:.0f} h", f"{cur['pct_gratis']} % av {cur['komp_h']} h", delta_color="off")
    k2.metric("Hela huset utan nätimport (denna månad)", f"{int(cur['hus_h'])} h")
    k3.metric(f"Kompressor på solel {pd.to_datetime(cur['manad']).year}", f"{yr['komp_gratis_h'].sum():.0f} h", f"{100 * yr['komp_gratis_h'].sum() / max(1, yr['komp_h'].sum()):.0f} % av {int(yr['komp_h'].sum())} h", delta_color="off")
    k4.metric(f"Hus utan nätimport {pd.to_datetime(cur['manad']).year}", f"{int(yr['hus_h'].sum())} h")
    fig = go.Figure()
    fig.add_bar(x=dm["Månad"], y=dm["komp_gratis_h"], name="Kompressor på solel", marker_color="#ffb300")
    fig.add_bar(x=dm["Månad"], y=(dm["komp_h"] - dm["komp_gratis_h"]).clip(lower=0), name="Kompressor på nätel", marker_color="#78909c")
    fig.update_layout(barmode="stack", height=300, margin=dict(l=10, r=10, t=30, b=10), yaxis_title="kompressortimmar", legend=dict(orientation="h", y=1.12))
    st.plotly_chart(fig, use_container_width=True)
    dh = pd.DataFrame(sf["timmar"])
    dh = dh.set_index("timme").reindex(range(24), fill_value=0).reset_index()
    fig2 = go.Figure()
    fig2.add_bar(x=dh["timme"], y=dh["hus_h"], name="Hela huset utan nätimport", marker_color="#ffe082")
    fig2.add_bar(x=dh["timme"], y=dh["komp_gratis_h"], name="Kompressor på solel", marker_color="#ff7043")
    fig2.update_layout(barmode="overlay", height=300, margin=dict(l=10, r=10, t=30, b=10), xaxis=dict(title="klockslag (svensk tid)", dtick=1), yaxis_title="timmar (summa sedan 25 mars)", legend=dict(orientation="h", y=1.12))
    st.caption("Vilka klockslag som är gratis: staplarna visar hur många timmar (summerat sedan 25 mars) som varje klockslag har varit utan nätimport.")
    st.plotly_chart(fig2, use_container_width=True)
    t = dm[["Månad", "hus_h", "komp_h", "komp_gratis_h", "pct_gratis", "komp_kwh", "komp_sol_kwh", "sparat_kr", "tackning_pct"]].rename(columns={
        "hus_h": "Hus utan nätimport (h)", "komp_h": "Kompressor (h)", "komp_gratis_h": "Kompressor på solel (h)", "pct_gratis": "Andel på solel (%)",
        "komp_kwh": "Pumpens el (kWh)", "komp_sol_kwh": "varav solel (kWh)", "sparat_kr": "Sparat (kr)", "tackning_pct": "Loggtäckning (%)"})
    st.dataframe(t.iloc[::-1], hide_index=True, use_container_width=True)
    st.caption("kWh = pumpens modellerade effekt (från framledningstemperaturen, kalibrerad mot 60 nätter) × tiden; Sparat = solel-kWh × inköpspris "
               "(spot × 1,25 + 0,62675 kr/kWh, samma modell som smartbox använder). Det är avoided inköpskostnad, inte försäljningsvärde.")
    st.caption("Gratis = ingen nätimport (nätet ≤ 0 W) medan solen producerar. Timmar för huset är uppskattade och uppskalade för loggluckor (se Loggtäckning). "
               "Kompressortimmar = pumpens riktiga räknare × den andel av körtiden som skedde utan nätimport.")


def render_pump_runtime():
    """Värmepumpens drifttid per månad och år (kompressor, tillsats 1/2, varmvatten). Källa: pump_runtime_daily."""
    st.divider()
    st.subheader("⏱️ Värmepumpens drifttid")
    try:
        deltas = """
            WITH x AS (
                SELECT day,
                       GREATEST(compressor_h - lag(compressor_h) OVER (ORDER BY day), 0) c,
                       GREATEST(aux1_h - lag(aux1_h) OVER (ORDER BY day), 0) a1,
                       GREATEST(aux2_h - lag(aux2_h) OVER (ORDER BY day), 0) a2,
                       GREATEST(warm_water_h - lag(warm_water_h) OVER (ORDER BY day), 0) w
                FROM pump_runtime_daily)
            SELECT date_trunc('{unit}', day)::date AS period, sum(c) AS kompressor, sum(a1) AS tillsats1, sum(a2) AS tillsats2,
                   sum(w) AS varmvatten, count(*) FILTER (WHERE c IS NOT NULL) AS dagar
            FROM x GROUP BY 1 ORDER BY 1"""
        df_m = pd.read_sql(text(deltas.format(unit="month")), engine)
        df_y = pd.read_sql(text(deltas.format(unit="year")), engine)
        df_last = pd.read_sql(text("SELECT day, compressor_h, aux1_h, aux2_h, warm_water_h FROM pump_runtime_daily ORDER BY day DESC LIMIT 1"), engine)
    except Exception as e:
        st.info(f"Drifttiden är inte tillgänglig ännu ({e}). Den skapas av smartbox vid nästa start.")
        return
    if df_m.empty or df_last.empty:
        st.info("Ingen drifttid sparad ännu.")
        return
    last = df_last.iloc[0]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Kompressor (totalt)", f"{int(last['compressor_h']):,} h".replace(",", " "), help="Pumpens egen räknare (Drifttid → Värmepump)")
    c2.metric("Tillsats 1 (totalt)", f"{int(last['aux1_h'])} h")
    c3.metric("Tillsats 2 (totalt)", f"{int(last['aux2_h'])} h")
    c4.metric("Varmvatten (totalt)", f"{int(last['warm_water_h']):,} h".replace(",", " "))
    cur = df_m.iloc[-1]
    prev = df_m.iloc[-2] if len(df_m) > 1 else None
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Kompressor denna månad", f"{int(cur['kompressor'])} h", f"{int(cur['kompressor'] - prev['kompressor']):+d} h mot förra" if prev is not None else None, delta_color="off")
    m2.metric("Tillsats 1+2 denna månad", f"{int(cur['tillsats1'] + cur['tillsats2'])} h")
    m3.metric("Varmvatten denna månad", f"{int(cur['varmvatten'])} h")
    yr = df_y.iloc[-1]
    m4.metric(f"Kompressor {pd.Timestamp(yr['period']).year} hittills", f"{int(yr['kompressor'])} h")
    df_plot = df_m.copy()
    df_plot["Månad"] = pd.to_datetime(df_plot["period"]).dt.strftime("%Y-%m")
    fig = go.Figure()
    fig.add_bar(x=df_plot["Månad"], y=df_plot["kompressor"], name="Kompressor", marker_color="#ff7043")
    fig.add_bar(x=df_plot["Månad"], y=df_plot["varmvatten"], name="Varmvatten", marker_color="#42a5f5")
    fig.add_bar(x=df_plot["Månad"], y=df_plot["tillsats1"] + df_plot["tillsats2"], name="Tillsats 1+2", marker_color="#e53935")
    fig.update_layout(barmode="group", height=320, margin=dict(l=10, r=10, t=30, b=10), yaxis_title="timmar", legend=dict(orientation="h", y=1.12))
    st.plotly_chart(fig, use_container_width=True)
    tab_m, tab_y = st.tabs(["📅 Per månad", "🗓️ Per år"])
    with tab_m:
        t = df_plot[["Månad", "kompressor", "tillsats1", "tillsats2", "varmvatten", "dagar"]].rename(columns={
            "kompressor": "Kompressor (h)", "tillsats1": "Tillsats 1 (h)", "tillsats2": "Tillsats 2 (h)", "varmvatten": "Varmvatten (h)", "dagar": "Dygn"})
        t["Kompressor (h/dygn)"] = (t["Kompressor (h)"] / t["Dygn"].where(t["Dygn"] > 0)).round(1)
        st.dataframe(t.iloc[::-1], hide_index=True, use_container_width=True)
    with tab_y:
        ty = df_y.copy()
        ty["År"] = pd.to_datetime(ty["period"]).dt.year
        ty = ty[["År", "kompressor", "tillsats1", "tillsats2", "varmvatten", "dagar"]].rename(columns={
            "kompressor": "Kompressor (h)", "tillsats1": "Tillsats 1 (h)", "tillsats2": "Tillsats 2 (h)", "varmvatten": "Varmvatten (h)", "dagar": "Dygn"})
        st.dataframe(ty.iloc[::-1], hide_index=True, use_container_width=True)
    st.caption(f"Timmarna räknas som skillnaden mellan pumpens räknare dygn för dygn (första dygnet, {pd.Timestamp(df_m.iloc[0]['period']).strftime('%Y-%m')}, saknar differens). Data från 25 mars 2026.")
    render_solar_free()


def page_pump():
    render_refresh_button("pump")
    _ovr = get_overrides()
    smart_pump_mode = _ovr.get("pump_smart_mode", "auto")
    
    st.subheader("🤖 Styrning av Värmepump")
    if row is not None:
        is_pump_online = pd.notna(row.get('outdoor_temp'))
        if is_pump_online:
            st.success("🟢 **Status:** Ansluten till värmepumpen via Husdata.")
        else:
            st.error("🔴 **Status:** OFFLINE! Ingen anslutning till värmepumpen via Husdata.")
    else:
        st.warning("⏳ Väntar på data från Smartbox...")
    is_smart = st.toggle("Aktivera Smart AI-styrning av värmepumpen", value=(smart_pump_mode == "auto"), help="När denna är på styr EnergyWizard temperaturen baserat på elpris och sol. Om den stängs av sköter värmepumpen sig själv.")
    
    if is_smart != (smart_pump_mode == "auto"):
        set_override_db("pump_smart_mode", "auto" if is_smart else "manual")
        st.rerun()
        
    if not is_smart:
        st.warning("⚠️ **Smart AI-styrning är AVAKTIVERAD.** Värmepumpen ignorerar nu elpriser och styrs enbart av sina egna inbyggda inställningar (eller det du tvingar manuellt nedan).")
    else:
        st.success("✅ **Smart AI-styrning är AKTIVERAD.** Systemet optimerar driften dygnet runt.")
        
    # Manuellt driftläge om smart styrning är av
    if not is_smart:
        st.subheader("⚙️ Manuell Driftläge (Direkt styrning av pumpen)")
        current_pump_mode_override = _ovr.get("pump_operating_mode", "auto")
        mode_options = ["Auto (EnergyWizard bestämmer)"] + [f"{k} ({v})" for k, v in PUMP_MODE_MAP.items() if k != 0]
        
        current_selection_index = 0
        if current_pump_mode_override != "auto":
            try:
                ovr_int = int(current_pump_mode_override)
                if ovr_int == 0: ovr_int = 1
                current_selection_index = mode_options.index(f"{ovr_int} ({PUMP_MODE_MAP.get(ovr_int)})")
            except:
                current_selection_index = 0
        
        selected_mode_str = st.selectbox("Välj pumpens driftläge", options=mode_options, index=current_selection_index)

        if selected_mode_str != mode_options[current_selection_index]:
            new_mode_val = "auto" if selected_mode_str == "Auto (EnergyWizard bestämmer)" else selected_mode_str.split(' ')[0]
            set_override_db("pump_operating_mode", new_mode_val)
            st.rerun()

    # ── Sommarläge: hur ska onödig husvärme undvikas på sommaren? ────────────────
    st.subheader("🌞 Sommarläge (undvik onödig husvärme)")
    _summer_opts = {
        "Växla till Endast varmvatten (rekommenderas)": "hot_water",
        "Behåll Auto, styr värmestoppet": "heat_stop",
        "Av – styr manuellt": "off",
    }
    _summer_db_to_label = {v: k for k, v in _summer_opts.items()}
    _cur_summer = _ovr.get("summer_mode_strategy", "hot_water")
    _cur_summer_label = _summer_db_to_label.get(_cur_summer, next(iter(_summer_opts)))
    _sel_summer = st.radio(
        "När 5-dygnsmedlet ute ligger över pumpens värmestopp-tröskel:",
        options=list(_summer_opts.keys()),
        index=list(_summer_opts.keys()).index(_cur_summer_label),
        key="summer_mode_strategy_radio",
        help=("**Endast varmvatten** (läge 4): vattentätt – pumpen kan då fysiskt inte värma huset, men gör fortfarande varmvatten. "
              "**Behåll Auto**: pumpen står kvar i Auto men EnergyWizard sänker Thermias värmestopp så huset inte värms (mindre vattentätt). "
              "**Av**: EnergyWizard rör inte pumpläget – du styr manuellt ovan."),
    )
    if _summer_opts[_sel_summer] != _cur_summer:
        set_override_db("summer_mode_strategy", _summer_opts[_sel_summer])
        st.rerun()
    if row is not None and pd.notna(row.get('operating_mode')):
        _cm = int(row.get('operating_mode'))
        st.caption(f"Pumpen står just nu i läge **{_cm} ({PUMP_MODE_MAP.get(_cm, 'Okänt')})**. "
                   "EnergyWizard växlar automatiskt mellan Auto (vinter) och Endast varmvatten (sommar) enligt vald strategi.")

    st.divider()

    # 🔮 MPC-förvärmning (skuggläge) — systemets självsignal: "nu är jag redo, så här mkt är jag värd"
    st.subheader("🔮 MPC-förvärmning (skuggläge)")
    try:
        _mpc = pd.read_sql(text("SELECT * FROM mpc_backtest ORDER BY id DESC LIMIT 1"), engine)
    except Exception:
        _mpc = pd.DataFrame()
    if _mpc.empty:
        st.info("⏳ Ingen självvalidering körd än — backtesten kör automatiskt veckovis i bakgrunden. Kolla tillbaka om något dygn.")
    else:
        _m = _mpc.iloc[0]
        _heating = bool(_m.get('heating_active'))
        _trained = bool(_m.get('models_trained'))
        _pct = float(_m.get('saving_pct') or 0.0)
        _kryear = float(_m.get('saving_kr_year') or 0.0)
        _days = int(_m.get('days_used') or 0)
        _ts = pd.to_datetime(_m['timestamp']).strftime('%Y-%m-%d')
        _p1, _p2, _p3 = st.columns(3)
        _p1.metric("Uppskattad besparing", f"{max(0.0, _pct):.0f} %")
        _p2.metric("≈ kr/år", f"{max(0.0, _kryear):.0f} kr")
        _p3.metric("Dygn i underlaget", f"{_days}")
        if not _heating:
            st.info(f"💤 **Vilar** — ingen husvärme just nu (sommar), inget att optimera. Vaknar automatiskt när det blir kallt. *(Senast körd {_ts}.)*")
        elif not _trained:
            st.warning(f"📊 **Samlar data** — husvärmen har startat, men de termiska modellerna behöver mer riktig värmedata innan siffran är pålitlig. *(Senast körd {_ts}.)*")
        elif _pct >= 4.0 and _days >= 7:
            st.success(f"✅ **Redo att gå live!** Validerad besparing ~{_pct:.0f} % på {_days} dygns riktig värmedata. **Pinga Claude för att koppla in MPC:n live** (med komfortgolv som skyddsräcke). *(Senast körd {_ts}.)*")
        else:
            st.info(f"🔍 Kör och validerar — nuvarande uppskattning ~{_pct:.0f} % på {_days} dygn. *(Senast körd {_ts}.)*")
    st.caption("MPC:n backtestar sig själv mot din historik varje vecka och **styr ingenting** förrän du bett Claude koppla in den live.")

    st.divider()

    # Hämta senaste legionellakörning
    try:
        with engine.connect() as _conn:
            _leg_row = _conn.execute(text("SELECT MAX(timestamp) FROM sensor_log WHERE water_temp >= 60")).fetchone()
            _last_60 = _leg_row[0] if _leg_row and _leg_row[0] else None
    except:
        _last_60 = None

    if row is not None:
        st.subheader("Aktuell status")
        c1, c2, c3, c4 = st.columns(4)
        _hum2 = row.get('indoor_humidity')
        _hum2_txt = f" · 💧 {_hum2:.0f} %" if _hum2 is not None and not pd.isna(_hum2) else ""
        c1.metric("🌡️ Inne (Median)", f"{row.get('indoor_temp') or 0:.1f} °C",
                  f"Mål: {row.get('target_room_temp') or 0:.1f} °C{_hum2_txt}", delta_color="off")
        c2.metric("🌲 Ute", f"{row.get('outdoor_temp') or 0:.1f} °C")
        
        raw_op_mode_val = row.get('operating_mode')
        mode_key = None
        if pd.notna(raw_op_mode_val):
            raw_int = int(raw_op_mode_val)
            mode_key = int(raw_int / 10) if raw_int >= 10 else raw_int
        c3.metric("⚙️ Driftläge", PUMP_MODE_MAP.get(mode_key, f"Okänt ({raw_op_mode_val})"))
        c4.metric("🌊 Framledning", f"{row.get('forward_temp') or 0:.1f} °C",
                  f"Börvärde: {row.get('calc_forward_temp') or 0:.1f} °C", delta_color="off")

        c5, c6, c7, c8 = st.columns(4)
        c5.metric("🛁 Varmvatten", f"{row.get('water_temp') or 0:.1f} °C",
                  f"Börvärde: {row.get('water_setpoint') or 0:.1f} °C", delta_color="off")

        # Home Assistant Sensor-referens
        entity_ha1 = ha_data.get('sensor.tempsensor_1_temperatur')
        if entity_ha1 and entity_ha1.get('state') not in ('unavailable', 'unknown'):
            try:
                temp_ha1 = float(entity_ha1.get('state'))
                c6.metric("🌡️ Inne (Huvudsensor)", f"{temp_ha1:.1f} °C")
            except:
                c6.metric("🌡️ Inne (Huvudsensor)", "Fel", delta_color="inverse")
        else:
            c6.metric("🌡️ Inne (Huvudsensor)", "Offline", delta_color="inverse")

        pump_heat = row.get('pump_heat_running', 0)
        c7.metric("🔄 Cirkulationspump", "PÅ 🟢" if pump_heat == 1 else "AV ⚪")
        c8.metric("🌊 Retur", f"{row.get('return_temp') or 0:.1f} °C")

        if _last_60 is not None:
            _days_since = (datetime.now(tz=_last_60.tzinfo) - _last_60).days
            st.metric("🦠 Legionella 60°C senast", _last_60.strftime("%Y-%m-%d %H:%M"), f"{_days_since} dagar sedan")

        st.divider()
        st.subheader("Kompressor & Kylkrets")
        k1, k2, k3, k4 = st.columns(4)
        cop_val = row.get('cop')
        meter_w = row.get('avg_w_tot')
        k1.metric("⚙️ Kompressoreffekt", f"{row.get('compressor_power_kw') or 0:.1f} kW", f"COP: {cop_val:.1f}" if cop_val else "COP: –")
        k2.metric("⚡ Elmätare (VP)", f"{meter_w:.0f} W" if meter_w else "–")
        k3.metric("🌡️ Hetgas", f"{row.get('hot_gas_temp') or 0:.1f} °C" if pd.notna(row.get('hot_gas_temp')) else "–")
        k4.metric("🌡️ Brine in/ut", f"{row.get('brine_in_temp') or 0:.1f} / {row.get('brine_out_temp') or 0:.1f} °C")

        st.divider()
        st.subheader("🤖 Varför gör pumpen som den gör?")
        ai_log = row.get("ai_action_log", "")
        pump_ai_texts = [line for line in ai_log.split('\n') if any(k in line for k in ["🏠", "⚙️", "📡", "🚨", "🦠", "💧", "🌳"])]
        reason_text = "\n\n".join(pump_ai_texts) if pump_ai_texts else "Inga specifika beslut loggade just nu."
        st.info(f"**AI:ns bedömning:**\n{reason_text}")

        st.divider()
        st.subheader("📈 Historisk prestanda (Gradminuter)")
        pump_history_hours = st.select_slider("Välj tidsfönster", options=[12, 24, 48, 72], value=24, format_func=lambda x: f"{x} timmar", key="pump_hist_slider")

        try:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE sensor_log ADD COLUMN IF NOT EXISTS degree_minutes NUMERIC"))
                conn.execute(text("ALTER TABLE sensor_log ADD COLUMN IF NOT EXISTS target_room_temp NUMERIC"))
                conn.execute(text("ALTER TABLE sensor_log ADD COLUMN IF NOT EXISTS compressor_running SMALLINT"))

            query = text("""
                SELECT timestamp AT TIME ZONE 'Europe/Stockholm' as "Tid", 
                       degree_minutes as "Gradminuter",
                       target_room_temp as "Börvärde Rum (°C)",
                       outdoor_temp as "Ute (°C)",
                       indoor_temp as "Inne (°C)",
                       water_temp as "Varmvatten (°C)",
                       price as "Elpris (kr/kWh)",
                       compressor_running as "Kompressor PÅ"
                FROM sensor_log 
                WHERE timestamp >= NOW() - (CAST(:hours AS TEXT) || ' hours')::INTERVAL
                ORDER BY timestamp ASC
            """)
            df_hist = pd.read_sql(query, engine, params={"hours": pump_history_hours})

            if not df_hist.empty:
                df_hist["Elpris (öre/kWh)"] = df_hist["Elpris (kr/kWh)"] * 100
                
                # --- Kryssrutor för att välja linjer ---
                tillgangliga_linjer = ["Gradminuter", "Börvärde Rum (°C)", "Ute (°C)", "Inne (°C)", "Varmvatten (°C)", "Elpris (öre/kWh)"]
                valda_linjer = st.multiselect("Välj mätvärden att visa i grafen", options=tillgangliga_linjer, default=["Gradminuter", "Börvärde Rum (°C)", "Ute (°C)", "Elpris (öre/kWh)"])
                
                fig = make_subplots(specs=[[{"secondary_y": True}]])
                
                # Vi lägger Gradminuter och Elpris på Vänster axel (De krockar sällan då Gradminuter är < 0 och Pris är > 0)
                # Temperaturerna lägger vi på Höger axel.
                if "Gradminuter" in valda_linjer: fig.add_trace(go.Scatter(x=df_hist["Tid"], y=df_hist["Gradminuter"], name="Gradminuter", line=dict(color='#3498db', width=2)), secondary_y=False)
                if "Elpris (öre/kWh)" in valda_linjer: fig.add_trace(go.Scatter(x=df_hist["Tid"], y=df_hist["Elpris (öre/kWh)"], name="Elpris (öre/kWh)", mode='lines', line=dict(color='#bdc3c7', width=2, shape='hv')), secondary_y=True)
                
                if "Börvärde Rum (°C)" in valda_linjer: fig.add_trace(go.Scatter(x=df_hist["Tid"], y=df_hist["Börvärde Rum (°C)"], name="Börvärde Rum (°C)", line=dict(color='#d35400', width=2, dash='dot')), secondary_y=True)
                if "Ute (°C)" in valda_linjer: fig.add_trace(go.Scatter(x=df_hist["Tid"], y=df_hist["Ute (°C)"], name="Ute (°C)", line=dict(color='#ff6b6b', width=2, dash='dash')), secondary_y=True)
                if "Inne (°C)" in valda_linjer: fig.add_trace(go.Scatter(x=df_hist["Tid"], y=df_hist["Inne (°C)"], name="Inne (°C)", line=dict(color='#27ae60', width=2)), secondary_y=True)
                if "Varmvatten (°C)" in valda_linjer: fig.add_trace(go.Scatter(x=df_hist["Tid"], y=df_hist["Varmvatten (°C)"], name="Varmvatten (°C)", line=dict(color='#bb8fce', width=2)), secondary_y=True)

                # Skuggade områden för kompressor
                df_hist['Kompressor PÅ'] = df_hist['Kompressor PÅ'].fillna(0).astype(int)
                is_running = False
                start_time = None
                for _, r in df_hist.iterrows():
                    if r['Kompressor PÅ'] == 1 and not is_running:
                        start_time = r['Tid']; is_running = True
                    elif r['Kompressor PÅ'] == 0 and is_running:
                        if start_time: fig.add_vrect(x0=start_time, x1=r['Tid'], fillcolor="#2ecc71", opacity=0.15, layer="below", line_width=0)
                        is_running = False
                if is_running and start_time:
                    fig.add_vrect(x0=start_time, x1=df_hist['Tid'].iloc[-1], fillcolor="#2ecc71", opacity=0.15, layer="below", line_width=0)
            
                fig.add_trace(go.Scatter(x=[None], y=[None], mode='markers', marker=dict(color='rgba(46, 204, 113, 0.5)', symbol='square', size=15), name='Kompressor aktiv'), secondary_y=False)
                fig.update_layout(template="plotly_dark", hovermode="x unified", margin=dict(l=10, r=10, t=40, b=10))
                fig.update_yaxes(title_text="Gradminuter / Öre", secondary_y=False)
                fig.update_yaxes(title_text="Temperatur (°C)", secondary_y=True)
                plot(fig, width="stretch")
        except Exception as e:
            st.error(f"Fel vid rendering av graf: {e}")

        st.divider()
        st.subheader("🎛️ Justera Värden")
        if is_smart:
            with st.form("ai_pump_settings"):
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("**Ekonomi / Normaldrift**")
                    t_cheap = st.number_input("Måltemp Rum (Billig el / Sol)", value=float(settings.get("temp_cheap", 22.0)), step=0.5)
                    t_exp = st.number_input("Måltemp Rum (Dyr el / Sparläge)", value=float(settings.get("temp_expensive", 20.0)), step=0.5)
                    wt_norm = st.number_input("Måltemp Varmvatten (Normalt)", value=float(settings.get("water_target_normal", 50.0)), step=0.5)
                with c2:
                    st.markdown("**Gränsvärden (Ramverk för AI)**")
                    i_max = st.number_input("Maxtak Inne (Mjukt kompressorstopp)", value=float(settings.get("indoor_max", 22.5)), step=0.5, help="Om sol eller billig el värmt huset över denna nivå stänger AI:n av pumpen oavsett elpris.")
                    i_min = st.number_input("Komfortgolv Inne (Tvingande värme)", value=float(settings.get("indoor_min", 19.0)), step=0.5, help="Sjunker huset under detta tvingas pumpen igång, även om elen är jättedyr.")
                    leg_temp = st.number_input("Måltemp Legionellakörning", value=float(settings.get("legionella_temp", 60.0)), step=0.5)
                if st.form_submit_button("💾 Spara AI-målvärden"):
                    save_settings(settings.get("cheap_hours_count", 8), t_cheap, t_exp, i_max, i_min, leg_temp, settings.get("legionella_days", 14), wt_norm)
                    st.rerun()
        else:
            _OPT = ["Auto", "Tvinga PÅ", "Tvinga AV"]
            _OPT_TO_DB = {"Auto": "auto", "Tvinga PÅ": "on", "Tvinga AV": "off"}
            _DB_TO_OPT = {"auto": "Auto", "on": "Tvinga PÅ", "off": "Tvinga AV"}
            _oc1, _oc2 = st.columns(2)
            with _oc1:
                _sel_heat = st.radio("♨️ Värme", _OPT, index=_OPT.index(_DB_TO_OPT.get(_ovr.get("heat", "auto"), "Auto")), key="ov_heat_pump_tab")
                if _OPT_TO_DB[_sel_heat] != _ovr.get("heat"):
                    set_override_db("heat", _OPT_TO_DB[_sel_heat]); st.rerun()
            with _oc2:
                _sel_hw = st.radio("🚿 Varmvatten", _OPT, index=_OPT.index(_DB_TO_OPT.get(_ovr.get("hotwater", "auto"), "Auto")), key="ov_hotwater_pump_tab")
                if _OPT_TO_DB[_sel_hw] != _ovr.get("hotwater"):
                    set_override_db("hotwater", _OPT_TO_DB[_sel_hw]); st.rerun()
    else:
        st.info("Väntar på data från Smartbox...")
    render_pump_runtime()

# ══════════════════════════════════════════════════════════════════════════════
# 🤖 ROBOTGRÄSKLIPPARE
# ══════════════════════════════════════════════════════════════════════════════
def render_mower_scene(scene: str) -> str:
    """Självständig animerad HTML/CSS-scen för klipparens status.
    Ritas helt med CSS – kräver inga bildfiler (assets)."""
    css = """
    <style>
    .ewmower-box{position:relative;width:100%;height:175px;border-radius:14px;overflow:hidden;
        font-size:34px;box-shadow:inset 0 0 0 1px rgba(255,255,255,.10);}
    .ewmower-lawn{background:repeating-linear-gradient(90deg,#2e7d32 0 14px,#388e3c 14px 28px);}
    .ewmower-dock{background:linear-gradient(180deg,#26343f,#1b242c);}
    .ewmower-off{background:linear-gradient(180deg,#3a3f44,#23272b);filter:grayscale(.55);}
    .ewmower-ground{position:absolute;left:0;right:0;bottom:0;height:16px;background:rgba(0,0,0,.28);}
    .ewmower-robot{position:absolute;bottom:16px;}
    .ewmower-label{position:absolute;top:8px;left:12px;font-size:12px;font-weight:600;
        color:rgba(255,255,255,.75);letter-spacing:1px;}
    .ewmower-station{position:absolute;bottom:16px;right:20px;font-size:42px;}
    .ewmower-bolt{position:absolute;top:16px;right:20px;animation:ewmower-pulse 1.2s ease-in-out infinite;}
    .ewmower-zzz{position:absolute;top:24px;right:34px;font-size:20px;color:#b0bec5;
        animation:ewmower-pulse 2.4s ease-in-out infinite;}
    .ewmower-batt{position:absolute;top:22px;left:22px;width:26px;height:46px;
        border:3px solid #cfd8dc;border-radius:5px;}
    .ewmower-batt:before{content:'';position:absolute;top:-8px;left:6px;width:11px;height:5px;
        background:#cfd8dc;border-radius:2px;}
    .ewmower-batt i{position:absolute;left:2px;right:2px;bottom:2px;background:#4caf50;border-radius:2px;
        animation:ewmower-fill 2.5s ease-in-out infinite alternate;}
    .ewmower-mowing .ewmower-robot{animation:ewmower-drive 6s linear infinite;}
    .ewmower-idle .ewmower-robot{animation:ewmower-bob 3s ease-in-out infinite;}
    @keyframes ewmower-drive{0%{left:8%;transform:scaleX(1)}48%{left:78%;transform:scaleX(1)}
        50%{left:78%;transform:scaleX(-1)}98%{left:8%;transform:scaleX(-1)}100%{left:8%;transform:scaleX(1)}}
    @keyframes ewmower-bob{0%,100%{transform:translateY(0)}50%{transform:translateY(-4px)}}
    @keyframes ewmower-pulse{0%,100%{opacity:.35;transform:scale(.9)}50%{opacity:1;transform:scale(1.15)}}
    @keyframes ewmower-fill{0%{height:8%}100%{height:90%}}
    </style>"""
    scenes = {
        "mowing": """<div class="ewmower-box ewmower-lawn ewmower-mowing">
            <div class="ewmower-label">KLIPPER</div><div class="ewmower-ground"></div>
            <div class="ewmower-robot">🤖</div></div>""",
        "charging": """<div class="ewmower-box ewmower-dock">
            <div class="ewmower-label">LADDAR</div><div class="ewmower-batt"><i></i></div>
            <div class="ewmower-bolt">⚡</div><div class="ewmower-ground"></div>
            <div class="ewmower-robot" style="left:46%;">🤖</div><div class="ewmower-station">🏠</div></div>""",
        "off": """<div class="ewmower-box ewmower-off">
            <div class="ewmower-label">STRÖM AV</div><div class="ewmower-ground"></div>
            <div class="ewmower-robot" style="left:46%;opacity:.6;">🤖</div>
            <div class="ewmower-bolt" style="animation:none;opacity:.8;">⛔</div></div>""",
        "idle": """<div class="ewmower-box ewmower-dock ewmower-idle">
            <div class="ewmower-label">VILAR</div><div class="ewmower-zzz">z z z</div>
            <div class="ewmower-ground"></div>
            <div class="ewmower-robot" style="left:46%;">🤖</div><div class="ewmower-station">🏠</div></div>""",
    }
    html = css + scenes.get(scene, scenes["idle"])
    # VIKTIGT: Streamlit/markdown tolkar rader som inleds med 4+ blanksteg som ett
    # kodblock och visar då rå HTML som text. Ta bort all indragning så att HTML:en
    # renderas korrekt (allt sammanfogas till en enda rad).
    return "".join(line.strip() for line in html.splitlines())


def page_mower():
    render_refresh_button("mower")
    st.subheader("🤖 Robotgräsklippare")

    mower_power  = safe_float("sensor.shellyb1_effekt")
    mower_is_on  = ha_state("switch.shellyb1") == "on"
    mower_energy = safe_float("sensor.shellyb1_energi")

    # Statusen bestäms av backend (smartbox/lawnmower.py) och loggas i sensor_log.
    mower_status_db = row.get("mower_status") if row is not None else None
    if mower_status_db not in ("Klipper", "Laddar", "Vilar", "Avstängd", "Okänd"):
        mower_status_db = "Avstängd" if not mower_is_on else "Okänd"

    status_map = {
        "Klipper":  ("Klipper", "Klipparen är ute på gräsmattan.", "mowing"),
        "Laddar":   ("Laddar", "Klipparen står i stationen och laddar.", "charging"),
        "Vilar":    ("Vilar", "Klipparen är fulladdad och vilar i stationen.", "idle"),
        "Avstängd": ("Avstängd", "Strömmen till laddstationen är avstängd.", "off"),
        "Okänd":    ("Okänd", "Väntar på data från smart plug…", "idle"),
    }
    status_text, status_desc, scene = status_map[mower_status_db]

    # --- Visuell status (animerad CSS-scen) ---
    with st.container(border=True):
        m_c1, m_c2 = st.columns([1, 1])
        with m_c1:
            st.markdown(render_mower_scene(scene), unsafe_allow_html=True)
        with m_c2:
            st.markdown(f"### Status: {status_text}")
            st.caption(status_desc)
            st.metric("Live-förbrukning", f"{mower_power:.1f} W")
            st.metric("Ström till laddstation", "PÅ 🟢" if mower_is_on else "AV ⚫")
            st.metric("Total energi", f"{mower_energy:.3f} kWh")

    st.divider()

    st.markdown("#### 🧠 Träna AI:n - Vad gör klipparen just nu?")
    st.caption("Hjälp systemet att lära sig genom att manuellt logga klipparens status. Datan sparas i en databas för framtida maskininlärning.")

    with st.form("mower_activity_log_form"):
        activity = st.radio("Välj aktuell aktivitet:", ("Klipper", "Laddar", "Vilar"), horizontal=True)
        
        submitted = st.form_submit_button("💾 Spara observation")
        if submitted:
            try:
                with SessionLocal() as db:
                    new_activity = MowerActivity(
                        power_w=mower_power,
                        energy_kwh=mower_energy,
                        activity_label=activity
                    )
                    db.add(new_activity)
                    db.commit()
                st.success(f"✅ Observation sparad: '{activity}' vid {mower_power:.1f}W.")
            except Exception as e:
                st.error(f"Kunde inte spara observation: {e}")

    st.divider()

    # --- Väderstyrning ---
    st.markdown("#### 🌦️ Väderstyrning")
    st.caption(
        "När väderstyrning är PÅ stängs strömmen till laddstationen av automatiskt vid regn "
        "eller åska – men bara om klipparen står i stationen. Strömmen slås på igen när ovädret "
        "passerat. (Säkerhetsreglerna stänger aldrig av medan klipparen är ute och klipper.)"
    )
    def _mower_ov_bool(key, default=True):
        # get_ov_bool finns bara i Aviseringsfliken; läs override direkt här.
        try:
            with engine.connect() as _c:
                _r = _c.execute(text("SELECT mode FROM overrides WHERE device = :d"), {"d": key}).fetchone()
            if not _r or _r[0] in (None, "auto"):
                return default
            return _r[0] == "true"
        except Exception:
            return default

    weather_ctrl_on = _mower_ov_bool("mower_weather_control", True)
    toggled_wctrl = st.toggle(
        "Aktivera väderstyrning (regn/åska)", value=weather_ctrl_on, key="mower_weather_ctrl"
    )
    if toggled_wctrl != weather_ctrl_on:
        set_override_db("mower_weather_control", str(toggled_wctrl).lower())
        st.rerun()

    rain_ctrl_on = _mower_ov_bool("mower_rain_control", True)
    toggled_rain = st.toggle(
        "🌧️ Regnreglage – parkera klipparen vid regn", value=rain_ctrl_on, key="mower_rain_ctrl",
        help="Av = regn ignoreras (klipparen körs i regn). Åskskyddet styrs fortfarande av väderstyrningen ovan."
    )
    if toggled_rain != rain_ctrl_on:
        set_override_db("mower_rain_control", str(toggled_rain).lower())
        st.rerun()

    if not toggled_wctrl:
        st.info("⚙️ Väderstyrning är **AV** – klipparen körs oavsett väder.")
    else:
        is_raining = weather.is_raining_soon() and toggled_rain
        is_thunder = weather.is_thundering_soon()
        if is_thunder:
            st.warning("⛈️ **Åska väntas!** Strömmen stängs av om klipparen står i stationen, för att skydda elektroniken.")
        elif is_raining:
            st.warning("🌧️ **Regn detekterat!** Strömmen stängs av om klipparen står i stationen, för att skydda den.")
        else:
            st.success("☀️ **Uppehåll.** Klipparen tillåts att köra som normalt.")

    st.divider()

    # --- Manuell kontroll & Inställningar ---
    with st.expander("🔧 Manuell kontroll & Inställningar"):
        st.markdown("##### Manuell strömbrytare")
        st.caption("Använd denna för att manuellt slå av/på strömmen till laddstationen. Notera att säkerhetsreglerna kan komma att slå på strömmen igen automatiskt.")
        
        if st.button("Tvinga PÅ ström", key="mower_on_btn", disabled=mower_is_on):
            if homeassistant.toggle_mower_plug(True):
                st.success("✅ Strömmen är påslagen!")
                time.sleep(1); st.rerun()
            else:
                st.error("Kunde inte slå på strömmen.")

        if st.button("Tvinga AV ström", key="mower_off_btn", type="primary", disabled=not mower_is_on):
            mowing_threshold = settings.get("mower_mowing_threshold_w", 3.2)
            # Säkerhetsspärr: blockera om backend säger "Klipper" ELLER om live-effekten
            # ser ut som klippning (plugg på men förbrukning under klippgränsen).
            is_mowing_live = mower_is_on and mower_power < mowing_threshold
            if mower_status_db == "Klipper" or is_mowing_live:
                st.error("🚫 SÄKERHETSSPÄRR: Kan inte stänga av strömmen när klipparen är ute och klipper!")
            elif homeassistant.toggle_mower_plug(False):
                st.success("✅ Strömmen är avstängd!")
                time.sleep(1); st.rerun()
            else:
                st.error("Kunde inte stänga av strömmen.")

        st.divider()
        st.markdown("##### Justera gränsvärden för status")
        _x = float(settings.get("mower_mowing_threshold_w", 3.2))
        _y = float(settings.get("mower_charging_threshold_w", 10.0))
        st.markdown(
            "Effekten avgör vilket av **tre** lägen klipparen är i. Du justerar två gränser, "
            "**X** (klippgräns) och **Y** (laddgräns):\n\n"
            f"- 🤖 **Klipper** – under **{_x:.1f} W** (ute på gräsmattan)\n"
            f"- 💤 **Vilar** – mellan **{_x:.1f}** och **{_y:.1f} W** (fulladdad i stationen)\n"
            f"- 🔌 **Laddar** – över **{_y:.1f} W**"
        )
        with st.form("mower_threshold_form"):
            m_thresh_1, m_thresh_2 = st.columns(2)
            with m_thresh_1:
                new_mowing_w = st.number_input(
                    "X – Klippgräns (W): under = Klipper",
                    min_value=0.0, max_value=20.0, step=0.1,
                    value=_x,
                    help="UNDER detta värde antas klipparen vara ute och klippa. Mellan X och Y = Vilar."
                )
            with m_thresh_2:
                new_charging_w = st.number_input(
                    "Y – Laddgräns (W): över = Laddar",
                    min_value=1.0, max_value=50.0, step=0.5,
                    value=_y,
                    help="ÖVER detta värde antas klipparen ladda. Mellan X och Y = Vilar."
                )
            st.caption("Spannet **mellan X och Y** (gråzonen) tolkas som 💤 **Vilar**.")

            if st.form_submit_button("💾 Spara gränsvärden"):
                if new_mowing_w >= new_charging_w:
                    st.error("Klippgränsen (X) måste vara LÄGRE än laddgränsen (Y) – annars finns inget Vilar-spann.")
                else:
                    try:
                        with engine.begin() as conn:
                            conn.execute(text("""
                                UPDATE system_settings
                                SET mower_mowing_threshold_w = :mow, mower_charging_threshold_w = :charge
                                WHERE id = 1
                            """), {"mow": new_mowing_w, "charge": new_charging_w})
                        st.success("✅ Gränsvärden sparade!")
                        time.sleep(1); st.rerun()
                    except Exception as e:
                        st.error(f"Kunde inte spara: {e}")



# ══════════════════════════════════════════════════════════════════════════════
# ☀️ SOLCELLER
# ══════════════════════════════════════════════════════════════════════════════
def page_solar():
    render_refresh_button("solar")
    st.subheader("☀️ SolarEdge Växelriktare & Styrning")

    _ovr = get_overrides()
    ai_limit_active = _ovr.get("ai_solar_limit_active", "false").lower() == "true"
    if ai_limit_active:
        st.warning("🤖 **AI-styrning aktiv!** Produktionen begränsas just nu av den smarta prisgränsen för att undvika förlustaffärer.")
    
    if current_live_price is not None:
        # Beräkning för Jönköping Energi
        buy_cost = full_buy_cost(current_live_price)
        sell_value = full_sell_income(current_live_price)
        
        st.info(
            f"💸 **ELPRIS JUST NU:**\n\n"
            f"🛒 **Köpa:** {buy_cost:.2f} kr/kWh *(Spot {current_live_price:.2f} kr + Jönköping Energi överföring, skatt & moms)*\n\n"
            f"💰 **Sälja:** ~{sell_value:.2f} kr/kWh *(Spot)*"
        )
    else:
        st.info("💸 Elpris: Kan inte hämtas just nu.")

    SOLAREDGE_STATUS_MAP = {
        "I_STATUS_OFF": "Avstängd",
        "I_STATUS_SLEEPING": "Viloläge (Natt)",
        "I_STATUS_WAKEUP": "Startar upp",
        "I_STATUS_MPPT": "Producerar",
        "I_STATUS_THROTTLED": "Begränsad",
        "I_STATUS_SHUTTING_DOWN": "Stänger av",
        "I_STATUS_FAULT": "Fel",
        "I_STATUS_STANDBY": "Standby"
    }
    sc1, sc2, sc3, sc4 = st.columns(4)
    sc1.metric("☀️ Aktuell Effekt", f"{safe_float('sensor.solaredge_aktuell_effekt') / 1000:.2f} kW")
    sc2.metric("📅 Produktion idag", f"{ha_state('sensor.solaredge_el_i_dag')} kWh")
    sc3.metric("🔋 DC Effekt", f"{safe_float('sensor.solaredge_i1_dc_power') / 1000:.2f} kW")
    
    raw_status = ha_state('sensor.solaredge_i1_status')
    friendly_status = SOLAREDGE_STATUS_MAP.get(raw_status, raw_status)
    sc4.metric("📈 Status", friendly_status)

    st.divider()
    netto_live = get_live_net_power()
    label = "📤 Säljer till nätet" if netto_live < 0 else "📥 Köper från nätet"
    st.metric("🏠 Husets Nettoförbrukning (Live)", f"{abs(netto_live) / 1000:.2f} kW", label, delta_color="off")
    st.divider()

    st.subheader("Smart Exportbegränsning")
    st.caption("Sätt ett spotpris-golv. Om priset går under detta värde (och hela kaskaden med hus/ev/spa är full), kommer systemet att strypa exporten.")
    
    current_limit_price = float(_ovr.get("solar_export_price_limit", -1.0))

    new_limit_price = st.number_input("Begränsa export om spotpris är under (kr/kWh)", 
                                      value=current_limit_price, 
                                      min_value=-1.0, 
                                      max_value=5.0, 
                                      step=0.05,
                                      format="%.2f",
                                      key="solar_limit_price_input")
    
    if new_limit_price != current_limit_price:
        set_override_db("solar_export_price_limit", str(new_limit_price))
        st.success(f"✅ Prisgräns för export uppdaterad till {new_limit_price:.2f} kr/kWh.")
        st.rerun()

    notify_solar_limit_val_solar = _ovr.get("notify_solar_limit", "true").lower() == "true"
    new_notify_solar_limit_val_solar = st.toggle("🔔 Avisera vid start/stopp av begränsning", value=notify_solar_limit_val_solar, key="notify_solar_solar_tab")
    if new_notify_solar_limit_val_solar != notify_solar_limit_val_solar:
        set_override_db("notify_solar_limit", str(new_notify_solar_limit_val_solar).lower())
        st.rerun()

    st.divider()
    
    raw_limit_state = ha_state("number.solaredge_modbus_active_power_limit", None)
    current_limit = None if raw_limit_state in ("–", "unavailable", "unknown", None) else safe_float("number.solaredge_modbus_active_power_limit")
    
    if current_limit is None:
        st.warning("⚠️ **SolarEdge Limit Control (Modbus) är offline i Home Assistant!** Systemet läser av produktionen via backup-integrationen och utgår från 100% tills kommunikationen är tillbaka.")
    elif current_live_price is not None and current_live_price < 0:
        st.subheader("🤖 AI Styr Exportbegränsning (Minuspris)")
        st.info("AI:n (PI-regulatorn) justerar just nu produktionsgränsen varje minut för att nå 0W nettoexport eftersom spotpriset är under 0 kr.")
        st.metric("Nuvarande effektgräns", f"{current_limit:.0f} %")
        st.progress(int(current_limit if current_limit is not None else 0))
    else:
        st.subheader("🎛️ Manuell Exportbegränsning (Limit Control)")
        if current_limit is not None and current_limit > 0 and current_limit < 100:
            st.warning(f"⚠️ **Manuell begränsning aktiv!** Växelriktaren är strypt till **{current_limit:.0f} %**.")
        elif current_limit == 100:
            st.success("🟢 **Ingen begränsning aktiv.** Växelriktaren går på **100 %** (Maximal produktion).")
        elif current_limit is not None and current_limit == 0:
            st.error("🛑 **Produktionen är helt avstängd (0 %)!**")
        
        with st.form("limit_form"):
            new_limit = st.slider("Ställ in Active Power Limit (%)", min_value=0, max_value=100, value=int(current_limit) if current_limit is not None else 100, step=1)
            st.caption("0 % stänger av produktionen helt. 100 % är normal drift.")
            st.info("💡 **Observera:** Eftersom elpriset är positivt just nu låter GPM-motorn solcellerna producera maximalt. Om du sparar ett manuellt värde här kommer AI:n att skriva över det till 100% inom 60 sekunder. (Reglaget är mest användbart om du stängt av Smartboxen).")
            
            if st.form_submit_button("💾 Uppdatera gräns i SolarEdge"):
                try:
                    homeassistant.set_solaredge_limit(new_limit)
                    st.success(f"✅ Skickade kommando att sätta gränsen till {new_limit} %!")
                    time.sleep(1)
                    st.rerun()
                except Exception as e:
                    st.error(f"Kunde inte skicka kommando: {e}")

    st.divider()
    with st.expander("Visa alla SolarEdge-entiteter"):
        se_entities = [v for k, v in ha_data.items() if "solaredge" in k.lower()]
        if se_entities:
            df_se = pd.DataFrame([{"Entitet": v["entity_id"], "Namn": v.get("attributes", {}).get("friendly_name", ""), "Status": v["state"]} for v in se_entities])
            st.dataframe(df_se, width="stretch")
        else:
            st.info("Hittade inga SolarEdge-entiteter.")

# ══════════════════════════════════════════════════════════════════════════════
# 🛁 SPABAD
# ══════════════════════════════════════════════════════════════════════════════
def page_spa():
    render_refresh_button("spa")
    st.subheader("🛁 Gecko Spabad (Live från HA)")

    # 🔌 Ny 3-fas-effektmätare på spabadet (Shelly) — verklig effekt per fas + exakt kostnad.
    with st.container(border=True):
        st.markdown("**🔌 Effektmätare (3-fas Shelly)**")
        _pa = abs(safe_float('sensor.spabad_phase_a_effekt') or 0.0)
        _pb = abs(safe_float('sensor.spabad_phase_b_effekt') or 0.0)
        _pc = abs(safe_float('sensor.spabad_phase_c_effekt') or 0.0)
        _sc = st.columns(4)
        _sc[0].metric("Total", f"{(_pa+_pb+_pc)/1000:.2f} kW")
        _sc[1].metric("Fas A", f"{_pa:.0f} W")
        _sc[2].metric("Fas B", f"{_pb:.0f} W")
        _sc[3].metric("Fas C", f"{_pc:.0f} W")
        try:
            _spac = pd.read_sql(text("""
                SELECT COALESCE(SUM(spa_power_w/1000.0/60.0),0) AS kwh,
                       COALESCE(SUM(spa_power_w/1000.0/60.0 * price),0) AS spot_kr
                FROM sensor_log
                WHERE timestamp AT TIME ZONE 'Europe/Stockholm' >= date_trunc('day', NOW() AT TIME ZONE 'Europe/Stockholm')
                  AND spa_power_w IS NOT NULL AND price IS NOT NULL
            """), engine)
            if not _spac.empty:
                _kwh = float(_spac.iloc[0]['kwh'] or 0.0)
                _kr = float(_spac.iloc[0]['spot_kr'] or 0.0) * 1.25 + _kwh * 0.62675  # full köpkostnad
                _e1, _e2 = st.columns(2)
                _e1.metric("⚡ Idag: energi", f"{_kwh:.2f} kWh")
                _e2.metric("💸 Idag: kostnad", f"{_kr:.2f} kr")
        except Exception:
            st.caption("Exakt kostnad visas när mätaren loggat en stund.")
        st.caption("Verklig per-fas-effekt från spabadets nya Shelly-mätare (tecknet vänt – visar förbrukning).")
    st.divider()

    # 💰 Spa-ekonomi: kostnad & förbrukning för att ha spabadet igång
    st.subheader("💰 Spa-ekonomi")
    st.caption("Vad det kostar att ha spabadet igång. **Faktisk** = med solöverskott som ibland täcker badet; **Utan solceller** = allt köpt från nätet till fullpris.")
    _CASE = "CASE WHEN net_power >= 0 THEN price*1.25+0.62675 ELSE price+0.02125 END"
    try:
        _spam = pd.read_sql(text(f"""
            SELECT to_char(date_trunc('month', timestamp AT TIME ZONE 'Europe/Stockholm'),'YYYY-MM') AS man,
                   COALESCE(SUM(spa_power_w/1000.0/60.0),0) AS kwh,
                   COALESCE(SUM(spa_power_w/1000.0/60.0 * ({_CASE})),0) AS faktisk_kr,
                   COALESCE(SUM(spa_power_w/1000.0/60.0 * (price*1.25+0.62675)),0) AS utan_sol_kr
            FROM sensor_log WHERE spa_power_w IS NOT NULL AND price IS NOT NULL
            GROUP BY 1 ORDER BY 1
        """), engine)
        _spatoday = pd.read_sql(text(f"""
            SELECT COALESCE(SUM(spa_power_w/1000.0/60.0),0) AS kwh,
                   COALESCE(SUM(spa_power_w/1000.0/60.0 * ({_CASE})),0) AS faktisk_kr,
                   COALESCE(SUM(spa_power_w/1000.0/60.0 * (price*1.25+0.62675)),0) AS utan_sol_kr
            FROM sensor_log
            WHERE timestamp AT TIME ZONE 'Europe/Stockholm' >= date_trunc('day', NOW() AT TIME ZONE 'Europe/Stockholm')
              AND spa_power_w IS NOT NULL AND price IS NOT NULL
        """), engine)
    except Exception:
        _spam = pd.DataFrame(); _spatoday = pd.DataFrame()
    if _spam.empty:
        st.info("Samlar data — spa-ekonomin visas när mätaren loggat en stund.")
    else:
        _yr = datetime.now(SWE_TZ).strftime('%Y'); _cm = datetime.now(SWE_TZ).strftime('%Y-%m')
        _t = _spatoday.iloc[0] if not _spatoday.empty else {'kwh':0,'faktisk_kr':0,'utan_sol_kr':0}
        _mr = _spam[_spam['man']==_cm]; _yrdf = _spam[_spam['man'].str.startswith(_yr)]
        def _agg(kwh,f,u): return {'Förbrukning (kWh)':round(float(kwh),1),'Faktisk (kr)':round(float(f),0),'Utan solceller (kr)':round(float(u),0),'Solnytta (kr)':round(float(u-f),0)}
        _summary = pd.DataFrame([
            {'Period':'📅 Idag', **_agg(_t['kwh'],_t['faktisk_kr'],_t['utan_sol_kr'])},
            {'Period':'📆 Denna månad', **_agg(*( (_mr.iloc[0]['kwh'],_mr.iloc[0]['faktisk_kr'],_mr.iloc[0]['utan_sol_kr']) if not _mr.empty else (0,0,0)))},
            {'Period':'🗓️ I år', **_agg(_yrdf['kwh'].sum(),_yrdf['faktisk_kr'].sum(),_yrdf['utan_sol_kr'].sum())},
            {'Period':'♾️ Någonsin', **_agg(_spam['kwh'].sum(),_spam['faktisk_kr'].sum(),_spam['utan_sol_kr'].sum())},
        ])
        st.dataframe(_summary, width="stretch", hide_index=True)
        st.markdown("**Varje månad:**")
        _disp = _spam.rename(columns={'man':'Månad','kwh':'Förbrukning (kWh)','faktisk_kr':'Faktisk (kr)','utan_sol_kr':'Utan solceller (kr)'})
        _disp['Solnytta (kr)'] = (_disp['Utan solceller (kr)'] - _disp['Faktisk (kr)']).round(0)
        for _c in ['Förbrukning (kWh)','Faktisk (kr)','Utan solceller (kr)']:
            _disp[_c] = _disp[_c].round(1 if 'kWh' in _c else 0)
        st.dataframe(_disp, width="stretch", hide_index=True)
    st.divider()

    # 🧠 Fas-inlärning: vad driver varje fas? (korrelerar Gecko-aktivitet mot per-fas-effekt)
    st.subheader("🧠 Vad gör varje fas? (inlärt)")
    try:
        _pl = pd.read_sql(text("SELECT * FROM spa_phase_log"), engine)
    except Exception:
        _pl = pd.DataFrame()
    _acts = [('heating','🔥 Värmare'),('pump1','🌀 Pump 1 (jets)'),('blower','💨 Blåsare'),
             ('waterfall','⛲ Vattenfall'),('circ_pump','♻️ Cirkulationspump'),('lights','💡 Belysning'),('ozone','🫧 Ozon')]
    if _pl.empty or len(_pl) < 30:
        st.info(f"🧠 **Lär sig fortfarande** — har {len(_pl)} minuters data. När spabadets funktioner slagit på/av några gånger kan jag säga vilken fas som driver vad, och hur mycket varje drar.")
    else:
        _rows=[]
        for _col,_label in _acts:
            if _col not in _pl.columns: continue
            _on=_pl[_pl[_col]==True]; _off=_pl[_pl[_col]==False]
            if len(_on) < 5: continue
            _best=None; _bd=0.0
            for _ph,_phn in [('phase_a_w','A'),('phase_b_w','B'),('phase_c_w','C')]:
                _d=(_on[_ph].mean() or 0) - (_off[_ph].mean() or 0)
                if _d > _bd: _bd=_d; _best=_phn
            if _best and _bd > 20:
                _rows.append({'Funktion':_label,'Drivs av fas':_best,'Effekt när på':f"{_bd:.0f} W",'Datapunkter':len(_on)})
        if _rows:
            st.dataframe(pd.DataFrame(_rows), width="stretch", hide_index=True)
            st.caption("Inlärt genom att jämföra per-fas-effekten när varje funktion är PÅ mot när den är AV.")
        else:
            st.info("🧠 Har data men ännu inga tydliga fas-samband — behöver fler på/av-växlingar av funktionerna.")
    st.divider()

    st.markdown("### 🎛️ Manuell Överstyrning (Högst Prioritet)")
    with st.container(border=True):
        current_force = settings.get("spa_force_heat", False)
        new_force = st.toggle("🔥 Tvångsvärme (Värmer till Maxtemp och ignorerar ALLT fram till 23:00)", value=current_force)
        if new_force != current_force:
            try:
                with engine.begin() as conn:
                    if new_force:
                        conn.execute(text("UPDATE system_settings SET spa_force_heat = TRUE, spa_schedule_enabled = FALSE WHERE id = 1"))
                    else:
                        conn.execute(text("UPDATE system_settings SET spa_force_heat = FALSE WHERE id = 1"))
                
                fetch_ha_data.clear()
                st.success("✅ Tvångsvärme uppdaterad! GPM-motorn aktiverar värmaren inom 60 sekunder.")
                
                st.rerun()
            except Exception as e:
                st.error(f"Fel: {e}")
                
    st.markdown("### 💤 Economy Mode (Energisparläge)")
    eco_c1, eco_c2 = st.columns(2)
    eco = ha_state('switch.spabad_economy_mode')
    eco_ovr = get_overrides().get("spa_force_eco", "auto")
    
    with eco_c1:
        with st.container(border=True):
            st.markdown("#### 👤 Manuell Styrning")
            new_eco = st.toggle("Tvinga Economy Mode PÅ", value=(eco_ovr == "on"), help="Ignorerar AI och tvingar badet att svalna till Lågtemp.")
            if new_eco != (eco_ovr == "on"):
                set_override_db("spa_force_eco", "on" if new_eco else "auto")
                
                if new_eco:
                    try:
                        with engine.begin() as conn:
                            conn.execute(text("UPDATE system_settings SET spa_force_heat = FALSE, spa_schedule_enabled = FALSE WHERE id = 1"))
                    except Exception:
                        pass

                fetch_ha_data.clear()
                st.success("✅ Economy mode uppdaterat! GPM-motorn justerar badet inom 60 sekunder.")
                st.rerun()

    with eco_c2:
        with st.container(border=True):
            st.markdown("#### 🤖 AI-Motorns Status")
            if eco_ovr == "on":
                st.info("✋ Överstyrd av manuell knapp.")
            else:
                ai_log = row.get("ai_action_log", "") if row is not None else ""
                spa_lines = [line for line in ai_log.split('\n') if "🛁" in line]
                spa_ai_text = "\n".join(spa_lines)
                is_ai_eco = "Economy Mode" in spa_ai_text or "sänker badet" in spa_ai_text.lower() or "dvala" in spa_ai_text.lower() or "schema aktivt -> avvaktar" in spa_ai_text.lower()
                
                if is_ai_eco:
                    st.warning("🟢 **PÅ** (Aktiverad av AI)")
                    st.caption(f"**Orsak:** {spa_ai_text}")
                    st.caption("Avaktiveras automatiskt när elpriset sjunker, solöverskott uppstår eller ett schemalagt uppvärmningsfönster startar.")
                else:
                    st.success("⚪ **AV** (Badet värms normalt)")
                    if spa_ai_text:
                        st.caption(f"**Status:** {spa_ai_text}")

    st.divider()

    # Hämta senast max temp
    _last_max_temp_time = None
    try:
        with engine.connect() as _conn:
            # Vi kollar när tempen var >= spabadets maxtemp minus en liten marginal (0.2)
            _max_row = _conn.execute(text("""
                SELECT MAX(timestamp) AT TIME ZONE 'Europe/Stockholm'
                FROM sensor_log
                WHERE spa_temp >= (SELECT spa_max_temp FROM system_settings WHERE id = 1) - 0.2
            """)).fetchone()
            _last_max_temp_time = _max_row[0] if _max_row and _max_row[0] else None
    except Exception:
        pass
        
    current_target_dt = settings.get("spa_target_datetime")
    current_target_temp = settings.get("spa_target_temp")
    schedule_enabled = settings.get("spa_schedule_enabled", False)

    if current_target_dt:
        if current_target_dt.tzinfo is None:
            current_target_dt = current_target_dt.replace(tzinfo=SWE_TZ)
        else:
            current_target_dt = current_target_dt.astimezone(SWE_TZ)

    # Förbered ML-variabler och generera planen ifall ett schema är aktivt
    try:
        curr_spa_temp = float(ha_state('sensor.spa_malmgatan_34_current_temperature', 38.0))
    except Exception:
        curr_spa_temp = 38.0
        
    out_temp = row.get('outdoor_temp', 0) if row is not None else 0
    model_intercept, model_slope_out, model_slope_spa = learning.get_heating_rate_model()
    cooling_k, _ = learning.get_cooling_rate_model()
    spa_max = float(settings.get("spa_max_temp", 40.0))
    spa_normal = float(settings.get("spa_normal_temp", 34.0))

    df_plan = None
    if schedule_enabled and current_target_dt and current_target_dt > datetime.now(SWE_TZ):
        df_plan = pred.get_spa_schedule_plan(datetime.now(SWE_TZ), current_target_dt, curr_spa_temp, model_intercept, model_slope_out, model_slope_spa, cooling_k, float(current_target_temp or 38.0), spa_max, spa_normal, out_temp, float(settings.get("spa_low_temp", 15.0)))
    spa_plan_df_for_forecast = df_plan # Spara för prognos-fliken så vi slipper räkna ut detta igen!

    # Förklara AI:ns beslut för spabadet
    ai_log = row.get("ai_action_log", "") if row is not None else ""
    
    # HÄMTA BESLUT DIREKT FRÅN GPM.PY
    spa_ai_texts = [line for line in ai_log.split('\n') if "🛁" in line]
    
    heater_attr = ha_attribute('climate.spabad_heater', 'hvac_action', default=None)
    if not heater_attr: heater_attr = ha_state('climate.spabad_heater', default=None)
    if not heater_attr: heater_attr = ha_state('water_heater.spa_malmgatan_34_heater', default='–')
    heater_state = str(heater_attr).lower()
    
    if spa_ai_texts:
        spa_status_text = "\n\n".join(spa_ai_texts)
    else:
        spa_status_text = "Ingen loggdata från GPM tillgänglig just nu. Väntar på nästa minut-uppdatering..."

    st.info(f"**🧠 AI-Styrning just nu:**\n\n{spa_status_text}")
    
    # Solprognos (Overtemp)
    try:
        df_w_spa = pd.read_sql(text("SELECT timestamp AT TIME ZONE 'Europe/Stockholm' AS t, cloud_cover FROM weather_forecast WHERE timestamp >= NOW() AND timestamp < NOW() + INTERVAL '24 hours' ORDER BY timestamp ASC"), engine)
        if not df_w_spa.empty:
                df_w_spa['t'] = pd.to_datetime(df_w_spa['t'])
                _spa_solar_prof = learning.get_solar_profile()
                df_w_spa['sol_w'] = df_w_spa.apply(lambda r: pred.get_smart_solar_w(r['cloud_cover'], r['t'], _spa_solar_prof), axis=1)
                high_solar = df_w_spa[df_w_spa['sol_w'] > 2000]
                if not high_solar.empty:
                    next_solar_time = high_solar.iloc[0]['t']
                    st.success(f"☀️ **Prognos:** Mycket goda chanser till gratisladdning av spabadet (solöverskott) runt kl **{next_solar_time.strftime('%H:%M')}**.")
    except Exception:
        pass

    sp1, sp2, sp3, sp4 = st.columns(4)
    sp_placeholder_1 = sp1.empty()
    sp_placeholder_2 = sp2.empty()
    sp_placeholder_3 = sp3.empty()
    sp_placeholder_4 = sp4.empty()

    def render_spa_live():
        h_state_raw = ha_state('water_heater.spa_malmgatan_34_heater', default='–').lower()
        h_attr = ha_attribute('climate.spabad_heater', 'hvac_action', default=h_state_raw).lower()
        
        if h_attr in ['heat', 'heating']: heater_display = "Värmer 🔥"
        elif h_attr == 'idle': heater_display = "Vilar ⚪"
        elif h_attr == 'cooling': heater_display = "Svalnar ❄️"
        else: heater_display = h_attr.capitalize()
        
        sp_placeholder_1.metric("🌡️ Aktuell Temp", f"{ha_state('sensor.spa_malmgatan_34_current_temperature', '–')} °C")
        sp_placeholder_2.metric("🎯 Måltemp", f"{ha_state('sensor.spa_malmgatan_34_target_temperature', '–')} °C")
        sp_placeholder_3.metric("🔥 Värmare", heater_display)
        sp_placeholder_4.metric("💰 Economy Mode", "PÅ 🟢" if ha_state('switch.spabad_economy_mode') == "on" else "AV ⚫")
        
    render_spa_live()

    st.divider()
    sp5, sp6 = st.columns(2)
    netto_live = get_live_net_power()
    lbl_netto = "📤 Säljer till nätet" if netto_live < 0 else "📥 Köper från nätet"
    sp5.metric(lbl_netto, f"{abs(netto_live):.0f} W", delta_color="normal" if netto_live < 0 else "inverse")

    if _last_max_temp_time:
        sp6.metric("⏱️ Senast på Maxtemp", _last_max_temp_time.strftime("%Y-%m-%d %H:%M"))
    else:
        sp6.metric("⏱️ Senast på Maxtemp", "Ingen data loggad ännu")

    st.divider()
    st.markdown("### 📡 Radiodiagnostik (Gecko in.touch 2)")
    st.caption("Visar signalstyrka och vilken radiokanal spabadet kommunicerar över. Du kan tvinga fram ett kanalbyte om signalen är dålig.")
    
    rf_channel = ha_state('sensor.spa_malmgatan_34_rf_channel', ha_state('sensor.spabad_rf_channel', 'Okänd'))
    radio_signal = ha_state('sensor.spabad_radio', 'Okänd')
    
    r1, r2, r3 = st.columns([1, 1, 2])
    r1.metric("📶 Signalstyrka", f"{radio_signal} %" if radio_signal != 'Okänd' else "Okänd")
    r2.metric("📻 RF Kanal", rf_channel)
    with r3:
        st.write("") # Padding
        if st.button("🔄 Tvinga ny kanalsökning (Reconnect)", help="Startar om radiomodulen i badet så den skannar efter ett renare frekvensband."):
            try:
                ha_ip = os.environ.get("HA_IP")
                ha_token = os.environ.get("HA_TOKEN", "").strip("\"'")
                url = f"https://{ha_ip}:8123/api/services/button/press"
                headers = {"Authorization": f"Bearer {ha_token}", "Content-Type": "application/json"}
                res = requests.post(url, headers=headers, json={"entity_id": "button.spabad_reconnect"}, timeout=5, verify=False)
                if res.status_code == 200:
                    st.success("✅ Kommando skickat! Spabadet bryter nu anslutningen och letar upp en renare kanal.")
                else:
                    st.error(f"Kunde inte skicka kommando (HTTP {res.status_code})")
            except Exception as e:
                st.error(f"Kunde inte skicka kommando: {e}")
                
    try:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE sensor_log ADD COLUMN IF NOT EXISTS spa_rf_channel NUMERIC, ADD COLUMN IF NOT EXISTS spa_signal_pct NUMERIC"))
            
        df_rf = pd.read_sql(text("""
            SELECT timestamp AT TIME ZONE 'Europe/Stockholm' as "Tid", 
                   spa_rf_channel as "Kanal",
                   spa_signal_pct as "Signal (%)"
            FROM sensor_log 
            WHERE timestamp >= NOW() - INTERVAL '7 days'
              AND spa_signal_pct IS NOT NULL
            ORDER BY timestamp ASC
        """), engine)
        
        if not df_rf.empty:
            fig_rf = make_subplots(specs=[[{"secondary_y": True}]])
            fig_rf.add_trace(go.Scatter(x=df_rf["Tid"], y=df_rf["Signal (%)"], name="Signalstyrka (%)", fill='tozeroy', fillcolor='rgba(46, 204, 113, 0.2)', line=dict(color='#2ecc71', width=2)), secondary_y=False)
            fig_rf.add_trace(go.Scatter(x=df_rf["Tid"], y=df_rf["Kanal"], name="RF Kanal", mode='markers', marker=dict(color='#3498db', size=6, opacity=0.7)), secondary_y=True)
            
            fig_rf.update_layout(template="plotly_dark", hovermode="x unified", title="Signalstyrka och Kanalval (Senaste veckan)", margin=dict(l=10, r=10, t=40, b=10), legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5))
            fig_rf.update_yaxes(title_text="Signal (%)", range=[0, 105], secondary_y=False)
            fig_rf.update_yaxes(title_text="Kanal", range=[10, 27], secondary_y=True)
            plot(fig_rf, width="stretch")
    except Exception as e:
        pass

    st.divider()
    st.subheader("📈 Historisk prestanda (Temperatur & Värmare)")
    st.caption("Visar spabadets temperatur, målvärde och när värmaren faktiskt har varit aktiv.")
    
    try:
        spa_history_hours = st.select_slider(
            "Välj tidsfönster för spabadets graf",
            options=[12, 24, 48, 72],
            value=24,
            format_func=lambda x: f"{x} timmar",
            key="spa_hist_slider"
        )
        df_spa_hist = pd.read_sql(text(f"""
            SELECT timestamp AT TIME ZONE 'Europe/Stockholm' as "Tid", 
                       spa_temp as "Aktuell Temp (°C)",
                       spa_target as "Måltemp (°C)",
                       outdoor_temp as "Ute (°C)",
                       spa_heater_running as "Värmare PÅ"
                FROM sensor_log 
                WHERE timestamp >= NOW() - INTERVAL '1 hour' * :hours
                  AND spa_temp IS NOT NULL
                ORDER BY timestamp ASC
        """), engine, params={"hours": spa_history_hours})

        if not df_spa_hist.empty:
            fig_spa = make_subplots(specs=[[{"secondary_y": True}]])

            fig_spa.add_trace(go.Scatter(x=df_spa_hist["Tid"], y=df_spa_hist["Aktuell Temp (°C)"], name="Aktuell Temp (°C)", line=dict(color='#5dade2', width=2)), secondary_y=False)
            fig_spa.add_trace(go.Scatter(x=df_spa_hist["Tid"], y=df_spa_hist["Måltemp (°C)"], name="Måltemp (°C)", line=dict(color='#d35400', width=2, dash='dot')), secondary_y=False)
            fig_spa.add_trace(go.Scatter(x=df_spa_hist["Tid"], y=df_spa_hist["Ute (°C)"], name="Ute (°C)", line=dict(color='#ff6b6b', width=2, dash='dash')), secondary_y=True)

            # Shaded areas for heater running
            df_spa_hist['Värmare PÅ'] = df_spa_hist['Värmare PÅ'].fillna(0).astype(int)
            is_running = False
            start_time = None
            for _, row_hist in df_spa_hist.iterrows():
                if row_hist['Värmare PÅ'] == 1 and not is_running:
                    start_time = row_hist['Tid']
                    is_running = True
                elif row_hist['Värmare PÅ'] == 0 and is_running:
                    if start_time:
                        fig_spa.add_vrect(x0=start_time, x1=row_hist['Tid'], fillcolor="#e74c3c", opacity=0.2, layer="below", line_width=0)
                    is_running = False
                    start_time = None
            if is_running and start_time:
                fig_spa.add_vrect(x0=start_time, x1=df_spa_hist['Tid'].iloc[-1], fillcolor="#e74c3c", opacity=0.2, layer="below", line_width=0)

            fig_spa.add_trace(go.Scatter(x=[None], y=[None], mode='markers', marker=dict(color='rgba(231, 76, 60, 0.5)'), name='Värmare PÅ'))

            fig_spa.update_layout(
                title_text="Spabad Temperatur & Värmardrift",
                template="plotly_dark",
                hovermode="x unified",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
            )
            fig_spa.update_yaxes(title_text="Spabad Temp (°C)", range=[10, 45], secondary_y=False)
            fig_spa.update_yaxes(title_text="Ute Temp (°C)", secondary_y=True)
            
            plot(fig_spa, width="stretch")
        else:
            st.info("Ingen historik för spabadet hittades för den valda perioden.")
    except Exception as e:
        st.error(f"Kunde inte ladda graf för spabadet: {e}")

    st.divider()

    st.markdown("### 📅 Schemalägg uppvärmning")
    st.caption("Ställ in en tid och temperatur som spabadet ska ha nått. AI:n kommer att planera uppvärmningen för att vara så kostnadseffektiv som möjligt.")

    with st.form("spa_schedule_form"):
        form_cols = st.columns([2, 1, 1, 1])
        
        with form_cols[0]:
            # Display current target if it exists and is in the future
            if schedule_enabled and current_target_dt and current_target_dt > datetime.now(SWE_TZ):
                st.success(f"✅ Aktivt schema: **{current_target_temp}°C** den **{current_target_dt.strftime('%Y-%m-%d %H:%M')}**")
            elif schedule_enabled and current_target_dt:
                st.warning(f"⚠️ Gammalt schema passerat: **{current_target_temp}°C** den **{current_target_dt.strftime('%Y-%m-%d %H:%M')}**. Inaktivera eller sätt ett nytt.")
            else:
                st.info("Inget aktivt schema.")

        # Inputs for new schedule
        default_date = current_target_dt.date() if current_target_dt and current_target_dt.date() >= datetime.now(SWE_TZ).date() else datetime.now(SWE_TZ).date()
        default_time = current_target_dt.time() if current_target_dt else datetime.strptime("18:00", "%H:%M").time()
        
        with form_cols[1]:
            target_date = st.date_input("Datum", value=default_date, help="Välj ett datum i framtiden.")
        with form_cols[2]:
            target_time = st.time_input("Tid", value=default_time, help="Tidpunkten då tempen ska vara uppnådd.")
        with form_cols[3]:
            target_temp = st.number_input("Måltemp (°C)", min_value=20.0, max_value=41.0, value=float(current_target_temp or 38.0), step=0.5)

        sch_c1, sch_c2 = st.columns([1, 3])
        with sch_c1:
            new_schedule_enabled = st.toggle("Aktivera/avaktivera schema", value=schedule_enabled)
        with sch_c2:
            submitted = st.form_submit_button("💾 Spara schema")

        if submitted:
            # Combine date and time
            new_target_dt = datetime.combine(target_date, target_time).replace(tzinfo=SWE_TZ)

            if new_target_dt < datetime.now(SWE_TZ) and new_schedule_enabled:
                st.error("Fel: Du kan inte sätta ett schema i dåtid. Välj ett datum och en tid i framtiden.")
            else:
                try:
                    with engine.begin() as conn:
                        conn.execute(text("""
                            UPDATE system_settings
                            SET spa_target_datetime = :dt, spa_target_temp = :temp, spa_schedule_enabled = :enabled
                            WHERE id = 1
                        """), {"dt": new_target_dt, "temp": target_temp, "enabled": new_schedule_enabled})
                        
                        if new_schedule_enabled:
                            conn.execute(text("UPDATE system_settings SET spa_force_heat = FALSE WHERE id = 1"))
                        
                    if new_schedule_enabled:
                        try:
                            curr_spa_temp = float(ha_state('sensor.spa_malmgatan_34_current_temperature', 38.0))
                        except:
                            curr_spa_temp = 38.0 # Fallback

                        out_temp = row.get('outdoor_temp', 0) if row is not None else 0
                        model_intercept, model_slope_out, model_slope_spa = learning.get_heating_rate_model()
                        cooling_k, _ = learning.get_cooling_rate_model()
                        spa_max = float(settings.get("spa_max_temp", 40.0))
                        spa_normal = float(settings.get("spa_normal_temp", 34.0))
                        
                        df_plan_imm = pred.get_spa_schedule_plan(datetime.now(SWE_TZ), new_target_dt, curr_spa_temp, model_intercept, model_slope_out, model_slope_spa, cooling_k, float(target_temp), spa_max, spa_normal, out_temp, float(settings.get("spa_low_temp", 15.0)))
                        
                        current_hour = datetime.now(SWE_TZ).replace(minute=0, second=0, microsecond=0).replace(tzinfo=None)
                        
                        if df_plan_imm is not None and not df_plan_imm.empty:
                            curr_plan_row = df_plan_imm[df_plan_imm['t_hour'] == current_hour]
                            is_heating = not curr_plan_row.empty and curr_plan_row.iloc[0]['is_heating']
                            is_solar = not curr_plan_row.empty and curr_plan_row.iloc[0]['solar_w'] > 1500
                        else:
                            temp_diff = max(0.0, float(target_temp) - curr_spa_temp)
                            heating_rate = learning.predict_heating_rate(out_temp, curr_spa_temp, model_intercept, model_slope_out, model_slope_spa)
                            safe_rate = max(0.5, heating_rate * 0.8)
                            fallback_hours = temp_diff / safe_rate
                            latest_start_time = new_target_dt - timedelta(hours=fallback_hours)
                            is_heating = datetime.now(SWE_TZ) >= latest_start_time
                            is_solar = False

                    fetch_ha_data.clear()

                    st.success("✅ Schema sparat! GPM-motorn tar över styrningen inom 60 sek.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Kunde inte spara schema: {e}")

    # --- RITA UPP GRAFEN OM SCHEMAT ÄR AKTIVT ---
    if schedule_enabled and current_target_dt and current_target_dt > datetime.now(SWE_TZ):
        if df_plan is not None and not df_plan.empty:
            st.markdown("#### 📈 Prognos: Så här planerar systemet uppvärmningen")
            
            df_plan['Date'] = df_plan['t_slot'].dt.date
            unique_dates = df_plan['Date'].unique()
            
            # Veckodagar och månader på svenska
            sv_days = {0: "Mån", 1: "Tis", 2: "Ons", 3: "Tor", 4: "Fre", 5: "Lör", 6: "Sön"}
            sv_months = {1: "jan", 2: "feb", 3: "mars", 4: "apr", 5: "maj", 6: "juni", 7: "juli", 8: "aug", 9: "sep", 10: "okt", 11: "nov", 12: "dec"}
            
            tab_names = [f"{sv_days[d.weekday()]} {d.day} {sv_months[d.month]}" for d in unique_dates]
            date_tabs = st.tabs(tab_names)
            
            COLOR_MAP = {
                'Vilar': '#F0F2F6',
                '☀️ Solenergi': '#FFD700',
                '💰 Billig el (Planerad)': '#1E90FF',
                '🔥 Måste värma (Tidskrav)': '#FF4500'
            }
            
            for idx, d in enumerate(unique_dates):
                with date_tabs[idx]:
                    df_day = df_plan[df_plan['Date'] == d].copy()
                    fig = make_subplots(specs=[[{"secondary_y": True}]])
                    
                    # Elpris som en tunn vit linje (Vänster Y-axel i öre/kWh)
                    fig.add_trace(
                        go.Scatter(
                            x=df_day['t_slot'], 
                            y=df_day['price'] * 100, 
                            name="Elpris (öre/kWh)", 
                            mode='lines', 
                            line=dict(shape='hv', color='#bdc3c7', width=2),
                            hovertemplate="%{x|%H:%M}<br>Pris: %{y:.1f} öre<extra></extra>"
                        ),
                        secondary_y=False
                    )
                    
                    # Temperaturstaplar uppdelade på färgkategori (Höger Y-axel)
                    for act, color in COLOR_MAP.items():
                        df_act = df_day[df_day['Aktivitet'] == act]
                        if not df_act.empty:
                            fig.add_trace(
                                go.Bar(
                                    x=df_act['t_slot'],
                                    y=df_act['Simulerad Temp'],
                                    name=act,
                                    marker_color=color,
                                    customdata=df_act[['Start Temp', 'Simulerad Temp', 'Aktivitet']],
                                    hovertemplate=(
                                        "<b>Status:</b> %{customdata[2]}<br>"
                                        "<b>Starttemp:</b> %{customdata[0]:.1f} °C<br>"
                                        "<b>Sluttemp:</b> %{customdata[1]:.1f} °C<br>"
                                        "<b>Varaktighet:</b> 15 min<extra></extra>"
                                    )
                                ),
                                secondary_y=True
                            )
                    
                    # Layout (Plotly Dark Theme) likt Tibber
                    max_price = max(120, (df_day['price'].max() * 100) * 1.1) if not df_day.empty else 120
                    start_of_day = pd.Timestamp(d)
                    end_of_day = start_of_day + pd.Timedelta(hours=23, minutes=59)
                    
                    fig.update_layout(
                        template="plotly_dark",
                        margin=dict(l=20, r=20, t=40, b=20),
                        legend=dict(orientation="h", yanchor="bottom", y=1.05, xanchor="center", x=0.5),
                        barmode='group',
                        bargap=0.1,
                        hovermode="x unified",
                        plot_bgcolor="rgba(0,0,0,0)",
                        paper_bgcolor="rgba(0,0,0,0)",
                    )
                    
                    fig.update_yaxes(title_text="Elpris (öre/kWh)", secondary_y=False, showgrid=False, zeroline=False, range=[0, max_price])
                    fig.update_yaxes(title_text="Temperatur (°C)", secondary_y=True, showgrid=False, zeroline=False, range=[20, 45])
                    fig.update_xaxes(title_text="", tickformat="%H:%M", dtick=3600000*2, showgrid=False, range=[start_of_day, end_of_day])
                    
                    plot(fig, width="stretch")
            
            current_heating_rate = learning.predict_heating_rate(out_temp, curr_spa_temp, model_intercept, model_slope_out, model_slope_spa)
            st.info(f"🧠 **Maskininlärning:** Baserat på {out_temp:.1f}°C ute är momentan uppvärmningshastighet **{current_heating_rate:.2f} °C/timme**.\n"
                    f"Avsvalningskonstanten (k) är **{cooling_k:.4f}**. Badet är {curr_spa_temp}°C och beräknas behöva {len(df_plan[df_plan['is_heating'] == True])} timmar aktiv uppvärmning för att nå målet {current_target_temp}°C i tid.")

    st.markdown("### ⚙️ Automatisk Styrning (Temperaturer)")
    st.caption("Ställ in vilka temperaturer AI:n ska styra mot. Maxtemp används vid solöverskott/tvångsvärme, Normaltemp när badet vilar, och Lågtemp vid Economy Mode.")
    
    with st.form("spa_settings_form"):
        s_col1, s_col2, s_col3 = st.columns(3)
        with s_col1:
            ny_max = st.number_input("Maxtemp (solöverskott/tvång)", min_value=15.0, max_value=41.0, value=min(float(settings.get("spa_max_temp", 40.0)), 41.0), step=0.5)
        with s_col2:
            ny_norm = st.number_input("Normaltemp (standby)", min_value=15.0, max_value=41.0, value=min(float(settings.get("spa_normal_temp", 34.0)), 41.0), step=0.5)
        with s_col3:
            ny_low = st.number_input("Lågtemp (Economy Mode)", min_value=10.0, max_value=41.0, value=min(float(settings.get("spa_low_temp", 15.0)), 41.0), step=0.5)
        
        if st.form_submit_button("💾 Spara Spabad-inställningar"):
            try:
                with engine.begin() as conn:
                    conn.execute(text("UPDATE system_settings SET spa_max_temp = :ma, spa_normal_temp = :no, spa_low_temp = :lo WHERE id = 1"), {"ma": ny_max, "no": ny_norm, "lo": ny_low})
                st.success("✅ Spabad-inställningar sparade!")
                st.rerun()
            except Exception as e:
                st.error(f"Kunde inte spara: {e}")

    st.divider()
    st.markdown("### 🧠 Digital Tvilling – Inlärd Värme/Kyl-profil")
    st.caption("AI:n lär sig kontinuerligt hur ditt spabad reagerar på olika utomhustemperaturer genom att analysera historisk loggdata. Ju mer badet används och vilar, desto mer precis blir denna kalkyl.")
    
    temps = range(-20, 31)
    k, _ = learning.get_cooling_rate_model()
    raw_data = []
    for t in temps:
        h_rate = get_spa_heating_rate(t, 38.0)
        c_rate = k * (38.0 - t) # Beräkna momentan avsvalning vid 38°C vattentemp
        raw_data.append({
            "Utetemp": t,
            "Värmning": h_rate,
            "Kylning": -c_rate
        })
        
    df_raw = pd.DataFrame(raw_data)
    df_melt = df_raw.melt(id_vars=["Utetemp"], var_name="Typ", value_name="Takt")
    
    chart = alt.Chart(df_melt).mark_line(interpolate='monotone', strokeWidth=3).encode(
        x=alt.X('Utetemp:Q', title='Utetemperatur (°C)'),
        y=alt.Y('Takt:Q', title='Temperaturförändring (°C/h)'),
        color=alt.Color('Typ:N', scale=alt.Scale(domain=['Värmning', 'Kylning'], range=['#ff6b6b', '#5dade2']), legend=alt.Legend(title="Aktivitet")),
        tooltip=[alt.Tooltip('Utetemp:Q', title='Ute (°C)'), alt.Tooltip('Typ:N', title='Aktivitet'), alt.Tooltip('Takt:Q', format='.2f', title='°C/h')]
    ).interactive().properties(height=350)
    
    st.altair_chart(chart, width="stretch")

    ml_data = []
    for d in raw_data:
        ml_data.append({
            "Utetemperatur": f"{d['Utetemp']} °C",
            "Värmningstakt": f"{d['Värmning']:.2f} °C/h",
            "Kylningstakt (Förlust)": f"{d['Kylning']:.2f} °C/h"
        })
    st.dataframe(pd.DataFrame(ml_data).set_index("Utetemperatur"), width="stretch")

    # --- NY AI-STATUS (Träningsdata) ---
    try:
        df_train = pd.read_sql(text("SELECT COUNT(*) FROM sensor_log WHERE spa_heater_running = 1"), engine)
        df_cool = pd.read_sql(text("SELECT COUNT(*) FROM sensor_log WHERE spa_heater_running = 0"), engine)
        heat_mins = int(df_train.iloc[0,0])
        cool_mins = int(df_cool.iloc[0,0])
            
        st.info(f"📊 **Insamlad Träningsdata:** AI:n har just nu loggat **{heat_mins} minuter** aktiv uppvärmning och **{cool_mins} minuter** avkylning.")
        
        current_heating_rate = learning.predict_heating_rate(out_temp, curr_spa_temp, model_intercept, model_slope_out, model_slope_spa)
        if heat_mins < 60:
            st.warning("⚠️ **Väntar på mer data:** Linjen ovan är fortfarande rak (standardvärde 2.0 °C/h) eftersom systemet behöver observera värmaren i minst 60 minuter uppdelat i 3 distinkta värmnings-sessioner för att kunna dra en egen personlig kurva.")
        else:
            if current_heating_rate == 2.0: # Default rate
                st.warning("⚠️ Datamängden är över 60 minuter, men systemet har ännu inte uppmätt tillräckligt kraftiga temperaturhöjningar (>0.2°C per gång) för att dra en säker statistisk slutsats. Det kommer med tiden!")
            else:
                st.success("✅ Maskininlärningen är aktiv och använder din personliga bad-data för att förutspå exakt starttid.")
    except Exception:
        pass

    st.divider()
    with st.expander("Visa alla Spabad-entiteter"):
        spa_entities = [v for k, v in ha_data.items() if "spa" in k.lower()] 
        if spa_entities:
            df_spa = pd.DataFrame([{"Entitet": v["entity_id"], "Namn": v.get("attributes", {}).get("friendly_name", ""), "Status": v["state"]} for v in spa_entities])
            st.dataframe(df_spa, width="stretch")
        else:
            st.info("Hittade inga Spabad-entiteter.")

    st.divider()
    st.markdown("### 🧠 Så här fungerar AI-styrningen (Prioriteringsordning)")
    st.caption("Smarthubben utvärderar nedanstående villkor varje minut. Det översta villkoret som är sant 'vinner' och bestämmer badets temperatur.")
    
    st.markdown("""
    **1. 🔥 Tvångsvärme (Högsta prioritet)**
    - Direkt uppvärmning till Maxtemp.
    - Ignorerar alla andra regler fram till midnatt.
    
    **2. 🤑 Minuspris (Pris < 0 kr/kWh)**
    - Overridar Economy och Schema.
    - Spabadet värms omedelbart till Maxtemp.
    - Utnyttjar vattnet maximalt som termiskt batteri.
    
    **3. ☀️ Solöverskott (Dynamiskt tröskelvärde)**
    - Soltrigger aktiveras när solel > dynamisk gräns:
        • 500–1000 W om badet är nära måltemp (≤ 2°C under).
        • 1500–2000 W om badet är 3–5°C under.
        • 2000–2500 W om badet är >5°C under.
    - Solboost-tid styrs dynamiskt:
        • 0–3 timmar per dygn baserat på solprognos + värmebehov.
    - Värmer endast upp till Maxtemp.
    
    **4. 📅 Schema (Prognosbaserad smart uppvärmning)**
    - AI beräknar när värme måste starta för att nå måltemp i tid.
    - Väljer de billigaste och/eller mest soliga timmarna före startfönster.
    - Under väntan hålls badet inom Normaltemp-intervall.
    
    **5. 💤 Economy Mode (Intelligent dvalaläge)**
    - Används endast om punkterna ovan inte triggar.
    - Badet får sjunka inom ett temperaturintervall (ex: 33–36°C).
    - AI minimerar värmning under dyra eller onödiga timmar.
    - Låter temperaturen falla mer när billigare pris väntas senare.
    
    **6. 💸 Prisspik (Adaptiv blockering)**
    - Aktiveras om någon av följande är sant:
        • Timmen är en av dagens 4 dyraste.
        • Pris > dygnsmedel × 1.4.
        • Pris ligger > näst dyraste timmen + 20 öre.
    - Stoppar all onödig värme.
    - Håller badet stabilt inom Normaltemp men utan toppningar.
    
    **7. ✅ Normaldrift (Lägsta prioritet)**
    - Om inga regler ovan är aktiva:
        • Håller badet på Normaltemp men inom ett span på ± 2°C, så den inte startar och stoppar hela tiden.
        • Underhållsvärmer lugnt och stabilt.
    
    ---
    *(💡 **Säkerhetsspärr:** Om badet drivs upp till sin Maxtemp av t.ex. solöverskott eller minuspris, pausar AI:n värmaren automatiskt i 1 timme så fort målet är nått. Detta skyddar värmarens reläer från att stå och slå av/på kontinuerligt om temperaturen pendlar runt gränsvärdet).*
    """)

# ══════════════════════════════════════════════════════════════════════════════
# 🌡️ TEMPERATURER
# ══════════════════════════════════════════════════════════════════════════════
def page_temps_list():
    render_refresh_button("temps")
    st.subheader("🌡️ Temperaturöversikt")
    
    s1 = safe_float("sensor.tempsensor_1_temperatur")
    s2 = safe_float("sensor.timmerflotte_temp_hmd_sensor_temperatur")
    s3 = safe_float("sensor.timmerflotte_temp_hmd_sensor_temperatur_2")
    s4 = safe_float("sensor.timmerflotte_temp_hmd_sensor_temperatur_3")
    s5 = safe_float("sensor.esp_tempsensor_temperature")
    
    if s5 <= 0 and row is not None and row.get('temp_esp') is not None:
        s5 = float(row.get('temp_esp'))

    calc_in_t = row.get('indoor_temp') if row is not None else None
    in_t_label = "🏠 Inne (Median av sensorerna)"
    st.metric(in_t_label, f"{calc_in_t:.1f} °C" if calc_in_t is not None else "– °C", help="Exakt det värde styrningen använder (loggat av smartbox). Median när minst 3 sensorer svarar, annars medel. ESP-sensorn justeras −0,6 °C när Zigbee-sensorn saknas.")
    _h = row.get('indoor_humidity') if row is not None else None
    st.metric("💧 Luftfuktighet inne (Median)", f"{_h:.0f} %" if _h is not None and not pd.isna(_h) else "– %", help="Styrningen höjer måltemperaturen upp till +1 °C när fuktigheten går från 55 % till 75 %.")

    st.divider()

    st.subheader("Inomhussensorer (Live från HA)")
    t1, t2, t3, t4 = st.columns(4)
    t1.metric("Huvudsensor (Zigbee)", f"{ha_state('sensor.tempsensor_1_temperatur')} °C", f"💧 {ha_state('sensor.tempsensor_1_luftfuktighet')} %", delta_color="off")
    t2.metric("Matter 1 (Timmerflotte)", f"{ha_state('sensor.timmerflotte_temp_hmd_sensor_temperatur')} °C", f"💧 {ha_state('sensor.timmerflotte_temp_hmd_sensor_luftfuktighet')} %", delta_color="off")
    t3.metric("Matter 2 (Timmerflotte)", f"{ha_state('sensor.timmerflotte_temp_hmd_sensor_temperatur_2')} °C", f"💧 {ha_state('sensor.timmerflotte_temp_hmd_sensor_luftfuktighet_2')} %", delta_color="off")
    t4.metric("ESP (Athom)", f"{ha_state('sensor.esp_tempsensor')} °C", f"💧 {ha_state('sensor.athom_temperature_humidity_sensor_4b73a0_humidity')} %", delta_color="off")

    m1, m2, m3 = st.columns(3)
    m1.metric("Matter 3 (Timmerflotte)", f"{ha_state('sensor.timmerflotte_temp_hmd_sensor_temperatur_3')} °C")
    m2.metric("ESP-Tempsensor", f"{s5:.1f} °C" if s5 > 0 else "Offline")
    m3.metric("Garage", f"{ha_state('sensor.sensor_garage_enhetens_temperatur')} °C")

    st.divider()
    st.subheader("Utomhussensorer")
    t4, t5 = st.columns(2)
    out_t = row.get('outdoor_temp')
    t4.metric("🌲 Ute (Pump)", f"{out_t:.1f} °C" if out_t is not None else "– °C", help="Hämtas från pumpens utomhusgivare: husdata modbus outdoor_temp (Läs Sensor).")
    t5.metric("🛣️ Väg (Torsvik)", f"{ha_state('sensor.torsvik_road_temperature')} °C", help="Referenssensor från Trafikverket.")

    st.divider()
    with st.expander("Visa alla temperatursensorer"):
        temp_entities = [v for k, v in ha_data.items() if "temp" in k.lower()]
        if temp_entities:
            df_t = pd.DataFrame([{"Entitet": v["entity_id"], "Namn": v.get("attributes", {}).get("friendly_name", ""), "Status": v["state"]} for v in temp_entities])
            st.dataframe(df_t, width="stretch")

# ══════════════════════════════════════════════════════════════════════════════
# ⚡ ELBIL (Easee)
# ══════════════════════════════════════════════════════════════════════════════
def page_ev():
    render_refresh_button("ev")
    netto_live = get_live_net_power()
    label = "📤 Säljer till nätet" if netto_live < 0 else "📥 Köper från nätet"
    st.metric("🏠 Husets Nettoförbrukning (Live)", f"{abs(netto_live) / 1000:.2f} kW", label, delta_color="normal" if netto_live < 0 else "inverse")
    st.divider()

    st.subheader("🔋 Smart Elbilsladdning")
    st.caption("Systemet anpassar laddningshastigheten för att möta ditt schema så kostnadseffektivt som möjligt, med prioritet på solenergi och låga elpriser, samtidigt som husets totala effekt hålls under kontroll.")
    st.info("💡 **Prioritering:** Värme > Varmvatten > **Elbil** > Spabad. Elbilsladdningen stryps automatiskt för att undvika effekttoppar.")

    ev_schedule = settings_module.get_ev_schedule()
    days_of_week = ["Måndag", "Tisdag", "Onsdag", "Torsdag", "Fredag", "Lördag", "Söndag"]

    nissan_soc = car_soc('sensor.leaf_battery_level', 'nissan_soc')[0] or 0.0
    tesla_soc = car_soc('sensor.tesla_model_y_battery', 'tesla_soc')[0] or 0.0
    joint_plan_df, joint_plan_info = create_joint_ev_plan(ev_schedule, nissan_soc, tesla_soc) # Har ändrats i funktionen ovan

    # --- GPS KARTA FÖR SMART HEMKOMST ---
    with st.expander("📍 Visa Live-Karta (GPS & Smart Hemkomst)"):
        n_lat = ha_attribute('device_tracker.leaf_location', 'latitude', None)
        n_lon = ha_attribute('device_tracker.leaf_location', 'longitude', None)
        t_lat = ha_attribute('device_tracker.tesla_model_y_location_tracker', 'latitude', None)
        t_lon = ha_attribute('device_tracker.tesla_model_y_location_tracker', 'longitude', None)
        
        n_speed = ha_attribute('device_tracker.leaf_location', 'speed', None)
        t_speed = ha_attribute('device_tracker.tesla_model_y_location_tracker', 'speed', None)
        
        if n_lat or t_lat:
            fig_gps = go.Figure()
            
            # Rita ut Huset
            fig_gps.add_trace(go.Scattermap(
                lat=[weather.LATITUDE], lon=[weather.LONGITUDE],
                mode='markers+text', marker=go.scattermap.Marker(size=18, color='#3498db'),
                text=["🏠 Huset"], textposition="bottom right", name="Huset"
            ))
            
            # Rita ut Nissan
            if n_lat and n_lon:
                dist_n = calc_dist(weather.LATITUDE, weather.LONGITUDE, n_lat, n_lon)
                # FIX: laddar i hemma-Easee ⟹ hemma (stale GPS ignoreras). Visa vid huset, ingen hemkomst-linje.
                _n_home_charging = (str(ha_state('sensor.easee_lite_status', '')).lower() == 'charging'
                                    or (safe_float('sensor.easee_lite_effekt') or 0) >= 200)
                if _n_home_charging:
                    n_plot_lat, n_plot_lon = weather.LATITUDE, weather.LONGITUDE
                    n_text = "🚙 Nissan (hemma & laddar ⚡)"
                else:
                    n_plot_lat, n_plot_lon = n_lat, n_lon
                    if 0.5 < dist_n < 15.0:
                        fig_gps.add_trace(go.Scattermap(
                            mode='lines',
                            lat=[weather.LATITUDE, float(n_lat)], lon=[weather.LONGITUDE, float(n_lon)],
                            line=dict(width=3, color='#2ecc71'),
                            name="Smart Hemkomst (Nissan)", hoverinfo="skip"
                        ))
                    n_text = "🚙 Nissan Leaf"
                    if n_speed is not None:
                        try:
                            n_text += f" ({round(float(n_speed))} km/h)"
                        except (ValueError, TypeError):
                            pass
                fig_gps.add_trace(go.Scattermap(
                    lat=[n_plot_lat], lon=[n_plot_lon],
                    mode='markers+text', marker=go.scattermap.Marker(size=14, color='#2ecc71'),
                    text=[n_text], textposition="bottom right", name="Nissan Leaf"
                ))
                
            # Rita ut Tesla
            if t_lat and t_lon:
                dist_t = calc_dist(weather.LATITUDE, weather.LONGITUDE, t_lat, t_lon)
                # FIX: laddar i hemma-Easee (carport) ⟹ hemma. Visa vid huset, ingen hemkomst-linje.
                _t_home_charging = (str(ha_state('sensor.carport_status', '')).lower() == 'charging'
                                    or (safe_float('sensor.carport_effekt') or 0) >= 200)
                if _t_home_charging:
                    t_plot_lat, t_plot_lon = weather.LATITUDE, weather.LONGITUDE
                    t_text = "🚗 Tesla (hemma & laddar ⚡)"
                else:
                    t_plot_lat, t_plot_lon = t_lat, t_lon
                    if 0.5 < dist_t < 15.0:
                        fig_gps.add_trace(go.Scattermap(
                            mode='lines',
                            lat=[weather.LATITUDE, float(t_lat)], lon=[weather.LONGITUDE, float(t_lon)],
                            line=dict(width=3, color='#e74c3c'),
                            name="Smart Hemkomst (Tesla)", hoverinfo="skip"
                        ))
                    t_text = "🚗 Tesla Model Y"
                    if t_speed is not None:
                        try:
                            t_text += f" ({round(float(t_speed))} km/h)"
                        except (ValueError, TypeError):
                            pass
                fig_gps.add_trace(go.Scattermap(
                    lat=[t_plot_lat], lon=[t_plot_lon],
                    mode='markers+text', marker=go.scattermap.Marker(size=14, color='#e74c3c'),
                    text=[t_text], textposition="bottom right", name="Tesla Model Y"
                ))
                
            fig_gps.update_layout(
                map_style="carto-darkmatter", # Mörk kartstil, matchar dashboardens tema (Plotly 6 MapLibre)
                map=dict(center=dict(lat=weather.LATITUDE, lon=weather.LONGITUDE), zoom=11),
                margin={"r":0,"t":0,"l":0,"b":0},
                height=450, showlegend=False
            )

            plot(fig_gps, config={**DEFAULT_PLOTLY_CONFIG, "scrollZoom": True})
            st.caption("AI:n analyserar avståndet mellan bilarna och huset. Om bilen befinner sig mellan 0.5 km och 15 km bort, och avståndet krymper, triggas Smart Hemkomst automatiskt.")
        else:
            st.info("Ingen GPS-data tillgänglig från bilarna via Home Assistant just nu.")

    # --- TESLA ---
    st.divider()
    st.markdown("### 🚗 Tesla (Carport)")
    
    def get_sv_tesla_status():
        # HOME-baserad: Teslans egna charging/plugged-sensorer är platsoberoende (sant även vid
        # supercharger borta) → vi utgår från HEMMA-laddaren (carport Easee) + GPS-hemma.
        easee = ha_state('sensor.carport_status', 'offline').lower()
        cp = safe_float('sensor.carport_effekt') or 0.0
        cp_kw = cp / 1000.0 if cp > 100 else cp
        _ts, _td, _ = get_car_location_info('tesla')
        tesla_home = (_ts.lower() == 'home') or (_td <= 0.5)

        if easee == 'charging' or cp_kw >= 0.2: return "Laddar ⚡"
        # Bortaladdning: visa bilens EGNA laddtelemetri när den laddar borta (t.ex. supercharger).
        # Detta är ren visning – det påverkar INTE allokering/schema (de är hemma-laddar-baserade).
        car_power = safe_float('sensor.tesla_model_y_charger_power') or 0.0
        car_charging = ha_state('binary_sensor.tesla_model_y_charging', 'off') == 'on' or car_power >= 0.2
        if not tesla_home and car_charging: return "Laddar borta 🌍⚡"
        if easee not in ['disconnected', 'offline', 'none', '']:
            if easee == 'awaiting_start': return "Väntar på schema ⏳"
            if easee == 'completed': return "Färdigladdad ✅"
            if easee == 'paused': return "Pausad ⏸️"
            if easee == 'off': return "Laddbox avstängd 🔴"
            return "Ansluten 🔌"
        if not tesla_home: return "Borta 🚗💨"
        if easee == 'offline': return "Offline 📡"
        return "Frånkopplad ⚪"

    t_status_sv = get_sv_tesla_status()
    t_amps_set = ha_state('number.tesla_model_y_charging_amps', '–')
    
    t_c1, t_c2, t_c3 = st.columns(3)
    t_c1.metric("🔌 Status", t_status_sv)
    t_c2_placeholder = t_c2.empty()
    
    def render_tesla_live_metrics():
        # Bortaladdning: visa bilens EGNA effekt + hastighet (carport-Easee är ju tom när den är borta).
        _ts2, _td2, _ = get_car_location_info('tesla')
        _t_home2 = (_ts2.lower() == 'home') or (_td2 <= 0.5)
        _car_pw = safe_float('sensor.tesla_model_y_charger_power') or 0.0
        if (not _t_home2) and (ha_state('binary_sensor.tesla_model_y_charging', 'off') == 'on' or _car_pw >= 0.2):
            _rate = safe_float('sensor.tesla_model_y_charging_rate') or 0.0
            _added = safe_float('sensor.tesla_model_y_energy_added') or 0.0
            t_c2_placeholder.metric("⚡ Effekt (borta)", f"{_car_pw:.2f} kW",
                                    f"{t_amps_set}A · {_rate:.0f} km/h · +{_added:.1f} kWh denna session", delta_color="off")
            return
        t_power = safe_float('sensor.carport_effekt')
        t_power_kw = t_power if t_power < 100 else t_power / 1000.0
        t_phases = 3 if ha_state('select.carport_allowed_charging_phases', 'SinglePhase') == 'ThreePhase' else 1
        active_t_phases = sum([1 for a in ('inCurrentT3', 'inCurrentT4', 'inCurrentT5') if _num_or0(ha_attribute('sensor.carport_strom', a, 0)) > 0.5])
        if active_t_phases == 0 and t_power_kw > 0.1: 
            active_t_phases = 3 if t_power_kw > 4.0 else t_phases
        t_limit = ha_state('sensor.carport_maximum_allowed_charge_current', '0')
        t_phase_str = f"{active_t_phases}-fas aktiv" if t_power_kw > 0 else f"{t_phases}-fas tillåten"
        t_c2_placeholder.metric("⚡ Effekt", f"{t_power_kw:.2f} kW", f"Easee: {t_limit}A | Tesla-app: {t_amps_set}A ({t_phase_str})", delta_color="off")
    render_tesla_live_metrics()
    
    with t_c3:
        _t_soc, _t_stale = car_soc('sensor.tesla_model_y_battery', 'tesla_soc')
        st.metric("🔋 Batteri", f"{_t_soc:.0f} %" if _t_soc is not None else "– %", "senast känd (bilen sover)" if _t_stale else None, delta_color="off")
        tesla_plan_text = joint_plan_info.get('tesla', {}).get('text', 'Plan ej tillgänglig.')
        st.caption(tesla_plan_text)
        _tcc = forecast_charge_complete('tesla')
        if _tcc:
            st.caption(_tcc)
        if row is not None and 'tesla_charge_completed' in row and row['tesla_charge_completed'] == 1:
            st.info("🏁 Färdigladdad (flagga aktiv)")

    st.markdown("##### 🎛️ Manuell Tvångsladdning")
    st.caption("Åsidosätter Peak Shaving och Scheman. Bilen laddar exakt som du anger tills du återställer till 'Auto'.")
    with st.form("tesla_force_form"):
        t_options = {
            "Auto (AI styr)": (0, 0),
            "1.4 kW (1-fas, 6A)": (6, 1),
            "2.3 kW (1-fas, 10A)": (10, 1),
            "3.7 kW (1-fas, 16A)": (16, 1),
            "4.1 kW (3-fas, 6A)": (6, 3),
            "6.9 kW (3-fas, 10A)": (10, 3),
            "11.0 kW (3-fas, 16A)": (16, 3)
        }
        curr_t_amps = int(get_overrides().get("tesla_force_amps", "0") if get_overrides().get("tesla_force_amps", "0") != "auto" else "0")
        curr_t_phases = int(get_overrides().get("tesla_force_phases", "0") if get_overrides().get("tesla_force_phases", "0") != "auto" else "0")
        
        curr_t_val = (curr_t_amps, curr_t_phases)
        if curr_t_val not in t_options.values():
            curr_t_val = (0, 0)
            
        selected_t_label = st.selectbox("Laddhastighet", options=list(t_options.keys()), index=list(t_options.values()).index(curr_t_val))
        new_t_amps, new_t_phases = t_options[selected_t_label]
        
        t_soc = safe_float('sensor.tesla_model_y_battery')
        if t_soc > 0 and new_t_amps > 0:
            t_kw = (new_t_amps * 230 * new_t_phases) / 1000.0
            if t_kw > 0:
                t_kwh_left = 75.0 * ((100 - t_soc) / 100.0) * 1.12 # Inklusive 12% laddförlust
                t_hours_left = t_kwh_left / t_kw
                t_finish_time = (datetime.now(SWE_TZ) + timedelta(hours=t_hours_left)).strftime("%H:%M")
                st.success(f"Beräknad klar: **kl {t_finish_time}** (Laddar med {t_kw:.1f} kW)")
            else:
                st.info("Pausad (0 kW).")

        if st.form_submit_button("🚀 Verkställ Tvångsladdning"):
            set_override_db("tesla_force_amps", str(new_t_amps))
            set_override_db("tesla_force_phases", str(new_t_phases))
            st.success("✅ Omedelbar överstyrning aktiverad!")
            st.rerun()

    # 🔌 Gästladdning: force max på carport (Tesla-laddaren), ignorerar schema/pris/sol/effektvakt (Prio 11.5).
    _t_guest_on = get_overrides().get("tesla_force_amps", "0") == "16"
    _t_guest = st.toggle("🔌 Gästladdning (max) – carport", value=_t_guest_on, key="tesla_guest_toggle",
        help="Laddaren kör max (16A/3-fas) och struntar i schema, pris, sol och effektvakt – laddar gästbilen så snabbt laddaren tillåter. Stäng av för att återgå till Auto.")
    if _t_guest != _t_guest_on:
        set_override_db("tesla_force_amps", "16" if _t_guest else "0")
        set_override_db("tesla_force_phases", "0")  # 0 = rör INTE fasen (undvik fasbyte-loop) – laddaren kör sin nativa fas
        st.rerun()

    st.markdown("##### ⚡ Snabbåtgärder")
    t_btn_c1, t_btn_c2, t_btn_c3 = st.columns(3)
    with t_btn_c1:
        if st.button("🔌 Starta Laddning", key="t_charge_on", width="stretch"):
            try:
                homeassistant.turn_on_charger(homeassistant.EASEE_CARPORT_ID)
                st.success("✅ Laddning startad!")
                time.sleep(0.5)
                st.rerun()
            except Exception as e: st.error(f"Fel: {e}")
    with t_btn_c2:
        if st.button("🛑 Stoppa Laddning", key="t_charge_off", width="stretch"):
            try:
                homeassistant.turn_off_charger(homeassistant.EASEE_CARPORT_ID)
                st.success("✅ Laddning stoppad!")
                time.sleep(0.5)
                st.rerun()
            except Exception as e: st.error(f"Fel: {e}")
    with t_btn_c3:
        if st.button("🔄 Ladda om & Släpp spärr", key="tesla_reload", width="stretch"):
            set_override_db("force_ev_recalc", "true")
            fetch_ha_data.clear()
            st.success("✅ Schemat räknas om direkt och kontaktorspärren är nollställd!")
            st.rerun()

    # --- NISSAN ---
    st.divider()
    st.markdown("### 🚙 Nissan Leaf (Easee Lite)")
    
    def get_sv_nissan_status():
        # HOME-baserad (samma princip som Tesla): hemma-laddaren (easee_lite) styr, inte bilens
        # platsoberoende leaf_charging. Effekt-fallback fångar laddning även om status-sensorn slöar.
        easee = ha_state('sensor.easee_lite_status', 'offline').lower()
        np_ = safe_float('sensor.easee_lite_effekt') or 0.0
        np_kw = np_ / 1000.0 if np_ > 100 else np_
        _ns, _nd, _ = get_car_location_info('nissan')
        nissan_home = (_ns.lower() == 'home') or (_nd <= 0.5)

        if easee == 'charging' or np_kw >= 0.2: return "Laddar ⚡"
        if easee not in ['disconnected', 'offline', 'none', '']:
            if easee == 'awaiting_start': return "Väntar på schema ⏳"
            if easee == 'completed': return "Färdigladdad ✅"
            if easee == 'paused': return "Pausad ⏸️"
            if easee == 'off': return "Laddbox avstängd 🔴"
            return "Ansluten 🔌"
        if not nissan_home: return "Borta 🚗💨"
        if easee == 'offline': return "Offline 📡"
        return "Frånkopplad ⚪"

    n_status_sv = get_sv_nissan_status()
    
    n_c1, n_c2, n_c3, n_c4 = st.columns(4)
    n_c1.metric("🔌 Status", n_status_sv)
    n_c2_placeholder = n_c2.empty()
    
    def render_nissan_live_metrics():
        n_power = safe_float('sensor.easee_lite_effekt')
        n_power_kw = n_power if n_power < 100 else n_power / 1000.0
        n_phases = 3 if ha_state('select.easee_lite_allowed_charging_phases', 'SinglePhase') == 'ThreePhase' else 1
        active_n_phases = sum([1 for a in ('inCurrentT3', 'inCurrentT4', 'inCurrentT5') if _num_or0(ha_attribute('sensor.easee_lite_strom', a, 0)) > 0.5])
        if active_n_phases == 0 and n_power_kw > 0.1: 
            active_n_phases = 3 if n_power_kw > 4.0 else n_phases
        n_limit = ha_state('sensor.easee_lite_maximum_allowed_charge_current', '0')
        n_phase_str = f"{active_n_phases}-fas aktiv" if n_power_kw > 0 else f"{n_phases}-fas tillåten"
        n_c2_placeholder.metric("⚡ Effekt", f"{n_power_kw:.2f} kW", f"Easee-gräns: {n_limit}A ({n_phase_str})", delta_color="off")
    render_nissan_live_metrics()
    
    with n_c3:
        _n_soc, _n_stale = car_soc('sensor.leaf_battery_level', 'nissan_soc')
        st.metric("🔋 Batteri", f"{_n_soc:.0f} %" if _n_soc is not None else "– %", "senast känd" if _n_stale else None, delta_color="off")
        nissan_plan_text = joint_plan_info.get('nissan', {}).get('text', 'Plan ej tillgänglig.')
        st.caption(nissan_plan_text)
        _ncc = forecast_charge_complete('nissan')
        if _ncc:
            st.caption(_ncc)
        if row is not None and 'nissan_charge_completed' in row and row['nissan_charge_completed'] == 1:
            st.info("🏁 Färdigladdad (flagga aktiv)")

    climate_state_raw = ha_state('climate.leaf_climate', default='off').lower()
    climate_state_display = "Okänd"
    if climate_state_raw in ('heat', 'heat_cool'):
        climate_state_display = "Värmer 🔥"
    elif climate_state_raw == 'off':
        climate_state_display = "Av ⚫"
    else:
        climate_state_display = climate_state_raw.capitalize()
    climate_temp = ha_attribute('climate.leaf_climate', 'current_temperature', '–')
    temp_str = f"{climate_temp} °C" if climate_temp != '–' else ""
    n_c4.metric("🔥 Värme", climate_state_display, temp_str, delta_color="off")

    st.markdown("##### 🎛️ Manuell Tvångsladdning")
    st.caption("Åsidosätter Peak Shaving och Scheman. Bilen laddar exakt som du anger tills du återställer till 'Auto'.")
    with st.form("nissan_force_form"):
        n_options = {
            "Auto (AI styr)": (0, 0),
            "1.4 kW (6A)": (6, 1),
            "2.3 kW (10A)": (10, 1),
            "3.7 kW (16A)": (16, 1),
            "4.6 kW (20A)": (20, 1)
        }
        curr_n_amps = int(get_overrides().get("nissan_force_amps", "0") if get_overrides().get("nissan_force_amps", "0") != "auto" else "0")
        curr_n_val = next((v for v in n_options.values() if v[0] == curr_n_amps), (0, 0))
        
        selected_n_label = st.selectbox("Laddhastighet", options=list(n_options.keys()), index=list(n_options.values()).index(curr_n_val), help="Nissan Leaf (2018) stödjer endast 1-fas.")
        new_n_amps, new_n_phases = n_options[selected_n_label]
        
        n_soc = safe_float('sensor.leaf_battery_level')
        if n_soc > 0 and new_n_amps > 0:
            n_kw = (new_n_amps * 230 * new_n_phases) / 1000.0
            if n_kw > 0:
                n_kwh_left = 40.0 * ((100 - n_soc) / 100.0) * 1.12 # Inklusive 12% laddförlust
                n_hours_left = n_kwh_left / n_kw
                n_finish_time = (datetime.now(SWE_TZ) + timedelta(hours=n_hours_left)).strftime("%H:%M")
                st.success(f"Beräknad klar: **kl {n_finish_time}** (Laddar med {n_kw:.1f} kW)")
            else:
                st.info("Pausad (0 kW).")

        if st.form_submit_button("🚀 Verkställ Tvångsladdning"):
            set_override_db("nissan_force_amps", str(new_n_amps))
            set_override_db("nissan_force_phases", str(new_n_phases))
            st.success("✅ Omedelbar överstyrning aktiverad!")
            st.rerun()

    # 🔌 Gästladdning: force max på easee_lite (Nissan-laddaren), ignorerar schema/pris/sol/effektvakt (Prio 11.5).
    _n_guest_on = get_overrides().get("nissan_force_amps", "0") == "16"
    _n_guest = st.toggle("🔌 Gästladdning (max) – easee_lite", value=_n_guest_on, key="nissan_guest_toggle",
        help="Laddaren kör max (16A/3-fas) och struntar i schema, pris, sol och effektvakt – laddar gästbilen så snabbt laddaren tillåter. Stäng av för att återgå till Auto.")
    if _n_guest != _n_guest_on:
        set_override_db("nissan_force_amps", "16" if _n_guest else "0")
        set_override_db("nissan_force_phases", "0")  # 0 = rör INTE fasen (undvik fasbyte-loop) – laddaren kör sin nativa fas
        st.rerun()

    st.markdown("##### ⚡ Snabbåtgärder")
    n_btn_c1, n_btn_c2, n_btn_c3, n_btn_c4, n_btn_c5 = st.columns(5)
    with n_btn_c1:
        if st.button("🔥 Starta Värme", key="n_heat_on", width="stretch"):
            try:
                homeassistant.set_car_climate("climate.leaf_climate", "heat_cool", 21.0)
                set_override_db("nissan_climate", "21.0")
                st.success("✅ Värme startad (Vakthund aktiverad)!")
                time.sleep(0.5)
                st.rerun()
            except Exception as e: st.error(f"Fel: {e}")
    with n_btn_c2:
        if st.button("🛑 Stoppa Värme", key="n_heat_off", width="stretch"):
            try:
                homeassistant.set_car_climate("climate.leaf_climate", "off")
                set_override_db("nissan_climate", "off")
                st.success("✅ Värme stoppad (Vakthund avaktiverad)!")
                time.sleep(0.5)
                st.rerun()
            except Exception as e: st.error(f"Fel: {e}")
    with n_btn_c3:
        if st.button("🔌 Starta Laddning", key="n_charge_on", width="stretch"):
            try:
                homeassistant.turn_on_charger(homeassistant.EASEE_LITE_ID)
                st.success("✅ Laddning startad!")
                time.sleep(0.5)
                st.rerun()
            except Exception as e: st.error(f"Fel: {e}")
    with n_btn_c4:
        if st.button("🛑 Stoppa Laddning", key="n_charge_off", width="stretch"):
            try:
                homeassistant.turn_off_charger(homeassistant.EASEE_LITE_ID)
                st.success("✅ Laddning stoppad!")
                time.sleep(0.5)
                st.rerun()
            except Exception as e: st.error(f"Fel: {e}")
    with n_btn_c5:
        if st.button("🔄 Ladda om & Släpp spärr", key="nissan_reload", width="stretch"):
            set_override_db("force_ev_recalc", "true")
            fetch_ha_data.clear()
            st.success("✅ Schemat räknas om direkt och kontaktorspärren är nollställd!")
            st.rerun()

    # --- SCHEMAN (I Expanders under kontrollerna) ---
    st.divider()
    st.markdown("### 🗓️ Schemaläggning av laddning och värme")
    
    with st.form("ev_prio_form"):
        st.markdown("#### 🥇 Prioritering vid samtidig laddning")
        st.caption("Om båda bilarna behöver laddas samtidigt, fördelas den tillgängliga strömmen. Prio 1 får 50% mer ström än Prio 2.")
        prio_cols = st.columns(2)
        with prio_cols[0]:
            nissan_prio = st.selectbox("Nissan Leaf", options=[1, 2], index=settings.get("ev_nissan_prio", 2) - 1, key="nissan_prio_select")
        with prio_cols[1]:
            tesla_prio = st.selectbox("Tesla", options=[1, 2], index=settings.get("ev_tesla_prio", 1) - 1, key="tesla_prio_select")
        
        prio_submitted = st.form_submit_button("💾 Spara Prioritering")
        if prio_submitted:
            if nissan_prio == tesla_prio:
                st.error("Bilarna kan inte ha samma prioritet. Välj olika värden.")
            else:
                with engine.begin() as conn:
                    conn.execute(text("UPDATE system_settings SET ev_nissan_prio = :np, ev_tesla_prio = :tp WHERE id = 1"), {"np": nissan_prio, "tp": tesla_prio})
                st.success("✅ Prioritering sparad!")
                time.sleep(1)
                st.rerun()

    climate_sched = settings_module.get_climate_schedule()

    sc_col1, sc_col2 = st.columns(2)
    with sc_col1:
        with st.expander("🌡️ Ställ in klimatschema för Nissan", expanded=climate_sched['nissan']['enabled']):
            # Hämta aktuell kupétemperatur
            leaf_climate_temp = ha_attribute('climate.leaf_climate', 'current_temperature', '–')
            st.metric("🌡️ Nuvarande kupétemperatur", f"{leaf_climate_temp} °C")

            with st.form("nissan_climate_form"):
                st.markdown("Ställ in när bilen ska vara uppvärmd. AI:n startar förvärmningen ca 30 min innan avfärd och stänger av när måltemperaturen är nådd.")
                c_cols = st.columns([1, 2, 2, 3])
                with c_cols[0]:
                    n_clim_en = st.toggle("Aktiv", value=climate_sched['nissan']['enabled'], key="n_clim_en")
                with c_cols[1]:
                    n_clim_time = st.time_input("Klar kl.", value=datetime.strptime(climate_sched['nissan']['target_time'], "%H:%M").time(), key="n_clim_t", label_visibility="collapsed")
                with c_cols[2]:
                    n_clim_temp = st.number_input("Måltemp (°C)", min_value=15.0, max_value=28.0, value=float(climate_sched['nissan']['target_temp']), step=0.5, key="n_clim_temp", label_visibility="collapsed")
                with c_cols[3]:
                    if st.form_submit_button("💾 Spara"):
                        settings_module.save_climate_schedule_db('nissan', n_clim_en, n_clim_time.strftime('%H:%M'), n_clim_temp)
                        st.success("✅ Klimatschema sparat för Nissan!")
                        st.rerun()

        with st.expander("🔌 Ställ in laddningsschema för Nissan"):
            with st.form("nissan_schedule_form"):
                st.markdown("Ange när bilen senast ska vara fulladdad för varje veckodag.")
                new_nissan_schedule = {}
                for i, day_name in enumerate(days_of_week):
                    day_data = ev_schedule['nissan'][i]
                    cols = st.columns([2, 1, 2, 2, 2])
                    with cols[0]:
                        st.write(day_name)
                    with cols[1]:
                        enabled = st.toggle("Aktiv", value=day_data['enabled'], key=f"nissan_enabled_{i}")
                    with cols[2]:
                        target_time_dt = datetime.strptime(day_data['target_time'], '%H:%M').time()
                        target_time = st.time_input("Klar kl.", value=target_time_dt, key=f"nissan_time_{i}", label_visibility="collapsed")
                    with cols[3]:
                        target_soc = st.slider("Mål-SOC", 0, 100, value=day_data.get('target_soc', 100), key=f"nissan_soc_{i}", format="%d%%", label_visibility="collapsed")
                    with cols[4]:
                        panic = st.toggle("🚨 Tvinga (Panic)", value=day_data.get('panic_mode', False), key=f"nissan_panic_{i}", help="Ignorera effekttaket (Peak Shaving) och tvinga bilen att bli full oavsett belastning på huset.")
                    new_nissan_schedule[i] = {'enabled': enabled, 'target_time': target_time.strftime('%H:%M'), 'target_soc': target_soc, 'panic_mode': panic}
                
                if st.form_submit_button("💾 Spara laddschema för Nissan"):
                    settings_module.save_ev_schedule_db('nissan', new_nissan_schedule)
                    st.success("✅ Schema för Nissan har sparats!")
                    st.rerun()

    with sc_col2:
        with st.expander("🔌 Ställ in laddningsschema för Tesla"):
            with st.form("tesla_schedule_form"):
                st.markdown("Ange när bilen senast ska vara fulladdad för varje veckodag.")
                new_tesla_schedule = {}
                for i, day_name in enumerate(days_of_week):
                    day_data = ev_schedule['tesla'][i]
                    cols = st.columns([2, 1, 2, 2, 2])
                    with cols[0]:
                        st.write(day_name)
                    with cols[1]:
                        enabled = st.toggle("Aktiv", value=day_data['enabled'], key=f"tesla_enabled_{i}")
                    with cols[2]:
                        target_time_dt = datetime.strptime(day_data['target_time'], '%H:%M').time()
                        target_time = st.time_input("Klar kl.", value=target_time_dt, key=f"tesla_time_{i}", label_visibility="collapsed")
                    with cols[3]:
                        target_soc = st.slider("Mål-SOC", 0, 100, value=day_data.get('target_soc', 100), key=f"tesla_soc_{i}", format="%d%%", label_visibility="collapsed")
                    with cols[4]:
                        panic = st.toggle("🚨 Tvinga (Panic)", value=day_data.get('panic_mode', False), key=f"tesla_panic_{i}", help="Ignorera effekttaket (Peak Shaving) och tvinga bilen att bli full oavsett belastning på huset.")
                    new_tesla_schedule[i] = {'enabled': enabled, 'target_time': target_time.strftime('%H:%M'), 'target_soc': target_soc, 'panic_mode': panic}
                
                if st.form_submit_button("💾 Spara laddschema för Tesla"):
                    settings_module.save_ev_schedule_db('tesla', new_tesla_schedule)
                    st.success("✅ Schema för Tesla har sparats!")
                    st.rerun()

    # --- GEMENSAM GRAF (Moved to after schedules for better flow) ---
    if not joint_plan_df.empty: # Only show if there's a plan
        st.divider()
        now_dt = datetime.now(SWE_TZ)
        max_dt = joint_plan_df['t_slot'].max().tz_localize(SWE_TZ)
        st.markdown("#### 📈 Gemensam Planerad Laddning (Kvarts-upplösning)")
        st.caption("Visar AI:ns laddplan **oavsett om bilarna är hemma just nu** – en riktig prognos baserad på batteri-%, önskad klar-tid, elpris, husets förväntade förbrukning och solprognos. Uppdateras varje kvart och justeras direkt när du ändrar klar-tid ovan och sparar. Strömmen smetas ut jämnt (**Smooth Allocation**) för att skona kontaktorer och minimera effekttoppar.")
        
        df_graph = joint_plan_df.copy()
        if 'slot_power_limit' not in df_graph.columns:
            df_graph['slot_power_limit'] = settings.get("power_limit_kw", 10.0)
        
        fig_comb = make_subplots(specs=[[{"secondary_y": True}]])
        
        power_limit = settings.get("power_limit_kw", 10.0)        
        df_graph['tesla_soc_text'] = df_graph.apply(lambda row: f"{row['tesla_start_soc']:.1f}% → {row['tesla_end_soc']:.1f}%" if row['tesla_kw'] > 0 else "", axis=1)
        df_graph['nissan_soc_text'] = df_graph.apply(lambda row: f"{row['nissan_start_soc']:.1f}% → {row['nissan_end_soc']:.1f}%" if row['nissan_kw'] > 0 else "", axis=1)
        
        fig_comb.add_trace(go.Bar(
            x=df_graph['t_slot'], 
            y=df_graph['tesla_kw'], 
            name="Tesla Model Y", 
            marker_color='#e74c3c',
            customdata=df_graph['tesla_soc_text'],
            hovertemplate="<b>Tesla Model Y</b><br>Tid: %{x|%H:%M}<br>Effekt: %{y:.1f} kW<br><b>Batteri: %{customdata}</b><extra></extra>"
        ), secondary_y=False)
        
        fig_comb.add_trace(go.Bar(
            x=df_graph['t_slot'], 
            y=df_graph['nissan_kw'], 
            name="Nissan Leaf", 
            marker_color='#2ecc71',
            customdata=df_graph['nissan_soc_text'],
            hovertemplate="<b>Nissan Leaf</b><br>Tid: %{x|%H:%M}<br>Effekt: %{y:.1f} kW<br><b>Batteri: %{customdata}</b><extra></extra>"
        ), secondary_y=False)
            
        fig_comb.add_trace(go.Scatter(x=df_graph['t_slot'], y=df_graph['price']*100, name="Elpris (öre/kWh)", mode='lines', line=dict(shape='hv', color='#bdc3c7', width=2),
                                      hovertemplate="Pris: %{y:.1f} öre<extra></extra>"), secondary_y=True)

        # Prognos för husets förbrukning + sol – visar VARFÖR AI:n väljer vissa kvartar.
        if 'house_load_kw' in df_graph.columns:
            fig_comb.add_trace(go.Scatter(x=df_graph['t_slot'], y=df_graph['house_load_kw'], name="🏠 Husets förbrukning (prognos)",
                                          mode='lines', line=dict(shape='hv', color='#f39c12', width=2, dash='dot'),
                                          hovertemplate="Husets förbrukning: %{y:.1f} kW<extra></extra>"), secondary_y=False)
        if 'solar_kw' in df_graph.columns:
            fig_comb.add_trace(go.Scatter(x=df_graph['t_slot'], y=df_graph['solar_kw'], name="☀️ Solproduktion (prognos)",
                                          mode='lines', line=dict(shape='hv', color='#f1c40f', width=2),
                                          hovertemplate="Solprognos: %{y:.1f} kW<extra></extra>"), secondary_y=False)

        # Rita bara in effekttaket om det är en RIKTIG begränsning (peak shaving på och rimlig nivå).
        # Annars (99 kW-"taket" när peak shaving är av) tvingar den flata linjen y-axeln till 0-100
        # och krymper laddning/sol/husbaslast till en osynlig strimma längst ner.
        _ps_enabled = bool(settings.get("peak_shaving_enabled", True))
        _tak_meaningful = _ps_enabled and df_graph['slot_power_limit'].max() < 30.0
        if _tak_meaningful:
            fig_comb.add_trace(go.Scatter(
                x=df_graph['t_slot'],
                y=df_graph['slot_power_limit'],
                name="Effekttak",
                mode='lines',
                line=dict(shape='hv', color='red', width=2, dash='dot'),
                hovertemplate="Effekttak: %{y:.1f} kW<extra></extra>"
            ), secondary_y=False)

        fig_comb.update_layout(template="plotly_dark", hovermode="x unified", barmode='stack', legend=dict(orientation="h", y=1.02, x=0.5, xanchor="center"))

        # Sätt kW-axeln efter de FAKTISKA värdena (inte det meningslösa 99 kW-taket) så att
        # laddning, sol och husbaslast faktiskt syns i förhållande till elpriset.
        _kw_series = [df_graph[['tesla_kw', 'nissan_kw']].sum(axis=1), df_graph.get('solar_kw', pd.Series([0])),
                     df_graph.get('house_load_kw', pd.Series([0]))]
        if _tak_meaningful:
            _kw_series.append(df_graph['slot_power_limit'])
        _kw_max = max(1.0, max(s.max() for s in _kw_series)) * 1.15

        fig_comb.update_yaxes(title_text="Total Effekt (kW)", secondary_y=False, range=[0, _kw_max])
        fig_comb.update_yaxes(title_text="Elpris (öre/kWh)", secondary_y=True, rangemode="tozero")

        plot(fig_comb, width="stretch")

    st.divider()
    st.subheader("📈 Laddningshistorik (Sparas i databasen)")
    try:
        ev_time = st.selectbox("Tidsperiod", ["Senaste dygnet", "Senaste 3 dygnen", "Senaste veckan"], key="ev_time")
        ev_hours = {"Senaste dygnet": 24, "Senaste 3 dygnen": 72, "Senaste veckan": 168}[ev_time]
        df_ev = pd.read_sql(text(f"SELECT timestamp, ev_power_kw, ev_current_a, ev_dynamic_limit_a FROM sensor_log WHERE timestamp >= NOW() - INTERVAL '{ev_hours} hours' AND ev_power_kw IS NOT NULL ORDER BY timestamp ASC"), engine)
        if not df_ev.empty:
            df_ev['timestamp'] = pd.to_datetime(df_ev['timestamp'], utc=True).dt.tz_convert('Europe/Stockholm')
            df_ev.set_index('timestamp', inplace=True)
            df_ev.rename(columns={"ev_power_kw": "Laddeffekt (kW)", "ev_current_a": "Ström (A)", "ev_dynamic_limit_a": "Dynamisk gräns (A)"}, inplace=True)
            df_melt = df_ev.reset_index().melt(id_vars='timestamp', var_name='Mätserie', value_name='Värde')
            chart = alt.Chart(df_melt).mark_line().encode(x=alt.X('timestamp:T'), y=alt.Y('Värde:Q'), color='Mätserie:N').interactive()
            st.altair_chart(chart, width="stretch")
    except Exception:
        pass
    render_ev_solar()

@st.cache_data(ttl=600)
def _ev_solar_cached():
    import pump_runtime as _pr
    with engine.connect() as _c:
        return _pr.ev_solar(_c)


def render_ev_solar():
    """Elbilarnas laddning: hur mycket som kom från solen (och vad det sparat)."""
    st.divider()
    st.subheader("☀️ Elbilar: solel i laddningen")
    try:
        ev = _ev_solar_cached()
    except Exception as e:
        st.info(f"Kunde inte räkna solel för elbilarna ({e}).")
        return
    if not ev:
        st.info("Ingen laddningsdata ännu.")
        return
    d = pd.DataFrame(ev)
    d["Månad"] = pd.to_datetime(d["manad"]).dt.strftime("%Y-%m")
    cur = d.iloc[-1]
    yr = d[pd.to_datetime(d["manad"]).dt.year == pd.to_datetime(cur["manad"]).year]
    y = pd.to_datetime(cur["manad"]).year
    pct = lambda a, b: f"{100 * a / max(1, b):.0f} %"
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Nissan: solel denna månad", f"{int(cur['lite_sol_kwh'])} kWh", f"{pct(cur['lite_sol_kwh'], cur['lite_kwh'])} av {int(cur['lite_kwh'])} kWh", delta_color="off")
    c2.metric("Tesla: solel denna månad", f"{int(cur['carport_sol_kwh'])} kWh", f"{pct(cur['carport_sol_kwh'], cur['carport_kwh'])} av {int(cur['carport_kwh'])} kWh", delta_color="off")
    c3.metric("Sparat denna månad", f"{int(cur['lite_kr'] + cur['carport_kr'])} kr")
    c4.metric(f"Sparat {y}", f"{int(yr['lite_kr'].sum() + yr['carport_kr'].sum())} kr")
    e1, e2 = st.columns(2)
    e1.metric(f"Nissan solel {y}", f"{int(yr['lite_sol_kwh'].sum())} kWh", f"{pct(yr['lite_sol_kwh'].sum(), yr['lite_kwh'].sum())} av {int(yr['lite_kwh'].sum())} kWh", delta_color="off")
    e2.metric(f"Tesla solel {y}", f"{int(yr['carport_sol_kwh'].sum())} kWh", f"{pct(yr['carport_sol_kwh'].sum(), yr['carport_kwh'].sum())} av {int(yr['carport_kwh'].sum())} kWh", delta_color="off")
    fig = go.Figure()
    fig.add_bar(x=d["Månad"], y=d["lite_sol_kwh"], name="Nissan solel", marker_color="#ffb300")
    fig.add_bar(x=d["Månad"], y=(d["lite_kwh"] - d["lite_sol_kwh"]).clip(lower=0), name="Nissan nätel", marker_color="#90a4ae")
    fig.add_bar(x=d["Månad"], y=d["carport_sol_kwh"], name="Tesla solel", marker_color="#ff7043")
    fig.add_bar(x=d["Månad"], y=(d["carport_kwh"] - d["carport_sol_kwh"]).clip(lower=0), name="Tesla nätel", marker_color="#546e7a")
    fig.update_layout(barmode="stack", height=320, margin=dict(l=10, r=10, t=30, b=10), yaxis_title="kWh", legend=dict(orientation="h", y=1.12))
    st.plotly_chart(fig, use_container_width=True)
    t = d[["Månad", "lite_kwh", "lite_sol_kwh", "lite_kr", "carport_kwh", "carport_sol_kwh", "carport_kr", "tackning_pct"]].rename(columns={
        "lite_kwh": "Nissan (kWh)", "lite_sol_kwh": "varav sol", "lite_kr": "Sparat (kr)", "carport_kwh": "Tesla (kWh)", "carport_sol_kwh": "varav sol ", "carport_kr": "Sparat (kr) ", "tackning_pct": "Loggtäckning (%)"})
    st.dataframe(t.iloc[::-1], hide_index=True, use_container_width=True)
    st.caption("Uppmätt laddeffekt från Easee-laddarna (Lite = Nissan Leaf, Carport = Tesla). Solandel per minut: den del av laddeffekten som inte importeras från nätet "
               "(elbilen som marginallast), bara medan solen producerar. Sparat = solel-kWh × inköpspris (spot × 1,25 + 0,62675 kr/kWh). "
               "Uppskalat för loggluckor. Om Tesla laddar i Easee Lite räknas det på Nissan-raden.")



# ══════════════════════════════════════════════════════════════════════════════
# 💸 ELPRISER
# ══════════════════════════════════════════════════════════════════════════════
def page_prices():
    render_refresh_button("prices")
    if settings:
        try:
            with engine.connect() as conn:
                next_qt = now + timedelta(minutes=15)
                nxt_row = conn.execute(text("SELECT sek_per_kwh FROM elpriser WHERE time_start <= :next AND time_end > :next"), {"next": next_qt}).fetchone()
                next_price_tab = float(nxt_row[0]) if nxt_row else None

            df_prices = pd.read_sql(text("""
                SELECT time_start AT TIME ZONE 'Europe/Stockholm' AS sthlm_time, sek_per_kwh FROM elpriser WHERE time_start >= :start AND time_start < :end ORDER BY time_start ASC
            """), engine, params={"start": today_start, "end": tomorrow_start})

            if not df_prices.empty:
                cheap_quarters_count = settings["cheap_hours_count"] * 4
                all_prices_tab = df_prices['sek_per_kwh'].tolist()
                dynamic_limit = sorted(all_prices_tab)[cheap_quarters_count - 1] if len(all_prices_tab) >= cheap_quarters_count else 0
                df_prices['t'] = pd.to_datetime(df_prices['sthlm_time']).dt.tz_localize(None)
                df_prices.set_index('t', inplace=True)
                full_idx = pd.date_range(start=today_start.replace(tzinfo=None), end=tomorrow_start.replace(tzinfo=None), freq='15min', inclusive='left')
                df_prices = df_prices.reindex(full_idx).ffill().reset_index()
                
                all_prices_tab = df_prices['sek_per_kwh'].dropna().tolist()
                cheap_quarters_count = min(len(all_prices_tab), settings["cheap_hours_count"] * 4)
                dynamic_limit = sorted(all_prices_tab)[cheap_quarters_count - 1] if cheap_quarters_count > 0 else 0
                strat_tab = nordpool.calculate_day_strategy(all_prices_tab, settings["cheap_hours_count"])
                h_tab     = strat_tab.get("hysteresis", 0)

                mc1, mc2, mc3 = st.columns(3)
                mc1.metric("📊 Smärtgräns idag", f"{dynamic_limit:.3f} kr/kWh")
                if current_live_price is not None:
                    mc2.metric("⚡ Pris just nu", f"{format_kr_ore(current_live_price)}/kWh")
                if next_price_tab is not None:
                    delta_p = next_price_tab - (current_live_price or 0)
                    mc3.metric("⏩ Nästa kvart", f"{format_kr_ore(next_price_tab)}/kWh",
                               delta=f"{delta_p:+.3f} kr", delta_color="inverse")

                if strat_tab["mode"] == "optimize" and h_tab > 0:
                    st.caption(f"Gråzon: {(dynamic_limit - h_tab):.3f} – {(dynamic_limit + h_tab):.3f} kr/kWh")

                df_prices['Tid'] = df_prices['index'].dt.strftime('%H:%M')
                df_display = df_prices[['Tid', 'sek_per_kwh']].rename(columns={'sek_per_kwh': 'Pris (kr/kWh)'}).dropna()
                df_display.set_index('Tid', inplace=True)

                def highlight_price(row):
                    p = row['Pris (kr/kWh)']
                    if p <= dynamic_limit - h_tab:
                        return ['background-color: rgba(46, 204, 113, 0.25)'] * len(row)
                    elif p <= dynamic_limit + h_tab:
                        return ['background-color: rgba(255, 193, 7, 0.20)'] * len(row)
                    return [''] * len(row)

                styled_df = df_display.style.apply(highlight_price, axis=1).format({'Pris (kr/kWh)': "{:.3f}"})
                cheap_count = len(df_prices[df_prices['sek_per_kwh'] <= dynamic_limit - h_tab])
                grey_count  = len(df_prices[(df_prices['sek_per_kwh'] > dynamic_limit - h_tab) & (df_prices['sek_per_kwh'] <= dynamic_limit + h_tab)])
                st.write(f"📊 **Dagens 96 kvartar – 🟢 {cheap_count} st billiga | 🟡 {grey_count} st gråzon**")
                st.dataframe(styled_df, width="stretch", height=400)
        except Exception as e:
            st.error(f"Kunde inte ladda priser: {e}")

# ══════════════════════════════════════════════════════════════════════════════
# 💰 EKONOMI
# ══════════════════════════════════════════════════════════════════════════════
def page_economy():
    try:
        month_start = today_start.replace(day=1)
        with engine.connect() as conn:
            today_prices = conn.execute(text("SELECT AVG(sek_per_kwh), MAX(sek_per_kwh), MIN(sek_per_kwh) FROM elpriser WHERE time_start >= :start AND time_start < :end"), {"start": today_start, "end": tomorrow_start}).fetchone()
            avg_price_today = float(today_prices[0]) if today_prices and today_prices[0] else 0.0
            max_price_today = float(today_prices[1]) if today_prices and today_prices[1] else 0.0
            min_price_today = float(today_prices[2]) if today_prices and today_prices[2] else 0.0
            
            month_prices = conn.execute(text("SELECT AVG(sek_per_kwh), MAX(sek_per_kwh), MIN(sek_per_kwh) FROM elpriser WHERE time_start >= :start AND time_start < :end"), {"start": month_start, "end": tomorrow_start}).fetchone()
            avg_price_month = float(month_prices[0]) if month_prices and month_prices[0] else 0.0
            max_price_month = float(month_prices[1]) if month_prices and month_prices[1] else 0.0
            min_price_month = float(month_prices[2]) if month_prices and month_prices[2] else 0.0

            df_month = pd.read_sql(text("""
                SELECT timestamp, net_power, pv_power_w, price, avg_w_tot
                FROM sensor_log
                WHERE timestamp >= :start
                ORDER BY timestamp ASC
            """), engine, params={"start": month_start})

            peaks_month_data = None
            if not df_month.empty:
                peaks_month_data = calculate_peaks_for_month(month_start)

        if not df_month.empty and peaks_month_data:
            peaks_month = peaks_month_data
            
            df_month['timestamp'] = pd.to_datetime(df_month['timestamp'], utc=True).dt.tz_convert('Europe/Stockholm')
            df_month = df_month.dropna(subset=['net_power', 'price'])

            df_month['full_cost_kwh'] = df_month['price'].apply(full_buy_cost)

            # kWh köpt från nätet och faktisk kostnad (inkl alla påslag)
            df_month['grid_kwh'] = df_month['net_power'].clip(lower=0) / 1000 / 60
            df_month['kostnad']  = df_month['grid_kwh'] * df_month['full_cost_kwh']

            df_month['export_kwh']    = (-df_month['net_power']).clip(lower=0) / 1000 / 60
            df_month['export_income'] = df_month['export_kwh'] * df_month['price'].apply(full_sell_income)

            # Egenanvänd sol = producerat - exporterat
            # Besparing = vad du slapp köpa, värderat i fullkostnad
            if 'pv_power_w' in df_month.columns:
                df_month['pv_power_w'] = df_month['pv_power_w'].fillna(0)
                export_w = (-df_month['net_power']).clip(lower=0)
                df_month['solar_self_use_kwh'] = (df_month['pv_power_w'] - export_w).clip(lower=0) / 1000 / 60
                df_month['solar_saving']       = df_month['solar_self_use_kwh'] * df_month['full_cost_kwh']
            else:
                df_month['solar_self_use_kwh'] = 0.0
                df_month['solar_saving']       = 0.0
                df_month['export_kwh']         = 0.0
                df_month['export_income']      = 0.0

            # VP-kostnad (från undermätaren avg_w_tot)
            if 'avg_w_tot' in df_month.columns:
                df_month['vp_kwh']    = df_month['avg_w_tot'].clip(lower=0).fillna(0) / 1000 / 60
                df_month['vp_kostnad'] = df_month['vp_kwh'] * df_month['full_cost_kwh']
            else:
                df_month['vp_kwh']    = 0.0
                df_month['vp_kostnad'] = 0.0

            mask_today = df_month['timestamp'] >= pd.Timestamp(today_start)
            df_today   = df_month[mask_today].copy()

            total_grid_kwh_today    = df_today['grid_kwh'].sum()
            actual_cost_today       = df_today['kostnad'].sum()
            solar_saving_today      = df_today['solar_saving'].sum()
            solar_self_kwh_today    = df_today['solar_self_use_kwh'].sum()
            export_kwh_today        = df_today['export_kwh'].sum()
            export_income_today     = df_today['export_income'].sum()
            vp_kwh_today            = df_today['vp_kwh'].sum()
            vp_kostnad_today        = df_today['vp_kostnad'].sum()
            
            # Baslinje (alternativkostnad) = samma kWh köpt till dygnets RAKA spotsnitt – inget dolt
            # profilpåslag. Transparent och konsekvent med den historiska besparingen (båda ×1,0).
            baseline_avg_today      = total_grid_kwh_today * full_buy_cost(avg_price_today)
            baseline_max_today      = total_grid_kwh_today * full_buy_cost(max_price_today)
            baseline_min_today      = total_grid_kwh_today * full_buy_cost(min_price_today)
            savings_avg_today       = baseline_avg_today - actual_cost_today
            savings_max_today       = baseline_max_today - actual_cost_today

            total_grid_kwh_month    = df_month['grid_kwh'].sum()
            actual_cost_month       = df_month['kostnad'].sum()
            solar_saving_month      = df_month['solar_saving'].sum()
            export_income_month     = df_month['export_income'].sum()
            export_kwh_month        = df_month['export_kwh'].sum()
            vp_kwh_month            = df_month['vp_kwh'].sum()
            vp_kostnad_month        = df_month['vp_kostnad'].sum()
            baseline_avg_month      = total_grid_kwh_month * full_buy_cost(avg_price_month)
            baseline_max_month      = total_grid_kwh_month * full_buy_cost(max_price_month)
            baseline_min_month      = total_grid_kwh_month * full_buy_cost(min_price_month)
            savings_avg_month       = baseline_avg_month - actual_cost_month

            # === Jämförelse mot en kund UTAN solceller (och utan smartstyrning) ===
            # En sådan kund köper HELA husets last (import + egenanvänd sol) till dygnets RAKA snitt
            # och har ingen exportintäkt. Skillnaden mot din faktiska NETTO-kostnad (faktisk rörlig
            # kostnad minus exportintäkt) = totalt värde av sol + smart styrning.
            nosolar_base_today    = (total_grid_kwh_today + solar_self_kwh_today) * full_buy_cost(avg_price_today)
            net_actual_today      = actual_cost_today - export_income_today
            savings_nosolar_today = nosolar_base_today - net_actual_today

            solar_self_kwh_month  = df_month['solar_self_use_kwh'].sum()
            nosolar_base_month    = (total_grid_kwh_month + solar_self_kwh_month) * full_buy_cost(avg_price_month)
            net_actual_month      = actual_cost_month - export_income_month
            savings_nosolar_month = nosolar_base_month - net_actual_month
            
            # --- NYA VARIABLAR FÖR SNITTPRISER ---
            full_avg_price_today = full_buy_cost(avg_price_today)
            user_avg_price_today = actual_cost_today / total_grid_kwh_today if total_grid_kwh_today > 0 else 0.0
            full_avg_price_month = full_buy_cost(avg_price_month)
            user_avg_price_month = actual_cost_month / total_grid_kwh_month if total_grid_kwh_month > 0 else 0.0

            # Totalkostnad Månad (Faktisk faktura-prognos).
            # Effekttariff tas bort ur fakturan när peak-shaving är av (= du har ingen effekttariff).
            _has_effekttariff = settings.get("peak_shaving_enabled", True)
            bas_cost = (peaks_month['avg_bas'] * 27.70) if _has_effekttariff else 0.0
            hog_cost = (peaks_month['avg_hog'] * 65.66) if _has_effekttariff else 0.0
            fixed_network = get_fixed_network_fee(now)
            fixed_tibber = 49.00
            total_monthly_bill = actual_cost_month + bas_cost + hog_cost + fixed_network + fixed_tibber - export_income_month

            st.subheader("📅 Idag (Hittills)")
            st.caption("Alternativkostnaden = ett hus UTAN solceller (och utan smartstyrning) som köper hela sin förbrukning – även det din sol täcker – till dygnets raka snittpris. Besparingen är skillnaden mot din faktiska nettokostnad (rörlig kostnad minus exportintäkt) och fångar både solnyttan och den smarta tajmingen.")
            
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("🔌 Förbrukning", f"{total_grid_kwh_today:.1f} kWh")
            c2.metric("📊 Dagens Snittpris", f"{full_avg_price_today:.2f} kr/kWh", help="Vad elen kostar i snitt idag (inkl. påslag, nät, skatt, moms)")
            
            delta_price_today = user_avg_price_today - full_avg_price_today
            c3.metric("🎯 Ditt Snittpris", f"{user_avg_price_today:.2f} kr/kWh", 
                      delta=f"{delta_price_today:+.2f} kr/kWh", delta_color="inverse", 
                      help="Ditt faktiska volymvägda snittpris idag, tack vare smartstyrning.")
            
            c4.metric("💡 Besparing vs hus utan sol", f"{max(0, savings_nosolar_today):.2f} kr", help="Total besparing idag jämfört med ett hus UTAN solceller (och utan smartstyrning) som köper hela sin förbrukning till dygnets snittpris. Inkluderar solel-egenanvändning, exportintäkt och smart tajming. Varav smart tajming på köpt el: " + f"{max(0, savings_avg_today):.2f} kr.")
            
            st.metric("💸 Faktisk Rörlig Kostnad (Idag)", f"{actual_cost_today:.2f} kr", 
                      f"Best Case: {baseline_min_today:.2f} kr | Worst Case: {baseline_max_today:.2f} kr", delta_color="off")

            if solar_self_kwh_today > 0 or export_kwh_today > 0:
                st.caption("Varav solbidrag (ingår redan i besparingen ovan):")
                s1, s2, s3 = st.columns(3)
                s1.metric("☀️ Solel egenanvänd", f"{solar_self_kwh_today:.1f} kWh",
                          f"Värde: {solar_saving_today:.2f} kr", delta_color="off")
                s2.metric("📤 Exporterad sol", f"{export_kwh_today:.1f} kWh",
                          f"Intäkt: {export_income_today:.2f} kr", delta_color="off")
                s3.metric("🌞 Total Solnytta (Idag)",
                          f"{solar_saving_today + export_income_today:.2f} kr", delta_color="off")

            if vp_kwh_today > 0:
                st.divider()
                st.caption("♨️ Värmepump (undermätare)")
                v1, v2 = st.columns(2)
                v1.metric("⚡ VP Förbrukning", f"{vp_kwh_today:.1f} kWh")
                v2.metric("💸 VP Kostnad", f"{vp_kostnad_today:.2f} kr",
                          f"{vp_kostnad_today / vp_kwh_today:.2f} kr/kWh snitt" if vp_kwh_today > 0 else "", delta_color="off")

            st.divider()
            st.subheader("📆 Denna månad (Hittills)")
            
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("🔌 Förbrukning", f"{total_grid_kwh_month:.1f} kWh")
            m2.metric("📊 Månadens Snittpris", f"{full_avg_price_month:.2f} kr/kWh")
            delta_price_month = user_avg_price_month - full_avg_price_month
            m3.metric("🎯 Ditt Snittpris", f"{user_avg_price_month:.2f} kr/kWh", 
                      delta=f"{delta_price_month:+.2f} kr/kWh", delta_color="inverse")
            m4.metric("💡 Besparing vs hus utan sol", f"{max(0, savings_nosolar_month):.0f} kr", help="Total besparing denna månad jämfört med ett hus utan solceller (och utan smartstyrning) som köper all el till månadens snittpris. Inkluderar solnytta + smart tajming. Varav smart tajming på köpt el: " + f"{max(0, savings_avg_month):.0f} kr.")
            
            m_cost1, m_cost2 = st.columns(2)
            m_cost1.metric("💸 Faktisk Rörlig Kostnad", f"{actual_cost_month:.0f} kr", 
                      f"Best Case: {baseline_min_month:.0f} kr | Worst Case: {baseline_max_month:.0f} kr", delta_color="off")
            m_cost2.metric("🧾 Total Fakturaprognos (Månad)", f"{total_monthly_bill:.0f} kr",
                      help="Inkluderar fasta avgifter, effekttariff och elhandel, minus såld el.")
                      
            if solar_saving_month > 0 or export_income_month > 0:
                st.caption("Varav solbidrag (ingår redan i besparingen ovan):")
                ms1, ms2, ms3 = st.columns(3)
                ms1.metric("☀️ Solel egenanvänd", f"{solar_saving_month:.0f} kr",
                           f"{df_month['solar_self_use_kwh'].sum():.0f} kWh värde", delta_color="off")
                ms2.metric("📤 Exportintäkt", f"{export_income_month:.0f} kr",
                           f"{export_kwh_month:.0f} kWh intäkt", delta_color="off")
                ms3.metric("🌞 Total Solnytta (Månad)", f"{solar_saving_month + export_income_month:.0f} kr", delta_color="off")
                           
            st.divider()
            st.subheader("💰 Kostnad & Besparing per dag")
            st.caption("Grafen visar din faktiska kostnad inbäddad mellan 'Best Case' (om all din el köpts på dygnets billigaste timme) och 'Worst Case' (om all el köpts på dygnets dyraste). Snittpriset visar vad det hade kostat om du förbrukat din energi jämnt över dygnet.")
            
            df_month['Datum'] = df_month['timestamp'].dt.date
            df_daily = df_month.groupby('Datum').agg(
                grid_kwh=('grid_kwh', 'sum'),
                kostnad=('kostnad', 'sum'),
            ).reset_index()
            
            daily_prices = df_month.groupby('Datum')['price'].agg(['mean', 'min', 'max']).reset_index()
            df_daily = pd.merge(df_daily, daily_prices, on='Datum')
            df_daily['alt_avg'] = df_daily['grid_kwh'] * df_daily['mean'].apply(full_buy_cost)
            df_daily['alt_min'] = df_daily['grid_kwh'] * df_daily['min'].apply(full_buy_cost)
            df_daily['alt_max'] = df_daily['grid_kwh'] * df_daily['max'].apply(full_buy_cost)
            
            fig_daily = go.Figure()
            fig_daily.add_trace(go.Bar(x=df_daily['Datum'], y=df_daily['kostnad'], name='Faktisk Kostnad', marker_color='#3498db'))
            fig_daily.add_trace(go.Scatter(x=df_daily['Datum'], y=df_daily['alt_max'], name='Worst Case (Dyrast)', mode='lines', line=dict(color='#ff6b6b', dash='dot', width=2)))
            fig_daily.add_trace(go.Scatter(x=df_daily['Datum'], y=df_daily['alt_avg'], name='Snittpris (Alternativkostnad)', mode='lines', line=dict(color='#d35400', dash='dash', width=2)))
            fig_daily.add_trace(go.Scatter(x=df_daily['Datum'], y=df_daily['alt_min'], name='Best Case (Billigast)', mode='lines', line=dict(color='#27ae60', dash='dot', width=2)))
            
            fig_daily.update_layout(
                template="plotly_dark", 
                hovermode="x unified", 
                barmode='group', 
                legend=dict(orientation="h", yanchor="bottom", y=1.05, xanchor="center", x=0.5),
                margin=dict(l=20, r=20, t=40, b=20)
            )
            fig_daily.update_yaxes(title_text="Kostnad (kr)")
            plot(fig_daily, width="stretch")
            
            st.divider()
            with st.expander("🧾 Detaljerad Fakturaprognos (Månad)"):
                st.markdown(f"**Jönköping Energi (Elnät)**")
                st.markdown(f"- Fast Nätavgift (20A): **{fixed_network:.2f} kr**")
                if _has_effekttariff:
                    st.markdown(f"- Effektavgift Baslast ({peaks_month['avg_bas']:.2f} kW × 27.70 kr): **{bas_cost:.2f} kr**")
                    st.markdown(f"- Effektavgift Höglast ({peaks_month['avg_hog']:.2f} kW × 65.66 kr): **{hog_cost:.2f} kr**")
                else:
                    st.markdown("- Effektavgift: **0 kr** *(effekttariff borttagen från nätavtalet)*")
                st.caption(f"*(Överföring & Energiskatt ingår i rörliga elhandelskostnaden nedan)*")
                
                st.markdown(f"**Tibber (Elhandel & Skatter)**")
                st.markdown(f"- Tibber Månadsavgift: **{fixed_tibber:.2f} kr**")
                st.markdown(f"- Rörligt (Spot + Påslag + Skatt + Överföring): **{actual_cost_month:.2f} kr**")
                st.markdown(f"- Såld El (Spot + Nätnytta): **-{export_income_month:.2f} kr**")
                
                st.markdown(f"### Totalt att betala: {total_monthly_bill:.0f} kr")

            if vp_kwh_month > 0:
                st.divider()
                st.caption("♨️ Värmepump (undermätare)")
                mv1, mv2 = st.columns(2)
                mv1.metric("⚡ VP Förbrukning", f"{vp_kwh_month:.0f} kWh")
                mv2.metric("💸 VP Kostnad", f"{vp_kostnad_month:.0f} kr",
                           f"{vp_kostnad_month / vp_kwh_month:.2f} kr/kWh snitt" if vp_kwh_month > 0 else "", delta_color="off")

        st.divider()
        st.subheader("📊 Historisk Besparing (vs hus utan solceller)")
        st.caption("Total besparing per månad jämfört med ett hus UTAN solceller (och utan smartstyrning) som köpt hela sin förbrukning till månadens raka snittpris. Inkluderar solel-egenanvändning, exportintäkt och smart tajming.")
        try:
            df_hist_savings = pd.read_sql(text("""
                SELECT 
                    DATE_TRUNC('month', timestamp AT TIME ZONE 'Europe/Stockholm') as month_ts,
                    SUM(GREATEST(net_power, 0) / 1000.0 / 60.0) as total_grid_kwh,
                    SUM((GREATEST(net_power, 0) / 1000.0 / 60.0) * price) as actual_spot_cost,
                    SUM(GREATEST(COALESCE(pv_power_w, 0) - GREATEST(-net_power, 0), 0) / 1000.0 / 60.0) as solar_self_kwh,
                    SUM(GREATEST(-net_power, 0) / 1000.0 / 60.0) as export_kwh
                FROM sensor_log
                WHERE timestamp >= NOW() - INTERVAL '12 months' AND price IS NOT NULL
                GROUP BY 1 ORDER BY 1
            """), engine)
            df_avg_prices = pd.read_sql(text("""
                SELECT 
                    DATE_TRUNC('month', time_start AT TIME ZONE 'Europe/Stockholm') as month_ts,
                    AVG(sek_per_kwh) as avg_spot_price
                FROM elpriser
                WHERE time_start >= NOW() - INTERVAL '12 months'
                GROUP BY 1 ORDER BY 1
            """), engine)
            if not df_hist_savings.empty and not df_avg_prices.empty:
                df_hist_savings['month_ts'] = pd.to_datetime(df_hist_savings['month_ts']).dt.tz_localize(None)
                df_avg_prices['month_ts'] = pd.to_datetime(df_avg_prices['month_ts']).dt.tz_localize(None)
                df_hist_savings = pd.merge(df_hist_savings, df_avg_prices, on='month_ts')
                df_hist_savings['actual_full_cost'] = (df_hist_savings['actual_spot_cost'] * 1.25) + (df_hist_savings['total_grid_kwh'] * 0.62675)
                # Kund UTAN solceller (och utan smartstyrning): köper HELA lasten (import + egenanvänd
                # sol) till månadens raka snitt och har ingen exportintäkt.
                df_hist_savings['nosolar_cost'] = (df_hist_savings['total_grid_kwh'] + df_hist_savings['solar_self_kwh'].fillna(0)) * df_hist_savings['avg_spot_price'].apply(full_buy_cost)
                df_hist_savings['export_income'] = df_hist_savings['export_kwh'].fillna(0) * df_hist_savings['avg_spot_price'].apply(full_sell_income)
                df_hist_savings['net_actual_cost'] = df_hist_savings['actual_full_cost'] - df_hist_savings['export_income']
                df_hist_savings['savings'] = df_hist_savings['nosolar_cost'] - df_hist_savings['net_actual_cost']
                df_hist_savings['Månad'] = df_hist_savings['month_ts'].dt.strftime('%Y-%m')
                
                sc1, sc2 = st.columns(2)
                sc1.metric("💡 I år", f"{max(0, df_hist_savings[df_hist_savings['month_ts'].dt.year == datetime.now(SWE_TZ).year]['savings'].sum()):.0f} kr")
                sc2.metric("💡 Rullande 12 mån", f"{max(0, df_hist_savings['savings'].sum()):.0f} kr")
                
                fig_sav = go.Figure(go.Bar(x=df_hist_savings['Månad'], y=df_hist_savings['savings'].clip(lower=0), marker_color='#2ecc71', name='Besparing (kr)'))
                fig_sav.update_layout(template="plotly_dark", title="Besparing vs hus utan solceller per Månad (kr)")
                plot(fig_sav, width="stretch")
        except Exception as e:
            st.error(f"Kunde inte ladda historisk besparing: {e}")

        # FIX: Timgrafen låg tidigare inne i except (visades bara vid fel) och else-grenen
        # var en try-else som visade "Ingen förbrukning" när besparingen lyckades. Nu visas
        # timgrafen alltid när dagens data finns, annars info-texten.
        if not df_today.empty:
            st.divider()
            st.write("📈 **Kostnad per timme idag (kr):**")
            df_today['Timme'] = df_today['timestamp'].dt.strftime('%H:00')
            df_hourly = df_today.groupby('Timme')['kostnad'].sum().reset_index()
            st.bar_chart(df_hourly.set_index('Timme'), color="#ff4b4b")
        else:
            st.info("Ingen förbrukning loggad ännu.")
    except Exception as e:
        if "does not exist" in str(e):
            pass
        else:
            st.error(f"Kunde inte ladda ekonomi: {e}")

# ══════════════════════════════════════════════════════════════════════════════
# 🌤️ VÄDER
# ══════════════════════════════════════════════════════════════════════════════
def page_weather():
    try:
        df_weather = pd.read_sql(text("""
            SELECT timestamp AT TIME ZONE 'Europe/Stockholm' AS sthlm_time, temp, cloud_cover, wind_speed, wind_dir FROM weather_forecast WHERE timestamp >= :start AND timestamp <= :end ORDER BY timestamp ASC
        """), engine, params={"start": now.replace(tzinfo=None).replace(minute=0, second=0), "end": (now + timedelta(hours=24)).replace(tzinfo=None)})
        if not df_weather.empty:
            _weather_solar_prof = learning.get_solar_profile()
            df_weather['Sol (W)'] = df_weather.apply(
                lambda r: pred.get_smart_solar_w(r['cloud_cover'], pd.to_datetime(r['sthlm_time']), _weather_solar_prof), axis=1
            )
            df_weather['Tid'] = pd.to_datetime(df_weather['sthlm_time']).dt.strftime('%a %H:%M')
            df_w = df_weather[['Tid', 'temp', 'cloud_cover', 'wind_speed', 'wind_dir', 'Sol (W)']].rename(columns={
                'temp': 'Temp (°C)', 'cloud_cover': 'Moln (%)', 'wind_speed': 'Vind (m/s)', 'wind_dir': 'Vindriktning (°)'
            })
            st.dataframe(df_w.set_index('Tid'), width="stretch", height=400)
            st.caption("☀️ Sol (W) = uppskattad produktion baserat på molntäcke.")
    except Exception as e:
        if "does not exist" in str(e):
            pass
        else:
            st.error(f"Kunde inte ladda väder: {e}")

# ══════════════════════════════════════════════════════════════════════════════
# 📅 PROGNOS – Värmepumpens förväntade schema
# ══════════════════════════════════════════════════════════════════════════════
def page_forecast_plan():
    st.subheader("AI:ns Pris- & Solprognos (Tidsfönster)")
    st.caption(
        "Detta är grundschemat som AI:n utgår från de kommande 48 timmarna. "
        "GPM-motorn (Master Logic) använder detta för att planera uppvärmning för värmepump, elbil och spabad. "
        "Faktisk drift styrs minut-för-minut och kan avvika (t.ex. om effektvakten stryper lasten)."
    )

    cheap_h = settings["cheap_hours_count"] if settings else 8
    predictions = pred.predict_schedule(cheap_hours_count=cheap_h)

    if predictions:
        now_fc = datetime.now(SWE_TZ)

        # ── Filtrera: idag vs imorgon ──────────────────────────────────────
        today_fc = now_fc.replace(hour=0, minute=0, second=0, microsecond=0)
        pred_today = [p for p in predictions if p["time"].date() == today_fc.date()]
        pred_tomorrow = [p for p in predictions if p["time"].date() == (today_fc + timedelta(days=1)).date()]

        day_tabs = ["Idag"]
        if pred_tomorrow:
            day_tabs.append("Imorgon")
        day_sel = st.radio("Visa", day_tabs, horizontal=True)
        active_pred = pred_today if day_sel == "Idag" else pred_tomorrow

        if active_pred:
            sessions = pred.group_sessions(active_pred)
            summary  = pred.format_summary_lines(sessions, active_pred)

            # ── Textsummering ──────────────────────────────────────────────
            st.markdown("#### Systemets optimering förväntas bli:")
            for line in summary:
                st.markdown(line)

            st.divider()

            # ── Tidslinje ─────────────────────────────────────────────────
            st.markdown("#### 24-timmars tidslinje")

            COLOR_MAP = {
                "solar_heat":  "#27ae60",   # Mörkgrön – sol värme
                "solar_water": "#2ecc71",   # Ljusgrön – sol varmvatten
                "cheap":       "#3498db",   # Blå – billig el
                "comfort":     "#9b59b6",   # Lila – komfortläge
                "grayzone":    "#f39c12",   # Orange – gråzon
                "expensive":   "#e74c3c",   # Röd – dyr el
            }
            LABEL_MAP = {
                "solar_heat":  "☀️ Solöverskott (>500W)",
                "solar_water": "🚿 Solöverskott (>100W)",
                "cheap":       "💰 Billig el (Under gräns)",
                "comfort":     "😌 Jämt pris (Komfort)",
                "grayzone":    "⏸️ Normalpris (Gråzon)",
                "expensive":   "🔴 Dyr el (Över gräns)",
            }

            # --- Hämta och Beräkna Data för Effektdiagrammet ---
            ev_schedule = settings_module.get_ev_schedule()
            nissan_soc = safe_float('sensor.leaf_battery_level')
            tesla_soc = safe_float('sensor.tesla_model_y_battery')
            joint_plan_df, _ = create_joint_ev_plan(ev_schedule, nissan_soc, tesla_soc)
            
            spa_target_dt = settings.get("spa_target_datetime")
            spa_sched_enabled = settings.get("spa_schedule_enabled", False)
            spa_plan_df = None
            # Fix 8: spa_plan_df_for_forecast delades tidigare mellan flikar (modulscope). Nu är varje
            # sida en egen funktion → variabeln finns inte här. Sätt None så vi faller till else-grenen
            # nedan som räknar om spa-planen (samma resultat, utan korsflik-beroende).
            spa_plan_df_for_forecast = None
            if spa_sched_enabled and spa_target_dt:
                if spa_plan_df_for_forecast is not None and not spa_plan_df_for_forecast.empty:
                    spa_plan_df = spa_plan_df_for_forecast
                else:
                    try:
                        curr_spa_temp = float(ha_state('sensor.spa_malmgatan_34_current_temperature', 38.0))
                    except:
                        curr_spa_temp = 38.0
                    out_temp = row.get('outdoor_temp', 0) if row is not None else 0
                    model_intercept, model_slope_out, model_slope_spa = learning.get_heating_rate_model()
                    cooling_k, _ = learning.get_cooling_rate_model()
                    spa_max = float(settings.get("spa_max_temp", 40.0))
                    spa_normal = float(settings.get("spa_normal_temp", 34.0))
                    if spa_target_dt.tzinfo is None:
                        spa_target_dt = spa_target_dt.replace(tzinfo=zoneinfo.ZoneInfo("UTC")).astimezone(SWE_TZ)
                    else:
                        spa_target_dt = spa_target_dt.astimezone(SWE_TZ)
                    spa_plan_df = pred.get_spa_schedule_plan(now_fc, spa_target_dt, curr_spa_temp, model_intercept, model_slope_out, model_slope_spa, cooling_k, float(settings.get("spa_target_temp") or 38.0), spa_max, spa_normal, out_temp, float(settings.get("spa_low_temp", 15.0)))
                
            base_load_profile = learning.get_base_load_profile()
            
            df_fc_rows = []
            for p in active_pred:
                t = p["time"]
                t_naive = t.replace(tzinfo=None)
                
                baslast_kw = learning.predict_base_load(t, base_load_profile)
                
                if p["runs"] is True:
                    pump_kw = 2.5
                elif p["runs"] is None:
                    pump_kw = 1.0  # Pumpen går på underhåll/sparlåga i gråzonen
                else:
                    pump_kw = 0.0
                
                nissan_kw = 0.0
                tesla_kw = 0.0
                if joint_plan_df is not None and not joint_plan_df.empty:
                    # LÖSNING PÅ SYNK-FELET: Hämta medelvärdet för Hela timmen (alla 4 kvartar), 
                    # annars missas laddning som ligger på XX:15, XX:30 eller XX:45.
                    ev_rows = joint_plan_df[(joint_plan_df['t_slot'] >= t_naive) & (joint_plan_df['t_slot'] < t_naive + timedelta(hours=1))]
                    if not ev_rows.empty:
                        n_mean = ev_rows['nissan_kw'].mean()
                        t_mean = ev_rows['tesla_kw'].mean()
                        nissan_kw = float(n_mean) if pd.notna(n_mean) else 0.0
                        tesla_kw = float(t_mean) if pd.notna(t_mean) else 0.0
                        
                spa_kw = 0.0
                if spa_plan_df is not None and not spa_plan_df.empty:
                    # Gör samma fix för spabadet för säkerhets skull
                    spa_rows = spa_plan_df[(spa_plan_df['t_slot'] >= t_naive) & (spa_plan_df['t_slot'] < t_naive + timedelta(hours=1))]
                    if not spa_rows.empty and spa_rows['is_heating'].any():
                        spa_kw = 3.0
                
                df_fc_rows.append({
                    "Tid":        t,
                    "Sluttid":    p["time_end"],
                    "Anledning":  p.get("reason_label", LABEL_MAP.get(p["reason"], p["reason"])),
                    "Pris (öre)": round(p["price"] * 100, 1),
                    "Sol (W)":    p["solar_w"],
                    "Sol (kW)":   p["solar_w"] / 1000.0,
                    "Baslast (kW)": baslast_kw,
                    "Värmepump (kW)": pump_kw,
                    "Spabad (kW)": spa_kw,
                    "Nissan Leaf (kW)": nissan_kw,
                    "Tesla Model Y (kW)": tesla_kw,
                })
            
            df_fc = pd.DataFrame(df_fc_rows)

            fig_fc = make_subplots(specs=[[{"secondary_y": True}]])
            
            # Lägg till solcellerna som ett fyllt område i bakgrunden (Primär Y)
            fig_fc.add_trace(go.Scatter(
                x=df_fc['Tid'], 
                y=df_fc['Sol (kW)'], 
                name="Solprognos", 
                mode='lines', 
                fill='tozeroy', fillcolor='rgba(211, 84, 0, 0.15)',
                line=dict(color='#d35400', width=2, dash='dot'),
                hovertemplate="Sol: %{y:.2f} kW<extra></extra>"
            ), secondary_y=False)
            
            # Skapa stacked bars för effekten (Primär Y)
            fig_fc.add_trace(go.Bar(x=df_fc['Tid'], y=df_fc['Baslast (kW)'], name="Baslast", marker_color='#95a5a6'), secondary_y=False)
            fig_fc.add_trace(go.Bar(x=df_fc['Tid'], y=df_fc['Värmepump (kW)'], name="Värmepump", marker_color='#3498db'), secondary_y=False)
            fig_fc.add_trace(go.Bar(x=df_fc['Tid'], y=df_fc['Spabad (kW)'], name="Spabad", marker_color='#e67e22'), secondary_y=False)
            fig_fc.add_trace(go.Bar(x=df_fc['Tid'], y=df_fc['Nissan Leaf (kW)'], name="Nissan Leaf", marker_color='#2ecc71'), secondary_y=False)
            fig_fc.add_trace(go.Bar(x=df_fc['Tid'], y=df_fc['Tesla Model Y (kW)'], name="Tesla Model Y", marker_color='#e74c3c'), secondary_y=False)
            
            fig_fc.add_trace(go.Scatter(
                x=df_fc['Tid'], 
                y=df_fc['Pris (öre)'], 
                name="Elpris (öre/kWh)", 
                mode='lines', 
                line=dict(color='#bdc3c7', width=2, shape='hv'), 
                customdata=df_fc['Anledning'],
                hovertemplate="Pris: %{y:.1f} öre<br>Status: %{customdata}<extra></extra>"
            ), secondary_y=True)
            
            fig_fc.update_layout(
                template="plotly_dark", hovermode="x unified", barmode='stack',
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5),
                margin=dict(l=10, r=10, t=30, b=10)
            )
            fig_fc.update_yaxes(title_text="Effekt & Sol (kW)", secondary_y=False, rangemode='tozero')
            fig_fc.update_yaxes(title_text="Elpris (öre/kWh)", secondary_y=True)

            # Nu-linje: visa direkt var i tiden vi är (x-axeln är tz-naiv)
            try:
                fig_fc.add_vline(x=now_fc.replace(tzinfo=None), line_width=2, line_dash="dash",
                                 line_color="#ffffff", opacity=0.6,
                                 annotation_text="nu", annotation_position="top")
            except Exception:
                pass

            plot(fig_fc, width="stretch")

            # ── Detaljtabell ───────────────────────────────────────────────
            with st.expander("Visa detaljtabell"):
                df_show = df_fc[["Tid", "Anledning", "Pris (öre)", "Sol (W)", "Baslast (kW)", "Värmepump (kW)", "Spabad (kW)", "Nissan Leaf (kW)", "Tesla Model Y (kW)"]].copy()
                df_show["Tid"] = df_show["Tid"].dt.strftime("%H:%M")
                st.dataframe(df_show.set_index("Tid"), width="stretch", height=400)
        else:
            st.info("Inga prisdata hittades för vald dag.")
    else:
        st.warning("Kunde inte generera prognos – saknas prisdata eller väderdata i databasen.")

# ══════════════════════════════════════════════════════════════════════════════
# 📈 HISTORIK
# ══════════════════════════════════════════════════════════════════════════════
def page_history():
    AVAILABLE_METRICS = {
        "Elpris (Loggat) (kr/kWh)":              "price",
        "Elpris (Prognos framåt) (kr/kWh)":      "price_forecast",
        "Husets Totala Förbrukning (W)":          "house_consumption_w",
        "Nettoeffekt (Mot Nätet) (W)":            "net_power",
        "Solproduktion (W)":                      "pv_power_w",
        "Snitteffekt (Pump) (W)":                 "avg_w_tot",
        "Innetemperatur (°C)":                    "indoor_temp",
        "Utetemperatur (°C)":                     "outdoor_temp",
        "Varmvatten (°C)":                        "water_temp",
        "Framledning (°C)":                       "forward_temp",
        "Retur (°C)":                             "return_temp",
        "Cirkulationspump Värme (0/1)":           "pump_heat_running",
        "Kompressor PÅ (0/1)":                    "compressor_running",
        "Förbrukning (kWh)":                      "consumed_kwh",
        "Molnighet (%)":                          "cloud_cover",
        "Vindhastighet (m/s)":                    "wind_speed",
        "Batteri SOC (%)":                        "battery_soc",
        "Batterieffekt (W)":                      "battery_power_w",
        "Solproduktion idag (kWh)":               "solar_today_kwh",
        "Nissan Laddeffekt (kW)":                 "ev_power_kw",
        "Tesla Laddeffekt (kW)":                  "ev_carport_power_kw",
        "Nissan SOC (%)":                         "nissan_soc",
        "Tesla SOC (%)":                          "tesla_soc",
        "Spabad Temp (°C)":                       "spa_temp",
        "Spabad Måltemp (°C)":                    "spa_target",
        "Spabad Värmare PÅ (0/1)":                "spa_heater_running",
        "Temp Vardagsrum (°C)":                   "temp_vardagsrum",
        "Temp Garage (°C)":                       "temp_garage",
        "Husets Avsvalning (°C/h)":               "predicted_cooling_rate",
    }

    col_time, col_metrics = st.columns([1, 3])
    with col_time:
        time_range = st.selectbox("Tidsperiod", ["Senaste dygnet", "Senaste 3 dygnen", "Senaste veckan", "All data"], key="history_time_range")
        limit_hours = {"Senaste dygnet": 24, "Senaste 3 dygnen": 72, "Senaste veckan": 168, "All data": 9999}[time_range]
    with col_metrics:
        selected_names = st.multiselect(
            "Välj data att visa",
            options=list(AVAILABLE_METRICS.keys()),
            default=["Elpris (Prognos framåt) (kr/kWh)", "Solproduktion (W)", "Innetemperatur (°C)"]
        )

    if selected_names:
        log_cols = []
        wants_price_forecast = False
        for name in selected_names:
            col = AVAILABLE_METRICS[name]
            if col == "price_forecast":
                wants_price_forecast = True
            else:
                log_cols.append(col)
        try:
            df_final = get_historical_dataframe(limit_hours, tuple(log_cols), wants_price_forecast)
            if not df_final.empty:
                df_final.rename(columns={val: key for key, val in AVAILABLE_METRICS.items()}, inplace=True)
                df_melt = df_final.reset_index().melt(id_vars='timestamp', var_name='Mätserie', value_name='Värde')
                chart = alt.Chart(df_melt).mark_line(strokeWidth=3).encode(
                    x=alt.X('timestamp:T', axis=alt.Axis(title='Tid', format='%H:%M\n%Y-%m-%d', labelOverlap=True)),
                    y=alt.Y('Värde:Q', title='Värde'),
                    color=alt.Color('Mätserie:N', legend=alt.Legend(title="Valda data", orient='bottom')),
                    tooltip=['timestamp:T', 'Mätserie:N', 'Värde:Q']
                ).interactive()
                st.altair_chart(chart, width="stretch")
            else:
                st.info("Ingen historik hittades för den valda perioden.")
        except Exception as e:
            if "does not exist" in str(e):
                pass
            else:
                st.error(f"Kunde inte rita graf: {e}")

# ══════════════════════════════════════════════════════════════════════════════
# ⚙️ INSTÄLLNINGAR
# ══════════════════════════════════════════════════════════════════════════════
def page_settings():
    if settings:
        with st.form("settings_form"):
            c1, c2 = st.columns(2)
            with c1:
                st.subheader("Elprisanpassning")
                cheap_hours = st.slider("Antal billiga timmar/dygn", min_value=1, max_value=24, value=settings["cheap_hours_count"], help="Hur många timmar per dygn anser du vara 'billiga'? Systemet kommer försöka lägga huvuddelen av all uppvärmning under dessa timmar.")
            with c2:
                pass
            
            submitted = st.form_submit_button("💾 Spara inställningar")
            if submitted:
                save_settings(
                    cheap_hours,
                    settings.get("temp_cheap", 22.0),
                    settings.get("temp_expensive", 20.0),
                    settings.get("indoor_max", 22.5),
                    settings.get("indoor_min", 19.0),
                    settings.get("legionella_temp", 60.0),
                    settings.get("legionella_days", 14),
                    settings.get("water_target_normal", 50.0)
                )
                st.rerun()
            
        st.divider()
        st.subheader("Cool Factor (ROI & AI)")
        with st.form("extra_settings_form"):
            new_roi = st.number_input("Hårdvarukostnad (kr) för ROI-mätning", value=float(settings.get("roi_hardware_cost", 0.0)), step=1000.0)
            new_gemini = st.text_input("Gemini API Key (För Chatbot)", value=settings.get("gemini_api_key", ""), type="password")
            if st.form_submit_button("💾 Spara Extrafunktioner"):
                try:
                    with engine.begin() as conn:
                        conn.execute(text("UPDATE system_settings SET roi_hardware_cost = :roi, gemini_api_key = :key WHERE id = 1"), {"roi": new_roi, "key": new_gemini})
                    st.success("✅ Extrafunktioner sparade!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Kunde inte spara: {e}")
    else:
        st.error("Kunde inte ladda inställningar.")

# ══════════════════════════════════════════════════════════════════════════════
# 🔔 AVISERINGAR
# ══════════════════════════════════════════════════════════════════════════════
def page_notifications():
    st.caption("Här kan du aktivera/avaktivera ALLA händelser som skickas direkt till din telefon (Emils telefon).")
    
    _ovr = get_overrides()
    def get_ov_bool(key, default=True):
        val = _ovr.get(key)
        if val is None or val == "auto": return default
        return val.lower() == "true"

    if settings:
        with st.form("notify_settings_form"):
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("#### 🛁 Spabad")
                val_spa = st.toggle("✅ Spabadet har nått sin måltemperatur", value=settings.get("notify_spa_ready", True))
                val_spa_open = st.toggle("⚠️ Varning om onormal värmeförlust (glömt lock)", value=settings.get("notify_spa_open", True))
                val_spa_boost = st.toggle("☀️ Sol-boost startar/stoppar", value=get_ov_bool("notify_spa_boost", True))
                val_spa_reconnect = st.toggle("🔌 Spabad återanslutet (efter nedtid)", value=get_ov_bool("notify_spa_reconnect", True))
                
                st.markdown("#### ⚡ Elbil & Hushåll")
                val_ev = st.toggle("🚗 Laddning startar", value=settings.get("notify_ev_start", True))
                val_ev_full = st.toggle("✅ Laddning slutförd (Fullt batteri)", value=get_ov_bool("notify_ev_full", True))
                val_washer = st.toggle("🧺 Tvättmaskin startar", value=settings.get("notify_washer_start", True))

                st.markdown("#### 🤖 Robotgräsklippare")
                val_mower_mowing = st.toggle("✅ Klipparen startar", value=get_ov_bool("notify_mower_mowing", True))
                val_mower_charging = st.toggle("🔌 Klipparen laddar", value=get_ov_bool("notify_mower_charging", True))
                val_mower_idle = st.toggle("💤 Klipparen vilar", value=get_ov_bool("notify_mower_idle", False))
                val_mower_weather = st.toggle("🌦️ Väderstyrning av/på", value=get_ov_bool("notify_mower_weather", True))
                val_mower_manual = st.toggle("🔌 Manuell av/på av strömmen", value=get_ov_bool("notify_mower_manual", True))
                val_mower_failsafe = st.toggle("🚨 Failsafe-larm (5 min)", value=get_ov_bool("notify_mower_failsafe", True))

            with c2:
                st.markdown("#### 💸 Elpriser & System")
                val_price_tip = st.toggle("🌅 Morgonens elpristips", value=get_ov_bool("notify_price_tip", True))
                val_high_low = st.toggle("💸 Varning för extremt högt/lågt spotpris", value=get_ov_bool("notify_high_low", True))
                val_peak = st.toggle("⚠️ Peak Shaving: Varning när effekttaket hotas", value=get_ov_bool("notify_peak_shaving", True))
                
                st.markdown("#### 🔧 Värmepump & Sensorer")
                val_pump_alarm = st.toggle("🚨 Värmepump: Larm och felkoder", value=get_ov_bool("notify_pump_alarm", True))
                val_pump_mode = st.toggle("⚙️ Värmepump: Automatiskt byte av driftläge", value=get_ov_bool("notify_pump_mode", False))
                val_solar_err = st.toggle("☀️ Solceller: Växelriktare offline / fel", value=get_ov_bool("notify_solar_error", True))
                val_solar_lim = st.toggle("📉 Solceller: Produktion begränsas av AI", value=get_ov_bool("notify_solar_limit", True))
            
            if st.form_submit_button("💾 Spara aviseringsval"):
                with engine.begin() as conn:
                    conn.execute(text("UPDATE system_settings SET notify_spa_ready=:nsr, notify_spa_open=:nso, notify_ev_start=:nes, notify_washer_start=:nws WHERE id=1"), 
                                 {"nsr": val_spa, "nso": val_spa_open, "nes": val_ev, "nws": val_washer})
                set_override_db("notify_spa_boost", str(val_spa_boost).lower())
                set_override_db("notify_spa_reconnect", str(val_spa_reconnect).lower())
                set_override_db("notify_ev_full", str(val_ev_full).lower())
                set_override_db("notify_price_tip", str(val_price_tip).lower())
                set_override_db("notify_high_low", str(val_high_low).lower())
                set_override_db("notify_peak_shaving", str(val_peak).lower())
                set_override_db("notify_pump_alarm", str(val_pump_alarm).lower())
                set_override_db("notify_pump_mode", str(val_pump_mode).lower())
                set_override_db("notify_solar_error", str(val_solar_err).lower())
                set_override_db("notify_mower_mowing", str(val_mower_mowing).lower())
                set_override_db("notify_mower_charging", str(val_mower_charging).lower())
                set_override_db("notify_mower_idle", str(val_mower_idle).lower())
                set_override_db("notify_mower_weather", str(val_mower_weather).lower())
                set_override_db("notify_mower_manual", str(val_mower_manual).lower())
                set_override_db("notify_mower_failsafe", str(val_mower_failsafe).lower())
                set_override_db("notify_solar_limit", str(val_solar_lim).lower())
                st.success("✅ Aviseringsinställningarna är sparade!")
                time.sleep(1)
                st.rerun()

    st.divider()
    st.markdown("##### Skicka test-avisering")
    with st.form("test_notify_form"):
        test_message = st.text_area("Meddelande", "Detta är ett testmeddelande från EnergyWizard-dashboarden.")
        submitted = st.form_submit_button("📢 Skicka till min mobil")
        if submitted:
            ha_ip = os.environ.get("HA_IP")
            ha_token = os.environ.get("HA_TOKEN", "").strip("\"'")
            url = f"https://{ha_ip}:8123/api/services/notify/mobile_app_emils_telefon"
            headers = {"Authorization": f"Bearer {ha_token}", "Content-Type": "application/json"}
            try:
                r = requests.post(url, headers=headers, json={"title": "Test från EnergyWizard", "message": test_message}, timeout=5, verify=False)
                r.raise_for_status()
                st.success("✅ Avisering skickad!")
            except Exception as e:
                st.error(f"❌ Kunde inte skicka avisering: {e}")

# ══════════════════════════════════════════════════════════════════════════════
# 🏠 HOME ASSISTANT
# ══════════════════════════════════════════════════════════════════════════════
def page_ha():
    st.subheader("Enheter från Home Assistant (Live)")
    st.caption("Här hämtas dina enheter och deras aktuella värden direkt från Home Assistant via REST API.")

    ha_ip = os.environ.get("HA_IP")
    ha_token = os.environ.get("HA_TOKEN")

    if not ha_ip or not ha_token:
        st.warning("⚠️ HA_IP eller HA_TOKEN saknas i miljövariablerna för dashboarden.")
    else:
        if ha_data:
            df_ha = pd.DataFrame([{
                "Enhet (Entity ID)": s.get("entity_id"),
                "Värde / Status": str(s.get("state")),
                "Namn (Friendly Name)": str(s.get("attributes", {}).get("friendly_name", "")),
                "Attribut (Dolda värden)": str({k: v for k, v in s.get("attributes", {}).items() if k != "friendly_name"}),
                "Senast uppdaterad": s.get("last_updated")
            } for s in ha_data.values()])
            
            if not df_ha.empty:
                try:
                    df_ha['Senast uppdaterad'] = pd.to_datetime(df_ha['Senast uppdaterad']).dt.tz_convert('Europe/Stockholm').dt.strftime('%Y-%m-%d %H:%M:%S')
                except Exception:
                    pass

            c1, c2 = st.columns([2, 1])
            with c1:
                search = st.text_input("🔍 Sök på enhet (t.ex. 'sensor.temp' eller 'lampa')")
            with c2:
                st.metric("Totalt antal enheter", f"{len(df_ha)} st")

            if search:
                df_ha = df_ha[df_ha["Enhet (Entity ID)"].str.contains(search, case=False, na=False) | 
                              df_ha["Namn (Friendly Name)"].str.contains(search, case=False, na=False)]
            
            st.dataframe(df_ha, width="stretch", height=500)
        else:
            st.info("Inga enheter hittades.")

# ── Driftsinstruktioner ─────────────────────────────────────────────────────────
def page_docs():
    cfg_d = load_settings()
    t_cheap   = cfg_d.get("temp_cheap",    22.0)
    t_exp     = cfg_d.get("temp_expensive",20.0)
    i_max     = cfg_d.get("indoor_max",    22.5)
    i_min     = cfg_d.get("indoor_min",    19.0)
    ch_hours  = cfg_d.get("cheap_hours_count", 8)

    st.header("📖 Driftsinstruktioner")
    st.caption("Hur systemet fattar beslut – uppdateras automatiskt när inställningar ändras.")

    st.subheader("1. Prisstrategi – när är elen billig?")
    st.markdown(f"""
Varje dag beräknas en **dynamisk prisgräns** baserat på dagens alla timpriskvartlar, sorterade stigande.
Gränsen sätts till det **{ch_hours}:e billigaste timsvärdet** – d.v.s. systemet siktar på att köra
under de {ch_hours} billigaste timmarna per dygn *(inställningsbart under ⚙️ Inställningar)*.

**Strategival:**
- Om dagssnittet < 0,50 kr **och** spreaden < 0,30 kr → **Komfortläge**: pumpen kör 21 °C hela dagen, ingen optimering.
- Annars → **Optimeringsläge**: hysteres = 15 % av dagens spread, begränsat 5–20 öre.

| Läge | Villkor | Rumstemperatur | Varmvatten |
|------|---------|---------------|------------|
| 🟢 Billig el | Pris ≤ gräns − hysteres | {t_cheap} °C | PÅ |
| 🔴 Dyr el   | Pris ≥ gräns + hysteres | {t_exp} °C | AV |
| ⏸️ Gråzon   | Däremellan              | Håller föregående läge | – |

**Gråzon med behovskoll:** Om systemet håller *Billig*-läget i gråzonen men innetempen
är ≥ {i_min + 1.5:.1f} °C (dvs. {i_min:.0f} + 1,5 °C) **och** varmvattnet ≥ 50 °C
→ byter systemet direkt till *Dyr*-läge och sparar energi.
""")

    st.subheader("2. Solöverskott – när kör pumpen på sol?")
    st.markdown(f"""
Solläget aktiveras när **nätöverskottet överstiger 500 W** för uppvärmning, eller **100 W** för varmvatten.

**Behovskoll (gäller alltid):**
Även om det finns överskott startar systemet *inte* sol-läget om:
- Innetempen ≥ {i_min + 1.5:.1f} °C **och** varmvattnet ≥ 50 °C

I så fall säljs överskottet till nätet i stället. Typiskt innebär detta att morgonsolens
överskott säljs, och pumpen värderas in när behovet faktiskt finns (ofta runt
middagstid när priserna också är lägre).

**Lägesval – värme eller varmvatten?**
Det som har störst procentuellt underskott mot sitt börvärde väljs:
- **Sol-Varmvatten:** Laddar varmvattenberedaren (mål 50 °C).
- **Sol-Värme:** Värmer rummet mot {t_cheap} °C – kräver dessutom att nästa kvarts
  solprognos > 100 W (förhindrar start precis när ett moln drar in).

**30-minutersspärr:** När kompressorn väl startar i sol-läge är det låst i minst 30 min
för att skydda kompressorns livslängd. Sol och värme är ömsesidigt uteslutande – aldrig båda samtidigt.
""")

    st.subheader("3. Inomhustemperatur – tak och golv")
    st.markdown(f"""
| Gräns | Värde | Effekt |
|-------|-------|--------|
| Maxtak | {i_max} °C | Pumpen sänker till *dyrläge* ({t_exp} °C) även om elen är billig |
| Komfortgolv | {i_min} °C | Används som referens; > {i_min + 1.5:.1f} °C = behovet anses uppfyllt |

Pumpen stängs aldrig av helt – *dyrläge* ({t_exp} °C) innebär att kompressorn håller golvet
men inte aktivt värmer utöver det.
""")

    st.subheader("4. Elbil (Easee)")
    st.markdown("""
Laddströmmen begränsas dynamiskt baserat på husets fasbelastning:

    Tillgänglig ström = 16 A (säkring) − 1 A (marginal) − högst belastade fas

Mäts var 10:e sekund och uppdateras kontinuerligt. Minsta laddström är 6 A.
""")


# ══════════════════════════════════════════════════════════════════════════════
# 🧭 NAVIGERING (fix 8) – nästlade föräldrasidor + st.navigation
#   Bara den AKTIVA sidan körs per rerun (mot tidigare: alla 13 flikar varje gång).
# ══════════════════════════════════════════════════════════════════════════════
def page_temperaturer():
    _list, _karta = st.tabs(["📋 Lista", "🗺️ Karta"])
    with _list:  page_temps_list()
    with _karta: page_heatmap()

def page_prognos():
    _plan, _priser, _vader = st.tabs(["📈 Plan", "💸 Elpriser", "🌤️ Väder"])
    with _plan:   page_forecast_plan()
    with _priser: page_prices()
    with _vader:  page_weather()

def page_system():
    _ha, _mower, _docs = st.tabs(["🏠 Home Assistant", "🤖 Robotgräsklippare", "📖 Driftsinstruktioner"])
    with _ha:    page_ha()
    with _mower: page_mower()
    with _docs:  page_docs()

_nav = st.navigation([
    st.Page(page_overview,      title="📊 Översikt",       url_path="oversikt", default=True),
    st.Page(page_economy,       title="💰 Ekonomi",        url_path="ekonomi"),
    st.Page(page_power,         title="🔌 Elförbrukning",  url_path="elforbrukning"),
    st.Page(page_ev,            title="⚡ Elbil",          url_path="elbil"),
    st.Page(page_pump,          title="♨️ Värmepump",      url_path="varmepump"),
    st.Page(page_solar,         title="☀️ Solceller",      url_path="solceller"),
    st.Page(page_spa,           title="🛁 Spabad",         url_path="spabad"),
    st.Page(page_temperaturer,  title="🌡️ Temperaturer",   url_path="temperaturer"),
    st.Page(page_prognos,       title="📅 Prognos",        url_path="prognos"),
    st.Page(page_history,       title="📈 Historik",       url_path="historik"),
    st.Page(page_settings,      title="⚙️ Inställningar",   url_path="installningar"),
    st.Page(page_notifications, title="🔔 Aviseringar",    url_path="aviseringar"),
    st.Page(page_system,        title="🛠️ System",         url_path="system"),
])
_nav.run()
