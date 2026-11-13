"""#392: priser utanför Sverige direkt från Nord Pools öppna portal - som källa när ingen HA-prissensor är
vald, och som reserv när den valda HA-sensorn misslyckas (grundorsaken till #210/#211). Aldrig nätverket."""
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
import requests

import ew_settings
import nordpool

DAY = datetime(2026, 11, 13, tzinfo=nordpool.SWE_TZ)


def settings(monkeypatch, country, area, currency, vat=21.0, ha_entity=""):
    monkeypatch.delenv("PRICE_SOURCE", raising=False)
    base = nordpool.cost_settings()
    monkeypatch.setattr(nordpool, "cost_settings", lambda: {**base, "country": country, "area": area,
                                                            "currency": currency, "vat_pct": vat})
    real = ew_settings.get
    monkeypatch.setattr(ew_settings, "get", lambda k, d=None: ha_entity if k == "price_ha_entity" else real(k, d))


def portal(area, values, start="2026-11-12T23:00:00Z", step=15, status=200):
    r = MagicMock(status_code=status)
    r.raise_for_status = MagicMock()
    from datetime import timedelta
    t0 = datetime.fromisoformat(start.replace("Z", "+00:00"))
    r.json.return_value = {"multiAreaEntries": [
        {"deliveryStart": (t0 + timedelta(minutes=i * step)).isoformat().replace("+00:00", "Z"),
         "deliveryEnd": (t0 + timedelta(minutes=(i + 1) * step)).isoformat().replace("+00:00", "Z"),
         "entryPerArea": {area: v}} for i, v in enumerate(values)]}
    return r


def run(fn, response):
    with patch("nordpool.requests.get", return_value=response) as get, patch("nordpool.get_db") as db:
        conn = MagicMock()
        db.return_value.__enter__.return_value = conn
        cur = conn.cursor.return_value.__enter__.return_value
        ok = fn()
    rows = cur.executemany.call_args[0][1] if cur.executemany.called else []
    return ok, get, rows


@pytest.mark.parametrize("country,area,currency,want", [
    ("NL", "NL", "EUR", "nordpool_api"), ("BE", "BE", "EUR", "nordpool_api"), ("DK", "DK1", "DKK", "nordpool_api"),
    ("GB", "GB", "GBP", "nordpool_api"), ("DE", "DE-LU", "EUR", "nordpool_api"),
    ("CZ", "CZ", "CZK", "ha_nordpool"), ("AU", "AU", "AUD", "ha_nordpool"),
])
def test_källa_utan_vald_sensor(monkeypatch, country, area, currency, want):
    settings(monkeypatch, country, area, currency)
    assert nordpool.price_source() == want


def test_vald_ha_sensor_gäller_som_förut(monkeypatch):
    settings(monkeypatch, "NL", "NL", "EUR", ha_entity="sensor.zonneplan_prices")
    assert nordpool.price_source() == "ha_nordpool"


def test_sparar_kvartspriser_per_kwh_utan_moms(monkeypatch):
    settings(monkeypatch, "NL", "NL", "EUR")
    ok, get, rows = run(lambda: nordpool.fetch_nordpool_api_and_save(DAY), portal("NL", [183.7, 186.04]))
    assert ok is True
    assert get.call_args.kwargs["params"] == {"date": "2026-11-13", "market": "DayAhead", "deliveryArea": "NL", "currency": "EUR"}
    assert rows == [("2026-11-12T23:00:00Z", "2026-11-12T23:15:00Z", 0.1837),
                    ("2026-11-12T23:15:00Z", "2026-11-12T23:30:00Z", 0.18604)]


def test_tyskland_och_storbritannien_har_egna_koder(monkeypatch):
    settings(monkeypatch, "DE", "DE-LU", "EUR")
    _, get, _ = run(lambda: nordpool.fetch_nordpool_api_and_save(DAY), portal("GER", [100.0]))
    assert get.call_args.kwargs["params"]["deliveryArea"] == "GER"
    settings(monkeypatch, "GB", "GB", "GBP", vat=5.0)
    ok, get, rows = run(lambda: nordpool.fetch_nordpool_api_and_save(DAY), portal("UK", [154.67], step=60))
    assert ok and get.call_args.kwargs["params"]["market"] == "N2EX_DayAhead" and get.call_args.kwargs["params"]["currency"] == "GBP"
    assert rows == [("2026-11-12T23:00:00Z", "2026-11-13T00:00:00Z", 0.15467)]


def test_reserv_när_ha_sensorn_misslyckas_med_samma_moms(monkeypatch):
    settings(monkeypatch, "BE", "BE", "EUR", vat=6.0, ha_entity="sensor.entsoe_prices")
    monkeypatch.setattr(nordpool, "fetch_ha_nordpool_and_save", lambda *a, **k: False)
    monkeypatch.setattr(nordpool, "prices_include_vat", lambda: True)
    ok, get, rows = run(lambda: nordpool._fetch_and_save(DAY), portal("BE", [100.0]))
    assert ok is True                                 # förut: False -> "KRITISKT: Kunde inte hämta dagens priser"
    assert rows[0][2] == pytest.approx(0.106)         # 100 €/MWh med 6 % moms, som sensorn


def test_inte_publicerat_än_är_ingen_varning(monkeypatch, capsys):
    settings(monkeypatch, "NL", "NL", "EUR")
    ok, _, rows = run(lambda: nordpool.fetch_nordpool_api_and_save(DAY), MagicMock(status_code=204))
    assert ok is False and rows == [] and capsys.readouterr().out == ""


def test_nätfel_är_varning_inte_programfel(monkeypatch, capsys):
    settings(monkeypatch, "NL", "NL", "EUR")
    with patch("nordpool.requests.get", side_effect=requests.ConnectionError("x")):
        assert nordpool.fetch_nordpool_api_and_save(DAY) is False
    out = capsys.readouterr().out
    assert out.startswith("⚠️") and "❌" not in out


def test_land_utanför_portalen_hämtas_inte(monkeypatch):
    settings(monkeypatch, "CZ", "CZ", "CZK")
    with patch("nordpool.requests.get") as get:
        assert nordpool.fetch_nordpool_api_and_save(DAY) is False
    get.assert_not_called()
