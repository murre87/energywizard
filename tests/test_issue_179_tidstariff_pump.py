"""#179: värmepumpens billig/dyr-val räknade bara på spotpriset. Med tidstariff (0,46 kr vardagar 06-22) är 05:45 och
06:15 med samma spotpris inte lika billiga. Utan tidstariff ska allt vara som förut."""
import zoneinfo
from datetime import datetime

from test_marginal_spapaus import _state

SWE = zoneinfo.ZoneInfo("Europe/Stockholm")


def _mode(monkeypatch, when, tou):
    import gpm as g
    import nordpool
    monkeypatch.setattr(nordpool, "tou_spot_extra", lambda t, c=None: tou if 6 <= t.astimezone(SWE).hour < 22 else 0.0)
    m = g.GlobalPriorityManager()
    out = m.evaluate(_state(when, current_price=1.0, dynamic_limit=1.2, hysteresis=0.1))
    return m.last_price_mode, out["log"][0]


def test_tariffen_gor_dagkvarten_dyr(monkeypatch):
    morgon = datetime(2026, 11, 9, 5, 45, tzinfo=SWE)        # måndag, före tariffen
    dag = datetime(2026, 11, 9, 6, 15, tzinfo=SWE)
    assert _mode(monkeypatch, morgon, 0.37)[0] == "CHEAP"
    mode, log = _mode(monkeypatch, dag, 0.37)                # 1,0 + 0,37 >= 1,2 + 0,1
    assert mode == "EXPENSIVE" and "tidstariff" in log


def test_utan_tariff_oforandrat(monkeypatch):
    assert _mode(monkeypatch, datetime(2026, 11, 9, 6, 15, tzinfo=SWE), 0.0)[0] == "CHEAP"


def test_rangordningen_far_tariffen(monkeypatch):
    import nordpool
    monkeypatch.setattr(nordpool, "prices_include_vat", lambda: False)
    monkeypatch.setattr(nordpool, "_vat_factor", lambda: 1.25)
    c = {"tou_extra": 0.5, "tou_weekdays": True, "tou_months": [11, 3], "tou_hours": [6, 22]}
    monkeypatch.setattr(nordpool, "cost_settings", lambda: c)
    monday_7 = datetime(2026, 11, 9, 7, 0, tzinfo=SWE)
    assert abs(nordpool.tou_spot_extra(monday_7, c) - 0.4) < 1e-9            # 0,50 inkl. moms = 0,40 i spotbas
    assert nordpool.tou_spot_extra(datetime(2026, 11, 8, 7, 0, tzinfo=SWE), c) == 0.0   # söndag


def test_contract_prices_drive_pump_comparison(monkeypatch):
    import gpm
    import nordpool
    import distribution_tariff
    import ew_settings
    monkeypatch.setattr(gpm.GlobalPriorityManager, '_restore_compressor_lock', lambda self: None)
    settings = {'price_country': 'CZ', 'price_buy_mode': 'fixed', 'price_buy_fixed': 2.0}
    monkeypatch.setattr(ew_settings, 'get', lambda k, d=None: settings.get(k, d))
    when = datetime(2026, 11, 9, 7, tzinfo=SWE)
    mode = gpm.GlobalPriorityManager()
    mode.evaluate(_state(when, current_price=10, dynamic_limit=2, hysteresis=.1))
    assert mode.last_price_mode == 'CHEAP'
    settings.update(price_buy_mode='hdo', price_hdo_entity='sensor.hdo', price_buy_nt=1, price_buy_vt=4)
    monkeypatch.setattr(distribution_tariff, 'schedule_for', lambda e: [
        (datetime(2026, 11, 9, 0, tzinfo=SWE), datetime(2026, 11, 9, 8, tzinfo=SWE), 'NT'),
        (datetime(2026, 11, 9, 8, tzinfo=SWE), datetime(2026, 11, 10, 0, tzinfo=SWE), 'VT')])
    mode = gpm.GlobalPriorityManager()
    mode.evaluate(_state(when, current_price=10, dynamic_limit=2, hysteresis=.1))
    assert mode.last_price_mode == 'CHEAP'
    mode.evaluate(_state(when.replace(hour=9), current_price=0, dynamic_limit=2, hysteresis=.1))
    assert mode.last_price_mode == 'EXPENSIVE'
