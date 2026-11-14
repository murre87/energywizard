"""support_view.py - samlad felsökningsvy per kvart: plan/order, uppmätt och täckning (#386).

Läser bara det som redan sparas: kontrolljournalen (beställt mot uppmätt varje minut per enhet, control_journal.py),
elpriserna och de uppmätta effekterna i sensor_log. Ingen ny journal. Saknade minuter räknas aldrig som att planen
följdes: varje andel anger vad den räknas på ("följde 3 av 12 loggade min", "12 av 15 min mätta").
Ren funktion (quarters) + läsare (load) - testas i tests/test_issue_386_support_view.py."""
from collections import defaultdict
from datetime import timedelta

QUARTER_MIN = 15


def _q(ts):
    return ts.replace(minute=ts.minute - ts.minute % 15, second=0, microsecond=0)


def quarters(journal, prices, measured):
    """journal: (ts, device, ok, ordered, actual, note), ordered/actual som text. prices: (time_start, price). measured: (ts, ev_kw, battery_w).
    Returnerar en lista per kvart med data, äldst först."""
    out = defaultdict(lambda: {"devices": {}, "price": None, "ev_kwh": 0.0, "battery_kwh": 0.0, "measured_min": 0})
    for ts, dev, ok, ordered, actual, note in journal:
        d = out[_q(ts)]["devices"].setdefault(dev, {"logged": 0, "ok": 0, "ordered": None, "actual": None, "notes": []})
        d["logged"] += 1
        d["ok"] += 1 if ok else 0
        for k, v in (("ordered", ordered), ("actual", actual)):      # journalen sparar text ("9 A", "22.0 °C", "paus")
            if v not in (None, ""):
                d[k] = str(v)                                      # senaste värdet i kvarten
        if note and note not in d["notes"]:
            d["notes"].append(str(note))
    for t, p in prices:
        if _q(t) in out and p is not None:
            out[_q(t)]["price"] = float(p)
    for ts, ev_kw, bat_w in measured:
        q = out[_q(ts)]
        q["measured_min"] += 1
        q["ev_kwh"] += max(0.0, float(ev_kw or 0)) / 60.0
        q["battery_kwh"] += float(bat_w or 0) / 1000.0 / 60.0
    rows = []
    for t in sorted(out):
        q = out[t]
        devs = {}
        for dev, d in q["devices"].items():
            devs[dev] = {"logged_min": d["logged"], "ok_min": d["ok"],
                         "ordered": d["ordered"], "actual": d["actual"],
                         "notes": d["notes"][:2], "deviation": d["ok"] < d["logged"]}
        rows.append({"t": t.isoformat(), "price": q["price"], "devices": devs,
                     "measured_min": min(q["measured_min"], QUARTER_MIN), "ev_kwh": round(q["ev_kwh"], 2),
                     "battery_kwh": round(q["battery_kwh"], 2),
                     "deviation": any(v["deviation"] for v in devs.values())})
    return rows


def load(conn, back=0):
    """Ett dygns kvartar (0 = idag, 1 = igår) via en SQLAlchemy-anslutning (webben)."""
    from sqlalchemy import text
    win = ("ts >= (date_trunc('day', NOW() AT TIME ZONE 'Europe/Stockholm') - make_interval(days => :b)) AT TIME ZONE 'Europe/Stockholm' "
           "AND ts < (date_trunc('day', NOW() AT TIME ZONE 'Europe/Stockholm') - make_interval(days => :b - 1)) AT TIME ZONE 'Europe/Stockholm'")
    try:
        journal = conn.execute(text(f"SELECT ts, device, ok, ordered, actual, note FROM control_journal WHERE {win} ORDER BY ts"), {"b": int(back)}).all()
    except Exception:
        conn.rollback()
        journal = []
    if not journal:
        return []
    a, b = _q(journal[0][0]), _q(journal[-1][0]) + timedelta(minutes=QUARTER_MIN)
    prices = conn.execute(text("SELECT time_start, sek_per_kwh FROM elpriser WHERE time_start >= :a AND time_start < :b"), {"a": a, "b": b}).all()
    measured = conn.execute(text("SELECT timestamp, ev_power_kw, battery_power_w FROM sensor_log WHERE timestamp >= :a AND timestamp < :b"),
                            {"a": a, "b": b}).all()
    return quarters([tuple(r) for r in journal], [tuple(r) for r in prices], [tuple(r) for r in measured])
