"""ha_card_feed.py - EN sensor i Home Assistant som EnergyWizards kort läser: sensor.energywizard_kort.

Korten (ha-cards/, installeras via HACS) ritar ur den här sensorns attribut, så de fungerar likadant för
HA-tillägget och Docker: inget kort behöver nå EnergyWizards egen webb eller inloggning. Samma byggare som
mobilappen och webben använder (live_flow.nodes, plan_clock.load) matar sensorn, så korten visar samma sak.

Sensorn publiceras av ha_publisher.py (MQTT med autodiscovery om en broker finns, annars HA:s REST-API).
Attributen hålls små (< 16 kB, HA:s gräns för attribut i databasen): flödet som korta poster och planen som
en rad per kvart med några tal.

Schema (v1), alla fält är valfria för korten:
  v        1
  ts       ISO-tid då sensorn byggdes
  unit     valutasymbol, t.ex. "kr"
  flow     [{k, l, i, w, on, d, r}]  nyckel, namn, ikon, watt, aktiv, detaljtext, roll (source/grid/hub/load)
  why      {nyckel: förklaring}      varför motorn gör som den gör, per enhet
  slots    [[t, pris, spot, läge, sol_w, elbil_kw, batteri_kw]]  en rad per kvart, t = epoch-sekunder,
           läge "C" billigt, "E" dyrt, "" okänt
  cars     [{id, name, soc, w, on, win}]  laddnivå %, watt, laddar nu, planerade pass [[start, slut, kW]] (epoch-sekunder)
  heat     {indoor, target, setpoint, outdoor, water, water_set, mode, floor, cheap, max, min, cop}  värmepump och varmvatten
  price    {now, spot, mode}         nuvarande pris (kr/kWh), spotpris och läge
  battery  true/false                finns husbatteri
  eco      {today, week, month} eller null (#558). Varje period:
           {buy_kwh, buy, buy_avg, sell_kwh, sell, sell_avg, net, saved, pct, bat}
           buy är köpt el inklusive avgifter, sell är såld el, saved är sparat genom
           tajmning mot ett vanligt hushåll, bat är sparat mot batteriet i
           självförbrukning (null utan jämförelse). En period utan dagar är null, inte noll.
           Ingen period för sedan start.
"""
import os
import time
from datetime import datetime

ENTITY = "sensor.energywizard_kort"
SCHEMA = 1
_SLOT_TTL_S = 300          # planen räknas om högst var femte minut, flödet varje minut
_cache = {"t": 0.0, "slots": None}
_eco_cache = {"t": 0.0, "day": None, "v": None}   # ekonomin delar intervallet: självförbrukningen simulerar dygnen

_MODE = {"CHEAP": "C", "EXPENSIVE": "E"}


def _num(v, n=3):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return round(f, n) if f == f and abs(f) != float("inf") else None


def _epoch(iso):
    try:
        return int(datetime.fromisoformat(str(iso)).timestamp())
    except (TypeError, ValueError):
        return None


def _flow(flow, pump_w=None):
    """pump_w: värmepumpens uppmätta elförbrukning (load_breakdown). live_flow ger kompressorns värmeeffekt, som för en
    värmepump är flera gånger elförbrukningen (11,5 kW värme mot 2,7 kW el vid COP 4,8), så kortet ska visa elen."""
    out = []
    for n in (flow or {}).get("nodes", []) or []:
        w = _num(n.get("w"), 0)
        if n.get("key") == "varmepump" and pump_w is not None:
            w = _num(pump_w, 0)
        out.append({"k": n.get("key"), "l": n.get("label"), "i": n.get("icon"), "w": None if w is None else int(w),
                    "on": bool(n.get("active")), "d": n.get("detail"), "r": n.get("role")})
    return out


def _slots(planclock):
    rows = []
    for s in (planclock or {}).get("slots", []) or []:
        t = _epoch(s.get("t"))
        if t is None:
            continue
        ev = s.get("ev") or {}
        ev_kw = sum(v for v in (_num(x, 2) for x in (ev.values() if isinstance(ev, dict) else [])) if v) if ev else 0
        sun = _num(s.get("sun_w"), 0)
        rows.append([t, _num(s.get("price")), _num(s.get("spot")), _MODE.get(s.get("heat"), ""),
                     None if sun is None else int(sun), round(ev_kw, 2) if ev_kw else 0, _num(s.get("bat_kw"), 2)])
    return rows


