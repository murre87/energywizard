"""Prio 3.6: två bilar under 50 % före kl 06 delar säkring eller turas om (#302)."""
from datetime import datetime, timezone

import gpm

SPECS = {
    "nissan": {"name": "Nissan", "max_a": 20},
    "tesla": {"name": "Tesla", "max_a": 16},
}


def _state(**over):
    st = {
        "nissan_soc": 30, "tesla_soc": 40,
        "nissan_connected": True, "tesla_connected": True,
        "ev_fuse_cap_a": 20, "avg_net_w": 0,
    }
    st.update(over)
    return st


def test_delar_nar_sakringen_racker_till_bada():
    actions = {"nissan_limit_a": 0, "tesla_limit_a": 16, "log": []}
    now = datetime(2026, 11, 12, 4, 10, tzinfo=timezone.utc)
    assert gpm.ensure_morning_floor_share(actions, _state(), ["nissan", "tesla"], SPECS, 6, now, actions["log"])
    assert actions["nissan_limit_a"] >= 6
    assert actions["tesla_limit_a"] >= 6
    assert "delar säkringen" in actions["log"][-1]


def test_turas_om_nar_sakringen_bara_racker_till_en():
    actions = {"nissan_limit_a": 0, "tesla_limit_a": 16, "log": []}
    now = datetime(2026, 11, 12, 4, 10, tzinfo=timezone.utc)
    assert gpm.ensure_morning_floor_share(
        actions, _state(ev_fuse_cap_a=10), ["nissan", "tesla"], SPECS, 6, now, actions["log"],
    )
    assert actions["nissan_limit_a"] == 10
    assert actions["tesla_limit_a"] == 0
    assert "Säkringen räcker bara till en bil" in actions["log"][-1]


def test_rors_inte_efter_klockan_sex():
    actions = {"nissan_limit_a": 0, "tesla_limit_a": 16, "log": []}
    now = datetime(2026, 11, 12, 7, 0, tzinfo=timezone.utc)
    assert not gpm.ensure_morning_floor_share(actions, _state(), ["nissan", "tesla"], SPECS, 6, now, actions["log"])
    assert actions["nissan_limit_a"] == 0
    assert actions["log"] == []
