"""
battery_plan.py - husbatteriets plan över dygnet (steg 3): när det lönar sig att ladda, spara
och ladda ur, givet elpriset, husets förväntade last, solprognosen och elbilens laddplan.

Dynamisk programmering över batteriets energi, kvart för kvart. För varje kvart prövas de
avsikter batteriet stöder:

  auto       självförbrukning: täcker husets underskott, tar upp solöverskott
  hold       tar upp solöverskott, laddar inte ur
  idle       varken laddar eller laddar ur
  charge     laddar med full effekt (även från nätet)
  discharge  laddar ur med full effekt (överskott säljs)

Kostnaden per kvart är nätköp × fullt köppris - försäljning × säljintäkt (nordpool.full_buy_cost /
full_sell_income, samma som resten av motorn). Verkningsgraden räknas på vägen in och ut.
Energi kvar vid horisontens slut värderas till vad den sparar senare (25:e percentilen av köppriset × urladdnings-
verkningsgrad, försiktigt satt) - annars skulle planen tömma batteriet bara för att horisonten tar slut.

Gränser: aldrig under reservnivån, aldrig över maxnivån, och aldrig urladdning medan elbilen är
planerad att ladda (töm inte batteriet i bilen - samma regel som battery_control.py).

Ren modul utan I/O, testas i tests/test_battery_plan.py. main.py bygger indata och sparar planen.
"""

import math

import battery_learning

DT_H = 0.25                 # kvart

# Planeringsstil (som FTW:s "planning style"): hur mycket planen litar på prognosen.
# Försiktig = räkna med mindre sol och mer förbrukning, och värdera energi kvar vid slutet högre
# (behåller mer i batteriet). Djärv = planera på prognosen som den är (tjänar mest när den stämmer).
# Säkerhetsgränserna (reservnivå, säkringsskydd, effekttak) är desamma i alla stilar.
PLAN_STYLES = {
    #               sol ×  last ×  percentil för slutvärdet
    "very_careful": (0.60, 1.25, 50),
    "careful":      (0.80, 1.10, 35),
    "balanced":     (1.00, 1.00, 25),
    "bold":         (1.00, 1.00, 15),
    "very_bold":    (1.05, 0.95, 5),
}
DEFAULT_STYLE = "balanced"


def style_params(style):
    return PLAN_STYLES.get(style or DEFAULT_STYLE, PLAN_STYLES[DEFAULT_STYLE])
ACTIONS = ("auto", "hold", "idle", "charge", "discharge")

# Pågående laddning som ligger långt under det planen räknar med (#251, punkt 4).
# Schemat för resten av dygnet använder den uppmätta takten. Beställningen till
# batteriet sänks inte: en tillfällig begränsning ska inte bli det vi ber om.
LIVE_CHARGE_RATIO = 0.60
LIVE_CHARGE_MIN_SAMPLES = 3
LIVE_CHARGE_MIN_SPAN_S = 300.0
LIVE_CHARGE_MIN_W = 400.0
LIVE_CHARGE_ON_W = 150.0


def live_charge_kw(planned_kw, samples):
    """kW som dygnets schema ska räkna med när en pågående laddning är långsammare än planen.

    samples = [(ts_sekunder, power_w)] med + som laddning, från ett fönster där planen redan
    laddar. Kräver minst tre prover över 150 W utspridda på fem minuter, och ett medel som
    ligger under 60 % av planned_kw men minst 400 W. Annars planned_kw, oförändrat.
    Höjer aldrig effekten och sparar inget: nästa plan räknar om från nya prover.
    """
    try:
        planned = float(planned_kw)
    except (TypeError, ValueError):
        return planned_kw
    if not math.isfinite(planned) or planned <= 0:
        return planned_kw
    pts = []
    for ts, power in samples or []:
        try:
            ts, power = float(ts), float(power)
        except (TypeError, ValueError):
            continue
        if math.isfinite(ts) and math.isfinite(power) and power > LIVE_CHARGE_ON_W:
            pts.append((ts, power))
    if len(pts) < LIVE_CHARGE_MIN_SAMPLES:
        return planned
    if max(t for t, _ in pts) - min(t for t, _ in pts) < LIVE_CHARGE_MIN_SPAN_S:
        return planned
    mean_w = sum(p for _, p in pts) / len(pts)
    if mean_w < LIVE_CHARGE_MIN_W or mean_w >= LIVE_CHARGE_RATIO * planned * 1000.0:
        return planned
    return round(min(planned, mean_w / 1000.0), 2)


