"""smartbox/telemetry.py: PÅ som standard - bevisar att det skickas utan att
något måste sättas i .env, att TELEMETRY_OPT_IN=false stänger av helt, att
rätt (och bara rätt) fält skickas, och att ett sändningsfel aldrig kraschar.
Mockar requests helt - rör aldrig nätverket."""
import importlib
from unittest.mock import MagicMock, patch

import pytest


def _reload(monkeypatch, opt_in=None, endpoint=None):
    """opt_in/endpoint=None -> miljövariabeln är helt osatt (testar det faktiska
    standardläget, inte en tom sträng som betyder något annat i koden)."""
    if opt_in is None:
        monkeypatch.delenv("TELEMETRY_OPT_IN", raising=False)
    else:
        monkeypatch.setenv("TELEMETRY_OPT_IN", opt_in)
    if endpoint is None:
        monkeypatch.delenv("TELEMETRY_ENDPOINT", raising=False)
    else:
        monkeypatch.setenv("TELEMETRY_ENDPOINT", endpoint)
    import telemetry
    return importlib.reload(telemetry)


def test_pa_som_standard_utan_nagon_env_variabel(monkeypatch):
    t = _reload(monkeypatch)
    assert t.OPT_IN is True
    assert t.ENDPOINT == "https://energywizzard.profitalgos.com/telemetry"
    with patch("telemetry.requests.post") as mock_post:
        t.send_driver_snapshot({"house_id": "mitt-hus"})
    mock_post.assert_called_once()


def test_opt_in_false_stanger_av_helt(monkeypatch):
    t = _reload(monkeypatch, opt_in="false")
    with patch("telemetry.requests.post") as mock_post:
        t.send_driver_snapshot({"house_id": "mitt-hus"})
        t.report_error({"house_id": "mitt-hus"}, "main_loop", "ValueError")
    mock_post.assert_not_called()


def test_tom_endpoint_skickar_inget_aven_om_pa(monkeypatch):
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
