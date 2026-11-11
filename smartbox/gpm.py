"""
gpm.py – Global Priority Manager (Master Logic Tree)

MASTER HIERARCHY (Utvärderas kontinuerligt. Högre siffra överstyr alltid lägre siffra):
Prio 12: HÅRDKODAD SÄKERHET (Anti-Overheat) - Max 65°C VV, 40°C Spa. Failsafe 21°C för pump.
Prio 11: MANUELL TVÅNGSVÄRME - Överstyr allt. Värmer mot target omedelbart. Stängs ovillkorligen av kl 23:00.
Prio 10: PREDIKTIV PEAK SHAVING - Stryper EV och Spa omedelbart om E_prognos hotar gränsen.
Prio 9:  WATCHDOG & FAILSAFE - Tvingar 21°C om Modbus-kontakt tappas > 45 minuter.
Prio 8:  KOMPRESSORSKYDD (Dwell Time) - Låser AI:n i CHEAP (60m) / EXPENSIVE (45m).
Prio 7:  LEGIONELLA - Tvingande var 14:e dag till 60°C. Proaktiv start dag 12+ vid sol/minuspris.
Prio 6:  VARMVATTEN (Failsafe) - Tvingar produktion om beredaren sjunker under 38°C (Dusch-garanti).
Prio 5.8: PREDIKTIVT VARMVATTEN - Föruppvärmer om ML-modellen bedömer sannolikhet >40% för nära förestående dusch.
Prio 5:  HUSVÄRME (Adaptive Comfort) - Styrs av spot-spread och modifieras av husets termiska tröghet (ML).
Prio 4:  SPABAD (Smart Mode) - Max vid minuspris, dynamisk soltröskel, eller ML-optimerad uppvärmning mot tid.
Prio 3.8: PREDIKTIV ELBILSLADDNING (ML) - Tvingar laddning om bilen snart ska åka och batteriet är lågt.
Prio 3.5: EV BATTERISKYDD - Tvingar laddningen att fortsätta i minst 30 minuter efter start.
Prio 3:  ELBILSLADDNING - Laddar baserat på Spread-Scoring och tillgänglig hus-ström.
Prio 2:  SOLCELLSOPTIMERING - Vid minuspris används PI-regulator för att hålla nettoexport exakt på 0 W.
Prio 1:  NORMALDRIFT / DVALA - Spa dalar mot 15°C i ECO, pump på sparläge (20°C).
"""

from datetime import datetime, timedelta, timezone
import learning
import logger
import notifier
import ev_power
import nordpool


def _percentile(values, pct):
    """Enkel percentil (nearest-rank) av en lista. Används för spread-adaptiva pris-trösklar
    i stället för magiska multiplikatorer (×1.4/×1.5/×2.0) som är blinda för dagens spridning."""
    if not values:
        return None
    s = sorted(values)
    k = max(0, min(len(s) - 1, int(round((pct / 100.0) * (len(s) - 1)))))
    return s[k]


SOLAR_EV_EXPENSIVE_IMPORT_W = 500.0   # solladdning som köper mer än så här från nätet vid dyr el justeras varje minut i stället för var 5:e
SOLAR_EV_FAST_EVAL_MIN = 1.0


def _is_expensive(price, all_prices):
    """Dyr = i dygnets dyraste tredjedel (samma definition som appens 'dyrt'); en platt dag eller minuspris räknas inte som dyr."""
    p67 = _percentile(all_prices, 67)
    return price is not None and price > 0 and p67 is not None and price >= p67


SPA_EV_PAUSE_MAX_DROP_C = 5.0      # badet pausas under bilens laddfönster så länge det är högst så här många grader under normaltemperaturen

def _ev_fuse_room(state, house_excluding_ev):
    """Ledig ström för bilarna mot huvudsäkringen. Med färsk mätdata kommer taket från den termiska
    säkringsmodellen (fuse_guard.py, satt av main.py som 'ev_fuse_cap_a') - den tål korta toppar
    och stryper på säkringens värme, inte på en enskild minut. Utan den (tester, Tibber nere):
    den tidigare formeln säkring - husets last (värsta fasen)."""
    cap = state.get('ev_fuse_cap_a')
    if cap is not None:
        return max(0, int(cap))
    return max(0, state.get('max_fuse_a', 16) - house_excluding_ev)



# Husvärme UTAN innegivare: motorn ser inte om huset kyls ut, så sänkningen vid dyr el får
# skydd i stället: kortare tid i sträck, och mindre (eller ingen) sänkning när det är kallt ute.
NO_SENSOR_MAX_LOWERED_S = 3 * 3600     # högst 3 h sänkt i sträck ...
NO_SENSOR_RECOVER_S = 3600             # ... sedan minst 1 h normal värme innan nästa sänkning
NO_SENSOR_COLD_LIMIT_C = -5.0          # kallare än så: högst 1 °C sänkning
NO_SENSOR_NO_DROP_C = -15.0            # kallare än så: ingen sänkning alls


def _car_specs(state, car_ids):
    """Varje bils egenskaper ur installationen (main.py bygger car_specs ur house_config: laddboxens faser och
    maxström). phases: "1" = alltid 1-fas, "3" = alltid 3-fas, "auto" = kan växla. Inga bilnamn i koden."""
    specs = state.get('car_specs') or {}
    out = {}
    for cid in car_ids:
        s = specs.get(cid) or {}
        ph = str(s.get('phases', 'auto')).lower()
        out[cid] = {"name": s.get("name") or cid.capitalize(), "max_a": int(s.get("max_a") or 16),
                    "phases": ph if ph in ("1", "3", "auto") else "auto", "max_charge_kw": s.get("max_charge_kw")}
    return out


def _primary_car(cars, prios):
    """Den prioriterade bilen: den första med prioritet 1, annars den sista bland dem med lägst siffra
    (samma val som förut med två bilar: Nissan bara om den har prio 1, annars Tesla)."""
    for cid in cars:
        if prios.get(cid) == 1:
            return cid
    low = min(prios.get(c, 9) for c in cars)
    return [c for c in cars if prios.get(c, 9) == low][-1]


def _split_amps(final, cars, prios, specs, min_a, other_share=None):
    """Fördelar final A mellan bilarna som ska laddas. Två bilar: exakt den gamla regeln (den prioriterade
    får 60 %, den andra other_share eller resten; når någon inte min_a får den andra allt). Fler: i prioritetsordning."""
    out = {c: 0 for c in cars}
    if not cars:
        return out
    cap = lambda c: specs[c]["max_a"]
    if len(cars) == 1:
        out[cars[0]] = min(final, cap(cars[0]))
        return out
    if len(cars) == 2:
        p = _primary_car(cars, prios)
        o = cars[1] if cars[0] == p else cars[0]
        out[p] = min(int(final * 0.6), cap(p))
        out[o] = min(final - out[p], cap(o)) if other_share is None else min(int(final * other_share), cap(o))
        if out[cars[0]] < min_a:
            out[cars[0]] = 0
            out[cars[1]] = min(final, cap(cars[1]))
        if out[cars[1]] < min_a:
            out[cars[1]] = 0
            out[cars[0]] = min(final, cap(cars[0]))
        for c in cars:
            out[c] = min(out[c], cap(c))
        return out
    left = final
    for c in sorted(cars, key=lambda c: (prios.get(c, 9), cars.index(c))):
        a = min(left, cap(c))
        if a >= min_a:
            out[c] = a
            left -= a
    return out


