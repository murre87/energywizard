"""Bevisar: nytt hus -> ett mejl. Samma hus igen -> inget mejl. Mejl av om
SMTP_HOST/ALERT_EMAIL_TO saknas (standardläget). Mockar smtplib helt - rör
aldrig ett riktigt SMTP-nät."""
import importlib
import os
import tempfile
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


def _client(monkeypatch, smtp_host="", alert_to=""):
    db_fd, db_path = tempfile.mkstemp()
    os.close(db_fd)
    os.remove(db_path)
    monkeypatch.setenv("TELEMETRY_DB_PATH", db_path)
    monkeypatch.setenv("SMTP_HOST", smtp_host)
    monkeypatch.setenv("ALERT_EMAIL_TO", alert_to)
    import app as collector_app
    importlib.reload(collector_app)
    return TestClient(collector_app.app), collector_app


def test_nytt_hus_skickar_ett_mejl(monkeypatch):
    client, mod = _client(monkeypatch, smtp_host="smtp.example.com", alert_to="emil@example.com")
    with patch("app.smtplib.SMTP") as mock_smtp:
        instance = MagicMock()
        mock_smtp.return_value.__enter__.return_value = instance
        r = client.post("/ingest/drivers", json={"house": "abc123", "version": "x", "drivers": []})
    assert r.status_code == 200
    instance.send_message.assert_called_once()


def test_samma_hus_igen_skickar_inget_mejl(monkeypatch):
    client, mod = _client(monkeypatch, smtp_host="smtp.example.com", alert_to="emil@example.com")
    with patch("app.smtplib.SMTP") as mock_smtp:
        instance = MagicMock()
        mock_smtp.return_value.__enter__.return_value = instance
        client.post("/ingest/drivers", json={"house": "abc123", "version": "x", "drivers": []})
        client.post("/ingest/drivers", json={"house": "abc123", "version": "x", "drivers": []})
    assert instance.send_message.call_count == 1


def test_av_utan_smtp_konfiguration(monkeypatch):
    client, mod = _client(monkeypatch, smtp_host="", alert_to="")
    with patch("app.smtplib.SMTP") as mock_smtp:
        client.post("/ingest/drivers", json={"house": "nytt-hus", "version": "x", "drivers": []})
    mock_smtp.assert_not_called()


def test_mejlfel_kraschar_inte_ingest(monkeypatch):
    client, mod = _client(monkeypatch, smtp_host="smtp.example.com", alert_to="emil@example.com")
    with patch("app.smtplib.SMTP", side_effect=RuntimeError("timeout")):
        r = client.post("/ingest/drivers", json={"house": "hus-x", "version": "x", "drivers": []})
    assert r.status_code == 200


def test_stats_raknar_aktiva_och_utrustning_utan_husidentiteter(monkeypatch):
    client, _ = _client(monkeypatch)
    a, b = "0123456789abcdef", "fedcba9876543210"
    client.post("/ingest/drivers", json={"house": a, "version": "v1", "drivers": ["heatpump:thermia_husdata", "battery:generic@FoxESS"]})
    client.post("/ingest/drivers", json={"house": a, "version": "v2", "drivers": ["heatpump:thermia_husdata", "battery:generic@FoxESS"]})
    client.post("/ingest/drivers", json={"house": b, "version": "v2", "drivers": ["battery:generic@FoxESS", "car:tesla"]})
    client.post("/ingest/drivers", json={"house": "testverify", "version": "x", "drivers": ["car:nissan"]})
    s = client.get("/api/stats").json()
    assert s["active"] == 2 and s["total_known"] == 2 and s["new_last_7d"] == 2
    assert s["equipment"]["battery"] == {"generic@FoxESS": 2}
    client.post("/ingest/drivers", json={"house": b, "version": "v2", "drivers": ["charger:easee", "charger:easee", "car:tesla"]})
    assert client.get("/api/stats").json()["equipment"]["charger"] == {"easee": 2}
    assert s["equipment"]["heatpump"] == {"thermia_husdata": 1} and "nissan" not in str(s)
    assert s["versions"] == {"v2": 2}
    assert a not in str(s) and b not in str(s)


