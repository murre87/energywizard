"""Besparingskortet (smartbox/savings.py): samma formel som den publika sidan,
(dygnssnitt - betalt snittpris) × köpt kWh, summerat över Idag / 7 dagar / Månad."""
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "smartbox")))

from savings import build_day, summarize_periods


def test_en_dag_samma_formel_som_publika_sidan():
    r = build_day("2026-11-02", kwh=20.0, day_avg=1.00, paid_avg=0.70)
    assert r["saved_kr"] == 6.0            # (1.00 - 0.70) × 20
    assert r["would_cost_kr"] == 20.0


def test_dag_som_kopte_dyrare_an_snittet_blir_negativ():
    assert build_day("2026-11-02", 10.0, 0.50, 0.60)["saved_kr"] == -1.0


def test_saknade_varden_ger_ingen_rad():
    assert build_day("2026-11-02", None, 1.0, 0.5) is None
    assert build_day("2026-11-02", 10.0, 1.0, None) is None


def test_perioder_idag_vecka_manad():
    rows = [build_day(d, 10.0, 1.0, 0.8) for d in
            ("2026-10-25", "2026-10-31", "2026-11-01", "2026-11-02")]   # 2 kr/dag
    p = summarize_periods(rows, "2026-11-02")
    assert p["today"]["saved_kr"] == 2.0 and p["today"]["days"] == 1
    assert p["week"]["days"] == 3 and p["week"]["saved_kr"] == 6.0      # 27 okt-2 nov, inte 25 okt
    assert p["month"]["days"] == 2 and p["month"]["saved_kr"] == 4.0    # bara november
    assert p["today"]["pct"] == 20.0                                    # 2 kr av 10 kr
    assert p["today"]["paid_kr"] == 8.0


def test_tom_historik_ger_noll_och_ingen_procent():
    p = summarize_periods([], "2026-11-02")
    assert p["today"] == {"saved_kr": 0, "kwh": 0, "paid_kr": 0, "pct": None, "days": 0}


def test_procent_doljs_nar_jamforelsekostnaden_ar_nara_noll():
    """Minuspris-dag: vad elen 'hade kostat' kan vara ~0 eller negativt - procent blir då meningslöst."""
    p = summarize_periods([build_day("2026-11-02", 10.0, -0.02, -0.10)], "2026-11-02")
    assert p["today"]["pct"] is None and p["today"]["saved_kr"] == 0.8


def test_avgifter_gor_att_betalt_snitt_kan_sla_hogsta_spot():
    """#510: snittet på köpt el är inklusive avgifter. Högsta spotpriset är det inte."""
    from datetime import datetime, timezone
    from savings import price_span
    cheap = datetime(2026, 11, 18, 6, tzinfo=timezone.utc)
    peak = datetime(2026, 11, 18, 17, tzinfo=timezone.utc)
    span = price_span([(cheap, 0.80), (peak, 2.43), (peak, None)], buy_cost=lambda spot, t: spot + 0.50)
    assert span["spot"]["max"] == 2.43
    assert span["buy"]["min"] == 1.30 and span["buy"]["max"] == 2.93
    assert span["buy"]["max"] > span["spot"]["max"]
    assert round(span["spot"]["avg"], 4) == round((0.80 + 2.43) / 2, 4)
    # Tidstariffen hör till timmen, så högst att köpa kan skilja sig från ett fast påslag.
    span = price_span([(cheap, 1.0), (peak, 1.0)], buy_cost=lambda spot, t: spot + (0.2 if t.hour >= 17 else 0))
    assert span["buy"]["min"] == 1.0 and span["buy"]["max"] == 1.2


def test_prisintervall_utan_rader():
    from savings import price_span
    empty = {"min": None, "avg": None, "max": None}
    assert price_span([]) == {"spot": empty, "buy": empty}
    assert price_span([(None, None)], buy_cost=lambda spot, t: spot)["spot"]["max"] is None


def test_pengar_per_period():
    from savings import money_periods
    rows = [{"day": "2026-10-20", "bought_kwh": 10, "cost": 30, "sold_kwh": 0, "income": 0, "net": 30},
            {"day": "2026-11-01", "bought_kwh": 20, "cost": 50, "sold_kwh": 5, "income": 4, "net": 46},
            {"day": "2026-11-03", "bought_kwh": 10, "cost": 25, "sold_kwh": 2, "income": 3, "net": 22}]
    p = money_periods(rows, "2026-11-03")
    assert p["today"]["net"] == 22 and p["today"]["avg_paid"] == 2.5
    assert p["week"]["cost"] == 75 and p["week"]["days"] == 2
    assert p["month"]["income"] == 7 and p["month"]["days"] == 2
    assert money_periods([], "2026-11-03")["today"]["avg_paid"] is None
    assert p["today"]["avg_sold"] == 1.5 and p["week"]["avg_sold"] == 1.0
    assert money_periods([], "2026-11-03")["today"]["avg_sold"] is None


