"""smartbox/telemetry.py: strikt opt-in - bevisar att INGET skickas som standard,
att rätt (och bara rätt) fält skickas när det är påslaget, och att ett
sändningsfel aldrig kraschar. Mockar requests helt - rör aldrig nätverket."""
import importlib
from unittest.mock import MagicMock, patch

import pytest


def _reload(monkeypatch, opt_in="", endpoint=""):
    monkeypatch.setenv("TELEMETRY_OPT_IN", opt_in)
    monkeypatch.setenv("TELEMETRY_ENDPOINT", endpoint)
    import telemetry
    return importlib.reload(telemetry)


def test_av_som_standard_skickar_inget(monkeypatch):
    t = _reload(monkeypatch, opt_in="", endpoint="")
    with patch("telemetry.requests.post") as mock_post:
        t.send_driver_snapshot({"house_id": "mitt-hus"})
        t.report_error({"house_id": "mitt-hus"}, "main_loop", "ValueError")
    mock_post.assert_not_called()


def test_paslaget_men_ingen_endpoint_skickar_inget(monkeypatch):
    t = _reload(monkeypatch, opt_in="true", endpoint="")
    with patch("telemetry.requests.post") as mock_post:
        t.send_driver_snapshot({"house_id": "mitt-hus"})
    mock_post.assert_not_called()


def test_driver_snapshot_skickar_bara_tillatna_falt(monkeypatch):
    t = _reload(monkeypatch, opt_in="true", endpoint="https://telemetri.example.com")
    cfg = {
        "house_id": "mitt-hus",
        "solar": {"enabled": True, "driver": "solaredge"},
        "heat_pump": {"enabled": True, "driver": "husdata"},
        "evs": [{"driver": "tesla"}],
    }
    with patch("telemetry.requests.post") as mock_post:
        t.send_driver_snapshot(cfg)
    assert mock_post.call_count == 1
    url, kwargs = mock_post.call_args[0][0], mock_post.call_args[1]
    assert url == "https://telemetri.example.com/ingest/drivers"
    payload = kwargs["json"]
    assert set(payload.keys()) == {"house", "version", "drivers", "ts"}
    assert payload["house"] != "mitt-hus"  # hashat, inte klartext
    assert len(payload["house"]) == 16
    assert set(payload["drivers"]) == {"solar:solaredge", "heatpump:husdata", "car:tesla"}


def test_samma_hus_ger_samma_hash_olika_hus_ger_olika_hash(monkeypatch):
    t = _reload(monkeypatch, opt_in="true", endpoint="https://telemetri.example.com")
    assert t._hashed_house_id("hus-a") == t._hashed_house_id("hus-a")
    assert t._hashed_house_id("hus-a") != t._hashed_house_id("hus-b")


def test_report_error_skickar_bara_tillatna_falt_inte_feltexten(monkeypatch):
    t = _reload(monkeypatch, opt_in="true", endpoint="https://telemetri.example.com")
    with patch("telemetry.requests.post") as mock_post:
        t.report_error({"house_id": "mitt-hus"}, "main_loop", "ValueError")
    payload = mock_post.call_args[1]["json"]
    assert set(payload.keys()) == {"house", "version", "module", "error_type", "ts"}
    assert payload["module"] == "main_loop"
    assert payload["error_type"] == "ValueError"


def test_report_error_avdubblar_inom_24h(monkeypatch):
    t = _reload(monkeypatch, opt_in="true", endpoint="https://telemetri.example.com")
    with patch("telemetry.requests.post") as mock_post:
        t.report_error({"house_id": "h"}, "main_loop", "ValueError")
        t.report_error({"house_id": "h"}, "main_loop", "ValueError")
    assert mock_post.call_count == 1


def test_natverksfel_kraschar_inte(monkeypatch):
    t = _reload(monkeypatch, opt_in="true", endpoint="https://telemetri.example.com")
    with patch("telemetry.requests.post", side_effect=RuntimeError("timeout")):
        t.send_driver_snapshot({"house_id": "h"})
        t.report_error({"house_id": "h"}, "main_loop", "ValueError")
