"""pump_runtime.py – Värmepumpens drifttid (kompressor, tillsats 1/2, varmvatten) per månad och år.

Pumpens räknare (timmar, Husdata-register 34-37) loggas redan varje minut i sensor_log. Här sparas dagsvärdet
permanent i tabellen pump_runtime_daily (räknarens värde per dygn). Timmar per månad/år = skillnaden mellan dygnens
räknarvärden (delta). Tabellen fylls på bakåt från sensor_log vid start och uppdateras varje minut för dagens datum.
"""
from sqlalchemy import text
import nordpool

DDL = """
CREATE TABLE IF NOT EXISTS pump_runtime_daily (
    day           DATE PRIMARY KEY,
    compressor_h  INTEGER,
    aux1_h        INTEGER,
    aux2_h        INTEGER,
    warm_water_h  INTEGER,
    updated_at    TIMESTAMPTZ DEFAULT now()
)"""

# Dygnets värde = maxvärdet, men glitchvärden som ligger mer än 24 h från dygnets median ignoreras
# (en räknare kan aldrig öka mer än 24 h på ett dygn).
_SELECT_DAYS = """
WITH d AS (
    SELECT (timestamp AT TIME ZONE 'Europe/Stockholm')::date AS day,
           compressor_runtime_h c, aux_runtime_h a1, aux_runtime_2_h a2, warm_water_runtime_h w
    FROM sensor_log WHERE compressor_runtime_h IS NOT NULL {where}
), m AS (
    SELECT day, percentile_disc(0.5) WITHIN GROUP (ORDER BY c) mc, percentile_disc(0.5) WITHIN GROUP (ORDER BY a1) ma1,
           percentile_disc(0.5) WITHIN GROUP (ORDER BY a2) ma2, percentile_disc(0.5) WITHIN GROUP (ORDER BY w) mw
    FROM d GROUP BY day
)
SELECT d.day,
       max(d.c)  FILTER (WHERE d.c  BETWEEN m.mc  - 24 AND m.mc  + 24),
       max(d.a1) FILTER (WHERE d.a1 BETWEEN m.ma1 - 24 AND m.ma1 + 24),
       max(d.a2) FILTER (WHERE d.a2 BETWEEN m.ma2 - 24 AND m.ma2 + 24),
       max(d.w)  FILTER (WHERE d.w  BETWEEN m.mw  - 24 AND m.mw  + 24)
FROM d JOIN m USING (day) GROUP BY d.day"""

_UPSERT = """
INSERT INTO pump_runtime_daily (day, compressor_h, aux1_h, aux2_h, warm_water_h)
{select}
ON CONFLICT (day) DO UPDATE SET
    compressor_h = GREATEST(pump_runtime_daily.compressor_h, EXCLUDED.compressor_h),
    aux1_h       = GREATEST(pump_runtime_daily.aux1_h, EXCLUDED.aux1_h),
    aux2_h       = GREATEST(pump_runtime_daily.aux2_h, EXCLUDED.aux2_h),
    warm_water_h = GREATEST(pump_runtime_daily.warm_water_h, EXCLUDED.warm_water_h),
    updated_at   = now()"""


def ensure_and_backfill(engine):
    """Skapar tabellen och fyller på alla dygn som finns i sensor_log (säkert att köra upprepat)."""
    with engine.begin() as c:
        c.execute(text(DDL))
        c.execute(text(_UPSERT.format(select=_SELECT_DAYS.format(where=""))))


def upsert_today(engine):
    with engine.begin() as c:
        where = "AND timestamp >= (date_trunc('day', now() AT TIME ZONE 'Europe/Stockholm') AT TIME ZONE 'Europe/Stockholm')"
        c.execute(text(_UPSERT.format(select=_SELECT_DAYS.format(where=where))))


_DELTAS = """
WITH x AS (
    SELECT day,
           GREATEST(compressor_h - lag(compressor_h) OVER (ORDER BY day), 0) c,
           GREATEST(aux1_h - lag(aux1_h) OVER (ORDER BY day), 0) a1,
           GREATEST(aux2_h - lag(aux2_h) OVER (ORDER BY day), 0) a2,
           GREATEST(warm_water_h - lag(warm_water_h) OVER (ORDER BY day), 0) w
    FROM pump_runtime_daily
)
SELECT date_trunc('{unit}', day)::date AS period, sum(c), sum(a1), sum(a2), sum(w), count(*) FILTER (WHERE c IS NOT NULL) AS dagar
FROM x GROUP BY 1 ORDER BY 1"""


def periods(conn, unit="month"):
    """[(period_start_date, komp_h, tillsats1_h, tillsats2_h, varmvatten_h, dagar), ...]. Första dygnet saknar delta."""
    return [(r[0], int(r[1] or 0), int(r[2] or 0), int(r[3] or 0), int(r[4] or 0), int(r[5] or 0))
            for r in conn.execute(text(_DELTAS.format(unit=unit))).fetchall()]


