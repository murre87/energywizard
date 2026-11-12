"""Dygnet timme för timme (smartbox/timeline.py) och just nu-flödet (smartbox/live_flow.py)."""
import os
import sys
from datetime import datetime, timedelta

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "smartbox")))

from timeline import SWE, build
from live_flow import nodes

NOW = datetime(2026, 11, 2, 14, 20, tzinfo=SWE)
H0 = NOW.replace(minute=0)


def _past():
    out = {}
    for k in range(24, -1, -1):
        h = H0 - timedelta(hours=k)
        out[h] = {"price": 1.0, "solar_kw": 2.0 if 9 <= h.hour <= 15 else 0.0, "compressor": 0.5,
                  "spa": 1.0 if h.hour == 3 else 0.0, "ev": {"tesla": 11.0 if h.hour in (2, 3) else 0.0, "nissan": 0.0}}
    return out


def test_bakat_uppmatt_framat_planerat():
    fut_prices = {H0 + timedelta(hours=k): 0.5 for k in range(1, 10)}
    d = build(NOW, _past(), fut_prices, {}, {H0 + timedelta(hours=2): "CHEAP"}, {H0 + timedelta(hours=3): {"tesla": 11.0}},
              car_ids=["nissan", "tesla"])
    assert d["now"] == H0.isoformat()
    assert len(d["hours"]) == 24 + 1 + 9                       # 24 bakåt, nuvarande timme, 9 framåt
    i_now = d["hours"].index(H0.isoformat())
    assert d["future"][i_now] is False and d["future"][i_now + 1] is True
    lanes = {l["key"]: l for l in d["lanes"]}
    assert lanes["varmepump"]["text"][i_now] == "Kompressorn gick 30 min"
    assert lanes["varmepump"]["text"][i_now + 2].startswith("Planerat: billigt")
    assert lanes["spabad"]["values"][i_now + 1] is None        # ingen plan framåt för spabadet
    assert lanes["ev_tesla"]["text"][i_now + 3] == "Planerat: 11.0 kWh"
    assert lanes["ev_tesla"]["values"][i_now + 3] == 1.0       # normerat mot största laddningen


def test_framat_bara_sa_langt_priserna_racker():
    d = build(NOW, _past(), {H0 + timedelta(hours=1): 0.5}, {}, {}, {})
    assert d["hours"][-1] == (H0 + timedelta(hours=1)).isoformat()


def test_framat_hela_leverantorens_priser():
    """Imorgondygnet publiceras runt lunch och ligger längre än 24 h fram. Hela serien ska med."""
    fut = {H0 + timedelta(hours=k): round(0.40 + k / 100, 2) for k in range(1, 37)}
    d = build(NOW, _past(), fut, {}, {}, {})
    assert d["hours"][-1] == (H0 + timedelta(hours=36)).isoformat()
    assert d["price"][-1] == 0.76
    assert d["future"][-1] is True
    assert sum(1 for f in d["future"] if f) == 36


def test_framat_tak_mot_felaktig_tidsstampel():
    fut = {H0 + timedelta(hours=k): 1.0 for k in range(1, 90)}
    d = build(NOW, _past(), fut, {}, {}, {})
    assert d["hours"][-1] == (H0 + timedelta(hours=72)).isoformat()


def test_flode_bara_det_huset_har():
    row = {"pv_power_w": 4200, "net_power": -1500, "house_consumption_w": 2700, "compressor_running": 1,
           "compressor_power_kw": 1.8, "indoor_temp": 21.4, "water_temp": 48, "water_mode": 0}
    n = {x["key"]: x for x in nodes(row)["nodes"]}
    assert set(n) == {"sol", "nat", "hus", "varmepump", "varmvatten"}     # inget spabad, ingen bil, inget batteri
    assert n["nat"]["detail"] == "Säljer 1.5 kW" and n["nat"]["active"]
    assert n["varmepump"]["active"] and n["varmepump"]["w"] == 1800
    assert not n["varmvatten"]["active"]


def test_flode_bilar_spa_batteri_och_varfor():
    row = {"pv_power_w": 0, "net_power": 9000, "ev_carport_power_kw": 11.0, "tesla_soc": 54, "ev_power_kw": 0, "nissan_soc": 80,
           "spa_temp": 37.5, "spa_power_w": 3000, "spa_heater_running": 1, "battery_power_w": -800, "battery_soc": 60}
    d = nodes(row, [{"key": "elbil", "text": "Laddar enligt schema."}, {"key": "spabad", "text": "Minuspris – värmer."}],
              cars=[("nissan", "Nissan", "ev_power_kw"), ("tesla", "Tesla", "ev_carport_power_kw")])    # installationens bilar
    n = {x["key"]: x for x in d["nodes"]}
    assert n["ev_tesla"]["active"] and n["ev_tesla"]["detail"] == "Laddar 11.0 kW · 54 %"
    assert not n["ev_nissan"]["active"]
    assert n["spabad"]["active"] and n["batteri"]["detail"] == "Laddar ur · 60 %"
    assert d["why"]["spabad"] == "Minuspris – värmer." and d["why"]["ev_tesla"] == "Laddar enligt schema."
