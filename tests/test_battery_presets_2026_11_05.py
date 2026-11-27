"""Förinställningar för batteristyrning (2026-11-05): GoodWe, SolarEdge (multi), Sungrow (mkaiser), Huawei (tjänster),
Tesla Powerwall och Enphase. Entitetsnamn och lägen enligt integrationernas källkod."""
import tempfile
from unittest.mock import patch

import yaml

from discovery import discover_house


def E(e, n, d="dev1", m="X", dc=None, u=None, st="50", mo=""):
    return {"e": e, "n": n, "a": None, "d": d, "dn": m, "m": m, "mo": mo, "dc": dc, "u": u, "st": st}


def bat(ents):
    return discover_house(ents)["battery"]


def test_goodwe():
    b = bat([E("sensor.gw_soc", "Battery State of Charge", m="GoodWe", dc="battery", u="%"),
             E("sensor.gw_pbat", "Battery Power", m="GoodWe", dc="power", u="W", st="-300"),
             {**E("select.gw_mode", "Inverter operation mode", m="GoodWe", st="general"),
              "options": ["general", "eco_charge", "eco_discharge"]}])
    gs = b["generic_suggestion"]
    assert gs["preset"] == "goodwe" and gs["modes"] == {"auto": "general", "charge": "eco_charge", "discharge": "eco_discharge"}
    assert gs["entities"]["mode_select"] == "select.gw_mode"


def test_solaredge_multi_gar_fore_fronius():
    b = bat([E("sensor.se_soc", "Battery State of Energy", m="SolarEdge", dc="battery", u="%"),
             E("sensor.se_p", "Battery Power", m="SolarEdge", dc="power", u="W"),
             E("select.se_ctrl", "Storage Control Mode", m="SolarEdge", st="Maximize Self Consumption"),
             E("select.se_cmd", "Storage Command Mode", m="SolarEdge", st="Solar Power Only (Off)"),
             E("number.se_cl", "Storage Charge Limit", m="SolarEdge", u="W"),
             E("number.se_dl", "Storage Discharge Limit", m="SolarEdge", u="W")])
    gs = b["generic_suggestion"]
    assert gs["preset"] == "solaredge_modbus_multi" and gs["keepalive_s"] == 600
    assert gs["modes"]["discharge"] == {"select.se_ctrl": "Remote Control", "select.se_cmd": "Discharge to Minimize Import"}
    assert gs["entities"]["charge_power"] == "number.se_cl" and gs["entities"]["discharge_power"] == "number.se_dl"


def test_fronius_fortfarande_fronius():
    b = bat([E("sensor.fr_soc", "Battery SoC", m="Fronius", dc="battery", u="%"),
             E("sensor.fr_p", "Battery power", m="Fronius", dc="power", u="W"),
             E("select.fr_scm", "Storage Control Mode", m="Fronius", st="Auto")])
    assert b["generic_suggestion"]["preset"] == "fronius_modbus"


def test_huawei_tjanster_och_yaml():
    b = bat([E("sensor.hw_soc", "Batteries State of capacity", d="hwbat", m="Huawei", dc="battery", u="%"),
             E("sensor.hw_p", "Batteries Charge/Discharge power", d="hwbat", m="Huawei", dc="power", u="W")])
    gs = b["generic_suggestion"]
    assert gs["preset"] == "huawei_solar" and gs["keepalive_s"] == 900
    assert gs["modes"]["charge"] == {"service": "huawei_solar.forcible_charge", "data": {"device_id": "hwbat", "duration": 30},
                                     "power_field": "power"}
    assert "hold" not in gs["modes"] and "idle" not in gs["modes"]          # 0 W släpper i Huawei
    # Guiden ska kunna skriva och läsa tillbaka tjänsteanropen
    import importlib.util, os, sys
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    cwd = os.getcwd()
    os.chdir(root / "webdashboard")
    try:
        mod = sys.modules.get("webdashboard_app")
        if mod is None:
            spec = importlib.util.spec_from_file_location("webdashboard_app", root / "webdashboard" / "app.py")
            mod = importlib.util.module_from_spec(spec)
            sys.modules["webdashboard_app"] = mod
            spec.loader.exec_module(mod)
        text = mod._build_house_config_yaml({"battery": b})
    finally:
        os.chdir(cwd)
    modes = yaml.safe_load(text)["battery"]["modes"]
    assert modes["discharge"]["service"] == "huawei_solar.forcible_discharge" and modes["discharge"]["data"]["duration"] == 30


