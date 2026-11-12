"""2026-11-06: styrning av Sonnen (tjänster), Victron (ESS-börvärde), Kostal (håll via min SoC) och FTW-drivrutiner med
batterikommando (Pixii, Deye, Sigenergy) - igenkänning, drivrutinens steg och guidens YAML."""
import asyncio
import importlib.util
import os
import sys
from pathlib import Path
from unittest.mock import patch

import yaml

import homeassistant
import house_config
from discovery import discover_house
from drivers.battery_generic import GenericBatteryDriver

ROOT = Path(__file__).resolve().parent.parent


def _wd():
    mod = sys.modules.get("webdashboard_app")
    if mod is None:
        cwd = os.getcwd(); os.chdir(ROOT / "webdashboard")
        try:
            spec = importlib.util.spec_from_file_location("webdashboard_app", ROOT / "webdashboard" / "app.py")
            mod = importlib.util.module_from_spec(spec); sys.modules["webdashboard_app"] = mod; spec.loader.exec_module(mod)
        finally:
            os.chdir(cwd)
    return mod


def ent(e, n, m, dc=None, u=None, st="0", d="dev1"):
    return {"e": e, "n": n, "a": None, "d": d, "dn": m + " batteri", "m": m, "mo": None, "dc": dc, "u": u, "st": st}


def _yaml_roundtrip(battery):
    cwd = os.getcwd(); os.chdir(ROOT / "webdashboard")
    try:
        cfg = yaml.safe_load(_wd()._build_house_config_yaml({"battery": battery}))
    finally:
        os.chdir(cwd)
    return cfg, house_config.build_battery_driver(cfg)


def test_sonnen_manuellt_lage_och_borvarde():
    b = discover_house([ent("sensor.sonnen_usoc", "State of charge", "sonnen GmbH", "battery", "%", "60"),
                        ent("sensor.sonnen_battery_power", "Battery power", "sonnen GmbH", "power", "W", "0")])["battery"]
    m = b["generic_suggestion"]["modes"]
    assert m["charge"][0]["data"]["mode"] == "manual" and m["charge"][1]["service"] == "sonnenbatterie.charge_battery"
    cfg, drv = _yaml_roundtrip(b)
    calls = []
    with patch.object(homeassistant, "call_service", side_effect=lambda d, s, data: calls.append((d, s, dict(data))) or True), \
            patch.object(homeassistant, "_get_numeric_state", return_value=60.0):
        assert drv._apply("charge", 2500)
    assert [c[1] for c in calls] == ["set_operating_mode", "charge_battery"] and calls[1][2]["power"] == 2500


def test_victron_ess_borvarde():
    ents = [ent("sensor.victron_battery_soc", "Battery SOC", "Victron Energy", "battery", "%", "70"),
            ent("sensor.victron_battery_power", "Battery power", "Victron Energy", "power", "W", "0"),
            ent("number.victron_settings_ess_acpowersetpoint", "ESS AC power setpoint", "Victron Energy")]
    b = discover_house(ents)["battery"]
    assert b["control_preset"] == "victron_ess"
    cfg, drv = _yaml_roundtrip(b)
    sets = []
    with patch.object(homeassistant, "set_number", side_effect=lambda e, v: sets.append(v) or True):
        drv._apply("discharge", 3000); drv._apply("charge", 2000); drv._apply("auto")
    assert sets == [-3000, 2000, 0]


def test_kostal_hall_via_min_soc():
    ents = [ent("sensor.kostal_battery_soc", "Battery SoC", "Kostal", "battery", "%", "72"),
            ent("sensor.kostal_battery_power", "Battery power", "Kostal", "power", "W", "0"),
            ent("number.kostal_battery_min_soc", "Battery min SoC", "Kostal")]
    b = discover_house(ents)["battery"]
    assert b["control_preset"] == "kostal_plenticore" and set(b["generic_suggestion"]["modes"]) == {"auto", "hold"}
    drv = GenericBatteryDriver(entities={"soc": "sensor.kostal_battery_soc"}, modes=b["generic_suggestion"]["modes"])
    sets = []
    with patch.object(homeassistant, "set_number", side_effect=lambda e, v: sets.append((e, v)) or True), \
            patch.object(homeassistant, "_get_numeric_state", return_value=72.4):
        drv._apply("hold"); drv._apply("auto")
    assert sets == [("number.kostal_battery_min_soc", 72), ("number.kostal_battery_min_soc", 5)]


def test_ftw_styrning_valt_i_guiden():
    cwd = os.getcwd(); os.chdir(ROOT / "webdashboard")
    try:
        txt = _wd()._build_house_config_yaml({"ftw": {"driver": "pixii", "host": "192.0.2.5", "port": 502, "unit_id": 1,
                                                      "battery": True, "solar": False, "control": True}})
    finally:
        os.chdir(cwd)
    cfg = yaml.safe_load(txt)
    assert cfg["battery"]["control"] == "styr" and cfg["battery"]["control_unverified"] is True
    drv = house_config.build_battery_driver(cfg)
    assert drv._control is True


def test_ftw_lista_vet_vilka_som_kan_styra():
    d = asyncio.run(_wd().ftw_drivers())
    can = {x["id"]: x["can_control"] for x in d["drivers"]}
    assert can["pixii"] and can["deye"] and can["sigenergy"] and can["solinteg"] and not can["sma"] and not can["victron"]
    caps = {x["id"]: x["capabilities"] for x in d["drivers"]}
    assert "battery" in caps["solinteg"] and "pv" in caps["solinteg"]
    assert "battery" in caps["sigenergy"] and "pv" in caps["sigenergy"]
