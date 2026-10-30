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
        heating = _latest_heating_backtest(conn)

    years_covered = max(days / 365.0, 1 / 365.0)
    data = {
        "generated_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
        "since": first_day.date().isoformat() if first_day else None,
        "days_covered": days,
        "total_kwh_bought": round(total_kwh, 0),
        "total_saved_kr": round(total_saved, 0),
        "saved_kr_per_year_avg": round(total_saved / years_covered, 0),
        "heating": heating,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Skrev {OUT_PATH}: {data}")


if __name__ == "__main__":
    main()
