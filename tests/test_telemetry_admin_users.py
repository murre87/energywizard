"""#265: TELEMETRY_ADMIN_USERS får se flottvyn utan owner-roll — och bara den."""
import importlib
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

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
