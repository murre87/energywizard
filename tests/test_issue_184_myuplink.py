"""#184: myUplink-drivrutinen tolkar kompressorstatus (kod 20/40/60/100 eller text som "Kör") som HA-vägen."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "smartbox"))
from drivers.heatpump_myuplink import MyUplinkHeatPumpDriver  # noqa: E402


def run(value, name="Status kompressor", pid="43427"):
    d = MyUplinkHeatPumpDriver({"compressor_running": pid})
    d._points = lambda: [{"parameterId": pid, "parameterName": name, "value": value}]
    return d.read_sensors()["compressor_running"]


def test_koder():
    assert run(20) == 0 and run(60) == 1 and run(40) == 1 and run(100) == 0


def test_text():
    assert run("Kör") == 1 and run("Av") == 0 and run("Stoppar") == 0


def test_frekvens():
    assert run(35.0, "Kompressorfrekvens, aktuell", "41778") == 1
    assert run(0, "Kompressorfrekvens, aktuell", "41778") == 0
