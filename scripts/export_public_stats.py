"""Exporterar aggregerade, verkliga besparingssiffror till docs/data/stats.json
för den publika GitHub Pages-sidan. Körs lokalt på NUC:en (cron), aldrig i CI -
behöver nå den privata Postgres-databasen. Skriver bara aggregat, ingen rå
sensor- eller personuppgift.

Besparingsformeln är samma som smartbox/ha_publisher.py:99-108 (daglig
"besparing idag"-sensor) - generaliserad till hela historiken: per dag,
(dygnssnittpris - effektviktat snittpris betalat) * köpt kWh, summerat.
"""
import json
import os
from pathlib import Path

from sqlalchemy import create_engine, text

ENGINE = create_engine(
    f"postgresql+psycopg://{os.environ['POSTGRES_USER']}:{os.environ['POSTGRES_PASSWORD']}"
    f"@{os.environ.get('POSTGRES_HOST', 'localhost')}:{os.environ.get('POSTGRES_PORT', '5432')}"
    f"/{os.environ['POSTGRES_DB']}"
)

OUT_PATH = Path(__file__).resolve().parent.parent / "docs" / "data" / "stats.json"


def _total_saving(conn):
    """Per dag: (dygnssnittpris - effektviktat snittpris betalat) * köpt kWh,
    summerat över alla dagar med riktig data. Samma formel som den dagliga
    HA-sensorn, bara applicerad på hela historiken i stället för bara idag."""
    rows = conn.execute(text("""
        SELECT date_trunc('day', timestamp) AS d,
               sum(net_power) / 60000.0 AS kwh,
               avg(price) AS day_avg,
               sum(net_power * price) / nullif(sum(net_power), 0) AS weighted_price
        FROM sensor_log
        WHERE net_power > 0 AND price IS NOT NULL
        GROUP BY 1
        HAVING sum(net_power) > 0
        ORDER BY 1
    """)).fetchall()
    total_saved = 0.0
    total_kwh = 0.0
    days = 0
    first_day = None
    for d, kwh, day_avg, weighted_price in rows:
        if kwh is None or day_avg is None or weighted_price is None:
            continue
        total_saved += (float(day_avg) - float(weighted_price)) * float(kwh)
        total_kwh += float(kwh)
        days += 1
        if first_day is None:
            first_day = d
    return total_saved, total_kwh, days, first_day


def _monthly_breakdown(conn):
    """Prisoptimering + solvärde per månad - visar trenden rakt av (t.ex. att
    prisoptimeringen ökar på hösten när elpriserna blir mer volatila) istället
    för att påstå en vinterprognos vi inte har data för än."""
    rows = conn.execute(text("""
        WITH daily AS (
            SELECT date_trunc('day', timestamp) AS d,
                   sum(net_power) / 60000.0 AS kwh,
                   avg(price) AS day_avg,
                   sum(net_power * price) / nullif(sum(net_power), 0) AS weighted_price
            FROM sensor_log WHERE net_power > 0 AND price IS NOT NULL
            GROUP BY 1 HAVING sum(net_power) > 0
        ),
        daily_solar AS (
            SELECT date_trunc('day', timestamp) AS d,
                   sum((pv_power_w + LEAST(net_power, 0)) * price) / 60000.0 AS solar_kr
            FROM sensor_log
            WHERE pv_power_w IS NOT NULL AND net_power IS NOT NULL AND price IS NOT NULL AND pv_power_w > 0
            GROUP BY 1
        )
        SELECT date_trunc('month', daily.d) AS m,
               sum((day_avg - weighted_price) * kwh) AS timing_kr,
               sum(COALESCE(daily_solar.solar_kr, 0)) AS solar_kr
        FROM daily LEFT JOIN daily_solar ON daily.d = daily_solar.d
        GROUP BY 1 ORDER BY 1
    """)).fetchall()
    def _r(v):
        v = round(float(v or 0), 0)
        return v + 0.0 if v == 0 else v  # normaliserar -0.0 -> 0.0 (fulare i JSON annars)

    return [{"month": m.date().isoformat()[:7], "timing_kr": _r(timing_kr), "solar_kr": _r(solar_kr)} for m, timing_kr, solar_kr in rows]


