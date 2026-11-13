"""Automatiskt val av prissensor: i länder utan Nord Pools portal (Australien, Tjeckien ...) och utan vald sensor
letar motorn själv upp prissensorn i HA, landets egen källa först, och momsen följer integrationens format."""
from unittest.mock import MagicMock, patch

import pytest

import ew_settings
import nordpool


def setup(monkeypatch, country, area, currency, ha_entity="", vat_setting=None):
    monkeypatch.delenv("PRICE_SOURCE", raising=False)
    monkeypatch.delenv("NORDPOOL_HA_ENTITY", raising=False)
    monkeypatch.delenv("PRICE_INCLUDES_VAT", raising=False)
    base = nordpool.cost_settings()
    monkeypatch.setattr(nordpool, "cost_settings", lambda: {**base, "country": country, "area": area, "currency": currency})
    real = ew_settings.get
    vals = {"price_ha_entity": ha_entity or None, "price_includes_vat": vat_setting}
    monkeypatch.setattr(ew_settings, "get", lambda k, d=None: vals[k] if k in vals else real(k, d))
    nordpool._auto_price.update(key=None, at=-1e9, entity=None, kind=None)


def states(*items):
    r = MagicMock(status_code=200)
    r.raise_for_status = MagicMock()
    r.json.return_value = list(items)
    return r


AMBER = {"entity_id": "sensor.amber_general_forecast", "attributes": {"forecasts": [
    {"start_time": "2026-11-13T00:00:00+11:00", "end_time": "2026-11-13T00:30:00+11:00", "per_kwh": 0.21}]}}
ENTSOE = {"entity_id": "sensor.entsoe_prices", "attributes": {"prices": [
    {"time": "2026-11-13T00:00:00+01:00", "price": 0.1}, {"time": "2026-11-13T01:00:00+01:00", "price": 0.11}]}}
OTE = {"entity_id": "sensor.current_spot_electricity_price", "attributes": {
    "2026-11-13T00:00:00+01:00": 2.1, "2026-11-13T01:00:00+01:00": 2.2, "unit_of_measurement": "CZK/kWh"}}
TEMP = {"entity_id": "sensor.ute", "attributes": {"unit_of_measurement": "°C"}}


def test_australien_väljer_amber_före_annat(monkeypatch, capsys):
    setup(monkeypatch, "AU", "AU", "AUD")
    with patch("nordpool.requests.get", return_value=states(TEMP, ENTSOE, AMBER)):
        assert nordpool.auto_price_entity() == ("sensor.amber_general_forecast", "Amber Electric")
        assert nordpool._price_entities() == ["sensor.amber_general_forecast"]
        assert nordpool.prices_include_vat() is True          # Amber har moms
    assert "Prissensor vald automatiskt: sensor.amber_general_forecast, Amber Electric" in capsys.readouterr().out


def test_tjeckien_väljer_ote_utan_moms(monkeypatch):
    setup(monkeypatch, "CZ", "CZ", "CZK")
    with patch("nordpool.requests.get", return_value=states(OTE, TEMP)):
        assert nordpool.auto_price_entity()[0] == "sensor.current_spot_electricity_price"
        assert nordpool.prices_include_vat() is False


def test_eget_momsval_går_före(monkeypatch):
    setup(monkeypatch, "CZ", "CZ", "CZK", vat_setting=True)
    with patch("nordpool.requests.get", return_value=states(OTE)):
        assert nordpool.prices_include_vat() is True


def test_vald_sensor_går_före_och_ingen_sökning(monkeypatch):
    setup(monkeypatch, "AU", "AU", "AUD", ha_entity="sensor.min_tariff")
    with patch("nordpool.requests.get") as get:
        assert nordpool.auto_price_entity() == (None, None)
        assert nordpool._price_entities() == ["sensor.min_tariff"]
    get.assert_not_called()


@pytest.mark.parametrize("country,area,currency", [("SE", "SE3", "SEK"), ("NL", "NL", "EUR"), ("GB", "GB", "GBP")])
def test_inget_automatiskt_val_där_det_inte_behövs(monkeypatch, country, area, currency):
    setup(monkeypatch, country, area, currency)
    with patch("nordpool.requests.get") as get:
        assert nordpool.auto_price_entity() == (None, None)
    get.assert_not_called()


def test_sökningen_cachas(monkeypatch):
    setup(monkeypatch, "AU", "AU", "AUD")
    with patch("nordpool.requests.get", return_value=states(AMBER)) as get:
        nordpool.auto_price_entity()
        nordpool.auto_price_entity()
        nordpool._price_entities()
    assert get.call_count == 1


def test_ingen_prissensor_faller_tillbaka_som_förut(monkeypatch):
    setup(monkeypatch, "AU", "AU", "AUD")
    with patch("nordpool.requests.get", return_value=states(TEMP)):
        assert nordpool.auto_price_entity() == (None, None)
        assert nordpool._price_entities() == [nordpool.NORDPOOL_HA_ENTITY]


def test_ha_nere_ger_varning_inte_programfel(monkeypatch, capsys):
    import requests
    setup(monkeypatch, "AU", "AU", "AUD")
    with patch("nordpool.requests.get", side_effect=requests.ConnectionError("x")):
        assert nordpool.auto_price_entity() == (None, None)
    out = capsys.readouterr().out
    assert out.startswith("⚠️") and "❌" not in out
