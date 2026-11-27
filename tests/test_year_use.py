"""#603: årsförbrukning. En saknad månad är inte noll, och prognosen är ett spann."""
from datetime import datetime

from year_use import SWE, assemble, forecast_span, winters


def _year(year, values):
    return {(year, month): value for month, value in enumerate(values, start=1)}


def test_prognosen_ar_spannet_mellan_tidigare_ar():
    monthly = {}
    monthly.update(_year(2024, [50] * 6 + [50] + [80] * 5))
    monthly.update(_year(2025, [100] * 12))
    monthly.update(_year(2026, [200] * 6 + [50]))
    span = forecast_span(monthly, 2026, datetime(2026, 7, 15, tzinfo=SWE))
    assert span == {"low": 2400.0, "high": 3000.0, "years": 2}


def test_saknad_manad_hoppar_over_aret_och_blir_inte_noll():
    monthly = _year(2025, [100] * 12)
    monthly.update(_year(2026, [200] * 6 + [50]))
    broken = _year(2024, [50] * 12)
    del broken[(2024, 3)]
    monthly.update(broken)
    span = forecast_span(monthly, 2026, datetime(2026, 7, 15, tzinfo=SWE))
    assert span == {"low": 2400.0, "high": 2400.0, "years": 1}


def test_aret_behover_inte_borja_i_januari():
    monthly = _year(2025, [100] * 12)
    monthly.update({(2026, month): 200 for month in range(2, 7)})
    monthly[(2026, 7)] = 50
    span = forecast_span(monthly, 2026, datetime(2026, 7, 15, tzinfo=SWE))
    assert span == {"low": 2200.0, "high": 2200.0, "years": 1}


def test_ingen_prognos_utan_tidigare_ar_eller_i_januari():
    monthly = _year(2026, [200] * 6 + [50])
    now = datetime(2026, 7, 15, tzinfo=SWE)
    assert forecast_span(monthly, 2026, now) is None
    assert forecast_span(_year(2026, [10] * 12), 2026, datetime(2026, 1, 20, tzinfo=SWE)) is None


def test_tom_manad_ar_null_och_uppmatt_noll_finns_kvar():
    meter = [(datetime(2026, 1, 1, tzinfo=SWE), 10.0, 4.0), (datetime(2026, 3, 1, tzinfo=SWE), 0.0, None)]
    parts = [(datetime(2026, 1, 1, tzinfo=SWE), 2.0, None, 0.0, 1.0)]
    out = assemble(meter, parts, 2026, datetime(2026, 3, 2, tzinfo=SWE))
    january, february, march = out["months"][:3]
    assert january["used_kwh"] == 10.0 and january["bought_kwh"] == 4.0
    assert january["ev_kwh"] == 2.0 and january["spa_kwh"] == 0.0 and january["pump_kwh"] is None
    assert february["used_kwh"] is None and february["ev_kwh"] is None
    assert march["used_kwh"] == 0.0 and march["bought_kwh"] is None
    assert out["used_kwh"] == 10.0 and out["parts"]["spa_kwh"] == 0.0 and out["parts"]["pump_kwh"] is None


def test_vintern_visar_saknade_manader_som_null():
    monthly = {(2025, 11): 100.0, (2025, 12): 110.0, (2026, 1): 120.0}
    rows = winters(monthly, 2026)
    assert rows[0]["label"] == "2025/26"
    assert [item["used_kwh"] for item in rows[0]["months"]] == [100.0, 110.0, 120.0, None, None]
