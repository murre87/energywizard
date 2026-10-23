"""
mpc.py – Prediktiv förvärmnings-planerare (MPC-lite) för husvärmen.

Använder de REDAN tränade termiska ML-modellerna (learning.get_house_cooling_rate_model +
predict_house_heating_rate) tillsammans med dygnets elpriser för att hitta ett kostnads-
optimalt värmeschema som håller innetempen inom [comfort_min, comfort_max] och FÖRVÄRMER
på billiga timmar inför dyra block (husets värmetröghet = termiskt batteri).

Just nu körs den i SKUGGLÄGE: run_backtest() replayar planeraren mot din historiska data
och uppskattar besparingen — den styr INGET live förrän den validerats.
"""

from datetime import datetime, timedelta
import learning
import logger as sm_logger

# Hur många timmar husets värmetröghet realistiskt kan "coasta" på förvärmd värme.
MAX_COAST_HOURS = 6
# Default komfort-band (kan skickas in). Golv = du fryser aldrig under detta; tak = hur högt
# vi tillåter förvärmning (banka värme).
DEFAULT_COMFORT_MIN = 20.0
DEFAULT_COMFORT_MAX = 22.5
# Representativ värmepumps-effekt (kW el) för att omvandla "på-timmar" → kr. Påverkar bara
# ABSOLUTA kronor, inte besparings-PROCENTEN (pump_kw är en gemensam faktor).
DEFAULT_PUMP_KW = 2.2
# Prismodell (samma som dashboardens full_buy_cost) för kr/kWh inkl moms/nät/skatt.
def _full_buy_cost(spot):
    return (spot * 1.25) + 0.62675


def _hourly_day(day_start):
    """Hämtar timvis (outdoor, solar_w, indoor, spot_pris) för ett dygn. Returnerar dict hour->rad."""
    day_end = day_start + timedelta(days=1)
    rows = {}
    try:
        with sm_logger.get_db() as conn, conn.cursor() as cur:
            cur.execute("""
                SELECT EXTRACT(HOUR FROM timestamp AT TIME ZONE 'Europe/Stockholm')::int AS h,
                       AVG(outdoor_temp), AVG(pv_power_w), AVG(indoor_temp)
                FROM sensor_log
                WHERE timestamp >= %s AND timestamp < %s
                  AND outdoor_temp IS NOT NULL AND indoor_temp IS NOT NULL
                GROUP BY 1
            """, (day_start, day_end))
            for h, out, pv, ind in cur.fetchall():
                rows[int(h)] = {'outdoor': float(out) if out is not None else None,
                                'solar': float(pv) if pv is not None else 0.0,
                                'indoor': float(ind) if ind is not None else None,
                                'price': None}
            cur.execute("""
                SELECT EXTRACT(HOUR FROM time_start AT TIME ZONE 'Europe/Stockholm')::int AS h,
                       AVG(sek_per_kwh)
                FROM elpriser WHERE time_start >= %s AND time_start < %s GROUP BY 1
            """, (day_start, day_end))
            for h, p in cur.fetchall():
                if int(h) in rows:
                    rows[int(h)]['price'] = float(p) if p is not None else None
    except Exception as e:
        print(f"❌ MPC._hourly_day: {e}")
        return {}
    return rows


def _simulate(hours, prices, heat_rates, cool_rates, cmin, cmax, indoor0, mode):
    """Simulerar innetempen timme för timme och returnerar (på-lista, summa_pris_för_på-timmar).
    mode='reactive' värmer i själva bristtimmen; mode='mpc' förvärmer i billigaste timmen i fönstret."""
    H = len(hours)
    on = [False] * H
    for _ in range(H * 3):  # iterera tills inga komfortbrott kvar
        temp = indoor0
        violation = None
        for i in range(H):
            temp += heat_rates[i] if on[i] else -cool_rates[i]
            if temp > cmax:      # termostaten tillåter inte överhettning bortom taket
                temp = cmax
            if temp < cmin - 1e-6 and violation is None:
                violation = i
        if violation is None:
            break
        if mode == 'reactive':
            cand = [violation]
        else:  # mpc: förvärm i billigaste lediga timmen i fönstret före bristen
            ws = max(0, violation - MAX_COAST_HOURS)
            free = [i for i in range(ws, violation + 1) if not on[i]]
            cand = [min(free, key=lambda i: prices[i])] if free else [violation]
        added = False
        for i in cand:
            if not on[i]:
                on[i] = True
                added = True
                break
        if not added:
            break
    unit_cost = sum(prices[i] for i in range(H) if on[i])  # per pump-kWh; ×pump_kw senare
    return on, unit_cost


