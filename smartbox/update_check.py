"""update_check.py - finns en nyare EnergyWizard? (Emil 2026-11-13: 84 av 95 hus körde en äldre version och fick inte
rättningarna; tillägg uppdateras inte av sig själva i Home Assistant.)

- HA-tillägget: Supervisor vet både installerad och senaste version (/addons/self/info: version, version_latest,
  update_available). Kräver hassio_api: true i tilläggets config.yaml.
- Docker: bilderna heter 1.<körningsnummer> (APP_VERSION); senaste lyckade bildbygget på main hämtas från GitHubs
  öppna API.
- Annars (utveckling, okänt): ingen uppgift - vi påstår aldrig "senaste" utan att veta.

Hämtas högst var sjätte timme, i bakgrunden, så att inget anrop väntar på nätet. Appen och webben visar en uppmaning
och motorn skickar en avisering per ny version.
"""
from __future__ import annotations

import os
import re
import threading
import time

REFRESH_S = 6 * 3600
CHANGELOG_URL = "https://github.com/murre87/energywizard/blob/main/ha-addon/smartbox/CHANGELOG.md"
_state: dict = {"at": 0.0, "result": None, "busy": False}
_lock = threading.Lock()


def _addon_info():
    import requests
    tok = os.environ.get("SUPERVISOR_TOKEN")
    r = requests.get("http://supervisor/addons/self/info", headers={"Authorization": f"Bearer {tok}"}, timeout=8)
    r.raise_for_status()
    d = (r.json() or {}).get("data") or {}
    cur, latest = d.get("version"), d.get("version_latest")
    return {"kind": "addon", "running": cur, "latest": latest,
            "outdated": bool(d.get("update_available")) if d.get("update_available") is not None else
            bool(cur and latest and cur != latest)}


def _docker_info(app_version: str):
    import requests
    m = re.fullmatch(r"1\.(\d+)", app_version or "")
    if not m:
        return {"kind": "unknown", "running": app_version or None, "latest": None, "outdated": False}
    r = requests.get("https://api.github.com/repos/murre87/energywizard/actions/workflows/docker.yml/runs",
                     params={"branch": "main", "status": "success", "per_page": 1}, timeout=8,
                     headers={"Accept": "application/vnd.github+json"})
    r.raise_for_status()
    runs = (r.json() or {}).get("workflow_runs") or []
    latest = runs[0].get("run_number") if runs else None
    return {"kind": "docker", "running": app_version, "latest": f"1.{latest}" if latest else None,
            "outdated": bool(latest and int(m.group(1)) < int(latest))}


def _refresh():
    try:
        if os.environ.get("SUPERVISOR_TOKEN"):
            res = _addon_info()
        else:
            res = _docker_info(os.environ.get("APP_VERSION", "").strip())
        res["checked"] = int(time.time())
        res["changelog"] = CHANGELOG_URL
        _state["result"] = res
    except Exception:
        pass                                   # nätet nere eller API:t svarar inte: behåll förra svaret
    finally:
        _state.update(at=time.time(), busy=False)


def status(block: bool = False) -> dict | None:
    """Senaste kända läget, eller None om det inte är känt än. Startar en uppdatering i bakgrunden vid behov."""
    with _lock:
        stale = time.time() - _state["at"] > REFRESH_S
        if stale and not _state["busy"]:
            _state["busy"] = True
            if block:
                _refresh()
            else:
                threading.Thread(target=_refresh, daemon=True, name="ew-update-check").start()
    return _state["result"]


_notified = {"version": None}


def notify_if_new() -> None:
    """Motorn: en avisering per ny version (inte vid varje omstart av samma version)."""
    s = status()
    if not s or not s.get("outdated") or not s.get("latest"):
        return
    try:
        import ew_settings
        if ew_settings.get("update_notified") == s["latest"] or _notified["version"] == s["latest"]:
            return
        import notifier
        how = ("Uppdatera i Home Assistant: Inställningar → Tillägg → EnergyWizard → Uppdatera." if s.get("kind") == "addon"
               else "Hämta den nya bilden (docker compose pull) eller låt Watchtower göra det.")
        notifier.send_emil(f"⬆️ Ny version av EnergyWizard: {s['latest']}",
                           f"Du kör {s.get('running') or 'en äldre version'}. {how} Nyheter och rättningar: {CHANGELOG_URL}",
                           key="system")
        ew_settings.update(update_notified=s["latest"])
        _notified["version"] = s["latest"]
    except Exception:
        pass
