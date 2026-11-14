"""Owner-only read access and sanitized monitor status across API/storage."""
from contextlib import contextmanager
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
from unittest.mock import Mock

import psycopg
import pytest
from sqlalchemy import create_engine
import hot_water_monitor as monitor

NOW = datetime(2026, 11, 14, 10, tzinfo=timezone.utc).timestamp()


@pytest.fixture
def web(monkeypatch, tmp_path):
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("hot_water_status_web", root / "webdashboard" / "app.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.chdir(root / "webdashboard")
    spec.loader.exec_module(module)
    config = tmp_path / "house.yaml"
    config.write_text("heat_pump:\n  enabled: true\n  driver: nibe_local\n  connection: {password: secret}\n  hot_water_shadow: {enabled: true}\n")
    monkeypatch.setattr(module, "HOUSE_CONFIG_FILE", str(config))
    monkeypatch.setattr(module.AUTH, "session", lambda req: ("owner", "owner"))
    return module


def test_denied_roles_cannot_read_configuration_or_status(web, monkeypatch):
    connect = Mock()
    monkeypatch.setattr(web.ENGINE, "connect", connect)
    load = Mock(side_effect=AssertionError("Unauthorized configuration read"))
    monkeypatch.setattr(web.house_config, "load_house_config", load)
    for role in (None, "guest", "family"):
        monkeypatch.setattr(web.AUTH, "session", lambda req, role=role: (role, "user"))
        assert web.api_hot_water_shadow_status(Mock()).status_code == 403
    connect.assert_not_called()
    load.assert_not_called()


def test_disabled_monitor_stays_hidden_without_database_access(web, monkeypatch):
    monkeypatch.setattr(web.house_config, "load_house_config", lambda path: {})
    connect = Mock()
    monkeypatch.setattr(web.ENGINE, "connect", connect)
    result = web.api_hot_water_shadow_status(Mock())
    assert result["enabled"] is False
    connect.assert_not_called()


def test_config_or_database_failure_returns_unknown_without_raw_details(web, monkeypatch):
    monkeypatch.setattr(web.ENGINE, "connect", Mock(side_effect=OSError("secret address and token")))
    result = web.api_hot_water_shadow_status(Mock())
    assert result["enabled"] is True and result["status"]["state"] == "unknown"
    assert "secret" not in json.dumps(result)
    monkeypatch.setattr(web.house_config, "load_house_config", Mock(side_effect=OSError("private path")))
    result = web.api_hot_water_shadow_status(Mock())
    assert result["enabled"] is None and "private" not in json.dumps(result)


def test_actual_publication_read_and_api_exclude_private_fields(db, web, monkeypatch):
    import logger
    @contextmanager
    def connection():
        with db.transaction():
            yield db
    monkeypatch.setattr(logger, "get_db", connection)
    db.execute("CREATE TABLE IF NOT EXISTS overrides(device text PRIMARY KEY,mode text,updated_at timestamptz DEFAULT NOW())")
    report = {"schema": 1, "state": "proposed", "simulation_only": True, "control_ready": False,
              "reservation_applied": False, "guard_qualified": False, "reported_at": NOW,
              "start": "2026-11-14T10:00:00Z", "end": "2026-11-14T10:15:00Z",
              "deadline": "2026-11-14T11:00:00Z", "energy_kwh": .5, "estimated_import_cost": 1,
              "raw_error": "secret", "endpoint": "private"}
    monitor.publish(report)
    engine = create_engine("postgresql+psycopg://", creator=lambda: psycopg.connect(db.info.dsn, password=os.environ["POSTGRES_PASSWORD"]))
    monkeypatch.setattr(web, "ENGINE", engine)
    import time
    monkeypatch.setattr(time, "time", lambda: NOW+10)
    try:
        result = web.api_hot_water_shadow_status(Mock())
        assert result["enabled"] and result["status"]["fresh"]
        assert result["status"]["state"] == "proposed" and result["status"]["energy_kwh"] == .5
        assert "secret" not in json.dumps(result) and "private" not in json.dumps(result)
        monkeypatch.setattr(time, "time", lambda: NOW+91)
        assert web.api_hot_water_shadow_status(Mock())["status"]["state"] == "unknown"
    finally:
        engine.dispose()
        db.execute("DELETE FROM overrides WHERE device=%s", (monitor.DEVICE,))
