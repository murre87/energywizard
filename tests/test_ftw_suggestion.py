"""Guiden namnger FTW-drivrutinen när Home Assistant kan läsa batteriet men inte styra det."""
from pathlib import Path

from discovery import discover_house

ROOT = Path(__file__).resolve().parents[1]


def E(e, n, m, dc=None, u=None, st="50", d="dev1"):
    return {"e": e, "n": n, "a": None, "d": d, "dn": m, "m": m, "mo": "", "dc": dc, "u": u, "st": st}


def _battery(maker, soc="sensor.x_soc", power="sensor.x_p", power_w="400"):
    return discover_house([
        E(soc, "Battery SOC", maker, dc="battery", u="%"),
        E(power, "Battery Power", maker, dc="power", u="W", st=power_w),
    ])


def test_deye_utan_styrning_foreslar_ftw():
    house = _battery("Deye", "sensor.deye_soc", "sensor.deye_p")
    hint = house["ftw_suggestion"]
    assert hint["driver"] == "deye" and hint["battery"] is True and hint["solar"] is True
    assert "deye" in house["battery"]["note"]
    assert "modes" not in (house["battery"].get("generic_suggestion") or {})


def test_sunsynk_ar_samma_drivrutin_som_deye():
    assert _battery("Sunsynk")["ftw_suggestion"]["driver"] == "deye"


def test_solinteg_sigenergy_och_pixii():
    solinteg = _battery("Solinteg")["ftw_suggestion"]
    assert solinteg["driver"] == "solinteg" and solinteg["solar"] is True and solinteg["battery"] is True
    assert _battery("Sigenergy")["ftw_suggestion"]["driver"] == "sigenergy"
    assert _battery("SigenStor")["ftw_suggestion"]["driver"] == "sigenergy"
    pixii = _battery("Pixii")["ftw_suggestion"]
    assert pixii["driver"] == "pixii" and pixii["solar"] is False and pixii["battery"] is True


def test_entity_id_deye_racker_nar_tillverkaren_ar_solarman():
    house = _battery("Solarman", "sensor.deye_battery_soc", "sensor.deye_battery_power")
    assert house["ftw_suggestion"]["driver"] == "deye"


def test_goodwe_med_lagen_foreslas_inte():
    house = discover_house([
        E("sensor.gw_soc", "Battery State of Charge", "GoodWe", dc="battery", u="%"),
        E("sensor.gw_p", "Battery Power", "GoodWe", dc="power", u="W", st="-300"),
        {**E("select.gw_mode", "Inverter operation mode", "GoodWe", st="general"),
         "options": ["general", "eco_charge", "eco_discharge"]},
    ])
    assert "ftw_suggestion" not in house
    assert house["battery"]["generic_suggestion"]["preset"] == "goodwe"
    assert "FTW-drivrutinen" not in (house["battery"].get("note") or "")


def test_okant_batteri_foreslas_inte():
    assert "ftw_suggestion" not in _battery("Acme", "sensor.acme_soc", "sensor.acme_p")


def test_deye_bara_sol_foreslar_anda():
    house = discover_house([
        E("sensor.deye_pv", "PV Power", "Deye", dc="power", u="W", st="2500"),
    ])
    assert house["battery"] is None
    assert house["solar"]["pv_power_entity"] == "sensor.deye_pv"
    assert house["ftw_suggestion"]["driver"] == "deye"
    assert "deye" in house["solar"]["note"]


def test_knappen_kryssar_inte_i_styrning():
    js = (ROOT / "webdashboard/static/app.js").read_text(encoding="utf-8")
    start = js.index("function mountFtwSuggestion")
    body = js[start:js.index("\nfunction ", start + 10)]
    assert "ctl.checked = false" in body
    assert "ctl.checked = true" not in body
    assert "mountFtwSuggestion(d.ftw_suggestion)" in js
