"""#389: hur färska och kompletta indata var sparas i planens ögonblicksbild (schema 2). Gamla bilder (schema 1)
spelas fortfarande upp, och kvaliteten styr ingenting."""
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone

import battery_plan
import plan_snapshot as S


def example():
    now = datetime(2026, 10, 25, 0, tzinfo=timezone.utc)
    slots = [{'t': now + timedelta(minutes=15 * i), 'buy': p, 'sell': p / 2, 'load_kw': 1.0, 'solar_kw': 0, 'ev_kw': 0}
             for i, p in enumerate([0.2, 2, -0.1, 1])]
    params = dict(soc0_kwh=1, capacity_kwh=2, reserve_kwh=0.2, max_kwh=2, charge_kw=1, discharge_kw=1, eff=0.9,
                  allowed={'auto', 'charge', 'hold', 'discharge'})
    return slots, params, battery_plan.optimize(slots, **params), now


Q = {"prices": {"source": "elprisetjustnu", "coverage": 0.95, "missing": 2, "horizon_h": 24.0},
     "solar": {"source": "mixed", "coverage": 0.5}, "load": {"source": "profile", "coverage": 1.0},
     "soc": {"source": "battery", "known": True, "age_s": None, "secret": "x"}, "token": "must-not-leak"}


def test_kvalitet_sparas_och_spelas_upp():
    snap = S.build(*example(), quality=Q)
    assert snap["schema_version"] == 2
    assert snap["input_quality"]["prices"] == {"source": "elprisetjustnu", "coverage": 0.95, "missing": 2, "horizon_h": 24.0}
    assert "secret" not in S.canonical(snap) and "must-not-leak" not in S.canonical(snap)
    assert S.replay(json.loads(S.canonical(snap)))["matches"]


def test_gammal_ögonblicksbild_schema_1_spelas_fortfarande_upp():
    snap = S.build(*example())
    old = {k: v for k, v in snap.items() if k != "plan_id"}
    old["schema_version"] = 1
    old["plan_id"] = hashlib.sha256(S.canonical(old).encode()).hexdigest()
    assert S.replay(json.loads(S.canonical(old)))["matches"]


def test_icke_ändliga_tal_blir_okända():
    q = S.normalize_quality({"prices": {"coverage": float("nan"), "missing": 1}})
    assert q["prices"]["coverage"] is None and q["prices"]["missing"] == 1


def test_planen_räknar_fram_kvaliteten():
    src = open(os.path.join(os.path.dirname(__file__), "..", "smartbox", "battery_plan.py"), encoding="utf-8").read()
    assert 'r["input_quality"] = quality' in src and "plan_snapshot.capture(slots, params, r, now, quality=quality)" in src
