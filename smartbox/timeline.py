"""
timeline.py - dygnet timme för timme: vad som hände och vad som är planerat.

En rad per timme, 24 h bakåt och framåt så långt elpriserna räcker.
Leverantören (Nord Pool med flera) publicerar idag och imorgon, ibland lite längre.
Grafen tar med hela den serien. FUTURE_CAP_H är bara ett tak mot en felaktig tidsstämpel.

  BAKÅT (uppmätt, sensor_log):  elpris, solproduktion, hur stor del av timmen värmepumpens
                                kompressor gick, om spabadet värmde, hur mycket varje laddbox laddade.
  FRAMÅT (planerat):            elpris, solprognos (weather.py, samma som motorn använder),
                                värmepumpens grundläge enligt prisregeln (plan_brief.py) och
                                elbilarnas planerade laddning (ev_plan_slots).

Spabadet har ingen plan framåt (det beslutas minut för minut) - de timmarna lämnas tomma
hellre än gissade.

Laddboxarna i sensor_log heter ev_power_kw (Lite) och ev_carport_power_kw (Carport); de
kopplas till bilnamn på samma sätt som resten av gränssnittet (CHARGER_CAR). build() är ren
och testas i tests/test_timeline.py; load() läser databasen.
"""

from datetime import datetime, timedelta
import zoneinfo

SWE = zoneinfo.ZoneInfo("Europe/Stockholm")
# Idag + imorgon räcker oftast till ~36 h framåt. Taket släpper in det utan att en trasig rad ritar ett år.
FUTURE_CAP_H = 72
# Laddboxarna loggas i installationens ordning: första -> ev_power_kw, andra -> ev_carport_power_kw (main.py).
# Vilken bil som hör till vilken kolumn kommer ur installationen (load(cars=...)); utan den bara "Laddbox 1/2".
DEFAULT_CHARGER_CAR = {"ev_power_kw": "laddbox_1", "ev_carport_power_kw": "laddbox_2"}
CAR_COLORS = ["#22d3a0", "#38bdf8", "#a78bfa", "#f472b6"]


def _hour(ts):
    ts = ts.astimezone(SWE) if ts.tzinfo else ts.replace(tzinfo=SWE)
    return ts.replace(minute=0, second=0, microsecond=0)


