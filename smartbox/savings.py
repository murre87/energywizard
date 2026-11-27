"""
savings.py - besparing per dag (besparingskortet på webben, i appen och HA-sensorn sensor.smartbox_besparing_idag).

Jämförelsen (2026-11-05, beslut Emil): vad samma el hade kostat i ett VANLIGT hushåll utan styrning, minus vad den
faktiskt kostade - med moms.

    besparing = (kostnad med en vanlig hushållsprofil - faktisk kostnad) × (1 + moms)

En vanlig hushållsprofil (PROFILE) fördelar dygnets köpta kWh över timmarna som ett hus utan styrning gör: lite på
natten, toppar på morgonen och kvällen när elen oftast är dyrast (matlagning, disk, tvätt, bilen kopplas in vid
hemkomst). Det är rättvisare än det tidigare måttet (jämnt fördelat över dygnet), som underskattade vad ett hus utan
styrning betalar. Momsen läggs på eftersom den betalas på spotpriset: varje sparad krona i spotpris är 1,25 kr på
fakturan (om priserna inte redan är inklusive moms). En dag då vi köpte dyrare än profilen blir negativ och visas så.

Dygnen räknas i svensk tid. daily_rows() läser databasen; build_day()/summarize_periods() är rena och testas i
tests/test_savings.py.
"""

from local_sql import local_sql
from sqlalchemy import text

# Andel av dygnets förbrukning per timme (00-23) i ett typiskt svenskt småhus utan styrning (vinterhalvår, normerad
# till 1): lågt på natten, topp 07-09 och 17-21.
PROFILE = [2.6, 2.3, 2.2, 2.2, 2.3, 2.8, 3.8, 4.8, 4.9, 4.4, 4.1, 4.0, 3.9, 3.8, 3.9, 4.3, 5.1, 6.0, 6.3, 6.0, 5.4, 4.6, 3.8, 3.0]
_PS = sum(PROFILE)
PROFILE = [p / _PS for p in PROFILE]

_HOURLY_SQL = """
    SELECT (timestamp AT TIME ZONE __EW_TIMEZONE__)::date AS d,
           extract(hour FROM timestamp AT TIME ZONE __EW_TIMEZONE__)::int AS h,
           avg(price) AS p,
           sum(GREATEST(net_power, 0)) / 60000.0 AS kwh,
           sum(GREATEST(net_power, 0) * price) / 60000.0 AS cost
    FROM sensor_log
    WHERE price IS NOT NULL AND net_power IS NOT NULL
      AND timestamp >= now() - make_interval(days => :days)
    GROUP BY 1, 2
    ORDER BY 1, 2
"""


def vat_factor() -> float:
    """1 + moms om priserna i databasen är exklusive moms, annars 1."""
    try:
        import nordpool
        return 1.0 if nordpool.prices_include_vat() else nordpool._vat_factor()
    except Exception:
        return 1.25


def profile_day(hours, min_hours=12):
    """hours = [(timme, snittpris, köpt kWh, faktisk kostnad)] för ett dygn -> (kWh, profilpris, betalt snittpris) eller
    None. Profilpriset = vad en kWh kostar i snitt med en vanlig hushållsprofil; timmar utan pris viktas om bort."""
    hours = [(int(h), float(p), float(k or 0), float(c or 0)) for h, p, k, c in hours if p is not None]
    kwh = sum(k for _h, _p, k, _c in hours)
    if kwh <= 0 or len(hours) < min_hours:
        return None
    w = sum(PROFILE[h] for h, _p, _k, _c in hours)
    prof_price = sum(PROFILE[h] * p for h, p, _k, _c in hours) / w
    paid = sum(c for _h, _p, _k, c in hours) / kwh
    return kwh, prof_price, paid


def daily_rows(conn, days=40, min_hours=12):
    """[{day, kwh, day_avg (profilpris), paid_avg, saved_kr, would_cost_kr}] för de senaste dagarna. min_hours: så många
    timmar med data krävs för att ett dygn ska räknas (12 för hela dygn; 1 för "idag hittills")."""
    by_day = {}
    for d, h, p, k, c in conn.execute(text(local_sql(_HOURLY_SQL)), {"days": int(days)}).fetchall():
        by_day.setdefault(d, []).append((h, p, k, c))
    vf = vat_factor()
    out = []
    for d in sorted(by_day):
        r = profile_day(by_day[d], min_hours)
        if r:
            row = build_day(d.isoformat(), r[0], r[1], r[2], vat=vf)
            if row:
                out.append(row)
    return out


