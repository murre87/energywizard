"""
predictor.py – Simulerar beslutslogiken framåt i tid.

Hämtar elpris + väderprognos från databasen och kör samma besluts-
logik som main.py för varje timme. Returnerar en lista med prediktion
per timme: kör / kör inte / gråzon, med anledning.
"""

import math
import pandas as pd
import learning
import decisions
import nordpool
from datetime import datetime, timedelta
import zoneinfo

SWE_TZ = zoneinfo.ZoneInfo("Europe/Stockholm")

from database_engine import engine
from sqlalchemy import text

def get_smart_solar_w(cloud_cover, dt, solar_profile):
    """Säker wrapper ifall weather.py i containern inte är helt synkad."""
    import weather
    if hasattr(weather, 'get_smart_solar_w'):
        return weather.get_smart_solar_w(cloud_cover, dt, solar_profile)
    
    # Fallback till lokal logik om weather.py är gammal i Docker
    roof_max = solar_profile.get((dt.month, dt.hour)) if solar_profile else None
    if roof_max is not None:
        return max(0.0, roof_max * (1.0 - (cloud_cover / 100.0) * 0.85))
    return weather.estimate_solar_w(cloud_cover, dt)

def predict_schedule(cheap_hours_count=8):
    """
    Simulerar styrningen framåt i tiden baserat på elpris och väder.
    Returnerar en lista med dictionarys (prediktioner) per kvart/timme.
    """
    now = datetime.now(SWE_TZ)
    start_dt = now.replace(minute=0, second=0, microsecond=0)
    end_dt = start_dt + timedelta(days=2)

    try:
        with engine.connect() as conn:
            df_prices = pd.read_sql(text("""
                SELECT time_start AT TIME ZONE 'Europe/Stockholm' AS t, sek_per_kwh
                FROM elpriser
                WHERE time_start >= :start AND time_start < :end
                ORDER BY time_start ASC
            """), conn, params={"start": start_dt, "end": end_dt})

            df_weather = pd.read_sql(text("""
                SELECT timestamp AT TIME ZONE 'Europe/Stockholm' AS t, cloud_cover, wind_speed, temp
                FROM weather_forecast
                WHERE timestamp >= :start AND timestamp < :end
            """), conn, params={"start": start_dt, "end": end_dt})

            row = conn.execute(text("SELECT indoor_temp, target_room_temp FROM sensor_log ORDER BY timestamp DESC LIMIT 1")).fetchone()
            current_indoor = float(row[0]) if row and row[0] is not None else 20.0
            target_indoor = float(row[1]) if row and row[1] is not None else 20.0
    except Exception as e:
        print(f"Fel vid prediktion: {e}")
        return []

    if df_prices.empty:
        return []

    # Spara undan timpriserna för strategiberäkning innan vi samplar upp
    df_prices_hourly = df_prices.copy()
    df_prices_hourly['date'] = pd.to_datetime(df_prices_hourly['t']).dt.date
    daily_strategies = {}
    for date, group in df_prices_hourly.groupby('date'):
        daily_strategies[date] = nordpool.calculate_day_strategy(group['sek_per_kwh'].tolist(), cheap_hours_count)

    # Sampla upp dataramen till 15-minuters intervall för att matcha EV/Spabad
    df_prices['t'] = pd.to_datetime(df_prices['t']).dt.tz_localize(None)
    df_prices.set_index('t', inplace=True)
    max_t = df_prices.index.max()
    full_idx = pd.date_range(start=start_dt.replace(tzinfo=None), end=max_t + pd.Timedelta(minutes=45), freq='15min')
    df_prices = df_prices.reindex(full_idx).ffill().reset_index().rename(columns={'index': 't'})

    weather_by_hour = {}
    if not df_weather.empty:
        for _, w_row in df_weather.iterrows():
            # Håll allt tz-NAIVT (DB-tider kommer redan naiva via AT TIME ZONE).
            w_t = pd.to_datetime(w_row['t']).tz_localize(None) if pd.to_datetime(w_row['t']).tzinfo else pd.to_datetime(w_row['t'])
            weather_by_hour[w_t] = {
                "cloud": float(w_row['cloud_cover']),
                "wind": float(w_row['wind_speed']),
                "temp": float(w_row['temp'])
            }

    bl_profile = learning.get_base_load_profile()
    house_model = learning.get_house_cooling_rate_model()
    solar_profile = learning.get_solar_profile()

    
    # Initiera energibudget (överskottsvärme i grader)
    thermal_budget = max(0.0, current_indoor - target_indoor)

    results = []
    for _, price_row in df_prices.iterrows():
        hour_dt = pd.to_datetime(price_row['t'])
        if hour_dt.tzinfo is not None:
            hour_dt = hour_dt.tz_localize(None)  # håll naiv – matchar df_weather['t']

        # Hämta rätt strategi för den specifika dagen
        strat = daily_strategies.get(hour_dt.date(), nordpool.calculate_day_strategy([], cheap_hours_count))
        limit = strat["dynamic_limit"]
        h     = strat["hysteresis"]
        price    = float(price_row['sek_per_kwh'])
        hour_key = hour_dt.replace(minute=0, second=0, microsecond=0)
        
        w_data   = weather_by_hour.get(hour_key, {"cloud": 50.0, "wind": 0.0, "temp": 0.0})
        cloud    = w_data["cloud"]
        wind     = w_data["wind"]
        out_t    = w_data["temp"]
        
        solar_w  = get_smart_solar_w(cloud, hour_dt, solar_profile)
        
        # 2. Vindavkyld utetemperatur (Wind Chill - anpassad för Jönköping)
        if out_t < 10 and wind > 1.3: # 1.3 m/s motsvarar ca 4.8 km/h, vilket formeln kräver för att vara giltig
            v_kmh = wind * 3.6 # Formeln kräver vindhastighet i km/h
            eff_out_t = 13.12 + 0.6215 * out_t - 11.37 * (v_kmh ** 0.16) + 0.3965 * out_t * (v_kmh ** 0.16)
        else:
            eff_out_t = out_t
            
        # 3. Solinstrålning (Solar Gains)
        # Om solen lyser starkt mitt på dagen ökar vi vår energibudget proaktivt
        if 10 <= hour_dt.hour <= 15 and cloud < 30:
            thermal_budget += 0.15 # Grader "gratis" värme per kvart
            
        # Hämta historisk rullande sol från df_weather om möjligt (förenklad i prognosen)
        solar_w_roll_3h = solar_w
        if not df_weather.empty:
            past_mask = (df_weather['t'] >= hour_dt - timedelta(hours=3)) & (df_weather['t'] <= hour_dt)
            past_weather = df_weather[past_mask]
            if not past_weather.empty:
                past_weather['est_sol'] = past_weather.apply(lambda r: get_smart_solar_w(r['cloud_cover'], pd.to_datetime(r['t']), solar_profile), axis=1)
                solar_w_roll_3h = past_weather['est_sol'].mean()

        # 4. Husets Värmetröghet (Avkylning över tid)
        delta_t = current_indoor - eff_out_t
        cooling_rate = learning.predict_house_cooling_rate(eff_out_t, wind, solar_w, solar_w_roll_3h, hour_dt.hour, house_model)
        thermal_decay = cooling_rate / 4.0 # Grader per kvart
        thermal_budget = max(0.0, thermal_budget - thermal_decay)

        # Ersätt hårdkodade 800W med ML-tvillingen!
        dynamic_base_w = learning.predict_base_load(hour_dt, bl_profile) * 1000.0
        est_net  = dynamic_base_w - solar_w  # negativt = vi säljer

        # 1. Master Kill Switch (Hard stop vid värmeöverskott) prioriteras först
        is_heating_fast_by_sun = (cloud < 30 and 10 <= hour_dt.hour <= 15)
        
        if thermal_budget > 0.5:
            runs, reason, label = False, "overheating", f"🛑 Stoppad (Värmeöverskott {thermal_budget:.1f}°C)"
        elif is_heating_fast_by_sun and thermal_budget > 0.2:
            runs, reason, label = False, "overheating", f"🛑 Proaktivt stopp (Snabbt stigande sol-värme)"
        elif strat["mode"] == "comfort":
            runs, reason, label = True,  "comfort",      "😌 Jämt pris (Komfort)"
        elif est_net < -500:
            runs, reason, label = True,  "solar_heat",   f"☀️ Solöverskott ({solar_w:.0f} W)"
        elif est_net < -100:
            runs, reason, label = True,  "solar_water",  f"🚿 Litet solöverskott ({solar_w:.0f} W)"
        elif limit is not None and price <= limit - h:
            runs, reason, label = True,  "cheap",        f"🟢 Billig el ({price:.3f} kr)"
        elif limit is not None and price >= limit + h:
            runs, reason, label = False, "expensive",    f"🔴 Dyr el ({price:.3f} kr)"
        else:
            runs, reason, label = None,  "grayzone",     f"⏸️ Gråzon ({price:.3f} kr)"

        results.append({
            "time":          hour_dt,
            "time_end":      hour_dt + timedelta(minutes=15),
            "price":         price,
            "solar_w":       solar_w,
            "estimated_net": est_net,
            "runs":          runs,
            "reason":        reason,
            "reason_label":  label,
        })

    return results


