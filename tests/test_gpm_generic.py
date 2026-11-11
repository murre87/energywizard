"""EnergyWizard Open Fas 2: GPM ska överleva en cykel utan några bilar/spa/sol/värmepump
alls - det är den konkreta bevisningen att "funkar utan något" håller för den LEVANDE
styrlogiken (inte bara config-laddningen, som redan testas i test_config_loader.py)."""
import os
import sys
import pytest
from datetime import datetime, timedelta, timezone

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "smartbox")))

from gpm import GlobalPriorityManager


def test_helt_tomt_state_kraschar_inte():
    """Ett hus utan några konfigurerade delsystem alls skickar i praktiken ett nästan
    tomt state-dict (ingen pump_data, ingen bil, inget spa, ingen sol). GPM ska producera
    overksamma actions, inte kasta ett undantag."""
    engine = GlobalPriorityManager()
    actions = engine.evaluate({"now": datetime(2026, 10, 30, 12, 0, 0), "car_ids": []})
    assert actions["ev"] == {}


def test_noll_bilar_ger_tom_ev_dict_men_rör_inte_befintlig_logik():
    engine = GlobalPriorityManager()
    actions = engine.evaluate({
        "now": datetime(2026, 10, 30, 12, 0, 0),
        "car_ids": [],
        "nissan_soc": 50, "nissan_connected": True,   # finns i state men ska ignoreras när car_ids=[]
        "indoor_temp": 21.0, "indoor_min": 19.0,
    })
    assert actions["ev"] == {}
    # 2026-11-04: inga hårdkodade bilar - utan bilar finns inga bilnycklar alls
    assert "nissan_limit_a" not in actions and "tesla_limit_a" not in actions


def test_manuell_tvangsladdning_funkar_for_en_tredje_bil():
    """Prio 11.5 var tidigare två duplicerade kodblock (en för nissan, en för tesla) -
    nu en loop över car_ids. Bevisar att det funkar för en bil som INTE heter nissan/tesla,
    inte bara att det råkar fungera för de två namnen koden ursprungligen skrevs för."""
    engine = GlobalPriorityManager()
    actions = engine.evaluate({
        "now": datetime(2026, 10, 30, 12, 0, 0),
        "car_ids": ["tredje_bilen"],
        "tredje_bilen_force_amps": 12,
    })
    assert actions["tredje_bilen_limit_a"] == 12
    assert actions["ev"]["tredje_bilen"]["limit_a"] == 12


def test_manuell_paus_funkar_for_en_tredje_bil():
    """Prio 11.6, samma sak - tidigare en hårdkodad tuple, nu car_ids."""
    engine = GlobalPriorityManager()
    actions = engine.evaluate({
        "now": datetime(2026, 10, 30, 12, 0, 0),
        "car_ids": ["tredje_bilen"],
        "tredje_bilen_hold": True,
    })
    assert actions["tredje_bilen_limit_a"] == 0


def test_batteriskydd_funkar_for_en_tredje_bil():
    """30-minuters-batteriskyddet (kontaktorslitage) - tidigare hårdkodad lista, nu car_ids.
    Simulerar att bilen redan laddat i 10 min (under 30-minutersgränsen) och att inget annat
    satt dess strömgräns denna cykel -> skyddet ska tvinga fram minimiströmmen."""
    engine = GlobalPriorityManager()
    now = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
    engine.ev_charging_since["tredje_bilen"] = now - timedelta(minutes=10)
    actions = engine.evaluate({"now": now, "car_ids": ["tredje_bilen"], "tredje_bilen_soc": 60})
    assert actions["tredje_bilen_limit_a"] == 6


def test_utan_car_ids_finns_inga_bilar():
    """2026-11-04: gpm antar inga bilar - main.py skickar car_ids och car_specs ur installationen."""
    engine = GlobalPriorityManager()
    actions = engine.evaluate({
        "now": datetime(2026, 10, 30, 12, 0, 0),
        "nissan_soc": 50, "nissan_connected": True,
        "tesla_soc": 50, "tesla_connected": True,
    })
    assert actions["ev"] == {} and "nissan_limit_a" not in actions


def _engine():
    from unittest.mock import patch
    with patch.object(GlobalPriorityManager, "_restore_compressor_lock", lambda self: None):
        return GlobalPriorityManager()


@pytest.mark.parametrize('configured, reported, expected', [
    ('1', 3, 1), ('1', '3', 1), ('1', 'ThreePhase', 1),
    ('auto', 1, 3), ('auto', '1', 3), ('auto', 'SinglePhase', 3),
    ('1', 1, None), ('auto', 3, None), ('auto', None, None),
])
def test_phase_reset_accepts_numeric_driver_states(configured, reported, expected):
    actions = _engine().evaluate({
        'now': datetime(2026, 11, 11, 12, tzinfo=timezone.utc),
        'current_price': 0.3, 'avg_net_w': 0,
        'car_ids': ['car'], 'car_specs': {'car': {'phases': configured}},
        'car_phases': reported, 'car_connected': False,
    })
    assert actions['car_set_phases'] == expected


def test_plan_laddar_bilar_med_andra_namn_och_egna_faser():
    """Generisk N-bilsladdning: en Kia på 3-fas och en Volvo på 1-fas enligt laddplanen."""
    import pandas as pd
    now = datetime(2026, 11, 4, 2, 7, tzinfo=timezone.utc)
    slot = now.replace(minute=0, tzinfo=None)
    plan = pd.DataFrame([{"t_slot": slot, "kia_kw": 11.0, "volvo_kw": 3.7}])
    a = _engine().evaluate({"now": now, "current_price": 0.3, "all_prices": [0.3] * 24, "avg_net_w": 800,
                            "house_load_a": 4, "ev_actual_a": 0, "max_fuse_a": 35, "ev_plan": plan,
                            "car_ids": ["kia", "volvo"],
                            "car_specs": {"kia": {"name": "Kia", "max_a": 16, "phases": "3"},
                                          "volvo": {"name": "Volvo", "max_a": 16, "phases": "1"}},
                            "kia_soc": 40, "kia_connected": True, "volvo_soc": 60, "volvo_connected": True,
                            "kia_prio": 1, "volvo_prio": 2})
    assert a["kia_limit_a"] >= 6 and a["volvo_limit_a"] >= 6
    assert a["ev"]["kia"]["limit_a"] == a["kia_limit_a"]
    assert any("Sätter Kia:" in l and "Volvo:" in l for l in a["log"])


def test_solladdning_vaxlar_bara_bilar_som_kan():
    """En 1-fasbil (phases "1") växlas aldrig till 3-fas, en bil med phases "auto" får växla."""
    now = datetime(2026, 7, 4, 12, 0, tzinfo=timezone.utc)
    eng = _engine()
    st = {"now": now, "current_price": 0.3, "all_prices": [0.3] * 24, "avg_net_w": -9000, "house_load_a": 2,
          "ev_actual_a": 0, "max_fuse_a": 25, "car_ids": ["zoe", "id4"],
          "car_specs": {"zoe": {"name": "Zoe", "max_a": 16, "phases": "1"}, "id4": {"name": "ID4", "max_a": 16, "phases": "auto"}},
          "zoe_soc": 50, "zoe_connected": True, "zoe_phases": "SinglePhase",
          "id4_soc": 50, "id4_connected": True, "id4_phases": "SinglePhase"}
    a = eng.evaluate(dict(st))
    assert a.get("zoe_set_phases") in (None, 1) and a.get("id4_set_phases") == 3
