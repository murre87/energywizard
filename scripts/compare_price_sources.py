"""Jämför elprisetjustnu.se mot Home Assistants nordpool-integration för samma dygn, innan
PRICE_SOURCE=ha_nordpool någonsin sätts i produktion. Körs manuellt, inte en del av testsviten -
inget mockat test kan bevisa att två RIKTIGA prisserier faktiskt överensstämmer (markup/moms-
antaganden kan skilja sig åt mellan källorna).

Körs inifrån smartbox-containern (har requests + rätt env för HA_IP/HA_TOKEN/SUPERVISOR_TOKEN):

    docker compose exec smartbox python compare_price_sources.py [YYYY-MM-DD]

Utan datum jämförs dagens dygn.
"""
import sys
from datetime import datetime, timedelta

sys.path.insert(0, "/app")

import nordpool
import homeassistant


def _old_source_prices(date_obj):
    import requests
    date_str = date_obj.strftime("%Y/%m-%d")
    url = f"https://www.elprisetjustnu.se/api/v1/prices/{date_str}_SE3.json"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    return {
        datetime.fromisoformat(item["time_start"]).astimezone(nordpool.SWE_TZ): item["SEK_per_kWh"]
        for item in r.json()
    }


def _ha_source_prices(date_obj):
    import os
    import requests
    entity = os.environ.get("NORDPOOL_HA_ENTITY", "sensor.nordpool")
    r = requests.get(
        f"{homeassistant._BASE}/states/{entity}",
        headers=homeassistant._HEADERS, timeout=10, verify=homeassistant._VERIFY,
    )
    r.raise_for_status()
    attrs = r.json().get("attributes", {})
    raw = (attrs.get("raw_today") or []) + (attrs.get("raw_tomorrow") or [])
    return {
        datetime.fromisoformat(item["start"]).astimezone(nordpool.SWE_TZ): item["value"]
        for item in raw
        if datetime.fromisoformat(item["start"]).astimezone(nordpool.SWE_TZ).date() == date_obj.date()
    }


def main():
    date_obj = datetime.strptime(sys.argv[1], "%Y-%m-%d").replace(tzinfo=nordpool.SWE_TZ) \
        if len(sys.argv) > 1 else datetime.now(nordpool.SWE_TZ)

    print(f"Jämför priskällor för {date_obj.date()}...\n")
    old = _old_source_prices(date_obj)
    ha = _ha_source_prices(date_obj)

    print(f"elprisetjustnu.se: {len(old)} rader (timupplösning)")
    print(f"HA nordpool:       {len(ha)} rader (kvartsupplösning)\n")

    diffs = []
    # Gammal källa är timbaserad - jämför varje HA-kvart mot timmens elprisetjustnu-pris.
    for ts, ha_price in sorted(ha.items()):
        hour_ts = ts.replace(minute=0, second=0, microsecond=0)
        old_price = old.get(hour_ts)
        if old_price is None:
            continue
        diff = ha_price - old_price
        diffs.append(diff)
        marker = "  <-- STOR AVVIKELSE" if abs(diff) > 0.05 else ""
        print(f"{ts.strftime('%H:%M')}  HA={ha_price:.4f}  gammal={old_price:.4f}  diff={diff:+.4f}{marker}")

    if diffs:
        avg_diff = sum(diffs) / len(diffs)
        max_diff = max(diffs, key=abs)
        print(f"\nSnittavvikelse: {avg_diff:+.4f} kr/kWh")
        print(f"Största avvikelse: {max_diff:+.4f} kr/kWh")
    else:
        print("\nIngen överlappande data att jämföra - kontrollera att båda källorna har data för dygnet.")


if __name__ == "__main__":
    main()