def command_power_w(action, simulated_kw, command_kw, schedule_kw):
    """Watt att beställa nu. Schemat får räkna med en lägre hållen laddeffekt, men
    beställningen stannar på den inlärda eller konfigurerade effekten."""
    try:
        command, schedule = float(command_kw), float(schedule_kw)
    except (TypeError, ValueError):
        command = schedule = None
    if (action == "charge" and command and schedule and math.isfinite(command) and math.isfinite(schedule)
            and schedule + 0.05 < command):
        return command * 1000.0
    if simulated_kw is None:
        return None
    try:
        return abs(float(simulated_kw)) * 1000.0
    except (TypeError, ValueError):
        return None


def _battery_power(action, net_kw, pc, pd):
    """Batteriets AC-effekt (kW, + laddar) för en avsikt, före laddnivågränser."""
    if action == "auto":
        return max(-pd, min(pc, -net_kw))
    if action == "hold":
        return max(0.0, min(pc, -net_kw))
    if action == "idle":
        return 0.0
    if action == "charge":
        return pc
    return -pd


def _step(soc, b_kw, lo, hi, eff_c, eff_d):
    """Ny energi (kWh) och faktisk batterieffekt efter att gränserna klippt den."""
    if b_kw >= 0:
        de = b_kw * DT_H * eff_c
        if soc + de > hi:
            de = max(0.0, hi - soc)
            b_kw = de / (DT_H * eff_c) if eff_c else 0.0
    else:
        de = b_kw * DT_H / eff_d
        if soc + de < lo:
            de = min(0.0, lo - soc)
            b_kw = de * eff_d / DT_H
    return soc + de, b_kw


def _cost(grid_kw, buy, sell):
    e = grid_kw * DT_H
    return e * buy if e > 0 else e * sell


def simulate(slots, soc0, actions, capacity, reserve, max_kwh, pc, pd, eff, cycle_cost=0.0,
             charge_wear_cost_sek_per_kwh=0.0, discharge_wear_cost_sek_per_kwh=0.0):
    """Kör en given avsiktsserie och returnerar (kostnad, rader). Används för baslinjen."""
    eff_c = eff_d = math.sqrt(eff)
    soc, cost, rows = soc0, 0.0, []
    for s, a in zip(slots, actions):
        net = s["load_kw"] + s.get("ev_kw", 0.0) - s.get("solar_kw", 0.0)
        b = _battery_power(a, net, pc, pd)
        if s.get("ev_kw", 0.0) > 0.1 and b < 0:
            b = 0.0
        previous_soc = soc
        soc, b = _step(soc, b, reserve, max_kwh, eff_c, eff_d)
        grid = net + b
        c = _cost(grid, s["buy"], s["sell"]) + cycle_cost * max(0.0, -b) * DT_H
        if charge_wear_cost_sek_per_kwh:
            c += max(0.0, soc - previous_soc) * charge_wear_cost_sek_per_kwh
        if discharge_wear_cost_sek_per_kwh:
            c += max(0.0, previous_soc - soc) * discharge_wear_cost_sek_per_kwh
        cost += c
        rows.append({"t": s["t"], "action": a, "soc_kwh": soc, "battery_kw": b, "grid_kw": grid, "cost": c})
    return cost, rows


