"""
battery_learning.py - batteriplanen lär sig av hur DETTA batteri och DETTA hus faktiskt beter sig.

Planen (battery_plan.py) börjar med värdena i house_config.yaml. Ur historiken i sensor_log
lär sig EnergyWizard sedan, och skärper planen dag för dag:

  verkningsgrad + kapacitet  Hur många kWh som går IN per procent laddning (k_in) och kommer UT
                             per procent urladdning (k_out). Tur-och-retur-verkningsgraden är
                             k_out / k_in och den användbara kapaciteten 100 x sqrt(k_in x k_out).
  maxeffekt                  Den effekt batteriet håller över en kvart (75:e percentilen av
                             kvartsmedel), inte enstaka toppar och inte databladets.
  solprognosens fel per timme  Faktisk solproduktion / prognos per timme på dygnet - rättar nästa
                             plans solprognos (molnig morgon pga. dalgång, skugga på eftermiddagen...).
  uppmätt besparing          Vad elen hade kostat UTAN batteriet minus vad den kostade, minut för minut
                             (nätet utan batteri = uppmätt nät - batteriets effekt).

Inlärt används bara när det finns tillräckligt med data och värdena är fysiskt rimliga
(FTW:s princip: inlärda modeller är råd, inte sanning - en ung eller drivande modell får aldrig
köra över mätning eller konfigurerade gränser). Annars används configens värden.

Rena funktioner testas i tests/test_battery_learning.py; learn_from_db() läser databasen.
"""

import math

MIN_SEGMENTS = 3            # minst så många laddnings- resp. urladdningspass innan verkningsgrad/kapacitet används
MIN_SEGMENT_SOC = 5.0       # ett pass räknas om laddnivån ändrats minst så här många procent
MIN_SOLAR_HOURS = 5         # minst så många mätta timmar per timme-på-dygnet för solrättningen
EFF_BOUNDS = (0.70, 0.98)
CAP_BOUNDS = (0.5, 1.3)     # inlärd kapacitet får vara 50-130 % av den konfigurerade
POWER_BOUNDS = (0.3, 1.5)   # kort historik: hållen effekt får vara 30-150 % av databladet
POWER_FLOOR_SOLID = 0.15    # med minst SOLID_POWER_QUARTERS kvartar får en verkligt lägre effekt igenom (#251)
QUARTER_S = 900.0
MIN_QUARTER_SAMPLES = 3     # en enstaka topp bildar ingen kvart
MIN_POWER_QUARTERS = 4      # minst en timmes laddkvartar innan effekten ens räknas
SOLID_POWER_QUARTERS = 8    # två timmar: då är 15 %-golvet tillåtet (Solis som håller 2,5 kW mot 11 kW i databladet)
POWER_PCTL = 75             # kvartar under den här percentilen får inte styra; toppar över den heller inte
SOLAR_BOUNDS = (0.3, 2.0)


def _median(v):
    s = sorted(v)
    if not s:
        return None
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def _pct(v, p):
    s = sorted(v)
    return s[max(0, min(len(s) - 1, int(round(p / 100.0 * (len(s) - 1)))))] if s else None


def _positive_kw(configured, key):
    """W i config -> kW, eller None om nyckeln saknas, är 0 eller inte är ett tal."""
    try:
        v = float(configured.get(key))
    except (TypeError, ValueError):
        return None
    if v != v or v <= 0:
        return None
    return v / 1000.0


