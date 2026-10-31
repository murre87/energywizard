"""Strikt opt-in-telemetri: AV som standard, PÅ bara om TELEMETRY_OPT_IN=true
sätts uttryckligen i .env. När den är av skickas absolut ingenting - ingen
nätverksanrop görs ens.

Vad som skickas när den är PÅ (och bara det):
  - en anonymiserad husidentifierare (sha256(house_id), inte house_id i klartext)
  - vilka drivrutinklasser som är aktiva (klassnamn, t.ex. "GenericSolarDriver" -
    inga entity-id:n, inga sensorvärden, inga adresser/IP:n)
  - fel: modul + feltyp (exceptionens klassnamn, ALDRIG str(exception) - kan
    innehålla sensorvärden eller sökvägar)
  - tidsstämpel och git-commit-hash (grov versionsindikator)
Inget annat skickas - ingen elprisdata, ingen sensorhistorik, ingen plats.

Fail-safe med flit: ett nätverksfel eller en trasig collector får ALDRIG
störa huvudloopen i main.py - varje publik funktion fångar allt och loggar
bara lokalt, med kort timeout.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

OPT_IN = os.environ.get("TELEMETRY_OPT_IN", "").strip().lower() in ("true", "1", "yes")
ENDPOINT = os.environ.get("TELEMETRY_ENDPOINT", "").strip().rstrip("/")

_ERROR_SEEN: dict[str, datetime] = {}  # (modul, feltyp) -> senast skickad, i minnet räcker - processen kör kontinuerligt


def _hashed_house_id(house_id: str) -> str:
    return hashlib.sha256((house_id or "unknown").encode()).hexdigest()[:16]


def _software_version() -> str:
    try:
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=3, cwd=Path(__file__).parent)
        return r.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _driver_summary(cfg: dict) -> list[str]:
    """Kategoriska drivrutinsnamn, t.ex. ["heatpump:husdata", "car:tesla",
    "solar:solaredge"] - bara klassnamn/kategorier ur configen, inga entity-id:n."""
    out = []
    if cfg.get("heat_pump", {}).get("enabled"):
        out.append(f"heatpump:{cfg['heat_pump'].get('driver', '?')}")
    if cfg.get("solar", {}).get("enabled"):
        out.append(f"solar:{cfg['solar'].get('driver', '?')}")
    if cfg.get("spa", {}).get("enabled"):
        out.append(f"spa:{cfg['spa'].get('driver', '?')}")
    if cfg.get("battery", {}).get("enabled"):
        out.append(f"battery:{cfg['battery'].get('driver', '?')}")
    for ev in cfg.get("evs", []) or []:
        out.append(f"car:{ev.get('driver', '?')}")
    for ch in cfg.get("chargers", []) or []:
        out.append(f"charger:{ch.get('driver', '?')}")
    return out


def send_driver_snapshot(cfg: dict) -> None:
    """Skickas en gång vid uppstart - vilka drivrutinkategorier som är aktiva."""
    if not (OPT_IN and ENDPOINT):
        return
    try:
        payload = {
            "house": _hashed_house_id(cfg.get("house_id", "")),
            "version": _software_version(),
            "drivers": _driver_summary(cfg),
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        requests.post(f"{ENDPOINT}/ingest/drivers", json=payload, timeout=5)
    except Exception as e:
        print(f"ℹ️ Telemetri (drivrutinsöversikt) kunde inte skickas, fortsätter ändå: {e}")


def report_error(cfg: dict, module: str, error_type: str) -> None:
    """module/error_type ska alltid vara korta konstanter (t.ex. modulnamn och
    exceptionens klassnamn via type(e).__name__) - aldrig str(exception) rakt
    av. Avdubblar en gång/dygn per (modul, feltyp) så en upprepad bugg inte
    spammar samlaren."""
    if not (OPT_IN and ENDPOINT):
        return
    try:
        key = f"{module}:{error_type}"
        now = datetime.now(timezone.utc)
        last = _ERROR_SEEN.get(key)
        if last is not None and (now - last) < timedelta(hours=24):
            return
        _ERROR_SEEN[key] = now
        payload = {
            "house": _hashed_house_id(cfg.get("house_id", "")),
            "version": _software_version(),
            "module": module,
            "error_type": error_type,
            "ts": now.isoformat(),
        }
        requests.post(f"{ENDPOINT}/ingest/error", json=payload, timeout=5)
    except Exception as e:
        print(f"ℹ️ Telemetri (felrapport) kunde inte skickas, fortsätter ändå: {e}")
