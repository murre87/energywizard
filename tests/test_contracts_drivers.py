"""Steg 2 av uppdelningen: kontrakt för drivrutiner (state och kommandon), batteriplan och batteribeslut (contracts/*.schema.json).

Tre skydd mot att något tappas: (1) varje publik metod på drivrutinsgränssnitten är klassad som kommando eller icke-kommando och kommandona
finns i schemat, (2) vakten i tests/contract_guard.py kontrollerar alla riktiga drivrutinssvar, batteriplaner och batteribeslut i hela sviten,
(3) de här testerna visar att schemana nekar det de ska."""
import ast
import copy
import inspect
import json
from pathlib import Path

import pytest

import contract_guard as cg
import contracts
import jsonschema

ROOT = Path(__file__).resolve().parents[1]
ABCS = {}


def _abcs():
    if not ABCS:
        from drivers import battery, car, charger, heatpump, solar, spa
        ABCS.update(battery=battery.BatteryDriver, car=car.CarDriver, charger=charger.ChargerDriver, heatpump=heatpump.HeatPumpDriver,
                    solar=solar.SolarDriver, spa=spa.SpaDriver)
    return ABCS


def _v(name):
    return jsonschema.Draft202012Validator(contracts.schema(name), format_checker=jsonschema.FormatChecker())


COMMAND = _v("driver-command")
DECISION = _v("battery-decision")
PLAN = _v("battery-plan")


def test_the_new_schemas_are_valid_and_versioned():
    for name in ("driver-state", "driver-command", "battery-plan", "battery-decision"):
        s = contracts.schema(name)
        jsonschema.Draft202012Validator.check_schema(s)
        assert s["x-api-version"] == contracts.API_VERSION and s["$id"].endswith(f"{name}.schema.json")


# ---- gränssnitten: varje metod klassad, kommandona i schemat ----
def test_every_public_driver_method_is_classified_exactly_once():
    for dev, cls in _abcs().items():
        public = {n for n, f in inspect.getmembers(cls, inspect.isfunction) if not n.startswith("_")}
        cmds, non = set(contracts.COMMANDS[dev]), contracts.NON_COMMANDS[dev]
        assert not cmds & non, f"{dev}: både kommando och icke-kommando: {cmds & non}"
        assert public == cmds | non, f"{dev}: oklassade metoder {sorted(public - cmds - non)}, klassade men borta {sorted((cmds | non) - public)}"


def test_command_arguments_match_the_method_signatures():
    for dev, cls in _abcs().items():
        for cmd, args in contracts.COMMANDS[dev].items():
            params = tuple(p for p in inspect.signature(getattr(cls, cmd)).parameters if p != "self")
            assert params == args, f"{dev}.{cmd}: metoden tar {params}, kontraktet säger {args}"


def _sample_args(dev, cmd):
    sample = {"intent": "charge", "power_w": 2000, "mode": "auto", "hvac_mode": "heat", "temperature": 21.0, "amps": 16, "reason": "plan", "phases": 3,
              "delta": 1.0, "offset": -1.0, "minutes": 30, "active": True, "target_c": 21.0, "pct": 50, "temp_c": 38.0, "enable": True, "on": True}
    return {a: sample[a] for a in contracts.COMMANDS[dev][cmd] if a != "now"}


def test_the_command_schema_covers_exactly_the_registered_commands():
    pairs = set()
    for ref in contracts.schema("driver-command")["oneOf"]:
        d = contracts.schema("driver-command")["$defs"][ref["$ref"].rsplit("/", 1)[1]]["properties"]
        pairs.add((d["device"]["const"], d["command"]["const"]))
    assert pairs == {(dev, c) for dev, cs in contracts.COMMANDS.items() for c in cs}
    for dev, cs in contracts.COMMANDS.items():
        for cmd in cs:
            env = {"device": dev, "command": cmd, "args": _sample_args(dev, cmd)}
            errs = list(COMMAND.iter_errors(env))
            assert not errs, f"{dev}.{cmd}: {errs[0].message}"
            assert COMMAND.is_valid({**env, "id": "abc"})


