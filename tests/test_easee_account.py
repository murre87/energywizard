"""Easee-kontot och laddboxens månadshistorik (smartbox/easee_account.py, #605). Inget test anropar Easee."""
import os
import sys
from datetime import date, datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "smartbox"))
import easee_account as ea  # noqa: E402

NOW = datetime(2026, 11, 27, 8, 0, tzinfo=timezone.utc)
TODAY = date(2026, 11, 27)


def _http(routes):
    calls = []

    def http(method, path, body=None, token=None):
        calls.append({"method": method, "path": path, "body": body, "token": token})
        for (m, p), fn in routes.items():
            if method == m and path == p:
                return fn(body, token)
        raise AssertionError(f"oväntat anrop {method} {path}")

    return http, calls


def _ok_routes(monthly=None):
    monthly = monthly if monthly is not None else [
        {"year": 2025, "month": 1, "totalEnergyUsage": 100, "totalCost": 0, "currencyId": "SEK"},
        {"year": 2025, "month": 11, "totalEnergyUsage": 180.5, "totalCost": 400, "currencyId": "SEK"},
        {"year": 2026, "month": 11, "totalEnergyUsage": 90, "totalCost": 250, "currencyId": "SEK"},
        {"year": 2026, "month": 1, "totalEnergyUsage": 210, "totalCost": None, "currencyId": "SEK"},
    ]

    def login(body, token):
        assert body["password"] == "hemligt" and token is None
        return 200, {"accessToken": "a1", "refreshToken": "r1", "expiresIn": 3600}

    def chargers(body, token):
        assert token == "a1"
        return 200, [{"id": "EHC0FFEE", "name": "Garage"}, {"id": "../x", "name": "ogiltig"}]

    def months(body, token):
        assert token == "a1"
        return 200, monthly

    return {("POST", "/api/accounts/login"): login, ("GET", "/api/chargers"): chargers,
            ("GET", "/api/sessions/charger/EHC0FFEE/monthly"): months}


def test_manadssummor_och_jamforelse_raknas_for_hand():
    rows = ea.parse_monthly([
        {"year": 2026, "month": 11, "totalEnergyUsage": 90, "totalCost": 10, "currencyId": "SEK"},
        {"year": 2025, "month": 11, "totalEnergyUsage": 180.5, "totalCost": 20, "currencyId": "SEK"},
        {"year": 2026, "month": 13, "totalEnergyUsage": 5},          # ogiltig månad
        {"year": 2026, "month": 1, "totalEnergyUsage": -1},          # negativ energi
        "skräp",
    ])
    assert [r["month"] for r in rows] == ["2025-11", "2026-11"]
    (year,) = [y for y in ea.summarize_years(rows) if y["year"] == "2026"]
    assert year["kwh"] == 90 and year["cost"] == 10
    cmp = ea.same_months_last_year(
        rows + [{"month": "2026-01", "kwh": 210, "cost": None, "currency": ""},
                {"month": "2025-01", "kwh": 100, "cost": None, "currency": ""}], TODAY)
    assert cmp["this_kwh"] == 300 and cmp["last_kwh"] == 280.5 and cmp["months"] == 2
    # november 2024 saknas, så 2025 kan inte jämföras mot året innan
    assert ea.same_months_last_year(rows, date(2025, 11, 1)) is None


def test_synk_loggar_in_hamtar_och_visar_aldrig_losenordet():
    http, calls = _http(_ok_routes())
    stored, view = ea.sync({"username": "a@b.c", "password": "hemligt"}, ea.Client(http), NOW, TODAY)
    assert [c["path"] for c in calls] == ["/api/accounts/login", "/api/chargers", "/api/sessions/charger/EHC0FFEE/monthly"]
    assert stored["refresh_token"] == "r1" and stored["password"] == "hemligt"
    assert "password" not in view and "access_token" not in view and "refresh_token" not in view
    assert view["chargers"][0]["id"] == "EHC0FFEE"
    assert view["chargers"][0]["compare"]["this_kwh"] == 300
    assert view["chargers"][0]["compare"]["last_kwh"] == 280.5
    dumped = str(view)
    assert "hemligt" not in dumped and "a1" not in dumped
    # inom dygnet blir det inga nya anrop
    ea.sync(stored, ea.Client(lambda *a: (_ for _ in ()).throw(AssertionError("anrop"))), NOW + timedelta(hours=1), TODAY)


