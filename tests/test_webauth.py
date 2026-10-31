"""Inloggningen krävde tidigare bara ett TOMT användarnamn + rätt lösenord för ägarrollen
(Emils egen "lämna tomt som ägare"). Bytt till att kräva det explicita användarnamnet
'admin' istället - tydligare i gränssnittet, mindre förvirrande när flera roller finns.
Bevisar att bytet faktiskt skedde och inte råkar tappas bort i en framtida ändring."""
import asyncio

import pytest

import webauth


class _FakeRequest:
    def __init__(self, body: dict, ip: str = "10.0.0.5"):
        self._body = body
        self.headers = {}
        self.client = type("c", (), {"host": ip})()

    async def json(self):
        return self._body


def _login(auth, body):
    return asyncio.run(auth.login(_FakeRequest(body)))


def test_admin_med_ratt_losenord_ger_owner(monkeypatch):
    monkeypatch.setattr(webauth, "PASSWORD", "hemligt123")
    auth = webauth.Auth(salt="test")
    r = _login(auth, {"user": "admin", "password": "hemligt123"})
    assert r.status_code == 200
    assert "ew=" in r.headers.get("set-cookie", "")


def test_admin_skiftlage_spelar_ingen_roll(monkeypatch):
    monkeypatch.setattr(webauth, "PASSWORD", "hemligt123")
    auth = webauth.Auth(salt="test")
    r = _login(auth, {"user": "ADMIN", "password": "hemligt123"})
    assert r.status_code == 200


def test_tomt_anvandarnamn_fungerar_inte_langre(monkeypatch):
    """Det gamla beteendet (tomt fält = ägare) ska INTE längre fungera - admin krävs nu."""
    monkeypatch.setattr(webauth, "PASSWORD", "hemligt123")
    auth = webauth.Auth(salt="test")
    with pytest.raises(Exception):
        _login(auth, {"user": "", "password": "hemligt123"})


def test_fel_losenord_avvisas(monkeypatch):
    monkeypatch.setattr(webauth, "PASSWORD", "hemligt123")
    auth = webauth.Auth(salt="test")
    with pytest.raises(Exception):
        _login(auth, {"user": "admin", "password": "fel"})
