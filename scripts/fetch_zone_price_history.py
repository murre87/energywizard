"""Hämtar historiska spotpriser per elområde (SE1-SE4) från elprisetjustnu.se
(samma API som smartbox/nordpool.py redan använder för SE3, bara utökat till
alla fyra områden och många år bakåt) och räknar fram ett årssnitt och ett
volatilitetsmått per område till docs/data/price_zones.json.

Rör INTE den skarpa elpriser-tabellen (den är SE3-only och styr live-driften) -
detta är en fristående, läsbar jämförelse för den publika sidan. Cachar varje
dags rådata lokalt (scripts/data/price_cache/, gitignorad) så ett omkört inte
behöver hämta om allt - bara nya dagar sen förra körningen.
"""
import json
import time
from datetime import date, timedelta
from pathlib import Path

import requests

ZONES = ["SE1", "SE2", "SE3", "SE4"]
START_DATE = date.today() - timedelta(days=3 * 365)  # senaste 3 åren - Emils val 2026-10-30, kortare än den fulla tillgängliga historiken (sen 2022)
CACHE_DIR = Path(__file__).resolve().parent / "data" / "price_cache"
OUT_PATH = Path(__file__).resolve().parent.parent / "docs" / "data" / "price_zones.json"
REQUEST_DELAY_S = 0.15  # hövlig mot elprisetjustnu.se - inte en produktions-SLA-tjänst


def fetch_day(zone: str, d: date) -> list[dict] | None:
    cache_file = CACHE_DIR / zone / f"{d.isoformat()}.json"
    if cache_file.exists():
        return json.loads(cache_file.read_text())
    date_str = d.strftime("%Y/%m-%d")
    url = f"https://www.elprisetjustnu.se/api/v1/prices/{date_str}_{zone}.json"
    try:
        r = requests.get(url, timeout=10)
        time.sleep(REQUEST_DELAY_S)
        if r.status_code != 200:
            return None
        data = r.json()
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(data))
        return data
    except requests.RequestException:
        time.sleep(1)
        return None


def main():
    today = date.today()
    result = {"generated_at": None, "since": START_DATE.isoformat(), "zones": {}}

    for zone in ZONES:
        prices = []
        daily_ranges = []
        yearly = {}
        d = START_DATE
        fetched, missing = 0, 0
        while d < today:
            rows = fetch_day(zone, d)
            if rows:
                day_prices = [float(r["SEK_per_kWh"]) for r in rows]
                prices.extend(day_prices)
                if len(day_prices) > 1:
                    daily_ranges.append(max(day_prices) - min(day_prices))
                yearly.setdefault(d.year, []).extend(day_prices)
                fetched += 1
            else:
                missing += 1
            d += timedelta(days=1)

        if prices:
            avg = sum(prices) / len(prices)
            avg_daily_range = sum(daily_ranges) / len(daily_ranges) if daily_ranges else 0.0
            yearly_avg = {str(y): round(sum(v) / len(v), 3) for y, v in sorted(yearly.items())}
            result["zones"][zone] = {
                "avg_sek_per_kwh": round(avg, 3),
                "avg_daily_range_sek_per_kwh": round(avg_daily_range, 3),
                "days_covered": fetched,
                "yearly_avg": yearly_avg,
            }
        print(f"{zone}: {fetched} dagar hämtade, {missing} saknades/404")

    import datetime as dt
    result["generated_at"] = dt.datetime.utcnow().isoformat() + "Z"
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Skrev {OUT_PATH}")


if __name__ == "__main__":
    main()