def build_day(day, kwh, day_avg, paid_avg, vat=1.0):
    """day_avg = jämförelsepriset (vanlig hushållsprofil), paid_avg = faktiskt betalt; vat = 1 + moms."""
    if kwh is None or day_avg is None or paid_avg is None:
        return None
    kwh, day_avg, paid_avg, vat = float(kwh), float(day_avg), float(paid_avg), float(vat)
    return {
        "day": day,
        "kwh": round(kwh, 2),
        "day_avg": round(day_avg, 4),
        "paid_avg": round(paid_avg, 4),
        "saved_kr": round((day_avg - paid_avg) * kwh * vat, 2),
        "would_cost_kr": round(day_avg * kwh * vat, 2),
    }


def _summary(rows):
    saved = sum(r["saved_kr"] for r in rows)
    would = sum(r["would_cost_kr"] for r in rows)
    kwh = sum(r["kwh"] for r in rows)
    return {
        "saved_kr": round(saved, 2),
        "kwh": round(kwh, 1),
        "paid_kr": round(would - saved, 2),
        # Procent av vad samma el hade kostat till snittpris. Bara meningsfullt när den
        # kostnaden är positiv (en minuspris-dag kan göra den negativ).
        "pct": round(100.0 * saved / would, 1) if would > 0.5 else None,
        "days": len(rows),
    }


_all_cache = {"t": 0.0, "day": None, "val": None}
ALL_TTL_S = 1800


def all_time(conn, today):
    """Sparat sedan EnergyWizard startade (hela historiken i loggen): {saved_kr, kwh, paid_kr, pct, days, since}.
    Samma formel som Idag/7 dagar/Månad. Cachas i tio minuter, eftersom den läser hela historiken."""
    import time as _t
    now = _t.time()
    if _all_cache["val"] is not None and _all_cache["day"] == today and now - _all_cache["t"] < ALL_TTL_S:
        return _all_cache["val"]
    rows = daily_rows(conn, days=4000)
    val = _summary(rows)
    val["since"] = rows[0]["day"] if rows else None
    _all_cache.update(t=now, day=today, val=val)
    return val


_benefit_cache = {"t": 0.0, "day": None, "val": None}
_refresh = {"running": False}


def cached(conn, today):
    """(sedan_start, total_nytta) ur cachen, aldrig blockerande: hela historiken läses (flera sekunder), så en inaktuell eller tom
    cache fylls i en bakgrundstråd med egen anslutning, och sidan visar det som finns (None första gången, tills tråden är klar)."""
    import threading
    import time as _t
    now = _t.time()
    fresh = (_benefit_cache["val"] is not None and _benefit_cache["day"] == today and now - _benefit_cache["t"] < ALL_TTL_S
             and _all_cache["val"] is not None and _money_cache["val"] is not None and _money_cache["day"] == today)
    if not fresh and not _refresh["running"]:
        _refresh["running"] = True
        engine = conn.engine

        def run():
            try:
                with engine.connect() as c2:
                    all_time(c2, today)
                    total_benefit(c2, today)
                    money_all(c2, today)                        # pengarna sedan start (Ekonomi, period Totalt) fylls av samma tråd
            except Exception as e:
                print(f"⚠️ Total nytta: {type(e).__name__}: {str(e)[:120]}")
            finally:
                _refresh["running"] = False
        threading.Thread(target=run, daemon=True, name="savings-refresh").start()
    return _all_cache["val"], _benefit_cache["val"]


