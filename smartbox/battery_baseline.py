"""battery_baseline.py - vad styrningen gav utöver ett batteri i självförbrukningsläge (#398).

Besparingen jämförs annars med "ett vanligt hushåll utan styrning", och för den som har husbatteri blandas då
batteriets egen nytta ihop med EnergyWizards. Här räknas samma uppmätta kvartar en gång till med batteriet i
växelriktarens vanliga självförbrukningsläge ("auto": täck husets behov, ladda med solöverskott), med samma
simulator, gränser och verkningsgrad som planeraren (battery_plan.simulate).

Förbrukningen tas ur energibalansen: last = nät + sol - batteri (batteri + = laddar), så att den är densamma i
båda fallen. Kvartar som saknar nät-, batteri- eller prisvärde hoppas över och räknas som ofullständiga.
Idé från Darkstar (jämförelse mot "a plain self-use inverter"), egen implementation."""
from datetime import date, timedelta

from sqlalchemy import text

import battery_plan

MIN_COVERAGE = 0.8          # minst så stor del av dygnets kvartar för att dygnet ska räknas
QUARTERS_PER_DAY = 96


def compare(slots, soc0_kwh, capacity_kwh, reserve_kwh, max_kwh, charge_kw, discharge_kw, eff):
    """Faktisk kostnad mot självförbrukning för samma kvartar. slots: t, grid_kw, solar_kw, battery_kw, buy, sell."""
    actual, sim = 0.0, []
    for s in slots:
        e = s["grid_kw"] * battery_plan.DT_H
        actual += e * s["buy"] if e > 0 else e * s["sell"]
        sim.append({"t": s["t"], "load_kw": s["grid_kw"] + s["solar_kw"] - s["battery_kw"], "solar_kw": s["solar_kw"],
                    "buy": s["buy"], "sell": s["sell"]})
    selfuse, _ = battery_plan.simulate(sim, soc0_kwh, ["auto"] * len(sim), capacity_kwh, reserve_kwh, max_kwh,
                                       charge_kw, discharge_kw, eff)
    return {"actual": round(actual, 2), "selfuse": round(selfuse, 2), "saved": round(selfuse - actual, 2),
            "quarters": len(slots)}


_SQL = text("""
    SELECT date_trunc('hour', timestamp) + floor(extract(minute FROM timestamp) / 15) * interval '15 minutes' AS q,
           avg(net_power) AS net_w, avg(coalesce(pv_power_w, 0)) AS pv_w, avg(battery_power_w) AS bat_w,
           avg(price) AS price, min(battery_soc) AS soc
    FROM sensor_log
    WHERE timestamp >= :a AND timestamp < :b AND net_power IS NOT NULL AND battery_power_w IS NOT NULL AND price IS NOT NULL
    GROUP BY 1 ORDER BY 1""")


def day_slots(conn, day, tz):
    """Dygnets kvartar ur sensor_log med fulla köp-/säljpriser (moms, avgifter, tidstariff som i motorn)."""
    import nordpool
    from datetime import datetime
    a = datetime.combine(day, datetime.min.time(), tz)
    rows = conn.execute(_SQL, {"a": a, "b": a + timedelta(days=1)}).fetchall()
    slots, soc0 = [], None
    for q, net_w, pv_w, bat_w, price, soc in rows:
        if soc0 is None and soc is not None:
            soc0 = float(soc)
        spot = float(price)
        slots.append({"t": q, "grid_kw": float(net_w) / 1000.0, "solar_kw": max(0.0, float(pv_w) / 1000.0),
                      "battery_kw": float(bat_w) / 1000.0, "buy": nordpool.full_buy_cost(spot, q),
                      "sell": nordpool.full_sell_income(spot)})
    return slots, soc0


def periods(conn, cfg, today: date, tz):
    """Idag / 7 dagar / månad: {saved, actual, selfuse, days, partial}. None utan batteridata eller kapacitet."""
    cap = cfg.get("capacity_kwh")
    if not cap:
        return None
    reserve = cap * cfg.get("reserve_soc", 20.0) / 100.0
    max_kwh = cap * cfg.get("max_soc", 100.0) / 100.0
    pc = (cfg.get("max_charge_w") or cfg.get("max_power_w") or 5000.0) / 1000.0
    pd = (cfg.get("max_discharge_w") or cfg.get("max_power_w") or 5000.0) / 1000.0
    eff = cfg.get("efficiency", 0.9)
    days = {}
    first = min(today.replace(day=1), today - timedelta(days=6))
    d = first
    while d <= today:
        slots, soc0 = day_slots(conn, d, tz)
        need = QUARTERS_PER_DAY * MIN_COVERAGE if d < today else 4
        if slots and soc0 is not None and len(slots) >= need:
            r = compare(slots, cap * soc0 / 100.0, cap, reserve, max_kwh, pc, pd, eff)
            r["partial"] = len(slots) < QUARTERS_PER_DAY * 0.98 and d < today
            days[d] = r
        d += timedelta(days=1)
    if not days:
        return None

    def tot(keys):
        rs = [days[k] for k in keys if k in days]
        if not rs:
            return None
        return {"saved": round(sum(r["saved"] for r in rs), 2), "actual": round(sum(r["actual"] for r in rs), 2),
                "selfuse": round(sum(r["selfuse"] for r in rs), 2), "days": len(rs),
                "partial": any(r["partial"] for r in rs)}
    week = [today - timedelta(days=i) for i in range(7)]
    month = [k for k in days if k.month == today.month and k.year == today.year]
    return {"today": tot([today]), "week": tot(week), "month": tot(month)}
