"""Bil-lås/luckor i webdashboard: eget ew2-omverifieringsflöde (lösenordet igen, 10 min)
innan ett lås-/luckokommando proxas vidare till ewapp. Mockar requests helt - rör aldrig
en riktig Tesla eller Home Assistant. Anropar routfunktionerna direkt (samma mönster som
tests/test_webauth.py) istället för ett ASGI-testklientbibliotek, för att inte dra in ett
nytt testberoende i smartbox/requirements.txt bara för det här."""
import asyncio
import hashlib
import hmac
import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "smartbox"))  # webauth/discovery/house_config/pump


class _FakeRequest:
    def __init__(self, body: dict | None = None, cookies: dict | None = None, ip: str = "10.0.0.5"):
        self._body = body or {}
        self.cookies = cookies or {}
        self.headers = {}
        self.client = type("c", (), {"host": ip})()

    async def json(self):
        return self._body


@pytest.fixture(scope="module")
def wd():
    mp = pytest.MonkeyPatch()
    mp.setenv("DASHBOARD_PASSWORD", "hemligt123")
    import webauth
    mp.setattr(webauth, "PASSWORD", "hemligt123")  # webdashboard läser webauth.PASSWORD direkt vid import, inte miljövariabeln igen
    cwd = Path.cwd()
    os.chdir(ROOT / "webdashboard")  # app.py monterar StaticFiles(directory="static") relativt cwd
    try:
        spec = importlib.util.spec_from_file_location("webdashboard_app", ROOT / "webdashboard" / "app.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules["webdashboard_app"] = mod
        spec.loader.exec_module(mod)
    finally:
        os.chdir(cwd)
    yield mod
    mp.undo()


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


def _run(coro):
    return asyncio.run(coro)


def test_secure_fel_losenord_ger_401(wd):
    req = _FakeRequest({"password": "fel"}, {"ew": _owner_cookie(wd)})
    r = _run(wd.secure(req))
    assert r.status_code == 401


def test_secure_ratt_losenord_satter_ew2_kaka(wd):
    req = _FakeRequest({"password": "hemligt123"}, {"ew": _owner_cookie(wd)})
    r = _run(wd.secure(req))
    assert r.status_code == 200
    assert any(h[0].lower() == b"set-cookie" and b"ew2=" in h[1] for h in r.raw_headers)


def test_secure_for_manga_fel_ger_429(wd):
    ip = "10.0.0.9"
    for _ in range(5):
        _run(wd.secure(_FakeRequest({"password": "fel"}, {"ew": _owner_cookie(wd)}, ip=ip)))
    r = _run(wd.secure(_FakeRequest({"password": "hemligt123"}, {"ew": _owner_cookie(wd)}, ip=ip)))
    assert r.status_code == 429
    wd._secure_fails.pop(ip, None)


def test_lock_kraver_inte_secure(wd):
    req = _FakeRequest({"what": "lock"}, {"ew": _owner_cookie(wd)})
    with patch("webdashboard_app.requests.post", return_value=_resp(json_data={"ok": True, "msg": "Bilen låst"})):
        r = _run(wd.proxy_tesla_access(req))
    assert r.status_code == 200


def test_unlock_utan_ew2_ger_403_secure(wd):
    req = _FakeRequest({"what": "unlock"}, {"ew": _owner_cookie(wd)})
    r = _run(wd.proxy_tesla_access(req))
    assert r.status_code == 403
    assert json.loads(r.body)["detail"] == "secure"


def test_unlock_med_giltig_ew2_proxas_till_ewapp(wd):
    ew2 = _ew2_cookie(wd)
    req = _FakeRequest({"what": "unlock"}, {"ew": _owner_cookie(wd), "ew2": ew2})
    with patch("webdashboard_app.requests.post", return_value=_resp(json_data={"ok": True, "msg": "Bilen upplåst"})) as mock_post:
        r = _run(wd.proxy_tesla_access(req))
    assert r.status_code == 200
    _, kwargs = mock_post.call_args
    assert kwargs["cookies"]["ew2"] == ew2


def test_unlock_med_utganget_ew2_ger_403_secure(wd):
    req = _FakeRequest({"what": "unlock"}, {"ew": _owner_cookie(wd), "ew2": _ew2_cookie(wd, exp_delta=-10)})
    r = _run(wd.proxy_tesla_access(req))
    assert r.status_code == 403


def test_okand_atgard_ger_400(wd):
    req = _FakeRequest({"what": "nedbrand"}, {"ew": _owner_cookie(wd)})
    r = _run(wd.proxy_tesla_access(req))
    assert r.status_code == 400


def test_access_state_plockar_ut_tesla(wd):
    full_state = {"cars": [
        {"key": "nissan", "access": None},
        {"key": "tesla", "access": {"locked": True, "trunk": False, "frunk": False}},
    ]}
    with patch("webdashboard_app.requests.get", return_value=_resp(json_data=full_state)):
        r = _run(wd.tesla_access_state())
    assert r["access"]["locked"] is True


def test_ingen_session_nekas_av_delade_guard(wd):
    """Själva routfunktionen antar att middlewaren redan stoppat obehöriga - det
    generiska skyddet testas redan i tests/test_webauth.py. Bevisar här bara att
    webdashboards guard faktiskt täcker /api/tesla/access-sökvägen."""
    req = _FakeRequest()
    req.url = type("u", (), {"path": "/api/tesla/access"})()
    req.method = "POST"
    err = wd.AUTH.guard_response(req)
    assert err is not None
    assert err.status_code == 401
