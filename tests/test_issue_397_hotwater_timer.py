"""#397: varmvatten "Till" med tid går tillbaka till Auto av sig själv. "Tills jag ändrar" och "Från" som förut."""
import os

import timed_override as to

T = 1_800_000_000.0


def test_går_ut_när_tiden_passerat():
    ov = {"hotwater": "on", "hotwater_until": str(int(T - 1))}
    assert to.expired(ov, "hotwater", T) is True


def test_inte_innan():
    assert to.expired({"hotwater": "on", "hotwater_until": str(int(T + 60))}, "hotwater", T) is False


def test_utan_tid_som_förut():
    assert to.expired({"hotwater": "on", "hotwater_until": ""}, "hotwater", T) is False
    assert to.expired({"hotwater": "on"}, "hotwater", T) is False


def test_redan_auto_rörs_inte():
    assert to.expired({"hotwater": "auto", "hotwater_until": str(int(T - 1))}, "hotwater", T) is False


def test_giltiga_längder():
    assert to.minutes(30) == 30 and to.minutes("360") == 360
    assert to.minutes(5) is None and to.minutes(600) is None and to.minutes(None) is None and to.minutes("x") is None


def test_kopplat_i_motor_och_app():
    root = os.path.join(os.path.dirname(__file__), "..")
    rd = lambda *p: open(os.path.join(root, *p), encoding="utf-8").read()
    assert 'timed_override.expired(all_overrides, "hotwater", time.time())' in rd("smartbox", "main.py")
    app = rd("ewapp", "app.py")
    assert 'set_override("hotwater_until"' in app and '"until": intval(ov.get("hotwater_until"))' in app
    assert "return hotwaterSheet();" in rd("ewapp", "static", "app.js")
