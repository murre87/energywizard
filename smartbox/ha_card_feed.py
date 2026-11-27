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
  bath     null, eller (#558): {water, water_set, spa, spa_set, in_bath, next, until, heat}
           water/spa är grader. next och until är ISO-tider (nästa badtid, eller badtidens slut).
           heat är "now" under badtid, "before" när uppvärmning planeras inom 36 timmar,
           "later" när badtiden ligger längre bort, och null utan badtider. Ingen tid gissas.
"""
import os
import time
from datetime import datetime, timedelta

ENTITY = "sensor.energywizard_kort"
SCHEMA = 1
_SLOT_TTL_S = 300          # planen räknas om högst var femte minut, flödet varje minut
_cache = {"t": 0.0, "slots": None}

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


def bath_view(now, row, windows, mode="bath", spa_set=None, ahead_h=36):
    """Varmvatten, spabadets temperatur och nästa badtid till kortet.

    Saknas både temperatur och badtid blir det None, inte nollor. Uppvärmningens starttimme
    räknas inte här: inom 36 timmar planerar motorn den, längre bort gör den det inte än.
    """
    import spa_bath
    row = row or {}
    water = _num(row.get("water_temp"), 0)
    water_set = _num(row.get("water_setpoint"), 0) if water is not None else None
    spa = _num(row.get("spa_temp"), 1)
    target = _num(spa_set, 1) if spa is not None else None
    try:
        in_bath, nxt, end = spa_bath.status(now, windows, "nobath" if mode == "nobath" else "bath")
    except Exception:
        in_bath, nxt, end = False, None, None
    if water is None and spa is None and not in_bath and nxt is None and end is None:
        return None

    def iso(dt):
        return None if dt is None else dt.isoformat(timespec="minutes")

    if in_bath:
        heat = "now"
    elif nxt is not None and nxt - now <= timedelta(hours=ahead_h):
        heat = "before"
    elif nxt is not None:
        heat = "later"
    else:
        heat = None
    return {"water": water, "water_set": water_set, "spa": spa, "spa_set": target,
            "in_bath": bool(in_bath), "next": None if in_bath else iso(nxt),
            "until": iso(end) if in_bath else None, "heat": heat}


def build(flow, planclock, now=None, unit="kr", row=None, cfg=None, pump_w=None, bath=None):
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
        "bath": bath,
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
    bath = None
    try:
        import ew_settings
        import local_sql
        import spa_bath
        now_b = datetime.now(local_sql.installation_timezone())
        mode = ew_settings.get("spa_bath_mode") or "bath"
        spa_set = (cfg or {}).get("spa_normal_temp")
        bath = bath_view(now_b, row, ew_settings.get("spa_bath_windows"), mode, spa_set, spa_bath.PLAN_AHEAD_H)
    except Exception:
        bath = None
    state, attrs = build(flow, pc, unit=nordpool.cost_settings()["symbol"], row=row, cfg=cfg, pump_w=pump_w, bath=bath)
    return {ENTITY: (state, attrs)}
