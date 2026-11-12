"""Batteriplanen lär sig (smartbox/battery_learning.py) - mot ett simulerat batteri med känd
verkningsgrad och kapacitet."""
import math
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "smartbox")))

from battery_learning import learn, apply, realized_saving, describe, planning_kw, segments

CFG = {"capacity_kwh": 10.0, "max_power_w": 5000.0, "efficiency": 0.9}


def _battery(cycles=4, eff=0.9, cap=11.0, kw=3.0):
    """Minutvisa mätningar: ladda 20->90 %, vila, ladda ur 90->20 %, vila - upprepat."""
    ec = ed = math.sqrt(eff)
    t, soc, out = 0.0, 20.0, []
    def run(p_kw, until):
        nonlocal t, soc
        while (p_kw > 0 and soc < until) or (p_kw < 0 and soc > until):
            out.append((t, round(soc, 2), p_kw * 1000))
            de = p_kw / 60.0 * (ec if p_kw > 0 else 1 / ed)
            soc += de / cap * 100.0
            t += 60
    for _ in range(cycles):
        run(kw, 90.0)
        for _ in range(30):
            out.append((t, round(soc, 2), 0.0)); t += 60
        run(-kw, 20.0)
        for _ in range(30):
            out.append((t, round(soc, 2), 0.0)); t += 60
    return out


def _quarters(n, watts, step_s=60.0, start=0.0):
    """n hela kvartar med ett prov i minuten."""
    out, t = [], start
    for _ in range(n):
        for _s in range(15):
            out.append((t, 50.0, watts))
            t += step_s
    return out


def test_hittar_verkningsgrad_och_kapacitet():
    m = learn(_battery(eff=0.88, cap=11.0), [], CFG)
    assert abs(m["learned"]["efficiency"] - 0.88) < 0.02
    assert abs(m["learned"]["capacity_kwh"] - 11.0) < 0.3
    assert m["use"]["efficiency"] == m["learned"]["efficiency"]
    assert m["use"]["capacity_kwh"] == m["learned"]["capacity_kwh"]
    assert abs(m["use"]["charge_kw"] - 3.0) < 0.01 and abs(m["use"]["discharge_kw"] - 3.0) < 0.01


def test_for_lite_data_anvands_inte():
    m = learn(_battery(cycles=2), [], CFG)
    assert "efficiency" not in m["use"] and "capacity_kwh" not in m["use"]
    assert "behöver 1" in describe(m)


def test_orimliga_varden_anvands_inte():
    m = learn(_battery(eff=0.9, cap=30.0), [], CFG)          # 300 % av konfigurerat
    assert "capacity_kwh" not in m["use"] and "capacity_kwh" in m["learned"]


def test_solprognosens_fel_per_timme():
    pairs = [(9, 2000, 1000)] * 6 + [(13, 4000, 4400)] * 6 + [(16, 1500, 1500)] * 2   # 16: för få timmar
    m = learn([], pairs, CFG)
    assert m["use"]["solar_factor"] == {9: 0.5, 13: 1.1}


def test_toppar_styr_inte_laddeffekten():
    """#251: p95 av enstaka 11 kW-prov är 11 kW. Kvartsmedlet är (11 + 14×2,5) / 15 = 3,07 kW."""
    samples = []
    t = 0.0
    for _q in range(12):
        for i in range(15):
            samples.append((t, 50.0, 11000.0 if i == 0 else 2500.0))
            t += 60.0
    m = learn(samples, [], {"max_power_w": 11000.0, "capacity_kwh": 15.0})
    assert abs(m["learned"]["charge_kw"] - 3.07) < 0.02
    assert m["use"]["charge_kw"] == m["learned"]["charge_kw"]
    text = describe(m)
    assert "laddar med 3.1 kW" in text and "inlärt 3.1" not in text


def test_hallen_effekt_under_trettio_procent_anvands():
    """2,5 kW mot ett 11 kW-datablad är under det korta 30 %-golvet, men hålls kvart efter kvart."""
    m = learn(_quarters(10, 2500.0), [], {"max_power_w": 11000.0, "capacity_kwh": 15.0})
    assert m["learned"]["charge_kw_quarters"] == 10
    assert abs(m["use"]["charge_kw"] - 2.5) < 0.05


def test_kort_lag_effekt_sanker_inte_planen():
    m = learn(_quarters(3, 2500.0), [], {"max_power_w": 11000.0})
    assert "charge_kw" not in m["use"] and "charge_kw" not in m["learned"]
    m = learn(_quarters(5, 2500.0), [], {"max_power_w": 11000.0})
    assert abs(m["learned"]["charge_kw"] - 2.5) < 0.05
    assert "charge_kw" not in m["use"]
    assert "används inte" in describe(m)


def test_enstaka_svaga_kvartar_sanker_inte_percentilen():
    """Tappade skrivningar i en fjärdedel av kvartarna är inte batteriets nya max."""
    samples = _quarters(3, 2500.0) + _quarters(9, 10000.0, start=3 * 900.0)
    m = learn(samples, [], {"max_power_w": 11000.0})
    assert m["use"]["charge_kw"] > 8.0