def total_benefit(conn, today):
    """Hela nyttan sedan start, post för post (startsidan): prisstyrning av köpt el, solel som huset använt (värderad till vad den
    hade kostat att köpa: moms, nätavgift, skatt), såld solel, och därav sol till elbil och spabad. Posterna för sol finns bara
    om huset har solceller. Summan lägger ihop posterna (sol till elbil/spa är en del av solelen och räknas inte dubbelt).
    Prisstyrningen är det EnergyWizard styr; solposterna är vad solcellerna ger, med eller utan styrning. Cachas i tio minuter."""
    import time as _t
    now = _t.time()
    if _benefit_cache["val"] is not None and _benefit_cache["day"] == today and now - _benefit_cache["t"] < ALL_TTL_S:
        return _benefit_cache["val"]
    timing = all_time(conn, today)
    items = [{"key": "timing", "kr": round(timing["saved_kr"], 0), "kwh": round(timing["kwh"], 0)}]
    flexible = None
    try:
        import nordpool
        rows = conn.execute(text("""
            SELECT date_trunc('hour', timestamp) AS h, sum(pv_power_w + LEAST(net_power, 0)) / 60000.0 AS kwh, avg(price) AS p
            FROM sensor_log WHERE pv_power_w IS NOT NULL AND net_power IS NOT NULL AND price IS NOT NULL AND pv_power_w > 0
            GROUP BY 1""")).fetchall()
        kr = kwh = 0.0
        for h, k, p in rows:
            if k is None or p is None or k <= 0:
                continue
            kr += float(k) * nordpool.full_buy_cost(float(p), h)
            kwh += float(k)
        if kwh > 1:
            items.append({"key": "solar_self", "kr": round(kr, 0), "kwh": round(kwh, 0)})
            sold = conn.execute(text(f"""
                SELECT sum(GREATEST(-net_power, 0) * {nordpool.sql_sell_income_expr('price')}) / 60000.0,
                       sum(GREATEST(-net_power, 0)) / 60000.0
                FROM sensor_log WHERE net_power IS NOT NULL AND price IS NOT NULL""")).fetchone()
            if sold and sold[1] and float(sold[1]) > 1:
                items.append({"key": "solar_sold", "kr": round(float(sold[0] or 0), 0), "kwh": round(float(sold[1]), 0)})
            f = conn.execute(text("""
                SELECT sum(COALESCE(ev_power_kw, 0) + COALESCE(ev_carport_power_kw, 0)) / 60.0,
                       sum(CASE WHEN spa_heater_running = 1 THEN spa_power_w ELSE 0 END) / 60000.0,
                       sum((COALESCE(ev_power_kw, 0) + COALESCE(ev_carport_power_kw, 0)) * 1000 * price) / 60000.0
                         + sum(CASE WHEN spa_heater_running = 1 THEN spa_power_w * price ELSE 0 END) / 60000.0
                FROM sensor_log WHERE net_power IS NOT NULL AND net_power <= 0 AND price IS NOT NULL""")).fetchone()
            if f and f[2] is not None and float(f[2]) > 0:
                flexible = {"kr": round(float(f[2]), 0), "ev_kwh": round(float(f[0] or 0), 0), "spa_kwh": round(float(f[1] or 0), 0)}
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
    val = {"since": timing.get("since"), "days": timing["days"], "items": items, "flexible": flexible,
           "total_kr": round(sum(i["kr"] for i in items), 0)}
    _benefit_cache.update(t=now, day=today, val=val)
    return val


def summarize_periods(rows, today, all_rows=None):
    """rows från daily_rows(), today = 'YYYY-MM-DD' i svensk tid.

    today: bara dagens rad (kan saknas tidigt på morgonen). week: de 7 kalenderdagarna
    t.o.m. idag. month: innevarande kalendermånad. Dagar utan data räknas inte som noll-
    besparing, de räknas inte alls (days visar hur många som fanns)."""
    from datetime import date, timedelta
    t = date.fromisoformat(today)
    week_start = (t - timedelta(days=6)).isoformat()
    month_prefix = today[:7]
    rows = sorted(rows or [], key=lambda r: r["day"])
    out = {
        "today": _summary([r for r in rows if r["day"] == today]),
        "week": _summary([r for r in rows if week_start <= r["day"] <= today]),
        "month": _summary([r for r in rows if r["day"].startswith(month_prefix) and r["day"] <= today]),
    }
    if all_rows is not None:                               # sedan start: hela historiken (dict från all_time, eller rader)
        if isinstance(all_rows, dict):
            out["all"] = all_rows
        else:
            ar = sorted(all_rows, key=lambda r: r["day"])
            out["all"] = {**_summary(ar), "since": ar[0]["day"] if ar else None}
    return out


# ---- Pengar per dag och period (Ekonomi-sidan) ---------------------------------------------------------------------
# Köpt och såld el minut för minut (sensor_log: en rad per minut, net_power + = köp), värderad med samma formel som
# motorn (nordpool.sql_buy_cost_expr/sql_sell_income_expr: moms, nätavgift, skatt och påslag enligt inställningarna).
def _money_sql():
    import nordpool
    buy, sell = nordpool.sql_buy_cost_expr("price", "timestamp"), nordpool.sql_sell_income_expr("price")
    return text(local_sql(f"""
        SELECT (timestamp AT TIME ZONE __EW_TIMEZONE__)::date AS d,
               sum(GREATEST(net_power, 0)) / 60000.0 AS bought_kwh,
               sum(GREATEST(net_power, 0) * {buy}) / 60000.0 AS cost,
               sum(GREATEST(-net_power, 0)) / 60000.0 AS sold_kwh,
               sum(GREATEST(-net_power, 0) * {sell}) / 60000.0 AS income
        FROM sensor_log
        WHERE net_power IS NOT NULL AND price IS NOT NULL AND timestamp >= now() - make_interval(days => :days)
        GROUP BY 1 ORDER BY 1"""))


