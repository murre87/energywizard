"""#265: TELEMETRY_ADMIN_USERS får se flottvyn utan owner-roll — och bara den."""
import importlib
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock
import time
import pytest
import asyncio
import json

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "webdashboard"))
sys.path.insert(0, str(ROOT / "smartbox"))


def _reload_app(**env):
    for k in list(os.environ):
        if k.startswith("TELEMETRY_"):
            os.environ.pop(k, None)
    os.environ.update({k: v for k, v in env.items() if v is not None})
    os.environ.setdefault("POSTGRES_USER", "u")
    os.environ.setdefault("POSTGRES_PASSWORD", "p")
    os.environ.setdefault("POSTGRES_DB", "d")
    if "app" in sys.modules:
        del sys.modules["app"]
    # app.py monterar ./static relativt cwd
    cwd = os.getcwd()
    os.chdir(ROOT / "webdashboard")
    try:
        return importlib.import_module("app")
    finally:
        os.chdir(cwd)


def test_owner_sees_installs_when_stats_url_set():
    mod = _reload_app(TELEMETRY_STATS_URL="http://collector/api/stats", TELEMETRY_ADMIN_USERS="")
    assert mod._can_view_installs("owner", "owner")
    assert not mod._can_view_installs("family", "elin")
    assert not mod._is_fleet_admin("owner", "owner")


def test_allowlisted_family_sees_installs():
    mod = _reload_app(
        TELEMETRY_STATS_URL="http://collector/api/stats",
        TELEMETRY_ADMIN_USERS="lazgeo, other",
    )
    assert mod._can_view_installs("family", "lazgeo")
    assert mod._can_view_installs("family", "LAZGEO")
    assert mod._is_fleet_admin("family", "lazgeo")
    assert not mod._can_view_installs("family", "elin")
    assert not mod._can_view_installs("guest", "lazgeo")
    assert not mod._is_fleet_admin("owner", "lazgeo")


def test_no_stats_url_nobody_sees_installs():
    mod = _reload_app(TELEMETRY_STATS_URL="", TELEMETRY_ADMIN_USERS="lazgeo")
    assert not mod._can_view_installs("owner", "owner")
    assert not mod._can_view_installs("family", "lazgeo")
    assert not mod._is_fleet_admin("family", "lazgeo")


def test_fleet_admin_me_only_installationer(monkeypatch):
    import asyncio
    import nordpool

    mod = _reload_app(
        TELEMETRY_STATS_URL="http://collector/api/stats",
        TELEMETRY_ADMIN_USERS="lazgeo",
    )
    monkeypatch.setattr(mod.AUTH, "session", lambda _r: ("family", "lazgeo"))
    monkeypatch.setattr(nordpool, "cost_settings", lambda: {"currency": "SEK", "symbol": "kr"})
    out = asyncio.run(mod.me(MagicMock()))
    assert out["mode"] == "fleet"
    assert out["default_page"] == "installationer"
    assert [p["id"] for p in out["pages"]] == ["installationer"]


def test_fleet_admin_api_allowlist():
    mod = _reload_app(
        TELEMETRY_STATS_URL="http://collector/api/stats",
        TELEMETRY_ADMIN_USERS="lazgeo",
    )
    assert "/api/installs" in mod.FLEET_ADMIN_API
    assert "/api/overview" not in mod.FLEET_ADMIN_API
    assert "/api/me" in mod.FLEET_ADMIN_API


def _http_client(monkeypatch, role="family", user="lazgeo"):
    import webauth
    import nordpool

    monkeypatch.setattr(webauth, "owner_password", lambda: "test-only-owner-password")
    mod = _reload_app(TELEMETRY_STATS_URL="http://collector.invalid/api/stats",
                      TELEMETRY_STATS_TOKEN="test-only-stats-token", TELEMETRY_ADMIN_USERS="lazgeo")
    monkeypatch.setattr(mod.house_config, "load_house_config", lambda *_a: {})
    monkeypatch.setattr(nordpool, "cost_settings", lambda: {"currency": "SEK", "symbol": "kr"})
    response = MagicMock()
    response.json.return_value = {"active": 2, "error_groups": [{"key": "poll: Error", "houses": 1}]}
    get = MagicMock(return_value=response)
    monkeypatch.setattr(mod.requests, "get", get)
    cookie = mod.AUTH.sign(int(time.time()) + 60, role, user)
    def request(method, path):
        # Call the complete ASGI application using only the standard library.
        # Root CI does not install Starlette's optional HTTP test client.
        async def run():
            sent = []
            received = False

            async def receive():
                nonlocal received
                if not received:
                    received = True
                    return {"type": "http.request", "body": b"", "more_body": False}
                await asyncio.Future()

            async def send(message):
                sent.append(message)

            scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
                     "http_version": "1.1", "method": method, "scheme": "http",
                     "path": path, "raw_path": path.encode(), "query_string": b"", "root_path": "",
                     "headers": [(b"host", b"testserver"),
                                 (b"cookie", f"{mod.AUTH.cookie}={cookie}".encode())],
                     "client": ("127.0.0.1", 12345), "server": ("testserver", 80)}
            await mod.app(scope, receive, send)
            status = next(m["status"] for m in sent if m["type"] == "http.response.start")
            body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
            return status, body.decode()

        return asyncio.run(run())

    return request, get


@pytest.mark.parametrize("method,path", [
    ("GET", "/api/overview"), ("GET", "/api/historylog"),
    ("GET", "/api/house-config-status"), ("POST", "/api/shadow"),
])
def test_fleet_account_cannot_reach_house_endpoints(monkeypatch, method, path):
    request, get = _http_client(monkeypatch)
    status, _body = request(method, path)
    assert status == 403
    get.assert_not_called()


@pytest.mark.parametrize("role,user,allowed", [
    ("family", "lazgeo", True), ("owner", "owner", True),
    ("family", "other", False), ("guest", "lazgeo", False),
])
def test_fleet_data_requires_authorized_signed_session(monkeypatch, role, user, allowed):
    request, get = _http_client(monkeypatch, role, user)
    status, body = request("GET", "/api/installs")
    assert status == 200
    payload = json.loads(body)
    assert payload["ok"] is allowed
    if allowed:
        get.assert_called_once()
        assert get.call_args.args == ("http://collector.invalid/api/stats",)
        assert get.call_args.kwargs["headers"] == {"X-Stats-Token": "test-only-stats-token"}
        assert payload["active"] == 2
    else:
        get.assert_not_called()
    assert "test-only-stats-token" not in body
    assert "test-only-owner-password" not in body
