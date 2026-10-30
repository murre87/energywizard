"""Anonym telemetri: en gång/vecka skickas ett litet, aggregerat besparingsmått
plus (vid fel) saniterade felrapporter till Emils egen samlare - se
docs/integritet.html för exakt fältlista och hur man stänger av det
(house_config.yaml: telemetry.enabled: false).

Allt här är fail-safe med flit: ett nätverksfel, en trasig DB-koppling eller
en oväntad exception i den här filen själv får ALDRIG störa styrloopen i
main.py - varje publik funktion fångar allt och loggar bara lokalt.

Skickar ALDRIG rådata (sensor_log-rader, tidsstämplade mätvärden, adress,
namn) - bara samma sorts veckoaggregat som redan bevisat fungerar i
scripts/export_public_stats.py, skalat till senaste 7 dagarna.
"""
from __future__ import annotations

import json
import os
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

TELEMETRY_ENDPOINT = os.environ.get("TELEMETRY_ENDPOINT", "https://energywizzard.profitalgos.com/t/ingest")
_ID_FILE = Path(os.environ.get("TELEMETRY_ID_PATH", "/smartbox_data/.telemetry_id"))
_ERROR_SEEN: dict[str, datetime] = {}  # (modul, feltyp) -> senast skickad, i minnet - räcker, processen kör kontinuerligt


def get_or_create_install_id() -> str:
    try:
        if _ID_FILE.exists():
            return _ID_FILE.read_text().strip()
        new_id = str(uuid.uuid4())
        _ID_FILE.parent.mkdir(parents=True, exist_ok=True)
        _ID_FILE.write_text(new_id)
        return new_id
    except OSError:
        return "unknown"  # ingen skrivbar volym - rapporter avvisas av samlaren (giltigt UUID krävs), men kraschar inte


def _software_version() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=3, cwd=Path(__file__).parent).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _driver_summary(cfg: dict) -> list[str]:
    """Kategoriska namn, t.ex. ["heatpump:thermia_husdata", "car:tesla", "car:nissan",
    "solar:solaredge"] - inga serienummer eller entity-id:n."""
    out = []
    if cfg.get("heat_pump", {}).get("enabled"):
        out.append(f"heatpump:{cfg['heat_pump'].get('driver', '?')}")
    if cfg.get("solar", {}).get("enabled"):
        out.append(f"solar:{cfg['solar'].get('driver', '?')}")
    if cfg.get("spa", {}).get("enabled"):
        out.append(f"spa:{cfg['spa'].get('driver', '?')}")
    for ev in cfg.get("evs", []):
        out.append(f"car:{ev.get('driver', '?')}")
    return out


def collect_weekly_aggregate(conn, cfg: dict) -> dict | None:
    """Samma formel som scripts/export_public_stats.py, skalad till 7 dagar.
    `conn` är en psycopg-anslutning (samma typ som logger.get_db() ger -
    main.py:s vanliga DB-mönster, inte SQLAlchemy)."""
    with conn.cursor() as cur:
        cur.execute("""
            WITH daily AS (
                SELECT date_trunc('day', timestamp) AS d,
                       sum(net_power) / 60000.0 AS kwh,
                       avg(price) AS day_avg,
                       sum(net_power * price) / nullif(sum(net_power), 0) AS weighted_price
                FROM sensor_log
                WHERE net_power > 0 AND price IS NOT NULL AND timestamp >= now() - interval '7 days'
                GROUP BY 1 HAVING sum(net_power) > 0
            ),
            solar AS (
                SELECT sum((pv_power_w + LEAST(net_power, 0)) * price) / 60000.0 AS value_kr,
                       sum(pv_power_w + LEAST(net_power, 0)) / 60000.0 AS kwh
                FROM sensor_log
                WHERE pv_power_w IS NOT NULL AND net_power IS NOT NULL AND price IS NOT NULL
                  AND pv_power_w > 0 AND timestamp >= now() - interval '7 days'
            )
            SELECT (SELECT sum((day_avg - weighted_price) * kwh) FROM daily) AS timing_kr,
                   (SELECT count(*) FROM daily) AS days_with_data,
                   solar.value_kr, solar.kwh
            FROM solar
        """)
        row = cur.fetchone()
    if row is None or row[1] == 0:
        return None
    timing_kr, days_with_data, solar_kr, solar_kwh = row
    return {
        "install_id": get_or_create_install_id(),
        "elomrade": cfg.get("elomrade"),
        "drivers": _driver_summary(cfg),
        "version": _software_version(),
        "timing_kr_7d": round(float(timing_kr or 0), 1),
        "solar_kr_7d": round(float(solar_kr or 0), 1),
        "solar_kwh_7d": round(float(solar_kwh or 0), 1),
        "days_with_data_7d": int(days_with_data),
    }


def send_weekly_report(conn, cfg: dict) -> None:
    if not cfg.get("telemetry", {}).get("enabled", True):
        return
    try:
        payload = collect_weekly_aggregate(conn, cfg)
        if payload is None:
            return
        requests.post(f"{TELEMETRY_ENDPOINT}/report", json=payload, timeout=10)
    except Exception as e:
        print(f"ℹ️ Telemetri (vecko­rapport) kunde inte skickas, fortsätter ändå: {e}")


def report_error(cfg: dict, module: str, error_type: str, safe_message: str) -> None:
    """Saniterat felrapport - module/error_type/safe_message ska ALLTID vara
    konstanter skrivna av anroparen, aldrig str(exception) rakt av (kan
    innehålla sensorvärden, IP, sökvägar). Avdubblar en gång/dygn per
    (modul, feltyp) - en upprepad bugg ska inte spamma samlaren."""
    if not cfg.get("telemetry", {}).get("enabled", True):
        return
    try:
        key = f"{module}:{error_type}"
        last = _ERROR_SEEN.get(key)
        now = datetime.now(timezone.utc)
        if last is not None and (now - last) < timedelta(hours=24):
            return
        _ERROR_SEEN[key] = now
        payload = {
            "install_id": get_or_create_install_id(),
            "module": module,
            "error_type": error_type,
            "message": safe_message,
            "version": _software_version(),
        }
        requests.post(f"{TELEMETRY_ENDPOINT}/error", json=payload, timeout=10)
    except Exception as e:
        print(f"ℹ️ Telemetri (felrapport) kunde inte skickas, fortsätter ändå: {e}")