def totals(conn):
    r = conn.execute(text("SELECT compressor_h, aux1_h, aux2_h, warm_water_h FROM pump_runtime_daily ORDER BY day DESC LIMIT 1")).fetchone()
    return r


# ── GRATIS TACK VARE SOLEN ─────────────────────────────────────────────────────────────────────────
# "Gratis" = ingen nätimport (net_power <= 0, alltså export eller precis noll) medan solen producerar (pv > 100 W).
# Tibbers nätmätning är tillförlitlig, medan solvärdet före 2026-09-20 kom från ett 15-minutersvärde, därför
# används solvärdet bara som "solen är uppe"-filter. Tidsvägt per loggrad (rader glesare än 20 min = lucka = räknas ej).
# Pumpens elförbrukning (W) modelleras från framledningen med den kalibrerade kurvan (samma som main._PUMP_EL_CURVE) och
# värderas med nordpool.sql_buy_cost_expr (delad inköpsprismodell, källoberoende - se gpm.py/smartdashboard).
_PUMP_W_SQL = """CASE WHEN fwd IS NULL THEN 2700 WHEN fwd <= 25 THEN 2000
    WHEN fwd <= 32.5 THEN 2000 + (fwd - 25) * (2480 - 2000) / 7.5 WHEN fwd <= 37.5 THEN 2480 + (fwd - 32.5) * (2655 - 2480) / 5
    WHEN fwd <= 42.5 THEN 2655 + (fwd - 37.5) * (2865 - 2655) / 5 WHEN fwd <= 50 THEN 2865 + (fwd - 42.5) * (3460 - 2865) / 7.5
    WHEN fwd <= 60 THEN 3460 + (fwd - 50) * (4180 - 3460) / 10 ELSE 4180 END"""
_SOLAR_SQL = """
WITH w AS (
    SELECT (timestamp AT TIME ZONE 'Europe/Stockholm') lt, net_power, compressor_running k, COALESCE(pv_power_w, 0) pv, fwd,
           COALESCE(price, 0) price,
           CASE WHEN raw <= 1200 THEN LEAST(raw, 900) ELSE 0 END dt
    FROM (SELECT timestamp, net_power, compressor_running, pv_power_w, forward_temp AS fwd, price,
                 extract(epoch FROM lead(timestamp) OVER (ORDER BY timestamp) - timestamp) raw
          FROM sensor_log WHERE net_power IS NOT NULL) x
), p AS (SELECT *, (""" + _PUMP_W_SQL + """) AS pw FROM w)
SELECT {grp} AS k, sum(dt) / 3600.0 AS logg_h,
       sum(dt) FILTER (WHERE net_power <= 0 AND pv > 100) / 3600.0 AS hus_h,
       sum(dt) FILTER (WHERE k = 1) / 3600.0 AS komp_h,
       sum(dt) FILTER (WHERE k = 1 AND net_power <= 0 AND pv > 100) / 3600.0 AS komp_gratis_h,
       sum(dt * pw) FILTER (WHERE k = 1) / 3600000.0 AS komp_kwh,
       sum(dt * pw) FILTER (WHERE k = 1 AND net_power <= 0 AND pv > 100) / 3600000.0 AS komp_sol_kwh,
       sum(dt * pw * {buy}) FILTER (WHERE k = 1 AND net_power <= 0 AND pv > 100) / 3600000.0 AS sparat_kr
FROM p GROUP BY 1 ORDER BY 1"""


