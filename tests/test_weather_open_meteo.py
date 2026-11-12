"""Open-Meteo: nätverksfel och trasigt svar är varning, inte programfel."""
from unittest.mock import MagicMock

import requests

import weather


def _hourly():
    return {
        "time": ["2026-06-29T14:00"],
        "temperature_2m": [18.0],
        "cloudcover": [40],
        "windspeed_10m": [3.0],
        "winddirection_10m": [180],
        "precipitation": [0.0],
        "precipitation_probability": [10],
        "weathercode": [1],
    }


def test_avbrott_och_trasigt_svar_ar_varning(monkeypatch, capsys):
    monkeypatch.setattr(weather, "_add_precip_column", lambda: None)
    errors = [
        requests.Timeout("timed out"),
        requests.ConnectionError("reset"),
        requests.exceptions.ChunkedEncodingError("connection broken"),
        requests.exceptions.JSONDecodeError("Expecting value", "<html>", 0),
    ]

    def get(*_a, **_k):
        err = errors.pop(0)
        if isinstance(err, requests.exceptions.JSONDecodeError):
            response = MagicMock()
            response.status_code = 200
            response.json.side_effect = err
            return response
        raise err

    monkeypatch.setattr(weather.requests, "get", get)
    for _ in range(4):
        assert weather.update_forecast() is False
    out = capsys.readouterr().out
    assert out.count("⚠️") == 4
    assert "❌" not in out
    assert "Timeout" in out and "ChunkedEncodingError" in out and "JSONDecodeError" in out


def test_databasfel_ar_fortfarande_programfel(monkeypatch, capsys):
    monkeypatch.setattr(weather, "_add_precip_column", lambda: None)
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"hourly": _hourly()}
    monkeypatch.setattr(weather.requests, "get", lambda *_a, **_k: response)

    def db_boom():
        raise RuntimeError("postgres nere")

    monkeypatch.setattr(weather, "get_db", db_boom)
    assert weather.update_forecast() is False
    out = capsys.readouterr().out
    assert "❌" in out and "postgres nere" in out
    assert "⚠️" not in out