def test_the_command_schema_rejects_what_it_should():
    ok = {"device": "charger", "command": "set_limit_a", "args": {"amps": 16, "reason": "plan"}}
    assert COMMAND.is_valid(ok)
    def with_(**kw):
        d = copy.deepcopy(ok); d.update(kw); return d
    bad = {
        "okänd enhet": with_(device="toaster"),
        "okänt kommando": with_(command="explode"),
        "kommando på fel enhet": with_(device="spa"),
        "extra argument": with_(args={"amps": 16, "turbo": True}),
        "saknat argument": with_(args={}),
        "fel typ": with_(args={"amps": "sexton"}),
        "bråktal som ampere": with_(args={"amps": 6.5}),
        "ampere över 32": with_(args={"amps": 33}),
        "negativa ampere": with_(args={"amps": -1}),
        "saknar args": {"device": "charger", "command": "turn_on"},
        "okänd nyckel överst": with_(hemlig=1),
        "fasbyte till 2": {"device": "charger", "command": "set_phases", "args": {"phases": 2}},
        "solgräns över 100": {"device": "solar", "command": "set_export_limit_pct", "args": {"pct": 101}},
        "paus noll minuter": {"device": "heatpump", "command": "pause", "args": {"minutes": 0}},
        "okänt pumpläge": {"device": "heatpump", "command": "set_operating_mode", "args": {"mode": "turbo"}},
        "batteriavsikt som inte finns": {"device": "battery", "command": "apply_intent", "args": {"intent": "explode"}},
        "turn_on med argument": {"device": "charger", "command": "turn_on", "args": {"x": 1}},
    }
    for what, env in bad.items():
        assert not COMMAND.is_valid(env), what


# ---- state ----
def test_normalization_fixes_exactly_the_known_loose_types():
    n = contracts.normalize_driver_state
    assert n("car", {"soc": 50.0, "plugged_in": 1.0})["plugged_in"] is True and n("car", {"plugged_in": 0})["plugged_in"] is False
    assert n("car", {"plugged_in": None})["plugged_in"] is None and n("car", {"plugged_in": "on"})["plugged_in"] is True and n("car", {"plugged_in": "?"})["plugged_in"] is None
    assert n("solar", {"status": 2})["status"] == "2" and n("solar", {"status": None})["status"] is None
    assert n("heatpump_sensors", {"compressor_running": 1, "alarm_active": 0, "operating_mode": 3}) == {"compressor_running": True, "alarm_active": False, "operating_mode": "3"}
    assert "_raw" not in n("heatpump_sensors", {"_raw": {"a": 1}, "_received_at": "x"}) and n("heatpump_sensors", {"_raw": {}, "_received_at": "x"})["_received_at"] == "x"
    assert n("battery", {"soc_pct": float("nan"), "power_w": 5})["soc_pct"] is None
    assert n("battery", {"ny_nyckel": 7})["ny_nyckel"] == 7                     # allt annat lämnas orört
    assert n("charger", {}) == {} and n("spa_state", None) == {}
    with pytest.raises(ValueError):
        n("toaster", {})


@pytest.mark.no_contract_guard
def test_state_schemas_reject_what_they_should():
    bad = [("battery", {"soc_pct": 150}), ("battery", {"soc_pct": -1}), ("battery", {"available_charge_w": -5}), ("battery", {"modules": []}),
           ("car", {"soc": 101}), ("car", {"soc": "full"}), ("charger", {"phases": 2}), ("charger", {"current_a": -1}), ("charger", {"current_is_limit": "ja"}),
           ("solar", {"pv_power_w": -1}), ("heatpump_state", {"indoor_temp": "kall"}), ("heatpump_state", {"dhw_temp_observation": {"value_c": "x"}}),
           ("spa_power_detail", {"overheated": "ja"}), ("spa_state", {"current_temp": [1]})]
    for kind, state in bad:
        assert cg.check(kind, state), (kind, state)
    good = [("battery", {"soc_pct": 55.5, "power_w": -1200, "soc_source": "ha_reported", "extra": 1}), ("car", {"soc": None, "plugged_in": True}),
            ("charger", {"status": "charging", "phases": 3, "current_a": 16.0}), ("solar", {"status": "ok", "pv_power_w": 0}),
            ("spa_activities", {"heating": True, "pump1": "on"}), ("heatpump_state", {"mode": "heat", "fault": None})]
    for kind, state in good:
        assert cg.check(kind, state) == [], (kind, state)


