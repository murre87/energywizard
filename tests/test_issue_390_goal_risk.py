"""#390: varna innan det är för sent när bilen inte hinner sitt mål, med laddboxens egna gränser inräknade, och
ta med laddboxens begränsning i förklaringen när målet missats."""
import os
from datetime import datetime, timedelta

import ev_missed as em

NOW = datetime(2026, 11, 14, 1, 0)


def test_hinner_inte():
    t, reach = em.goal_at_risk(40, 100, NOW + timedelta(hours=6), NOW, 75, 3.7)
    assert t.startswith("Hinner inte 100 % till 07:00: behöver 50 kWh, hinner ladda ungefär 20 kWh med 3.7 kW.")
    assert 60 < reach < 70


def test_hinner():
    assert em.goal_at_risk(40, 80, NOW + timedelta(hours=6), NOW, 75, 11.0) is None


def test_redan_vid_målet_eller_utan_mål():
    assert em.goal_at_risk(80, 80, NOW + timedelta(hours=1), NOW, 75, 3.7) is None
    assert em.goal_at_risk(40, 80, None, NOW, 75, 3.7) is None
    assert em.goal_at_risk(None, 80, NOW + timedelta(hours=1), NOW, 75, 3.7) is None


def test_bara_mål_inom_tolv_timmar_och_inte_passerade():
    assert em.goal_at_risk(10, 100, NOW + timedelta(hours=20), NOW, 75, 1.0) is None
    assert em.goal_at_risk(10, 100, NOW - timedelta(minutes=5), NOW, 75, 1.0) is None


def test_effekt_begränsas_av_laddboxens_gränser():
    assert em.effective_kw(16, 3) == 16 * 230 * 3 / 1000
    assert em.effective_kw(16, 3, {"circuit_limit_a": 10}) == 10 * 230 * 3 / 1000
    assert em.effective_kw(32, 1, {"circuit_rated_a": 16.0, "output_limit_a": None}) == 16 * 230 / 1000


def test_missad_förklaring_tar_med_laddboxens_gräns():
    txt = em.explain(30, 50, ordered_a=16, power_kw=2.3, status="charging",
                     charger_note="Lastbalanseringen tillåter 10 A. EnergyWizard bad om 16 A.")
    assert "Lastbalanseringen tillåter 10 A" in txt and txt.endswith("Kolla kabeln, bilens maxladdning och laddaren i Easee/HA.")


def test_kopplat():
    root = os.path.join(os.path.dirname(__file__), "..")
    rd = lambda *p: open(os.path.join(root, *p), encoding="utf-8").read()
    main = rd("smartbox", "main.py")
    assert "_ev_missed_mod.goal_at_risk(car_soc.get(car_id), _t_soc, _t_dt, now, _bkwh" in main
    assert 'charger_note=(globals().get("all_overrides") or {}).get(f"{car_id}_limit_note")' in main
    assert '"goal_risk":' in rd("ewapp", "app.py") and "c.goal_risk" in rd("ewapp", "static", "app.js")
