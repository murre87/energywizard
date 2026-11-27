"""sensor.energywizard_kort (smartbox/ha_card_feed.py): korten i HA ritar ur den här sensorns attribut."""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "smartbox")))

import ha_card_feed

NOW = datetime(2026, 11, 20, 14, 30, tzinfo=timezone(timedelta(hours=1)))


def _slot(minutes, price, heat="EXPENSIVE", ev=None, sun=0):
    t = (NOW.replace(hour=14, minute=0) + timedelta(minutes=minutes)).isoformat()
    return {"t": t, "spot": price - 0.6, "price": price, "bat": None, "bat_kw": None, "soc": None, "bat_balance": False,
            "ev": ev or {}, "heat": heat, "sun_w": sun}


FLOW = {"nodes": [
    {"key": "sol", "label": "Sol", "icon": "☀️", "w": 47.4, "active": False, "detail": "0.0 kW", "page": "x", "role": "source"},
    {"key": "nat", "label": "Elnät", "icon": "🔌", "w": 8212, "active": True, "detail": "Köper 8.2 kW", "page": "x", "role": "grid"},
    {"key": "ev_nissan", "label": "Nissan Leaf", "icon": "🚗", "w": None, "active": False, "detail": "Laddar inte · 64 %", "role": "load"}],
    "why": {"ev_nissan": "x" * 500}}
PC = {"ok": True, "now": NOW.isoformat(), "has_battery": False, "cars": [{"id": "nissan", "name": "Nissan Leaf"}],
      "slots": [_slot(0, 2.5), _slot(15, 2.6, "CHEAP", {"nissan": 3.7}, sun=1200), _slot(30, 1.1, "CHEAP"), _slot(45, 1.0, "CHEAP")]}


def test_tillstand_och_pris_ur_pagaende_kvart():
    state, a = ha_card_feed.build(FLOW, PC, now=NOW, unit="kr")
    assert a["price"] == {"now": 1.1, "spot": 0.5, "mode": "C"} and state == "billigt"      # 14:30-kvarten pågår
    assert a["v"] == 1 and a["unit"] == "kr" and a["battery"] is False


def test_flodet_blir_korta_poster_med_hela_watt():
    _, a = ha_card_feed.build(FLOW, PC, now=NOW)
    assert a["flow"][0] == {"k": "sol", "l": "Sol", "i": "☀️", "w": 47, "on": False, "d": "0.0 kW", "r": "source"}
    assert a["flow"][2]["w"] is None and a["flow"][1]["on"] is True
    assert len(a["why"]["ev_nissan"]) == 240                       # förklaringen kortas


def test_planen_en_rad_per_kvart_med_elbil_summerad():
    _, a = ha_card_feed.build(FLOW, PC, now=NOW)
    assert len(a["slots"]) == 4 and a["slots"][1][3] == "C" and a["slots"][1][5] == 3.7 and a["slots"][1][4] == 1200
    assert a["slots"][0][3] == "E" and a["slots"][0][5] == 0


def test_bilar_med_laddniva_och_planerade_pass():
    flow = {"nodes": [{"key": "ev_nissan", "label": "Nissan Leaf", "w": 3700, "active": True, "detail": "Laddar 3.7 kW · 64 %", "role": "load"},
                      {"key": "sol", "label": "Sol", "w": 0, "active": False, "detail": "0 kW", "role": "source"}]}
    pc = {"cars": [], "slots": [_slot(0, 2.5), _slot(15, 1.2, "CHEAP", {"nissan": 3.7}), _slot(30, 1.1, "CHEAP", {"nissan": 3.7}),
                                _slot(45, 1.0, "CHEAP"), _slot(60, 1.0, "CHEAP", {"nissan": 1.4})]}
    _, a = ha_card_feed.build(flow, pc, now=NOW)
    car = a["cars"][0]
    assert car["id"] == "nissan" and car["soc"] == 64 and car["w"] == 3700 and car["on"] is True
    assert len(car["win"]) == 2 and car["win"][0][1] - car["win"][0][0] == 1800 and car["win"][0][2] == 3.7 and car["win"][1][2] == 1.4


def test_varme_ur_senaste_raden_och_installningar():
    row = {"indoor_temp": 21.44, "target_room_temp": 20.0, "room_temp_setpoint": 21.0, "outdoor_temp": -2.0, "water_temp": 59.4,
           "water_setpoint": 60, "active_mode": "EXPENSIVE", "cop": 3.26}
    _, a = ha_card_feed.build(FLOW, PC, now=NOW, row=row, cfg={"temp_expensive": 20.5, "temp_cheap": 22.5, "indoor_max": 22.0, "indoor_min": 19.0})
    h = a["heat"]
    assert h["indoor"] == 21.4 and h["setpoint"] == 21.0 and h["mode"] == "E" and h["water"] == 59 and h["floor"] == 20.5 and h["max"] == 22.0
    assert ha_card_feed.build(FLOW, PC, now=NOW)[1]["heat"] is None


