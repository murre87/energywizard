"""2026-11-06: när HA är nere ska inte varje avläsning försöka igen (dussintals försök/min).
Avbrott utan HTTP-svar förblir varning (#228). HTTP-fel och oväntade fel skrivs som ❌."""
from unittest.mock import patch

import requests
import pytest

import homeassistant as ha


def test_paus_efter_misslyckande_och_lugnare_logg(monkeypatch, capsys):
    monkeypatch.setattr(ha, "_states_cache", {})
    monkeypatch.setattr(ha, "_ha_fail", {"n": 0})
    calls = []

    def boom(*a, **k):
        calls.append(1)
        raise requests.exceptions.ConnectionError("SSL handshake timed out")
    clock = [1000.0]
    monkeypatch.setattr(ha.time, "time", lambda: clock[0])
    with patch.object(ha.requests, "get", side_effect=boom):
        assert ha._get_raw_state("sensor.a") is None
        for _ in range(20):                                   # samma minut: inga nya försök
            ha._get_raw_state("sensor.b")
        assert len(calls) == 1
        clock[0] += 31
        ha._get_raw_state("sensor.c")
        assert len(calls) == 2
        for _ in range(8):                                    # direkta anrop (huvudloopen)
            ha.update_states()
    out = capsys.readouterr().out
    # 2026-11-08: avbrott räknas som en omstart av HA de första 30 försöken (~5 min) - väntan, inga felrader
    assert out.count("❌") == 0 and "väntar, troligen en omstart" in out
    assert "Traceback" not in out
    with patch.object(ha.requests, "get", side_effect=boom):
        for _ in range(30):
            ha.update_states()
    out = capsys.readouterr().out
    assert "❌" not in out and "fortsätter försöka" in out                   # avbrott är drift, inte programfel (#228)


def test_httpfel_och_ovantat_fel_ar_kvar(monkeypatch, capsys):
    monkeypatch.setattr(ha, "_states_cache", {})
    monkeypatch.setattr(ha, "_ha_fail", {"n": 0})
    resp = requests.Response()
    resp.status_code = 500
    err = requests.HTTPError("500")
    err.response = resp
    with patch.object(ha.requests, "get", side_effect=err):
        for _ in range(3):
            ha.update_states()
    assert "❌ HA: Fel vid update_states" in capsys.readouterr().out
    monkeypatch.setattr(ha, "_ha_fail", {"n": 0})
    with patch.object(ha.requests, "get", side_effect=ValueError("trasig")):
        ha.update_states()
    assert capsys.readouterr().out.count("❌ HA: Fel vid update_states") == 1


@pytest.mark.parametrize("status", [502, 503, 504])
def test_prolonged_gateway_outage_warns_and_recovers(monkeypatch, capsys, status):
    """#228: Supervisor gateway errors must not escalate after 30 failures."""
    monkeypatch.setattr(ha, "_states_cache", {"sensor.old": {"state": "12"}})
    monkeypatch.setattr(ha, "_ha_fail", {"n": 0})
    monkeypatch.setattr(ha, "last_update_ok", True)
    response = requests.Response()
    response.status_code = status
    error = requests.HTTPError(str(status), response=response)
    with patch.object(ha.requests, "get", side_effect=error) as get:
        for _ in range(40):
            assert ha.update_states() is False
        assert get.call_count == 40
    assert ha._states_cache == {} and ha.last_update_ok is False
    assert ha._ha_fail["n"] == 40
    out = capsys.readouterr().out
    assert "⚠️" in out and "❌" not in out and "Traceback" not in out

    response = requests.Response()
    response.status_code = 200
    response._content = b'[{"entity_id":"sensor.fresh","state":"21"}]'
    with patch.object(ha.requests, "get", return_value=response):
        assert ha.update_states() is True
    assert ha.last_update_ok is True and ha._ha_fail["n"] == 0
    assert ha._get_raw_state("sensor.fresh") == "21"
    assert "sensor.old" not in ha._states_cache


def test_unauthorized_ha_still_requires_action(monkeypatch, capsys):
    monkeypatch.setattr(ha, "_states_cache", {})
    monkeypatch.setattr(ha, "_ha_fail", {"n": 0})
    monkeypatch.setattr(ha, "last_update_ok", True)
    response = requests.Response()
    response.status_code = 401
    with patch.object(ha.requests, "get", side_effect=requests.HTTPError(response=response)):
        assert ha.update_states() is False
    assert "❌ HA: token" in capsys.readouterr().out
    assert ha.last_update_ok is False