@pytest.mark.no_contract_guard
def test_the_guard_reports_a_violating_driver_and_skips_mocks():
    from unittest.mock import MagicMock
    from drivers.charger import NullChargerDriver
    class Bad(NullChargerDriver):
        def read_state(self):
            return {"status": "charging", "phases": 2}
    cg.VIOLATIONS.clear()
    cg._wrap(Bad, "read_state", "charger")
    assert Bad().read_state()["phases"] == 2 and any("phases" in v for v in cg.VIOLATIONS)
    cg.VIOLATIONS.clear()
    cg._report("charger", {"status": MagicMock(), "phases": 2})                 # mock-värden hoppas över
    assert cg.VIOLATIONS == []
    cg._report("charger", {"status": "ok", "phases": 1, "x": float("inf")})     # inf blir null i kontraktet: ok
    assert cg.VIOLATIONS == []


# ---- batteribeslut ----
def test_battery_decision_rules_match_battery_control_exactly():
    tree = ast.parse((ROOT / "smartbox" / "battery_control.py").read_text(encoding="utf-8"))
    rules = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "out" and len(n.args) >= 2 and isinstance(n.args[1], ast.Constant):
            rules.add(n.args[1].value)
        if isinstance(n, ast.Dict):
            for k, v in zip(n.keys, n.values):
                if isinstance(k, ast.Constant) and k.value == "rule" and isinstance(v, ast.Constant):
                    rules.add(v.value)
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Tuple):
            for t in n.targets:
                if isinstance(t, ast.Tuple):
                    for e, v in zip(t.elts, n.value.elts):
                        if isinstance(e, ast.Name) and e.id == "rule" and isinstance(v, ast.Constant):
                            rules.add(v.value)
    assert rules == set(contracts.schema("battery-decision")["properties"]["rule"]["enum"])


def test_battery_decision_contract_rejects_what_it_should():
    ok = {"intent": "charge", "power_w": 3000.0, "reason": "Planen: laddar nu.", "rule": "plan"}
    assert DECISION.is_valid(ok) and DECISION.is_valid({"intent": None, "power_w": None, "reason": "Av.", "rule": "av"})
    for what, d in {"okänd avsikt": {**ok, "intent": "explode"}, "negativ effekt": {**ok, "power_w": -1}, "tom orsak": {**ok, "reason": ""},
                    "okänd regel": {**ok, "rule": "ny_regel"}, "extra nyckel": {**ok, "x": 1}, "saknar regel": {k: v for k, v in ok.items() if k != "rule"}}.items():
        assert not DECISION.is_valid(d), what


# ---- batteriplan ----
SAMPLE_PLAN = {"allow_export": True, "balance_deferred": False, "baseline_cost": 12.5, "cost": 10.0, "saving_kr": 2.5, "reversal_cost_sek": 0.1, "wear_cost_sek": 0.4,
               "style": "balanced", "input_quality": {"prices": {"source": "nordpool", "coverage": 1.0}, "soc": {"source": "ha"}},
               "rows": [{"t": "2026-11-27T12:00:00", "action": "charge", "battery_kw": 2.0, "buy": 0.9, "cost": 0.4, "direction_reversal": False, "grid_kw": 3.0,
                         "soc_kwh": 5.0, "wear_cost_sek": 0.01}], "plan_id": None, "control_ready": True}


def test_battery_plan_contract_accepts_a_real_shaped_plan_and_rejects_bad_ones():
    assert PLAN.is_valid(SAMPLE_PLAN)
    def broken(f):
        d = copy.deepcopy(SAMPLE_PLAN); f(d); return d
    for what, d in {
        "extra nyckel": broken(lambda d: d.update(ny=1)),
        "saknar kostnad": broken(lambda d: d.pop("cost")),
        "kostnad som text": broken(lambda d: d.update(cost="tio")),
        "rad utan tid": broken(lambda d: d["rows"][0].pop("t")),
        "tid som tal": broken(lambda d: d["rows"][0].update(t=5)),
        "negativ slitage": broken(lambda d: d.update(wear_cost_sek=-1)),
        "kvalitet som lista": broken(lambda d: d.update(input_quality=[1])),
        "reversering som text": broken(lambda d: d["rows"][0].update(direction_reversal="ja")),
    }.items():
        assert not PLAN.is_valid(d), what


def test_wire_conversion_of_plan_turns_datetimes_into_text():
    import datetime
    plan = copy.deepcopy(SAMPLE_PLAN)
    plan["rows"][0]["t"] = datetime.datetime(2026, 11, 27, 12, 0)
    wire = contracts.battery_plan_to_wire(plan)
    assert wire["rows"][0]["t"] == "2026-11-27T12:00:00" and PLAN.is_valid(wire)
    json.dumps(wire, allow_nan=False)
