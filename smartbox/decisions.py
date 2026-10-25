"""
decisions.py – Beslutslogik för värmepump och spabad

Separerad från main.py för att hålla styrlogiken samlad och testbar.

Regler:
 - Sol-överskott ger antingen värme ELLER varmvatten, aldrig båda.
 - Det som ligger sämst till (längst från sitt börvärde) väljs.
 - Valt läge låses i minst PUMP_MIN_MINUTES för att skydda kompressorn.
"""

from datetime import datetime, timedelta
import math
import learning
import pandas as pd
import logger
import weather
import settings

# Lastbalansering – Easee elbilsladdare
MAX_FUSE_A  = 25    # Huvudsäkring (A)
EV_MIN_A    = 6     # Easees lägsta laddström
EV_MARGIN_A = 1     # Säkerhetsmarginal mot säkringen

# Prisvarningar
PRICE_HIGH_MULTIPLIER = 2.0   # Notis om priset är >2× dagens snitt
PRICE_LOW_THRESHOLD   = 0.05  # Notis om priset är under 5 öre

# Varmvattenlägen som skickas till pumpen
WATER_ON  = 2
WATER_OFF = 0

def safe_get_smart_solar_w(cloud_cover, dt):
    """Säkerhetsfunktion ifall weather.py i containern inte är synkad."""
    import weather
    if hasattr(weather, 'get_smart_solar_w'):
        return weather.get_smart_solar_w(cloud_cover, dt)
    import learning
    solar_profile = learning.get_solar_profile()
    roof_max = solar_profile.get((dt.month, dt.hour)) if solar_profile else None
    if roof_max is not None:
        return max(0.0, roof_max * (1.0 - (cloud_cover / 100.0) * 0.85))
    return weather.estimate_solar_w(cloud_cover, dt)


def is_price_high(current_price, all_prices):
    """Returnerar True om priset är >2× dagens snitt."""
    if not all_prices:
        return False
    return current_price >= (sum(all_prices) / len(all_prices)) * PRICE_HIGH_MULTIPLIER


def is_price_low(current_price):
    """Returnerar True om priset är under 5 öre."""
    return current_price <= PRICE_LOW_THRESHOLD