def _soc(detail):
    import re
    m = re.search(r"(\d{1,3})\s?%", str(detail or ""))
    return min(100, int(m.group(1))) if m else None


def _windows(planclock):
    """Planerade laddpass per bil som [[start, slut, kW]], sammanhängande kvartar med laddning slås ihop."""
    out = {}
    slots = (planclock or {}).get("slots", []) or []
    for s in slots:
        t = _epoch(s.get("t"))
        ev = s.get("ev") or {}
        if t is None or not isinstance(ev, dict):
            continue
        for car, kwv in ev.items():
            k = _num(kwv, 2)
            if not k or k <= 0.05:
                continue
            wins = out.setdefault(car, [])
            if wins and wins[-1][1] == t:                  # fortsätter förra passet
                wins[-1][1] = t + 900
                wins[-1][2] = max(wins[-1][2], k)
            else:
                wins.append([t, t + 900, k])
    return out


def _cars(flow, planclock):
    wins = _windows(planclock)
    cars = []
    for n in (flow or {}).get("nodes", []) or []:
        key = str(n.get("key") or "")
        if not key.startswith("ev_"):
            continue
        cid = key[3:]
        w = _num(n.get("w"), 0)
        cars.append({"id": cid, "name": n.get("label"), "soc": _soc(n.get("detail")), "w": None if w is None else int(w),
                     "on": bool(n.get("active")), "win": wins.get(cid, [])[:6]})
    return cars


def _heat(row, cfg):
    """Värmepump och varmvatten ur senaste raden i sensor_log och inställningarna (golv, tak, billig temp)."""
    if not row:
        return None
    cfg = cfg or {}
    return {"indoor": _num(row.get("indoor_temp"), 1), "target": _num(row.get("target_room_temp"), 1),
            "setpoint": _num(row.get("room_temp_setpoint"), 1), "outdoor": _num(row.get("outdoor_temp"), 1),
            "water": _num(row.get("water_temp"), 0), "water_set": _num(row.get("water_setpoint"), 0),
            "mode": _MODE.get(str(row.get("active_mode") or "").upper(), ""), "cop": _num(row.get("cop"), 1),
            "floor": _num(cfg.get("temp_expensive"), 1), "cheap": _num(cfg.get("temp_cheap"), 1),
            "max": _num(cfg.get("indoor_max"), 1), "min": _num(cfg.get("indoor_min"), 1)}


def pack_economy(money, timing, battery):
    """Idag, 7 dagar och månad till korta tal. Period utan dagar blir null, inte noll.
    bat är null när jämförelsen mot självförbrukning saknas. Sedan start följer inte med."""
    if money is None and timing is None and battery is None:
        return None

    def one(key):
        m = (money or {}).get(key) or {}
        t = (timing or {}).get(key) or {}
        b = (battery or {}).get(key) if isinstance(battery, dict) else None
        has_money = (m.get("days") or 0) > 0
        has_timing = (t.get("days") or 0) > 0
        return {
            "buy_kwh": m.get("bought_kwh") if has_money else None,
            "buy": m.get("cost") if has_money else None,
            "buy_avg": m.get("avg_paid") if has_money else None,
            "sell_kwh": m.get("sold_kwh") if has_money else None,
            "sell": m.get("income") if has_money else None,
            "sell_avg": m.get("avg_sold") if has_money else None,
            "net": m.get("net") if has_money else None,
            "saved": t.get("saved_kr") if has_timing else None,
            "pct": t.get("pct") if has_timing else None,
            "bat": None if not isinstance(b, dict) or not b.get("days") else b.get("saved"),
        }

    return {k: one(k) for k in ("today", "week", "month")}


