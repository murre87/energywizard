"""Steg 2 (koppla ihop main.py med drivrutinsarkitekturen): bevisar att de RIKTIGA
drivrutinerna (inte Null-varianterna, som test_config_loader.py redan täcker) faktiskt
anropar samma homeassistant.py/pump.py-funktioner, med samma argument, som main.py:s
direkta anrop gör idag - INNAN main.py byts ut att gå via dem. Mockar homeassistant/pump
helt - rör aldrig riktig hårdvara/Modbus, till skillnad från
test_emils_hus_bygger_riktiga_drivrutiner som medvetet undviker just detta."""
from unittest.mock import MagicMock, patch

import pytest

from drivers.charger_easee import EaseeChargerDriver
from drivers.heatpump_thermia import ThermiaHusdataHeatPumpDriver
from drivers.solar_solaredge import SolarEdgeSolarDriver
from drivers.spa_gecko import GeckoSpaDriver
from drivers.car_generic import NissanCarDriver, TeslaCarDriver


# ---------- Värmepump (ThermiaHusdataHeatPumpDriver -> pump.py) ----------

def test_heatpump_read_sensors_vidarekopplar_pump():
    with patch("drivers.heatpump_thermia.pump") as mock_pump:
        mock_pump.read_sensors.return_value = {"indoor_temp": 21.4, "water_temp": 57.0}
        result = ThermiaHusdataHeatPumpDriver().read_sensors()
    assert result == {"indoor_temp": 21.4, "water_temp": 57.0}


def test_heatpump_read_sensors_none_blir_tomt_dict():
    """pump.read_sensors() kan ge None vid Modbus-fel - main.py:s mönster är att
    hantera det, inte krascha. Drivrutinen ska bevara det beteendet."""
    with patch("drivers.heatpump_thermia.pump") as mock_pump:
        mock_pump.read_sensors.return_value = None
        result = ThermiaHusdataHeatPumpDriver().read_sensors()
    assert result == {}


@pytest.mark.parametrize("method,args,pump_func", [
    ("set_room_temp", (21.0,), "set_room_temp"),
    ("set_water_stop_temp", (60.0,), "set_water_stop_temp"),
    ("set_water_start_temp", (55.0,), "set_water_start_temp"),
    ("set_heating_start_temp", (18.0,), "set_heating_start_temp"),
    ("set_operating_mode", (1,), "set_operating_mode"),
])
def test_heatpump_skrivmetoder_vidarekopplar_ratt_pump_funktion(method, args, pump_func):
    """Samma funktioner, samma argument, som main.py:1539/1762/1764/1150/1109 anropar
    direkt - annars är bytet i main.py en riktig beteendeändring, inte en vidarekoppling."""
    with patch("drivers.heatpump_thermia.pump") as mock_pump:
        getattr(ThermiaHusdataHeatPumpDriver(), method)(*args)
        getattr(mock_pump, pump_func).assert_called_once_with(*args)


# ---------- Sol (SolarEdgeSolarDriver -> homeassistant.py) ----------

def test_solar_read_production_vidarekopplar_homeassistant():
    """Inkluderar 'status' - main.py:1674 läser solar_data.get('status') för att larma
    vid växelriktarfel (statuskod 3); tappades nästan bort i Steg 4:s ihopkoppling."""
    with patch("drivers.solar_solaredge.homeassistant") as mock_ha:
        mock_ha.read_solaredge.return_value = {"pv_power_w": 2380.0, "today_kwh": 14.2, "status": 3}
        result = SolarEdgeSolarDriver().read_production()
    assert result == {"pv_power_w": 2380.0, "today_kwh": 14.2, "status": 3}


def test_solar_set_och_get_export_limit():
    """set_export_limit_pct returnerar True/False (main.py:s anropsmönster använder
    det för att avgöra om senast-skickat-värdet ska uppdateras - förlorades nästan
    i Steg 4:s ihopkoppling, täppt innan main.py byttes om)."""
    with patch("drivers.solar_solaredge.homeassistant") as mock_ha:
        mock_ha.get_solaredge_limit.return_value = 77
        mock_ha.set_solaredge_limit.return_value = True
        driver = SolarEdgeSolarDriver()
        assert driver.set_export_limit_pct(50) is True
        mock_ha.set_solaredge_limit.assert_called_once_with(50)
        assert driver.get_export_limit_pct() == 77


# ---------- Spa (GeckoSpaDriver -> homeassistant.py) ----------

def test_spa_read_state_ger_radata_rakt_av():
    """read_state() normaliserar INTE heater_state/economy_mode till booleans - main.py:s
    egna villkor (str(heater_state).lower() in [...], economy_mode == 1.0) förblir i
    main.py tills ett andra spamärke finns att verifiera en gemensam mappning mot
    (samma princip som HeatPumpDriver.set_operating_mode, se heatpump.py)."""
    with patch("drivers.spa_gecko.homeassistant") as mock_ha:
        mock_ha.read_gecko.return_value = {"current_temp": 36.5, "target_temp": 38.0, "heater_state": "heating", "economy_mode": 1.0}
        result = GeckoSpaDriver().read_state()
    assert result == {"current_temp": 36.5, "target_temp": 38.0, "heater_state": "heating", "economy_mode": 1.0}


