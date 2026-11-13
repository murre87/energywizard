"""Varmvattnets start/stopp (water_setpoints): stoppet sänks aldrig under normal, och värden
som pumpen inte tar emot upptäcks och försöks igen i stället för att tyst glömmas."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "smartbox"))

import water_setpoints as ws


class ThermiaLike:
    """Som Emils Thermia via Husdata 2026-11-13: stopp under 50 fäster inte, registret visar 60."""
    def __init__(self, min_stop=50.0, readable=True):
        self.min_stop, self.readable = min_stop, readable
        self.stop, self.start = 60.0, 45.0
        self.writes = []

    def set_water_stop_temp(self, v):
        self.writes.append(("stop", v))
        self.stop = v if v >= self.min_stop else 60.0
        return True

    def set_water_start_temp(self, v):
        self.writes.append(("start", v))
        self.start = v
        return True

    def read_water_setpoints(self):
        return (self.stop, self.start) if self.readable else None


def test_plan_dyrt_sanker_bara_start():
    assert ws.plan(40, 50) == (50.0, 35.0)      # dyrt: start 35 spärrar, stopp kvar på 50
    assert ws.plan(50, 50) == (50.0, 45.0)
    assert ws.plan(60, 50) == (60.0, 55.0)      # legionella/solöverskott: höjs som förut
    assert ws.plan(10, 50) == (50.0, 5.0)       # borta/effekttak: start 5 spärrar


def test_dyr_timme_fäster_på_thermia():
    p, s = ThermiaLike(), ws.WaterSetpoints()
    assert s.apply(p, 40.0, 50.0) is True
    assert (p.stop, p.start) == (50.0, 35.0)    # förr: stopp 40 skrevs och pumpen visade 60


def test_gamla_beteendet_hade_gett_60():
    p = ThermiaLike()
    p.set_water_stop_temp(40.0)
    assert p.stop == 60.0                       # låtsaspumpen återger felet vi mätte


def test_inget_omskrivande_när_det_fäst():
    p, s = ThermiaLike(), ws.WaterSetpoints()
    s.apply(p, 40.0, 50.0)
    n = len(p.writes)
    assert s.apply(p, 40.0, 50.0) is True
    assert len(p.writes) == n


def test_värde_som_inte_fäster_försöks_igen_och_varnar(capsys):
    p, s = ThermiaLike(min_stop=55.0), ws.WaterSetpoints()   # normal 50 under pumpens gräns
    for _ in range(5):
        assert s.apply(p, 50.0, 50.0) is False
    stops = [w for w in p.writes if w[0] == "stop"]
    assert len(stops) == ws.MAX_TRIES           # tre försök, sedan slutar den
    out = capsys.readouterr().out
    assert out.count("fäste inte") == ws.MAX_TRIES - 1
    assert out.count("Slutar försöka") == 1


def test_nytt_mål_ger_nya_försök():
    p, s = ThermiaLike(min_stop=55.0), ws.WaterSetpoints()
    for _ in range(4):
        s.apply(p, 50.0, 50.0)
    assert s.apply(p, 60.0, 50.0) is True      # 60 fäster
    assert s.apply(p, 50.0, 50.0) is False     # tillbaka till 50: försöker igen
    assert sum(1 for w in p.writes if w == ("stop", 50.0)) == ws.MAX_TRIES + 1


def test_utan_tillbakaläsning_som_förut():
    p, s = ThermiaLike(readable=False), ws.WaterSetpoints()
    assert s.apply(p, 40.0, 50.0) is True
    n = len(p.writes)
    s.apply(p, 40.0, 50.0)
    assert len(p.writes) == n


class NullDriver:
    def set_water_stop_temp(self, v):
        return False

    def set_water_start_temp(self, v):
        return False


def test_ingen_värmepump_ger_inga_varningar(capsys):
    s = ws.WaterSetpoints()
    for _ in range(4):
        s.apply(NullDriver(), 40.0, 50.0)
    assert capsys.readouterr().out == ""


def test_main_använder_modulen():
    src = open(os.path.join(os.path.dirname(__file__), "..", "smartbox", "main.py"), encoding="utf-8").read()
    assert "water_sp.apply(heat_pump_driver" in src
    assert "set_water_stop_temp(water_target)" not in src