def test_huawei_tjansteanrop_skickas():
    from drivers.battery_generic import GenericBatteryDriver
    modes = {"auto": {"service": "huawei_solar.stop_forcible_charge", "data": {"device_id": "hwbat"}},
             "charge": {"service": "huawei_solar.forcible_charge", "data": {"device_id": "hwbat", "duration": 30}, "power_field": "power"}}
    d = GenericBatteryDriver(entities={"soc": "sensor.s"}, modes=modes, max_power_w=5000)
    calls = []
    with patch("drivers.battery_generic.homeassistant") as ha:
        ha.call_service.side_effect = lambda dom, svc, data: calls.append((dom, svc, data)) or True
        assert d.supports_control() and d.apply_intent("charge", 2400) and d.apply_intent("auto")
    assert calls[0] == ("huawei_solar", "forcible_charge", {"device_id": "hwbat", "duration": 30, "power": 2400})
    assert calls[1] == ("huawei_solar", "stop_forcible_charge", {"device_id": "hwbat"})


def test_sungrow_mkaiser_utan_enhet():
    ents = [{"e": "sensor.battery_level", "n": "Battery level", "d": None, "dc": "battery", "u": "%", "st": "55"},
            {"e": "sensor.battery_charging_power_signed", "n": "Battery charging power signed", "d": None, "dc": "power", "u": "W", "st": "0"},
            {"e": "select.ems_mode", "n": "EMS mode", "d": None, "st": "Self-consumption mode (default)"},
            {"e": "select.battery_forced_charge_discharge", "n": "Battery forced charge discharge", "d": None, "st": "Stop (default)"},
            {"e": "number.battery_forced_charge_discharge_power", "n": "Battery forced charge discharge power", "d": None, "u": "W", "st": "0"}]
    b = bat(ents)
    gs = b["generic_suggestion"]
    assert gs["preset"] == "sungrow_mkaiser"
    assert gs["modes"]["charge"] == {"select.ems_mode": "Forced mode", "select.battery_forced_charge_discharge": "Forced charge"}
    assert gs["entities"]["charge_power"] == "number.battery_forced_charge_discharge_power"


def test_powerwall_och_enphase():
    b = bat([E("sensor.pw_soc", "Percentage charged", m="Tesla", dc="battery", u="%", mo="Powerwall 2"),
             E("sensor.pw_p", "Battery power", m="Tesla", dc="power", u="W", mo="Powerwall 2"),
             E("select.pw_op", "Operation mode", m="Tesla", st="self_consumption", mo="Powerwall 2")])
    assert b["generic_suggestion"]["preset"] == "tesla_powerwall" and b["generic_suggestion"]["modes"]["charge"] == "backup"
    b = bat([E("sensor.en_soc", "Battery", m="Enphase", dc="battery", u="%"),
             E("sensor.en_p", "Battery power", m="Enphase", dc="power", u="W"),
             E("select.en_st", "Storage mode", m="Enphase", st="self_consumption")])
    assert b["generic_suggestion"]["preset"] == "enphase"


def test_sigenergy_via_ha_med_enable_switch():
    b = bat([E("sensor.sg_soc", "Battery State of Charge", m="Sigenergy", dc="battery", u="%"),
             E("sensor.sg_p", "Battery Power", m="Sigenergy", dc="power", u="W", st="-300"),
             {**E("select.sg_mode", "Remote EMS control mode", m="Sigenergy", st="Maximum Self Consumption"),
              "options": ["Maximum Self Consumption", "Command Charging (Grid First)", "Command Discharging (ESS First)",
                          "PCS Remote Control"]},
             E("switch.sg_ems", "Remote EMS (controlled by Home Assistant)", m="Sigenergy", st="off")])
    gs = b["generic_suggestion"]
    assert gs["preset"] == "sigenergy_ha"
    assert gs["entities"]["mode_select"] == "select.sg_mode" and gs["entities"]["enable_switch"] == "switch.sg_ems"
    assert gs["modes"] == {"auto": "Maximum Self Consumption", "charge": "Command Charging (Grid First)",
                           "discharge": "Command Discharging (ESS First)"}
    assert "hold" not in gs["modes"] and "verifierad" in b["note"] and b["control_preset"] == "sigenergy_ha"


def test_sigenergy_utan_normalt_lage_ger_ingen_styrning():
    b = bat([E("sensor.sg_soc", "Battery State of Charge", m="Sigenergy", dc="battery", u="%"),
             E("sensor.sg_p", "Battery Power", m="Sigenergy", dc="power", u="W", st="-300"),
             {**E("select.sg_mode", "Remote EMS control mode", m="Sigenergy", st="PCS Remote Control"),
              "options": ["PCS Remote Control"]},
             E("switch.sg_ems", "Remote EMS", m="Sigenergy", st="off")])
    assert not (b.get("generic_suggestion") or {}).get("modes")         # ingen styrning föreslås utan normalläget