def test_varmepumpens_effekt_ar_elforbrukningen_inte_varmen():
    flow = {"nodes": [{"key": "varmepump", "label": "Värmepump", "w": 11500, "active": True, "detail": "Går", "role": "load"},
                      {"key": "spabad", "label": "Spabad", "w": 180, "active": False, "detail": "38 °C", "role": "load"}]}
    _, a = ha_card_feed.build(flow, PC, now=NOW, pump_w=2718.4)
    assert [n["w"] for n in a["flow"]] == [2718, 180]                       # bara värmepumpen byts
    _, b = ha_card_feed.build(flow, PC, now=NOW)
    assert b["flow"][0]["w"] == 11500                                       # utan mätvärde som förut


def test_tom_data_kraschar_inte():
    state, a = ha_card_feed.build({}, {}, now=NOW)
    assert state == "okänt" and a["flow"] == [] and a["slots"] == [] and a["price"]["now"] is None and a["cars"] == []
    assert a["eco"] is None


def test_ekonomi_perioder_utan_dagar_ar_inte_noll():
    """#558: kortet visar köpt, sålt, tajmning och självförbrukning. Tom period är null, inte 0.
    Sedan start (all) följer inte med."""
    money = {"today": {"bought_kwh": 10.0, "cost": 25.0, "sold_kwh": 2.0, "income": 3.0, "net": 22.0,
                       "avg_paid": 2.5, "avg_sold": 1.5, "days": 1},
             "week": {"bought_kwh": 0, "cost": 0, "sold_kwh": 0, "income": 0, "net": 0, "avg_paid": None, "avg_sold": None, "days": 0},
             "month": {"bought_kwh": 30.0, "cost": 75.0, "sold_kwh": 0.0, "income": 0.0, "net": 75.0,
                       "avg_paid": 2.5, "avg_sold": None, "days": 2}}
    timing = {"today": {"saved_kr": 4.2, "pct": 13.1, "days": 1},
              "week": {"saved_kr": 0, "pct": None, "days": 0},
              "month": {"saved_kr": 9.0, "pct": 8.0, "days": 2},
              "all": {"saved_kr": 400.0, "pct": 11.0, "days": 80, "since": "2024-01-01"}}
    battery = {"today": {"saved": 1.8, "days": 1}, "week": None, "month": {"saved": 0.0, "days": 2}}
    eco = ha_card_feed.pack_economy(money, timing, battery)
    assert set(eco) == {"today", "week", "month"}
    assert eco["today"] == {"buy_kwh": 10.0, "buy": 25.0, "buy_avg": 2.5, "sell_kwh": 2.0, "sell": 3.0,
                            "sell_avg": 1.5, "net": 22.0, "saved": 4.2, "pct": 13.1, "bat": 1.8}
    assert eco["week"] == {"buy_kwh": None, "buy": None, "buy_avg": None, "sell_kwh": None, "sell": None,
                           "sell_avg": None, "net": None, "saved": None, "pct": None, "bat": None}
    assert eco["month"]["sell_avg"] is None and eco["month"]["bat"] == 0.0 and eco["month"]["saved"] == 9.0
    assert ha_card_feed.pack_economy(None, None, None) is None
    _, a = ha_card_feed.build(FLOW, PC, now=NOW, economy=eco)
    assert a["eco"]["today"]["buy"] == 25.0 and "all" not in a["eco"]


def test_attributen_ryms_i_havets_grans_med_en_hel_dag():
    pc = {"ok": True, "has_battery": True, "cars": [{"id": "a", "name": "A"}, {"id": "b", "name": "B"}],
          "slots": [_slot(15 * i, 2.0 + i / 100, "CHEAP" if i % 2 else "EXPENSIVE", {"a": 3.7, "b": 1.4}, sun=900) for i in range(96)]}
    _, a = ha_card_feed.build(FLOW, pc, now=NOW, economy=ha_card_feed.pack_economy(
        {"today": {"bought_kwh": 1, "cost": 2, "sold_kwh": 0, "income": 0, "net": 2, "avg_paid": 2, "avg_sold": None, "days": 1},
         "week": {"days": 0}, "month": {"days": 0}},
        {"today": {"saved_kr": 1, "pct": 10, "days": 1}, "week": {"days": 0}, "month": {"days": 0}, "all": {"saved_kr": 9, "days": 3}},
        {"today": {"saved": 0.5, "days": 1}, "week": None, "month": None}))
    assert "all" not in a["eco"]
    assert len(json.dumps(a, ensure_ascii=False)) < 16000