def group_sessions(predictions):
    """
    Grupperar konsekutiva 'runs=True'-block till sessioner.

    Returnerar lista med dict:
      start       – datetime
      end         – datetime
      reasons     – set av reason-strängar i sessionen
      peak_solar  – högsta estimerade soleffekten under sessionen (W)
      min_price   – billigaste priset under sessionen
    """
    sessions = []
    current  = None

    for p in predictions:
        if p["runs"] is True:
            if current is None:
                current = {
                    "start":      p["time"],
                    "end":        p["time_end"],
                    "reasons":    {p["reason"]},
                    "peak_solar": p["solar_w"],
                    "min_price":  p["price"],
                }
            else:
                current["end"]        = p["time_end"]
                current["reasons"].add(p["reason"])
                current["peak_solar"] = max(current["peak_solar"], p["solar_w"])
                current["min_price"]  = min(current["min_price"],  p["price"])
        else:
            if current:
                sessions.append(current)
                current = None

    if current:
        sessions.append(current)
    return sessions


def format_summary_lines(sessions, predictions):
    """
    Returnerar en lista med läsbara rader för textsummeringen.
    Exempelrad: '☀️ 11:00–13:15  Sol (~4 200 W produktion)'
    """
    if not sessions:
        return ["Inga körtillfällen hittades för vald period."]

    lines = []
    for s in sessions:
        start = s["start"].strftime("%H:%M")
        end   = s["end"].strftime("%H:%M")

        if "solar_heat" in s["reasons"] or "solar_water" in s["reasons"]:
            icon = "☀️"
            detail = f"Sol (~{s['peak_solar']:.0f} W)"
        elif "cheap" in s["reasons"]:
            icon = "💰"
            detail = f"Billig el ({s['min_price']:.3f} kr/kWh)"
        else:
            icon = "😌"
            detail = "Komfortläge"

        lines.append(f"{icon} **{start}–{end}**  {detail}")

    total_runs = sum(1 for p in predictions if p["runs"] is True)
    stop_count = len(sessions) - 1  # stopp mellan sessionerna
    lines.append(f"\n*Totalt ~{total_runs/4:.1f} h körning, {stop_count} avbrott under perioden.*")
    return lines