def test_emaldo_via_ha_med_tjänster_och_slot_tider():
    b = bat([E("sensor.power_store_battery_soc", "Power Store Battery SoC", m="Emaldo", dc="battery", u="%"),
             E("sensor.power_store_battery_power", "Power Store Battery power", m="Emaldo", dc="power", u="W", st="-1200"),
             E("sensor.power_store_grid_power", "Power Store Grid power", m="Emaldo", dc="power", u="W", st="300")])
    gs = b["generic_suggestion"]
    assert gs["preset"] == "emaldo" and gs["power_invert"] is True and gs["keepalive_s"] == 300
    assert gs["modes"]["charge"] == {"service": "emaldo.set_slot_range",
                                     "data": {"start_time": "{slot_start}", "end_time": "{slot_end}", "action": "charge-100"}}
    assert gs["modes"]["discharge"]["data"]["action"] == "discharge-low" and "hold" not in gs["modes"]
    assert gs["modes"]["auto"] == {"service": "emaldo.reset_to_internal", "data": {"all": True}}
    assert "skuggläge" in b["note"] and b["control_preset"] == "emaldo"


def test_emaldo_slot_tider_fylls_i_per_kvart():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from drivers.battery_generic import _fill_slot_times
    d = {"start_time": "{slot_start}", "end_time": "{slot_end}", "action": "charge-100", "all": True}
    out = _fill_slot_times(d, now=datetime(2026, 11, 23, 14, 22, 40, tzinfo=ZoneInfo("Europe/Stockholm")))
    assert out == {"start_time": "14:15", "end_time": "14:45", "action": "charge-100", "all": True}
    assert _fill_slot_times({"all": True}) == {"all": True}
    out = _fill_slot_times(d, now=datetime(2026, 11, 23, 23, 50, tzinfo=ZoneInfo("Europe/Stockholm")))
    assert out["start_time"] == "23:45" and out["end_time"] == "00:15"


def test_emaldo_nätmätare_är_grid_power_inte_consumption():
    r = discover_house([E("sensor.power_store_battery_soc", "Power Store Battery SoC", m="Emaldo", dc="battery", u="%"),
                        E("sensor.power_store_battery_power", "Power Store Battery power", m="Emaldo", dc="power", u="W"),
                        E("sensor.power_store_grid_power", "Power Store Grid power", m="Emaldo", dc="power", u="W", st="300"),
                        E("sensor.power_store_consumption", "Power Store Consumption", m="Emaldo", dc="power", u="W", st="900")])
    assert [m["power_entity"] for m in r["grid_meters"]] == ["sensor.power_store_grid_power"]
    assert r["power_meter"]["entities"]["power_w"] == "sensor.power_store_grid_power"


def test_emaldo_laddar_med_slot_fönster():
    from drivers.battery_generic import GenericBatteryDriver
    calls = []
    modes = {"charge": {"service": "emaldo.set_slot_range",
                        "data": {"start_time": "{slot_start}", "end_time": "{slot_end}", "action": "charge-100"}}}
    with patch("drivers.battery_generic.homeassistant") as ha:
        ha.call_service.side_effect = lambda dom, svc, data: calls.append((dom, svc, data)) or True
        d = GenericBatteryDriver(entities={}, modes=modes)
        assert d.apply_intent("charge", 3000.0)
    dom, svc, data = calls[0]
    assert (dom, svc) == ("emaldo", "set_slot_range") and data["action"] == "charge-100"
    assert len(data["start_time"]) == 5 and data["start_time"][3:] in ("00", "15", "30", "45") and ":" in data["end_time"]


def test_bil_med_12v_batteri_väljer_traktionsbatteriet():
    """#596: Kia/Hyundai har både 12 V-batteri ("Car battery level") och laddnivå ("EV battery level")."""
    ents = [E("sensor.ioniq_car_battery_level", "Car battery level", d="car1", m="Hyundai", dc="battery", u="%"),
            E("sensor.ioniq_ev_battery_level", "EV battery level", d="car1", m="Hyundai", dc="battery", u="%"),
            E("device_tracker.ioniq", "Location", d="car1", m="Hyundai")]
    car = discover_house(ents)["cars"][0]
    assert car["soc_entity"] == "sensor.ioniq_ev_battery_level"
    assert [row["entity"] for row in car["soc_candidates"]] == ["sensor.ioniq_ev_battery_level", "sensor.ioniq_car_battery_level"]
    ents.reverse()
    assert discover_house(ents)["cars"][0]["soc_entity"] == "sensor.ioniq_ev_battery_level"
    only12v = [E("sensor.x_car_battery_level", "Car battery level", d="car2", m="Hyundai", dc="battery", u="%"),
               E("device_tracker.x", "Location", d="car2", m="Hyundai")]
    assert discover_house(only12v)["cars"][0]["soc_entity"] == "sensor.x_car_battery_level"      # inget annat finns
    plain = [E("sensor.p_battery", "Battery", d="car3", m="Peugeot", dc="battery", u="%"),
             E("sensor.p_12v", "12V battery", d="car3", m="Peugeot", dc="battery", u="%"),
             E("device_tracker.p", "Location", d="car3", m="Peugeot")]
    assert discover_house(plain)["cars"][0]["soc_entity"] == "sensor.p_battery"
