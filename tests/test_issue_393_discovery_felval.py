"""#393: guiden valde mobiltelefoner som husbatteri och brandvarnare, robotgräsklippare, UPS, surfplattor
och hundhalsband som elbil (telemetrins drivrutinsöversikt 2026-11-13). Riktiga bilar och batterier
ska fortfarande hittas."""
import pytest

import discovery


def dev(did, maker, model, *ents, name=None):
    head = {"d": did, "dn": name or f"{maker} {model}", "m": maker, "mo": model}
    return [{**head, **e} for e in ents]


SOC = {"e": "sensor.x_battery", "n": "Battery", "dc": "battery", "u": "%", "st": "80"}
TRACKER = {"e": "device_tracker.x", "n": "Location"}
BATT_POWER = {"e": "sensor.x_battery_power", "n": "Battery Power", "dc": "power", "u": "W", "st": "-3"}
RANGE = {"e": "sensor.x_range", "n": "Range", "u": "km", "st": "310"}


def uniq(ents, did):
    return [{**e, "e": e["e"].replace(".x", "." + did)} for e in ents]


def cars(*devices):
    return [c["device_name"] for c in discovery.discover_house([e for d in devices for e in d])["cars"]]


def battery(*devices):
    b = discovery.discover_house([e for d in devices for e in d])["battery"]
    return b and b["device_name"]


@pytest.fixture(autouse=True)
def _no_live(monkeypatch):
    for f in ("_check_configured_heat_pump",):
        if hasattr(discovery, f):
            monkeypatch.setattr(discovery, f, lambda: None)


@pytest.mark.parametrize("maker,model,extra", [
    ("Aqara", "Smart Smoke Detector EU", []),
    ("Aqara", "Wireless Mini Switch", []),
    ("Mammotion", "YUKA mini 600", [TRACKER]),
    ("Mammotion", "LUBA 3 AWD 3000", [TRACKER]),
    ("APC", "Smart-UPS 3000 XLM", []),
    ("LENOVO", "TB390FU", [TRACKER]),
    ("Teclast", "P20HD_EEA", [TRACKER]),
    ("PRITOM", "P7_EEA", [TRACKER]),
    ("Tractive GmbH", "", [TRACKER]),
    ("_TZ3000_6zvw8ham", "TS0203", []),
])
def test_inte_elbil(maker, model, extra):
    assert cars(dev("d1", maker, model, *uniq([SOC, *extra], "d1"))) == []


@pytest.mark.parametrize("maker,model", [("Google", "Pixel 6a"), ("samsung", "SM-S938B")])
def test_telefon_med_battery_power_ar_inte_husbatteri(maker, model):
    assert battery(dev("p1", maker, model, *uniq([SOC, BATT_POWER], "p1"))) is None


def test_ups_ar_inte_husbatteri():
    assert battery(dev("u1", "APC", "Smart-UPS 3000 XLM", *uniq([SOC, BATT_POWER], "u1"))) is None


@pytest.mark.parametrize("maker,model,extra", [
    ("Tesla", "Model Y", []),
    ("Volkswagen", "ID.7", []),
    ("Kia_offline", "Sorento PHEV", []),
    ("VolvoCars", "Polestar", []),
    ("MINI", "Cooper SE", []),
    ("Kia Europe", "EV6", []),
    ("Okänd", "Bil", [TRACKER, RANGE]),      # okänt märke men positionsspårare och räckvidd
])
def test_riktiga_bilar_hittas(maker, model, extra):
    assert cars(dev("c1", maker, model, *uniq([SOC, *extra], "c1"), name="Bilen")) == ["Bilen"]


def test_positionsspårare_ensam_räcker_inte():
    assert cars(dev("t1", "Okänd", "Pryl", *uniq([SOC, TRACKER], "t1"))) == []


def test_huawei_luna_ar_fortfarande_husbatteri():
    ents = dev("h1", "Huawei", "LUNA2000-10-S0", *uniq([{**SOC, "n": "Battery state of capacity"}, {**BATT_POWER, "n": "Battery charge/discharge power"}], "h1"), name="Batteries")
    assert battery(ents) == "Batteries"