def get_spa_schedule_plan(now_dt, target_dt, curr_temp, model_intercept, model_slope_out, model_slope_spa, cooling_k, target_temp, spa_max_temp, spa_normal_temp, outdoor_temp, spa_low_temp=15.0):
    """
    Simulerar spabadets temperaturutveckling framåt i tiden baserat på väder och elpriser.
    Låg till Streamlit, men flyttad hit för att hålla affärslogiken i backend.
    """
    try:
        with engine.connect() as conn:
            df_p = pd.read_sql(text("""
                SELECT time_start AT TIME ZONE 'Europe/Stockholm' AS t, sek_per_kwh as price
                FROM elpriser
                WHERE time_start >= :start AND time_start <= :end
                ORDER BY time_start ASC
            """), conn, params={"start": now_dt.replace(minute=0, second=0), "end": target_dt + timedelta(hours=1)})
            df_w = pd.read_sql(text("""
                SELECT timestamp AT TIME ZONE 'Europe/Stockholm' AS t, cloud_cover, temp
                FROM weather_forecast
                WHERE timestamp >= :start AND timestamp <= :end
            """), conn, params={"start": now_dt.replace(minute=0, second=0), "end": target_dt + timedelta(hours=1)})
    except Exception as e:
        print(f"Fel vid hämtning av schemadata för spa: {e}")
        return None

    target_dt_naive = target_dt.replace(tzinfo=None)
    now_dt_naive = now_dt.replace(tzinfo=None).replace(minute=0, second=0, microsecond=0)
    
    full_idx_15 = pd.date_range(start=now_dt_naive, end=target_dt_naive + timedelta(hours=1), freq='15min')
    solar_profile = learning.get_solar_profile()

    if not df_p.empty:
        df_p['t'] = pd.to_datetime(df_p['t']).dt.tz_localize(None)
        df_p.set_index('t', inplace=True)
        df_plan = df_p.reindex(full_idx_15).ffill().bfill().reset_index().rename(columns={'index': 't_slot'})
        df_plan['t_hour'] = df_plan['t_slot'].dt.floor('h')
    else:
        df_plan['price'] = 0.5
        df_plan = pd.DataFrame({'t_slot': full_idx_15, 'price': 0.5})

    if not df_w.empty:
        df_w['t_hour'] = pd.to_datetime(df_w['t']).dt.floor('h').dt.tz_localize(None)
        df_w['solar_w'] = df_w.apply(lambda r: get_smart_solar_w(r['cloud_cover'], r['t_hour'], solar_profile), axis=1)
        hourly_solar = df_w.groupby('t_hour')['solar_w'].mean().reset_index()
        
        df_plan['t_hour'] = df_plan['t_slot'].dt.floor('h')
        df_plan = pd.merge(df_plan, hourly_solar, on='t_hour', how='left').fillna({'solar_w': 0})
        hourly_temp = df_w.groupby('t_hour')['temp'].mean().reset_index()
        df_plan = pd.merge(df_plan, hourly_temp, on='t_hour', how='left')
        df_plan['temp'] = df_plan['temp'].ffill().bfill().fillna(outdoor_temp or 10.0)
    else:
        df_plan['solar_w'] = 0
        df_plan['temp'] = outdoor_temp

    df_plan['score'] = df_plan['price']
    df_plan['hour_val'] = df_plan['t_slot'].dt.hour
    df_plan.loc[(df_plan['hour_val'] >= 7) & (df_plan['hour_val'] < 20), 'score'] += 1.5 
    df_plan['hours_from_target'] = (target_dt_naive - df_plan['t_slot']).dt.total_seconds() / 3600.0
    df_plan['score'] += df_plan['hours_from_target'] * 0.05
    df_plan.loc[df_plan['solar_w'] > 1500, 'score'] -= 10.0

    df_plan['is_heating'] = False
    valid_mask = (df_plan['t_hour'] >= now_dt_naive) & (df_plan['t_hour'] < target_dt_naive)
    available_idx = df_plan[valid_mask].sort_values('score').index.tolist()
    target_hour = target_dt_naive.replace(minute=0, second=0, microsecond=0)
    
    ct_initial = float(curr_temp)
    temp_at_target_initial = ct_initial
    for i, r in df_plan.iterrows():
        if r['t_slot'] == target_hour:
            temp_at_target_initial = ct_initial
        T_env = df_plan.loc[i, 'temp']
        T_new = T_env + (ct_initial - T_env) * math.exp(-cooling_k * 0.25)
        ct_initial = max(T_new, float(spa_low_temp))
            
    if temp_at_target_initial < float(target_temp):
        for idx in available_idx:
            df_plan.at[idx, 'is_heating'] = True
            ct = float(curr_temp)
            temp_at_target = ct
            for i, r in df_plan.iterrows():
                if r['t_slot'] == target_hour:
                    temp_at_target = ct
                if r['is_heating']:
                    current_heating_rate = learning.predict_heating_rate(outdoor_temp, ct, model_intercept, model_slope_out, model_slope_spa)
                    ct += (current_heating_rate * 0.25)
                    max_t = float(spa_max_temp) if r['solar_w'] > 1500 else float(target_temp)
                    ct = min(ct, max_t)
                else:
                    T_env = df_plan.loc[i, 'temp']
                    T_new = T_env + (ct - T_env) * math.exp(-cooling_k * 0.25)
                    ct = max(T_new, float(spa_low_temp))
            if temp_at_target >= float(target_temp):
                break
                
    def get_label(r):
        if not r['is_heating']: return "Vilar"
        if r['solar_w'] > 1500: return "☀️ Solenergi"
        if r['hours_from_target'] <= 12: return "🔥 Värmer (Nära mål)"
        return "💰 Billig el (Planerad)"
        
    df_plan['Aktivitet'] = df_plan.apply(get_label, axis=1)
    df_plan['t_hour_end'] = df_plan['t_hour'] + pd.Timedelta(hours=1)
    
    df_plan = df_plan.sort_values('t_slot').reset_index(drop=True)
    sim_temps, start_temps = [], []
    ct = float(curr_temp)
    for i, r in df_plan.iterrows():
        start_temps.append(ct)
        if r['is_heating']:
            current_heating_rate = learning.predict_heating_rate(outdoor_temp, ct, model_intercept, model_slope_out, model_slope_spa)
            ct += (current_heating_rate * 0.25)
            max_t = float(spa_max_temp) if r['solar_w'] > 1500 else float(target_temp)
            ct = min(ct, max_t)
        else:
            T_env = df_plan.loc[i, 'temp']
            T_new = T_env + (ct - T_env) * math.exp(-cooling_k * 0.25)
            ct = max(T_new, float(spa_low_temp))
        sim_temps.append(ct)
        
    df_plan['Start Temp'] = [round(t, 1) for t in start_temps]
    df_plan['Simulerad Temp'] = [round(t, 1) for t in sim_temps]
    
    return df_plan

