"""Fas 0 (EnergyWizard Open): config-filerna ska parsa, och ett tomt hus (inga elbilar,
ingen värmepump/sol/spa) ska bygga en komplett uppsättning Null-drivrutiner utan fel -
det är den konkreta bevisningen att "funkar utan något" håller, inte bara en förhoppning."""
from pathlib import Path

from house_config import (
    build_car_drivers, build_charger_drivers, build_heat_pump_driver,
    build_solar_driver, build_spa_driver, load_house_config,
)
from drivers.car import NullCarDriver
from drivers.car_generic import NissanCarDriver, TeslaCarDriver
from drivers.charger import NullChargerDriver
from drivers.charger_easee import EaseeChargerDriver
from drivers.heatpump import NullHeatPumpDriver
from drivers.heatpump_thermia import ThermiaHusdataHeatPumpDriver
from drivers.solar import NullSolarDriver
from drivers.solar_solaredge import SolarEdgeSolarDriver
from drivers.spa import NullSpaDriver
from drivers.spa_gecko import GeckoSpaDriver

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "config" / "house_config.example.yaml"
EMIL = ROOT / "config" / "examples" / "emil_house.yaml"


def test_example_och_emil_parsar():
    for path in (EXAMPLE, EMIL):
        cfg = load_house_config(str(path))
        assert "house_id" in cfg


def test_tomt_hus_ger_bara_null_drivrutiner():
    cfg = load_house_config(str(EXAMPLE))
    assert build_car_drivers(cfg) == []
    assert isinstance(build_heat_pump_driver(cfg), NullHeatPumpDriver)
    assert isinstance(build_solar_driver(cfg), NullSolarDriver)
    assert isinstance(build_spa_driver(cfg), NullSpaDriver)


def test_tomt_hus_null_drivrutiner_kraschar_inte_vid_anrop():
    """Null-drivrutinerna ska gå att anropa precis som riktiga - ingen NotImplementedError
    eller AttributeError för att de är "tomma", bara overksamma svar."""
    cfg = load_house_config(str(EXAMPLE))
    hp, sol, spa = build_heat_pump_driver(cfg), build_solar_driver(cfg), build_spa_driver(cfg)
    assert hp.read_sensors() == {}
    hp.set_room_temp(21.0); hp.set_water_stop_temp(55.0); hp.set_operating_mode("heat")
    assert sol.read_production() == {"pv_power_w": None, "today_kwh": None}
    assert sol.supports_curtailment() is False
    sol.set_export_limit_pct(50)
    assert spa.read_state() == {"current_temp": None, "target_temp": None, "heating": None}
    assert spa.read_power_w() is None
    spa.set_target_temp(30.0); spa.set_economy(True)


def test_emils_hus_bygger_riktiga_drivrutiner():
    """Fas 1: Emils config pekar på riktiga drivrutiner (nissan/tesla/easee), inte Null.
    Anropar INTE read_state()/read_state() på dem här - de pratar med en riktig Home
    Assistant som inte finns i testmiljön. Bara att rätt klasser/id:n byggs upp testas."""
    cfg = load_house_config(str(EMIL))
    cars = build_car_drivers(cfg)
    assert [c.id for c in cars] == ["nissan", "tesla"]
    assert [c.battery_kwh for c in cars] == [40, 75]
    assert isinstance(cars[0], NissanCarDriver)
    assert isinstance(cars[1], TeslaCarDriver)
    chargers = build_charger_drivers(cfg)
    assert set(chargers.keys()) == {"nissan", "tesla"}
    assert all(isinstance(c, EaseeChargerDriver) for c in chargers.values())
    assert all(c.supports_phase_switch for c in chargers.values())
    assert isinstance(build_heat_pump_driver(cfg), ThermiaHusdataHeatPumpDriver)
    assert isinstance(build_solar_driver(cfg), SolarEdgeSolarDriver)
    assert isinstance(build_spa_driver(cfg), GeckoSpaDriver)


def test_null_bil_och_laddare_kraschar_inte_vid_anrop():
    car, charger = NullCarDriver(id="x", battery_kwh=50), NullChargerDriver(id="y")
    assert car.read_state() == {"soc": None, "plugged_in": False, "climate_temp": None, "climate_state": None}
    car.set_climate("heat", 21.0)
    assert charger.read_state() == {"status": None, "current_a": None, "phases": None}
    assert charger.set_limit_a(10) is False
    charger.set_phases(3); charger.turn_on(); charger.turn_off()
