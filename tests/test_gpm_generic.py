"""EnergyWizard Open Fas 2: GPM ska överleva en cykel utan några bilar/spa/sol/värmepump
alls - det är den konkreta bevisningen att "funkar utan något" håller för den LEVANDE
styrlogiken (inte bara config-laddningen, som redan testas i test_config_loader.py)."""
import os
import sys
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
    # Den gamla platta nyckeln påverkas inte av car_ids - oförändrad algoritm körs ändå
    assert "nissan_limit_a" in actions


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


def test_default_car_ids_speglar_nissan_tesla_som_idag():
    """Ingen car_ids i state alls (main.py skickar inte det här än, Fas 3) -> defaultar
    till dagens två bilar, så befintlig drift/tester inte påverkas."""
    engine = GlobalPriorityManager()
    actions = engine.evaluate({
        "now": datetime(2026, 10, 30, 12, 0, 0),
        "nissan_soc": 50, "nissan_connected": True,
        "tesla_soc": 50, "tesla_connected": True,
    })
    assert set(actions["ev"].keys()) == {"nissan", "tesla"}
    assert actions["ev"]["nissan"]["limit_a"] == actions["nissan_limit_a"]
    assert actions["ev"]["tesla"]["limit_a"] == actions["tesla_limit_a"]