def test_jamfort_med_vanlig_hushallsprofil_och_moms():
    """2026-11-05: besparingen mäts mot ett vanligt hushåll (toppar morgon/kväll), inkl. moms."""
    from savings import profile_day, PROFILE
    # dyrt 17-20 (2 kr), annars 1 kr; huset köpte allt billigt (10 kWh à 1 kr)
    hours = [(h, 2.0 if 17 <= h <= 20 else 1.0, 10 / 24 if not 17 <= h <= 20 else 0, (10 / 24) * 1.0 if not 17 <= h <= 20 else 0)
             for h in range(24)]
    kwh, prof_price, paid = profile_day(hours)
    assert abs(kwh - 10 * 20 / 24) < 1e-9 and abs(paid - 1.0) < 1e-9
    assert abs(prof_price - (1 + sum(PROFILE[17:21]))) < 1e-9          # profilen lägger mer på de dyra timmarna
    r = build_day("2026-11-05", kwh, prof_price, paid, vat=1.25)
    assert r["saved_kr"] == round((prof_price - paid) * kwh * 1.25, 2) and r["saved_kr"] > 0
    assert profile_day([(h, 1.0, 0, 0) for h in range(24)]) is None     # inget köpt -> ingen rad


def test_idag_hittills_raknas_fran_forsta_timmen():
    """HA-sensorn sensor.smartbox_besparing_idag fanns inte före lunch (kravet på 12 timmar)."""
    from savings import profile_day
    morning = [(h, 1.0 + h / 10, 1.5, 1.5 * (1.0 + h / 10)) for h in range(0, 8)]
    assert profile_day(morning) is None                                    # hela dygn kräver fortfarande 12 timmar
    kwh, prof, paid = profile_day(morning, min_hours=1)
    assert kwh == 12.0 and prof > 0 and paid > 0


def test_manader_tar_med_dagar_som_finns_och_hoppar_over_luckor():
    """#599: Månader på Ekonomisidan är samma summa som Idag, en stapel per kalendermånad.
    En månad utan rader visas inte som noll, och en dag efter idag räknas inte."""
    from savings import build_day, money_by_month, timing_by_month
    rows = [{"day": "2026-10-20", "bought_kwh": 10, "cost": 30, "sold_kwh": 0, "income": 0, "net": 30},
            {"day": "2026-11-01", "bought_kwh": 20, "cost": 50, "sold_kwh": 5, "income": 4, "net": 46},
            {"day": "2026-11-03", "bought_kwh": 10, "cost": 25, "sold_kwh": 2, "income": 3, "net": 22},
            {"day": "2026-12-01", "bought_kwh": 99, "cost": 99, "sold_kwh": 0, "income": 0, "net": 99}]
    months = money_by_month(rows, "2026-11-03")
    assert [m["month"] for m in months] == ["2026-10", "2026-11"]
    assert months[0]["days"] == 1 and months[0]["cost"] == 30 and months[0]["net"] == 30
    assert months[1]["days"] == 2 and months[1]["cost"] == 75 and months[1]["income"] == 7 and months[1]["net"] == 68
    assert "2026-09" not in [m["month"] for m in months]
    assert money_by_month([], "2026-11-03") == []
    saved = [build_day(d, 10.0, 1.0, 0.8) for d in ("2026-10-20", "2026-11-01", "2026-11-03", "2026-12-01")]
    timing = timing_by_month(saved, "2026-11-03")
    assert [m["month"] for m in timing] == ["2026-10", "2026-11"]
    assert timing[0]["saved_kr"] == 2.0 and timing[0]["days"] == 1
    assert timing[1]["saved_kr"] == 4.0 and timing[1]["days"] == 2 and timing[1]["pct"] == 20.0


def test_economy_months_slar_ihop_sidorna_och_cachar(monkeypatch):
    from savings import build_day, economy_months
    import savings
    savings._months_cache.update(t=0.0, day=None, val=None)
    money = [{"day": "2026-10-20", "bought_kwh": 10, "cost": 30, "sold_kwh": 0, "income": 0, "net": 30}]
    monkeypatch.setattr(savings, "money_rows", lambda c, days=40: money)
    monkeypatch.setattr(savings, "daily_rows", lambda c, days=40: [build_day("2026-11-02", 10.0, 1.0, 0.8)])
    out = economy_months(object(), "2026-11-03")
    assert [r["month"] for r in out] == ["2026-10", "2026-11"]
    assert out[0]["money"]["cost"] == 30 and out[0]["timing"] is None
    assert out[1]["money"] is None and out[1]["timing"]["saved_kr"] == 2.0
    monkeypatch.setattr(savings, "money_rows", lambda c, days=40: (_ for _ in ()).throw(AssertionError("cache")))
    assert economy_months(object(), "2026-11-03") == out
    savings._months_cache.update(t=0.0, day=None, val=None)
