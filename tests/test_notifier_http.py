"""#249: HTTP-fel från Home Assistant vid notis ska vara varning, inte programfel (❌)."""
import requests

import notifier


def _ready(monkeypatch):
    monkeypatch.setattr(notifier, "_init", lambda: None)
    monkeypatch.setattr(notifier, "_hist", lambda *a, **k: None)
    notifier._ha_base, notifier._ha_headers = "http://ha/api", {}


def _http_error(status):
    response = requests.Response()
    response.status_code = status
    response.url = "http://ha/api/services/notify/mobile_app_x"
    return requests.HTTPError(f"{status} Server Error", response=response)


def test_http_och_natverksfel_ar_varning(monkeypatch, capsys):
    _ready(monkeypatch)
    errors = [
        _http_error(503),
        _http_error(400),
        requests.Timeout("timed out"),
        requests.ConnectionError("refused"),
    ]

    def post(*_a, **_k):
        raise errors.pop(0)

    monkeypatch.setattr(notifier.requests, "post", post)
    for _ in range(len(errors)):
        assert notifier._send("mobile_app_x", "Tesla laddar", "16 A") is False
    out = capsys.readouterr().out
    assert out.count("⚠️") == 4
    assert "❌" not in out


def test_ovantat_fel_ar_fortfarande_programfel(monkeypatch, capsys):
    _ready(monkeypatch)

    def boom(*a, **k):
        raise RuntimeError("payload")

    monkeypatch.setattr(notifier.requests, "post", boom)
    assert notifier._send("mobile_app_x", "Tesla laddar", "16 A") is False
    out = capsys.readouterr().out
    assert "❌" in out
    assert "⚠️" not in out
