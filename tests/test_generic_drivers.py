"""Generiska drivrutiner (laddare/värmepump/sol) - täcker märken utan en handbyggd
drivrutin genom HA:s genuint generiska tjänster (switch.turn_on/off, number.set_value,
climate.set_temperature). Bevisar att rätt HA-tjänst anropas med rätt entitet/argument
(mockar homeassistant helt, samma mönster som test_driver_parity.py) OCH att
house_config.py faktiskt kopplar entities-dicten från configen till drivrutinen -
build_*-funktionerna tog tidigare bara id, inte entities, för de märkesspecifika
klasserna (Easee/Thermia/SolarEdge behöver det inte), ett hål de generiska
drivrutinerna skulle fallit rakt i annars."""
from unittest.mock import MagicMock, patch

from drivers.battery_generic import GenericBatteryDriver
from drivers.charger_generic import GenericChargerDriver
from drivers.heatpump_generic import GenericClimateHeatPumpDriver
from drivers.solar_generic import GenericNumberSolarDriver
from house_config import build_battery_driver, build_charger_drivers, build_heat_pump_driver, build_physical_charger_drivers, build_solar_driver


# ---------- Laddare (GenericChargerDriver -> homeassistant.py) ----------

def test_charger_turn_on_av_anropar_generisk_switch():
    with patch("drivers.charger_generic.homeassistant") as mock_ha:
        GenericChargerDriver(id="x", entities={"switch": "switch.min_laddare"}).turn_on()
    mock_ha.set_switch.assert_called_once_with("switch.min_laddare", True)


def test_charger_turn_off_anropar_generisk_switch():
    with patch("drivers.charger_generic.homeassistant") as mock_ha:
        GenericChargerDriver(id="x", entities={"switch": "switch.min_laddare"}).turn_off()
    mock_ha.set_switch.assert_called_once_with("switch.min_laddare", False)


def test_charger_utan_switch_entitet_gor_ingenting():
    with patch("drivers.charger_generic.homeassistant") as mock_ha:
        GenericChargerDriver(id="x", entities={}).turn_on()
    mock_ha.set_switch.assert_not_called()


def test_charger_set_limit_a_anropar_generisk_number():
    with patch("drivers.charger_generic.homeassistant") as mock_ha:
        mock_ha.set_number.return_value = True
        ok = GenericChargerDriver(id="x", entities={"current_limit": "number.laddstrom"}).set_limit_a(10)
    mock_ha.set_number.assert_called_once_with("number.laddstrom", 10)
    assert ok is True


def test_charger_utan_current_limit_entitet_ger_false():
    with patch("drivers.charger_generic.homeassistant") as mock_ha:
        ok = GenericChargerDriver(id="x", entities={}).set_limit_a(10)
    mock_ha.set_number.assert_not_called()
    assert ok is False


def test_charger_set_phases_ar_alltid_no_op():
    assert GenericChargerDriver(id="x").supports_phase_switch is False
    GenericChargerDriver(id="x").set_phases(3)  # kraschar inte, gör inget


def test_charger_read_state():
    with patch("drivers.charger_generic.homeassistant") as mock_ha:
        mock_ha._get_raw_state.return_value = "charging"
        mock_ha._get_numeric_state.return_value = 10.0
        state = GenericChargerDriver(id="x", entities={"status": "sensor.s", "current_limit": "number.n"}).read_state()
    # current_limit utan current_import -> strömmen är gränsen (märkt); ingen effektentitet -> power_kw None
    assert state == {"status": "charging", "status_raw": "charging", "current_a": 10.0, "current_is_limit": True,
                     "power_kw": None, "phases": None}


def test_charger_ocpp_status_normaliseras():
    from drivers.charger_generic import normalize_status
    assert [normalize_status(s) for s in ("Available", "Preparing", "Charging", "SuspendedEVSE", "SuspendedEV", "Faulted")] == \
        ["disconnected", "awaiting_start", "charging", "paused", "completed", "offline"]


def test_charger_6a_golv_0a_stanger_av_och_skrivspar():
    drv = GenericChargerDriver(id="x", entities={"switch": "switch.s", "current_limit": "number.n"})
    with patch("drivers.charger_generic.homeassistant") as ha:
        ha.set_number.return_value = True
        assert drv.set_limit_a(4) is True                      # under 6 A -> 6 A
        ha.set_number.assert_called_once_with("number.n", 6)
        assert drv.set_limit_a(10) is False                     # inom 10 s: väntar
        assert drv.set_limit_a(0) is True                       # 0 A = stäng av, inte gräns 0
        ha.set_switch.assert_called_once_with("switch.s", False)
    assert ha.set_number.call_count == 1


# ---------- Värmepump (GenericClimateHeatPumpDriver -> homeassistant.py) ----------

def test_heatpump_set_room_temp_anropar_generisk_climate():
    with patch("drivers.heatpump_generic.homeassistant") as mock_ha:
        mock_ha.set_climate_temperature.return_value = True
        ok = GenericClimateHeatPumpDriver(entity_id="climate.pump").set_room_temp(21.0)
    mock_ha.set_climate_temperature.assert_called_once_with("climate.pump", 21.0)
    assert ok is True


def test_heatpump_avancerade_metoder_ger_false_inte_krasch():
    driver = GenericClimateHeatPumpDriver(entity_id="climate.pump")
    assert driver.set_water_stop_temp(55.0) is False
    assert driver.set_water_start_temp(50.0) is False
    assert driver.set_heating_start_temp(18.0) is False
    assert driver.set_operating_mode(1) is False


def test_heatpump_utan_entitet_set_room_temp_ger_false():
    with patch("drivers.heatpump_generic.homeassistant") as mock_ha:
        ok = GenericClimateHeatPumpDriver(entity_id=None).set_room_temp(21.0)
    mock_ha.set_climate_temperature.assert_not_called()
    assert ok is False


