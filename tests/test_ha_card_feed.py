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


def test_sol_och_batteri_med_niva_och_prognos():
    """#558: kortsensorn hade bara battery true/false och bat_kw. Laddnivån, planen och solprognosen följer med."""
    flow = {"nodes": [
        {"key": "sol", "label": "Sol", "w": 1847.2, "active": True, "detail": "1.8 kW", "role": "source"},
        {"key": "batteri", "label": "Batteri", "w": -820.4, "active": True, "detail": "Laddar ur · 95 %", "role": "battery"},
    ]}
    later = (NOW + timedelta(days=1)).replace(hour=10, minute=0)
    pc = {"has_battery": True, "slots": [
        {"t": NOW.replace(hour=14, minute=0).isoformat(), "price": 2.0, "spot": 1.4, "heat": "EXPENSIVE",
         "sun_w": 1800, "ev": {}, "bat": "discharge", "bat_kw": -2.5, "soc": 96},
        {"t": NOW.replace(hour=14, minute=30).isoformat(), "price": 1.1, "spot": 0.5, "heat": "CHEAP",
         "sun_w": 400, "ev": {}, "bat": "hold", "bat_kw": 0, "soc": 94},
        {"t": later.isoformat(), "price": 1.0, "spot": 0.4, "heat": "",
         "sun_w": 2000, "ev": {}, "bat": "charge", "bat_kw": 3, "soc": 40},
    ]}
    _, a = ha_card_feed.build(flow, pc, now=NOW)
    assert a["battery"] is True
    assert a["batt"] == {"soc": 95, "w": -820, "plan": "hold", "plan_kw": 0.0}   # uppmätt 95 % går före planens 94
    assert a["solar"] == {"w": 1847, "today_kwh": 0.55, "tomorrow_kwh": 0.5}
    assert a["slots"][0][6] == -2.5                                              # den komprimerade raden är kvar

    no_meter = {"nodes": [{"key": "batteri", "label": "Batteri", "w": 0, "active": False, "detail": "Vilar", "role": "battery"}]}
    _, b = ha_card_feed.build(no_meter, pc, now=NOW)
    assert b["batt"]["soc"] == 94 and b["batt"]["plan"] == "hold"               # planens nivå när mätningen saknar procent
    _, c = ha_card_feed.build({"nodes": []}, {"has_battery": False, "slots": []}, now=NOW)
    assert c["batt"] is None and c["solar"] is None and c["battery"] is False


def test_tom_data_kraschar_inte():
    state, a = ha_card_feed.build({}, {}, now=NOW)
    assert state == "okänt" and a["flow"] == [] and a["slots"] == [] and a["price"]["now"] is None and a["cars"] == []


def test_attributen_ryms_i_havets_grans_med_en_hel_dag():
    pc = {"ok": True, "has_battery": True, "cars": [{"id": "a", "name": "A"}, {"id": "b", "name": "B"}],
          "slots": [_slot(15 * i, 2.0 + i / 100, "CHEAP" if i % 2 else "EXPENSIVE", {"a": 3.7, "b": 1.4}, sun=900) for i in range(96)]}
    _, a = ha_card_feed.build(FLOW, pc, now=NOW)
    assert len(json.dumps(a, ensure_ascii=False)) < 16000
