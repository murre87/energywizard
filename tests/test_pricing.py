"""nordpool.full_buy_cost/full_sell_income/sql_*_expr: samlar momsformeln som tidigare var
duplicerad i gpm.py, mpc.py, pump_runtime.py och smartdashboard/app.py på ETT ställe.
Viktigast: regressionsskydd (dagens produktionsbeteende, PRICE_SOURCE=elprisetjustnu, får
inte röra sig en endaste öre) + källinvarianten (samma verkliga kr oavsett vilken bas
elpriser har)."""
import pytest

import nordpool


PRICES = [-1.0, -0.5, -0.021, 0.0, 0.3, 1.0, 3.5]


def _old_full_buy_cost(spot):
    return (spot * 1.25) + 0.62675


def _old_full_sell_income(spot):
    return spot + 0.02125


@pytest.fixture(autouse=True)
def _default_source(monkeypatch):
    monkeypatch.setattr(nordpool, "PRICE_SOURCE", "elprisetjustnu")


@pytest.mark.parametrize("spot", PRICES)
def test_full_buy_cost_matchar_gamla_formeln_for_default_kalla(spot):
    assert nordpool.full_buy_cost(spot) == pytest.approx(_old_full_buy_cost(spot))


@pytest.mark.parametrize("spot", PRICES)
def test_full_sell_income_matchar_gamla_formeln_for_default_kalla(spot):
    assert nordpool.full_sell_income(spot) == pytest.approx(_old_full_sell_income(spot))


@pytest.mark.parametrize("spot_ex", PRICES)
def test_kallinvariant_buy_samma_verkliga_kr_oavsett_kalla(spot_ex, monkeypatch):
    monkeypatch.setattr(nordpool, "PRICE_SOURCE", "elprisetjustnu")
    ex_cost = nordpool.full_buy_cost(spot_ex)

    monkeypatch.setattr(nordpool, "PRICE_SOURCE", "ha_nordpool")
    inc_cost = nordpool.full_buy_cost(spot_ex * nordpool.VAT_FACTOR)

    assert inc_cost == pytest.approx(ex_cost)


@pytest.mark.parametrize("spot_ex", PRICES)
def test_kallinvariant_sell_samma_verkliga_kr_oavsett_kalla(spot_ex, monkeypatch):
    monkeypatch.setattr(nordpool, "PRICE_SOURCE", "elprisetjustnu")
    ex_income = nordpool.full_sell_income(spot_ex)

    monkeypatch.setattr(nordpool, "PRICE_SOURCE", "ha_nordpool")
    inc_income = nordpool.full_sell_income(spot_ex * nordpool.VAT_FACTOR)

    assert inc_income == pytest.approx(ex_income)


@pytest.mark.parametrize("spot", [-0.52, -0.505, -0.501, -0.4999, -0.49, 0.0, 1.0])
def test_paid_to_import_brytpunkt_oforandrad(spot):
    """Gamla IMPORT_PROFIT_SPOT = -(0.62675/1.25) ≈ -0.501 kr. Nya villkoret
    (full_buy_cost(price) < 0) måste träffa exakt samma brytpunkt för default-källan."""
    old_threshold = -(0.62675 / 1.25)
    old_result = spot < old_threshold
    new_result = nordpool.full_buy_cost(spot) < 0
    assert new_result == old_result


def test_sql_buy_cost_expr_matchar_python_for_default_kalla(smartbox):
    with smartbox.get_db() as conn, conn.cursor() as cur:
        for spot in PRICES:
            expr = nordpool.sql_buy_cost_expr(str(spot))
            cur.execute(f"SELECT {expr}")
            sql_value = float(cur.fetchone()[0])
            assert sql_value == pytest.approx(nordpool.full_buy_cost(spot))


def test_sql_sell_income_expr_matchar_python_for_default_kalla(smartbox):
    with smartbox.get_db() as conn, conn.cursor() as cur:
        for spot in PRICES:
            expr = nordpool.sql_sell_income_expr(str(spot))
            cur.execute(f"SELECT {expr}")
            sql_value = float(cur.fetchone()[0])
            assert sql_value == pytest.approx(nordpool.full_sell_income(spot))


def test_sql_buy_cost_expr_matchar_python_for_ha_kalla(smartbox, monkeypatch):
    monkeypatch.setattr(nordpool, "PRICE_SOURCE", "ha_nordpool")
    with smartbox.get_db() as conn, conn.cursor() as cur:
        for spot in PRICES:
            expr = nordpool.sql_buy_cost_expr(str(spot))
            cur.execute(f"SELECT {expr}")
            sql_value = float(cur.fetchone()[0])
            assert sql_value == pytest.approx(nordpool.full_buy_cost(spot))


# ---------- calculate_day_strategy: "billig dag"-gränsen ----------

def test_billig_dag_grans_oforandrad_for_default_kalla():
    cheap_prices = [0.40] * 96  # avg 0.40 < 0.50, spread 0 < 0.30
    strategy = nordpool.calculate_day_strategy(cheap_prices, cheap_hours_count=8)
    assert strategy["mode"] == "comfort"

    expensive_prices = [0.60] * 96  # avg 0.60 >= 0.50
    strategy = nordpool.calculate_day_strategy(expensive_prices, cheap_hours_count=8)
    assert strategy["mode"] == "optimize"


def test_billig_dag_grans_skalas_for_ha_kalla(monkeypatch):
    monkeypatch.setattr(nordpool, "PRICE_SOURCE", "ha_nordpool")
    # Samma verkliga "billiga dag" som ovan (0.40 kr ex moms), nu uttryckt momsinklusive.
    cheap_prices_inc_vat = [0.40 * nordpool.VAT_FACTOR] * 96
    strategy = nordpool.calculate_day_strategy(cheap_prices_inc_vat, cheap_hours_count=8)
    assert strategy["mode"] == "comfort"

    expensive_prices_inc_vat = [0.60 * nordpool.VAT_FACTOR] * 96
    strategy = nordpool.calculate_day_strategy(expensive_prices_inc_vat, cheap_hours_count=8)
    assert strategy["mode"] == "optimize"
