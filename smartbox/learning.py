"""
learning.py - Funktioner för att analysera historisk data och skapa modeller.
"""

import pandas as pd
import numpy as np
import pickle
import traceback
import logger as sm_logger # Använd alias för att undvika namnkonflikt
import warnings

warnings.filterwarnings("ignore", message=".*pandas only supports SQLAlchemy.*")

# Standardvärde om ingen historisk data finns (grader C per timme)
DEFAULT_SPA_HEATING_RATE = 2.0
DEFAULT_SPA_COOLING_RATE_K = 0.02 # Newtons avsvalningskonstant k
DEFAULT_SPA_COOLING_RATE = 0.5 # Behålls som fallback för predict_cooling_rate
DEFAULT_HOUSE_COOLING_RATE = 0.05  # Hus tappar sällan mer än 0.05-0.1 grader per timme

_cached_spa_heating_model = None
_cached_spa_heating_time = None

def get_heating_rate_model(max_age_hours=24, force_recalculation=False):
    """
    Hämtar en linjär regressionsmodell för spabadets uppvärmningstakt.
    Modellen cachas för att undvika upprepade databasfrågningar.

    Modell: heating_rate = intercept + (slope_out * outdoor_temp) + (slope_spa * spa_temp)
    (Asymptotisk tillväxt: Ju varmare badet är, desto lägre blir uppvärmningstakten)

    Returnerar:
        - intercept (float): Grunduppvärmningstakt vid 0°C ute.
        - slope_out, slope_spa (float, float): Koefficienter.
    """
    from datetime import datetime, timedelta
    from sklearn.linear_model import LinearRegression

    global _cached_spa_heating_model, _cached_spa_heating_time
    now = datetime.now()
    
    if not force_recalculation and _cached_spa_heating_model and _cached_spa_heating_time:
        if (now - _cached_spa_heating_time) < timedelta(hours=max_age_hours):
            return _cached_spa_heating_model
            
    try:
        with sm_logger.get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='system_settings' AND column_name='spa_model_time'")
                if not cur.fetchone():
                    cur.execute("ALTER TABLE system_settings ADD COLUMN spa_model_time TIMESTAMPTZ")
                    conn.commit()

                # FIX #9: Egen kolumn för spa-uppvärmningens slope_spa. Tidigare delades
                # spa_cooling_model_slope med kylmodellen, som skriver 0.0 dit var 24:e timme och
                # därmed nollställde uppvärmningens spatemp-beroende. Skapa egen kolumn vid behov.
                cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='system_settings' AND column_name='spa_model_slope_spa'")
                if not cur.fetchone():
                    cur.execute("ALTER TABLE system_settings ADD COLUMN spa_model_slope_spa NUMERIC")
                    conn.commit()

                if not force_recalculation:
                    # Läs i första hand den egna kolumnen; fall tillbaka på den gamla delade kolumnen
                    # under migrering så att vi inte tappar en redan tränad modell.
                    cur.execute("SELECT spa_model_intercept, spa_model_slope, spa_model_slope_spa, spa_model_time, spa_cooling_model_slope FROM system_settings WHERE id = 1")
                    row = cur.fetchone()
                    if row and row[0] is not None and row[1] is not None and row[3] is not None:
                        if (now - row[3].replace(tzinfo=None)) < timedelta(hours=max_age_hours):
                            slope_spa_val = row[2] if row[2] is not None else row[4]
                            _cached_spa_heating_model = (float(row[0]), float(row[1]), float(slope_spa_val) if slope_spa_val is not None else 0.0)
                            _cached_spa_heating_time = now
                            return _cached_spa_heating_model
    except Exception as e:
        print(f"❌ DB-fel vid läsning av spa uppvärmningsmodell: {e}")
        traceback.print_exc()

    print("🧠 Beräknar ny asymptotisk ML-modell för spabadets uppvärmning...")
    
    try:
        with sm_logger.get_db() as conn:
            # Hämta data från de senaste 30 dagarna där värmaren var på.
            df = pd.read_sql("""
                SELECT timestamp, spa_temp, outdoor_temp
                FROM sensor_log
                WHERE timestamp >= NOW() - INTERVAL '30 days'
                  AND spa_heater_running = 1
                  AND outdoor_temp IS NOT NULL
                  AND spa_temp IS NOT NULL
                ORDER BY timestamp ASC
            """, conn, index_col='timestamp')

        if len(df) < 15: # Sänkt krav: Kräver bara 15 minuters mätdata
            print("⚠️ Inte tillräckligt med data för att bygga en uppvärmningsmodell. Använder standardvärde.")
            return DEFAULT_SPA_HEATING_RATE, 0.0, 0.0

        # Identifiera sammanhängande uppvärmningssessioner.
        # En ny session startar om det gått mer än 5 minuter sedan förra loggen.
        df['session_id'] = (df.index.to_series().diff() > timedelta(minutes=5)).cumsum()
        
        heating_sessions = []
        total_sessions_found = df['session_id'].nunique()
        discarded_sessions = 0
        for session_id in df['session_id'].unique():
            session = df[df['session_id'] == session_id]
            
            if len(session) < 5: # Sänkt krav: Godkänn sessioner över 5 minuter
                discarded_sessions += 1
                continue

            # Använd linjär regression för att hitta uppvärmningstakten för sessionen.
            # Detta är mer robust mot brus i sensordata än att bara ta start/slut-värde.
            session_copy = session.copy()
            session_copy['time_seconds'] = (session_copy.index - session_copy.index.min()).total_seconds()

            session_model = LinearRegression()
            session_model.fit(session_copy[['time_seconds']], session_copy['spa_temp'])

            # Lutningen (coef_[0]) är i °C/sekund. Konvertera till °C/timme.
            rate = session_model.coef_[0] * 3600

            duration_hours = (session.index.max() - session.index.min()).total_seconds() / 3600
            if duration_hours == 0:
                continue

            # Uppskatta total temperaturökning baserat på den uträknade takten
            temp_gain = rate * duration_hours

            # Vi vill bara ha data där temperaturen faktiskt ökar
            if temp_gain <= 0.05: # Sänkt krav: Fånga upp extremt långsam uppvärmning
                discarded_sessions += 1
                continue

            # Rimlighetscheck: ignorera orimligt snabb/långsam uppvärmning (t.ex. vid mätfel)
            if not (0.5 <= rate <= 5.0):
                discarded_sessions += 1
                continue
                
            avg_outdoor_temp = session['outdoor_temp'].mean()
            avg_spa_temp = session['spa_temp'].mean()
            heating_sessions.append({
                "rate": rate,
                "outdoor_temp": avg_outdoor_temp,
                "spa_temp": avg_spa_temp
            })
        
        # FIX: höjt minimikrav till 10 sessioner innan vi litar på en full 2-variabel-regression.
        # Med bara 3 sessioner överanpassas modellen lätt och kan ge orimliga takter (slope_spa garbage).
        # Med 1-9 sessioner använder vi istället det robusta snittet (slope=0), 0 sessioner -> standardvärde.
        if len(heating_sessions) < 10:
            print(f"⚠️ För få giltiga uppvärmningssessioner hittades ({len(heating_sessions)} st). Använder standardvärde.")
            if len(heating_sessions) > 0:
                # Ny Logik: Vi har data, men inte nog för en full 3D-regression. Använd snittet!
                avg_rate = sum([s['rate'] for s in heating_sessions]) / len(heating_sessions)
                print(f"💡 Använder genomsnittet från tillgänglig data istället: {avg_rate:.2f} °C/h.")
                return avg_rate, 0.0, 0.0
            else:
                return DEFAULT_SPA_HEATING_RATE, 0.0, 0.0

        # Bygg en multivariabel regressionsmodell (Utetemp + Spatemp)
        model_df = pd.DataFrame(heating_sessions)
        X = model_df[['outdoor_temp', 'spa_temp']]
        y = model_df['rate']
        
        model = LinearRegression()
        model.fit(X, y)
        
        intercept = model.intercept_
        slope_out = model.coef_[0]
        slope_spa = model.coef_[1]

        # FIX: fysikalisk teckenrestriktion. Högre spatemp kan aldrig ge HÖGRE uppvärmningstakt
        # (asymptotisk modell). En positiv slope_spa är garbage-in/overfitting -> nollställ den.
        if slope_spa > 0:
            slope_spa = 0.0

        print(f"✅ Ny uppvärmningsmodell skapad: Takt = {intercept:.2f} + ({slope_out:.3f} * Ute) + ({slope_spa:.3f} * Spa). "
              f"Baserad på {len(heating_sessions)} sessioner.")

        # Spara den nya modellen till databasen
        # FIX #9: slope_spa skrivs nu till sin egen kolumn spa_model_slope_spa (inte den delade
        # spa_cooling_model_slope) så att kylmodellens cron-jobb inte längre kan nollställa den.
        with sm_logger.get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE system_settings
                    SET spa_model_intercept = %s, spa_model_slope = %s, spa_model_slope_spa = %s, spa_model_time = %s
                    WHERE id = 1
                """, (intercept, slope_out, slope_spa, now))
            conn.commit()
        print("✅ Uppvärmningsmodell sparad till databasen.")

        _cached_spa_heating_model = (intercept, slope_out, slope_spa)
        _cached_spa_heating_time = now
        return intercept, slope_out, slope_spa

    except Exception as e:
        print(f"❌ Fel vid beräkning av uppvärmningsmodell: {e}")
        traceback.print_exc()
        return DEFAULT_SPA_HEATING_RATE, 0.0, 0.0

def predict_heating_rate(outdoor_temp, spa_temp, model_intercept, model_slope_out, model_slope_spa):
    """ Förutspår uppvärmningstakten vid en given utomhustemperatur. """
    # Om vi inte har en modell (ännu), returnera standardvärdet
    if model_intercept is None or model_slope_out is None:
        return DEFAULT_SPA_HEATING_RATE

    if outdoor_temp is None:
        return model_intercept # Om utetemp saknas, returnera grundtakten
        
    spa_t = spa_temp if spa_temp is not None else 38.0
    slope_s = model_slope_spa if model_slope_spa is not None else 0.0
    
    # Beräkna takten och säkerställ att den är inom rimliga gränser
    rate = model_intercept + (model_slope_out * outdoor_temp) + (slope_s * spa_t)
    return max(0.5, min(rate, 5.0))

_cached_spa_cooling_model = None
_cached_spa_cooling_time = None

def get_cooling_rate_model(max_age_hours=24, force_recalculation=False):
    """
    Beräknar och hämtar spabadets avsvalningskonstant 'k' baserat på Newtons avsvalningslag.
    Modellen cachas för att undvika upprepade databasfrågningar.

    Modell: T(t) = T_env + (T_0 - T_env) * exp(-k*t)
    där k är avsvalningskonstanten.

    Returnerar:
        - k (float): Den beräknade avsvalningskonstanten.
        - 0.0 (float): För kompatibilitet, då den gamla modellen returnerade intercept och slope.
    """
    from datetime import datetime, timedelta
    from sklearn.ensemble import RandomForestRegressor
    import math
    
    global _cached_spa_cooling_model, _cached_spa_cooling_time
    now = datetime.now()
    
    if not force_recalculation and _cached_spa_cooling_model and _cached_spa_cooling_time:
        if (now - _cached_spa_cooling_time) < timedelta(hours=max_age_hours):
            return _cached_spa_cooling_model
    try:
        with sm_logger.get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='system_settings' AND column_name='spa_cooling_model_time'")
                if not cur.fetchone():
                    cur.execute("ALTER TABLE system_settings ADD COLUMN spa_cooling_model_time TIMESTAMPTZ")
                    conn.commit()

                if not force_recalculation:
                    cur.execute("SELECT spa_cooling_model_intercept, spa_cooling_model_time FROM system_settings WHERE id = 1")
                    row = cur.fetchone()
                    if row and row[0] is not None and row[1] is not None:
                        if (now - row[1].replace(tzinfo=None)) < timedelta(hours=max_age_hours):
                            _cached_spa_cooling_model = (float(row[0]), 0.0)
                            _cached_spa_cooling_time = now
                            return _cached_spa_cooling_model
    except Exception as e:
        print(f"❌ DB-fel vid läsning av spa kylningsmodell: {e}")
        traceback.print_exc()

    print("🧠 Beräknar ny modell för spabadets kylningstakt (Newton)...")
    
    try:
        with sm_logger.get_db() as conn:
            df = pd.read_sql("""
                SELECT timestamp, spa_temp, outdoor_temp
                FROM sensor_log
                WHERE timestamp >= NOW() - INTERVAL '30 days'
                  AND spa_heater_running = 0
                  AND outdoor_temp IS NOT NULL
                  AND spa_temp IS NOT NULL
                ORDER BY timestamp ASC
            """, conn, index_col='timestamp')

        if len(df) < 60:
            print("⚠️ Inte tillräckligt med data för att bygga en kylningsmodell. Använder standardvärde.")
            return DEFAULT_SPA_COOLING_RATE_K, 0.0

        df['session_id'] = (df.index.to_series().diff() > timedelta(minutes=5)).cumsum()

        # FIX: borttagen oanvänd 'cooling_sessions = []' (död variabel; endast k_values används här)
        k_values = []
        for session_id in df['session_id'].unique():
            session = df[df['session_id'] == session_id]

            if len(session) < 30: # Kräver minst 30 minuters vilodata
                continue

            start_time = session.index.min()
            end_time = session.index.max()
            duration_hours = (end_time - start_time).total_seconds() / 3600
            if duration_hours < 0.5: continue

            T_start = session['spa_temp'].iloc[0]
            T_end = session['spa_temp'].iloc[-1]
            T_env = session['outdoor_temp'].mean()

            temp_loss = T_start - T_end
            if temp_loss <= 0.1: continue # Ignorera om ingen märkbar avsvalning

            T_diff_start = T_start - T_env
            T_diff_end = T_end - T_env

            if T_diff_start <= 0 or T_diff_end <= 0: continue

            # k = -ln((T_end - T_env) / (T_start - T_env)) / duration_hours
            try:
                k = -math.log(T_diff_end / T_diff_start) / duration_hours
                # Rimlighetscheck för k (typiskt 0.01-0.1 för ett isolerat spabad)
                if 0.001 < k < 0.1:
                    k_values.append(k)
            except (ValueError, ZeroDivisionError):
                continue
        
        if not k_values:
            print("⚠️ Inga giltiga kylningssessioner hittades. Använder standardvärde för k.")
            return DEFAULT_SPA_COOLING_RATE_K, 0.0

        # Använd medianen för att vara robust mot outliers
        k_final = float(np.median(k_values))
        
        print(f"✅ Ny kylningsmodell (Newton) skapad: k = {k_final:.4f}. Baserad på {len(k_values)} sessioner.")

        with sm_logger.get_db() as conn:
            with conn.cursor() as cur:
                # Spara k i intercept-kolumnen och 0 i slope
                cur.execute("UPDATE system_settings SET spa_cooling_model_intercept = %s, spa_cooling_model_slope = %s, spa_cooling_model_time = %s WHERE id = 1", (k_final, 0.0, now))
            conn.commit()

        _cached_spa_cooling_model = (k_final, 0.0)
        _cached_spa_cooling_time = now
        return k_final, 0.0

    except Exception as e:
        print(f"❌ Fel vid beräkning av kylningsmodell: {e}")
        traceback.print_exc()
        return DEFAULT_SPA_COOLING_RATE_K, 0.0

def predict_cooling_rate(outdoor_temp, spa_temp, k):
    """ 
    Förutspår kylningstakten (°C/h) vid en given tidpunkt med Newtons avsvalningslag.
    Rate = k * (T_spa - T_outdoor)
    """
    if k is None or spa_temp is None or outdoor_temp is None:
        return DEFAULT_SPA_COOLING_RATE # Fallback to old constant rate if data is missing

    # Beräkna momentan avsvalningstakt
    rate = k * (spa_temp - outdoor_temp)
    return max(0.1, min(rate, 2.0)) # Samma rimlighetsgränser som förut

def get_house_cooling_rate_model(max_age_hours=24, force_recalculation=False):
    """
    Hämtar en Random Forest-modell för hur snabbt HUSETS innetemperatur faller 
    när värmepumpen vilar (pump_heat_running = 0), baserat på utetemp och vindhastighet.
    """
    from datetime import datetime, timedelta
    from sklearn.ensemble import RandomForestRegressor
    
    # Vi använder denna modell för både vind och solens värmande effekt
    now = datetime.now()
    try:
        with sm_logger.get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='system_settings' AND column_name='house_cooling_model'")
                if not cur.fetchone():
                    cur.execute("ALTER TABLE system_settings ADD COLUMN house_cooling_model BYTEA")
                    cur.execute("ALTER TABLE system_settings ADD COLUMN house_cooling_model_time TIMESTAMPTZ")
                    conn.commit()

                if not force_recalculation:
                    cur.execute("SELECT house_cooling_model, house_cooling_model_time FROM system_settings WHERE id = 1")
                    row = cur.fetchone()
                    if row and row[0] and row[1]:
                        if (now - row[1].replace(tzinfo=None)) < timedelta(hours=max_age_hours):
                            with warnings.catch_warnings():
                                warnings.simplefilter("error")
                                try:
                                    return pickle.loads(row[0])
                                except Exception as e:
                                    print(f"⚠️ Gammal hus-kylningsmodell upptäckt ({type(e).__name__}). Tvingar omträning...")
                                    # FIX: return None så tung omträning sker i bakgrundsjobb, inte synkront vid webbanrop
                                    return None
    except Exception as e:
        print(f"❌ DB-fel vid läsning av husets värmeförlustmodell: {e}")
        traceback.print_exc()

    try:
        # För att få med termisk tröghet hämtar vi all data först, beräknar rullande medelvärden,
        # och filtrerar SEDAN bort de tillfällen då pumpen gick.
        with sm_logger.get_db() as conn:
            df = pd.read_sql("""
                SELECT timestamp, indoor_temp, outdoor_temp, wind_speed, COALESCE(pv_power_w, 0) as pv_power_w, pump_heat_running, compressor_running
                FROM sensor_log
                WHERE timestamp >= NOW() - INTERVAL '45 days'
                  AND outdoor_temp IS NOT NULL
                  AND indoor_temp IS NOT NULL
                  AND wind_speed IS NOT NULL
                ORDER BY timestamp ASC
            """, conn, index_col='timestamp')

        if len(df) < 120:
            return None
            
        # 1. Tröghets-features: Rullande 3-timmars snitt för sol
        df['solar_w_roll_3h'] = df['pv_power_w'].rolling('3h').mean().fillna(0)
        # 2. Solvinkel-feature: Timme på dygnet
        df['hour'] = df.index.hour
        
        # Filtrera ut endast avsvalnings-sessioner
        df = df[(df['pump_heat_running'] == 0) & (df['compressor_running'] == 0)]

        df['session_id'] = (df.index.to_series().diff() > timedelta(minutes=5)).cumsum()
        
        cooling_sessions = []
        for session_id in df['session_id'].unique():
            session = df[df['session_id'] == session_id]
            
            # Vi behöver minst 60 minuters vila för att mäta ett pålitligt temperaturfall i ett tungt hus
            start_time = session.index.min()
            end_time = session.index.max()
            duration_hours = (end_time - start_time).total_seconds() / 3600
            if duration_hours < 0.5: continue

            temp_loss = session['indoor_temp'].iloc[0] - session['indoor_temp'].iloc[-1]
            if abs(temp_loss) <= 0.05: continue # Brus. Men tillåt negativa värden (uppvärmning av sol)
                
            rate = temp_loss / duration_hours
            
            # Ett normalisolerat hus tappar max 0.6 grader/h men kan VÄRMAS upp till 1 grad/h av sol
            if not (-1.0 <= rate <= 0.6): continue
                
            avg_outdoor_temp = session['outdoor_temp'].mean()
            avg_wind_speed = session['wind_speed'].mean()
            avg_solar_w = session['pv_power_w'].mean()
            avg_solar_roll = session['solar_w_roll_3h'].mean()
            avg_hour = session['hour'].mean()
            cooling_sessions.append({"rate": rate, "outdoor_temp": avg_outdoor_temp, "wind_speed": avg_wind_speed, "solar_w": avg_solar_w, "solar_w_roll_3h": avg_solar_roll, "hour": avg_hour})
        
        # FIX: höjt minimikrav från 5 till 30 sessioner. En RandomForest med 5 features tränad på
        # bara 5 punkter överanpassar grovt och blir sämre än DEFAULT_HOUSE_COOLING_RATE.
        # Vid för lite data returnerar vi None så predict_house_cooling_rate faller tillbaka på defaulten.
        if len(cooling_sessions) < 30:
            return None

        model_df = pd.DataFrame(cooling_sessions)
        X = model_df[['outdoor_temp', 'wind_speed', 'solar_w', 'solar_w_roll_3h', 'hour']]
        y = model_df['rate']
        
        model = RandomForestRegressor(n_estimators=100, max_depth=6, random_state=42)
        model.fit(X, y)
        
        print(f"🏠 Husets Digitala Tvilling: Random Forest-modell för termisk tröghet (inkl vind & sol) tränad på {len(cooling_sessions)} sessioner.")

        try:
            with sm_logger.get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute("UPDATE system_settings SET house_cooling_model = %s, house_cooling_model_time = %s WHERE id = 1", (pickle.dumps(model), now))
                conn.commit()
        except Exception as e:
            print(f"❌ Fel vid sparande av husets modell till databasen: {e}")
            traceback.print_exc()
            
        return model

    except Exception as e:
        print(f"❌ Fel vid beräkning av husets värmeförlust: {e}")
        traceback.print_exc()
        return None

def predict_house_cooling_rate(outdoor_temp, wind_speed, solar_w, solar_w_roll_3h, hour, model):
    """ Förutspår husets avsvalningstakt (negativ = uppvärmning) vid given temp, vind och sol med ML. """
    if model is None: return DEFAULT_HOUSE_COOLING_RATE
    if outdoor_temp is None: outdoor_temp = 0.0
    if wind_speed is None: wind_speed = 2.0
    if solar_w is None: solar_w = 0.0
    
    df_predict = pd.DataFrame({'outdoor_temp': [outdoor_temp], 'wind_speed': [wind_speed], 'solar_w': [solar_w], 'solar_w_roll_3h': [solar_w_roll_3h], 'hour': [hour]})
    rate = model.predict(df_predict)[0]
    return max(-1.0, min(rate, 0.6)) # Rimlighetsgränser för ett hus

def get_ev_habit_profile(car_id="nissan", max_age_hours=24):
    """
    Skapar en sannolikhetsmatris (0.0 - 1.0) för när en specifik elbil är inkopplad hemma,
    baserat på veckodag och timme. Tränas på de senaste 60 dagarna.
    """
    try:
        with sm_logger.get_db() as conn:
            status_col = "ev_status" if car_id == "nissan" else "ev_carport_status"
            df = pd.read_sql(f"""
                SELECT timestamp AT TIME ZONE 'Europe/Stockholm' as ts, 
                       {status_col} as status
                FROM sensor_log
                WHERE timestamp >= NOW() - INTERVAL '60 days'
            """, conn)
            
        if df.empty: return {}
        
        df['ts'] = pd.to_datetime(df['ts']).dt.tz_localize(None)
        df['is_home'] = (~df['status'].astype(str).str.lower().isin(['disconnected', 'offline', 'none', 'nan', ''])).astype(int)
        df['hour'] = df['ts'].dt.hour
        df['dow'] = df['ts'].dt.dayofweek
        
        # Beräkna andelen av tiden bilen är hemma per veckodag och timme
        profile = df.groupby(['dow', 'hour'])['is_home'].mean().to_dict()
        return profile
    except Exception as e:
        print(f"❌ Fel vid ML för elbilsvanor ({car_id}): {e}")
        return {}

def get_vp_recovery_model(max_age_hours=24):
    """
    Tränar en modell som lär sig hur snabbt värmepumpen återhämtar gradminuter
    beroende på utomhustemperatur när kompressorn går.
    """
    try:
        with sm_logger.get_db() as conn:
            df = pd.read_sql("""
                SELECT timestamp, degree_minutes, outdoor_temp
                FROM sensor_log
                WHERE timestamp >= NOW() - INTERVAL '30 days'
                  AND compressor_running = 1
                  AND degree_minutes IS NOT NULL
                ORDER BY timestamp ASC
            """, conn, index_col='timestamp')
            
        if len(df) < 120: return None
        
        df['session_id'] = (df.index.to_series().diff() > pd.Timedelta(minutes=5)).cumsum()
        sessions = []
        
        for session_id in df['session_id'].unique():
            session = df[df['session_id'] == session_id]
            duration_h = (session.index.max() - session.index.min()).total_seconds() / 3600
            if duration_h < 0.25: continue
            
            # Hur många gradminuter betade den av? (Start - Slut, eftersom negativa värden går mot noll)
            dm_recovery = session['degree_minutes'].iloc[-1] - session['degree_minutes'].iloc[0]
            if dm_recovery <= 0: continue # Ignorera sessioner där huset tappar värme trots att pumpen går
                
            recovery_rate = dm_recovery / duration_h
            avg_out = session['outdoor_temp'].mean()
            sessions.append({'outdoor_temp': avg_out, 'recovery_rate': recovery_rate})
            
        if len(sessions) < 5: return None
        
        model_df = pd.DataFrame(sessions)
        # Enkel regression för att hitta sambandet: Återhämtning = a + b * utetemp
        from sklearn.linear_model import LinearRegression
        model = LinearRegression().fit(model_df[['outdoor_temp']], model_df['recovery_rate'])
        return model
    except Exception as e:
        print(f"❌ Fel vid ML för VP Gradminuter: {e}")
        return None

_cached_solar_profile = None
_cached_solar_time = None

def get_solar_profile(max_age_hours=24, force_recalculation=False):
    """
    Skapar en Digital Tvilling-profil för solcellerna. Lär sig exakt hur mycket 
    effekt taket max-producerar vid en given månad och timme. Hanterar därmed 
    automatiskt väderstreck (söderläge), takvinkel och lokal skuggning!
    """
    from datetime import datetime, timedelta
    global _cached_solar_profile, _cached_solar_time
    now = datetime.now()
    
    if not force_recalculation and _cached_solar_profile and _cached_solar_time:
        if (now - _cached_solar_time) < timedelta(hours=max_age_hours):
            return _cached_solar_profile
            
    try:
        with sm_logger.get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='system_settings' AND column_name='solar_profile'")
                if not cur.fetchone():
                    cur.execute("ALTER TABLE system_settings ADD COLUMN solar_profile BYTEA")
                    cur.execute("ALTER TABLE system_settings ADD COLUMN solar_profile_time TIMESTAMPTZ")
                    conn.commit()

                if not force_recalculation:
                    cur.execute("SELECT solar_profile, solar_profile_time FROM system_settings WHERE id = 1")
                    row = cur.fetchone()
                    if row and row[0] and row[1]:
                        if (now - row[1].replace(tzinfo=None)) < timedelta(hours=max_age_hours):
                            _cached_solar_profile = pickle.loads(row[0])
                            _cached_solar_time = now
                            return _cached_solar_profile
    except Exception as e:
        traceback.print_exc()

    print("🧠 Tränar ML-modell för husets specifika solcellsproduktion (Klarhimmel-profil)...")
    try:
        with sm_logger.get_db() as conn:
            # Leta efter klara dagar senaste året. 90:e percentilen fångar en molnfri dag perfekt.
            df = pd.read_sql("""
                SELECT timestamp AT TIME ZONE 'Europe/Stockholm' as ts, pv_power_w
                FROM sensor_log
                WHERE timestamp >= NOW() - INTERVAL '365 days'
                  AND pv_power_w > 50
            """, conn)
            
        if df.empty or len(df) < 100:
            return {}
            
        df['ts'] = pd.to_datetime(df['ts']).dt.tz_localize(None)
        df['month'] = df['ts'].dt.month
        df['hour'] = df['ts'].dt.hour

        # Beräkna 90:e percentilen (Tar bort mätfel/extremspikar, men hittar klara soldagar)
        profile = df.groupby(['month', 'hour'])['pv_power_w'].quantile(0.90).to_dict()
        
        try:
            with sm_logger.get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute("UPDATE system_settings SET solar_profile = %s, solar_profile_time = %s WHERE id = 1", (pickle.dumps(profile), now))
                conn.commit()
        except Exception as e:
            traceback.print_exc()
            
        _cached_solar_profile = profile
        _cached_solar_time = now
        print("✅ Digital Solcells-tvilling genererad.")
        return profile
    except Exception as e:
        print(f"❌ Fel vid ML för solceller: {e}")
        traceback.print_exc()
        return {}

_cached_base_load_profile = None
_cached_base_load_time = None

def get_base_load_profile(max_age_hours=24, force_recalculation=False):
    """
    Skapar en ML-profil (Tidsserie / Percentil) för husets okända baslast 
    (Total import minus kända elbilsladdningar) per veckodag och timme.
    Används av Peak Shaving för att inte reservera i onödan.
    """
    from datetime import datetime, timedelta
    
    global _cached_base_load_profile, _cached_base_load_time
    now = datetime.now()
    
    if not force_recalculation and _cached_base_load_profile and _cached_base_load_time:
        if (now - _cached_base_load_time) < timedelta(hours=max_age_hours):
            return _cached_base_load_profile
            
    try:
        with sm_logger.get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='system_settings' AND column_name='base_load_profile'")
                if not cur.fetchone():
                    cur.execute("ALTER TABLE system_settings ADD COLUMN base_load_profile BYTEA")
                    cur.execute("ALTER TABLE system_settings ADD COLUMN base_load_profile_time TIMESTAMPTZ")
                    conn.commit()

                if not force_recalculation:
                    cur.execute("SELECT base_load_profile, base_load_profile_time FROM system_settings WHERE id = 1")
                    row = cur.fetchone()
                    if row and row[0] and row[1]:
                        if (now - row[1].replace(tzinfo=None)) < timedelta(hours=max_age_hours):
                            # FIX: deserialisera bara en gång och returnera cache-variabeln (undviker dubbelt pickle.loads)
                            _cached_base_load_profile = pickle.loads(row[0])
                            _cached_base_load_time = now
                            return _cached_base_load_profile
    except Exception as e:
        print(f"❌ DB-fel vid läsning av base_load_profile: {e}")
        traceback.print_exc()

    print("🧠 Tränar ML-modell för husets dynamiska baslast (Peak Shaving)...")
    try:
        with sm_logger.get_db() as conn:
            # Hämta senaste 30 dagarnas förbrukning där vi faktiskt köpte el
            df = pd.read_sql("""
                SELECT timestamp AT TIME ZONE 'Europe/Stockholm' as ts, 
                       GREATEST(net_power, 0) / 1000.0 as grid_import_kw,
                       COALESCE(ev_power_kw, 0) as ev_nissan,
                       COALESCE(ev_carport_power_kw, 0) as ev_tesla
                FROM sensor_log
                WHERE timestamp >= NOW() - INTERVAL '30 days'
                  AND net_power > 0
            """, conn)
            
        if df.empty or len(df) < 1000:
            return {}

        df['ts'] = pd.to_datetime(df['ts']).dt.tz_localize(None)
        df['other_kw'] = (df['grid_import_kw'] - df['ev_nissan'] - df['ev_tesla']).clip(lower=0)
        df['hour'] = df['ts'].dt.hour
        df['dow'] = df['ts'].dt.dayofweek

        # Använd 85:e percentilen. Det ger en säkerhetsmarginal som täcker 85% av alla historiska fall.
        profile = df.groupby(['dow', 'hour'])['other_kw'].quantile(0.85).to_dict()
        
        try:
            with sm_logger.get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute("UPDATE system_settings SET base_load_profile = %s, base_load_profile_time = %s WHERE id = 1", (pickle.dumps(profile), now))
                conn.commit()
        except Exception as e:
            print(f"❌ Fel vid sparande av base_load_profile till databasen: {e}")
            traceback.print_exc()
            
        print("✅ Dynamisk baslast-modell genererad.")
        return profile
    except Exception as e:
        print(f"❌ Fel vid ML för baslast: {e}")
        traceback.print_exc()
        return {}

def predict_base_load(dt, profile):
    """Gissar baslasten för en given tidpunkt. Fallback till 2.5 kW."""
    if not profile: return 2.5
    # Hämta värdet från profilen, runda av till minimum 1.0 kW och maximum 6.0 kW som sanity check
    pred = profile.get((dt.weekday(), dt.hour), 2.5)
    return max(1.0, min(pred, 6.0))


_price_shape_cache = None
_price_shape_cache_time = None

def get_price_shape_profile(max_age_hours=24):
    """Typisk intradygns-prisform: median spotpris (kr/kWh) per (månad, timme) över ~365 dygn.

    Elpris är svårt att punktprognostisera, men DYGNSMÖNSTRET (billig natt, dyr morgon/kväll)
    och säsongsnivån är stabila. Denna form används av nordpool.forecast_price_at() för att
    uppskatta priser BORTOM Nordpools publicerade horisont (formen × aktuell nivå). 24h-cache."""
    global _price_shape_cache, _price_shape_cache_time
    from datetime import datetime
    now = datetime.now()
    if (_price_shape_cache is not None and _price_shape_cache_time
            and (now - _price_shape_cache_time).total_seconds() < max_age_hours * 3600):
        return _price_shape_cache
    try:
        with sm_logger.get_db() as conn:
            df = pd.read_sql("""
                SELECT time_start AT TIME ZONE 'Europe/Stockholm' AS ts, sek_per_kwh
                FROM elpriser
                WHERE time_start >= NOW() - INTERVAL '365 days' AND sek_per_kwh IS NOT NULL
            """, conn)
        if df.empty:
            return {}
        df['ts'] = pd.to_datetime(df['ts'])
        df['month'] = df['ts'].dt.month
        df['hour'] = df['ts'].dt.hour
        prof = df.groupby(['month', 'hour'])['sek_per_kwh'].median().to_dict()
        _price_shape_cache = {(int(m), int(h)): float(v) for (m, h), v in prof.items()}
        _price_shape_cache_time = now
        return _price_shape_cache
    except Exception as e:
        print(f"❌ Fel vid pris-form-profil: {e}")
        return {}

def get_hot_water_habit_profile(max_age_hours=24):
    """
    Skapar en sannolikhetsmatris för när varmvatten används (duschar/bad)
    baserat på plötsliga temperaturfall i beredaren (lär sig över 60 dagar).
    """
    try:
        with sm_logger.get_db() as conn:
            df = pd.read_sql("""
                SELECT timestamp AT TIME ZONE 'Europe/Stockholm' as ts, 
                       water_temp
                FROM sensor_log
                WHERE timestamp >= NOW() - INTERVAL '60 days'
                  AND water_temp IS NOT NULL
                ORDER BY timestamp ASC
            """, conn)
            
        if df.empty: return {}
        
        df['ts'] = pd.to_datetime(df['ts']).dt.tz_localize(None)
        df = df.sort_values('ts')

        # KALIBRERING (dataanalys 60 dygn): verkliga varmvattenuttag syns som ~1°C-fall i loggen. Gamla koden
        # resamplade till 15-min-MEDEL och krävde >2.5°C-fall → steget smetades ut, NOLL uttag
        # detekterades, profilen lärde sig inget och Prio 5.8 var i praktiken dött. Verkliga uttag
        # syns som ≥1°C-fall mellan konsekutiva loggar, tydligt klustrade kl 17–23. Vi detekterar
        # därför uttag på RÅSERIEN (gap<=20 min), markerar varje 15-min-slot som hade ett uttag,
        # och räknar tim-sannolikheten korrekt som 1-(1-p_slot)^4 (chans för minst ett uttag bland
        # timmens fyra kvartar). Standby-baslinjen (~0.35 nattetid) ligger under pre-värme-tröskeln
        # (0.55 i gpm Prio 5.8) så bara de verkliga kvällsuttagen triggar föruppvärmning.
        df['drop'] = -df['water_temp'].diff()
        df['gap_min'] = df['ts'].diff().dt.total_seconds() / 60.0
        df['is_draw'] = ((df['drop'] >= 1.0) & (df['gap_min'] <= 20)).astype(int)

        df = df.set_index('ts')
        slot = df.resample('15min')['is_draw'].max().dropna().reset_index()
        slot['hour'] = slot['ts'].dt.hour
        slot['dow'] = slot['ts'].dt.dayofweek
        p_slot = slot.groupby(['dow', 'hour'])['is_draw'].mean()
        return {k: float(min(1.0, 1.0 - (1.0 - v) ** 4)) for k, v in p_slot.to_dict().items()}
    except Exception as e:
        print(f"❌ Fel vid ML för varmvattenvanor: {e}")
        return {}

def estimate_preheat_minutes(outdoor_temp):
    """
    Uppskattar hur många minuter i förväg klimatanläggningen behöver starta.
    Grundmodell: 30 min vid 0°C. Kallare ute = längre tid.
    Detta kan i framtiden ersättas av en självlärande ML-modell.
    """
    if outdoor_temp is None: outdoor_temp = 10.0
    adjustment = (0 - outdoor_temp) * 0.75
    preheat_time = 30 + adjustment
    return max(15, min(60, preheat_time))

# ==============================================================================
# 🧠 NYA AI & MASKININLÄRNINGSMODELLER (Smartare hjärna)
# ==============================================================================

_cached_pi_params = None
_cached_pi_time = None

def get_optimal_pi_params():
    """
    Auto-tuning av PI-regulatorn för Solceller: Analyserar hur mycket nettoeffekten 
    har pendlat (oscillerat) under de senaste minuspristimmarna. Är den för stökig
    sänker vi parametrarna mjukt.
    """
    global _cached_pi_params, _cached_pi_time
    from datetime import datetime
    now = datetime.now()
    
    default_kp = 0.005
    default_ki = 0.0005
    
    if _cached_pi_params and _cached_pi_time and (now - _cached_pi_time).total_seconds() < 3600 * 24:
        return _cached_pi_params
        
    try:
        with sm_logger.get_db() as conn:
            df = pd.read_sql("""
                SELECT net_power
                FROM sensor_log
                WHERE timestamp >= NOW() - INTERVAL '7 days'
                  AND price < 0
                  AND solar_limit_pct < 100
                  AND solar_limit_pct > 0
            """, conn)
            
        if len(df) < 60:
            _cached_pi_params = (default_kp, default_ki)
            _cached_pi_time = now
            return _cached_pi_params
            
        # Beräkna standardavvikelsen på nettoeffekten (mått på oscillation)
        std_dev = df['net_power'].std()
        kp, ki = default_kp, default_ki
        
        if std_dev > 1500:
            kp = default_kp * 0.5
            ki = default_ki * 0.5
        elif std_dev > 800:
            kp = default_kp * 0.8
            ki = default_ki * 0.8
        elif std_dev < 200:
            kp = default_kp * 1.2
            ki = default_ki * 1.2
            
        _cached_pi_params = (kp, ki)
        _cached_pi_time = now
        print(f"⚙️ AI: PI-regulator autotunad. Ny kp={kp:.5f}, ki={ki:.6f} (Standardavvikelse historiskt: {std_dev:.0f}W)")
        return kp, ki
    except Exception as e:
        # sensor_log har ingen kolumn solar_limit_pct (loggas aldrig), så frågan föll varje gång och skrev ett fel var minut.
        # Standardvärdena gäller i alla fall; spara dem ett dygn så att felet inte upprepas.
        print(f"❌ Fel vid autotuning av PI (standardvärden används i 24 h): {e}")
        _cached_pi_params = (default_kp, default_ki)
        _cached_pi_time = now
        return default_kp, default_ki

_cached_house_heating_model = None
_cached_house_heating_time = None
_house_heating_last_attempt = None

def get_house_heating_model(max_age_hours=24, force_recalculation=False):
    """
    Fullständig MPC för Husvärme: Hämtar/skapar en Random Forest-modell som exakt lär sig
    husets *uppvärmningstakt* när värmepumpen arbetar, beroende på vind, innetemp och utetemp.
    """
    from datetime import datetime, timedelta
    from sklearn.ensemble import RandomForestRegressor

    global _cached_house_heating_model, _cached_house_heating_time, _house_heating_last_attempt
    now = datetime.now()

    # FIX #14: Minnescache så att main-loopen (som anropar denna varje minut i bortaläge)
    # inte trampar DB:n. Returnerar cachad modell direkt om den är färsk.
    if not force_recalculation and _cached_house_heating_time is not None:
        if (now - _cached_house_heating_time) < timedelta(hours=max_age_hours):
            return _cached_house_heating_model

    try:
        with sm_logger.get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='system_settings' AND column_name='house_heating_model'")
                if not cur.fetchone():
                    cur.execute("ALTER TABLE system_settings ADD COLUMN house_heating_model BYTEA")
                    cur.execute("ALTER TABLE system_settings ADD COLUMN house_heating_model_time TIMESTAMPTZ")
                    conn.commit()

                if not force_recalculation:
                    cur.execute("SELECT house_heating_model, house_heating_model_time FROM system_settings WHERE id = 1")
                    row = cur.fetchone()
                    if row and row[0] and row[1]:
                        if (now - row[1].replace(tzinfo=None)) < timedelta(hours=max_age_hours):
                            with warnings.catch_warnings():
                                warnings.simplefilter("error")
                                try:
                                    _cached_house_heating_model = pickle.loads(row[0])
                                    _cached_house_heating_time = now
                                    return _cached_house_heating_model
                                except Exception as e:
                                    print(f"⚠️ Gammal hus-uppvärmningsmodell upptäckt ({type(e).__name__}). Tränas om automatiskt.")
                                    # return None: tung omträning sker i bakgrundsjobb, inte här i loopen
                                    return None
    except Exception as e:
        print(f"❌ DB-fel vid läsning av husets uppvärmningsmodell: {e}")

    # FIX #14: Aktiverar faktisk träning av house-heating-modellen (analogt med get_house_cooling_rate_model).
    # Tidigare returnerades alltid None här, vilket gjorde att bortaläget i main.py aldrig kunde använda
    # en lärd uppvärmningstakt utan fastnade på fallbacken 0.3 °C/h. Fallbacken 0.3 finns kvar i
    # predict_house_heating_rate och används fortfarande när vi har för lite data (return None nedan).
    #
    # Throttle: main-loopen anropar denna varje minut i bortaläge. När det inte finns nog data sparas
    # ingen modell i DB, så utan denna spärr skulle vi köra en tung 45-dagars SQL + RF-träning varje minut.
    # Vi gör därför ett nytt tränings-försök som mest var max_age_hours.
    if not force_recalculation and _house_heating_last_attempt is not None:
        if (now - _house_heating_last_attempt) < timedelta(hours=max_age_hours):
            return _cached_house_heating_model
    _house_heating_last_attempt = now

    print("🏠 Tränar ML-modell för husets uppvärmningstakt (MPC)...")
    try:
        with sm_logger.get_db() as conn:
            # Hämta data där värmepumpen aktivt värmde huset (pump_heat_running = 1).
            df = pd.read_sql("""
                SELECT timestamp, indoor_temp, outdoor_temp, wind_speed, pump_heat_running
                FROM sensor_log
                WHERE timestamp >= NOW() - INTERVAL '45 days'
                  AND outdoor_temp IS NOT NULL
                  AND indoor_temp IS NOT NULL
                  AND wind_speed IS NOT NULL
                ORDER BY timestamp ASC
            """, conn, index_col='timestamp')

        if len(df) < 120:
            return None

        # Filtrera ut endast uppvärmnings-sessioner (pumpen körde värme)
        df = df[df['pump_heat_running'] == 1]

        df['session_id'] = (df.index.to_series().diff() > timedelta(minutes=5)).cumsum()

        heating_sessions = []
        for session_id in df['session_id'].unique():
            session = df[df['session_id'] == session_id]

            start_time = session.index.min()
            end_time = session.index.max()
            duration_hours = (end_time - start_time).total_seconds() / 3600
            if duration_hours < 0.5: continue

            temp_gain = session['indoor_temp'].iloc[-1] - session['indoor_temp'].iloc[0]
            if temp_gain <= 0.05: continue  # Ingen märkbar uppvärmning -> hoppa över

            rate = temp_gain / duration_hours

            # Rimlighetscheck: ett hus värms typiskt 0.1-1.0 grader/h
            if not (0.05 <= rate <= 1.0): continue

            avg_outdoor_temp = session['outdoor_temp'].mean()
            avg_wind_speed = session['wind_speed'].mean()
            avg_indoor_temp = session['indoor_temp'].mean()
            heating_sessions.append({
                "rate": rate,
                "outdoor_temp": avg_outdoor_temp,
                "wind_speed": avg_wind_speed,
                "indoor_temp": avg_indoor_temp,
            })

        # Konservativt: kräv tillräckligt många sessioner innan vi litar på RF-modellen,
        # annars behåller vi None så fallbacken 0.3 används (inget overfitting på fåtal punkter).
        if len(heating_sessions) < 15:
            return None

        model_df = pd.DataFrame(heating_sessions)
        X = model_df[['outdoor_temp', 'wind_speed', 'indoor_temp']]
        y = model_df['rate']

        model = RandomForestRegressor(n_estimators=100, max_depth=6, random_state=42)
        model.fit(X, y)

        print(f"🏠 Husets Digitala Tvilling: Uppvärmningsmodell tränad på {len(heating_sessions)} sessioner.")

        try:
            with sm_logger.get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute("UPDATE system_settings SET house_heating_model = %s, house_heating_model_time = %s WHERE id = 1", (pickle.dumps(model), now))
                conn.commit()
        except Exception as e:
            print(f"❌ Fel vid sparande av husets uppvärmningsmodell till databasen: {e}")
            traceback.print_exc()

        _cached_house_heating_model = model
        _cached_house_heating_time = now
        return model

    except Exception as e:
        print(f"❌ Fel vid beräkning av husets uppvärmningsmodell: {e}")
        traceback.print_exc()
        return None

def predict_house_heating_rate(outdoor_temp, wind_speed, indoor_temp, model):
    """ Förutspår uppvärmningstakten (°C/h) med ML-modellen """
    if model is None: return 0.3 # Fallback 0.3 grader i timmen
    if outdoor_temp is None: outdoor_temp = 0.0
    if wind_speed is None: wind_speed = 2.0
    if indoor_temp is None: indoor_temp = 20.0
    
    df_predict = pd.DataFrame({'outdoor_temp': [outdoor_temp], 'wind_speed': [wind_speed], 'indoor_temp': [indoor_temp]})
    rate = model.predict(df_predict)[0]
    return max(0.1, min(rate, 1.0))

if __name__ == '__main__':
    # För att testa filen manuellt
    # FIX: get_heating_rate_model returnerar en 3-tupel och predict_heating_rate tar 5 argument.
    intercept, slope_out, slope_spa = get_heating_rate_model(max_age_hours=0, force_recalculation=True)

    if intercept:
        print("\\n--- Testar modellen ---")
        for temp in [-10, 0, 10, 20]:
            predicted_rate = predict_heating_rate(temp, 38.0, intercept, slope_out, slope_spa)
            print(f"Vid {temp}°C ute, förväntad uppvärmningstakt: {predicted_rate:.2f} °C/timme")
