"""#386: felsökning per kvart - beställt mot uppmätt per enhet, pris, uppmätt energi och täckning.
Saknade minuter räknas aldrig som att planen följdes."""
import os
from datetime import datetime, timedelta, timezone

import support_view as sv

T0 = datetime(2026, 11, 14, 6, 0, tzinfo=timezone.utc)


def m(minute):
    return T0 + timedelta(minutes=minute)


def test_kvartar_med_andel_av_loggade_minuter():
    journal = [(m(i), "Tesla Model Y", i < 3, "16 A", "9 A" if i >= 3 else "16 A", "Lägre ström" if i >= 3 else None) for i in range(12)]
    rows = sv.quarters(journal, [(T0, 0.82)], [(m(i), 7.0, 0) for i in range(10)])
    assert len(rows) == 1
    r = rows[0]
    d = r["devices"]["Tesla Model Y"]
    assert (d["logged_min"], d["ok_min"], d["ordered"], d["actual"]) == (12, 3, "16 A", "9 A")
    assert d["notes"] == ["Lägre ström"] and d["deviation"] and r["deviation"]
    assert r["price"] == 0.82 and r["measured_min"] == 10
    assert r["ev_kwh"] == round(7.0 * 10 / 60, 2)


def test_flera_kvartar_i_ordning_och_ingen_avvikelse():
    journal = [(m(1), "Värmepump", True, "22.0 °C", "22.0 °C", None), (m(16), "Värmepump", True, "22.0 °C", "22.0 °C", None)]
    rows = sv.quarters(journal, [], [])
    assert [r["t"] for r in rows] == [T0.isoformat(), (T0 + timedelta(minutes=15)).isoformat()]
    assert not any(r["deviation"] for r in rows) and rows[0]["measured_min"] == 0


def test_kopplat_på_webben():
    root = os.path.join(os.path.dirname(__file__), "..")
    rd = lambda *p: open(os.path.join(root, *p), encoding="utf-8").read()
    assert '@app.get("/api/support-quarters")' in rd("webdashboard", "app.py")
    js = rd("webdashboard", "static", "app.js")
    assert 'api("api/support-quarters?back=" + jBack)' in js and "sqWire();" in js
