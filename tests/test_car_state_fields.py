"""car_state() måste skicka laddnivå, status, kabel, hemma och laddning till appen. 2026-11-14: en kommentar mitt
på return-raden (#385/#390) gjorde att allt efter den blev bortkommenterat - bilarna visade "–" fast HA hade värdet."""
import ast
import os

REQUIRED = {"key", "name", "soc", "soc_stale", "status", "plugged", "home", "charging", "power_kw", "mode", "amps",
            "phases", "online", "charge_now_target", "limit_note", "goal_risk"}


def test_car_state_returnerar_alla_fält():
    src = open(os.path.join(os.path.dirname(__file__), "..", "ewapp", "app.py"), encoding="utf-8").read()
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == "car_state")
    rets = [n for n in ast.walk(fn) if isinstance(n, ast.Return) and isinstance(n.value, ast.Dict)]
    keys = {k.value for r in rets for k in r.value.keys if isinstance(k, ast.Constant)}
    missing = REQUIRED - keys
    assert not missing, f"car_state saknar {sorted(missing)}"