# ---------- Solceller (GenericNumberSolarDriver -> homeassistant.py) ----------

def test_solar_set_export_limit_anropar_generisk_number():
    with patch("drivers.solar_generic.homeassistant") as mock_ha:
        mock_ha.set_number.return_value = True
        driver = GenericNumberSolarDriver(entities={"export_limit_pct": "number.export"})
        assert driver.supports_curtailment() is True
        ok = driver.set_export_limit_pct(80)
    mock_ha.set_number.assert_called_once_with("number.export", 80)
    assert ok is True


def test_solar_utan_export_entitet_stodjer_inte_strypning():
    driver = GenericNumberSolarDriver(entities={})
    assert driver.supports_curtailment() is False
    assert driver.set_export_limit_pct(80) is False
    assert driver.get_export_limit_pct() is None


# ---------- house_config.py: entities-dicten kopplas faktiskt igenom ----------

def test_build_charger_driver_skickar_med_entities_fran_configen():
    cfg = {"evs": [{"id": "bil1", "charger": {"driver": "generic", "id": "x", "entities": {"switch": "switch.foo"}}}]}
    drivers = build_charger_drivers(cfg)
    assert isinstance(drivers["bil1"], GenericChargerDriver)
    assert drivers["bil1"]._e == {"switch": "switch.foo"}


def test_build_physical_charger_driver_skickar_med_entities_fran_configen():
    cfg = {"evs": [{"id": "bil1", "charger": {"driver": "generic", "id": "laddare1", "entities": {"switch": "switch.foo"}}}]}
    drivers = build_physical_charger_drivers(cfg)
    assert isinstance(drivers["laddare1"], GenericChargerDriver)
    assert drivers["laddare1"]._e == {"switch": "switch.foo"}


def test_build_heat_pump_driver_skickar_med_climate_entitet():
    cfg = {"heat_pump": {"enabled": True, "driver": "generic_climate", "entities": {"climate": "climate.pump"}}}
    driver = build_heat_pump_driver(cfg)
    assert isinstance(driver, GenericClimateHeatPumpDriver)
    assert driver._entity == "climate.pump"


def test_build_solar_driver_skickar_med_entities_fran_configen():
    cfg = {"solar": {"enabled": True, "driver": "generic_number", "entities": {"export_limit_pct": "number.export"}}}
    driver = build_solar_driver(cfg)
    assert isinstance(driver, GenericNumberSolarDriver)
    assert driver._e == {"export_limit_pct": "number.export"}


# ---------- Husbatteri (GenericBatteryDriver -> homeassistant.py) ----------
# OBS: bara läsning + enkel lägesstyrning - gpm.py importerar INTE det här alls
# (se drivers/battery.py:s modulkommentar). Ingen produktionsverifiering möjlig
# (Emils eget hus saknar batteri) - korrekthet bevisas här, mockat, inte live.

def test_battery_read_state_lasar_generiska_sensorer():
    with patch("drivers.battery_generic.homeassistant") as mock_ha:
        mock_ha._get_numeric_state.side_effect = [72.0]
        mock_ha.get_power_w.side_effect = [-850.0]          # effekten läses enhetsmedvetet (W/kW, #139)
        state = GenericBatteryDriver(capacity_kwh=10.0, entities={"soc": "sensor.soc", "power": "sensor.power"}).read_state()
    assert state == {"soc_pct": 72.0, "power_w": -850.0, "capacity_kwh": 10.0, "mode": None}


def test_battery_supports_control_kraver_select_och_lagesmappning():
    """Styrning kräver både batteriets select-entitet OCH en mappning från EnergyWizards avsikter
    till batteriets egna lägen - annars vet motorn inte vilket läge den ska välja."""
    assert GenericBatteryDriver(entities={"mode_select": "select.mode"}, modes={"auto": "Self-use"}).supports_control() is True
    assert GenericBatteryDriver(entities={"mode_select": "select.mode"}).supports_control() is False
    assert GenericBatteryDriver(entities={}).supports_control() is False


def test_battery_set_mode_anropar_generisk_select():
    with patch("drivers.battery_generic.homeassistant") as mock_ha:
        mock_ha.set_select.return_value = True
        ok = GenericBatteryDriver(entities={"mode_select": "select.mode"}).set_mode("charge")
    mock_ha.set_select.assert_called_once_with("select.mode", "charge")
    assert ok is True


def test_battery_set_mode_utan_entitet_ger_false():
    with patch("drivers.battery_generic.homeassistant") as mock_ha:
        ok = GenericBatteryDriver(entities={}).set_mode("charge")
    mock_ha.set_select.assert_not_called()
    assert ok is False


def test_build_battery_driver_skickar_med_entities_och_kapacitet():
    cfg = {"battery": {"enabled": True, "driver": "generic", "capacity_kwh": 13.5, "entities": {"soc": "sensor.soc"}}}
    driver = build_battery_driver(cfg)
    assert isinstance(driver, GenericBatteryDriver)
    assert driver.capacity_kwh == 13.5
    assert driver._e == {"soc": "sensor.soc"}


def test_thermia_set_room_temp_tar_celsius_och_skriver_tiondelar(monkeypatch):
    """Gränssnittet är °C för alla drivrutiner; Thermias register 15 vill ha tiondelar (#145)."""
    import pump
    from drivers.heatpump_thermia import ThermiaHusdataHeatPumpDriver
    sent = []
    monkeypatch.setattr(pump, "set_room_temp", lambda v: sent.append(v) or True)
    assert ThermiaHusdataHeatPumpDriver().set_room_temp(20.5) is True
    assert sent == [205] and type(sent[0]) is int
