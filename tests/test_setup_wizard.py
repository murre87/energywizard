"""Startguiden i webben: första lösenordet, anslutningen till Home Assistant och att inget
öppnas igen när det väl är satt. Ingen riktig HA anropas."""
import asyncio
import importlib
import importlib.util
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "smartbox"))


class _Req:
    def __init__(self, body=None, cookies=None):
        self._body = body or {}
        self.cookies = cookies or {}
        self.headers = {}
        self.client = type("c", (), {"host": "10.0.0.9"})()
        self.url = type("u", (), {"path": "/api/setup/status"})()

    async def json(self):
        return self._body


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Ny installation: inget lösenord, ingen HA i miljön, inställningar i en tom mapp."""
    import ew_settings, homeassistant, webauth
    monkeypatch.setattr(ew_settings, "PATH", str(tmp_path / "energywizard.json"))
    ew_settings._cache.update(mtime=None, data={})
    monkeypatch.setattr(webauth, "PASSWORD", "")
    monkeypatch.setattr(homeassistant, "SUPERVISOR_TOKEN", None)
    monkeypatch.setattr(homeassistant, "_ENV_URL", "")
    monkeypatch.setattr(homeassistant, "_ENV_TOKEN", "")
    monkeypatch.setattr(homeassistant, "HA_IP", None)
    homeassistant.reconfigure()
    cwd = Path.cwd()
    os.chdir(ROOT / "webdashboard")
    try:
        spec = importlib.util.spec_from_file_location("webdashboard_app_setup", ROOT / "webdashboard" / "app.py")
        wd = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(wd)
    finally:
        os.chdir(cwd)
    hc = tmp_path / "house_config.yaml"
    hc.write_text('house_id: "nytt"\n')
    monkeypatch.setattr(wd, "HOUSE_CONFIG_FILE", str(hc))
    yield wd, ew_settings, homeassistant, webauth
    homeassistant.reconfigure()


def _run(c):
    return asyncio.run(c)


def test_p1_phase_power_mapping_survives_generated_yaml(env):
    import yaml
    from house_config import power_meter_entities
    wd, *_ = env
    entities = {f"{direction}_l{ph}_w": f"sensor.momentary_active_{direction}_phase_{ph}"
                for direction in ("import", "export") for ph in (1, 2, 3)}
    entities.update({f"current_l{ph}": f"sensor.current_phase_{ph}" for ph in (1, 2, 3)})
    cfg = yaml.safe_load(wd._build_house_config_yaml({"power_meter": {"driver": "power_w", "entities": entities}}))
    assert power_meter_entities(cfg) == entities


def test_ny_installation_visar_vad_som_saknas(env):
    wd, *_ = env
    st = _run(wd.api_setup_status(_Req()))
    assert st == {"needs_password": True, "supervisor": False, "ha_ok": False, "devices_chosen": False}


def test_forsta_losenordet_loggar_in_och_kan_inte_sattas_igen(env):
    wd, ew_settings, _, webauth = env
    r = _run(wd.api_setup_password(_Req({"password": "kort"})))
    assert r.status_code == 400
    r = _run(wd.api_setup_password(_Req({"password": "hemligt123"})))
    assert r.status_code == 200 and f"{wd.AUTH.cookie}=" in r.headers.get("set-cookie", "")
    assert webauth.owner_password() == "hemligt123"
    assert oct(os.stat(ew_settings.PATH).st_mode & 0o777) == "0o600"
    # Ingen annan på nätet kan byta det efteråt
    r = _run(wd.api_setup_password(_Req({"password": "annat-losen"})))
    assert r.status_code == 409 and webauth.owner_password() == "hemligt123"


def test_losenordet_galler_direkt_for_inloggning(env):
    wd, ew_settings, _, _ = env
    ew_settings.update(dashboard_password="hemligt123")
    r = _run(wd.AUTH.login(_Req({"password": "hemligt123"})))
    assert r.status_code == 200
    with pytest.raises(Exception):
        _run(wd.AUTH.login(_Req({"password": "fel"})))


def test_status_ar_oppen_men_ha_kraver_agaren(env):
    wd, ew_settings, *_ = env
    import webauth
    assert "/api/setup/status" in webauth.OPEN_PATHS and "/api/setup/ha" not in webauth.OPEN_PATHS
    ew_settings.update(dashboard_password="hemligt123")
    r = _run(wd.api_setup_ha(_Req({"url": "1.2.3.4", "token": "x"})))
    assert r.status_code == 403


def _owner(wd):
    return {wd.AUTH.cookie: wd.AUTH.sign(int(time.time()) + 3600, "owner", "owner")}


def test_ha_testas_innan_det_sparas(env):
    wd, ew_settings, homeassistant, _ = env
    ew_settings.update(dashboard_password="hemligt123")
    with patch.object(homeassistant, "test_connection", return_value=(False, "Fick inget svar")):
        r = _run(wd.api_setup_ha(_Req({"url": "192.168.1.10", "token": "tok"}, _owner(wd))))
    assert r.status_code == 400 and "ha_url" not in ew_settings.load()
    with patch.object(homeassistant, "test_connection", return_value=(True, "Kontakt")):
        r = _run(wd.api_setup_ha(_Req({"url": "192.168.1.10", "token": "tok"}, _owner(wd))))
    assert r["ok"] is True
    assert ew_settings.get("ha_url") == "http://192.168.1.10:8123"
    assert homeassistant._BASE == "http://192.168.1.10:8123/api" and homeassistant.configured()
    st = _run(wd.api_setup_status(_Req(cookies=_owner(wd))))
    assert st["ha_ok"] and st["ha_url"] == "http://192.168.1.10:8123" and not st["ha_from_env"]


def test_miljovariabler_gar_fore(env, monkeypatch):
    wd, ew_settings, homeassistant, _ = env
    ew_settings.update(dashboard_password="hemligt123", ha_url="http://fel:8123", ha_token="t")
    monkeypatch.setattr(homeassistant, "_ENV_URL", "http://ratt:8123")
    monkeypatch.setattr(homeassistant, "_ENV_TOKEN", "envtok")
    homeassistant.reconfigure()
    assert homeassistant._BASE == "http://ratt:8123/api"
    r = _run(wd.api_setup_ha(_Req({"url": "x", "token": "y"}, _owner(wd))))
    assert r.status_code == 409


def test_test_connection_ger_begripliga_svar():
    import homeassistant
    import requests

    class R:
        def __init__(self, code):
            self.status_code = code
    with patch("homeassistant.requests.get", return_value=R(200)):
        assert homeassistant.test_connection("10.0.0.2", "t")[0] is True
    with patch("homeassistant.requests.get", return_value=R(401)):
        ok, msg = homeassistant.test_connection("10.0.0.2", "t")
        assert not ok and "token" in msg
    with patch("homeassistant.requests.get", side_effect=requests.exceptions.ConnectionError()):
        ok, msg = homeassistant.test_connection("10.0.0.2", "t")
        assert not ok and "svar" in msg