def solar_free(conn):
    """Returnerar {'manader': [...], 'timmar': [...]}.
    manader: dict(manad, logg_h, tackning_pct, hus_h (uppskattad, skalad för loggluckor), komp_h (pumpens räknare),
                  komp_gratis_h (uppskattad = räknartimmar x soltäckt andel), pct_gratis)
    timmar:  dict(timme, hus_h, komp_h, komp_gratis_h) – summerat över hela perioden (loggade timmar)."""
    from datetime import datetime, timedelta
    import zoneinfo
    swe = zoneinfo.ZoneInfo("Europe/Stockholm")
    first = conn.execute(text("SELECT min(timestamp) FROM sensor_log WHERE net_power IS NOT NULL")).scalar()
    first_l = first.astimezone(swe).replace(tzinfo=None) if first else None
    now_l = datetime.now(swe).replace(tzinfo=None)
    counter = {p[0]: p[1] for p in periods(conn, "month")}          # månad -> kompressortimmar från pumpens räknare
    out_m = []
    buy = nordpool.sql_buy_cost_expr("price")
    for r in conn.execute(text(_SOLAR_SQL.format(grp="date_trunc('month', lt)::date", buy=buy))).fetchall():
        m = r[0]
        nxt = datetime(m.year + (m.month // 12), m.month % 12 + 1, 1)
        start = max(datetime(m.year, m.month, 1), first_l or datetime(m.year, m.month, 1))
        cal_h = max(1.0, (min(nxt, now_l) - start).total_seconds() / 3600.0)
        logg_h, hus_h, komp_h, komp_g, kwh, sol_kwh, sparat = (float(x or 0) for x in r[1:8])
        cover = min(1.0, logg_h / cal_h)
        share = (komp_g / komp_h) if komp_h > 0 else 0.0
        c_h = counter.get(m, 0)
        scale = (c_h / komp_h) if komp_h > 0 and c_h > 0 else 1.0     # uppskalning för loggluckor via pumpens riktiga räknare
        out_m.append({"manad": m, "logg_h": round(logg_h), "tackning_pct": round(100 * cover),
                      "hus_h": round(hus_h / cover) if cover > 0 else 0, "komp_h": c_h,
                      "komp_gratis_h": round(c_h * share, 1), "pct_gratis": round(100 * share),
                      "komp_kwh": round(kwh * scale), "komp_sol_kwh": round(sol_kwh * scale), "sparat_kr": round(sparat * scale)})
    out_h = [{"timme": int(r[0]), "hus_h": round(float(r[2] or 0), 1), "komp_h": round(float(r[3] or 0), 1),
              "komp_gratis_h": round(float(r[4] or 0), 1)}
             for r in conn.execute(text(_SOLAR_SQL.format(grp="extract(hour FROM lt)::int", buy=buy))).fetchall()]
    return {"manader": out_m, "timmar": out_h}


# ── ELBIL: SOLEL I LADDNINGEN ──────────────────────────────────────────────────────────────────────
# Uppmätt laddeffekt per Easee-laddare (Lite = Nissan Leaf, Carport = Tesla). Solandel per minut enligt "elbilen som marginallast":
# den del av laddeffekten som INTE importeras från nätet, andel = clamp(1 - nätimport / total laddeffekt, 0, 1), och bara när solen
# är uppe (pv > 100 W). Exempel: nät 0 W → 100 % sol, nät = laddeffekten → 0 %, natt → 0 %.
_EV_SQL = """
WITH w AS (
    SELECT date_trunc('month', timestamp AT TIME ZONE 'Europe/Stockholm')::date mth, net_power, COALESCE(pv_power_w, 0) pv,
           COALESCE(price, 0) price, COALESCE(ev_power_kw, 0) * 1000 lite, COALESCE(ev_carport_power_kw, 0) * 1000 cp,
           CASE WHEN raw <= 1200 THEN LEAST(raw, 900) ELSE 0 END dt
    FROM (SELECT timestamp, net_power, pv_power_w, price, ev_power_kw, ev_carport_power_kw,
                 extract(epoch FROM lead(timestamp) OVER (ORDER BY timestamp) - timestamp) raw
          FROM sensor_log WHERE net_power IS NOT NULL) x
), s AS (
    SELECT *, lite + cp AS tot,
           CASE WHEN lite + cp > 50 AND pv > 100 THEN GREATEST(0, LEAST(1, 1 - GREATEST(net_power, 0) / (lite + cp))) ELSE 0 END sh
    FROM w
)
SELECT mth, sum(dt) / 3600.0 AS logg_h,
       sum(dt * lite) / 3600000.0, sum(dt * lite * sh) / 3600000.0, sum(dt * lite * sh * {buy}) / 3600000.0,
       sum(dt * cp) / 3600000.0,   sum(dt * cp * sh) / 3600000.0,   sum(dt * cp * sh * {buy}) / 3600000.0
FROM s GROUP BY 1 ORDER BY 1"""


def ev_solar(conn):
    """Månadsvis: dict(manad, lite_kwh, lite_sol_kwh, lite_kr, carport_kwh, carport_sol_kwh, carport_kr), uppskalade för loggluckor."""
    from datetime import datetime
    import zoneinfo
    swe = zoneinfo.ZoneInfo("Europe/Stockholm")
    first = conn.execute(text("SELECT min(timestamp) FROM sensor_log WHERE net_power IS NOT NULL")).scalar()
    first_l = first.astimezone(swe).replace(tzinfo=None) if first else None
    now_l = datetime.now(swe).replace(tzinfo=None)
    out = []
    for r in conn.execute(text(_EV_SQL.format(buy=nordpool.sql_buy_cost_expr("price")))).fetchall():
        m = r[0]
        nxt = datetime(m.year + (m.month // 12), m.month % 12 + 1, 1)
        start = max(datetime(m.year, m.month, 1), first_l or datetime(m.year, m.month, 1))
        cal_h = max(1.0, (min(nxt, now_l) - start).total_seconds() / 3600.0)
        cover = max(0.05, min(1.0, float(r[1] or 0) / cal_h))
        v = [float(x or 0) / cover for x in r[2:8]]
        out.append({"manad": m, "tackning_pct": round(100 * cover),
                    "lite_kwh": round(v[0]), "lite_sol_kwh": round(v[1]), "lite_kr": round(v[2]),
                    "carport_kwh": round(v[3]), "carport_sol_kwh": round(v[4]), "carport_kr": round(v[5])})
    return out
