"""Kontrakten mellan Core och planeringen (contracts/*.schema.json, smartbox/contracts.py) och paritetsverktyget (smartbox/parity.py).

Facit är de riktiga besluten: 2 600 beslut ur gpm:s golden-scenarier (tests/gpm_golden_gen.py) och en riktig laddplan ur
decisions.calculate_ev_charge_plan. Ändras beslutens form måste schemat ändras med, så att uppdelningen aldrig tappar något tyst."""
import copy
import importlib
import json
import sys
from unittest.mock import patch

import pytest

import jsonschema  # noqa: E402  (krävs: saknas det ska testet fallera, inte hoppas över; CI installerar det)

import contracts  # noqa: E402
import parity  # noqa: E402
import gpm_golden_gen as gen  # noqa: E402

DECISION = jsonschema.Draft202012Validator(contracts.schema("planner-decision"), format_checker=jsonschema.FormatChecker())
EVPLAN = jsonschema.Draft202012Validator(contracts.schema("ev-plan"), format_checker=jsonschema.FormatChecker())


def _engine_factory():
    import gpm
    def make():
        eng = gpm.GlobalPriorityManager()
        return lambda st: eng.evaluate(st)
    return make


@pytest.fixture(scope="module")
def golden_decisions():
    import gpm
    out = []
    with patch.object(gpm.GlobalPriorityManager, "_restore_compressor_lock", lambda self: None), patch("gpm.notifier"), \
            patch("gpm.logger"), patch("gpm.learning.get_optimal_pi_params", return_value=(0.5, 0.05)):
        for seq in gen.scenarios():
            eng = gpm.GlobalPriorityManager()
            for st in seq:
                out.append(contracts.decision_to_wire(eng.evaluate(dict(st))))
    return out


def test_schemas_are_valid_and_versioned():
    for name in ("planner-decision", "ev-plan"):
        s = contracts.schema(name)
        jsonschema.Draft202012Validator.check_schema(s)
        assert s["x-api-version"] == contracts.API_VERSION and s["$id"].endswith(f"{name}.schema.json")


def test_every_real_decision_follows_the_contract(golden_decisions):
    assert len(golden_decisions) == 2600
    for i, d in enumerate(golden_decisions):
        errs = sorted(DECISION.iter_errors(d), key=lambda e: list(e.path))
        assert not errs, f"beslut {i}: {errs[0].message} @ {list(errs[0].path)}"
        json.dumps(d, allow_nan=False)                                    # går att skicka som JSON


def test_the_decision_contract_rejects_what_it_should(golden_decisions):
    base = next(d for d in golden_decisions if d["nissan_set_phases"] is not None)
    assert DECISION.is_valid(base)
    def broken(mutate):
        d = copy.deepcopy(base); mutate(d); return d
    bad = {
        "ny okänd nyckel": broken(lambda d: d.update(ny_nyckel=1)),
        "saknar pump_mode": broken(lambda d: d.pop("pump_mode")),
        "okänt pumpläge": broken(lambda d: d.update(pump_mode="TURBO")),
        "laddström över taket": broken(lambda d: d.update(tesla_limit_a=33)),
        "negativ laddström": broken(lambda d: d.update(nissan_limit_a=-1)),
        "bråktal som laddström": broken(lambda d: d.update(nissan_limit_a=6.5)),
        "fasläge 2": broken(lambda d: d.update(tesla_set_phases=2)),
        "solgräns över 100": broken(lambda d: d.update(solar_limit_pct=101)),
        "loggrad som inte är text": broken(lambda d: d["log"].append(5)),
        "solinfo saknar fält": broken(lambda d: d["solar_info"]["ev"].pop("wants")),
        "okänd sollast": broken(lambda d: d["solar_info"].update(garage={"active": True, "min_w": 1, "wants": True})),
        "solordning med okänd last": broken(lambda d: d.update(solar_order=["ev", "ufo"])),
        "bil utan limit_a": broken(lambda d: d["ev"]["nissan"].pop("limit_a")),
        "panic som tal": broken(lambda d: d.update(tesla_panic=1)),
    }
    for what, d in bad.items():
        assert not DECISION.is_valid(d), what


def test_new_cars_and_optional_keys_are_allowed_by_pattern(golden_decisions):
    d = copy.deepcopy(golden_decisions[0])
    d.update(id4_limit_a=10, id4_panic=False, id4_set_phases=None, heat_feedback_sp=21.5, heat_feedback_for_mode="CHEAP",
             heat_ml_rate=0.3, hw_ml_start=47.0, house_solar_active=True, solar_order=["ev", "battery", "spa", "hotwater", "house"])
    d["ev"]["id4"] = {"limit_a": 10, "panic": False, "set_phases": None}
    assert DECISION.is_valid(d), [e.message for e in DECISION.iter_errors(d)][:1]


def test_wire_conversion_is_json_safe():
    import datetime
    import numpy as np
    w = contracts.plain({"a": np.int64(3), "b": np.float64(1.5), "c": float("nan"), "d": float("inf"), "e": datetime.datetime(2026, 11, 27, 12, 0),
                         "f": (1, 2), "g": np.bool_(True), "h": None})
    assert w == {"a": 3, "b": 1.5, "c": None, "d": None, "e": "2026-11-27T12:00:00", "f": [1, 2], "g": True, "h": None}
    json.dumps(w, allow_nan=False)
    with pytest.raises(TypeError):
        contracts.plain({"x": object()})


