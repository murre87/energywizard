"""Utökat facit för gpm (steg 4a): värmeåterkoppling, bortaläge, varmvattnets ML, spaextra och elbilens laddtak, de nycklar de 2 600 ursprungliga
scenarierna aldrig gav planeringen. Se tests/gpm_ext_gen.py. Facit fångar beteendet så som det var när täckningen lades till."""
import ast
import collections
import gzip
import json
import os
from pathlib import Path

import pytest

import contracts
import gpm_ext_gen as ext
import gpm_golden_gen as base

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "gpm_golden_ext.json.gz")
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def decisions():
    return ext.run()


def test_the_decisions_are_exactly_the_recorded_ones(decisions):
    with gzip.open(FIX, "rt", encoding="utf-8") as f:
        want = json.load(f)
    assert len(decisions) == len(want) == ext.N
    for si, (got_seq, want_seq) in enumerate(zip(decisions, want)):
        for k, (g, w) in enumerate(zip(got_seq, want_seq)):
            assert g == w, f"scenario {si} steg {k}: {sorted(set(g) ^ set(w)) or [x for x in g if g[x] != w.get(x)][:3]}"


def test_every_key_gpm_reads_is_now_exercised_except_the_documented_one():
    tree = ast.parse((ROOT / "smartbox" / "gpm.py").read_text(encoding="utf-8"))
    reads = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "get" and isinstance(n.func.value, ast.Name) \
                and n.func.value.id == "state" and n.args and isinstance(n.args[0], ast.Constant):
            reads.add(n.args[0].value)
    seen = {k for s in ext.scenarios() for st in s for k in st} | {k for s in base.scenarios() for st in s for k in st}
    assert reads - seen == {"heat_glide_hours"}, f"gpm läser nycklar som ingen scenario ger den: {sorted(reads - seen)}"
    flagged = {k for k, v in contracts.schema("planner-input")["properties"].items() if v.get("x-covered-by-scenarios")}
    assert flagged == seen & set(contracts.schema("planner-input")["properties"])


def test_the_extended_scenarios_reach_the_branches_they_were_made_for(decisions):
    logs = collections.Counter()
    for s in decisions:
        for a in s:
            for line in a["log"]:
                for kw in ("Rumsåterkoppling", "BORTA", "VARMVATTEN, ML", "LEGIONELLA", "SPA", "Återgång", "glida"):
                    if kw.lower() in line.lower():
                        logs[kw] += 1
    assert min(logs[k] for k in ("Rumsåterkoppling", "BORTA", "VARMVATTEN, ML", "SPA", "Återgång")) >= 100, dict(logs)
    assert logs["glida"] >= 1                                     # golvvaktens glidning nås också
    modes = {a["pump_mode"] for s in decisions for a in s}
    assert modes == {"CHEAP", "EXPENSIVE"}


def test_decisions_and_inputs_of_the_extended_scenarios_follow_the_contracts(decisions):
    import jsonschema
    dv = jsonschema.Draft202012Validator(contracts.schema("planner-decision"))
    iv = jsonschema.Draft202012Validator(contracts.schema("planner-input"), format_checker=jsonschema.FormatChecker())
    for seq, dec in zip(ext.scenarios(n=40), decisions[:40]):
        for st, a in zip(seq, dec):
            assert dv.is_valid(contracts.decision_to_wire(a)), [e.message for e in dv.iter_errors(contracts.decision_to_wire(a))][:1]
            errs = list(iv.iter_errors(contracts.planner_input_to_wire(st)))
            assert not errs, f"{errs[0].message[:150]} @ {list(errs[0].path)}"
