"""#265: TELEMETRY_ADMIN_USERS får se flottvyn utan owner-roll."""
import importlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "webdashboard"))
sys.path.insert(0, str(ROOT / "smartbox"))


def _reload_app(**env):
    for k, v in list(os.environ.items()):
        if k.startswith("TELEMETRY_"):
            os.environ.pop(k, None)
    os.environ.update({k: v for k, v in env.items() if v is not None})
    # Minimera import-side effects: app.py kräver DB-env
    os.environ.setdefault("POSTGRES_USER", "u")
    os.environ.setdefault("POSTGRES_PASSWORD", "p")
    os.environ.setdefault("POSTGRES_DB", "d")
    if "app" in sys.modules:
        del sys.modules["app"]
    return importlib.import_module("app")


def test_owner_sees_installs_when_stats_url_set():
    mod = _reload_app(TELEMETRY_STATS_URL="http://collector/api/stats", TELEMETRY_ADMIN_USERS="")
    assert mod._can_view_installs("owner", "owner")
    assert not mod._can_view_installs("family", "elin")


def test_allowlisted_family_sees_installs():
    mod = _reload_app(
        TELEMETRY_STATS_URL="http://collector/api/stats",
        TELEMETRY_ADMIN_USERS="lazgeo, other",
    )
    assert mod._can_view_installs("family", "lazgeo")
    assert mod._can_view_installs("family", "LAZGEO")
    assert not mod._can_view_installs("family", "elin")
    assert not mod._can_view_installs("guest", "lazgeo")


def test_no_stats_url_nobody_sees_installs():
    mod = _reload_app(TELEMETRY_STATS_URL="", TELEMETRY_ADMIN_USERS="lazgeo")
    assert not mod._can_view_installs("owner", "owner")
    assert not mod._can_view_installs("family", "lazgeo")