@pytest.fixture
def real_plan(monkeypatch):
    import pandas as pd
    import test_ev_plan_heating as t
    for name, mod in t._stubs(8.0).items():
        monkeypatch.setitem(sys.modules, name, mod)
    monkeypatch.syspath_prepend(t.SMARTBOX)
    sys.modules.pop("decisions", None)
    decisions = importlib.import_module("decisions")
    monkeypatch.setattr(pd, "read_sql", t._read_sql_factory(8.0))
    def run(cars):
        specs = {c: {"name": c, "max_a": 16, "phases": "auto", "battery_kwh": 77, "max_charge_kw": 7.4} for c in cars}
        data = {"car_ids": cars, "car_specs": specs, "heating_model": t.MODEL}
        sched = {}
        for c in cars:
            data.update({f"{c}_soc": 50, f"{c}_plugged_in": True, f"{c}_phases": None})
            sched[c] = {0: {"enabled": True, "target_time": "07:00", "target_soc": 80, "panic_mode": False}}
        cfg = {"fuse_size_a": 20, "power_limit_kw_bas": 8.0, "power_limit_kw_hog": 8.0, "peak_shaving_enabled": True}
        return decisions.calculate_ev_charge_plan(t.NOW, sched, data, cfg)
    yield run
    sys.modules.pop("decisions", None)


@pytest.mark.parametrize("cars", [["id4"], ["nissan", "tesla"]])
def test_the_real_ev_plan_follows_the_contract(real_plan, cars):
    df = real_plan(cars)
    wire = contracts.ev_plan_to_wire(df)
    assert len(wire["rows"]) == len(df) > 20
    errs = list(EVPLAN.iter_errors(wire))
    assert not errs, f"{errs[0].message} @ {list(errs[0].path)}"
    for c in cars:
        assert all(f"{c}_kw" in r and f"{c}_panic" in r for r in wire["rows"])
    assert all("t_hour" not in r for r in wire["rows"]) and "t_hour" in df.columns      # intern kolumn följer inte med
    assert any(r[f"{cars[0]}_kw"] > 0 for r in wire["rows"])                           # planen laddar faktiskt
    json.dumps(wire, allow_nan=False)


def test_ev_plan_contract_rejects_bad_rows_and_empty_plan_is_ok(real_plan):
    assert contracts.ev_plan_to_wire(None) == {"rows": []} and EVPLAN.is_valid({"rows": []})
    good = contracts.ev_plan_to_wire(real_plan(["id4"]))
    for what, mutate in {
        "okänd kolumn": lambda r: r.update(hemlig=1),
        "negativ effekt": lambda r: r.update(id4_kw=-1.0),
        "panic som text": lambda r: r.update(id4_panic="ja"),
        "saknar t_slot": lambda r: r.pop("t_slot"),
        "tid som tal": lambda r: r.update(t_slot=5),
    }.items():
        d = copy.deepcopy(good)
        mutate(d["rows"][3])
        assert not EVPLAN.is_valid(d), what


# ---- paritetsverktyget ----
def test_diff_finds_values_keys_lengths_and_types():
    assert parity.diff({"a": 1, "b": [1, 2]}, {"a": 1, "b": [1, 2]}) == []
    got = {p: (x, y) for p, x, y in parity.diff({"a": 1.0, "b": [1, 2], "c": "x", "d": True, "e": None, "g": 1},
                                                {"a": 1.5, "b": [1, 2, 3], "c": "y", "d": 1, "f": 2, "e": 0, "g": 1})}
    assert got["a"] == (1.0, 1.5) and got["b[len]"] == (2, 3) and got["c"] == ("x", "y")
    assert "d" in got and "e" in got                                   # True != 1 och None != 0 räknas som skillnader
    assert got["f"] == ("<saknas>", 2)
    assert parity.diff(1.0, 1.0 + 1e-12) == [] and parity.diff(1.0, 1.1, tol=0.2) == []


def test_the_engine_is_deterministic_across_all_golden_scenarios():
    """Samma indata genom två nya instanser ger exakt samma beslut: förutsättningen för att kunna jämföra gammalt och nytt."""
    import gpm
    with patch.object(gpm.GlobalPriorityManager, "_restore_compressor_lock", lambda self: None), patch("gpm.notifier"), \
            patch("gpm.logger"), patch("gpm.learning.get_optimal_pi_params", return_value=(0.5, 0.05)):
        rep = parity.compare(gen.scenarios(n=60), _engine_factory(), _engine_factory(), normalize=contracts.decision_to_wire)
    assert rep.ok, rep.summary()
    assert rep.scenarios == 60 and rep.steps == 600


def test_parity_reports_a_changed_implementation_with_where_and_what():
    import gpm
    make = _engine_factory()
    def drifting():
        f = make()
        def step(st):
            a = f(st)
            a["pump_target_temp"] = round(a["pump_target_temp"] + 0.5, 3)          # den "nya" implementationen avviker
            a["log"] = a["log"] + ["extra rad"]
            return a
        return step
    with patch.object(gpm.GlobalPriorityManager, "_restore_compressor_lock", lambda self: None), patch("gpm.notifier"), \
            patch("gpm.logger"), patch("gpm.learning.get_optimal_pi_params", return_value=(0.5, 0.05)):
        rep = parity.compare(gen.scenarios(n=3, steps=4), make, drifting, normalize=contracts.decision_to_wire)
    assert not rep.ok
    paths = {p for _, _, p, _, _ in rep.diffs}
    assert "pump_target_temp" in paths and any(p.startswith("log[") for p in paths)
    assert "pump_target_temp" in rep.summary()
    cut = parity.compare(gen.scenarios(n=3, steps=4), lambda: (lambda st: {"x": 1}), lambda: (lambda st: {"x": 2}), max_diffs=5)
    assert len(cut.diffs) == 5 and cut.truncated