def test_spa_read_activities_vidarekopplar_samma_funktion_main_py_anvander():
    """main.py:1837 läser homeassistant.read_spa_activities() direkt - drivrutinen
    ska ge exakt samma dict, inte en egen tolkning."""
    with patch("drivers.spa_gecko.homeassistant") as mock_ha:
        mock_ha.read_spa_activities.return_value = {"heating": True, "circ_pump": False}
        result = GeckoSpaDriver().read_activities()
    assert result == {"heating": True, "circ_pump": False}


def test_spa_set_plug_power_vidarekopplar_ny_toggle_spa_plug():
    with patch("drivers.spa_gecko.homeassistant") as mock_ha:
        mock_ha.toggle_spa_plug.return_value = True
        assert GeckoSpaDriver().set_plug_power(True) is True
        mock_ha.toggle_spa_plug.assert_called_once_with(True)


def test_spa_set_target_temp_och_economy():
    with patch("drivers.spa_gecko.homeassistant") as mock_ha:
        driver = GeckoSpaDriver()
        driver.set_target_temp(39.0)
        mock_ha.set_gecko_target.assert_called_once_with(39.0)
        driver.set_economy(True)
        mock_ha.set_gecko_economy.assert_called_once_with(True)


# ---------- Laddare (EaseeChargerDriver -> homeassistant.py) ----------

def test_charger_read_state_anvander_injicerad_reader():
    reader = MagicMock(return_value={"status": "charging", "current_a": 16, "phases": 3})
    driver = EaseeChargerDriver(id="easee1", reader=reader)
    assert driver.read_state() == {"status": "charging", "current_a": 16, "phases": 3}
    reader.assert_called_once()


def test_charger_set_limit_a_vidarekopplar_med_reason():
    with patch("drivers.charger_easee.homeassistant") as mock_ha:
        mock_ha.set_ev_dynamic_limit.return_value = True
        assert EaseeChargerDriver(id="easee1").set_limit_a(10, reason="golv") is True
        mock_ha.set_ev_dynamic_limit.assert_called_once_with("easee1", 10, reason="golv")


def test_charger_set_phases_turn_on_turn_off():
    with patch("drivers.charger_easee.homeassistant") as mock_ha:
        driver = EaseeChargerDriver(id="easee1")
        driver.set_phases(1)
        mock_ha.set_easee_phases.assert_called_once_with("easee1", 1)
        driver.turn_on()
        mock_ha.turn_on_charger.assert_called_once_with("easee1")
        driver.turn_off()
        mock_ha.turn_off_charger.assert_called_once_with("easee1")


# ---------- Bilar (Nissan/TeslaCarDriver -> homeassistant.py) ----------

def test_nissan_read_state_vidarekopplar_read_nissan_data():
    with patch("drivers.car_generic.homeassistant") as mock_ha:
        mock_ha.read_nissan_data.return_value = {"soc": 64}
        assert NissanCarDriver(id="nissan", battery_kwh=40).read_state() == {"soc": 64}


def test_tesla_read_state_vidarekopplar_read_tesla_data():
    with patch("drivers.car_generic.homeassistant") as mock_ha:
        mock_ha.read_tesla_data.return_value = {"soc": 81}
        assert TeslaCarDriver(id="tesla", battery_kwh=75).read_state() == {"soc": 81}


def test_set_climate_samma_entitet_argument_som_main_py_anvander():
    """Paritetskontroll mot main.py:1011/1013 (handle_car_climate): samma entity_id,
    samma hvac_mode/temperature-argument till homeassistant.set_car_climate - annars
    skulle bytet i main.py vara en tyst beteendeändring, inte en vidarekoppling."""
    entities = {"soc": "sensor.leaf_soc", "climate": "climate.leaf_climate"}
    with patch("drivers.car_generic.homeassistant") as mock_ha:
        driver = NissanCarDriver(id="nissan", battery_kwh=40, entities=entities)
        driver.set_climate("heat_cool", 21.0)
        mock_ha.set_car_climate.assert_called_once_with("climate.leaf_climate", "heat_cool", 21.0)

        mock_ha.reset_mock()
        driver.set_climate("off")
        mock_ha.set_car_climate.assert_called_once_with("climate.leaf_climate", "off", None)


def test_set_climate_utan_konfigurerad_climate_entity_ar_no_op():
    """En bil utan climate-entitet i configen (valfri, se house_config.example.yaml)
    ska inte krascha eller anropa HA med ett tomt entity_id."""
    with patch("drivers.car_generic.homeassistant") as mock_ha:
        NissanCarDriver(id="nissan", battery_kwh=40, entities={"soc": "sensor.x"}).set_climate("heat_cool", 21.0)
    mock_ha.set_car_climate.assert_not_called()