def _solar_self_consumption_value(conn):
    """Värdet av solel som gick direkt till huset i stället för att köpas eller
    säljas - sum((pv_power_w - exporterad_effekt) * price) över hela historiken.
    pv_power_w - max(0, -net_power) = den del av produktionen som INTE
    exporterades (net_power < 0 betyder nettoexport, se kalibrering i
    docs: positiv net_power = köper, negativ = säljer/exporterar)."""
    row = conn.execute(text("""
        SELECT sum((pv_power_w + LEAST(net_power, 0)) * price) / 60000.0 AS value_kr,
               sum(pv_power_w + LEAST(net_power, 0)) / 60000.0 AS kwh
        FROM sensor_log
        WHERE pv_power_w IS NOT NULL AND net_power IS NOT NULL AND price IS NOT NULL AND pv_power_w > 0
    """)).fetchone()
    if row is None or row[0] is None:
        return None
    return {"value_kr": round(float(row[0]), 0), "kwh": round(float(row[1]), 0)}


def _solar_timed_flexible_load(conn):
    """Elbilsladdning + spavärme som skedde specifikt medan huset nettoexporterade
    (net_power <= 0, dvs. inget extra köptes för just den lasten) - en konkret
    delmängd av solvärdet ovan, inte en uppskattning: bara ett villkor på
    riktiga loggrader (var nettot <= 0 just då), ingen flödesapproximation."""
    row = conn.execute(text("""
        SELECT sum(COALESCE(ev_power_kw, 0) + COALESCE(ev_carport_power_kw, 0)) / 60.0 AS ev_kwh,
               sum(CASE WHEN spa_heater_running = 1 THEN spa_power_w ELSE 0 END) / 60000.0 AS spa_kwh,
               sum((COALESCE(ev_power_kw, 0) + COALESCE(ev_carport_power_kw, 0)) * 1000 * price) / 60000.0
                 + sum(CASE WHEN spa_heater_running = 1 THEN spa_power_w * price ELSE 0 END) / 60000.0 AS value_kr
        FROM sensor_log
        WHERE net_power IS NOT NULL AND net_power <= 0 AND price IS NOT NULL
    """)).fetchone()
    if row is None or row[0] is None:
        return None
    return {"ev_kwh": round(float(row[0] or 0), 0), "spa_kwh": round(float(row[1] or 0), 0), "value_kr": round(float(row[2] or 0), 0)}


def _latest_heating_backtest(conn):
    row = conn.execute(text("""
        SELECT timestamp, days_used, saving_kr, saving_pct, saving_kr_year, models_trained
        FROM mpc_backtest
        WHERE heating_active = true
        ORDER BY timestamp DESC LIMIT 1
    """)).fetchone()
    if row is None:
        return None
    ts, days_used, saving_kr, saving_pct, saving_kr_year, models_trained = row
    return {
        "generated_at": ts.isoformat(),
        "days_used": days_used,
        "saving_kr": round(float(saving_kr or 0), 1),
        "saving_pct": round(float(saving_pct or 0), 1),
        "saving_kr_year": round(float(saving_kr_year or 0), 0),
        "models_trained": bool(models_trained),
        "early_season": (days_used or 0) < 60,
    }


def main():
    with ENGINE.connect() as conn:
        total_saved, total_kwh, days, first_day = _total_saving(conn)
        solar = _solar_self_consumption_value(conn)
        flexible = _solar_timed_flexible_load(conn)
        heating = _latest_heating_backtest(conn)
        monthly = _monthly_breakdown(conn)

    years_covered = max(days / 365.0, 1 / 365.0)
    combined_saved = total_saved + (solar["value_kr"] if solar else 0)
    data = {
        "generated_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
        "since": first_day.date().isoformat() if first_day else None,
        "days_covered": days,
        "total_kwh_bought": round(total_kwh, 0),
        "price_timing_saved_kr": round(total_saved, 0),
        "solar": solar,
        "solar_flexible_load": flexible,
        "total_saved_kr": round(combined_saved, 0),
        "saved_kr_per_year_avg": round(combined_saved / years_covered, 0),
        "heating": heating,
        "monthly": monthly,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Skrev {OUT_PATH}: {data}")


if __name__ == "__main__":
    main()
