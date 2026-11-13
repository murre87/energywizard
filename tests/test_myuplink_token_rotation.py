"""myUplink roterar refresh_token: den nya ska användas och sparas, och en nekad inloggning
(400/401) är ett inloggningsproblem hos användaren - tydlig varning, en avisering, glesa försök."""
import json
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

import drivers.heatpump_myuplink as myuplink


@pytest.fixture(autouse=True)
def _configured(monkeypatch, tmp_path):
    monkeypatch.setattr(myuplink, "_CLIENT_ID", "client")
    monkeypatch.setattr(myuplink, "_CLIENT_SECRET", "secret")
    monkeypatch.setattr(myuplink, "_REFRESH_TOKEN", "env-token")
    monkeypatch.setattr(myuplink, "_DEVICE_ID", "device-123")
    monkeypatch.setattr(myuplink, "_TOKEN_STORE", str(tmp_path / "myuplink-token.json"))
    sent = []
    monkeypatch.setitem(sys.modules, "notifier", types.SimpleNamespace(send_emil=lambda t, m, **k: sent.append(t)))
    return sent


def _ok(access, refresh=None):
    r = MagicMock(status_code=200)
    r.json.return_value = {"access_token": access, "expires_in": 3600, **({"refresh_token": refresh} if refresh else {})}
    return r


def _denied(status=400):
    r = MagicMock(status_code=status)
    r.raise_for_status.side_effect = AssertionError("ska inte nås")
    return r


def _sent_refresh(mock_post, call=-1):
    return mock_post.call_args_list[call].kwargs["data"]["refresh_token"]


def test_roterad_token_används_nästa_gång():
    d = myuplink.MyUplinkHeatPumpDriver()
    with patch.object(myuplink.requests, "post", side_effect=[_ok("a1", "rot-1"), _ok("a2", "rot-2")]) as post:
        d._refresh_access_token()
        d._refresh_access_token()
    assert _sent_refresh(post, 0) == "env-token"
    assert _sent_refresh(post, 1) == "rot-1"          # förut: alltid env-token -> 400 efter rotation


def test_roterad_token_överlever_omstart(tmp_path):
    with patch.object(myuplink.requests, "post", return_value=_ok("a1", "rot-1")):
        myuplink.MyUplinkHeatPumpDriver()._refresh_access_token()
    saved = json.load(open(myuplink._TOKEN_STORE))
    assert saved["refresh_token"] == "rot-1"
    with patch.object(myuplink.requests, "post", return_value=_ok("a2")) as post:
        myuplink.MyUplinkHeatPumpDriver()._refresh_access_token()   # ny process
    assert _sent_refresh(post) == "rot-1"


def test_ny_inloggning_i_miljön_går_före_sparad(monkeypatch):
    with patch.object(myuplink.requests, "post", return_value=_ok("a1", "rot-1")):
        myuplink.MyUplinkHeatPumpDriver()._refresh_access_token()
    monkeypatch.setattr(myuplink, "_REFRESH_TOKEN", "ny-env-token")   # användaren loggade in på nytt
    with patch.object(myuplink.requests, "post", return_value=_ok("a2")) as post:
        myuplink.MyUplinkHeatPumpDriver()._refresh_access_token()
    assert _sent_refresh(post) == "ny-env-token"


def test_nekad_inloggning_varnar_en_gång_aviserar_och_försöker_glest(capsys, monkeypatch, _configured):
    clock = [1000.0]
    monkeypatch.setattr(myuplink.time, "time", lambda: clock[0])
    d = myuplink.MyUplinkHeatPumpDriver()
    with patch.object(myuplink.requests, "post", return_value=_denied(400)) as post:
        for _ in range(4):                               # fyra kvartar
            assert d._refresh_access_token() is None
            clock[0] += 900
    assert post.call_count == 2                          # 0 och 30 min, inte varje kvart
    out = capsys.readouterr().out
    assert out.count("myUplink nekar inloggningen, HTTP 400") == 1
    assert "❌" not in out                                # inte ett programfel
    assert _configured == ["⚠️ myUplink: logga in igen"]
    with patch.object(myuplink.requests, "post", return_value=_ok("a9")):
        clock[0] += 1800
        assert d._refresh_access_token() == "a9"
    assert "inloggningen fungerar igen" in capsys.readouterr().out


def test_401_räknas_också_som_nekad(capsys):
    d = myuplink.MyUplinkHeatPumpDriver()
    with patch.object(myuplink.requests, "post", return_value=_denied(401)):
        assert d._refresh_access_token() is None
    assert "nekar inloggningen, HTTP 401" in capsys.readouterr().out
