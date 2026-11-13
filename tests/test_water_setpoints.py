"""Varmvattnets start/stopp (water_setpoints): Thermia via Husdata får bara startvärdet inom
pumpens intervall, övriga pumpar stopp + start som förut, och kontrollen görs nästa kvart
(gatewayen visar nyskrivna värden först efter ungefär en halv minut)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "smartbox"))

import water_setpoints as ws


class FakePump:
    """Ett skrivet värde syns först vid nästa läsning efter den som följer direkt (som Husdata)."""
    def __init__(self, start_only=False, start_range=None, min_stop=0.0, min_start=0.0, readable=True):
        self.WATER_START_ONLY = start_only
        if start_range:
            self.WATER_START_RANGE = start_range
        self.min_stop, self.min_start = min_stop, min_start
        self.stop, self.start = 60.0, 45.0
        self.pending = None
        self.writes = []
        if not readable:
            self.read_water_setpoints = None

    def set_water_stop_temp(self, v):
        self.writes.append(("stop", v))
        if v >= self.min_stop:
            self.pending = ("stop", v)
        return True

    def set_water_start_temp(self, v):
        self.writes.append(("start", v))
        if v >= self.min_start:
            self.pending_start = v
        return True

    def tick(self):                                       # en kvart går: gatewayen har hunnit uppdatera
        if self.pending:
            self.stop = self.pending[1]
            self.pending = None
        if getattr(self, "pending_start", None) is not None:
            self.start, self.pending_start = self.pending_start, None

    def read_water_setpoints(self):
        return (self.stop, self.start)


def run(p, s, target, quarters=1):
    res = None
    for _ in range(quarters):
        res = s.apply(p, target)
        p.tick()
    return res


def test_plan():
    assert ws.plan(40) == (40.0, 35.0)                              # vanliga pumpar: som före 1.2.74
    assert ws.plan(60) == (60.0, 55.0)
    assert ws.plan(40, start_only=True) == (None, 35.0)             # Thermia/Husdata: bara start
    assert ws.plan(10, True, (30.0, 55.0)) == (None, 30.0)          # borta/effekttak: inom 30-55
    assert ws.plan(62, True, (30.0, 55.0)) == (None, 55.0)


def test_thermia_drivrutinen():
    src = open(os.path.join(os.path.dirname(__file__), "..", "smartbox", "drivers", "heatpump_thermia.py"), encoding="utf-8").read()
    assert "WATER_START_ONLY = True" in src
    assert "WATER_START_RANGE = (30.0, 55.0)" in src


def test_thermia_rör_aldrig_stoppet():
    p, s = FakePump(start_only=True, start_range=(30.0, 55.0)), ws.WaterSetpoints()
    for target, want in ((40.0, 35.0), (50.0, 45.0), (60.0, 55.0), (10.0, 30.0)):
        run(p, s, target, 2)
        assert p.start == want
    assert not [w for w in p.writes if w[0] == "stop"]
    assert p.stop == 60.0


def test_kontrollen_görs_nästa_kvart_utan_falsk_varning(capsys):
    p, s = FakePump(start_only=True), ws.WaterSetpoints()
    assert s.apply(p, 40.0) is False                     # skrivet, inte kontrollerat än
    assert p.read_water_setpoints()[1] == 45.0           # gatewayen visar fortfarande det gamla
    p.tick()
    assert s.apply(p, 40.0) is True                      # nästa kvart: bekräftat
    assert capsys.readouterr().out == ""
    n = len(p.writes)
    assert s.apply(p, 40.0) is True
    assert len(p.writes) == n                            # inget omskrivande


def test_heishamon_får_spärren_via_stoppet():
    """HeishaMon har bara stoppvärdet (SetDHWTemp): dyrt ska ge 40 som före 1.2.74."""
    from drivers import heatpump_heishamon, heatpump_thermiq, heatpump_myuplink, heatpump_nibe_local
    for mod in (heatpump_heishamon, heatpump_thermiq, heatpump_myuplink, heatpump_nibe_local):
        for name in dir(mod):
            cls = getattr(mod, name)
            if isinstance(cls, type) and hasattr(cls, "set_water_stop_temp") and cls.__module__ == mod.__name__:
                assert not getattr(cls, "WATER_START_ONLY", False), name
    p, s = FakePump(), ws.WaterSetpoints()
    assert run(p, s, 40.0, 2) is True
    assert (p.stop, p.start) == (40.0, 35.0)


def test_start_som_inte_fäster_försöks_igen_och_varnar(capsys):
    p, s = FakePump(start_only=True, min_start=40.0), ws.WaterSetpoints()
    for _ in range(6):
        assert run(p, s, 40.0) is False
    assert sum(1 for w in p.writes if w[0] == "start") == ws.MAX_TRIES
    out = capsys.readouterr().out
    assert out.count("start 35 °C fäste inte, pumpen visar start 45 °C") == ws.MAX_TRIES - 1
    assert out.count("Slutar försöka") == 1


def test_stopp_som_inte_fäster_på_vanlig_pump(capsys):
    p, s = FakePump(min_stop=50.0), ws.WaterSetpoints()
    run(p, s, 40.0, 5)
    assert "stopp 40 °C och start 35 °C fäster inte, pumpen visar stopp 60 °C" in capsys.readouterr().out


def test_nytt_mål_ger_nya_försök():
    p, s = FakePump(start_only=True, min_start=40.0), ws.WaterSetpoints()
    run(p, s, 40.0, 5)
    assert run(p, s, 60.0, 2) is True
    run(p, s, 40.0)
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
