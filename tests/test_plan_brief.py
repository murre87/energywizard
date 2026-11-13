"""Planen i klartext (smartbox/plan_brief.py). Värmepumpens perioder räknas med motorns
RIKTIGA prisregel (nordpool.calculate_day_strategy), inte en kopia av den."""
import os
import sys
import pytest
from datetime import datetime, timedelta

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "smartbox")))

import nordpool
from plan_brief import SWE, build_brief, ev_items, heat_items

DAY = datetime(2026, 11, 2, tzinfo=SWE)


def _prices(hourly, day=DAY):
    """24 timpriser -> 96 kvartspriser (samma upplösning som elpriser-tabellen)."""
    return [(day + timedelta(minutes=15 * i), hourly[i // 4]) for i in range(96)]


# Billigt på natten, dyrt morgon och kväll - en vanlig vinterdag.
WINTER = [0.30] * 6 + [1.80] * 3 + [0.90] * 8 + [2.20] * 4 + [0.60] * 3


@pytest.mark.parametrize('active_flags',[[],[True],[False],[True,False]])
def test_headline_parts_preserve_source_and_separate_translatable_values(monkeypatch,active_flags):
    import plan_brief
    items=[dict(start=(DAY+timedelta(hours=i)).isoformat(),kind='heat',active=active,
                title='😌 Jämn komfort hela dygnet',when='imorgon 00:00–imorgon 24:00')
           for i,active in enumerate(active_flags)]
    monkeypatch.setattr(plan_brief,'ev_items',lambda *args:[])
    monkeypatch.setattr(plan_brief,'heat_items',lambda *args:items)
    monkeypatch.setattr(plan_brief,'battery_items',lambda *args:[])
    result=build_brief(DAY,[],[],lambda *args:None)
    assert ''.join(result['headline_parts'])==result['headline']
    if items:
        assert 'Jämn komfort hela dygnet' in result['headline_parts']
        assert 'imorgon 00:00–imorgon 24:00' in result['headline_parts']


def test_elbilens_slottar_slas_ihop_till_ett_pass_med_snittpris():
    rows = [("tesla", datetime(2026, 11, 2, 2, 0) + timedelta(minutes=15 * i), 11.0) for i in range(12)]
    items = ev_items(rows, _prices(WINTER), DAY)
    assert len(items) == 1
    it = items[0]
    assert it["title"] == "🚗 Tesla laddar" and it["when"] == "02:00–05:00"
    assert "11,0 kW" in it["detail"] and "33,0 kWh" in it["detail"]
    assert "snittpris 30 öre/kWh" in it["detail"]
    assert not it["active"]


def test_tva_separata_pass_och_tva_bilar():
    rows = [("tesla", datetime(2026, 11, 2, 1, 0), 11.0), ("tesla", datetime(2026, 11, 2, 4, 0), 11.0),
            ("nissan", datetime(2026, 11, 2, 1, 0), 3.7)]
    items = ev_items(rows, _prices(WINTER), DAY)
    assert sorted(i["title"] for i in items) == ["🚗 Nissan laddar", "🚗 Tesla laddar", "🚗 Tesla laddar"]


def test_passerade_pass_visas_inte_och_pagaende_ar_aktivt():
    rows = [("tesla", datetime(2026, 11, 2, 1, 0) + timedelta(minutes=15 * i), 11.0) for i in range(8)]  # 01-03
    assert ev_items(rows, _prices(WINTER), DAY.replace(hour=4)) == []
    it = ev_items(rows, _prices(WINTER), DAY.replace(hour=2))[0]
    assert it["active"] and it["when"] == "till 03:00"


def test_varmepumpen_foljer_motorns_prisregel():
    strat = nordpool.calculate_day_strategy([p for _, p in _prices(WINTER)], 8)
    assert strat["mode"] == "optimize"
    items = heat_items(_prices(WINTER), DAY, nordpool.calculate_day_strategy, 8)
    modes = [(i["mode"], i["when"]) for i in items]
    # 8 billigaste timmarna: 6 h à 0.30 + 2 av 3 h à 0.60 -> gränsen blir 0.60 kr, hysteres 0.20.
    assert strat["dynamic_limit"] == 0.60 and strat["hysteresis"] == 0.20
    assert modes[0] == ("CHEAP", "till 06:00")             # nattens billiga timmar (klockan är 00:00)
    # 0.60 kl 21-24 ligger i gråzonen (0.40-0.80) -> läget stannar på dyrt till midnatt,
    # precis som gpm.py gör. Midnatt visas som 24:00, inte "imorgon 00:00".
    assert modes[1] == ("EXPENSIVE", "06:00–24:00")
    for i in items:
        assert i["kind"] == "heat" and i["title"] and i["detail"]


def test_gratzonen_behaller_foregaende_lage():
    """Ett pris precis vid gränsen (inom hysteresen) byter inte läge."""
    strat = nordpool.calculate_day_strategy([p for _, p in _prices(WINTER)], 8)
    lim, h = strat["dynamic_limit"], strat["hysteresis"]
    hourly = [0.30] * 6 + [lim + h / 2] * 2 + [2.2] * 16
    items = heat_items(_prices(hourly), DAY, lambda prices, n: strat, 8)
    assert items[0]["mode"] == "CHEAP" and items[0]["when"] == "till 08:00"


def test_billig_platt_dag_ger_jamn_komfort():
    flat = [0.20] * 24
    items = heat_items(_prices(flat), DAY, nordpool.calculate_day_strategy, 8)
    assert len(items) == 1 and items[0]["mode"] == "COMFORT"


def test_morgondagens_priser_far_imorgon_i_tiden():
    prices = _prices(WINTER) + _prices(WINTER, DAY + timedelta(days=1))
    items = heat_items(prices, DAY.replace(hour=22), nordpool.calculate_day_strategy, 8)
    assert any("imorgon" in i["when"] for i in items)


def test_samma_lage_over_midnatt_blir_en_period():
    """Dyrt på kvällen och dyrt direkt efter midnatt = en rad, inte två."""
    hourly_today = [0.30] * 8 + [2.0] * 16
    # Imorgon: 0.05 kr ligger mer än hysteresen under gränsen (0.30) -> billigt läge kl 04.
    hourly_tomorrow = [2.0] * 4 + [0.05] * 4 + [0.30] * 4 + [2.0] * 12
    prices = _prices(hourly_today) + _prices(hourly_tomorrow, DAY + timedelta(days=1))
    items = heat_items(prices, DAY.replace(hour=20), nordpool.calculate_day_strategy, 8)
    assert items[0]["mode"] == "EXPENSIVE" and items[0]["when"] == "till imorgon 04:00"


def test_sammanfattning_har_rubrik_och_ar_sorterad():
    rows = [("tesla", datetime(2026, 11, 2, 2, 0) + timedelta(minutes=15 * i), 11.0) for i in range(4)]
    b = build_brief(DAY.replace(hour=1), _prices(WINTER), rows, nordpool.calculate_day_strategy, 8)
    assert b["headline"] == "Just nu: Huset laddas med värme. Härnäst 02:00–03:00: Tesla laddar."
    starts = [i["start"] for i in b["items"]]
    assert starts == sorted(starts)
    assert "grundläget" in b["note"]


def test_utan_priser_och_plan():
    b = build_brief(DAY, [], [], nordpool.calculate_day_strategy, 8)
    assert b["items"] == [] and "Inget planerat" in b["headline"]


def test_dokumenterar_motorns_nuvarande_regel_jamn_billig_natt_ger_inget_billigt_lage():
    """Inte ett önskat beteende, utan motorns FAKTISKA regel (gpm.py): billigt läge kräver
    pris <= gräns - hysteres, där gränsen är det N:te billigaste priset. En jämn billig natt
    hamnar då i gråzonen och läget byts aldrig. Planen ska visa det ärligt - ändras regeln i
    gpm.py ska det här testet ändras samtidigt."""
    hourly = [0.30] * 8 + [2.0] * 16
    items = heat_items(_prices(hourly), DAY, nordpool.calculate_day_strategy, 8, current_mode="EXPENSIVE")
    assert [i["mode"] for i in items] == ["EXPENSIVE"]