def test_statistiken_kraver_nyckel_nar_den_ar_satt(monkeypatch):
    monkeypatch.setenv("STATS_TOKEN", "hemlig")
    client, _ = _client(monkeypatch)
    assert client.get("/api/stats").status_code == 403
    assert client.get("/api/recent").status_code == 403
    assert client.get("/api/stats", headers={"X-Stats-Token": "fel"}).status_code == 403
    assert client.get("/api/stats", headers={"X-Stats-Token": "hemlig"}).status_code == 200
    monkeypatch.delenv("STATS_TOKEN")


def test_per_installation_anonymt_och_easee_ihop(monkeypatch):
    client, _ = _client(monkeypatch)
    a, b = "0123456789abcdef", "fedcba9876543210"
    client.post("/ingest/drivers", json={"house": a, "version": "v", "drivers": ["charger:easee", "charger:easee", "car:tesla@Tesla"]})
    client.post("/ingest/drivers", json={"house": b, "version": "v", "drivers": ["charger:easee@Easee", "battery:generic@Solis"]})
    s = client.get("/api/stats", params={"me": a}).json()
    assert s["equipment"]["charger"] == {"easee": 3}
    assert [h["label"] for h in s["houses"]] == ["Hus 1", "Hus 2"] and s["houses"][0]["mine"] and not s["houses"][1]["mine"]
    assert s["houses"][1]["devices"]["battery"] == ["generic@Solis"]
    assert a not in str(s) and b not in str(s)


def test_error_groups_grupperar_utan_hus(monkeypatch):
    monkeypatch.setenv("STATS_TOKEN", "hemlig")
    c, mod = _client(monkeypatch)
    for h in ("a" * 16, "b" * 16, "a" * 16):
        c.post("/ingest/error", json={"house": h, "version": "1.50", "module": "logger.log_data", "error_type": "UndefinedColumn"})
    c.post("/ingest/drivers", json={"house": "a" * 16, "version": "1.50", "drivers": ["battery:generic@Solis"]})
    assert c.get("/api/error-groups").status_code == 403
    g = c.get("/api/error-groups", headers={"X-Stats-Token": "hemlig"}).json()["groups"]
    assert g[0]["key"] == "logger.log_data: UndefinedColumn" and g[0]["houses"] == 2 and g[0]["reports"] == 3
    assert g[0]["versions"] == ["1.50"]
    assert "a" * 16 not in str(g)
    s = c.get("/api/stats", headers={"X-Stats-Token": "hemlig"}).json()
    assert s["error_groups"][0]["versions"] == ["1.50"]
    assert s["houses"][0]["errors"] == ["logger.log_data: UndefinedColumn"] and s["houses"][0]["version"] == "1.50"


def test_installationer_visar_bara_fel_som_kvarstar(monkeypatch):
    """Fel som upphört (inte rapporterat på 75 min) eller hör till en äldre version visas inte."""
    import sqlite3
    from datetime import datetime, timedelta, timezone
    c, mod = _client(monkeypatch)
    h = "c" * 16
    c.post("/ingest/error", json={"house": h, "version": "1.0", "module": "gammal", "error_type": "RattadISenare"})
    c.post("/ingest/error", json={"house": h, "version": "2.0", "module": "nu", "error_type": "Kvarstar"})
    c.post("/ingest/error", json={"house": h, "version": "2.0", "module": "forr", "error_type": "Upphort"})
    c.post("/ingest/drivers", json={"house": h, "version": "2.0", "drivers": ["battery:generic@Solis"]})
    old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    with sqlite3.connect(mod.DB_PATH) as db:
        db.execute("UPDATE errors SET received_at = ? WHERE module = 'forr'", (old,))
    s = c.get("/api/stats").json()
    assert s["houses"][0]["errors"] == ["nu: Kvarstar"]
