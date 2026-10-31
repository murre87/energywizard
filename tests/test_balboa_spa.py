"""BalboaSpaDriver: byggd mot HA:s officiella balboa-integrations DOKUMENTERADE
entitetsformer (climate/select/switch/fan), inte en gissad protokolltolkning - men
aldrig verifierad mot ett riktigt Balboa-system (ingen betatestare har ett). Mockar
homeassistant helt, samma mönster som test_driver_parity.py/test_generic_drivers.py -
bevisar att rätt HA-tjänst/attribut nås med rätt entitet, inte produktionskorrekthet
mot riktig hårdvara."""
from unittest.mock import patch

from drivers.spa_balboa import BalboaSpaDriver
from house_config import build_spa_driver


def test_build_spa_driver_skickar_med_entities_fran_configen():
    cfg = {"spa": {"enabled": True, "driver": "balboa", "entities": {"climate": "climate.spa"}}}
    driver = build_spa_driver(cfg)
    assert isinstance(driver, BalboaSpaDriver)
    assert driver._e == {"climate": "climate.spa"}


def test_read_state_lasar_climate_och_range_select():
    with patch("drivers.spa_balboa.homeassistant") as mock_ha:
        mock_ha._get_numeric_attribute.side_effect = [21.5, 38.0]  # current, target
        mock_ha._get_raw_state.side_effect = ["heat", "High"]  # heater_state, economy_mode
        state = BalboaSpaDriver(entities={"climate": "climate.spa", "range_select": "select.range"}).read_state()
    assert state == {"current_temp": 21.5, "target_temp": 38.0, "heater_state": "heat", "economy_mode": "High"}
    mock_ha._get_numeric_attribute.assert_any_call("climate.spa", "current_temperature")
    mock_ha._get_numeric_attribute.assert_any_call("climate.spa", "temperature")


def test_set_target_temp_anropar_generisk_climate():
    with patch("drivers.spa_balboa.homeassistant") as mock_ha:
        BalboaSpaDriver(entities={"climate": "climate.spa"}).set_target_temp(37.5)
    mock_ha.set_climate_temperature.assert_called_once_with("climate.spa", 37.5)


def test_set_economy_true_valjer_low():
    with patch("drivers.spa_balboa.homeassistant") as mock_ha:
        BalboaSpaDriver(entities={"range_select": "select.range"}).set_economy(True)
    mock_ha.set_select.assert_called_once_with("select.range", "Low")


def test_set_economy_false_valjer_high():
    with patch("drivers.spa_balboa.homeassistant") as mock_ha:
        BalboaSpaDriver(entities={"range_select": "select.range"}).set_economy(False)
    mock_ha.set_select.assert_called_once_with("select.range", "High")


def test_read_power_w_utan_entitet_ger_none():
    with patch("drivers.spa_balboa.homeassistant") as mock_ha:
        assert BalboaSpaDriver(entities={}).read_power_w() is None
    mock_ha._get_numeric_state.assert_not_called()


def test_read_activities_bara_konfigurerade_entiteter():
    with patch("drivers.spa_balboa.homeassistant") as mock_ha:
        mock_ha._get_raw_state.return_value = "on"
        activities = BalboaSpaDriver(entities={"pump1": "fan.pump1"}).read_activities()
    assert activities == {"pump1": "on"}


def test_set_plug_power_utan_entitet_ger_false():
    with patch("drivers.spa_balboa.homeassistant") as mock_ha:
        ok = BalboaSpaDriver(entities={}).set_plug_power(True)
    mock_ha.set_switch.assert_not_called()
    assert ok is False


def test_set_plug_power_med_entitet_anropar_generisk_switch():
    with patch("drivers.spa_balboa.homeassistant") as mock_ha:
        mock_ha.set_switch.return_value = True
        ok = BalboaSpaDriver(entities={"plug": "switch.spa_plug"}).set_plug_power(True)
    mock_ha.set_switch.assert_called_once_with("switch.spa_plug", True)
    assert ok is True
