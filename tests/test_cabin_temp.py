"""#610: bilfliken visar kupétemperaturen även när värmen är av.
Egen givare går före. Annars climate-entitetens current_temperature."""
import importlib.util
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _ewapp():
    os.environ.setdefault("POSTGRES_USER", "u")
    os.environ.setdefault("POSTGRES_PASSWORD", "p")
    os.environ.setdefault("POSTGRES_DB", "d")
    os.environ.setdefault("DASHBOARD_PASSWORD", "test")
    os.environ.setdefault("EW_NO_WATCH", "1")
    from starlette.staticfiles import StaticFiles
    original = StaticFiles.__init__

    def quiet(self, *args, **kwargs):
        original(self, *args, **{**kwargs, "check_dir": False})

    StaticFiles.__init__ = quiet
    cwd = os.getcwd()
    os.chdir(ROOT / "ewapp")
    try:
        spec = importlib.util.spec_from_file_location("ewapp_cabin", ROOT / "ewapp" / "app.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        os.chdir(cwd)
        StaticFiles.__init__ = original
    return mod


def _car():
    return {
        "name": "Tesla", "status": "sensor.bil_status", "power": "sensor.bil_power", "soc": "sensor.bil_soc",
        "tracker": "device_tracker.bil", "climate": "climate.bil", "inside": "sensor.bil_inne",
        "arrival": None, "dist": None, "destination": None, "shift": None, "online": None,
        "lock": None, "trunk": None, "frunk": None, "phases": 3, "cap_kwh": 75.0, "facts": {}, "tpms": [],
    }


def _state(inside=None, climate="off", cabin=None):
    st = {
        "sensor.bil_status": {"state": "disconnected"},
        "device_tracker.bil": {"state": "home"},
        "sensor.bil_soc": {"state": "55"},
        "climate.bil": {"state": climate, "attributes": {} if cabin is None else {"current_temperature": cabin}},
    }
    if inside is not None:
        st["sensor.bil_inne"] = {"state": inside}
    return st


def test_kupe_fran_givare_gar_fore_climate_och_saknad_ar_none(monkeypatch):
    ew = _ewapp()
    ew.CARS["bil"] = _car()
    monkeypatch.setattr(ew, "_car_mem_load", lambda: None)
    monkeypatch.setattr(ew, "plan_segments", lambda *a, **k: [])
    monkeypatch.setattr(ew, "plan_blocks_ui", lambda *a, **k: {"blocks": [], "kwh": 0.0})
    monkeypatch.setattr(ew, "plan_slots", lambda *a, **k: [])

    own = ew.car_state("bil", _state(inside="18.5", cabin=11), {})
    assert own["inside"] == 18.5 and own["climate_on"] is False

    fallback = ew.car_state("bil", _state(cabin=11.2), {})
    assert fallback["inside"] == 11.2 and fallback["climate_on"] is False

    heating = ew.car_state("bil", _state(climate="heat_cool", cabin=21), {})
    assert heating["inside"] == 21 and heating["climate_on"] is True

    unavailable = ew.car_state("bil", _state(inside="unavailable", cabin=9), {})
    assert unavailable["inside"] == 9

    assert ew.car_state("bil", _state(), {})["inside"] is None
    cold = ew.car_state("bil", _state(cabin=0), {})
    assert cold["inside"] == 0


@pytest.mark.skipif(subprocess.call(["node", "-e", "process.exit(0)"]) != 0, reason="Node.js krävs")
def test_bilfliken_ritar_kupe_aven_nar_varmen_ar_av():
    script = r"""
const fs = require("fs");
const src = fs.readFileSync("ewapp/static/app.js", "utf8");
const f1 = (x, d = 1) => (x == null ? "–" : Number(x).toFixed(d));
const heatChip = new Function("f1", src.slice(src.indexOf("const heatChip"), src.indexOf("const planPill")) + "\nreturn heatChip;")(f1);
const off = heatChip({ climate_on: false, inside: 12.4 });
const on = heatChip({ climate_on: true, inside: 21 });
const none = heatChip({ climate_on: false, inside: null });
if (!off.includes("Kupé") || !off.includes("12") || off.includes("Värmen är på")) process.exit(1);
if (!on.includes("Värmen är på") || !on.includes("21")) process.exit(1);
if (none !== "") process.exit(1);
const compact = src.slice(src.indexOf("function compact"), src.indexOf("function sunWindow"));
if (!compact.includes("Kupé") || !compact.includes("c.inside")) process.exit(1);
const web = fs.readFileSync("webdashboard/static/app.js", "utf8");
const car = web.slice(web.indexOf("api/car"), web.indexOf("api/car") + 2500);
if (!car.includes("Kupé") || !car.includes("climate_temp")) process.exit(1);
"""
    result = subprocess.run(["node", "-e", script], cwd=ROOT, text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