def sustained_quarter_kw(samples, sign):
    """Medeleffekt per kvart där batteriet faktiskt laddar (sign > 0) eller laddar ur (sign < 0).

    En kvart räknas bara om minst MIN_QUARTER_SAMPLES prover ligger i den och medelvärdet
    är över 150 W. Enstaka toppar inuti kvarten drar upp medelvärdet lite, inte till toppen.
    Returnerar positiva kW. Historiken är rullande (learn_from_db, 21 dygn): några långsamma
    kvartar, till exempel tappade skrivningar, sänker inte percentilen så länge de flesta
    laddkvartarna var snabbare. Värdet räknas om, det sparas inte som en permanent sänkning.
    """
    buckets = {}
    for ts, _soc, p in samples or []:
        if ts is None or p is None:
            continue
        try:
            ts, p = float(ts), float(p)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(ts) or not math.isfinite(p):
            continue
        buckets.setdefault(int(ts // QUARTER_S), []).append(p)
    out = []
    for powers in buckets.values():
        if len(powers) < MIN_QUARTER_SAMPLES:
            continue
        mean = sum(powers) / len(powers)
        if sign > 0 and mean > 150:
            out.append(mean / 1000.0)
        elif sign < 0 and mean < -150:
            out.append(-mean / 1000.0)
    return out


def segments(samples, min_w=150.0, max_gap_s=300.0):
    """samples = [(ts_sekunder, soc_pct, power_w)] i tidsordning (+ = laddar). Delar upp i sammanhängande
    laddnings- och urladdningspass och returnerar [(riktning, kWh_AC, delta_soc)]."""
    out, cur = [], None
    prev = None
    for ts, soc, p in samples:
        if soc is None or p is None:
            prev = None
            continue
        direction = "in" if p > min_w else "out" if p < -min_w else None
        if prev is not None:
            dt = ts - prev[0]
            if dt > max_gap_s or direction is None or (cur and cur["dir"] != direction):
                if cur:
                    out.append(cur)
                cur = None
            if direction and dt <= max_gap_s:
                if cur is None:
                    cur = {"dir": direction, "kwh": 0.0, "soc0": prev[1], "soc1": soc}
                cur["kwh"] += abs(p) * dt / 3.6e6
                cur["soc1"] = soc
        prev = (ts, soc, p)
    if cur:
        out.append(cur)
    return [(c["dir"], c["kwh"], abs(c["soc1"] - c["soc0"])) for c in out
            if abs(c["soc1"] - c["soc0"]) >= MIN_SEGMENT_SOC and c["kwh"] > 0.05]


def learn(samples, solar_pairs, configured):
    """samples: se segments(). solar_pairs: [(timme_på_dygnet, prognos_W, faktisk_W)] per timme.
    configured: house_config.battery_settings(). Returnerar inlärt + vad som faktiskt får användas."""
    segs = segments(samples)
    k_in = _median([kwh / dsoc for d, kwh, dsoc in segs if d == "in"])
    k_out = _median([kwh / dsoc for d, kwh, dsoc in segs if d == "out"])
    n_in = sum(1 for s in segs if s[0] == "in")
    n_out = sum(1 for s in segs if s[0] == "out")
    learned = {"segments_in": n_in, "segments_out": n_out}
    use = {}
    if k_in and k_out and n_in >= MIN_SEGMENTS and n_out >= MIN_SEGMENTS:
        eff = k_out / k_in
        cap = 100.0 * math.sqrt(k_in * k_out)
        learned.update(efficiency=round(eff, 3), capacity_kwh=round(cap, 2))
        if EFF_BOUNDS[0] <= eff <= EFF_BOUNDS[1]:
            use["efficiency"] = round(eff, 3)
        cfg_cap = configured.get("capacity_kwh")
        if cfg_cap and CAP_BOUNDS[0] * cfg_cap <= cap <= CAP_BOUNDS[1] * cfg_cap:
            use["capacity_kwh"] = round(cap, 2)

    nameplate = _positive_kw(configured, "max_power_w") or 5.0
    for key, sign, cap_key in (("charge_kw", 1, "max_charge_w"), ("discharge_kw", -1, "max_discharge_w")):
        vals = sustained_quarter_kw(samples, sign)
        learned[f"{key}_quarters"] = len(vals)
        cap = _positive_kw(configured, cap_key)
        if len(vals) < MIN_POWER_QUARTERS:
            continue
        v = _pct(vals, POWER_PCTL)
        learned[key] = round(v, 2)
        floor = POWER_FLOOR_SOLID if len(vals) >= SOLID_POWER_QUARTERS else POWER_BOUNDS[0]
        if floor * nameplate <= v <= POWER_BOUNDS[1] * nameplate:
            use[key] = round(min(v, cap) if cap else v, 2)

    by_hour = {}
    for h, fc, act in solar_pairs or []:
        if fc is not None and act is not None and fc > 200:
            by_hour.setdefault(int(h), []).append((float(fc), float(act)))
    factors = {}
    for h, pairs in by_hour.items():
        if len(pairs) >= MIN_SOLAR_HOURS:
            f = sum(a for _, a in pairs) / sum(fc for fc, _ in pairs)
            factors[h] = round(max(SOLAR_BOUNDS[0], min(SOLAR_BOUNDS[1], f)), 2)
    learned["solar_factor"] = factors
    if factors:
        use["solar_factor"] = factors
    return {"learned": learned, "use": use}


def median_load_profile(rows, min_days=3):
    """rows = [(veckodag, timme, kW)] - en rad per timme och dag. Median per (veckodag, timme).
    Effektvaktens profil (learning.get_base_load_profile) är 85:e percentilen - medvetet försiktig för
    att inte slå i effekttaket. För batteriplanen överskattar den lasten; medianen ger en ärligare
    förväntan (samma erfarenhet som flera andra hemmabyggen rapporterat)."""
    by = {}
    for dow, hour, kw in rows or []:
        if kw is not None:
            by.setdefault((int(dow), int(hour)), []).append(float(kw))
    return {k: round(_median(v), 3) for k, v in by.items() if len(v) >= min_days}


# Plan mot utfall: planens dygnsprognos för förbrukning och sol jämförs med det som sedan mättes.
# Ett systematiskt fel blir en rättningsfaktor - bara när det finns underlag nog, och inom gränser,
# så att en enstaka konstig vecka (semester, snö på panelerna) aldrig vänder planen helt.
OUTCOME_MIN_LOAD = 3 * 96          # minst tre dygns kvartar
OUTCOME_MIN_SOLAR = 40             # minst 40 soliga kvartar (prognos över 0,1 kW)
OUTCOME_BOUNDS = {"load": (0.8, 1.25), "solar": (0.7, 1.2)}


def outcome_bias(pairs, kind):
    """pairs = [(prognos_kW, uppmätt_kW)] per kvart. Kvot uppmätt/prognos (summor, inte snitt av kvoter -
    tål kvartar nära noll). None om underlaget är för litet. Returnerar (kvot, använd_kvot_eller_None, n)."""
    lo, hi = OUTCOME_BOUNDS[kind]
    floor = 0.1 if kind == "solar" else 0.0
    ok = [(float(p), float(a)) for p, a in pairs or [] if p is not None and a is not None and p > floor and a >= 0]
    need = OUTCOME_MIN_SOLAR if kind == "solar" else OUTCOME_MIN_LOAD
    if len(ok) < need or sum(p for p, _ in ok) <= 0:
        return None, None, len(ok)
    ratio = sum(a for _, a in ok) / sum(p for p, _ in ok)
    use = round(max(lo, min(hi, ratio)), 3)
    return round(ratio, 3), (use if abs(use - 1.0) >= 0.03 else None), len(ok)     # under 3 % fel: rör inget


def planning_kw(settings, direction):
    """Effekten dygnsplanen får räkna med. Inlärd hållen effekt, aldrig över ett explicit
    max_charge_w / max_discharge_w. Utan inlärt värde: det taket, annars max_power_w."""
    key = "charge_kw" if direction == "charge" else "discharge_kw"
    cap_key = "max_charge_w" if direction == "charge" else "max_discharge_w"
    learned = settings.get(key)
    nameplate = _positive_kw(settings, "max_power_w") or 5.0
    cap = _positive_kw(settings, cap_key)
    kw = float(learned) if learned else nameplate
    return min(kw, cap) if cap else kw


def apply(settings, model):
    """Configens batteriinställningar + det inlärda som klarat kontrollerna."""
    out = dict(settings)
    use = (model or {}).get("use") or {}
    for k in ("efficiency", "capacity_kwh"):
        if k in use:
            out[k] = use[k]
    if "charge_kw" in use or "discharge_kw" in use:
        out["charge_kw"] = use.get("charge_kw")
        out["discharge_kw"] = use.get("discharge_kw")
    out["solar_factor"] = use.get("solar_factor") or {}
    out["load_profile"] = use.get("load_profile") or {}
    out["load_bias"] = use.get("load_bias") or 1.0
    out["solar_bias"] = use.get("solar_bias") or 1.0
    return out


def realized_saving(rows, buy_fn, sell_fn):
    """rows = [(dt_sekunder, net_power_w, battery_power_w, spot)] (+ net = köper, + batteri = laddar).
    Kostnad utan batteri minus kostnad med - uppmätt, inte planerat."""
    def cost(kw, h, spot):
        e = kw * h
        return e * buy_fn(spot) if e > 0 else e * sell_fn(spot)
    total = 0.0
    for dt, net, bat, spot in rows:
        if None in (net, bat, spot):
            continue
        h = min(dt, 300.0) / 3600.0
        total += cost((net - bat) / 1000.0, h, spot) - cost(net / 1000.0, h, spot)
    return round(total, 2)


def _power_phrase(use, learned, key, verb, unused):
    """'laddar med 2.5 kW', och både det använda och det inlärda när de skiljer sig (#251)."""
    used, got = use.get(key), learned.get(key)
    if used is None and got is None:
        return None
    if used is None:
        return f"{unused} {got:.1f} kW används inte"
    if got is not None and abs(float(used) - float(got)) >= 0.05:
        return f"{verb} {float(used):.1f} kW (inlärt {float(got):.1f})"
    return f"{verb} {float(used):.1f} kW"


def describe(model):
    """Kort mening om vad som lärts, för gränssnittet."""
    use = (model or {}).get("use") or {}
    lr = (model or {}).get("learned") or {}
    parts = []
    if "efficiency" in use:
        parts.append(f"verkningsgrad {use['efficiency'] * 100:.0f} %")
    if "capacity_kwh" in use:
        parts.append(f"användbar kapacitet {use['capacity_kwh']:.1f} kWh")
    charge = _power_phrase(use, lr, "charge_kw", "laddar med", "inlärt laddning")
    if charge:
        parts.append(charge)
    discharge = _power_phrase(use, lr, "discharge_kw", "laddar ur med", "inlärt urladdning")
    if discharge and ("(" in discharge or "används inte" in discharge):
        parts.append(discharge)
    if use.get("solar_factor"):
        parts.append(f"solprognosen rättad för {len(use['solar_factor'])} timmar")
    if use.get("load_profile"):
        parts.append("husets förbrukning per timme (median)")
    for key, what in (("load_bias", "förbrukningen"), ("solar_bias", "solen")):
        if use.get(key):
            d = (use[key] - 1.0) * 100
            parts.append(f"planen mot utfallet: {what} blev {abs(d):.0f} % {'högre' if d > 0 else 'lägre'} än prognosen, "
                         f"planen räknar nu med det")
    need = max(0, MIN_SEGMENTS - min(lr.get("segments_in", 0), lr.get("segments_out", 0)))
    pending = f"Verkningsgraden lärs fortfarande - behöver {need} laddnings- och urladdningspass till." \
        if "efficiency" not in use and need else ""
    if not parts:
        return pending or "Lär sig fortfarande."
    return ("Inlärt: " + ", ".join(parts) + "." + (" " + pending if pending else "")).strip()


# ---------------------------------------------------------------- databas (main.py)

def learn_from_db(engine, configured, days=21):
    """Läser historiken och lär. Returnerar {'learned', 'use', 'saving_yesterday_kr'}."""
    from sqlalchemy import text
    import nordpool
    with engine.connect() as c:
        rows = c.execute(text("""SELECT extract(epoch FROM timestamp), battery_soc, battery_power_w, net_power, price
                                 FROM sensor_log WHERE timestamp > now() - make_interval(days => :d)
                                   AND battery_soc IS NOT NULL ORDER BY timestamp"""), {"d": int(days)}).fetchall()
        solar = c.execute(text("""SELECT extract(hour FROM timestamp AT TIME ZONE 'Europe/Stockholm')::int,
                                         avg(solar_forecast_w), avg(pv_power_w)
                                  FROM sensor_log WHERE timestamp > now() - make_interval(days => :d)
                                    AND solar_forecast_w IS NOT NULL AND pv_power_w IS NOT NULL
                                  GROUP BY date_trunc('hour', timestamp), 1"""), {"d": int(days)}).fetchall()
        load = c.execute(text("""SELECT extract(isodow FROM h)::int - 1, extract(hour FROM h)::int, kw FROM (
                                    SELECT date_trunc('hour', timestamp AT TIME ZONE 'Europe/Stockholm') AS h,
                                           avg(GREATEST(0, COALESCE(house_consumption_w, net_power + COALESCE(pv_power_w, 0)
                                                - COALESCE(battery_power_w, 0))) / 1000.0
                                               - COALESCE(ev_power_kw, 0) - COALESCE(ev_carport_power_kw, 0)) AS kw
                                    FROM sensor_log WHERE timestamp > now() - interval '28 days' GROUP BY 1) t"""
                                 )).fetchall()
        y = c.execute(text("""SELECT extract(epoch FROM timestamp), net_power, battery_power_w, price FROM sensor_log
                              WHERE timestamp >= date_trunc('day', now() AT TIME ZONE 'Europe/Stockholm') AT TIME ZONE 'Europe/Stockholm' - interval '1 day'
                                AND timestamp < date_trunc('day', now() AT TIME ZONE 'Europe/Stockholm') AT TIME ZONE 'Europe/Stockholm'
                              ORDER BY timestamp""")).fetchall()
    f = lambda v: float(v) if v is not None else None
    samples = [(float(ts), f(soc), f(p)) for ts, soc, p, _, _ in rows]
    model = learn(samples, [(h, f(fc), f(a)) for h, fc, a in solar], configured)
    prof = median_load_profile([(d, h, max(0.0, f(kw) or 0.0)) for d, h, kw in load])
    model["learned"]["load_profile_hours"] = len(prof)
    if len(prof) >= 24:                     # minst ett dygns timmar täckta
        model["use"]["load_profile"] = prof
    yrows = []
    for i, (ts, net, bat, price) in enumerate(y):
        dt = (float(y[i + 1][0]) - float(ts)) if i + 1 < len(y) else 60.0
        yrows.append((dt, f(net), f(bat), f(price)))
    try:
        with engine.connect() as c:
            pairs = c.execute(text("""SELECT f.load_kw, f.solar_kw, a.load_kw, a.solar_kw FROM battery_plan_forecast f JOIN (
                    SELECT date_trunc('hour', timestamp) + floor(extract(minute FROM timestamp) / 15) * interval '15 minutes' AS q,
                           avg(GREATEST(0, COALESCE(house_consumption_w, net_power + COALESCE(pv_power_w, 0)
                                - COALESCE(battery_power_w, 0))) / 1000.0
                               - COALESCE(ev_power_kw, 0) - COALESCE(ev_carport_power_kw, 0)) AS load_kw,
                           avg(pv_power_w) / 1000.0 AS solar_kw
                    FROM sensor_log WHERE timestamp > now() - interval '14 days' GROUP BY 1) a ON a.q = f.t_slot
                WHERE f.t_slot > now() - interval '14 days' AND f.t_slot < now() - interval '15 minutes'""")).fetchall()
    except Exception:                      # tabellen finns först när en plan sparats
        pairs = []
    for kind, i in (("load", 0), ("solar", 1)):
        ratio, use_v, n = outcome_bias([(f(r[i]), f(r[i + 2])) for r in pairs], kind)
        model["learned"][f"{kind}_outcome_ratio"], model["learned"][f"{kind}_outcome_n"] = ratio, n
        if use_v is not None:
            model["use"][f"{kind}_bias"] = use_v
    model["saving_yesterday_kr"] = realized_saving(yrows, nordpool.full_buy_cost, nordpool.full_sell_income) if yrows else None
    return model
