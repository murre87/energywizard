"""Elpris och avgifter per land (nordpool.cost_settings): utan inställningar exakt som förut (Sverige SE3),
med inställningar landets moms, egna avgifter, rätt elområde och HA:s Nordpool-källa utanför Sverige."""
from datetime import datetime

import pytest
import requests

import ew_settings
import nordpool


@pytest.fixture(autouse=True)
def _ren(monkeypatch, tmp_path):
    monkeypatch.setattr(ew_settings, "PATH", str(tmp_path / "ew.json"))
    ew_settings._cache.update(mtime=None, data={})
    for k in ("PRICE_SOURCE", "PRICE_COUNTRY", "PRICE_AREA", "PRICE_VAT_PCT", "PRICE_BUY_EXTRA", "PRICE_SELL_EXTRA"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(nordpool, "PRICE_SOURCE", "elprisetjustnu")


def test_utan_installningar_som_forut():
    c = nordpool.cost_settings()
    assert (c["country"], c["area"], c["vat_pct"], c["currency"]) == ("SE", "SE3", 25.0, "SEK")
    assert nordpool.full_buy_cost(1.0) == pytest.approx(1.25 + 0.62675)
    assert nordpool.full_sell_income(1.0) == pytest.approx(1.0 + 0.02125)
    assert nordpool.price_source() == "elprisetjustnu"


def test_annat_svenskt_elomrade_hamtas():
    ew_settings.update(price_area="SE4")
    urls = []
    class R:
        status_code = 404
    with pytest.MonkeyPatch.context() as m:
        m.setattr(nordpool.requests, "get", lambda url, timeout=10: urls.append(url) or R())
        nordpool.fetch_api_and_save(__import__("datetime").datetime(2026, 11, 3))
    assert urls and urls[0].endswith("2026/11-03_SE4.json")


def test_elprisetjustnu_natfel_ar_varning(capsys, monkeypatch):
    def boom(url, timeout=10):
        raise requests.ConnectionError("ned")
    monkeypatch.setattr(nordpool.requests, "get", boom)
    assert nordpool.fetch_api_and_save(datetime(2026, 11, 12)) is False
    out = capsys.readouterr().out
    assert "⚠️" in out and "elprisetjustnu.se" in out and "❌" not in out


def test_elprisetjustnu_ovantat_fel_ar_kvar(capsys, monkeypatch):
    def boom(url, timeout=10):
        raise RuntimeError("boom")
    monkeypatch.setattr(nordpool.requests, "get", boom)
    assert nordpool.fetch_api_and_save(datetime(2026, 11, 12)) is False
    assert "❌" in capsys.readouterr().out


def test_tyskland_egna_avgifter_och_nordpool_kalla():
    ew_settings.update(price_country="DE", price_buy_extra=0.21, price_sell_extra=0.08)
    c = nordpool.cost_settings()
    assert (c["vat_pct"], c["currency"], c["symbol"], c["area"]) == (19.0, "EUR", "€", "DE-LU")
    assert nordpool.price_source() == "ha_nordpool" and nordpool.prices_include_vat()
    assert nordpool.full_buy_cost(0.119) == pytest.approx(0.119 + 0.21)       # priset från HA har redan moms
    assert nordpool.full_sell_income(0.119) == pytest.approx(0.1 + 0.08)       # ingen moms på såld el som standard


def test_moms_pa_sald_el_och_egen_moms():
    ew_settings.update(price_country="NL", price_vat_pct=9, price_sell_vat=True)
    nordpool.PRICE_SOURCE = "elprisetjustnu"
    import os
    os.environ["PRICE_SOURCE"] = "elprisetjustnu"                                   # uttryckligt val vinner
    try:
        assert nordpool.price_source() == "elprisetjustnu"
        assert nordpool.full_buy_cost(1.0) == pytest.approx(1.09)
        assert nordpool.full_sell_income(1.0) == pytest.approx(1.09)
    finally:
        del os.environ["PRICE_SOURCE"]


def test_sql_och_python_samma_formel():
    ew_settings.update(price_country="FI", price_buy_extra=0.07)
    expr = nordpool.sql_buy_cost_expr("x")
    assert eval(expr.replace("x", "0.2")) == pytest.approx(nordpool.full_buy_cost(0.2))
    expr = nordpool.sql_sell_income_expr("x")
    assert eval(expr.replace("x", "0.2")) == pytest.approx(nordpool.full_sell_income(0.2))
