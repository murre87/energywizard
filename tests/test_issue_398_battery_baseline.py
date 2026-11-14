"""#398: vad styrningen gav utöver ett batteri i självförbrukningsläge, räknat på samma uppmätta kvartar."""
import os

import battery_baseline as bb
import battery_plan

CAP, RES, MAX, PC, PD, EFF = 10.0, 2.0, 10.0, 3.0, 3.0, 0.9


def _from_sim(load, solar, buy, actions, soc0):
    """Bygg "uppmätta" kvartar ur en simulering med givna avsikter (som om batteriet faktiskt gjort så)."""
    sl = [{"t": i, "load_kw": l, "solar_kw": s, "buy": b, "sell": b * 0.8} for i, (l, s, b) in enumerate(zip(load, solar, buy))]
    _, rows = battery_plan.simulate(sl, soc0, actions, CAP, RES, MAX, PC, PD, EFF)
    return [{"t": i, "grid_kw": r["grid_kw"], "solar_kw": solar[i], "battery_kw": r["battery_kw"], "buy": buy[i], "sell": buy[i] * 0.8}
            for i, r in enumerate(rows)]


def test_självförbrukning_ger_noll():
    n = 96
    load, solar = [1.0] * n, [0.0] * 40 + [3.0] * 16 + [0.0] * 40
    buy = [1.0] * n
    slots = _from_sim(load, solar, buy, ["auto"] * n, 5.0)
    r = bb.compare(slots, 5.0, CAP, RES, MAX, PC, PD, EFF)
    assert abs(r["saved"]) < 0.01 and r["quarters"] == n


def test_styrning_som_laddar_billigt_ger_besparing():
    n = 96
    load, solar = [1.0] * n, [0.0] * n
    buy = [0.2] * 24 + [1.0] * 48 + [3.0] * 24                 # billig natt, dyr kväll
    actions = ["charge"] * 12 + ["hold"] * 60 + ["auto"] * 24   # ladda på natten, spara till kvällen
    slots = _from_sim(load, solar, buy, actions, 3.0)
    r = bb.compare(slots, 3.0, CAP, RES, MAX, PC, PD, EFF)
    assert r["saved"] > 1.0 and r["selfuse"] > r["actual"]


def test_förbrukningen_är_densamma_i_båda():
    s = [{"t": 0, "grid_kw": 2.0, "solar_kw": 1.0, "battery_kw": 0.5, "buy": 1.0, "sell": 0.5}]
    r = bb.compare(s, 5.0, CAP, RES, MAX, PC, PD, EFF)
    assert r["actual"] == 0.5                                   # 2 kW i en kvart à 1 kr
    assert r["selfuse"] == 0.0                                  # last 2.5 kW = 1 sol + 1.5 ur batteriet


def test_kopplat_i_appen():
    root = os.path.join(os.path.dirname(__file__), "..")
    rd = lambda *p: open(os.path.join(root, *p), encoding="utf-8").read()
    assert '"battery_vs_selfuse": battery' in rd("ewapp", "app.py")
    assert "svBattery() ||" in rd("ewapp", "static", "app.js")