def money_rows(conn, days=40):
    """[{day, bought_kwh, cost, sold_kwh, income, net}] - kostnad och intäkt i landets valuta."""
    out = []
    for d, bk, cost, sk, inc in conn.execute(_money_sql(), {"days": int(days)}).fetchall():
        bk, cost, sk, inc = (float(x or 0) for x in (bk, cost, sk, inc))
        out.append({"day": d.isoformat(), "bought_kwh": round(bk, 2), "cost": round(cost, 2), "sold_kwh": round(sk, 2),
                    "income": round(inc, 2), "net": round(cost - inc, 2)})
    return out


def price_span(rows, buy_cost=None):
    """Min, medel och max för spotpris och för det man faktiskt betalar.

    rows är (tid, sek_per_kwh). Köpt el på ekonomi-sidan är kostnaden inklusive moms,
    nätavgift och skatt delat på köpta kWh. Högsta spotpriset kan då ligga under det
    snittet (#510). buy använder samma formel som nordpool.full_buy_cost."""
    if buy_cost is None:
        import nordpool
        buy_cost = nordpool.full_buy_cost
    spots, buys = [], []
    for row in rows or []:
        t, p = (row[0], row[1]) if len(row) > 1 else (None, row[0])
        if p is None:
            continue
        spot = float(p)
        spots.append(spot)
        buys.append(float(buy_cost(spot, t)))

    def pack(xs):
        if not xs:
            return {"min": None, "avg": None, "max": None}
        return {"min": min(xs), "avg": sum(xs) / len(xs), "max": max(xs)}

    return {"spot": pack(spots), "buy": pack(buys)}


def _money_total(rows):
    """Summerar dagar som finns. En dag utan pris eller effekt är inte med och blir inte 0."""
    s = {k: round(sum(r[k] for r in rows), 2) for k in ("bought_kwh", "cost", "sold_kwh", "income", "net")}
    s["avg_paid"] = round(s["cost"] / s["bought_kwh"], 3) if s["bought_kwh"] > 0.05 else None
    s["avg_sold"] = round(s["income"] / s["sold_kwh"], 3) if s["sold_kwh"] > 0.05 else None
    s["days"] = len(rows)
    return s


_money_cache = {"t": 0.0, "day": None, "val": None}


def money_all(conn, today):
    """Köpt, såld och netto sedan EnergyWizard startade. Samma formel som Idag/7 dagar/Månad.
    Cachas i tio minuter. Dagar utan pris eller effekt räknas inte som noll."""
    import time as _t
    now = _t.time()
    if _money_cache["val"] is not None and _money_cache["day"] == today and now - _money_cache["t"] < ALL_TTL_S:
        return _money_cache["val"]
    rows = sorted(money_rows(conn, days=4000), key=lambda r: r["day"])
    val = _money_total(rows)
    val["since"] = rows[0]["day"] if rows else None
    _money_cache.update(t=now, day=today, val=val)
    return val


def money_cached():
    """Köpt, såld och netto sedan start ur cachen, aldrig blockerande (None tills bakgrundstråden i cached() har fyllt den)."""
    return _money_cache["val"]


def money_periods(rows, today, all_rows=None):
    """Idag / 7 dagar / innevarande månad, samma perioder som summarize_periods().

    all_rows: hela historiken (dict från money_all, eller rader). Utan den finns ingen period all,
    så anrop som bara har de senaste dagarna ändras inte."""
    from datetime import date, timedelta
    t = date.fromisoformat(today)
    week_start = (t - timedelta(days=6)).isoformat()
    rows = sorted(rows or [], key=lambda r: r["day"])
    out = {"today": _money_total([r for r in rows if r["day"] == today]),
           "week": _money_total([r for r in rows if week_start <= r["day"] <= today]),
           "month": _money_total([r for r in rows if r["day"].startswith(today[:7]) and r["day"] <= today])}
    if all_rows is not None:
        if isinstance(all_rows, dict):
            out["all"] = all_rows
        else:
            ar = sorted(all_rows, key=lambda r: r["day"])
            out["all"] = {**_money_total(ar), "since": ar[0]["day"] if ar else None}
    return out
