"""Inloggningen accepterar både 'admin' och ett tomt användarnamn som ägare.
Tomt fält togs bort en gång (för tydlighet), men blev i praktiken en
återkommande fälla - folk lämnar fältet tomt och skriver bara lösenordet.
Återinfört 2026-11-01 eftersom verkligheten vann över principen."""
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


def test_tomt_anvandarnamn_ger_owner(monkeypatch):
    """Tomt fält = ägare, precis som 'admin' - den vanligaste felaktiga ifyllnaden
    annars (bara lösenordet ifyllt) ska inte misslyckas i onödan."""
    monkeypatch.setattr(webauth, "PASSWORD", "hemligt123")
    auth = webauth.Auth(salt="test")
    r = _login(auth, {"user": "", "password": "hemligt123"})
    assert r.status_code == 200
    assert "ew=" in r.headers.get("set-cookie", "")


def test_fel_losenord_avvisas(monkeypatch):
    monkeypatch.setattr(webauth, "PASSWORD", "hemligt123")
    auth = webauth.Auth(salt="test")
    with pytest.raises(Exception):
        _login(auth, {"user": "admin", "password": "fel"})