def simulate_ev_soc_plan(now_dt, ev_schedule, nissan_soc, tesla_soc, cfg, nissan_phases, tesla_phases, nissan_plugged_in=True, tesla_plugged_in=True):
    """
    Genererar elbilens laddplan och simulerar SOC per kvart framåt i tiden.
    Returnerar en ifylld dataframe.
    """
    # Konvertera schemats nycklar från textsträngar till heltal
    norm_schedule = {}
    for car, days in ev_schedule.items():
        norm_schedule[car] = {int(k): v for k, v in days.items() if str(k).isdigit()}
    ev_schedule = norm_schedule

    car_data = {
        'nissan_soc': nissan_soc, 
        'tesla_soc': tesla_soc,
        'nissan_phases': nissan_phases,
        'tesla_phases': tesla_phases,
        'nissan_plugged_in': nissan_plugged_in,
        'tesla_plugged_in': tesla_plugged_in
    }
    df_plan = decisions.calculate_ev_charge_plan(now_dt, ev_schedule, car_data, cfg)
    
    if df_plan.empty:
        return df_plan

    sim_nissan_soc = nissan_soc if nissan_soc is not None else 0.0
    sim_tesla_soc = tesla_soc if tesla_soc is not None else 0.0

    df_plan.sort_values('t_slot', inplace=True)
    df_plan['nissan_start_soc'] = 0.0
    df_plan['nissan_end_soc'] = 0.0
    df_plan['tesla_start_soc'] = 0.0
    df_plan['tesla_end_soc'] = 0.0

    for idx, row in df_plan.iterrows():
        df_plan.at[idx, 'nissan_start_soc'] = sim_nissan_soc
        kwh_added_nissan = row['nissan_kw'] / 4.0
        soc_added_nissan = (kwh_added_nissan / 40.0) * 100.0 if kwh_added_nissan > 0 else 0
        sim_nissan_soc += soc_added_nissan
        df_plan.at[idx, 'nissan_end_soc'] = sim_nissan_soc

        df_plan.at[idx, 'tesla_start_soc'] = sim_tesla_soc
        kwh_added_tesla = row['tesla_kw'] / 4.0
        soc_added_tesla = (kwh_added_tesla / 75.0) * 100.0 if kwh_added_tesla > 0 else 0
        sim_tesla_soc += soc_added_tesla
        df_plan.at[idx, 'tesla_end_soc'] = sim_tesla_soc
        
    return df_plan
