"""#395: SAJ H2 loggar ett skuggrecept och skriver inga register."""
import yaml

from discovery import discover_house
from house_config import battery_settings, build_battery_driver
from saj_shadow import describe, observation
from test_solax_modbus_battery import _builder


def _entity(eid, name, dc=None, unit=None, state="40", maker="SAJ", device="SAJ H2"):
    return {"e": eid, "n": name, "a": None, "d": "dev_saj", "dn": device,
            "m": maker, "mo": "H2", "dc": dc, "u": unit, "st": state}


SAJ = [
    _entity("sensor.saj_battery_soc", "Battery SOC", "battery", "%", "61"),
    _entity("sensor.saj_battery_power", "Battery Power", "power", "W", "-300"),
]


def _cfg(**extra):
    battery = {"enabled": True, "control": "samarbete", "max_power_w": 5000,
               "capacity_kwh": 10, "reserve_soc": 20, "max_soc": 100}
    battery.update(extra)
    return battery_settings({"battery": battery})


def _state(**extra):
    state = {"soc": 40, "price": 1.2, "meter_fresh": True, "avg_net_w": 800, "battery_w": 0,
             "prices_rest_of_day": [1.2, 1.2, 1.2]}
    state.update(extra)
    return state


def test_saj_utan_lagen_far_skuggrecept_och_inga_modes():
    battery = discover_house(SAJ)["battery"]
    assert battery["shadow_recipe"] == "saj_h2"
    assert battery["maker"] == "SAJ"
    assert not (battery.get("generic_suggestion") or {}).get("modes")
    assert "skriv" in battery["note"].lower()
    assert "#395" in battery["note"]


def test_ampere_storagepro_far_samma_recept():
    ents = [
        _entity("sensor.ampere_battery_soc", "Battery SOC", "battery", "%", "55",
                maker="Ampere", device="Ampere.StoragePro"),
        _entity("sensor.ampere_battery_power", "Battery Power", "power", "W", "0",
                maker="Ampere", device="Ampere.StoragePro"),
    ]
    assert discover_house(ents)["battery"]["shadow_recipe"] == "saj_h2"


def test_yaml_lamnar_styrningen_i_samarbete():
    text = _builder()({"cars": [], "battery": discover_house(SAJ)["battery"]})
    assert "shadow_recipe: saj_h2" in text
    assert "control: samarbete" in text
    assert "\n  modes:" not in text
    driver = build_battery_driver(yaml.safe_load(text))
    assert driver.supported_intents() == set()


def test_sjalvforbrukning_och_hall_har_hela_procent():
    cfg = _cfg()
    assert "13895 = 2 och 13905 = 20 %" in describe("auto", None, cfg)
    assert "13895 = 2 och 13905 = 100 %" in describe("hold", None, cfg)
    assert "0x7F64" in describe("charge", 5000, cfg)
    assert describe("charge", 800, cfg) is None
    assert describe("discharge", 5000, cfg) is None
    assert describe("idle", None, cfg) is None
    assert describe("auto", 5000, cfg) is None
    assert describe("auto", None, _cfg(reserve_soc=20.4)) is None
    for line in (describe("auto", None, cfg), describe("hold", None, cfg), describe("charge", 5000, cfg)):
        assert line.endswith("Skriver inte.")


def test_samarbete_loggar_minuspris_utan_att_andra_laget():
    cfg = _cfg()
    line = observation("saj_h2", _state(price=-0.4), cfg)
    assert "laddar" in line
    assert "13895 = 1" in line
    assert cfg["control"] == "samarbete"


def test_styrlage_och_okant_recept_ar_tysta():
    cfg = _cfg()
    cfg["control"] = "styr"
    assert observation("saj_h2", _state(price=-0.4), cfg) is None
    assert observation("sofar_g3", _state(price=-0.4), _cfg()) is None
    assert observation("annat", _state(price=-0.4), _cfg()) is None


def test_full_urladdning_vid_effekttak_har_inget_register():
    line = observation("saj_h2", _state(peak_reached=True, avg_net_w=400), _cfg())
    assert line is None


def test_elbil_fran_natet_blir_hall_i_skuggan():
    line = observation("saj_h2", _state(ev_charging_grid=True), _cfg())
    assert "håller utan urladdning" in line
    assert "13905 = 100 %" in line


def test_vila_och_delad_laddning_har_inget_register():
    assert observation("saj_h2", _state(solar_yield_to="elbilen"), _cfg()) is None
    assert observation("saj_h2", _state(planned_action="charge", planned_power_w=800), _cfg()) is None
