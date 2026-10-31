"""Bil-lås/luckor i webdashboard: eget ew2-omverifieringsflöde (lösenordet igen, 10 min)
innan ett lås-/luckokommando proxas vidare till ewapp. Mockar requests helt - rör aldrig
en riktig Tesla eller Home Assistant. Importerar webdashboard/app.py direkt via dess
filväg (modulen heter inget annat webdashboard-test importerar redan)."""
import hashlib
import hmac
import importlib.util
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "smartbox"))  # webauth/discovery/house_config/pump


@pytest.fixture(scope="module")
def wd():
    mp = pytest.MonkeyPatch()
    mp.setenv("DASHBOARD_PASSWORD", "hemligt123")
    import webauth
    mp.setattr(webauth, "PASSWORD", "hemligt123")  # webdashboard läser webauth.PASSWORD direkt vid import, inte miljövariabeln igen
    cwd = Path.cwd()
    os_chdir = __import__("os").chdir
    os_chdir(ROOT / "webdashboard")  # app.py monterar StaticFiles(directory="static") relativt cwd
    try:
        spec = importlib.util.spec_from_file_location("webdashboard_app", ROOT / "webdashboard" / "app.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules["webdashboard_app"] = mod
        spec.loader.exec_module(mod)
    finally:
        os_chdir(cwd)
    yield mod
    mp.undo()


@pytest.fixture()
def client(wd):
    from fastapi.testclient import TestClient
    return TestClient(wd.app)


def _owner_cookie(wd):
    exp = int(time.time()) + 3600
    return wd.AUTH.sign(exp, "owner", "owner")


def _ew2_cookie(wd, exp_delta=600):
    exp = int(time.time()) + exp_delta
    sig = hmac.new(wd._EWAPP_SECRET, ("sec" + str(exp)).encode(), hashlib.sha256).hexdigest()
    return f"{exp}.{sig}"


def _resp(status_code=200, json_data=None):
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = json_data if json_data is not None else {"ok": True}
    r.raise_for_status = MagicMock()
    if status_code >= 400:
        r.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    return r


def test_secure_fel_losenord_ger_401(wd, client):
    client.cookies.set("ew", _owner_cookie(wd))
    r = client.post("/api/secure", json={"password": "fel"})
    assert r.status_code == 401


def test_secure_ratt_losenord_satter_ew2_kaka(wd, client):
    client.cookies.set("ew", _owner_cookie(wd))
    r = client.post("/api/secure", json={"password": "hemligt123"})
    assert r.status_code == 200
    assert "ew2=" in r.headers.get("set-cookie", "")


def test_lock_kraver_inte_secure(wd, client):
    client.cookies.set("ew", _owner_cookie(wd))
    with patch("webdashboard_app.requests.post", return_value=_resp(json_data={"ok": True, "msg": "Bilen låst"})):
        r = client.post("/api/tesla/access", json={"what": "lock"})
    assert r.status_code == 200


def test_unlock_utan_ew2_ger_403_secure(wd, client):
    client.cookies.set("ew", _owner_cookie(wd))
    client.cookies.delete("ew2")
    r = client.post("/api/tesla/access", json={"what": "unlock"})
    assert r.status_code == 403
    assert r.json()["detail"] == "secure"


def test_unlock_med_giltig_ew2_proxas_till_ewapp(wd, client):
    client.cookies.set("ew", _owner_cookie(wd))
    client.cookies.set("ew2", _ew2_cookie(wd))
    with patch("webdashboard_app.requests.post", return_value=_resp(json_data={"ok": True, "msg": "Bilen upplåst"})) as mock_post:
        r = client.post("/api/tesla/access", json={"what": "unlock"})
    assert r.status_code == 200
    assert r.json()["msg"] == "Bilen upplåst"
    _, kwargs = mock_post.call_args
    assert kwargs["cookies"]["ew2"] == _ew2_cookie(wd) or "ew2" in kwargs["cookies"]


def test_unlock_med_utganget_ew2_ger_403_secure(wd, client):
    client.cookies.set("ew", _owner_cookie(wd))
    client.cookies.set("ew2", _ew2_cookie(wd, exp_delta=-10))
    r = client.post("/api/tesla/access", json={"what": "unlock"})
    assert r.status_code == 403


def test_okand_atgard_ger_400(wd, client):
    client.cookies.set("ew", _owner_cookie(wd))
    r = client.post("/api/tesla/access", json={"what": "nedbrand"})
    assert r.status_code == 400


def test_ingen_session_ger_401(wd, client):
    client.cookies.clear()
    r = client.post("/api/tesla/access", json={"what": "lock"})
    assert r.status_code == 401


def test_access_state_plockar_ut_tesla(wd, client):
    client.cookies.set("ew", _owner_cookie(wd))
    full_state = {"cars": [
        {"key": "nissan", "access": None},
        {"key": "tesla", "access": {"locked": True, "trunk": False, "frunk": False}},
    ]}
    with patch("webdashboard_app.requests.get", return_value=_resp(json_data=full_state)):
        r = client.get("/api/tesla/access-state")
    assert r.status_code == 200
    assert r.json()["access"]["locked"] is True