def load_economy(conn, today, tz, battery_cfg):
    """Samma formler som Ekonomisidan och appens jämförelse mot självförbrukning.
    Anropar inte savings.all_time: sedan start hör inte till kortet."""
    import savings
    money = savings.money_periods(savings.money_rows(conn, days=40), today)
    timing = savings.summarize_periods(savings.daily_rows(conn, days=40), today)
    battery = None
    cfg = battery_cfg or {}
    if cfg.get("control") != "av" and cfg.get("capacity_kwh"):
        try:
            import battery_baseline
            from datetime import date
            battery = battery_baseline.periods(conn, cfg, date.fromisoformat(today), tz)
        except Exception:
            conn.rollback()
            battery = None
    return pack_economy(money, timing, battery)


def build(flow, planclock, now=None, unit="kr", row=None, cfg=None, pump_w=None, economy=None):
    """Sensorns (tillstånd, attribut) ur flödet och planen. Rena funktioner, testas utan databas."""
    now = now or datetime.now().astimezone()
    slots = _slots(planclock)
    cur = None
    t_now = int(now.timestamp())
    for q in slots:                         # kvarten som pågår: sista raden som börjat
        if q[0] <= t_now:
            cur = q
    price = {"now": cur[1] if cur else None, "spot": cur[2] if cur else None, "mode": cur[3] if cur else ""}
    attrs = {
        "friendly_name": "EnergyWizard kort", "icon": "mdi:flash", "v": SCHEMA, "ts": now.isoformat(timespec="seconds"),
        "unit": unit, "flow": _flow(flow, pump_w), "why": {k: str(v)[:240] for k, v in ((flow or {}).get("why") or {}).items()},
        "slots": slots, "cars": _cars(flow, planclock), "heat": _heat(row, cfg),
        "price": price, "battery": bool((planclock or {}).get("has_battery")),
        "eco": economy,
    }
    return {"E": "dyrt", "C": "billigt"}.get(price["mode"], "okänt"), attrs


def entities(engine):
    """{sensor: (tillstånd, attribut)} för ha_publisher. Hämtar flöde och plan ur databasen som appen gör."""
    import json
    from sqlalchemy import text

    import house_config
    import live_flow
    import nordpool
    import plan_clock
    with engine.connect() as c:
        row = c.execute(text("SELECT * FROM sensor_log ORDER BY timestamp DESC LIMIT 1")).mappings().first()
        if row is None:
            return {}
        row = dict(row)
        try:
            hc = house_config.load_house_config(os.environ.get("HOUSE_CONFIG_PATH", "/house_config.yaml"))
        except Exception:
            hc = {}
        try:
            items = json.loads(row.get("decision_summary") or "[]")
        except (TypeError, ValueError):
            items = []
        cars, has_spa, _heat = live_flow.house_parts(hc)
        flow = live_flow.nodes(row, items if isinstance(items, list) else [], cars=cars, has_spa=has_spa, pump_w=live_flow.latest_pump_w(c))
        if _cache["slots"] is None or time.time() - _cache["t"] > _SLOT_TTL_S:
            _cache.update(t=time.time(), slots=plan_clock.load(
                c, cars=[{"id": x.get("id"), "name": x.get("name")} for x in (hc.get("evs") or [])]))
        pc = _cache["slots"]
        eco = None
        today = None
        try:
            import local_sql
            tz = local_sql.installation_timezone()
            today = datetime.now(tz).date().isoformat()
            if _eco_cache["v"] is not None and _eco_cache["day"] == today and time.time() - _eco_cache["t"] <= _SLOT_TTL_S:
                eco = _eco_cache["v"]
            else:
                try:
                    bat_cfg = house_config.battery_settings(hc)
                except Exception:
                    bat_cfg = {}
                eco = load_economy(c, today, tz, bat_cfg)
                _eco_cache.update(t=time.time(), day=today, v=eco)
        except Exception:
            try:
                c.rollback()
            except Exception:
                pass
            eco = _eco_cache["v"] if today and _eco_cache.get("day") == today else None
    try:
        import settings
        cfg = settings.get_settings()
    except Exception:
        cfg = {}
    pump_w = None
    try:
        with engine.connect() as c2:
            pump_w = live_flow.latest_pump_w(c2)
    except Exception:
        pump_w = None
    state, attrs = build(flow, pc, unit=nordpool.cost_settings()["symbol"], row=row, cfg=cfg, pump_w=pump_w, economy=eco)
    return {ENTITY: (state, attrs)}
