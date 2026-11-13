"""#399: elbilen och husbatteriet får inte båda klartecken mot samma lediga utrymme i säkringen, och husbatteriets
nätladdning begränsas av säkringen (förut alltid full effekt, även vid minuspris när bilen också laddar)."""
import os
from datetime import datetime, timedelta

import battery_control as bc
import fuse_guard
import ramp_budget

T = 1_000_000.0


def model(phases_a, ts=T):
    m = fuse_guard.FuseThermalModel()
    for k in range(10):                      # stabil värme på nivån
        m.update(phases_a, ts - 100 + k * 10)
    m.update(phases_a, ts)
    return m


def test_budget_räknar_bara_andra_lasten_och_glömmer_efter_en_stund():
    b = ramp_budget.RampBudget(pending_s=90)
    b.grant("battery", 7.0, ts=T)
    b.grant("ev", 4.0, ts=T)
    b.grant("ev", -6.0, ts=T)                # minskning registreras inte
    assert b.pending_a("ev", ts=T + 10) == 7.0
    assert b.pending_a("battery", ts=T + 10) == 4.0
    assert b.pending_a("ev", ts=T + 91) == 0.0


def test_bilens_tak_drar_av_batteriets_väntande_ökning():
    m = model([10.0, 10.0, 10.0])            # bilen drar 6 A, 25 A-säkring
    utan = m.ev_cap_a(25, [6.0, 6.0, 6.0], ts=T)
    med = m.ev_cap_a(25, [6.0, 6.0, 6.0], ts=T, pending_a=7.0)
    assert utan == 21 and med == 14          # 6 + (25-10) och 6 + (25-10-7)


def test_bilens_start_drar_också_av():
    m = model([12.0, 12.0, 12.0])
    assert m.ev_cap_a(25, [0, 0, 0], ts=T, pending_a=5.0) == 8


def test_batteriets_tak_räknar_tillbaka_egen_laddning_och_reserverar_bilens():
    m = model([20.0, 15.0, 15.0])            # batteriet laddar redan 3450 W (5 A/fas, trefas)
    cap = m.battery_charge_cap_w(25, battery_w=3450, phases=3, ts=T)
    assert round(cap) == round((25 - 20 + 5) * 230 * 3)
    cap2 = m.battery_charge_cap_w(25, battery_w=3450, phases=3, reserved_a=6.0, ts=T)
    assert round(cap2) == round((25 - 20 + 5 - 6) * 230 * 3)


def test_enfasig_växelriktare_räknas_på_värsta_fasen():
    m = model([20.0, 5.0, 5.0])
    assert round(m.battery_charge_cap_w(25, battery_w=0, phases=1, ts=T)) == 5 * 230


def test_ingen_färsk_mätdata_ger_inget_tak():
    assert fuse_guard.FuseThermalModel().battery_charge_cap_w(25, 0, ts=T) is None


CFG = {"control": "styr", "reserve_soc": 20, "max_soc": 100, "max_power_w": 5000}
ALL = frozenset({"auto", "charge", "discharge", "hold", "idle"})


def state(**kw):
    s = {"soc": 50, "price": 0.5, "avg_net_w": 3000, "meter_fresh": True, "fuse_state": "ok"}
    s.update(kw)
    return s


def test_minuspris_med_laddande_bil_begränsas_av_säkringen():
    d = bc.decide(state(price=-0.1, ev_charging_grid=True, fuse_charge_cap_w=2100.0), CFG, ALL)
    assert d["intent"] == "charge" and d["power_w"] == 2100.0 and d["rule"] == "fuse_cap"
    assert "begränsas till 2100 W" in d["reason"]


def test_planerad_laddning_utan_utrymme_håller():
    d = bc.decide(state(planned_action="charge", planned_power_w=4000, fuse_charge_cap_w=300.0), CFG, ALL)
    assert d["intent"] == "hold" and d["rule"] == "fuse_cap"


def test_utrymme_kvar_ändrar_inget():
    d = bc.decide(state(planned_action="charge", planned_power_w=3000, fuse_charge_cap_w=9000.0), CFG, ALL)
    assert d["intent"] == "charge" and d["power_w"] == 3000 and d["rule"] == "plan"


def test_utan_mätdata_som_förut():
    d = bc.decide(state(price=-0.1), CFG, ALL)
    assert d["intent"] == "charge" and d["power_w"] == 5000


def test_urladdning_påverkas_inte():
    d = bc.decide(state(planned_action="discharge", planned_power_w=3000, fuse_charge_cap_w=0.0), CFG, ALL)
    assert d["intent"] == "discharge"


def test_taket_skrivs_direkt_vid_minskning_men_inte_för_småsteg():
    now = datetime(2026, 11, 13, 12, 0)
    last = {"intent": "charge", "power_w": 3000.0, "rule": "fuse_cap"}
    sänk = {"intent": "charge", "power_w": 2800.0, "rule": "fuse_cap"}
    små = {"intent": "charge", "power_w": 3050.0, "rule": "fuse_cap"}
    håll = {"intent": "hold", "power_w": None, "rule": "fuse_cap"}
    assert bc.should_apply(sänk, last, now, now + timedelta(seconds=60))
    assert not bc.should_apply(små, last, now, now + timedelta(seconds=60))
    assert bc.should_apply(håll, last, now, now + timedelta(seconds=60))


def test_main_kopplar_in_budgeten():
    src = open(os.path.join(os.path.dirname(__file__), "..", "smartbox", "main.py"), encoding="utf-8").read()
    assert 'pending_a=_ramp.pending_a("ev")' in src
    assert '"fuse_charge_cap_w": _battery_fuse_cap_w(battery_state.get("power_w"))' in src
    assert '_ramp.grant("battery"' in src and '_ramp.grant("ev"' in src