def optimize(slots, soc0_kwh, capacity_kwh, reserve_kwh, max_kwh, charge_kw, discharge_kw,
             eff=0.9, allowed=ACTIONS, step_kwh=None, switch_cost=0.10, cycle_cost=0.0,
             terminal_pct=25, allow_export=True, charge_wear_cost_sek_per_kwh=0.0,
             discharge_wear_cost_sek_per_kwh=0.0, reversal_cost_sek=0.0, ev_mode="block",
             balance_target_kwh=0.0, balance_hold_slots=0, balance_deadline_slots=0):
    """ev_mode: vad batteriet får göra medan elbilen laddar - "block" (ladda inte ur alls, som förut),
    "offload" (Martins förslag 2026-11-07: täck bara husets egen förbrukning, aldrig bilen) eller "free" (även bilen).
    slots: [{'t', 'buy', 'sell', 'load_kw', 'solar_kw', 'ev_kw'}] (kvartar, i tidsordning).
    cycle_cost: kr per urladdad kWh - batteriets slitage (cellernas pris / livslängd i kWh). Planen
    laddar då bara ur när prisskillnaden täcker förluster OCH slitage.
    switch_cost: kr per lägesbyte - håller planen sammanhängande (färre skrivningar till
    växelriktarens flashminne) i stället för att jaga varje öre mellan kvartspriserna.
    Wear rates are SEK per stored kWh added/removed; reversal_cost_sek prices physical
    direction changes, including through idle. New wear rates are additive to cycle_cost;
    cost includes wear, as before. cycle_cost remains per discharged AC kWh.
    Returnerar {'rows': [...], 'cost': kr, 'baseline_cost': kr (bara auto), 'saving_kr': kr}."""
    if not slots or not capacity_kwh or capacity_kwh <= 0:
        return {"rows": [], "cost": 0.0, "baseline_cost": 0.0, "saving_kr": 0.0}
    for value in (cycle_cost, charge_wear_cost_sek_per_kwh, discharge_wear_cost_sek_per_kwh, reversal_cost_sek):
        if not math.isfinite(value) or value < 0:
            raise ValueError("Battery wear and reversal costs must be finite and nonnegative")
    acts = [a for a in ACTIONS if a in set(allowed) | {"auto"}]
    A = len(acts)
    # Previous mode and last physical direction (0=none, 1=charge, 2=discharge).
    # Idle/hold must not erase a reversal; auto can reverse without a mode change.
    # Keep the original A-state recurrence when reversal pricing is disabled.
    track_direction = reversal_cost_sek > 0
    direction_states = 3 if track_direction else 1
    P = A * direction_states
    # Optional maintenance automaton: pending, consecutive full quarters, done.
    # It is a requirement, not an arbitrage reward. The ordinary recurrence is
    # unchanged when disabled. A complete quarter must START and END at target.
    balancing = balance_target_kwh > 0
    if balancing and (not math.isfinite(balance_target_kwh) or
                      not reserve_kwh < balance_target_kwh <= capacity_kwh or
                      not isinstance(balance_hold_slots, int) or not 1 <= balance_hold_slots <= 16):
        raise ValueError("Invalid battery balancing target or hold duration")
    Q = balance_hold_slots + 1 if balancing else 1
    done = Q - 1
    deadline = min(len(slots), balance_deadline_slots or len(slots))
    if balancing and (not isinstance(deadline, int) or deadline < 1):
        raise ValueError("Invalid balancing deadline")
    P *= Q
    eff_c = eff_d = math.sqrt(eff)
    step = step_kwh or max(0.05, capacity_kwh / 100.0)
    lo, hi = max(0.0, reserve_kwh), min(capacity_kwh, max_kwh)
    n_states = int(round(capacity_kwh / step)) + 1
    idx = lambda e: max(0, min(n_states - 1, int(round(e / step))))

    # Energi kvar vid slutet värderas FÖRSIKTIGT (25:e percentilen av köppriset): med medianen
    # blev värdet så högt en dag med dyr kväll att planen hellre hamstrade än använde batteriet.
    buys = sorted(s["buy"] for s in slots)
    terminal_value = buys[min(len(buys) - 1, int(len(buys) * terminal_pct / 100))] * eff_d   # kr per kWh kvar vid slutet

    INF = float("inf")
    # State: energy index, previous mode and last nonzero physical direction.
    term = [-(i * step) * terminal_value for i in range(n_states)]
    future = [[term[i] if p % Q == done else INF for p in range(P)] for i in range(n_states)]
    choice = []
    for slot_index in range(len(slots) - 1, -1, -1):
        s = slots[slot_index]
        net = s["load_kw"] + s.get("ev_kw", 0.0) - s.get("solar_kw", 0.0)
        ev_on = s.get("ev_kw", 0.0) > 0.1
        # utfall per (energinivå, avsikt) är oberoende av förra avsikten - räkna en gång
        trans = []
        for i in range(n_states):
            soc = i * step
            row = []
            for a in acts:
                b = _battery_power(a, net, charge_kw, discharge_kw)
                if not allow_export and b < 0:
                    b = max(b, -max(0.0, net))        # bara husets egen förbrukning, ingen försäljning
                if ev_on and b < 0:
                    if ev_mode == "offload":
                        b = max(b, -max(0.0, s["load_kw"] - s.get("solar_kw", 0.0)))   # huset, inte bilen
                    elif ev_mode != "free":
                        if a == "discharge":
                            row.append(None)
                            continue
                        b = 0.0
                upper = max(hi, balance_target_kwh) if balancing else hi
                new, b = _step(soc, b, min(lo, soc), upper if soc <= upper else soc, eff_c, eff_d)
                wear = cycle_cost * max(0.0, -b) * DT_H
                if charge_wear_cost_sek_per_kwh:
                    wear += max(0.0, new - soc) * charge_wear_cost_sek_per_kwh
                if discharge_wear_cost_sek_per_kwh:
                    wear += max(0.0, soc - new) * discharge_wear_cost_sek_per_kwh
                row.append((idx(new), b, net + b, _cost(net + b, s["buy"], s["sell"]) + wear, wear))
            trans.append(row)
        normal_trans = trans
        if balancing:
            # Once finished, use the ordinary clipped transitions, including
            # partial charging up to the daily ceiling (rather than dropping
            # a charge action simply because maintenance allowed a higher SOC).
            normal_trans = []
            for i, row in enumerate(trans):
                soc, normal_row = i * step, []
                for t in row:
                    if t is None:
                        normal_row.append(None)
                        continue
                    new, b = _step(soc, t[1], min(lo, soc), hi if soc <= hi else soc, eff_c, eff_d)
                    wear = (cycle_cost * max(0.0, -b) * DT_H + max(0.0, new - soc) * charge_wear_cost_sek_per_kwh
                            + max(0.0, soc - new) * discharge_wear_cost_sek_per_kwh)
                    normal_row.append((idx(new), b, net + b, _cost(net + b, s["buy"], s["sell"]) + wear, wear))
                normal_trans.append(normal_row)
        cur = [[INF] * P for _ in range(n_states)]
        ch = [[None] * P for _ in range(n_states)]
        for i in range(n_states):
            for prev in range(P):
                mode_prev, phase = divmod(prev, Q)
                if balancing and slot_index >= deadline and phase != done:
                    continue
                best, arg = INF, None
                for k in range(A):
                    t = (normal_trans if phase == done else trans)[i][k]
                    if t is None:
                        continue
                    next_phase = phase
                    if balancing:
                        at_target = i * step >= balance_target_kwh - 1e-9 and t[0] * step >= balance_target_kwh - 1e-9 and t[1] >= -1e-9
                        next_phase = done if phase == done else min(done, phase + 1) if at_target else 0
                    if track_direction:
                        direction = 1 if t[1] > 1e-9 else 2 if t[1] < -1e-9 else 0
                        last_direction = mode_prev % 3
                        reversal = bool(direction and last_direction and direction != last_direction)
                        nxt_prev = k * 3 + (direction or last_direction)
                        c = t[3] + future[t[0]][nxt_prev * Q + next_phase] + (switch_cost if k != mode_prev // 3 else 0.0) + (reversal_cost_sek if reversal else 0.0)
                    else:
                        c = t[3] + future[t[0]][k * Q + next_phase] + (switch_cost if k != mode_prev else 0.0)
                    if c < best - 1e-12:
                        best, arg = c, k
                cur[i][prev], ch[i][prev] = best, arg
        future = cur
        choice.append((ch, trans, normal_trans))
    choice.reverse()

    rows, i, prev = [], idx(soc0_kwh), acts.index("auto") * direction_states * Q
    if balancing and not math.isfinite(future[i][prev]):
        return {"rows": [], "cost": 0.0, "baseline_cost": 0.0, "saving_kr": 0.0, "balance_feasible": False}
    last_direction = 0
    total = wear_total = reversal_total = 0.0
    for s, (ch, trans, normal_trans) in zip(slots, choice):
        k = ch[i][prev]
        phase = prev % Q
        nxt, b, grid, c, wear = (normal_trans if phase == done else trans)[i][k]
        direction = 1 if b > 1e-9 else 2 if b < -1e-9 else 0
        reversal = bool(direction and last_direction and direction != last_direction)
        wear_total += wear
        reversal_total += reversal_cost_sek if reversal else 0.0
        total += c
        a = acts[k]
        maintenance = balancing and phase != done
        next_phase = (min(done, phase + 1) if i * step >= balance_target_kwh - 1e-9 and nxt * step >= balance_target_kwh - 1e-9 and b >= -1e-9 else 0) if maintenance else phase
        # Ladda med fullt batteri / ladda ur vid reservnivån gör i praktiken ingenting - visa och
        # skicka det som "håll", så planen inte ser ut att ladda i timmar.
        if a in ("charge", "discharge") and abs(b) < 0.05 and "hold" in acts:
            a = "hold"
        holding = maintenance and i * step >= balance_target_kwh - 1e-9 and nxt * step >= balance_target_kwh - 1e-9 and b >= -1e-9
        if holding and abs(b) < 0.05 and "hold" in acts:
            a = "hold"  # Do not release to self-consumption during the dwell.
        rows.append({"t": s["t"], "action": a, "soc_kwh": nxt * step, "battery_kw": round(b, 3),
                     "grid_kw": round(grid, 3), "cost": c, "buy": s["buy"],
                     "wear_cost_sek": wear, "direction_reversal": reversal})
        if balancing:
            rows[-1]["balance"] = maintenance and (b > 0 or i * step >= balance_target_kwh - 1e-9)
            rows[-1]["balance_ceiling"] = maintenance
            rows[-1]["balance_hold"] = holding
        last_direction = direction or last_direction
        i, prev = nxt, (k * 3 + last_direction if track_direction else k) * Q + next_phase
    base_cost, base_rows = simulate(slots, soc0_kwh, ["auto"] * len(slots), capacity_kwh, lo, hi, charge_kw, discharge_kw, eff, cycle_cost,
                                    charge_wear_cost_sek_per_kwh, discharge_wear_cost_sek_per_kwh)
    # Rättvis jämförelse: värdera energin kvar vid slutet lika i båda.
    end_plan = rows[-1]["soc_kwh"] if rows else soc0_kwh
    end_base = base_rows[-1]["soc_kwh"] if base_rows else soc0_kwh
    base_reversals, last_direction = 0, 0
    for row in base_rows:
        b = row["battery_kw"]
        direction = 1 if b > 1e-9 else 2 if b < -1e-9 else 0
        base_reversals += int(bool(direction and last_direction and direction != last_direction))
        last_direction = direction or last_direction
    saving = (base_cost + base_reversals * reversal_cost_sek - end_base * terminal_value) - (total + reversal_total - end_plan * terminal_value)
    return {"rows": rows, "cost": total, "baseline_cost": base_cost, "saving_kr": round(saving, 2),
            "wear_cost_sek": wear_total, "reversal_cost_sek": reversal_total}


REASON = {
    "charge": "Planen: laddar nu på billig el inför dyrare timmar",
    "discharge": "Planen: laddar ur nu – dyr timme",
    "hold": "Planen: sparar batteriet till dyrare timmar",
    "idle": "Planen: batteriet vilar",
    "auto": "Planen: självförbrukning",
}


def blocks(rows):
    """Slår ihop kvartar med samma avsikt (utom auto) till sammanhängande pass för planvyn.
    'end' är sista kvartens start; passet slutar 15 min senare."""
    out = []
    for i, r in enumerate(rows):
        if out and out[-1]["action"] == r["action"] and out[-1]["_last"] == i - 1:
            out[-1].update(_last=i, end=r["t"], soc_end=r["soc_kwh"])
        else:
            out.append({"action": r["action"], "start": r["t"], "end": r["t"], "_last": i, "soc_end": r["soc_kwh"]})
    return [{k: v for k, v in b.items() if k != "_last"} for b in out if b["action"] != "auto"]


# ---------------------------------------------------------------- databas (main.py)

def _charge_samples(engine, now):
    """(ts, W) de senaste 20 minuterna, bara när den sparade planen redan laddar. Tomt vid fel."""
    from datetime import timedelta
    from sqlalchemy import text
    start = now - timedelta(minutes=20)
    try:
        with engine.connect() as c:
            try:
                charging = c.execute(text(
                    "SELECT 1 FROM battery_plan_slots WHERE action = 'charge' "
                    "AND t_slot >= :a AND t_slot <= :b LIMIT 1"
                ), {"a": start, "b": now}).scalar()
                if not charging:
                    return []
                rows = c.execute(text(
                    "SELECT EXTRACT(EPOCH FROM timestamp), battery_power_w FROM sensor_log "
                    "WHERE timestamp >= :a AND timestamp <= :b AND battery_power_w IS NOT NULL"
                ), {"a": start, "b": now}).fetchall()
            except Exception:
                c.rollback()
                return []
    except Exception:
        return []
    return [(float(t), float(p)) for t, p in rows if t is not None and p is not None]


def plan_from_db(engine, now, soc_pct, settings, base_profile, supported):
    """Bygger kvartarna från nu till slutet av kända elpriser och kör optimize(). Sparar planen i
    battery_plan_slots. Returnerar resultatet + 'action_now' för pågående kvart."""
    from datetime import timedelta
    from sqlalchemy import text
    import learning
    import nordpool
    import weather

    cap = settings.get("capacity_kwh")
    if not cap or soc_pct is None:
        return None
    try:                                  # valt i webben går före house_config.yaml
        import ew_settings
        _st = ew_settings.load()
    except Exception:
        _st = {}
    style = _st.get("battery_plan_style") or settings.get("plan_style") or DEFAULT_STYLE
    allow_export = _st.get("battery_allow_export", settings.get("allow_export", True)) is not False
    solar_mult, load_mult, terminal_pct = style_params(style)
    q0 = now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0)
    with engine.connect() as c:
        prices = c.execute(text("SELECT time_start, sek_per_kwh FROM elpriser WHERE time_start >= :a AND time_start < :b "
                                "ORDER BY time_start"), {"a": q0, "b": q0 + timedelta(hours=36)}).fetchall()
        try:
            ev = c.execute(text("SELECT t_slot, SUM(kw) FROM ev_plan_slots GROUP BY t_slot")).fetchall()
        except Exception:
            c.rollback()
            ev = []
    ev_kw = {t.replace(tzinfo=now.tzinfo) if t.tzinfo is None else t.astimezone(now.tzinfo): float(kw or 0) for t, kw in ev}
    hourly_price = {}
    for t, p in prices:
        if p is not None:
            hourly_price[t.astimezone(now.tzinfo)] = float(p)
    if not hourly_price:
        return None
    # Kvartspriser; timpriser (äldre dagar) delas upp i fyra kvartar.
    quarters, t = {}, q0
    for ts, p in sorted(hourly_price.items()):
        quarters[ts] = p
    solar_cache = {}

    factor = settings.get("solar_factor") or {}          # inlärd rättning per timme (battery_learning.py)

    src_count = {"solar_ha": 0, "solar_model": 0, "price_filled": 0, "load_profile": 0, "load_model": 0}   # #389

    def solar_at(ts):
        import ha_solar_forecast
        external = ha_solar_forecast.power_at(ts)
        if external is not None:
            src_count["solar_ha"] += 1
            return external / 1000.0 * factor.get(ts.hour, 1.0)
        src_count["solar_model"] += 1
        # Keep the existing hourly internal model for uncovered periods.
        h = ts.replace(minute=0)
        if h not in solar_cache:
            try:
                cloud, _, _, _ = weather.get_weather_at(h)
                solar_cache[h] = (weather.get_smart_solar_w(cloud, h, use_external=False) or 0.0) / 1000.0 * factor.get(h.hour, 1.0)
            except Exception:
                solar_cache[h] = 0.0
        return solar_cache[h]

    slots, last_p, forecast = [], None, []
    load_bias = float(settings.get("load_bias") or 1.0)        # plan mot utfall (battery_learning.outcome_bias)
    solar_bias = float(settings.get("solar_bias") or 1.0)
    end = max(quarters) + timedelta(minutes=15)
    balance_requested = bool((settings.get("balance_request") or {}).get("request"))
    quarter_prices = any(ts.minute != 0 for ts in quarters)
    while t < end:
        p = quarters.get(t, quarters.get(t.replace(minute=0), last_p))
        if balance_requested:
            # Maintenance may not cross unknown prices using the ordinary
            # plan's historical forward-fill fallback.
            p = quarters.get(t if quarter_prices else t.replace(minute=0))
        if p is None:
            break
        if quarters.get(t) is None and quarters.get(t.replace(minute=0)) is None:
            src_count["price_filled"] += 1              # framfyllt från förra kvarten
        last_p = p
        _prof = (settings.get("load_profile") or {}).get((t.weekday(), t.hour))
        src_count["load_profile" if _prof else "load_model"] += 1
        raw_load = _prof or learning.predict_base_load(t, base_profile)
        raw_solar = solar_at(t)
        forecast.append((t, raw_load, raw_solar))          # prognosen som den är, före stil och utfallsrättning
        slots.append({"t": t, "buy": nordpool.full_buy_cost(p, t), "sell": nordpool.full_sell_income(p), "spot": p,
                      "load_kw": raw_load * load_bias * load_mult, "solar_kw": raw_solar * solar_bias * solar_mult,
                      "ev_kw": ev_kw.get(t, 0.0)})
        t += timedelta(minutes=15)
    if not slots:
        return None
    command_kw = battery_learning.planning_kw(settings, "charge")
    schedule_kw = live_charge_kw(command_kw, _charge_samples(engine, now))
    params = dict(soc0_kwh=soc_pct / 100.0 * cap, capacity_kwh=cap,
                  reserve_kwh=settings["reserve_soc"] / 100.0 * cap,
                  max_kwh=settings["max_soc"] / 100.0 * cap,
                  charge_kw=schedule_kw,
                  discharge_kw=battery_learning.planning_kw(settings, "discharge"),
                  eff=settings.get("efficiency", 0.9), allowed=tuple(supported),
                  cycle_cost=settings.get("cycle_cost", 0.30), terminal_pct=terminal_pct,
                  allow_export=allow_export,
                  charge_wear_cost_sek_per_kwh=settings.get("charge_wear_cost_sek_per_kwh", 0.0),
                  discharge_wear_cost_sek_per_kwh=settings.get("discharge_wear_cost_sek_per_kwh", 0.0),
                  reversal_cost_sek=settings.get("reversal_cost_sek", 0.0))
    balance = settings.get("balance_request") or {}
    if balance.get("request"):
        params.update(balance_target_kwh=balance["target_soc"] / 100.0 * cap,
                      balance_hold_slots=balance["hold_slots"],
                      balance_deadline_slots=balance["deadline_slots"])
    r = optimize(slots, **params)
    deferred = r.get("balance_feasible") is False
    if deferred:
        # Insufficient horizon/power: keep the ordinary safe plan, never force
        # an immediate charge or pretend maintenance has completed.
        for key in ("balance_target_kwh", "balance_hold_slots", "balance_deadline_slots"):
            params.pop(key, None)
        r = optimize(slots, **params)
    r["balance_deferred"] = deferred
    import plan_snapshot
    n = len(slots)
    try:
        _psrc = nordpool.price_source()
    except Exception:
        _psrc = None
    quality = {   # #389: hur färska och kompletta indata var - rapporteras bara, styr ingenting
        "prices": {"source": _psrc, "coverage": round((n - src_count["price_filled"]) / n, 3), "missing": src_count["price_filled"],
                   "horizon_h": round(n / 4.0, 2)},
        "solar": {"source": "ha_forecast" if src_count["solar_ha"] and not src_count["solar_model"] else
                  "weather_model" if not src_count["solar_ha"] else "mixed",
                  "coverage": round(src_count["solar_ha"] / n, 3)},
        "load": {"source": "profile" if src_count["load_profile"] == n else "model" if not src_count["load_profile"] else "mixed",
                 "coverage": round(src_count["load_profile"] / n, 3)},
        "soc": {"source": "battery", "known": soc_pct is not None, "age_s": settings.get("soc_age_s")},
    }
    r["input_quality"] = quality
    r["plan_id"] = plan_snapshot.capture(slots, params, r, now, quality=quality)
    r["style"], r["allow_export"] = style, allow_export
    try:
        with engine.begin() as c:
            c.execute(text("CREATE TABLE IF NOT EXISTS battery_plan_slots (t_slot TIMESTAMPTZ PRIMARY KEY, action TEXT, "
                           "soc_pct NUMERIC, battery_kw NUMERIC, spot NUMERIC, saving_kr NUMERIC, updated_at TIMESTAMPTZ DEFAULT now())"))
            c.execute(text("ALTER TABLE battery_plan_slots ADD COLUMN IF NOT EXISTS grid_kw NUMERIC"))   # - = säljer (exportfärg)
            c.execute(text("ALTER TABLE battery_plan_slots ADD COLUMN IF NOT EXISTS balance BOOLEAN NOT NULL DEFAULT false"))
            c.execute(text("DELETE FROM battery_plan_slots"))
            # Plan mot utfall: den FÖRSTA prognosen per kvart sparas (ungefär ett dygn i förväg) och jämförs sedan
            # med det uppmätta i battery_learning.learn_from_db.
            c.execute(text("CREATE TABLE IF NOT EXISTS battery_plan_forecast (t_slot TIMESTAMPTZ PRIMARY KEY, "
                           "load_kw NUMERIC, solar_kw NUMERIC, made_at TIMESTAMPTZ DEFAULT now())"))
            c.execute(text("INSERT INTO battery_plan_forecast (t_slot, load_kw, solar_kw) VALUES (:t, :l, :s) "
                           "ON CONFLICT (t_slot) DO NOTHING"),
                      [{"t": t_, "l": round(l_, 4), "s": round(s_, 4)} for t_, l_, s_ in forecast])
            c.execute(text("DELETE FROM battery_plan_forecast WHERE t_slot < now() - interval '30 days'"))
            c.execute(text("INSERT INTO battery_plan_slots (t_slot, action, soc_pct, battery_kw, spot, saving_kr, grid_kw, balance) "
                           "VALUES (:t, :a, :s, :b, :p, :sv, :g, :balance)"),
                      [{"t": row["t"], "a": row["action"], "s": round(100.0 * row["soc_kwh"] / cap, 1), "b": row["battery_kw"],
                        "g": row.get("grid_kw"),
                        "balance": row.get("balance", False),
                        "p": sl["spot"], "sv": r["saving_kr"]} for row, sl in zip(r["rows"], slots)])
    except Exception as e:
        print(f"⚠️ Batteriplanen kunde inte sparas: {e}")
    r["action_now"] = r["rows"][0]["action"] if r["rows"] else None
    r["balance_now"] = bool(r["rows"] and r["rows"][0].get("balance"))
    r["balance_target_soc"] = balance.get("target_soc") if r["balance_now"] else None
    r["balance_hold_now"] = bool(r["rows"] and r["rows"][0].get("balance_hold"))
    sim_kw = r["rows"][0]["battery_kw"] if r["rows"] else None
    r["power_now_w"] = command_power_w(r["action_now"], sim_kw, command_kw, schedule_kw)
    if schedule_kw + 0.05 < command_kw:
        r["live_charge_note"] = (
            f"Pågående laddning håller {schedule_kw:.1f} kW, så resten av dygnet planeras i den takten. "
            f"Beställningen är fortfarande upp till {command_kw:.1f} kW."
        )
        print(f"🔋 {r['live_charge_note']}")
    if not allow_export and r["action_now"] == "discharge":
        r["action_now"] = "auto"        # självförbrukning täcker huset exakt och säljer aldrig från batteriet
    r["spot_now"] = slots[0]["spot"]
    return r