def no_sensor_heat(mode, outdoor_c, cheap_t, expensive_t, lowered_since, recover_until, now):
    """(läge, måltemp, lowered_since, recover_until, förklaring) för ett hus utan innegivare."""
    if mode != "EXPENSIVE":
        return mode, cheap_t, None, recover_until, None
    if recover_until is not None and now < recover_until:
        left = int((recover_until - now).total_seconds() // 60)
        return "CHEAP", cheap_t, None, recover_until, (
            f"Utan innegivare: huset har varit sänkt länge - normal värme ett tag till ({left} min) innan nästa sänkning.")
    out = 0.0 if outdoor_c is None else float(outdoor_c)
    drop = max(0.0, cheap_t - expensive_t)
    if out < NO_SENSOR_NO_DROP_C:
        drop = 0.0
    elif out < NO_SENSOR_COLD_LIMIT_C:
        drop = min(drop, 1.0)
    if drop <= 0:
        return "CHEAP", cheap_t, None, None, f"Utan innegivare: för kallt ute ({out:.0f}°C) för att sänka värmen - håller normal värme."
    lowered_since = lowered_since or now
    if (now - lowered_since).total_seconds() >= NO_SENSOR_MAX_LOWERED_S:
        return "CHEAP", cheap_t, None, now + timedelta(seconds=NO_SENSOR_RECOVER_S), (
            f"Utan innegivare: värmen har varit sänkt i {NO_SENSOR_MAX_LOWERED_S // 3600} h - höjer igen en timme så huset inte kyls ut.")
    since_min = int((now - lowered_since).total_seconds() // 60)
    return "EXPENSIVE", cheap_t - drop, lowered_since, None, (
        f"Utan innegivare: dyr el - sänker värmen {drop:.0f}°C (sänkt i {since_min} min, högst {NO_SENSOR_MAX_LOWERED_S // 3600} h i sträck).")


class GlobalPriorityManager:
    def __init__(self):
        self.pump_mode_lock_until = None
        self.current_pump_mode = "EXPENSIVE"
        # PI-regulator för solcellsexport
        self.pi_integral_error = 0.0
        self.last_pi_time = None
        self.kp = 0.005  # Proportional gain
        self.ki = 0.0005 # Integral gain
        
        self.ev_charging_since = {} # Per-car tracking for battery protection
       # Realtids-beräkning för EV Solcellsladdning
        self.ev_solar_last_eval_time = None
        self.ev_solar_target_amps = 0
        self.ev_solar_target_phases = 0
        self.ev_solar_charge_active = False
        self.ev_solar_phase_pause = False  # FIX #16: tillfällig 0A-paus under kontaktor-cooldown
        self.last_global_phase_switch = None
        self.avg_net_history = []
        self.spa_solar_since = None       # när spabadets solvärme startade (hysteres, se _spa_solar_hold)
        self.spa_cooldown_until = None
        self.prio5_hysteresis_active = False
        self.no_sensor_lowered_since = None   # husvärme utan innegivare: sänkt sedan
        self.no_sensor_recover_until = None   # ... och normal värme minst till
        # FIX: borttagen död variabel prio5_min_hysteresis_active (skrevs/lästes aldrig).

        # För larm om hög nettoeffekt (15 minuter)
        self.high_load_start_time = None
        self.high_load_notified = False

        # Återställ kompressorspärren om containern just startade om
        self._restore_compressor_lock()


    SPA_SOLAR_MIN_RUN = timedelta(minutes=10)

    @staticmethod
    def _spa_draw(state):
        """Vad spabadets värmare drar just nu (W), 0 om den inte värmer."""
        w = state.get('spa_measured_w')
        return float(w) if w is not None and w > 1000.0 else 0.0

    def _spa_solar_hold(self, avg_net, state, now, threshold):
        """Fortsätt solvärmen i spabadet: överskottet räknas UTAN badets egen värmare (annars stänger badet av sig
        självt när det börjar dra 3 kW, och slår på igen när det stängt - av/på med några minuters mellanrum,
        2026-11-04), och badet går minst SPA_SOLAR_MIN_RUN innan det får stängas."""
        if self.spa_solar_since is None:
            return False
        if now - self.spa_solar_since < self.SPA_SOLAR_MIN_RUN:
            return True
        if avg_net - self._spa_draw(state) < threshold:
            return True
        self.spa_solar_since = None
        return False
    def _restore_compressor_lock(self):
        try:
            with logger.get_db() as conn, conn.cursor() as cur:
                cur.execute("SELECT active_mode, timestamp FROM sensor_log WHERE active_mode IS NOT NULL ORDER BY timestamp DESC LIMIT 1")
                row = cur.fetchone()
                if row:
                    last_mode, last_ts = row[0], row[1]
                    if (datetime.now(last_ts.tzinfo) - last_ts) < timedelta(minutes=45):
                        self.current_pump_mode = last_mode
                        # FIX: Återställ även kompressorspärren över omstart, annars kan pumpen
                        # korttidscyklas direkt efter omstart om priset just växlat läge.
                        # Behåll last_ts tidszon (tz-aware) så jämförelsen mot now (tz-aware) i Prio 8 funkar.
                        dwell_mins = 60 if last_mode == "CHEAP" else 45
                        lock_until = last_ts + timedelta(minutes=dwell_mins)
                        if lock_until > datetime.now(last_ts.tzinfo):
                            self.pump_mode_lock_until = lock_until
        except Exception as e:
            # FIX: Logga felet i stället för att svälja det helt tyst.
            print(f"GPM _restore_compressor_lock misslyckades: {e}")

    def evaluate(self, state: dict) -> dict:
        now = state.get('now') or datetime.now(timezone.utc)
        # FIX: gör now tz-AWARE så jämförelsen mot tz-aware pump_mode_lock_until (Prio 8, från DB)
        # aldrig kraschar. Produktionen skickar alltid aware now; detta skyddar default/test-vägen.
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        price = state.get('current_price', 0.0)
        # FIX: current_price kan vara explicit None i state (nordpool.get_price_info
        # returnerar None när det saknas pris i DB för aktuell kvart; main.py sätter
        # nyckeln oberoende av det). .get()'s default gäller bara vid SAKNAD nyckel,
        # så None når sig till jämförelser som `price < 0` nedan (#208) → TypeError.
        # Normalisera till det avsedda fallback-värdet 0.0.
        if price is None:
            price = 0.0
        # EKONOMISKT OPTIMUM vid minuspris: paid_to_import = djupt minuspris där den verkliga
        # köpkostnaden (nordpool.full_buy_cost - moms+nätavgift+skatt, källoberoende formel)
        # blir negativ → maxa nätuttag + strypa solen (importera allt → max betalning).
        paid_to_import = price is not None and nordpool.full_buy_cost(price, now) < 0
        pv_power = state.get('pv_power_w', 0.0)
        avg_net = state.get('avg_net_w', 0.0)
        
        dyn_limit = state.get('dynamic_limit', 99.0)
        hysteresis = state.get('hysteresis', 0.10)
        cooling_rate = state.get('predicted_cooling_rate', 0.0)
        
        # --- 1. TVILLING-JUSTERAD PRISGRÄNS ---
        if cooling_rate > 0.15:
            dyn_limit += 0.30
        elif cooling_rate > 0.05:
            dyn_limit += 0.10

        # --- 2. HYSTERES & GRÅZON FÖR VÄRMEPUMPEN ---
        # Detta garanterar att pumpen inte stänger av och på hela tiden.
        # Den "kustar" bekvämt i gråzonen.
        if not hasattr(self, 'last_price_mode'):
            self.last_price_mode = "EXPENSIVE"
            
        # Tidstariffen räknas in (#179): dynamic_limit är rangordnad på spot + tariff, så priset jämförs likadant.
        # Utan tidstariff är tillägget 0 och allt är som förut.
        tou_now = nordpool.tou_spot_extra(now) if price is not None else 0.0
        price_cmp = nordpool.planning_buy_price(price, now)
        if price_cmp <= (dyn_limit - hysteresis):
            self.last_price_mode = "CHEAP"
        elif price_cmp >= (dyn_limit + hysteresis):
            self.last_price_mode = "EXPENSIVE"
            
        base_pump_mode = self.last_price_mode
        
        # --- Bilarna: valfritt antal, egenskaper ur installationen (car_specs) ---
        car_ids = list(state['car_ids']) if 'car_ids' in state else []
        specs = _car_specs(state, car_ids)

        # --- 3. INITIERA MED RÄTT PRISLÄGE (Kostnadsoptimerat) ---
        actions = {
            "spa_target": state.get('spa_low_temp', 15.0),
            "spa_eco": True,
            "pump_target_temp": state.get('temp_cheap', 22.0) if base_pump_mode == "CHEAP" else state.get('temp_expensive', 20.0),
            "water_target_temp": state.get('water_target_normal', 50.0) if base_pump_mode == "CHEAP" else (state.get('water_target_normal', 50.0) - 10.0),
            "pump_mode": base_pump_mode,
            "spa_solar_boost_active": False,
            "pump_run_water": False,
            "solar_limit_pct": 100,
            "log": []
        }
        for cid in car_ids:
            actions[f"{cid}_limit_a"] = 0
            actions[f"{cid}_set_phases"] = None
        
        symbol = nordpool.cost_settings().get("symbol", "kr")
        _pt = f"{price_cmp:.2f} {symbol}" + (f" inkl. tidstariff {tou_now:.2f}" if tou_now else "")
        if base_pump_mode == "CHEAP":
            actions["log"].append(f"🟢 Grundläge: Billig el ({_pt} <= {dyn_limit - hysteresis:.2f} {symbol}). Värmepump och Varmvatten i normaldrift.")
        elif price_cmp < (dyn_limit + hysteresis):
            actions["log"].append(f"⏸️ Grundläge: Gråzon ({_pt}). Ligger kvar i läge '{base_pump_mode}'.")
        else:
            actions["log"].append(f"🔴 Grundläge: Dyr el ({_pt} >= {dyn_limit + hysteresis:.2f} {symbol}). Värmepump styrs ner till sparläge.")

        self.avg_net_history.append(avg_net)
        if len(self.avg_net_history) > 5:
            self.avg_net_history.pop(0)
        rolling_avg_net = sum(self.avg_net_history) / len(self.avg_net_history)

        # --- 15-minuterslarm för hög nettoeffekt (bara relevant MED effekttariff) ---
        current_target_limit = state.get('current_target_limit', 10.0)
        power_limit_w = current_target_limit * 1000.0

        if state.get('peak_shaving_enabled', True) and avg_net > power_limit_w:
            if self.high_load_start_time is None:
                self.high_load_start_time = now
                self.high_load_notified = False
            else:
                time_above = now - self.high_load_start_time
                if time_above >= timedelta(minutes=15) and not self.high_load_notified:
                    notifier.alert_high_net_power(avg_net / 1000.0, current_target_limit, 15)
                    self.high_load_notified = True
                    actions["log"].append("🔔 LARM: Skickade notis om hög nettoförbrukning (>15 min).")
        else:
            self.high_load_start_time = None
            self.high_load_notified = False

        # --- Läs in och sanera EV-status (per bil) ---
        soc = {c: state.get(f'{c}_soc') for c in car_ids}
        completed = {c: state.get(f'{c}_charge_completed', False) for c in car_ids}
        prios = {c: state.get(f'{c}_prio', 2) for c in car_ids}
        connected = {c: state.get(f'{c}_connected', False) for c in car_ids}
        # Failsafe: Om SOC är tydligt under 95% men flaggan är satt, nollställ den.
        # Detta skyddar mot om `main.py` missar en uppdatering pga en tillfälligt otillgänglig sensor.
        for c in car_ids:
            if soc[c] is not None and soc[c] < 95 and completed[c]:
                completed[c] = False
                actions["log"].append(f"🔋 GPM Failsafe: {specs[c]['name']} SOC < 95%, återställer 'charge_completed' flaggan.")

        needs = {c: connected[c] and not completed[c] and (soc[c] is None or soc[c] < 98) for c in car_ids}
        any_ev_needs_charge = any(needs.values())

        for c in car_ids:
            if connected[c] and soc[c] is None:
                actions["log"].append(f"⚠️ GPM Failsafe: {specs[c]['name']} API offline (SOC saknas). Antar att laddning behövs.")

        EV_MIN_CHARGE_AMPS = 6
        EV_MAX_CHARGE_AMPS = 16

        # --- Prio 3.5: REAL-TIME SOLAR EV CHARGING (5-min intervall) ---
        THREE_PHASE_MIN_SURPLUS_W = -4200 # ~6A 3-fas
        ONE_PHASE_MIN_SURPLUS_W   = -1400 # ~6A 1-fas

        max_possible_phases = 3 if any(needs[c] and specs[c]["phases"] != "1" for c in car_ids) else 1

        if not hasattr(self, 'ev_solar_last_eval_time'):
            self.ev_solar_last_eval_time = None
            self.ev_solar_target_amps = 0
            self.ev_solar_target_phases = 0
            
        if any_ev_needs_charge:
            time_since_eval = (now - self.ev_solar_last_eval_time).total_seconds() / 60.0 if self.ev_solar_last_eval_time else 999.0
            
            if not self.ev_solar_charge_active:
                # ANVÄNDARREGEL: Ladda ALLTID på solöverskott (oavsett schema/pris) så länge det inte
                # skapar import. ONE_PHASE_MIN_SURPLUS_W (~1400W) är minsta överskott för 6A 1-fas utan
                # att köpa nätström – under det kan vi inte ladda utan att skapa bruttolast.
                if avg_net < ONE_PHASE_MIN_SURPLUS_W:
                    shaky = state.get('solar_is_shaky', False)
                    self.ev_solar_charge_active = True
                    self.ev_solar_last_eval_time = now

                    # Starta alltid med förra fasen om vi är inom 15 minuters spärren
                    locked_phase = None
                    if self.last_global_phase_switch and (now - self.last_global_phase_switch).total_seconds() < 15 * 60:
                        locked_phase = self.ev_solar_target_phases

                    # Vid skakig sol startar vi på 1-fas (mindre kontaktor-slitage vid moln-på/av);
                    # 3-fas bara när överskottet är stort OCH solen är stabil.
                    if avg_net < THREE_PHASE_MIN_SURPLUS_W and max_possible_phases == 3 and not shaky:
                        self.ev_solar_target_phases = locked_phase or 3
                        self.ev_solar_target_amps = min(16, int(-avg_net / 690.0))
                    else:
                        self.ev_solar_target_phases = locked_phase or 1
                        self.ev_solar_target_amps = min(20, int(-avg_net / 230.0))
                    _why = " (1-fas pga skakig sol)" if shaky else ""
                    actions["log"].append(f"☀️ Prio 3.5 (SOLAR EV): Startar sol-laddning{_why}! Mål: {self.ev_solar_target_amps}A på {self.ev_solar_target_phases}-fas (nollar {abs(avg_net):.0f}W överskott).")
            else:
                # Vi laddar redan. Uppdatera strömstyrkan var 5:e minut för att matcha överskottet.
                # 2026-10-30: köper vi el vid dyrt pris (solen försvann medan spabad/värmepump drog) justeras det varje minut, så att bilen inte laddar på dyr nätel i fem minuter.
                dyr_import = avg_net > SOLAR_EV_EXPENSIVE_IMPORT_W and _is_expensive(price, state.get('all_prices'))
                if time_since_eval >= 5.0 or (dyr_import and time_since_eval >= SOLAR_EV_FAST_EVAL_MIN):
                    self.ev_solar_last_eval_time = now
                    current_voltage = 690.0 if self.ev_solar_target_phases == 3 else 230.0
                    delta_amps = -avg_net / current_voltage
                    
                    new_amps = self.ev_solar_target_amps + delta_amps

                    rolling_delta_amps = -rolling_avg_net / current_voltage
                    rolling_new_amps = self.ev_solar_target_amps + rolling_delta_amps

                    # FIX #16: Skilj på "tillfällig paus pga kontaktorspärr" och "slut på solöverskott".
                    phase_switch_blocked_pause = False

                    # Automatiskt fasbyte om vi går utanför gränserna
                    if self.ev_solar_target_phases == 1 and rolling_new_amps >= 18.0 and max_possible_phases == 3:
                        if not self.last_global_phase_switch or (now - self.last_global_phase_switch).total_seconds() >= 15 * 60:
                            self.ev_solar_target_phases = 3
                            new_amps = (new_amps * 230.0) / 690.0
                            self.last_global_phase_switch = now
                            actions["log"].append(f"⚡ Prio 3.5 (Fasväxling): Går upp till 3-fas.")
                        else:
                            new_amps = 16.0
                            actions["log"].append(f"⏳ Prio 3.5 (Fasväxling): Kontaktor-skydd aktivt. Ligger kvar på 1-fas tills cooldown (15m) passerat.")
                    elif self.ev_solar_target_phases == 3 and (rolling_new_amps < 5.5 or max_possible_phases == 1):
                        if not self.last_global_phase_switch or (now - self.last_global_phase_switch).total_seconds() >= 15 * 60:
                            self.ev_solar_target_phases = 1
                            new_amps = (new_amps * 690.0) / 230.0
                            self.last_global_phase_switch = now
                            actions["log"].append(f"⚡ Prio 3.5 (Fasväxling): Går ner till 1-fas.")
                        else:
                            # FIX #16: Endast tillfällig paus under cooldown – avsluta INTE hela sol-sessionen.
                            new_amps = 0
                            phase_switch_blocked_pause = True
                            if self.ev_solar_target_amps > 0:
                                actions["log"].append(f"⏳ Prio 3.5 (Fasväxling): Kontaktor-skydd aktivt. Tvingas pausa laddning tillfälligt.")

                    new_amps = int(round(new_amps))

                    if phase_switch_blocked_pause:
                        # FIX #16: Håll kvar sol-laddningen (charge_active=True) men kör 0A denna cykel.
                        # Efter cooldown (15m) återupptas/fasväxlas laddningen utan omstart från noll.
                        self.ev_solar_target_amps = 0
                        self.ev_solar_phase_pause = True
                        actions["log"].append("☀️ Prio 3.5 (SOLAR EV): Pausar 0A under kontaktor-cooldown men behåller sol-sessionen aktiv.")
                    elif new_amps < EV_MIN_CHARGE_AMPS:
                        # Solen räcker inte till minimum. Stäng av sol-laddningen.
                        self.ev_solar_target_amps = 0
                        self.ev_solar_charge_active = False
                        self.ev_solar_phase_pause = False  # FIX #16: sessionen avslutad -> rensa pausflaggan
                        actions["log"].append(f"☀️ Prio 3.5 (SOLAR EV): Solöverskott borta (Netto: {avg_net:.0f}W). Avslutar sol-laddning (Batteriskyddet tar över om < 30 min).")
                    else:
                        self.ev_solar_target_amps = min(new_amps, 16 if self.ev_solar_target_phases == 3 else 20)
                        self.ev_solar_phase_pause = False  # FIX #16: riktig ström satt -> ingen aktiv paus
                        actions["log"].append(f"☀️ Prio 3.5 (SOLAR EV): 5-min uppdatering. Nytt mål: {self.ev_solar_target_amps}A på {self.ev_solar_target_phases}-fas (Netto låg på {avg_net:.0f}W).")
                else:
                    actions["log"].append(f"☀️ Prio 3.5 (SOLAR EV): Håller {self.ev_solar_target_amps}A på {self.ev_solar_target_phases}-fas. (Nästa utvärdering om {5.0 - time_since_eval:.1f} min)")

            if self.ev_solar_charge_active:
                target_phases = self.ev_solar_target_phases
                
                phase_change_in_progress = False
                for car_id in car_ids:
                    phases_str = state.get(f'{car_id}_phases')
                    if needs[car_id] and phases_str:
                        fixed = specs[car_id]["phases"]
                        target_phases_for_car = 1 if fixed == "1" else 3 if fixed == "3" else target_phases
                        current_phases = 3 if any(x in str(phases_str) for x in ['Three', '3', 'auto', 'Auto']) else 1
                        if current_phases != target_phases_for_car:
                            actions[f"{car_id}_set_phases"] = target_phases_for_car
                            actions["log"].append(f"⚡ Prio 3.5 (Fasväxling): Växlar {specs[car_id]['name']} till {target_phases_for_car}-fas.")
                            phase_change_in_progress = True

                if phase_change_in_progress:
                    for car_id in car_ids:
                        actions[f"{car_id}_limit_a"] = 0
                    # Pausa utvärderingstiden så vi inte tappar tid under bytet
                    self.ev_solar_last_eval_time = now
                else:
                    # Tilldela strömmen, skydda mot överbelastning
                    house_load_a = state.get('house_load_a', 0)
                    ev_actual_a = state.get('ev_actual_a', 0)
                    house_excluding_ev = max(0, int(house_load_a) - int(ev_actual_a))
                    # BUGFIX: Ignorera säkringsbegränsning om vi exporterar mycket solel
                    if avg_net < -500:
                        # Export = utgående solel: nätsidans tak behövs inte. Lastsidans tak (om en andra mätpunkt är
                        # konfigurerad) gäller ändå - exporten minskar inte strömmen genom en säkring bakom batteri/sol.
                        _load_cap = state.get('ev_load_cap_a')
                        available_amps_realtime = max(0, int(_load_cap)) if _load_cap is not None else max(0, state.get('max_fuse_a', 16))
                    else:
                        available_amps_realtime = _ev_fuse_room(state, house_excluding_ev)
                    final_ev_amps = min(self.ev_solar_target_amps, available_amps_realtime)

                    if final_ev_amps >= EV_MIN_CHARGE_AMPS:
                        # --- Prioritetslogik fördelar strömmen (den prioriterade 60 %, den andra 40 %) ---
                        _cars = [c for c in car_ids if needs[c]]
                        for c, a in _split_amps(final_ev_amps, _cars, prios, specs, EV_MIN_CHARGE_AMPS, other_share=0.4).items():
                            actions[f"{c}_limit_a"] = a
                    else:
                        for c in car_ids:
                            actions[f"{c}_limit_a"] = 0
                        # FIX #16: Avsluta INTE sol-sessionen om vi bara pausar 0A under kontaktor-cooldown.
                        if getattr(self, 'ev_solar_phase_pause', False):
                            actions["log"].append("☀️ Prio 3.5 (SOLAR EV): 0A under kontaktor-cooldown. Behåller sol-sessionen aktiv.")
                        else:
                            self.ev_solar_charge_active = False
                            actions["log"].append(f"☀️ Prio 3.5 (SOLAR EV): Säkring begränsar, kan ej starta laddning.")
        else:
            # No significant surplus, or solar charging was active but no longer needed
            self.ev_solar_charge_active = False
            self.ev_solar_phase_pause = False  # FIX #16: ingen sol-laddning -> rensa pausflaggan

            # 1-fasbilar ska alltid vara på 1-fas; bilar som kan växla återställs till 3-fas
            for c in car_ids:
                _ph = state.get(f'{c}_phases')
                if specs[c]["phases"] == "1" and _ph and 'Three' in _ph:
                    actions[f"{c}_set_phases"] = 1
                elif specs[c]["phases"] != "1" and _ph and 'Single' in _ph:
                    actions[f"{c}_set_phases"] = 3
                    actions["log"].append(f"☀️ Prio 3.5 (SOLAR EV): Ingen sol-laddning aktiv. Återställer {specs[c]['name']} till 3-fas.")

        # --- Prio 2: SOLCELLSOPTIMERING (PI-Regulator) ---
        current_solar_limit_pct = state.get('current_solar_limit_pct')
        solar_auto = state.get('solar_auto_export', True)     # Solceller -> Automatisk exportstyrning (av = användaren styr)
        if price < 0 and solar_auto:
            # --- AI: Auto-Tuning av PI-parametrar ---
            self.kp, self.ki = learning.get_optimal_pi_params()
            
            # PI-regulator för att hålla nettoexporten på 0 W
            setpoint = 0.0
            error = setpoint - avg_net

            # Beräkna dt (tidsskillnad sedan senaste körning, antar 60s första gången)
            dt = (now - self.last_pi_time).total_seconds() if self.last_pi_time is not None else 60.0
            self.last_pi_time = now

            # Proportional-term
            p_term = self.kp * error

            # Integral-term med anti-windup
            self.pi_integral_error += error * dt
            # Begränsa integralen så den inte kan justera med mer än 10%
            self.pi_integral_error = max(min(self.pi_integral_error, 20000), -20000)
            i_term = self.ki * self.pi_integral_error

            # Total justering (output u(t))
            adjustment_pct = p_term + i_term

            current_limit = current_solar_limit_pct if current_solar_limit_pct is not None else 100.0
            new_limit = current_limit - adjustment_pct
            new_limit = int(max(0, min(100, new_limit)))

            actions["solar_limit_pct"] = new_limit
            actions["log"].append(f"☀️ Prio 2 (SOL-PI): Minuspris. Netto: {avg_net:.0f}W. Fel: {error:.0f}. Justering: {-adjustment_pct:.2f}%. Ny gräns: {new_limit}%.")
        elif solar_auto:
            # Återställ PI-regulatorn och gränsen när det inte är minuspris
            self.pi_integral_error = 0.0
            self.last_pi_time = None
            if current_solar_limit_pct is not None and current_solar_limit_pct < 100:
                actions["solar_limit_pct"] = 100
                actions["log"].append("☀️ Prio 2 (SOL-PI): Pris > 0 -> Återställer gräns till 100%.")

        # --- Prio 3: ELBILSLADDNING (Spread-Scoring) ---
        full = {c: soc[c] is not None and soc[c] >= 98 for c in car_ids}

        def _zero_all():
            for c in car_ids:
                actions[f"{c}_limit_a"] = 0

        # Hoppa över 15-minutersschemat helt om vi redan laddar för fullt på solenergi i realtid!
        if not self.ev_solar_charge_active:
            if not any_ev_needs_charge:
                _zero_all()
                for c in car_ids:
                    if completed[c] or full[c]:
                        actions["log"].append(f"🚗 Prio 3 (EV): {specs[c]['name']} är fulladdad ({soc[c]}%). Stoppar laddning (0A).")
                if all(soc[c] is None for c in car_ids):
                    actions["log"].append("🚗 Prio 3 (EV): Ingen bil ansluten som kräver laddning (0A).")
            else:
                ev_plan = state.get('ev_plan')
                if ev_plan is not None and not ev_plan.empty:
                    # Hitta aktuell 15-minuters-slot i planen
                    current_slot_minute = (now.minute // 15) * 15
                    current_slot_time_naive = now.replace(minute=current_slot_minute, second=0, microsecond=0, tzinfo=None)

                    # Hitta raden i planen som matchar nuvarande tidsslot
                    current_plan_row = ev_plan[ev_plan['t_slot'] == current_slot_time_naive]

                    if not current_plan_row.empty:
                        row = current_plan_row.iloc[0]
                        kw = {c: (row.get(f'{c}_kw', 0.0) if needs[c] else 0.0) for c in car_ids}
                        total_planned_kw = sum(kw.values())

                        if total_planned_kw > 0:
                            # Faser per bil: 1-fasbilar alltid 1, annars laddboxens nuvarande läge
                            def _ph(c):
                                if specs[c]["phases"] == "1":
                                    return 1
                                if specs[c]["phases"] == "3":
                                    return 3
                                return 3 if any(x in str(state.get(f'{c}_phases')) for x in ['Three', '3', 'auto', 'Auto']) else 1
                            planned = {c: (ev_power.amps_for_kw(kw[c], specs[c].get("max_charge_kw"), specs[c]["max_a"], _ph(c)) if kw[c] > 0 else 0) for c in car_ids}
                            planned_amps = sum(planned.values())

                            panic = {c: (bool(row.get(f'{c}_panic', False)) if f'{c}_panic' in row else False) for c in car_ids}
                            for c in car_ids:
                                actions[f'{c}_panic'] = panic[c]

                            house_load_a = state.get('house_load_a', 0)
                            ev_actual_a = state.get('ev_actual_a', 0)
                            house_excluding_ev = max(0, int(house_load_a) - int(ev_actual_a))
                            # BUGFIX: Tibber mäter RMS-ström (positiv). Om vi exporterar stort
                            # är fasströmmen utgående solel. Elbilen minskar denna, så vi nollar begränsningen.
                            if avg_net < -500:
                                house_excluding_ev = 0
                            available_amps_realtime = _ev_fuse_room(state, house_excluding_ev)
                            final_amps = min(planned_amps, available_amps_realtime)
                            if final_amps < 6:
                                final_amps = 0

                            # --- Prioritetslogik fördelar strömmen (den prioriterade 60 %, den andra resten) ---
                            _cars = [c for c in car_ids if planned[c] > 0]
                            for c, a_ in _split_amps(final_amps, _cars, prios, specs, EV_MIN_CHARGE_AMPS).items():
                                actions[f'{c}_limit_a'] = a_

                            if final_amps == 0 and planned_amps > 0:
                                actions["log"].append(f"🚗 Prio 3 (EV Plan): Schemat vill ladda ({planned_amps}A), men huset och säkringen har 0A ledig kapacitet just nu. Pausar.")
                            else:
                                panic_str = " (PANIC MODE aktivt!)" if any(panic.values()) else ""
                                _set = ", ".join(f"{specs[c]['name']}: {actions[f'{c}_limit_a']}A" for c in car_ids)
                                actions["log"].append(f"🚗 Prio 3 (EV Plan): Laddar enligt schema{panic_str}. Husets säkring tillåter {available_amps_realtime}A. Sätter {_set}.")
                        else:
                            _zero_all()
                            actions["log"].append("🚗 Prio 3 (EV Plan): Pausar laddning enligt plan.")
                    else:
                        _zero_all()
                        actions["log"].append("🚗 Prio 3 (EV Plan): Utanför planerad laddningstid.")
                else:
                    _zero_all()
                    actions["log"].append("🚗 Prio 3 (EV): Väntar på att laddningsplan ska genereras.")
        else:
            actions["log"].append("🚗 Prio 3 (EV Plan): Schemalagd laddning ignoreras till förmån för Prio 3.5 (Sol-laddning aktiv).")

        # --- Prio 3.8: PREDIKTIV ELBILSLADDNING (AI Vanor) ---
        for car_id in car_ids:
            soc = state.get(f'{car_id}_soc')
            connected = state.get(f'{car_id}_connected', False)
            profile = state.get(f'{car_id}_habit_profile', {})
            
            if connected and soc is not None and soc < 40 and profile:
                current_hour = now.hour
                current_dow = now.weekday()
                prob_now = profile.get((current_dow, current_hour), 1.0)
                
                # Kolla sannolikheten att bilen är hemma de kommande 3 timmarna
                future_probs = [profile.get(((now + timedelta(hours=i)).weekday(), (now + timedelta(hours=i)).hour), 1.0) for i in range(1, 4)]
                min_future_prob = min(future_probs)
                
                # Om bilen är hemma nu (>60%) men sannolikheten droppar under 30% snart = avfärd närmar sig
                if prob_now > 0.60 and min_future_prob < 0.30:
                    current_limit = actions.get(f"{car_id}_limit_a", 0)
                    if current_limit < 10:
                        # FIX #39: Begränsa underhållsladdningen mot husets lediga säkringskapacitet
                        # så att 10A inte överskrider huvudsäkringen tillsammans med övrig last.
                        # Undanta rent solöverskott (samma -500W-konvention som Prio 3/3.5): då
                        # är fasströmmen utgående solel och bilen minskar bara exporten.
                        target_p38_amps = 10
                        if avg_net >= -500:
                            house_load_a = state.get('house_load_a', 0)
                            ev_actual_a = state.get('ev_actual_a', 0)
                            house_excluding_ev = max(0, int(house_load_a) - int(ev_actual_a))
                            available_amps_realtime = _ev_fuse_room(state, house_excluding_ev)
                            target_p38_amps = min(10, available_amps_realtime)
                        # Behåll redan beslutad ström om den är minst lika hög (boosta bara uppåt mot 10A).
                        target_p38_amps = max(target_p38_amps, current_limit)
                        if target_p38_amps >= EV_MIN_CHARGE_AMPS:
                            actions[f"{car_id}_limit_a"] = target_p38_amps
                            actions["log"].append(f"🔮 Prio 3.8 (AI EV-Vanor): {car_id.capitalize()} har lågt batteri ({soc}%) och ML-modellen förutspår avfärd inom kort. Tvingar underhållsladdning ({target_p38_amps}A, säkringsbegränsad).")
                        else:
                            actions["log"].append(f"🔮 Prio 3.8 (AI EV-Vanor): {car_id.capitalize()} har lågt batteri ({soc}%) och avfärd förutspås, men säkringen har för lite ledig kapacitet ({target_p38_amps}A) för underhållsladdning just nu.")

        # --- Prio 4: SPABAD (Smart Mode / Sol / Minuspris) ---
        spa_temp = state.get('spa_temp')
        spa_max_temp = state.get('spa_max_temp', 40.0)
        spa_normal_temp = state.get('spa_normal_temp', 34.0)
        spa_low_temp = state.get('spa_low_temp', 15.0)
        
        # ML/data-förbättring #2: kontinuerlig sol-tröskel förankrad i spabadets värmar­effekt
        # (~3 kW) i stället för en grov 3-stegstrappa. Kräver att en växande andel av värmarens
        # effekt kommer från solen ju kallare badet är (nära måltemp räcker lite sol, långt ifrån
        # kräver vi nästan hela värmar­effekten som överskott så vi inte köper nätström till badet).
        # Använd den 3-fas-MÄTTA spabads-effekten när värmaren faktiskt drar (>1000 W); annars
        # faller vi tillbaka på typvärdet 3000 W för planering.
        _spa_meas = state.get('spa_measured_w')
        SPA_HEATER_W = _spa_meas if (_spa_meas is not None and _spa_meas > 1000.0) else 3000.0
        diff = (spa_max_temp - spa_temp) if spa_temp is not None else 0.0
        _spa_solar_frac = min(0.95, 0.33 + 0.09 * max(0.0, diff))
        spa_solar_threshold = -SPA_HEATER_W * _spa_solar_frac

        if spa_temp is not None and spa_temp >= (spa_max_temp - 0.2) and not self.spa_cooldown_until:
            self.spa_cooldown_until = now + timedelta(hours=1)
            
        if self.spa_cooldown_until and now >= self.spa_cooldown_until:
            self.spa_cooldown_until = None
            
        in_cooldown = self.spa_cooldown_until is not None
        
        # Extremt säker kontroll: Laddar bilarna enligt GPM, Manuell överstyrning, eller drar de faktiskt ström från nätet?
        ev_is_charging = (
            any(actions.get(f'{c}_limit_a', 0) >= EV_MIN_CHARGE_AMPS for c in car_ids) or
            any(state.get(f'{c}_force_amps', 0) > 0 for c in car_ids) or
            state.get('ev_actual_a', 0) >= 6
        )
        # FIX #34: Använd en liten marginal (>300W) i stället för >0 så att mätbrus/svag baslast
        # inte räknas som "köper el". Undanta dessutom rent solöverskott (Prio 3.5 sol-laddning),
        # analogt med peak shaving-undantaget längre ned – då ska spabadet inte blockeras i onödan.
        buying_electricity = avg_net > 300
        ev_is_solar_only = getattr(self, 'ev_solar_charge_active', False) and avg_net <= 300
        is_away = state.get('away_mode_active', False)

        # NY REGEL: Om vi köper el och elbil laddar -> Spabadet får INTE värmas
        if buying_electricity and ev_is_charging and not ev_is_solar_only and state.get('peak_shaving_enabled', True):          # regeln skyddar effekttaket: gäller inte när effektvakten är avstängd
            actions["spa_target"] = spa_low_temp
            actions["spa_eco"] = True
            actions["log"].append("🛁 Prio 4 (SPA): Elbil laddas och el köps från nätet. Blockerar spabadsvärme för att skydda effekttaket.")
        elif ev_is_charging and not ev_is_solar_only and price >= 0 and (spa_temp is None or spa_temp >= spa_normal_temp - SPA_EV_PAUSE_MAX_DROP_C):
            # 2026-10-27: Tesla nådde inte 100 % före avresan eftersom säkringen bara gav 9-13 A (badet drog ~3 kW). Under bilens laddfönster pausas därför badets
            # uppvärmning (Economy), så att all ledig ström går till bilen. Gäller inte solöverskott/minuspris, och inte om badet redan svalnat mer än 5 °C under normaltemperaturen.
            actions["spa_target"] = spa_low_temp
            actions["spa_eco"] = True
            actions["log"].append("🛁 Prio 4 (SPA): Bilen laddas. Pausar badets uppvärmning under laddfönstret så att mer ström finns kvar till bilen.")
        elif is_away:
            actions["spa_target"] = spa_low_temp
            actions["spa_eco"] = True
            actions["log"].append("🛁 Prio 4 (SPA): Bortaläge är aktivt. Blockerar all Spabadsvärme även vid minuspris.")
        elif price < 0:
            if in_cooldown:
                actions["spa_target"] = spa_normal_temp
                actions["spa_eco"] = False
                actions["log"].append("🛁 Prio 4 (SPA): Minuspris, men badet vilar (cooldown) för att skydda reläer.")
            else:
                actions["spa_target"] = spa_max_temp
                actions["spa_eco"] = False
                actions["spa_solar_boost_active"] = True
                actions["log"].append("🛁 Prio 4 (SPA): Minuspris -> Värmer bad till max för termisk lagring.")
        
        elif avg_net < spa_solar_threshold or self._spa_solar_hold(avg_net, state, now, spa_solar_threshold):
            if in_cooldown:
                actions["spa_target"] = spa_normal_temp
                actions["spa_eco"] = False
                actions["log"].append("🛁 Prio 4 (SPA): Solöverskott, men badet vilar (cooldown) för att skydda reläer.")
            else:
                actions["spa_target"] = spa_max_temp
                actions["spa_eco"] = False
                actions["spa_solar_boost_active"] = True
                if self.spa_solar_since is None:
                    self.spa_solar_since = now
                actions["log"].append(f"🛁 Prio 4 (SPA): Solöverskott (netto {avg_net:.0f}W, utan badet {avg_net - self._spa_draw(state):.0f}W, "
                                      f"tröskel {spa_solar_threshold:.0f}W) -> Värmer spabadet på solel.")

        elif state.get('spa_target_scheduled_active'):
            _bn = state.get('spa_bath_note')
            if state.get('spa_should_heat_now'):
                actions["spa_target"] = state.get('spa_target_scheduled', 38.0)
                actions["spa_eco"] = False
                actions["log"].append(f"🛁 Prio 4 (SPA): {_bn} -> Värmer nu på billiga timmar så att badet är varmt i tid." if _bn else
                                      "🛁 Prio 4 (SPA): Schema aktivt -> Dags att värma! AI:n kör spabadet mot måltemperaturen.")
            else:
                actions["spa_target"] = state.get('spa_low_temp', 15.0)
                actions["spa_eco"] = True
                actions["log"].append(f"🛁 Prio 4 (SPA): {_bn} -> Badet vilar på eco-golvet tills det är dags att värma." if _bn else
                                      "🛁 Prio 4 (SPA): Schema aktivt -> Avvaktar billigare/mer soliga timmar. Badet vilar i Economy Mode för att spara el.")
        else:
            # NYTT: Normaldrift och Prisspiks-skydd (Imiterar decisions.py logik)
            all_p = state.get('all_prices_tou') or state.get('all_prices')   # spot + tidstariff (#179)
            is_prisspik = False
            if price > 0 and all_p:
                # ML/data-förbättring #1: spread-adaptiv spik via dagens percentiler i stället
                # för fast ×1.4. Spik = priset ligger i dygnets dyraste topp (>=85:e percentilen)
                # OCH dagen faktiskt har spridning (annars är "spiken" bara brus på en platt dag).
                day_p85 = _percentile(all_p, 85)
                day_p50 = _percentile(all_p, 50)
                if day_p85 is not None and day_p50 is not None and price_cmp >= day_p85 and day_p85 > day_p50 * 1.10:
                    is_prisspik = True
                    
            if is_prisspik:
                actions["spa_target"] = spa_normal_temp - 2.0
                actions["spa_eco"] = False
                actions["log"].append(f"🛁 Prio 4 (SPA): Prisspik! Elpriset är högt. Sänker badet 2°C tillfälligt för att spara el.")
            else:
                # Standard Normaldrift - Håller badet varmt (inte Economy mode)
                actions["spa_target"] = spa_normal_temp
                actions["spa_eco"] = False
                actions["log"].append(f"🛁 Prio 4 (SPA): Normaldrift. Håller badet på {spa_normal_temp}°C.")

        # Inget spabad i installationen (has_spa=False från main.py): spabadsbesluten ovan gäller inget och ska varken
        # loggas eller påverka resten (issue #122/#123: användare utan spa såg spabeslut och fick spa-aviseringar).
        if not state.get('has_spa', True):
            actions["spa_solar_boost_active"] = False
            actions["log"] = [l for l in actions["log"] if "(SPA)" not in l and "spabad" not in l.lower()]

        # --- Prio 4.5: TERMISKT BATTERI (Varmvatten 180L) ---
        if price < 0 or avg_net < -2000:
            actions["water_target_temp"] = 60.0
            actions["pump_run_water"] = True
            actions["log"].append("🔋 Prio 4.5 (TERMISKT BATTERI): Gratis el / Solöverskott! Maximerar varmvattenberedaren till 60°C.")

        if not actions.get("spa_solar_boost_active"):
            self.spa_solar_since = None   # en annan regel (bilen, bortaläge ...) tog över: solvärmen i badet räknas som avslutad

        # --- Prio 5: HUSVÄRME (Adaptive Comfort & Solöverskott) ---
        indoor_temp = state.get('indoor_temp')
        indoor_min = state.get('indoor_min', 19.0)
        indoor_max = state.get('indoor_max', 22.5)
        outdoor_avg_5d = state.get('outdoor_avg_5d', 10.0)
        
        # SAMVERKAN MED THERMIA: använd pumpens EGEN värmestopp-tröskel (reg 19 "Heating
        # setpnt./start", utetemp där värmesäsongen slutar) i stället för en hårdkodad gräns.
        # Då blockerar GPM billig nattvärme exakt när pumpen ändå inte värmer huset. Fallback 14°C.
        heat_stop = state.get('heat_stop_outdoor')
        summer_threshold = heat_stop if (heat_stop is not None and heat_stop > 0) else 14.0
        is_summer = outdoor_avg_5d >= summer_threshold
        
        if indoor_temp is not None:
            # 1. Proaktiv avstängning (Derivata & Sol)
            is_heating_fast_by_sun = cooling_rate < -0.1 and pv_power > 500
            dynamic_indoor_max = indoor_max - 0.3 if is_heating_fast_by_sun else indoor_max      # var 22,2 fast (= 0,3 under 22,5)

            # 2. Aktivera Hysteres om vi når taket
            if indoor_temp >= dynamic_indoor_max:
                self.prio5_hysteresis_active = True
                
            # 3. Släpp Hysteres först när vi sjunkit under komfortgolvet (eller åtminstone 0.5 under max)
            release_temp = indoor_max - 0.5
            if indoor_temp <= release_temp:
                self.prio5_hysteresis_active = False

            if self.prio5_hysteresis_active:
                # Glidande skala för att undvika "knäppningar" i shunt/rör
                overtemp = indoor_temp - indoor_max
                if overtemp <= 0.1:
                    adjustment = -2.0
                elif overtemp <= 0.3:
                    adjustment = -3.5
                else:
                    adjustment = -5.0
                
                if indoor_temp < indoor_max:
                    adjustment = -2.0 # Mjuk start om vi klipper proaktivt
                    
                actions["pump_mode"] = "EXPENSIVE"
                actions["pump_target_temp"] = state.get('temp_expensive', 20.0) + adjustment
                
                reason_str = "Snabbt stigande sol-värme" if indoor_temp < indoor_max else f"För varmt inne ({indoor_temp:.1f}°C >= {indoor_max}°C)"
                actions["log"].append(f"🛑 Prio 5 (HUS): {reason_str}. Mjukt kompressor-stopp aktiverat ({adjustment}°C).")
                
            # Bara när kylan hållit i sig (main.py: 30 min i följd, sustained.py) - inte för en vädring.
            # Saknas nyckeln (tester, återuppspelning) gäller det gamla beteendet.
            elif indoor_temp < indoor_min and state.get('indoor_cold_confirmed', True):
                actions["pump_mode"] = "CHEAP"
                actions["pump_target_temp"] = state.get('temp_cheap', 22.0)
                actions["log"].append(f"🏠 Prio 5 (HUS): Kallt inne! ({indoor_temp:.1f}°C < {indoor_min}°C). Tvingar värme oavsett elpris.")
                
            # NYTT: Solöverskott driver värmen oavsett timpris!
            elif avg_net < -1500 and actions["pump_mode"] == "EXPENSIVE":
                # Lagra solvärme bara om huset inte redan är varmt: högst 0,5 °C under taket, och 1 °C under när solen
                # väntas fortsätta - då värmer den huset genom fönstren av sig själv (2026-11-04: 23 °C en solig förmiddag).
                sun_soon = state.get('sun_soon') or {}
                store_max = indoor_max - (1.0 if sun_soon.get('sunny') else 0.5)
                if is_summer:
                    actions["log"].append(f"☀️ Prio 5 (HUS): Solöverskott ignoreras för husvärme pga sommarläge ({outdoor_avg_5d:.1f}°C).")
                elif indoor_temp >= store_max:
                    why = "sol väntas de närmaste timmarna och värmer huset ändå" if sun_soon.get('sunny') else "huset är redan varmt"
                    actions["log"].append(f"☀️ Prio 5 (HUS): Solöverskott, men {why} ({indoor_temp:.1f}°C >= {store_max:.1f}°C). "
                                          f"Lagrar ingen värme - överskottet går till bil, spabad eller försäljning.")
                else:
                    actions["pump_mode"] = "CHEAP"
                    actions["pump_target_temp"] = state.get('temp_cheap', 22.0)
                    actions["log"].append(f"☀️ Prio 5 (HUS): Kraftigt solöverskott ({abs(avg_net):.0f} W). Tvingar värmepumpen att lagra gratis värme i husets golv/radiatorer!")
                
            elif actions["pump_mode"] == "CHEAP":
                target_t = state.get('temp_cheap', 22.0)
                
                if is_summer:
                    target_t = state.get('temp_expensive', 20.0)
                    actions["pump_mode"] = "EXPENSIVE"
                    actions["pump_target_temp"] = target_t
                    actions["log"].append(f"☀️ Prio 5 (HUS): Sommar-läge aktivt (5-dygnsmedel ute: {outdoor_avg_5d:.1f}°C). Blockerar billig nattvärme för att inte kringgå Värmestoppet.")
                else:
                    # Sol väntas (nästa dagsljus): den värmer huset genom fönstren, så nattens/morgonens lagring blir mindre
                    # och ingen extra överladdning görs (2026-11-04: lagrat till 23,3 °C inför en solig dag).
                    sun_day = state.get('sun_day') or {}
                    sunny_ahead = bool(sun_day.get('sunny'))
                    if sunny_ahead:
                        target_t = target_t - 0.5
                    # PREDIKTIV ÖVERLADDNING: Om priset är billigt nu, men en extrem prisspik är på väg de närmaste 6 timmarna, 
                    # trycker vi in extra värme i huset (upp till max-gränsen) så kompressorn kan vila helt genom toppen.
                    all_p = state.get('all_prices_tou') or state.get('all_prices')   # spot + tidstariff (#179)
                    if all_p:
                        current_idx = now.hour * 4 + (now.minute // 15)
                        future_prices = all_p[current_idx : current_idx + 24] # Kommande 6 timmarna
                        if future_prices:
                            max_future_price = max(future_prices)
                            # ML/data-förbättring #1: spread-adaptiv överladdning. Boosta bara om
                            # en kommande timme ligger i dygnets dyra topp (>=85:e perc) MEDAN vi nu
                            # är billiga (<=medianen), och dagen har verklig spridning. Ersätter de
                            # spread-blinda +0.50 kr / ×1.5.
                            day_p85 = _percentile(all_p, 85)
                            day_p50 = _percentile(all_p, 50)
                            if (not sunny_ahead and day_p85 is not None and day_p50 is not None
                                    and max_future_price >= day_p85 and price_cmp <= day_p50
                                    and day_p85 > day_p50 * 1.10):
                                target_t = min(target_t + 1.0, indoor_max)
                                actions["log"].append(f"🔋 Prio 5 (HUS): Prediktiv överladdning! Priset stiger snart till {max_future_price:.2f} {symbol} (dygnets topp). Boostar innetempen (+1°C) i förväg för att bygga termiskt batteri.")
                    
                    actions["pump_mode"] = "CHEAP"
                    actions["pump_target_temp"] = target_t
                    if "Prediktiv överladdning" not in actions["log"][-1]:
                        extra = f" Sol väntas ({sun_day.get('kwh', 0):.0f} kWh), lagrar 0,5 °C mindre." if sunny_ahead else ""
                        actions["log"].append(f"🏠 Prio 5 (HUS): Pris och villkor godkända -> Håller huset på {target_t}°C.{extra}")

        else:
            # Ingen innegivare: prisstyrningen ovan (grundläget) får skydd mot att huset kyls ut.
            if is_summer:
                self.no_sensor_lowered_since = None
            else:
                mode, target, self.no_sensor_lowered_since, self.no_sensor_recover_until, why = no_sensor_heat(
                    actions["pump_mode"], state.get('outdoor_temp'), state.get('temp_cheap', 22.0),
                    state.get('temp_expensive', 20.0), self.no_sensor_lowered_since, self.no_sensor_recover_until, now)
                if why:
                    actions["pump_mode"] = mode
                    actions["pump_target_temp"] = target
                    actions["log"].append(f"🏠 Prio 5 (HUS): {why}")

        # --- Prio 5.5: BORTALÄGE (AWAY MODE) ---
        if state.get('away_mode_active'):
            actions["spa_target"] = state.get('spa_low_temp', 15.0)
            actions["spa_eco"] = True
            actions["pump_run_water"] = False
            actions["water_target_temp"] = 10.0
            
            if state.get('away_recovering'):
                actions["pump_mode"] = "CHEAP"
                actions["pump_target_temp"] = state.get('temp_cheap', 22.0)
                actions["log"].append("✈️ Prio 5.5 (BORTA): Återgångsfas aktiv! Värmer huset inför hemkomst. Spabad i dvala, varmvatten AV.")
            else:
                actions["pump_mode"] = "EXPENSIVE"
                actions["pump_target_temp"] = 15.0
                actions["log"].append("✈️ Prio 5.5 (BORTA): Bortaläge aktivt. Huset frostskyddas (15°C). Spabad i dvala, varmvatten AV.")

        # --- Prio 5.8: PREDIKTIVT VARMVATTEN (AI Dusch) ---
        hw_prob = state.get('hw_probability', 0.0)
        water_temp = state.get('water_temp')
        water_target_normal = state.get('water_target_normal', 50.0)
        
        # Tröskel 0.55 (kalibrerad mot 60 dygns data): kvällens verkliga uttag (kl 17-23) ligger
        # på 0.47-0.63, medan natt-standby ligger ~0.35 → 0.55 föruppvärmer bara inför verkliga uttag.
        if hw_prob > 0.55 and water_temp is not None and water_temp < (water_target_normal - 2.0):
            if price <= (dyn_limit + state.get('hysteresis', 0.10)): # Undvik om extremt dyrt
                actions["water_target_temp"] = water_target_normal + 2.0 # Boosta
                actions["pump_run_water"] = True
                actions["log"].append(f"🔮 Prio 5.8 (AI DUSCH): Hög sannolikhet ({hw_prob*100:.0f}%) för varmvattenuttag snart. Föruppvärmer beredaren proaktivt.")

        # --- Prio 6 & 7: VARMVATTEN & LEGIONELLA ---
        days_leg = state.get('days_since_legionella', 0)
        leg_max = state.get('legionella_max_days', 14)
        if days_leg >= leg_max:
            actions["water_target_temp"] = 60.0
            actions["log"].append(f"🦠 Prio 7 (LEGIONELLA): {leg_max} dagar passerade -> Tvingande körning till 60°C.")
        elif days_leg >= (leg_max - 2) and (price < 0 or avg_net < -2000):
            actions["water_target_temp"] = 60.0
            actions["log"].append(f"🦠 Prio 7 (LEGIONELLA): Proaktiv körning (Dag {leg_max - 2}+ och gynnsamt pris/sol) till 60°C.")
            
        if water_temp is not None and water_temp < 38.0:
            actions["water_target_temp"] = state.get('water_target_normal', 50.0)
            actions["log"].append(f"💧 Prio 6 (VV-FAILSAFE): Vattnet är kritiskt svalt ({water_temp:.1f}°C). Tvingar varmvatten oavsett elpris och effekttak!")

        # --- Prio 8: KOMPRESSORSKYDD (State Memory) ---
        if self.pump_mode_lock_until and now < self.pump_mode_lock_until:
            actions["pump_mode"] = self.current_pump_mode
            # Säkerställ att tempen matchar det låsta läget
            if self.current_pump_mode == "CHEAP":
                actions["pump_target_temp"] = state.get('temp_cheap', 22.0)
            else:
                actions["pump_target_temp"] = state.get('temp_expensive', 20.0)
            actions["log"].append(f"⚙️ Prio 8 (KOMPRESSOR): Anti-Short-Cycle -> Låst i läge {self.current_pump_mode} till {self.pump_mode_lock_until.strftime('%H:%M')}.")
        else:
            if actions["pump_mode"] != self.current_pump_mode:
                lock_mins = 60 if actions["pump_mode"] == "CHEAP" else 45
                self.pump_mode_lock_until = now + timedelta(minutes=lock_mins)
                self.current_pump_mode = actions["pump_mode"]
                actions["log"].append(f"⚙️ Prio 8 (KOMPRESSOR): Byter läge till {actions['pump_mode']}, låser i {lock_mins} minuter.")

        # --- Prio 9: WATCHDOG & FAILSAFE ---
        seconds_since_hb = (now - state.get('last_heartbeat', now)).total_seconds()
        if seconds_since_hb > 45 * 60:
            outdoor = state.get('outdoor_temp')
            if outdoor is not None and outdoor > 16.0:
                actions["pump_target_temp"] = 15.0  # Värm inte huset i onödan på sommaren
                actions["log"].append("📡 Prio 9 (WATCHDOG): Tappat kontakt > 45 min (Sommar) -> Tvingar 15°C.")
            else:
                actions["pump_target_temp"] = 21.0
                actions["log"].append("📡 Prio 9 (WATCHDOG): Tappat kontakt > 45 min (Kallt ute) -> Tvingar 21°C.")
            
        brine_out = state.get('brine_out_temp')
        if brine_out is not None and brine_out <= -7.0:
            actions["log"].append(f"🥶 Prio 9 (FAILSAFE): Kritiskt låg köldbärartemperatur ({brine_out}°C). Risk för isbildning i borrhålet!")

        # --- EV 30-MINUTES BATTERY PROTECTION ---
        for car_id in car_ids:
            limit_key = f"{car_id}_limit_a"
            current_car_limit = actions.get(limit_key, 0)
            
            soc = state.get(f"{car_id}_soc")
            is_full = soc is not None and soc >= 98
            is_done = state.get(f"{car_id}_charge_completed", False)

            if not state.get(f"{car_id}_connected", True):
                self.ev_charging_since[car_id] = None      # inte inkopplad (#174): kontaktorskyddet har inget att skydda
            elif current_car_limit >= EV_MIN_CHARGE_AMPS:
                if self.ev_charging_since.get(car_id) is None:
                    self.ev_charging_since[car_id] = now
            else: # Car is not charging or charging below min amps
                if self.ev_charging_since.get(car_id) is not None:
                    if is_full or is_done:
                        self.ev_charging_since[car_id] = None # Bilen är full, släpp spärren!
                    else:
                        minutes_run = (now - self.ev_charging_since[car_id]).total_seconds() / 60.0
                        if minutes_run < 30.0:
                            actions[limit_key] = EV_MIN_CHARGE_AMPS
                            actions["log"].append(f"🔋 Prio 3.5 (BATTERISKYDD): {car_id.capitalize()} måste ladda 30 min i sträck för att skydda kontaktorerna. Tvingar fram {EV_MIN_CHARGE_AMPS}A. (Kört {minutes_run:.0f}/30 min).")
                        else:
                            self.ev_charging_since[car_id] = None # 30 minuter uppnått

        # --- Prio 11.5: MANUELL TVÅNGSLADDNING ELBIL ---
        for car_id in car_ids:
            force_amps = state.get(f'{car_id}_force_amps', 0)
            if force_amps > 0 and not state.get(f"{car_id}_connected", True):
                actions["log"].append(f"⚡ Prio 11.5 (MANUELL EV): {car_id.capitalize()} är inte inkopplad - tvångsladdningen väntar tills kabeln sitter i.")
            elif force_amps > 0:
                actions[f"{car_id}_limit_a"] = force_amps
                actions["log"].append(f"⚡ Prio 11.5 (MANUELL EV): {car_id.capitalize()} tvingas till {force_amps}A. Ignorerar effektvakt och scheman.")
                force_phase = state.get(f'{car_id}_force_phases', 0)
                if force_phase in [1, 3]:
                    _cur = str(state.get(f'{car_id}_phases', ''))
                    _cur_ph = 3 if any(x in _cur for x in ['Three', '3']) else 1
                    if _cur_ph != force_phase:  # begär fasbyte BARA om det faktiskt skiljer (annars loop → laddaren fastnar på 0A)
                        actions[f"{car_id}_set_phases"] = force_phase

        # --- Prio 11.6: MANUELL PAUS (EnergyWizard Mobil) --- stoppad av användaren: 0A tills Auto väljs. Manuell tvångsladdning (11.5) går före.
        for _car in car_ids:
            if state.get(f"{_car}_hold") and not (state.get(f"{_car}_force_amps", 0) or 0) > 0:
                actions[f"{_car}_limit_a"] = 0
                actions["log"].append(f"⏸️ Prio 11.6 (MANUELL PAUS): {_car.capitalize()} är stoppad av användaren. Håller 0A tills Auto väljs.")

        # --- Prio 11.2: MANUELL ECO ---
        if state.get('spa_force_eco', False):
            actions["spa_target"] = state.get('spa_low_temp', 15.0)
            actions["spa_eco"] = True
            actions["log"].append("💤 Prio 11.2 (MANUELL ECO): Economy Mode är tvingat PÅ från dashboarden. Blockerar all annan värme.")

        # --- Prio 11: MANUELL TVÅNGSVÄRME ---
        # FIX: borttaget meningslöst villkor 'not disable_spa_force_heat' (sattes aldrig till True).
        if state.get('spa_force_heat', False):
            actions["spa_target"] = state.get('spa_max_temp', 40.0)
            actions["spa_eco"] = False
            actions["log"].append("🔥 Prio 11 (TVÅNGSVÄRME): Manuell överstyrning -> Värmer bad omedelbart.")

        # --- Prio 10: PREDIKTIV PEAK SHAVING (Flyttad ner för att garantera huvudsäkringen!) ---
        if state.get('peak_shaving_enabled', True):
            consumed_kwh = state.get('consumed_kwh_this_hour', 0.0)
            minutes_left = 60 - now.minute
            
            current_target_limit = state.get('current_target_limit', 10.0)
            assumed_base_load_kw = state.get('predicted_base_load_kw', 2.5)
            reserve_kwh_needed = assumed_base_load_kw * (minutes_left / 60.0)
            allowed_kwh_now = current_target_limit - reserve_kwh_needed
            
            if consumed_kwh >= allowed_kwh_now and (consumed_kwh > 0.05 or minutes_left < 58):
                car_panic = {c: actions.get(f'{c}_panic', False) or state.get(f'{c}_force_amps', 0) > 0 for c in car_ids}
                
                # SÄKERHET: Om vi laddar på solöverskott drar vi inte ström från nätet.
                # Vi får därför inte strypa bilarna (eller badet) bara för att timbudgeten är full.
                is_importing = avg_net > 100
                ev_is_solar = self.ev_solar_charge_active and not is_importing
                spa_is_solar = actions.get("spa_solar_boost_active", False) and not is_importing
                
                for c in car_ids:
                    if not car_panic[c] and not ev_is_solar:
                        actions[f"{c}_limit_a"] = 0
                    
                # SKÖLD: Stryp spabadet (om den inte drivs av solen just nu).
                # Undantag: manuell tvångsvärme (Prio 11) vinner över peak shaving enligt
                # dokumenterad hierarki – användarens uttryckliga val respekteras.
                spa_force = state.get('spa_force_heat', False)
                if not spa_is_solar and not spa_force:
                    actions["spa_target"] = state.get('spa_low_temp', 15.0)
                    actions["spa_eco"] = True
                
                indoor_temp = state.get('indoor_temp')
                indoor_min = state.get('indoor_min', 19.0)
                
                ev_throttled = not ev_is_solar and not any(car_panic.values())
                ev_str = "EV & " if ev_throttled else ""
                
                panic_msg = ""
                if any(car_panic.values()):
                    panic_msg = " Låter elbil ladda pga Panic/Tvångsladdning!"
                elif ev_is_solar:
                    panic_msg = " Låter elbil ladda på solöverskott!"

                if indoor_temp is not None and indoor_temp < indoor_min:
                    actions["log"].append(f"🚨 Prio 10 (PEAK): Energibudget nådd! ({consumed_kwh:.2f}/{allowed_kwh_now:.2f} kWh). Stryper {ev_str}Spa (VP undantagen pga kyla).{panic_msg}")
                else:
                    if not is_importing:
                        actions["log"].append(f"💡 Prio 10 (PEAK): Energibudget nådd, men huset drivs av solöverskott. Undantar Värmepumpen från strypning.")
                    else:
                        # Tvinga kompressorn att stanna helt omedelbart genom att sätta börvärden långt under verkligheten
                        actions["pump_target_temp"] = min(state.get('indoor_min', 19.0) - 1.0, 15.0)
                        actions["water_target_temp"] = 10.0
                        actions["pump_run_water"] = False
                        actions["pump_mode"] = "EXPENSIVE"
                        actions["log"].append(f"🚨 Prio 10 (PEAK): Energibudget nådd! ({consumed_kwh:.2f}/{allowed_kwh_now:.2f} kWh). STRYPER VÄRMEPUMP, Varmvatten och {ev_str}Spa!{panic_msg}")
        else:
             actions["log"].append("💡 Prio 10 (PEAK): Peak Shaving är inaktiverat av användaren. Skyddar ej effekttak.")

        # --- Prio 12: HÅRDKODAD SÄKERHET ---
        if actions.get("spa_target", 0) > 40.0:
            actions["spa_target"] = 40.0
        if actions.get("water_target_temp", 0) > 65.0:
            actions["water_target_temp"] = 65.0

        # --- EKONOMISKT OPTIMUM: PAID TO IMPORT (djupt minuspris) ------------------------
        # Köp-priset är NEGATIVT → vi FÅR BETALT för varje importerad kWh. Optimalt:
        #  (1) strypa egen solproduktion till 0 (importera allt ger större betalning än egenförbruk),
        #  (2) maxa nätuttaget: ladda anslutna, ej fulla bilar på FUSE-medveten maxström (säkert).
        # Varmvatten/spa maxas redan av minuspris-grenarna ovan (termisk lagring).
        if paid_to_import:
            actions["solar_limit_pct"] = 0
            _house_a = max(0, int(state.get('house_load_a', 0)) - int(state.get('ev_actual_a', 0)))
            _avail   = _ev_fuse_room(state, _house_a)
            _ok = [c for c in car_ids if state.get(f'{c}_connected', False) and not (soc[c] is not None and soc[c] >= 98)]
            if _avail >= EV_MIN_CHARGE_AMPS and _ok:
                if len(_ok) == 1:
                    actions[f"{_ok[0]}_limit_a"] = min(specs[_ok[0]]["max_a"], _avail)
                else:                                   # lika delar, resten till den sista (två bilar: som förut)
                    _each = _avail // len(_ok)
                    for i_, c in enumerate(_ok):
                        _share = _avail - _each * (len(_ok) - 1) if i_ == len(_ok) - 1 else _each
                        actions[f"{c}_limit_a"] = max(EV_MIN_CHARGE_AMPS, min(specs[c]["max_a"], _share))
            actions["log"].append(f"💰 EKONOMISKT OPTIMUM: Betalt för att förbruka (spot {price:+.2f} {symbol}/kWh) → maxar nätuttag (bilar från nätet) + stryper solen till 0%.")

        # --- LUFTFUKTIGHET: fuktig luft känns kallare -> höj pumpens mål lite (upp till +1°C) ----------
        # 55% RH eller lägre: ingen ändring. 75% eller mer: +1.0°C. Linjärt däremellan.
        # Hoppar över bortaläge och när Prio 5 stoppar värmen för att det är för varmt inne.
        indoor_hum = state.get('indoor_humidity')
        if (indoor_hum is not None and not state.get('away_mode_active')
                and not getattr(self, 'prio5_hysteresis_active', False)
                and actions.get("pump_target_temp") is not None):
            hum_boost = round(max(0.0, min(1.0, (indoor_hum - 55.0) / 20.0)), 1)
            if hum_boost > 0:
                _cap = max(actions["pump_target_temp"], state.get('indoor_max', 22.5))
                actions["pump_target_temp"] = min(actions["pump_target_temp"] + hum_boost, _cap)
                actions["log"].append(f"💧 Fukt: Luftfuktigheten är {indoor_hum:.0f}% (fuktig luft känns kallare). Höjer måltemperaturen +{hum_boost}°C.")

        # --- GENERISK SPEGLING (EnergyWizard Open, Fas 2) ---
        # actions['<bil>_limit_a'] (Prio 3/3.5, satta ovan) är fortfarande
        # sanningskällan för SJÄLVA allokeringsmatematiken - den är inte generaliserad till N
        # bilar än (kräver att decisions.py:s <bil>_kw-kolumner också görs generiska,
        # ett eget steg). Det som ÄR generaliserat här är alla delar som redan var oberoende
        # per bil (Prio 3.8, 11.5, 11.6, batteriskyddet ovan) - de loopar nu över car_ids
        # istället för en hårdkodad lista. Detta speglar bara slutresultatet till en generisk
        # form (actions['ev'][car_id]) som Fas 3 kan börja konsumera.
        actions['ev'] = {
            cid: {
                'limit_a': actions.get(f'{cid}_limit_a', 0),
                'set_phases': actions.get(f'{cid}_set_phases'),
                'panic': bool(actions.get(f'{cid}_panic', False)),
            }
            for cid in car_ids
        }

        return actions