def build(now, past, future_prices, future_solar_kw, heat_modes, ev_plan, car_ids=None, battery_plan=None,
          car_names=None, has_spa=True, has_heat=True):
    """now: tz-medveten. past: {timme: {'price','solar_kw','compressor','spa','ev': {car: kW}}}.
    future_prices/future_solar_kw: {timme: värde}. heat_modes: {timme: 'CHEAP'|'EXPENSIVE'|'COMFORT'}.
    ev_plan: {timme: {car: kWh}}. Returnerar en dict för grafen."""
    h0 = _hour(now)
    last_future = max(list(future_prices) + [h0])
    end = min(last_future, h0 + timedelta(hours=FUTURE_CAP_H))
    hours = []
    t = h0 - timedelta(hours=24)
    while t <= end:
        hours.append(t)
        t += timedelta(hours=1)

    cars = list(dict.fromkeys(list(car_ids or []) +
                              [c for v in past.values() for c in (v.get("ev") or {})] +
                              [c for v in ev_plan.values() for c in v]))
    price, solar, is_future = [], [], []
    hp, hp_text, spa, spa_text = [], [], [], []
    ev = {c: ([], []) for c in cars}
    for h in hours:
        fut = h > h0 or (h == h0 and h not in past)
        is_future.append(fut)
        p = past.get(h, {})
        if not fut:
            price.append(p.get("price"))
            solar.append(p.get("solar_kw"))
            comp = p.get("compressor")
            hp.append(comp)
            hp_text.append(f"Kompressorn gick {round(comp * 60)} min" if comp is not None else "Ingen data")
            s = p.get("spa")
            spa.append(s)
            spa_text.append((f"Värmde {round(s * 60)} min" if s and s > 0.01 else "Värmde inte") if s is not None else "Ingen data")
            for c in cars:
                kw = (p.get("ev") or {}).get(c)
                ev[c][0].append(kw if kw and kw > 0.05 else 0.0 if kw is not None else None)
                ev[c][1].append(f"Laddade {kw:.1f} kWh" if kw and kw > 0.05 else "Laddade inte")
        else:
            price.append(future_prices.get(h))
            solar.append(future_solar_kw.get(h))
            m = heat_modes.get(h)
            hp.append({"CHEAP": 1.0, "COMFORT": 0.6, "EXPENSIVE": 0.15}.get(m))
            hp_text.append({"CHEAP": "Planerat: billigt – laddar huset med värme",
                            "COMFORT": "Planerat: jämn komfort",
                            "EXPENSIVE": "Planerat: sänkt – dyr el"}.get(m, "Ingen plan"))
            spa.append(None)
            spa_text.append("Beslutas minut för minut")
            for c in cars:
                kwh = (ev_plan.get(h) or {}).get(c, 0.0)
                ev[c][0].append(kwh)
                ev[c][1].append(f"Planerat: {kwh:.1f} kWh" if kwh > 0.05 else "Ingen laddning planerad")

    # Husbatteriet: uppmätt effekt bakåt, planerad avsikt framåt (battery_plan.py). Bara om det finns.
    battery_plan = battery_plan or {}
    has_bat = any(p.get("battery_kw") is not None for p in past.values()) or bool(battery_plan)
    bat_v, bat_t = [], []
    if has_bat:
        for h, fut in zip(hours, is_future):
            if not fut:
                kw = past.get(h, {}).get("battery_kw")
                bat_v.append(None if kw is None else min(1.0, abs(kw) / 5.0))
                bat_t.append("Ingen data" if kw is None else f"Laddade {kw:.1f} kW" if kw > 0.05
                             else f"Laddade ur {-kw:.1f} kW" if kw < -0.05 else "Vilade")
            else:
                a = battery_plan.get(h)
                bat_v.append({"charge": 1.0, "discharge": 1.0, "hold": 0.3, "idle": 0.2, "auto": 0.15}.get(a))
                bat_t.append({"charge": "Planerat: laddar", "discharge": "Planerat: laddar ur", "hold": "Planerat: sparas",
                              "idle": "Planerat: vilar", "auto": "Planerat: självförbrukning"}.get(a, "Ingen plan"))
    ev_max = max([v for c in cars for v in ev[c][0] if v] + [1.0])
    names = car_names or {}
    # Bara det huset har (#136: Spabad och "Nissan" syntes i alla hus)
    lanes = ([{"key": "varmepump", "label": "Värmepump", "color": "#fb923c", "values": hp, "text": hp_text}] if has_heat else []) + \
            ([{"key": "spabad", "label": "Spabad", "color": "#a78bfa", "values": spa, "text": spa_text}] if has_spa else []) + \
        [{"key": f"ev_{c}", "label": names.get(c) or c.replace("_", " ").capitalize(), "color": CAR_COLORS[i % len(CAR_COLORS)],
          "values": [None if v is None else min(1.0, v / ev_max) for v in ev[c][0]], "text": ev[c][1]}
         for i, c in enumerate(cars)]
    if has_bat:
        lanes.append({"key": "batteri", "label": "Batteri", "color": "#0e7490", "values": bat_v, "text": bat_t})
    return {"ok": True, "now": h0.isoformat(), "hours": [h.isoformat() for h in hours],
            "future": is_future, "price": price, "solar_kw": solar, "lanes": lanes}


