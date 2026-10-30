"""2026-10-30: solladdningen låg kvar på 15 A i upp till fem minuter medan huset köpte 4,6 kW till 2,86 kr. Vid dyr el och import justeras den nu varje minut."""
import zoneinfo
from datetime import datetime, timedelta

from test_marginal_spapaus import _state

SWE = zoneinfo.ZoneInfo("Europe/Stockholm")
DYRA = [1.0] * 64 + [3.0] * 32            # dygnets dyraste tredjedel ligger på 3,0 kr
START = datetime(2026, 10, 30, 9, 0, tzinfo=SWE)


def _session(nu, **over):
    """Ett kör där Nissan ansluten och solöverskott (-2000 W) startar sol-laddningen."""
    from gpm import GlobalPriorityManager

    gpm = GlobalPriorityManager()
    bas = dict(nissan_connected=True, nissan_charge_completed=False, nissan_soc=60.0, tesla_connected=False, avg_net_w=-2000.0, grid_import_w=0.0)
    bas.update(over)
    gpm.evaluate(_state(START, **bas))
    assert gpm.ev_solar_charge_active, "sol-laddningen startade inte"
    return gpm


def _senare(gpm, minuter, **over):
    bas = dict(nissan_connected=True, nissan_charge_completed=False, nissan_soc=60.0, tesla_connected=False)
    bas.update(over)
    return gpm.evaluate(_state(START + timedelta(minutes=minuter), **bas))


def test_solar_charging_is_cut_within_a_minute_when_buying_at_an_expensive_price():
    gpm = _session(START, current_price=3.0, all_prices=DYRA)
    _senare(gpm, 1.5, current_price=3.0, all_prices=DYRA, avg_net_w=4600.0, grid_import_w=4600.0)
    assert gpm.ev_solar_charge_active is False                                                    # nu, inte efter fem minuter


def test_solar_charging_keeps_the_five_minute_pace_when_the_price_is_not_expensive():
    gpm = _session(START, current_price=1.0, all_prices=DYRA)
    _senare(gpm, 1.5, current_price=1.0, all_prices=DYRA, avg_net_w=4600.0, grid_import_w=4600.0)
    assert gpm.ev_solar_charge_active is True                                                     # billig el: oförändrat 5-minutersintervall
    _senare(gpm, 5.5, current_price=1.0, all_prices=DYRA, avg_net_w=4600.0, grid_import_w=4600.0)
    assert gpm.ev_solar_charge_active is False


def test_a_small_import_at_an_expensive_price_does_not_trigger_the_fast_cut():
    gpm = _session(START, current_price=3.0, all_prices=DYRA)
    _senare(gpm, 1.5, current_price=3.0, all_prices=DYRA, avg_net_w=300.0, grid_import_w=300.0)
    assert gpm.ev_solar_charge_active is True                                                     # under 500 W: ingen snabbjustering
