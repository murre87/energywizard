"""#396: "Toppa husbatteriet nu till X %" - laddar tills målet, alltid inom säkringen, och säkerhetsreglerna går före."""
import os
from datetime import datetime, timedelta

import battery_control as bc

CFG = {"control": "styr", "reserve_soc": 20, "max_soc": 100, "max_power_w": 5000}
ALL = frozenset({"auto", "charge", "discharge", "hold", "idle"})


def st(**kw):
    s = {"soc": 50, "price": 1.5, "avg_net_w": 2000, "meter_fresh": True, "fuse_state": "ok"}
    s.update(kw)
    return s


def test_toppar_till_målet_med_full_effekt():
    d = bc.decide(st(topup_target=80), CFG, ALL)
    assert d["intent"] == "charge" and d["power_w"] == 5000 and d["rule"] == "topup"
    assert "Toppar batteriet till 80 %, 50 % nu." in d["reason"]


def test_inom_säkringen():
    d = bc.decide(st(topup_target=80, fuse_charge_cap_w=1800.0), CFG, ALL)
    assert d["intent"] == "charge" and d["power_w"] == 1800.0 and d["rule"] == "fuse_cap"


def test_vid_målet_som_vanligt():
    assert bc.decide(st(soc=80, topup_target=80), CFG, ALL)["rule"] != "topup"


def test_säkerhetsregler_går_före():
    assert bc.decide(st(topup_target=80, meter_fresh=False), CFG, ALL)["rule"] == "stale"
    assert bc.decide(st(topup_target=80, fuse_state="overload", fuse_excess_a=3), CFG, ALL)["rule"] == "fuse"


def test_toppning_startar_direkt():
    now = datetime(2026, 11, 14, 9, 0)
    last = {"intent": "auto", "power_w": None, "rule": "default"}
    new = {"intent": "charge", "power_w": 5000, "rule": "topup"}
    assert bc.should_apply(new, last, now, now + timedelta(seconds=30))


def test_kopplat_i_motor_och_app():
    root = os.path.join(os.path.dirname(__file__), "..")
    rd = lambda *p: open(os.path.join(root, *p), encoding="utf-8").read()
    main = rd("smartbox", "main.py")
    assert '"topup_target": _tu_t or None' in main and 'battery_topup_until' in main
    app = rd("ewapp", "app.py")
    assert '@app.post("/api/battery/topup")' in app and '"topup_target": intval(ov.get("battery_topup_target"))' in app
    assert 'api("battery/topup"' in rd("ewapp", "static", "app.js")