def run_backtest(days=14, comfort_min=None, comfort_max=None, pump_kw=DEFAULT_PUMP_KW, end_date=None):
    """Replayar planeraren mot `days` dygn som slutar `end_date` (default: idag).
    Vid None-modeller (t.ex. sommar utan värmedata) används default-rater → ger ändå en
    ballpark av pris-arbitrage-möjligheten. Returnerar en dict med uppskattad besparing."""
    cmin = DEFAULT_COMFORT_MIN if comfort_min is None else float(comfort_min)
    cmax = DEFAULT_COMFORT_MAX if comfort_max is None else float(comfort_max)
    if cmax <= cmin:
        cmax = cmin + 2.0

    cool_model = learning.get_house_cooling_rate_model()
    heat_model = learning.get_house_heating_model()

    today = (end_date or datetime.now()).replace(hour=0, minute=0, second=0, microsecond=0)
    tot_react = tot_mpc = 0.0
    used_days = 0
    per_day = []

    for d in range(1, days + 1):
        day = today - timedelta(days=d)
        rows = _hourly_day(day)
        hours = [h for h in range(24) if h in rows and rows[h]['price'] is not None
                 and rows[h]['outdoor'] is not None]
        if len(hours) < 20:   # kräver ett nästan komplett dygn
            continue
        prices = [rows[h]['price'] for h in hours]
        indoor0 = next((rows[h]['indoor'] for h in hours if rows[h]['indoor'] is not None), cmin)
        # Om huset redan var varmare än taket denna dag (t.ex. sommar) → ingen värme behövs, hoppa.
        if indoor0 > cmax:
            continue

        heat_rates, cool_rates = [], []
        prev_solar = [rows[h]['solar'] for h in hours]
        for idx, h in enumerate(hours):
            out = rows[h]['outdoor']
            solar = rows[h]['solar']
            roll3 = sum(prev_solar[max(0, idx-2):idx+1]) / max(1, len(prev_solar[max(0, idx-2):idx+1]))
            hr = learning.predict_house_heating_rate(out, 2.0, indoor0, heat_model) if heat_model else 0.3
            cr = learning.predict_house_cooling_rate(out, 2.0, solar, roll3, h, cool_model)
            heat_rates.append(max(0.05, hr))
            cool_rates.append(max(0.0, cr))   # negativ = huset värms av solen → 0 avsvalning

        # Reaktiv baslinje vs MPC-plan. kr = på-timmar × pump_kW × full köp-kostnad(spot).
        react_on, _ = _simulate(hours, prices, heat_rates, cool_rates, cmin, cmax, indoor0, 'reactive')
        mpc_on, _   = _simulate(hours, prices, heat_rates, cool_rates, cmin, cmax, indoor0, 'mpc')
        react_kr = sum(_full_buy_cost(prices[i]) for i in range(len(hours)) if react_on[i]) * pump_kw
        mpc_kr   = sum(_full_buy_cost(prices[i]) for i in range(len(hours)) if mpc_on[i]) * pump_kw

        tot_react += react_kr
        tot_mpc += mpc_kr
        used_days += 1
        per_day.append({'day': day.strftime('%m-%d'), 'react_kr': round(react_kr, 2),
                        'mpc_kr': round(mpc_kr, 2), 'react_h': sum(react_on), 'mpc_h': sum(mpc_on)})

    if used_days == 0:
        return {'ok': False, 'reason': 'För få kompletta dygn med värmebehov i historiken.'}

    saving = tot_react - tot_mpc
    pct = (saving / tot_react * 100.0) if tot_react > 0 else 0.0
    return {
        'ok': True, 'days': used_days,
        'comfort_min': cmin, 'comfort_max': cmax, 'pump_kw': pump_kw,
        'baseline_kr': round(tot_react, 1), 'mpc_kr': round(tot_mpc, 1),
        'saving_kr': round(saving, 1), 'saving_pct': round(pct, 1),
        'saving_kr_per_year_est': round(saving / used_days * 365, 0),
        'models': {'cooling': cool_model is not None, 'heating': heat_model is not None},
        'per_day': per_day[:10],
    }


def run_and_store_backtest(days=30):
    """Kör backtesten på de senaste `days` dygnen och LAGRAR resultatet i tabellen mpc_backtest.
    I sommar (ingen husvärme) blir det ~0 → status 'vilar'; på vintern ger den riktiga siffror.
    Detta är systemets SJÄLV-signal: 'nu är jag redo, så här mycket är jag värd'."""
    r = run_backtest(days=days)
    ok = bool(r.get('ok'))
    baseline = float(r.get('baseline_kr', 0.0) or 0.0)
    heating_active = ok and baseline > 0.5           # fanns det värmekostnad att optimera?
    models = r.get('models', {}) if ok else {}
    models_trained = bool(models.get('cooling') and models.get('heating'))
    try:
        with sm_logger.get_db() as conn, conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS mpc_backtest (
                    id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    days_used INT, baseline_kr REAL, mpc_kr REAL, saving_kr REAL, saving_pct REAL,
                    saving_kr_year REAL, models_trained BOOLEAN, heating_active BOOLEAN, detail TEXT
                )
            """)
            cur.execute("""
                INSERT INTO mpc_backtest
                    (days_used, baseline_kr, mpc_kr, saving_kr, saving_pct, saving_kr_year,
                     models_trained, heating_active, detail)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (r.get('days', 0), baseline, r.get('mpc_kr', 0.0), r.get('saving_kr', 0.0),
                  r.get('saving_pct', 0.0), r.get('saving_kr_per_year_est', 0.0),
                  models_trained, heating_active, r.get('reason', '')))
            conn.commit()
        print(f"🔮 MPC-backtest lagrad: {r.get('saving_pct', 0)}% ({r.get('days',0)} dygn, "
              f"värme_aktiv={heating_active}, modeller_tränade={models_trained}).")
    except Exception as e:
        print(f"❌ mpc.run_and_store_backtest: {e}")
    return r


def last_backtest_age_days():
    """Ålder (dygn) på senaste lagrade backtest, eller None om ingen finns/tabell saknas."""
    try:
        with sm_logger.get_db() as conn, conn.cursor() as cur:
            cur.execute("SELECT EXTRACT(EPOCH FROM (NOW() - MAX(timestamp)))/86400.0 FROM mpc_backtest")
            row = cur.fetchone()
            return float(row[0]) if row and row[0] is not None else None
    except Exception:
        return None
