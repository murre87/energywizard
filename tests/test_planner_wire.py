"""Steg 4b-1 av uppdelningen: planeringens indata överlever en tur genom JSON och ger EXAKT samma beslut.

Det är förutsättningen för att planeringen ska kunna bli en egen process: det som Core skickar över gränsen (planner_input_to_wire, JSON) och
det planeringen bygger upp igen (planner_input_from_wire) måste ge samma beslut som den ursprungliga indatan, för alla 4 680 facit-steg
(2 600 ursprungliga + 2 080 utökade). Jämförelsen görs med paritetsverktyget."""
import copy
import json
from datetime import datetime, timezone
from unittest.mock import patch

import pandas as pd

import contracts
import gpm_ext_gen as ext
import gpm_golden_gen as base
import parity


def _patches():
    import gpm
    return (patch.object(gpm.GlobalPriorityManager, "_restore_compressor_lock", lambda self: None), patch("gpm.notifier"),
            patch("gpm.logger"), patch("gpm.learning.get_optimal_pi_params", return_value=(0.5, 0.05)))


def _local():
    import gpm
    eng = gpm.GlobalPriorityManager()
    return lambda st: eng.evaluate(st)


def _over_the_wire():
    """Samma motor, men indatan går först igenom JSON som om den skickats till en annan process."""
    import gpm
    eng = gpm.GlobalPriorityManager()
    def step(st):
        text = json.dumps(contracts.planner_input_to_wire(st), allow_nan=False)
        return eng.evaluate(contracts.planner_input_from_wire(json.loads(text)))
    return step


def _compare(scenarios):
    a, b, c, d = _patches()
    with a, b, c, d:
        return parity.compare(scenarios, _local, _over_the_wire, normalize=contracts.decision_to_wire)


def test_all_original_scenarios_give_identical_decisions_over_the_wire():
    rep = _compare(base.scenarios())
    assert rep.ok, rep.summary()
    assert rep.steps == 2600


def test_all_extended_scenarios_give_identical_decisions_over_the_wire():
    rep = _compare(ext.scenarios())
    assert rep.ok, rep.summary()
    assert rep.steps == 2080


def test_the_wire_form_of_every_type_roundtrips():
    st = {"now": datetime(2026, 11, 27, 12, 30, tzinfo=timezone.utc), "last_heartbeat": datetime(2026, 11, 27, 12, 29),
          "hw_profile": {(0, 7): 0.7, (4, 19): 0.9}, "heat_horizon": (0.5, 3.0), "heat_ml_w": [0.1, 0.2, -0.3, -0.01], "all_prices": [0.5, None, 1.2],
          "ev_plan": pd.DataFrame({"t_slot": pd.to_datetime(["2026-11-27 12:30", "2026-11-27 12:45"]), "nissan_kw": [0.0, 4.6], "nissan_panic": [False, True]}),
          "car_ids": ["nissan"], "indoor_temp": None, "peak_shaving_enabled": True, "max_fuse_a": 25}
    wire = json.loads(json.dumps(contracts.planner_input_to_wire(st), allow_nan=False))
    back = contracts.planner_input_from_wire(wire)
    assert back["now"] == st["now"] and back["now"].tzinfo is not None and back["last_heartbeat"] == st["last_heartbeat"] and back["last_heartbeat"].tzinfo is None
    assert back["hw_profile"] == st["hw_profile"] and back["heat_horizon"] == (0.5, 3.0) and isinstance(back["heat_horizon"], tuple)
    assert back["heat_ml_w"] == st["heat_ml_w"] and back["all_prices"] == st["all_prices"] and back["indoor_temp"] is None and back["max_fuse_a"] == 25
    pd.testing.assert_frame_equal(back["ev_plan"], st["ev_plan"])
    assert back["ev_plan"]["t_slot"].dtype == st["ev_plan"]["t_slot"].dtype


def test_empty_and_missing_plans_and_input_survive():
    for ev in (pd.DataFrame(), None):
        wire = json.loads(json.dumps(contracts.planner_input_to_wire({"ev_plan": ev, "car_ids": []})))
        back = contracts.planner_input_from_wire(wire)
        assert back["ev_plan"] is None or back["ev_plan"].empty
    assert contracts.planner_input_from_wire(json.loads(json.dumps(contracts.planner_input_to_wire({})))) == {}


def test_a_changed_wire_form_is_caught_by_the_parity_check():
    """Om omvandlingen tappar något (här: laddplanen kastas) syns det som en skillnad i besluten, inte tyst."""
    import gpm
    def lossy():
        eng = gpm.GlobalPriorityManager()
        def step(st):
            back = contracts.planner_input_from_wire(json.loads(json.dumps(contracts.planner_input_to_wire(st))))
            back.pop("ev_plan", None)
            return eng.evaluate(back)
        return step
    a, b, c, d = _patches()
    with a, b, c, d:
        rep = parity.compare(base.scenarios(n=60), _local, lossy, normalize=contracts.decision_to_wire)
    assert not rep.ok
    assert any(p.endswith("_limit_a") or p == "log[len]" or p.startswith("log[") for _, _, p, _, _ in rep.diffs)
