"""Steg 3 av uppdelningen: planeringens indata (contracts/planner-input.schema.json) = det delade tillståndet mellan Core och planeringen.

Nyckeluppsättningen jämförs mot koden åt båda håll (gpm.py läser, main.py skickar), så att en ny, borttagen eller omdöpt nyckel inte kan
passera gränsen utan att kontraktet ändras. Typerna är facit ur de 2 600 scenarierna där de finns (x-evidence)."""
import ast
import copy
import json
import re
from pathlib import Path

import jsonschema
import pytest

import contracts
import gpm_golden_gen as gen

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = contracts.schema("planner-input")
INPUT = jsonschema.Draft202012Validator(SCHEMA, format_checker=jsonschema.FormatChecker())
PROPS = SCHEMA["properties"]
PATTERNS = list(SCHEMA["patternProperties"])


def _fkey(node):
    """('static', 'x') för en konstant nyckel, ('dyn', '_suffix') för f'{bil}_suffix', annars None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return ("static", node.value)
    if isinstance(node, ast.JoinedStr) and len(node.values) == 2 and isinstance(node.values[0], ast.FormattedValue) and isinstance(node.values[1], ast.Constant):
        return ("dyn", node.values[1].value)
    return None


def _gpm_reads():
    tree = ast.parse((ROOT / "smartbox" / "gpm.py").read_text(encoding="utf-8"))
    static, dyn = set(), set()
    for n in ast.walk(tree):
        key = None
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "get" and isinstance(n.func.value, ast.Name) \
                and n.func.value.id == "state" and n.args:
            key = _fkey(n.args[0])
        elif isinstance(n, ast.Subscript) and isinstance(n.value, ast.Name) and n.value.id == "state":
            key = _fkey(n.slice)
        if key:
            (static if key[0] == "static" else dyn).add(key[1])
    return static, dyn


def _main_provides():
    tree = ast.parse((ROOT / "smartbox" / "main.py").read_text(encoding="utf-8"))
    static, dyn = set(), set()
    def take(k):
        key = _fkey(k)
        if key:
            (static if key[0] == "static" else dyn).add(key[1])
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name) and t.id == "gpm_state" and isinstance(n.value, ast.Dict):
                    [take(k) for k in n.value.keys]
                if isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name) and t.value.id == "gpm_state":
                    take(t.slice)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "update" and isinstance(n.func.value, ast.Name) and n.func.value.id == "gpm_state":
            for a in n.args:
                if isinstance(a, ast.Dict):
                    [take(k) for k in a.keys]
    return static, dyn


def _pattern_for(suffix):
    probe = f"nissan{suffix}"
    return [p for p in PATTERNS if re.search(p, probe)]


def test_schema_is_valid_versioned_and_states_its_evidence():
    jsonschema.Draft202012Validator.check_schema(SCHEMA)
    assert SCHEMA["x-api-version"] == contracts.API_VERSION and SCHEMA["required"] == []
    ev = {k: v["x-evidence"] for k, v in PROPS.items()}
    assert set(ev.values()) == {"golden", "main-code", "scenario", "unverified"}
    assert sum(1 for v in ev.values() if v == "golden") >= 40


def test_the_schema_matches_what_gpm_reads_and_main_sends_in_both_directions():
    reads, reads_dyn = _gpm_reads()
    sends, sends_dyn = _main_provides()
    assert {"car_ids", "outdoor_avg_5d"} <= reads | sends
    assert reads - set(PROPS) == set(), f"gpm läser nycklar som kontraktet saknar: {sorted(reads - set(PROPS))}"
    assert sends - set(PROPS) == set(), f"main skickar nycklar som kontraktet saknar: {sorted(sends - set(PROPS))}"
    assert set(PROPS) - (reads | sends) == set(), f"kontraktet har nycklar som varken läses eller skickas: {sorted(set(PROPS) - (reads | sends))}"
    # flaggorna är exakt skillnaderna mellan läsare och skickare
    assert {k for k, v in PROPS.items() if v.get("x-not-provided-by-main")} == reads - sends
    assert {k for k, v in PROPS.items() if v.get("x-unused-by-planner")} == sends - reads
    # per-bil-nycklar: varje suffix som koden använder täcks av ett mönster, och varje mönster används av något
    for suffix in reads_dyn | sends_dyn:
        assert _pattern_for(suffix), f"inget mönster för per-bil-nyckeln <bil>{suffix}"
    used = {p for suffix in reads_dyn | sends_dyn for p in _pattern_for(suffix)}
    assert set(PATTERNS) - used == set(), f"mönster som ingen kod använder: {sorted(set(PATTERNS) - used)}"


def test_known_gaps_are_the_ones_we_documented():
    """Det enda som är kvar: en inställning gpm läser men main aldrig skickar. Rättas den ska flaggan tas bort här och i schemat."""
    assert {k for k, v in PROPS.items() if v.get("x-not-provided-by-main")} == {"heat_glide_hours"}
    assert {k for k, v in PROPS.items() if v.get("x-unused-by-planner")} == set()                 # städat i steg 4a
    assert {k for k, v in PROPS.items() if v["x-evidence"] == "unverified"} == {"heat_glide_hours"}


def test_every_golden_scenario_input_follows_the_contract():
    n = 0
    for seq in gen.scenarios():
        for st in seq:
            wire = contracts.planner_input_to_wire(st)
            errs = list(INPUT.iter_errors(wire))
            assert not errs, f"indata {n}: {errs[0].message[:160]} @ {list(errs[0].path)}"
            json.dumps(wire, allow_nan=False)
            n += 1
    assert n == 2600


@pytest.fixture(scope="module")
def sample():
    st = next(s for seq in gen.scenarios() for s in seq if "ev_plan" in s and len(s["ev_plan"]))
    return contracts.planner_input_to_wire(st)


def test_the_input_contract_rejects_what_it_should(sample):
    assert INPUT.is_valid(sample) and isinstance(sample["ev_plan"], dict) and sample["ev_plan"]["rows"]
    def broken(f):
        d = copy.deepcopy(sample); f(d); return d
    for what, d in {
        "okänd nyckel": broken(lambda d: d.update(ny_nyckel=1)),
        "temperatur som text": broken(lambda d: d.update(indoor_temp="varm")),
        "peak_shaving som null": broken(lambda d: d.update(peak_shaving_enabled=None)),
        "tid som tal": broken(lambda d: d.update(now=5)),
        "priser som text": broken(lambda d: d.update(all_prices="dyrt")),
        "bil med soc över 100": broken(lambda d: d.update(nissan_soc=150)),
        "negativ tvångsström": broken(lambda d: d.update(nissan_force_amps=-1)),
        "inkopplad som text": broken(lambda d: d.update(nissan_connected="ja")),
        "bilspec utan max_a": broken(lambda d: d["car_specs"]["nissan"].pop("max_a")),
        "bilspec med okänt fasläge": broken(lambda d: d["car_specs"]["nissan"].update(phases="7")),
        "sol utan sunny": broken(lambda d: d["sun_day"].pop("sunny")),
        "laddplansrad utan tid": broken(lambda d: d["ev_plan"]["rows"][0].pop("t_slot")),
        "negativ laddeffekt": broken(lambda d: d["ev_plan"]["rows"][0].update(nissan_kw=-1.0)),
        "laddplan som lista": broken(lambda d: d.update(ev_plan=[])),
    }.items():
        assert not INPUT.is_valid(d), what


def test_empty_input_and_unknown_sensors_are_allowed(sample):
    assert INPUT.is_valid({})                                                  # gpm klarar en helt tom indata
    d = copy.deepcopy(sample)
    d.update(indoor_temp=None, outdoor_avg_5d=None, current_price=None, heat_stop_outdoor=None)    # givare som saknas = null
    d.pop("car_ids")
    assert INPUT.is_valid(d), [e.message for e in INPUT.iter_errors(d)][:1]


def test_new_cars_and_empty_plan_pass_by_pattern(sample):
    d = copy.deepcopy(sample)
    d["car_ids"].append("id4")
    d["car_specs"]["id4"] = {"name": "ID.4", "max_a": 16, "phases": "3"}
    d.update(id4_soc=None, id4_connected=True, id4_charge_completed=False, id4_force_amps=0, id4_phases=None, id4_prio=3, id4_hold=None)
    d["ev_plan"] = {"rows": []}
    assert INPUT.is_valid(d), [e.message for e in INPUT.iter_errors(d)][:1]
    d["ev_plan"] = None
    assert INPUT.is_valid(d)