def test_sparad_nyckel_anvands_och_fornyas_nar_den_gatt_ut():
    http, calls = _http({
        ("POST", "/api/accounts/refresh_token"): lambda body, token: (200, {"accessToken": "a2", "refreshToken": "r2", "expiresIn": 3600}),
        ("GET", "/api/chargers"): lambda body, token: (200, [{"id": "EH1234", "name": "Hus"}]) if token == "a2" else (401, {}),
        ("GET", "/api/sessions/charger/EH1234/monthly"): lambda body, token: (200, []),
    })
    stored = {"username": "a@b.c", "password": "hemligt", "access_token": "gammal", "refresh_token": "r0",
              "access_until": (NOW - timedelta(minutes=5)).isoformat()}
    saved, view = ea.sync(stored, ea.Client(http), NOW, TODAY)
    assert calls[0]["path"] == "/api/accounts/refresh_token" and calls[0]["body"] == {"refreshToken": "r0"}
    assert saved["access_token"] == "a2" and view["chargers"][0]["months"] == []


def test_nekad_nyckel_provar_losenordet_en_gang():
    state = {"login": 0}

    def login(body, token):
        state["login"] += 1
        return 200, {"accessToken": "ny", "refreshToken": "r", "expiresIn": 3600}

    def chargers(body, token):
        return (401, {}) if token == "gammal" else (200, [{"id": "EH1234", "name": "Hus"}])

    http, calls = _http({
        ("POST", "/api/accounts/login"): login,
        ("GET", "/api/chargers"): chargers,
        ("GET", "/api/sessions/charger/EH1234/monthly"): lambda body, token: (200, []),
    })
    stored = {"username": "a@b.c", "password": "hemligt", "access_token": "gammal", "refresh_token": "",
              "access_until": (NOW + timedelta(hours=1)).isoformat()}
    saved, view = ea.sync(stored, ea.Client(http), NOW, TODAY)
    assert state["login"] == 1 and saved["access_token"] == "ny" and view["error"] is None


def test_fel_losenord_sparar_inte_en_nyckel_och_visar_inte_losenordet():
    http, _ = _http({("POST", "/api/accounts/login"): lambda body, token: (401, {"password": body["password"]})})
    stored, view = ea.sync({"username": "a@b.c", "password": "hemligt"}, ea.Client(http), NOW, TODAY)
    assert stored.get("access_token") is None
    assert view["error"].startswith("Easee tog inte emot kontot")
    assert "hemligt" not in view["error"] and view["chargers"] == []


def test_manuell_uppdatering_vantar_en_kvart():
    stored = {"username": "a@b.c", "password": "x", "fetched_at": NOW.isoformat(), "chargers": []}
    _, view = ea.sync(stored, ea.Client(lambda *a: (_ for _ in ()).throw(AssertionError("anrop"))), NOW + timedelta(minutes=5), TODAY, force=True)
    assert "Vänta" in view["error"] and view["stale"] is True


def test_byte_av_losenord_glommer_nyckeln_tomt_losenord_behaller_det():
    old = {"username": "a@b.c", "password": "gammal", "access_token": "a", "chargers": [{"id": "EH1"}]}
    kept = ea.apply_credentials(old, "a@b.c", "")
    assert kept["password"] == "gammal" and kept["access_token"] == "a"
    changed = ea.apply_credentials(old, "a@b.c", "ny")
    assert changed["password"] == "ny" and "access_token" not in changed and "chargers" not in changed
    with pytest.raises(ea.EaseeError):
        ea.apply_credentials({}, "a@b.c", "")
