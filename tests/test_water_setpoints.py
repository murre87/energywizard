"""Varmvattnets start/stopp (water_setpoints): Thermia via Husdata får bara startvärdet,
övriga pumpar stopp + start som förut, och värden som inte fäster upptäcks och försöks igen."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "smartbox"))

import water_setpoints as ws


class FakePump:
    def __init__(self, start_only=False, min_stop=0.0, min_start=0.0, readable=True):
        self.WATER_START_ONLY = start_only
        self.min_stop, self.min_start, self.readable = min_stop, min_start, readable
        self.stop, self.start = 60.0, 45.0
        self.writes = []

    def set_water_stop_temp(self, v):
        self.writes.append(("stop", v))
        self.stop = v if v >= self.min_stop else 60.0   # som Thermia 2026-11-13: 40 -> visade 60
        return True

    def set_water_start_temp(self, v):
        self.writes.append(("start", v))
        if v >= self.min_start:
            self.start = v
        return True

    def read_water_setpoints(self):
        return (self.stop, self.start) if self.readable else None


def test_plan():
    assert ws.plan(40) == (40.0, 35.0)                   # vanliga pumpar: som före 1.2.74
    assert ws.plan(60) == (60.0, 55.0)
    assert ws.plan(40, start_only=True) == (None, 35.0)  # Thermia/Husdata: bara start
    assert ws.plan(10, start_only=True) == (None, 5.0)


def test_thermia_rör_aldrig_stoppet():
    p, s = FakePump(start_only=True, min_stop=50.0), ws.WaterSetpoints()
    for target in (40.0, 50.0, 60.0, 10.0):
        assert s.apply(p, target) is True
        assert p.start == target - 5
    assert not [w for w in p.writes if w[0] == "stop"]
    assert p.stop == 60.0                                 # installatörens värde orört


def test_thermia_drivrutinen_är_start_only():
    src = open(os.path.join(os.path.dirname(__file__), "..", "smartbox", "drivers", "heatpump_thermia.py"), encoding="utf-8").read()
    assert "WATER_START_ONLY = True" in src


def test_heishamon_får_spärren_via_stoppet():
    """HeishaMon har bara stoppvärdet (SetDHWTemp): dyrt ska ge 40 som före 1.2.74."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "smartbox", "drivers"))
    from drivers import heatpump_heishamon, heatpump_thermiq, heatpump_myuplink, heatpump_nibe_local
    for mod in (heatpump_heishamon, heatpump_thermiq, heatpump_myuplink, heatpump_nibe_local):
        for name in dir(mod):
            cls = getattr(mod, name)
            if isinstance(cls, type) and hasattr(cls, "set_water_stop_temp") and cls.__module__ == mod.__name__:
                assert not getattr(cls, "WATER_START_ONLY", False), name
    p, s = FakePump(), ws.WaterSetpoints()
    assert s.apply(p, 40.0) is True
    assert (p.stop, p.start) == (40.0, 35.0)


def test_inget_omskrivande_när_det_fäst():
    p, s = FakePump(start_only=True), ws.WaterSetpoints()
    s.apply(p, 40.0)
    n = len(p.writes)
    assert s.apply(p, 40.0) is True
    assert len(p.writes) == n


def test_start_som_inte_fäster_försöks_igen_och_varnar(capsys):
    p, s = FakePump(start_only=True, min_start=40.0), ws.WaterSetpoints()
    for _ in range(5):
        assert s.apply(p, 40.0) is False                  # start 35 under pumpens gräns
    assert sum(1 for w in p.writes if w[0] == "start") == ws.MAX_TRIES
    out = capsys.readouterr().out
    assert out.count("start 35 °C fäste inte, pumpen visar start 45 °C") == ws.MAX_TRIES - 1
    assert out.count("Slutar försöka") == 1


def test_stopp_som_inte_fäster_på_vanlig_pump(capsys):
    p, s = FakePump(min_stop=50.0), ws.WaterSetpoints()
    for _ in range(4):
        assert s.apply(p, 40.0) is False
    assert "stopp 40 °C och start 35 °C fäster inte, pumpen visar stopp 60 °C" in capsys.readouterr().out


def test_nytt_mål_ger_nya_försök():
    p, s = FakePump(start_only=True, min_start=40.0), ws.WaterSetpoints()
    for _ in range(4):
        s.apply(p, 40.0)
    assert s.apply(p, 60.0) is True
    assert s.apply(p, 40.0) is False
    assert sum(1 for w in p.writes if w == ("start", 35.0)) == ws.MAX_TRIES + 1


def test_utan_tillbakaläsning_som_förut():
    p, s = FakePump(readable=False), ws.WaterSetpoints()
    assert s.apply(p, 40.0) is True
    n = len(p.writes)
    s.apply(p, 40.0)
    assert len(p.writes) == n


class NullDriver:
    def set_water_stop_temp(self, v):
        return False

    def set_water_start_temp(self, v):
        return False


def test_ingen_värmepump_ger_inga_varningar(capsys):
    s = ws.WaterSetpoints()
    for _ in range(4):
        s.apply(NullDriver(), 40.0)
    assert capsys.readouterr().out == ""


def test_main_använder_modulen():
    src = open(os.path.join(os.path.dirname(__file__), "..", "smartbox", "main.py"), encoding="utf-8").read()
    assert 'water_sp.apply(heat_pump_driver, gpm_actions["water_target_temp"]' in src
    assert "set_water_stop_temp(water_target)" not in src


def test_växelventilen_loggas():
    root = os.path.join(os.path.dirname(__file__), "..", "smartbox")
    assert '"hotwater_valve":       reg[30]' in open(os.path.join(root, "pump.py"), encoding="utf-8").read()
    lg = open(os.path.join(root, "logger.py"), encoding="utf-8").read()
    assert "ADD COLUMN IF NOT EXISTS hotwater_valve" in lg and '"hotwater_valve": p.get("hotwater_valve")' in lg
