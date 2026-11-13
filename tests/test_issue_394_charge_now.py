"""#394: "Ladda nu till X %" avslutas av sig själv vid målet, urdragen kabel eller efter 24 h. Utan mål som förut."""
import os

import charge_now as cn

T = 1_800_000_000.0


def ov(target="80", amps="16", until=T + 3600):
    return {"tesla_force_amps": amps, "tesla_charge_now_target": target, "tesla_charge_now_until": str(until)}


def test_fortsätter_under_målet():
    assert cn.should_end(ov(), "tesla", 60, True, T) == (False, None)


def test_slutar_vid_målet():
    assert cn.should_end(ov(), "tesla", 80, True, T) == (True, "target")


def test_slutar_när_kabeln_dras_ur():
    assert cn.should_end(ov(), "tesla", 60, False, T) == (True, "unplugged")


def test_slutar_efter_24_timmar():
    assert cn.should_end(ov(until=T - 1), "tesla", 60, True, T) == (True, "timeout")


def test_okänd_laddnivå_laddar_vidare_till_tidsgränsen():
    assert cn.should_end(ov(), "tesla", None, True, T) == (False, None)


def test_utan_mål_som_förut():
    assert cn.should_end(ov(target=""), "tesla", 100, False, T) == (False, None)


def test_stoppad_på_annat_sätt_städas_upp():
    assert cn.should_end(ov(amps="0"), "tesla", 50, True, T) == (True, "stopped")


def test_ogiltigt_mål_ignoreras():
    assert cn.target({"x_charge_now_target": "abc"}, "x") is None
    assert cn.target({"x_charge_now_target": "150"}, "x") is None


def test_återställning_tillbaka_till_planen():
    keys = cn.clear_keys("tesla")
    assert keys["tesla_force_amps"] == "0" and keys["tesla_charge_now_target"] == "" and keys["force_ev_recalc"] == "true"


def test_kopplat_i_motorn_och_appen():
    root = os.path.join(os.path.dirname(__file__), "..")
    main = open(os.path.join(root, "smartbox", "main.py"), encoding="utf-8").read()
    assert "charge_now.should_end(all_overrides, _c, car_soc.get(_c)" in main
    app = open(os.path.join(root, "ewapp", "app.py"), encoding="utf-8").read()
    assert 'set_override(f"{car}_charge_now_target"' in app and '"charge_now_target": charge_now_target or None' in app
    js = open(os.path.join(root, "ewapp", "static", "app.js"), encoding="utf-8").read()
    assert "target_soc: +b.dataset.x.slice(1)" in js