def check_spa_schedule_plan(now, target_dt, curr_temp, target_temp, model_intercept, model_slope_out, model_slope_spa, cooling_k, spa_max_temp, outdoor_temp, spa_low_temp=15.0):  # FIX: tog bort oanvänd param spa_normal_temp
    """Kollar om nuvarande timme är vald för uppvärmning baserat på pris och framtida solprognos."""
    try:
        import pandas as pd
        import math
        import logger as sm_logger
        import weather

        now_hour = now.replace(minute=0, second=0, microsecond=0)
        now_slot = now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0)
        target_dt_naive = target_dt.replace(tzinfo=None)
        now_dt_naive = now_slot.replace(tzinfo=None)

        with sm_logger.get_db() as conn:
            df_p = pd.read_sql("""
                SELECT time_start AT TIME ZONE 'Europe/Stockholm' AS t, sek_per_kwh as price
                FROM elpriser
                WHERE time_start >= %s AND time_start <= %s
            """, conn, params=(now_hour, target_dt + timedelta(hours=1)))

            df_w = pd.read_sql("""
                SELECT timestamp AT TIME ZONE 'Europe/Stockholm' AS t, cloud_cover, temp
                FROM weather_forecast
                WHERE timestamp >= %s AND timestamp <= %s
            """, conn, params=(now_hour, target_dt + timedelta(hours=1)))

        full_idx = pd.date_range(start=now_dt_naive, end=target_dt_naive + timedelta(hours=1), freq='15min')
        
        if not df_p.empty: # Prisdata
            df_p['t'] = pd.to_datetime(df_p['t']).dt.tz_localize(None)
            df_p.set_index('t', inplace=True)
            # Sommartid -> normaltid (sista söndagen i oktober): klockan 02 finns två gånger i lokal tid. Behåll första så indexet blir unikt.
            df_p = df_p[~df_p.index.duplicated(keep='first')]
            df_plan = df_p.reindex(full_idx).ffill().bfill().reset_index().rename(columns={'index': 't_slot'})
        else:
            df_plan = pd.DataFrame({'t_slot': full_idx, 'price': 0.5})

        if not df_w.empty: # Väderdata
            df_w['t_hour'] = pd.to_datetime(df_w['t']).dt.floor('h').dt.tz_localize(None)
            df_w['solar_w'] = df_w.apply(lambda r: safe_get_smart_solar_w(r['cloud_cover'], r['t_hour'].replace(tzinfo=weather.SWE_TZ)), axis=1)
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
        df_plan['hours_from_target'] = (target_dt_naive - df_plan['t_slot']).dt.total_seconds() / 3600.0
        df_plan['score'] += df_plan['hours_from_target'] * 0.05

        # Ge soltimmar en stor bonus, och gynna TIDIGA soltimmar (så vi fångar överskottet direkt och buffrar)
        df_plan.loc[df_plan['solar_w'] > 1500, 'score'] -= (10.0 + df_plan['hours_from_target'] * 0.1)

        df_plan['is_heating'] = False
        valid_mask = (df_plan['t_slot'] >= now_dt_naive) & (df_plan['t_slot'] < target_dt_naive)
        available_idx = df_plan[valid_mask].sort_values('score').index.tolist()
        # FIX: avrunda deadline till 15-min-slot (inte hel timme) och läs av temp_at_target
        # EFTER att den sloten simulerats, så uppvärmning mellan :00 och deadline räknas med.
        target_slot = target_dt_naive.replace(minute=(target_dt_naive.minute // 15) * 15, second=0, microsecond=0)

        ct_initial = float(curr_temp)
        temp_at_target_initial = ct_initial
        for _, r in df_plan.iterrows():
            T_env = r['temp']
            T_old = ct_initial
            T_new = T_env + (T_old - T_env) * math.exp(-cooling_k * 0.25) # 15 minuter
            ct_initial = T_new
            if ct_initial < float(spa_low_temp):
                ct_initial = float(spa_low_temp)
            if r['t_slot'] == target_slot:
                temp_at_target_initial = ct_initial

        if temp_at_target_initial < float(target_temp):
            for idx in available_idx:
                df_plan.at[idx, 'is_heating'] = True

                ct = float(curr_temp)
                temp_at_target = ct
                for i, r in df_plan.iterrows():
                    if r['is_heating']:
                        current_heating_rate = learning.predict_heating_rate(outdoor_temp, ct, model_intercept, model_slope_out, model_slope_spa)
                        ct += (current_heating_rate * 0.25)
                        max_t = float(spa_max_temp) if r['solar_w'] > 1500 else float(target_temp)
                        if ct > max_t:
                            ct = max_t
                    else:
                        T_env = df_plan.loc[i, 'temp']
                        T_old = ct
                        T_new = T_env + (T_old - T_env) * math.exp(-cooling_k * 0.25)
                        ct = T_new
                        if ct < float(spa_low_temp):
                            ct = float(spa_low_temp)
                    if r['t_slot'] == target_slot:
                        temp_at_target = ct

                if temp_at_target >= float(target_temp):
                    break

        current_plan = df_plan[df_plan['t_slot'] == now_dt_naive]
        if not current_plan.empty:
            return bool(current_plan.iloc[0]['is_heating']), current_plan.iloc[0]['solar_w'] > 1500
        return False, False
    except Exception as e:
        # FIX: logga full traceback så tysta fel i spa-planen blir synliga i loggen.
        # Behåller den säkra fallbacken (False, False) och catch-all så att ett fel här
        # aldrig kraschar minut-tasken i main.py.
        import traceback
        print(f"❌ Fel i check_spa_schedule_plan: {e}\n{traceback.format_exc()}")
        return False, False

# --- EV Charging Plan ---
NISSAN_BATTERY_KWH = 40
TESLA_BATTERY_KWH = 75

# ANVÄNDARREGEL (Emil, 2026-10-25): oavsett laddschema ska bilen alltid vara minst 50 % kl 06:00 varje morgon.
MORNING_MIN_SOC = 50
MORNING_HOUR = 6

def get_car_plan_details(now, car_id, schedule, current_soc, battery_kwh):
    """Hjälpfunktion som beräknar nästa mål och energibehov för en bil."""
    target_dt, target_soc, panic_mode = None, 100, False
    today_weekday = now.weekday()
    for i in range(7):
        day_offset = i
        check_day = (today_weekday + day_offset) % 7
        day_schedule = schedule.get(car_id, {}).get(check_day, {})
        if day_schedule.get('enabled'):
            t_str = day_schedule.get('target_time', '07:00')
            try:
                t_hour, t_min = map(int, str(t_str).split(':'))
            except (ValueError, AttributeError):
                t_hour, t_min = 7, 0
            test_dt = (now + timedelta(days=day_offset)).replace(hour=t_hour, minute=t_min, second=0, microsecond=0)
            if test_dt > now:
                target_dt = test_dt
                target_soc = day_schedule.get('target_soc', 100)
                panic_mode = day_schedule.get('panic_mode', False)

                break
    # Morgongolv: schemat får aldrig ge lägre mål än MORNING_MIN_SOC, och saknas aktivt schema
    # (avstängt/inget) gäller ändå nästa morgon kl MORNING_HOUR som deadline.
    if target_dt is None:
        morning_dt = now.replace(hour=MORNING_HOUR, minute=0, second=0, microsecond=0)
        if morning_dt <= now:
            morning_dt += timedelta(days=1)
        target_dt, target_soc = morning_dt, MORNING_MIN_SOC
    else:
        target_soc = max(target_soc, MORNING_MIN_SOC)

    if current_soc is None or current_soc >= target_soc:
        return None, target_soc, 0, False
    
    # Beräkna hur mycket energi som krävs från nätet. Vi lägger på 12% för att täcka normala 
    # laddförluster (AC till DC-omvandling samt värmeförluster), annars når vi aldrig ända fram.
    kwh_needed = max(0, (target_soc - current_soc) / 100.0 * battery_kwh) * 1.12
    return target_dt, target_soc, kwh_needed, panic_mode

def get_morning_floor(now, current_soc, battery_kwh, target_dt):
    """Golvet (MORNING_MIN_SOC kl MORNING_HOUR) som ett eget första delmål: (deadline, kWh från nätet) eller None.
    Behövs bara när bilen är under golvet och schemats tid ligger EFTER kl 06 - då ska golvet nås först och resten till schemats tid."""
    if current_soc is None or current_soc >= MORNING_MIN_SOC or target_dt is None:
        return None
    morning_dt = now.replace(hour=MORNING_HOUR, minute=0, second=0, microsecond=0)
    if morning_dt <= now:
        morning_dt += timedelta(days=1)
    if target_dt <= morning_dt:
        return None
    return morning_dt, max(0.0, (MORNING_MIN_SOC - current_soc) / 100.0 * battery_kwh) * 1.12

def calculate_ev_charge_plan(now, ev_schedule, car_data, cfg):
    """Skapar en "Spread & Smooth" laddningsplan för de kommande 48 timmarna."""
    # Användarens INSTÄLLDA huvudsäkring (Inställningar-fliken), fallback till modulkonstanten.
    fuse_a = cfg.get('fuse_size_a', MAX_FUSE_A) if cfg else MAX_FUSE_A
    nissan_soc = car_data.get('nissan_soc')
    tesla_soc = car_data.get('tesla_soc')
    nissan_plugged_in = car_data.get('nissan_plugged_in', False)
    tesla_plugged_in = car_data.get('tesla_plugged_in', False)

    # Nissan Leaf 2018 stöder enbart 1-fasladdning (Max ca 6.6 kW / 29A)
    nissan_phases = 1
    
    tesla_phases_str = car_data.get('tesla_phases')
    tesla_phases = 3 if tesla_phases_str is None or any(x in str(tesla_phases_str) for x in ['Three', '3', 'auto', 'Auto']) else 1

    nissan_target_dt, _, nissan_kwh, nissan_panic = get_car_plan_details(now, 'nissan', ev_schedule, nissan_soc, NISSAN_BATTERY_KWH)
    tesla_target_dt, _, tesla_kwh, tesla_panic = get_car_plan_details(now, 'tesla', ev_schedule, tesla_soc, TESLA_BATTERY_KWH)

    max_dt = now
    if nissan_target_dt and nissan_target_dt > max_dt: max_dt = nissan_target_dt
    if tesla_target_dt and tesla_target_dt > max_dt: max_dt = tesla_target_dt

    if max_dt == now: return pd.DataFrame()

    planning_window_end = max_dt + timedelta(hours=1)
    try:
        with logger.get_db() as conn:
            df_prices = pd.read_sql("""
                SELECT time_start AT TIME ZONE 'Europe/Stockholm' AS t, sek_per_kwh
                FROM elpriser
                WHERE time_start >= %s AND time_start < %s
                ORDER BY time_start ASC
            """, conn, params=(now.replace(minute=0, second=0), planning_window_end))
            df_weather = pd.read_sql("""
                SELECT timestamp AT TIME ZONE 'Europe/Stockholm' AS t, cloud_cover
                FROM weather_forecast
                WHERE timestamp >= %s AND timestamp < %s
                ORDER BY timestamp ASC
            """, conn, params=(now.replace(minute=0, second=0, microsecond=0), planning_window_end))
    except Exception as e:
        print(f"❌ EV Plan: DB-fel: {e}")
        return pd.DataFrame()

    if df_prices.empty: return pd.DataFrame()

    df_prices['t'] = pd.to_datetime(df_prices['t']).dt.tz_localize(None)
    df_prices.set_index('t', inplace=True)
    # Samma sak här: den dubbla timmen vid övergången till normaltid ger dubbletter i indexet (reindex kraschar annars).
    df_prices = df_prices[~df_prices.index.duplicated(keep='first')]
    start_grid = now.replace(minute=0, second=0, microsecond=0, tzinfo=None)
    full_idx = pd.date_range(start=start_grid, end=planning_window_end.replace(tzinfo=None), freq='15min')
    df_plan = df_prices.reindex(full_idx).ffill().bfill().reset_index()
    df_plan.rename(columns={'index': 't_slot', 'sek_per_kwh': 'price'}, inplace=True)

    if not df_weather.empty:
        df_weather['t_hour'] = pd.to_datetime(df_weather['t']).dt.floor('h')
        weather_by_hour = df_weather.groupby('t_hour')['cloud_cover'].mean().reset_index()
        df_plan['t_hour'] = df_plan['t_slot'].dt.floor('h')
        df_plan = pd.merge(df_plan, weather_by_hour, on='t_hour', how='left')
        df_plan['cloud_cover'] = df_plan['cloud_cover'].ffill().bfill().fillna(50)
    else:
        df_plan['cloud_cover'] = 50

    # FIX: låg tidigare felindenterad under else → solar_w saknades (KeyError) när väderdata fanns
    df_plan['solar_w'] = df_plan.apply(lambda r: safe_get_smart_solar_w(r['cloud_cover'], r['t_slot']), axis=1)
    # ANVÄNDARPRIORITET: solladdning ska väga tungt. Tidigare (/10000) krävde det ~full sol (10kW)
    # för att ge en 1,0 kr-bonus – för svagt för att slå normala prisskillnader vid måttlig sol.
    # /4000 ger redan 3kW sol en bonus på 0,75 kr (slår de flesta vanliga prisskillnader), och
    # 8-10kW sol (~2-2,5 kr bonus) vinner även mot ovanligt dyra timmar. Skalar linjärt med solstyrka.
    df_plan['score'] = df_plan['price'] - (df_plan['solar_w'] / 4000.0)

    # Prognoskolumner för VISNING (grafen) – ren tilläggsdata, påverkar inte allokeringen nedan.
    # husets_forbrukning = inlärd baslastprofil per kvart; sol = redan beräknad solprognos ovan.
    _display_base_load_profile = learning.get_base_load_profile()
    df_plan['house_load_kw'] = df_plan['t_slot'].apply(
        lambda ts: learning.predict_base_load(ts, _display_base_load_profile))
    df_plan['solar_kw'] = df_plan['solar_w'] / 1000.0
    df_plan['hour_val'] = df_plan['t_slot'].dt.hour
    df_plan.loc[(df_plan['hour_val'] >= 7) & (df_plan['hour_val'] < 20), 'score'] += 1.5

    df_plan['nissan_kw'] = 0.0
    df_plan['tesla_kw'] = 0.0
    df_plan['nissan_panic'] = False
    df_plan['tesla_panic'] = False
    df_plan['allocated_kw'] = 0.0
    
    power_limit_bas = cfg.get("power_limit_kw_bas", 0.0)
    power_limit_hog = cfg.get("power_limit_kw_hog", 0.0)
    old_limit = cfg.get("power_limit_kw", 0.0)
    if power_limit_bas == 0 and power_limit_hog == 0 and old_limit > 0:
        power_limit_bas = old_limit
        power_limit_hog = old_limit
        
    if power_limit_bas == 0 or power_limit_hog == 0:
        # Hämta månadens faktiska toppar från databasen (samma logik som main.py)
        p_peaks = logger.get_monthly_power_peaks()
        bas_avg = (p_peaks.get('bas_p1', 0) + p_peaks.get('bas_p2', 0)) / 2.0
        hog_avg = (p_peaks.get('hog_p1', 0) + p_peaks.get('hog_p2', 0)) / 2.0
        
        if bas_avg == 0: bas_avg = 10.0
        if hog_avg == 0: hog_avg = bas_avg
        if power_limit_bas == 0: power_limit_bas = bas_avg
        if power_limit_hog == 0: power_limit_hog = hog_avg

    peak_shaving_enabled = cfg.get("peak_shaving_enabled", True)
    
    def get_slot_limit(ts):
        is_high = settings.is_high_load_time(ts)
        lim = power_limit_hog if is_high else power_limit_bas
        return lim if peak_shaving_enabled else 99.0

    df_plan['slot_power_limit'] = df_plan['t_slot'].apply(get_slot_limit)

    # --- 6A TRAP FIX: Efficiency-Aware Scoring ---
    base_load_profile = learning.get_base_load_profile()
    
    def adjust_score_for_efficiency(row):
        limit = row['slot_power_limit']
        if limit == 0: limit = 99.0
        
        assumed_base = learning.predict_base_load(row['t_slot'], base_load_profile)
        available_kw = max(0.0, limit - assumed_base)
        available_kw = min(13.8, available_kw)
        
        score = row['score']
        if available_kw >= 1.38:
            # Straffa låga strömstyrkor för att undvika "The 6A Trap".
            # Vid 11kW = 0 straff. Vid 4.14kW = +0.165 straff till score.
            eff_penalty = 0.10 * ((11.0 / available_kw) - 1.0)
            score += max(0.0, eff_penalty)
            
        return score
        
    df_plan['score'] = df_plan.apply(adjust_score_for_efficiency, axis=1)

    cars_to_plan = []
    if nissan_target_dt and nissan_kwh > 0 and nissan_plugged_in:
        cars_to_plan.append({'id': 'nissan', 'deadline': nissan_target_dt, 'kwh_needed': nissan_kwh, 'min_kw': 6 * 230 * 1 / 1000.0, 'max_kw': min(20, fuse_a) * 230 * 1 / 1000.0, 'panic_mode': nissan_panic, 'floor': get_morning_floor(now, nissan_soc, NISSAN_BATTERY_KWH, nissan_target_dt)})
    if tesla_target_dt and tesla_kwh > 0 and tesla_plugged_in:
        cars_to_plan.append({'id': 'tesla', 'deadline': tesla_target_dt, 'kwh_needed': tesla_kwh, 'min_kw': 6 * 230 * tesla_phases / 1000.0, 'max_kw': min(16, fuse_a) * 230 * tesla_phases / 1000.0, 'panic_mode': tesla_panic, 'floor': get_morning_floor(now, tesla_soc, TESLA_BATTERY_KWH, tesla_target_dt)})
    cars_to_plan.sort(key=lambda x: x['deadline'])

    hourly_energy_allocated = {}
    now_slot_naive = now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0, tzinfo=None)

    for car in cars_to_plan:
        car_min_kw = car['min_kw']
        car_max_kw = car['max_kw']
        # Delmål: först golvet kl 06 (om bilen är under det och schemats tid är senare), sedan resten till schemats tid.
        stages = []
        if car.get('floor'):
            stages.append((car['floor'][0], min(car['floor'][1], car['kwh_needed'])))
            stages.append((car['deadline'], car['kwh_needed'] - stages[0][1]))
        else:
            stages.append((car['deadline'], car['kwh_needed']))

        for stage_idx, (stage_deadline, kwh_needed) in enumerate(stages):
            if kwh_needed <= 0:
                continue
            car_deadline_dt_naive = stage_deadline.replace(tzinfo=None)
            potential_slots_df = df_plan[(df_plan['t_slot'] < car_deadline_dt_naive) & (df_plan['t_slot'] >= now_slot_naive)]
            if stage_idx > 0:   # slots som delmålet före redan gett ström tas inte om (skulle skrivas över)
                potential_slots_df = potential_slots_df[potential_slots_df[f"{car['id']}_kw"] <= 0]
            if potential_slots_df.empty:
                continue

            charge_slots_indices = potential_slots_df.sort_values('score').index.tolist()
            kwh_rem = kwh_needed

            # PASS 1: Respektera Peak Shaving (Effektvakten)
            for idx in charge_slots_indices:
                if kwh_rem <= 0: break

                slot_dt = df_plan.at[idx, 't_slot']
                hour_key = slot_dt.strftime('%Y-%m-%d %H:00')
            
                peak_shaving_enabled = cfg.get("peak_shaving_enabled", True)
                limit = df_plan.at[idx, 'slot_power_limit']
                hourly_limit_kwh = limit if peak_shaving_enabled and limit > 0 else 99.0
            
                base_load_profile = learning.get_base_load_profile()
                assumed_base_load_kwh = learning.predict_base_load(slot_dt, base_load_profile)
                available_ev_kwh_for_hour = max(0.0, hourly_limit_kwh - assumed_base_load_kwh)
            
                min_kwh_per_slot = car_min_kw / 4.0
                if 0 < available_ev_kwh_for_hour < min_kwh_per_slot:
                    available_ev_kwh_for_hour = min_kwh_per_slot
                
                already_allocated_this_hour = hourly_energy_allocated.get(hour_key, 0.0)
                max_kwh_for_slot = available_ev_kwh_for_hour - already_allocated_this_hour
            
                if max_kwh_for_slot <= 0: continue
            
                max_kw_from_energy = max_kwh_for_slot * 4.0
                max_total_kw = min(car_max_kw, max_kw_from_energy)

                available_kw_slot = max_total_kw - df_plan.at[idx, 'allocated_kw']
                if available_kw_slot < car_min_kw: continue

                power_to_give = min(available_kw_slot, car_max_kw)
                kwh_to_give = power_to_give / 4.0  # kWh for a 15-min slot
                if kwh_to_give > kwh_rem:
                    power_to_give = kwh_rem * 4.0

                if 0 < power_to_give < car_min_kw:
                    power_to_give = car_min_kw

                kwh_to_give_final = power_to_give / 4.0

                df_plan.at[idx, f"{car['id']}_kw"] = power_to_give
                df_plan.at[idx, 'allocated_kw'] += power_to_give
                kwh_rem -= kwh_to_give_final
                hourly_energy_allocated[hour_key] = already_allocated_this_hour + kwh_to_give_final
            
            # PASS 2: PANIC MODE (Ignorera Peak Shaving för att tvinga bilen full)
            if kwh_rem > 0 and car['panic_mode']:
                for idx in charge_slots_indices:
                    if kwh_rem <= 0: break
                    current_allocated = df_plan.at[idx, f"{car['id']}_kw"]
                    available_extra_kw = car_max_kw - current_allocated
                
                    # Fysiskt tak: Huvudsäkring - Förväntad baslast i detta 15-min fönster
                    slot_dt = df_plan.at[idx, 't_slot']
                    assumed_base_load_kw = learning.predict_base_load(slot_dt, base_load_profile)
                    fuse_limit_kw = (fuse_a * 230 * 3 / 1000.0) - assumed_base_load_kw
                
                    room_in_slot = max(0.0, fuse_limit_kw - df_plan.at[idx, 'allocated_kw'])
                    available_extra_kw = min(available_extra_kw, room_in_slot)
                
                    if available_extra_kw > 0:
                        power_to_add = min(available_extra_kw, kwh_rem * 4.0)
                        if (current_allocated + power_to_add) > 0 and (current_allocated + power_to_add) < car_min_kw:
                            # Tvinga inte upp till car_min_kw om det spränger huvudsäkringen (brandrisk)
                            if room_in_slot >= car_min_kw:
                                power_to_add = car_min_kw - current_allocated
                            else:
                                power_to_add = 0.0 # Blås inte huvudsäkringen, ens i Panic Mode!

                        # FIX: sätt inte panic-flaggan på en slot som ändå får 0 kW (vilseledande nedströms)
                        if power_to_add <= 0:
                            continue

                        df_plan.at[idx, f"{car['id']}_kw"] += power_to_add
                        df_plan.at[idx, f"{car['id']}_panic"] = True
                        df_plan.at[idx, 'allocated_kw'] += power_to_add
                        kwh_rem -= power_to_add / 4.0

    return df_plan.sort_values('t_slot')