def load(conn, now=None, cars=None, has_spa=None, has_heat=None):
    """Läser databasen och bygger tidslinjen. cars: [(bil_id, namn, loggkolumn|None)] ur installationen;
    has_spa/has_heat: om installationen har spabad/värmepump (None = visa)."""
    charger_car = dict(DEFAULT_CHARGER_CAR)
    car_names = {}
    if cars is not None:
        charger_car = {col: cid for cid, _n, col in cars if col}
        car_names = {cid: n for cid, n, _c in cars}
    from sqlalchemy import text
    import nordpool
    import plan_brief
    now = (now or datetime.now(SWE)).astimezone(SWE)
    h0 = _hour(now)

    past = {}
    rows = conn.execute(text("""
        SELECT date_trunc('hour', timestamp AT TIME ZONE 'Europe/Stockholm') AS h,
               avg(price), avg(pv_power_w), avg(compressor_running), avg(spa_heater_running::int),
               avg(ev_power_kw), avg(ev_carport_power_kw), avg(battery_power_w)
        FROM sensor_log WHERE timestamp >= :start GROUP BY 1 ORDER BY 1"""),
        {"start": h0 - timedelta(hours=24)}).fetchall()
    f = lambda v: float(v) if v is not None else None
    for h, pr, pv, comp, spa, ev1, ev2, bat in rows:
        evs = {}
        for col, val in (("ev_power_kw", ev1), ("ev_carport_power_kw", ev2)):
            if val is not None:
                kw = float(val)
                if col in charger_car:
                    evs[charger_car[col]] = kw / 1000.0 if kw > 100 else kw    # vissa rader loggade W
        past[h.replace(tzinfo=SWE)] = {"price": f(pr), "solar_kw": f(pv) / 1000.0 if pv is not None else None,
                                       "compressor": f(comp), "spa": f(spa), "ev": evs,
                                       "battery_kw": f(bat) / 1000.0 if bat is not None else None}

    prices_q = conn.execute(text("SELECT time_start, sek_per_kwh FROM elpriser WHERE time_start >= :a AND time_start < :b "
                                 "ORDER BY time_start"), {"a": h0 - timedelta(hours=24), "b": h0 + timedelta(hours=FUTURE_CAP_H + 1)}).fetchall()
    fut_prices, by_hour = {}, {}
    for t, p in prices_q:
        if p is None:
            continue
        hh = _hour(t)
        by_hour.setdefault(hh, []).append(float(p))
    for hh, ps in by_hour.items():
        if hh >= h0:
            fut_prices[hh] = sum(ps) / len(ps)
        elif hh in past and past[hh]["price"] is None:
            past[hh]["price"] = sum(ps) / len(ps)

    fut_solar = {}
    try:
        import weather
        for k in range(0, FUTURE_CAP_H + 1):
            hh = h0 + timedelta(hours=k)
            if hh not in fut_prices:
                continue
            cloud, _, _, _ = weather.get_weather_at(hh)
            w = weather.get_hourly_solar_w(cloud, hh)
            fut_solar[hh] = round(float(w) / 1000.0, 2) if w is not None else None
    except Exception:
        pass

    heat_modes = {}
    try:
        cheap = conn.execute(text("SELECT cheap_hours_count FROM system_settings WHERE id = 1")).scalar() or 8
        mode_now = conn.execute(text("SELECT active_mode FROM sensor_log WHERE active_mode IS NOT NULL "
                                     "ORDER BY timestamp DESC LIMIT 1")).scalar()
        q_today = conn.execute(text("SELECT time_start, sek_per_kwh FROM elpriser WHERE time_start >= :a ORDER BY time_start"),
                               {"a": h0.replace(hour=0)}).fetchall()
        items = plan_brief.heat_items([(t, float(p)) for t, p in q_today if p is not None], now,
                                      nordpool.calculate_day_strategy, int(cheap), mode_now)
        for it in items:
            s, e = _hour(datetime.fromisoformat(it["start"])), datetime.fromisoformat(it["end"])
            while s < e:
                heat_modes.setdefault(s, it["mode"])
                s += timedelta(hours=1)
    except Exception:
        pass

    ev_plan = {}
    try:
        for car, t_slot, kw in conn.execute(text("SELECT car_id, t_slot, kw FROM ev_plan_slots")).fetchall():
            if kw is None:
                continue
            hh = _hour(t_slot)
            ev_plan.setdefault(hh, {})
            ev_plan[hh][str(car)] = ev_plan[hh].get(str(car), 0.0) + float(kw) / 4.0      # 15-minutersslottar
    except Exception:
        conn.rollback()

    bat_plan = {}
    try:
        counts = {}
        for t_slot, action in conn.execute(text("SELECT t_slot, action FROM battery_plan_slots WHERE t_slot >= :a"),
                                           {"a": h0}).fetchall():
            hh = _hour(t_slot)
            counts.setdefault(hh, {}).setdefault(action, 0)
            counts[hh][action] += 1
        bat_plan = {hh: max(c, key=c.get) for hh, c in counts.items()}     # timmens vanligaste avsikt
    except Exception:
        conn.rollback()

    car_ids = [c for c, _n, _col in cars] if cars is not None else list(charger_car.values())
    if cars is not None:      # bara installationens bilar i planen (gamla bil-id i ev_plan_slots döljs)
        ev_plan = {h: {c: v for c, v in d.items() if c in car_ids} for h, d in ev_plan.items()}
    return build(now, past, fut_prices, fut_solar, heat_modes, ev_plan, car_ids=car_ids,
                 battery_plan=bat_plan, car_names=car_names, has_spa=has_spa is not False, has_heat=has_heat is not False)
