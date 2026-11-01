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