def test_max_charge_w_ar_tak_aven_nar_inlart_ar_hogre():
    m = learn(_battery(kw=5.0), [], {"max_power_w": 11000.0, "max_charge_w": 3000, "capacity_kwh": 10.0})
    assert abs(m["learned"]["charge_kw"] - 5.0) < 0.05
    assert abs(m["use"]["charge_kw"] - 3.0) < 0.05
    txt = describe(m)
    assert "laddar med 3.0 kW (inlärt 5.0)" in txt
    assert planning_kw({"max_power_w": 11000, "max_charge_w": 3000}, "charge") == 3.0
    assert planning_kw({"max_power_w": 11000, "charge_kw": 2.5, "max_charge_w": 3000}, "charge") == 2.5
    assert planning_kw({"max_power_w": 5000}, "discharge") == 5.0


def test_apply_lagger_inlart_over_config():
    s = apply({**CFG, "control": "styr"}, {"use": {"efficiency": 0.86, "charge_kw": 2.5, "solar_factor": {9: 0.5}}})
    assert s["efficiency"] == 0.86 and s["capacity_kwh"] == 10.0 and s["charge_kw"] == 2.5 and s["solar_factor"] == {9: 0.5}
    assert apply(CFG, None)["solar_factor"] == {}


def test_uppmatt_besparing():
    # 1 h: huset drar 3 kW, batteriet laddar ur 3 kW -> nätet 0. Utan batteri hade 3 kWh köpts.
    rows = [(60.0, 0.0, -3000.0, 2.0)] * 60
    saved = realized_saving(rows, lambda s: s * 1.25 + 0.6, lambda s: s)
    assert abs(saved - 3.0 * (2.0 * 1.25 + 0.6)) < 0.01
    # laddning från nätet kostar: 1 h à 3 kW vid 0,2 kr
    cost = realized_saving([(60.0, 3000.0, 3000.0, 0.2)] * 60, lambda s: s * 1.25 + 0.6, lambda s: s)
    assert cost < 0


def test_pass_delas_vid_riktningsbyte_och_luckor():
    samples = [(i * 60.0, 20 + i, 3000.0) for i in range(10)] + [(3600.0 + i * 60, 30 - i, -3000.0) for i in range(10)]
    segs = segments(samples)
    assert [s[0] for s in segs] == ["in", "out"]


def test_medianprofil_for_planen():
    from battery_learning import median_load_profile
    rows = [(0, 7, 1.0), (0, 7, 1.2), (0, 7, 9.0), (0, 8, 2.0), (0, 8, 2.0)]   # en extrem topp kl 7
    p = median_load_profile(rows, min_days=2)
    assert p[(0, 7)] == 1.2 and p[(0, 8)] == 2.0                              # medianen bryr sig inte om toppen
    assert median_load_profile(rows, min_days=3) == {(0, 7): 1.2}
    assert apply({}, {"use": {"load_profile": p}})["load_profile"] == p


# ---- plan mot utfall ---------------------------------------------------------------------------------------------
from battery_learning import OUTCOME_MIN_LOAD, apply as _apply, describe as _describe, outcome_bias


def test_utfall_kraver_underlag():
    assert outcome_bias([(1.0, 1.2)] * (OUTCOME_MIN_LOAD - 1), "load")[1] is None
    ratio, use, n = outcome_bias([(1.0, 1.1)] * OUTCOME_MIN_LOAD, "load")
    assert ratio == 1.1 and use == 1.1 and n == OUTCOME_MIN_LOAD


def test_utfall_inom_granser_och_litet_fel_ror_inget():
    assert outcome_bias([(1.0, 2.0)] * 400, "load")[1] == 1.25          # taket
    assert outcome_bias([(1.0, 0.3)] * 400, "solar")[1] == 0.7           # golvet
    assert outcome_bias([(1.0, 1.02)] * 400, "load")[1] is None          # under 3 %: planen lämnas som den är


def test_utfall_sol_bara_soliga_kvartar_och_summor():
    pairs = [(0.0, 0.4)] * 500 + [(2.0, 1.6)] * 30 + [(0.5, 0.4)] * 30   # natt räknas inte; 3,2+... / summor
    ratio, use, n = outcome_bias(pairs, "solar")
    assert n == 60 and ratio == round((1.6 * 30 + 0.4 * 30) / (2.0 * 30 + 0.5 * 30), 3) and use == ratio


def test_utfall_anvands_och_forklaras():
    model = {"learned": {}, "use": {"load_bias": 1.12, "solar_bias": 0.85}}
    s = _apply({"capacity_kwh": 10}, model)
    assert s["load_bias"] == 1.12 and s["solar_bias"] == 0.85
    assert _apply({}, {"use": {}})["load_bias"] == 1.0
    txt = _describe(model)
    assert "förbrukningen blev 12 % högre" in txt and "solen blev 15 % lägre" in txt
