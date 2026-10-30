"""ha_publisher.py – Publicerar härledda smartbox-värden (elpriser, effektfördelning, COP, besparing, solprognos)
som sensorer i Home Assistant, för dashboard-flikarna "Översikt" och "Analys".

Körs i en egen bakgrundstråd (start() anropas en gång från main.py) och läser bara från databasen, så den
kan aldrig påverka styrningen. Sensorerna skapas via HA:s REST-API (icke-persistenta, uppdateras varje minut).
"""
import threading
import time
import zoneinfo
from datetime import datetime

from sqlalchemy import text

import homeassistant
import pump_runtime
from database_engine import engine

SWE = zoneinfo.ZoneInfo("Europe/Stockholm")
INTERVAL_S = 60

_TODAY = "(date_trunc('day', now() AT TIME ZONE 'Europe/Stockholm') AT TIME ZONE 'Europe/Stockholm')"


def _num(v, n=2):
    return round(float(v), n) if v is not None else None


def _day_prices(conn, offset_days):
    """Kvartspriser (kr/kWh) för idag (0) eller imorgon (1) som [[epoch_ms, pris], ...]."""
    rows = conn.execute(text(
        f"SELECT extract(epoch FROM time_start) * 1000, sek_per_kwh FROM elpriser "
        f"WHERE time_start >= {_TODAY} + interval '{offset_days} day' "
        f"AND time_start < {_TODAY} + interval '{offset_days + 1} day' ORDER BY time_start")).fetchall()
    return [[int(r[0]), round(float(r[1]), 4)] for r in rows if r[1] is not None]


def _cheapest_dearest(prices):
    """Billigaste och dyraste hela timme (lokal tid) av en dags kvartspriser."""
    by_hour = {}
    for ts_ms, p in prices:
        h = datetime.fromtimestamp(ts_ms / 1000, SWE).hour
        by_hour.setdefault(h, []).append(p)
    if not by_hour:
        return None, None, None
    avg = {h: sum(v) / len(v) for h, v in by_hour.items()}
    lo = min(avg, key=avg.get)
    hi = max(avg, key=avg.get)
    return (lo, avg[lo]), (hi, avg[hi]), sum(avg.values()) / len(avg)


def _collect():
    ent = {"sensor.smartbox_puls": (datetime.now(SWE).isoformat(timespec="seconds"),
                                    {"friendly_name": "Smartbox Puls", "device_class": "timestamp", "icon": "mdi:heart-pulse"})}
    with engine.connect() as c:
        today = _day_prices(c, 0)
        tomorrow = _day_prices(c, 1)
        now_ms = time.time() * 1000
        cur = next((p for ts, p in reversed(today) if ts <= now_ms), None)
        cheap, dear, day_avg = _cheapest_dearest(today)
        attrs = {"friendly_name": "Smartbox Prisprognos", "unit_of_measurement": "kr/kWh", "icon": "mdi:chart-bar",
                 "idag": today, "imorgon": tomorrow,
                 "billigaste_timme": cheap[0] if cheap else None, "billigaste_pris": _num(cheap[1], 3) if cheap else None,
                 "dyraste_timme": dear[0] if dear else None, "dyraste_pris": _num(dear[1], 3) if dear else None,
                 "snitt_idag": _num(day_avg, 3)}
        ent["sensor.smartbox_prisprognos"] = (_num(cur, 3), attrs)

        lb = c.execute(text("SELECT total_w, ev_w, pump_w, spa_w, unexplained_w FROM load_breakdown "
                            "WHERE timestamp > now() - interval '5 minutes' ORDER BY timestamp DESC LIMIT 1")).fetchone()
        if lb:
            names = [("total", "Totalt", "mdi:flash"), ("elbil", "Elbil", "mdi:car-electric"),
                     ("varmepump", "Värmepump", "mdi:heat-pump"), ("spa", "Spabad", "mdi:hot-tub"),
                     ("ovrigt", "Övrigt", "mdi:home-lightning-bolt")]
            for (key, label, icon), val in zip(names, lb):
                ent[f"sensor.smartbox_effekt_{key}"] = (_num(max(float(val or 0), 0.0), 0),
                    {"friendly_name": f"Smartbox Effekt {label}", "unit_of_measurement": "W", "device_class": "power", "icon": icon})

        car = c.execute(text("SELECT mode FROM overrides WHERE device = 'ev_charging_car'")).fetchone()
        if car:
            ent["sensor.smartbox_elbil_laddar"] = (car[0], {"friendly_name": "Smartbox Elbil som laddar", "icon": "mdi:car-electric"})

        ph = c.execute(text("SELECT shelly_l1_a, shelly_l2_a, shelly_l3_a FROM sensor_log "
                            "WHERE timestamp > now() - interval '5 minutes' AND shelly_l1_a IS NOT NULL ORDER BY timestamp DESC LIMIT 1")).fetchone()
        if ph:
            for i, a in enumerate(ph, start=1):
                ent[f"sensor.smartbox_fas_l{i}"] = (_num(a, 1), {"friendly_name": f"Smartbox Fasström L{i} (nät)", "unit_of_measurement": "A", "device_class": "current", "icon": "mdi:current-ac"})

        r = c.execute(text(
            "SELECT avg(cop) FILTER (WHERE cop > 0), avg(compressor_running) * 100 FROM sensor_log "
            "WHERE timestamp > now() - interval '24 hours'")).fetchone()
        if r:
            ent["sensor.smartbox_cop_24h"] = (_num(r[0], 2), {"friendly_name": "Smartbox COP (24 h)", "icon": "mdi:heat-pump"})
            ent["sensor.smartbox_kompressor_andel"] = (_num(r[1], 0), {"friendly_name": "Smartbox Kompressor gick (24 h)", "unit_of_measurement": "%", "icon": "mdi:fan"})

        sf = c.execute(text("SELECT solar_forecast_w FROM sensor_log WHERE solar_forecast_w IS NOT NULL "
                            "ORDER BY timestamp DESC LIMIT 1")).fetchone()
        if sf:
            ent["sensor.smartbox_solprognos"] = (_num(sf[0], 0), {"friendly_name": "Smartbox Solprognos", "unit_of_measurement": "W", "device_class": "power", "icon": "mdi:weather-sunny"})

        # Idag: köpt el från nätet, effektviktat snittpris och vad tajmningen sparat mot dygnssnittet.
        # (Bygger på nätimporten net_power > 0 – avg_w_tot är pumpens SCHABLON och ingen mätning av husets last.)
        e = c.execute(text(
            f"SELECT sum(net_power) / 60000.0, sum(net_power * price) / nullif(sum(net_power), 0) FROM sensor_log "
            f"WHERE timestamp >= {_TODAY} AND net_power > 0 AND price IS NOT NULL")).fetchone()
        if e and e[0] is not None and day_avg is not None and e[1] is not None:
            kwh, wprice = float(e[0]), float(e[1])
            ent["sensor.smartbox_forbrukning_idag"] = (_num(kwh, 1), {"friendly_name": "Smartbox Köpt el idag", "unit_of_measurement": "kWh", "device_class": "energy", "icon": "mdi:counter"})
            ent["sensor.smartbox_snittpris_idag"] = (_num(wprice, 3), {"friendly_name": "Smartbox Snittpris idag (viktat)", "unit_of_measurement": "kr/kWh", "icon": "mdi:cash", "dygnssnitt": _num(day_avg, 3)})
            ent["sensor.smartbox_besparing_idag"] = (_num((day_avg - wprice) * kwh, 2), {"friendly_name": "Smartbox Besparing idag", "unit_of_measurement": "kr", "icon": "mdi:piggy-bank"})
    # Värmepumpens drifttid: dagens värde sparas permanent, och månads-/årssiffror publiceras till HA.
    try:
        pump_runtime.upsert_today(engine)
        with engine.connect() as c:
            months = pump_runtime.periods(c, "month")
            years = pump_runtime.periods(c, "year")
            tot = pump_runtime.totals(c)
        if months:
            cur = months[-1]
            to_ms = lambda d: int(datetime(d.year, d.month, d.day, 12, tzinfo=SWE).timestamp() * 1000)
            ent["sensor.smartbox_drifttid"] = (cur[1], {
                "friendly_name": "Smartbox Värmepump drifttid (denna månad)", "unit_of_measurement": "h", "icon": "mdi:timer-outline",
                "manad": cur[0].strftime("%Y-%m"), "tillsats1_manad": cur[2], "tillsats2_manad": cur[3], "varmvatten_manad": cur[4],
                "manader": [[to_ms(m[0]), m[1], m[2], m[3], m[4]] for m in months[-24:]],
                "ar": [{"ar": y[0].year, "kompressor": y[1], "tillsats1": y[2], "tillsats2": y[3], "varmvatten": y[4], "dagar": y[5]} for y in years],
                "rakneverk_kompressor": tot[0] if tot else None, "rakneverk_tillsats1": tot[1] if tot else None,
                "rakneverk_tillsats2": tot[2] if tot else None, "rakneverk_varmvatten": tot[3] if tot else None})
    except Exception as e:
        print(f"⚠️ pump_runtime: {e}")
    # Gratis tack vare solen (tung fråga ~2,5 s -> beräknas högst var 30:e minut och återanvänds däremellan).
    try:
        if time.time() - _solar_cache["t"] > 1800 or _solar_cache["val"] is None:
            with engine.connect() as c:
                _solar_cache["val"] = pump_runtime.solar_free(c)
            _solar_cache["t"] = time.time()
        sf_ = _solar_cache["val"]
        if sf_ and sf_["manader"]:
            cur = sf_["manader"][-1]
            to_ms = lambda d: int(datetime(d.year, d.month, d.day, 12, tzinfo=SWE).timestamp() * 1000)
            yr = [m for m in sf_["manader"] if m["manad"].year == cur["manad"].year]
            ent["sensor.smartbox_solgratis"] = (cur["komp_gratis_h"], {
                "friendly_name": "Smartbox Kompressor på solel (denna månad)", "unit_of_measurement": "h", "icon": "mdi:solar-power-variant",
                "hus_utan_natimport_manad_h": cur["hus_h"], "andel_manad_pct": cur["pct_gratis"],
                "ar_komp_gratis_h": round(sum(m["komp_gratis_h"] for m in yr), 1), "ar_komp_h": sum(m["komp_h"] for m in yr),
                "ar_hus_utan_natimport_h": sum(m["hus_h"] for m in yr),
                "manad_sol_kwh": cur["komp_sol_kwh"], "manad_kwh": cur["komp_kwh"], "manad_sparat_kr": cur["sparat_kr"],
                "ar_sol_kwh": sum(m["komp_sol_kwh"] for m in yr), "ar_kwh": sum(m["komp_kwh"] for m in yr), "ar_sparat_kr": sum(m["sparat_kr"] for m in yr),
                "manader": [[to_ms(m["manad"]), m["hus_h"], m["komp_gratis_h"], m["komp_h"], m["pct_gratis"], m["komp_sol_kwh"], m["komp_kwh"], m["sparat_kr"]] for m in sf_["manader"][-24:]],
                "per_timme": [[t["timme"], t["hus_h"], t["komp_gratis_h"], t["komp_h"]] for t in sf_["timmar"]]})
    except Exception as e:
        print(f"⚠️ solgratis: {e}")
    # Elbil: solel i laddningen (delar cache-intervallet med solgratis; egen tung fråga ~2 s).
    try:
        if _solar_cache.get("ev") is None or time.time() - _solar_cache.get("ev_t", 0) > 1800:
            with engine.connect() as c:
                _solar_cache["ev"] = pump_runtime.ev_solar(c)
            _solar_cache["ev_t"] = time.time()
        evm = _solar_cache["ev"]
        if evm:
            cur = evm[-1]
            yr = [m for m in evm if m["manad"].year == cur["manad"].year]
            to_ms = lambda d: int(datetime(d.year, d.month, d.day, 12, tzinfo=SWE).timestamp() * 1000)
            sm = lambda k, rows: sum(m[k] for m in rows)
            ent["sensor.smartbox_elbil_solel"] = (cur["lite_sol_kwh"] + cur["carport_sol_kwh"], {
                "friendly_name": "Smartbox Elbil solel (denna månad)", "unit_of_measurement": "kWh", "icon": "mdi:car-electric",
                "manad_kwh": cur["lite_kwh"] + cur["carport_kwh"], "manad_sparat_kr": cur["lite_kr"] + cur["carport_kr"],
                "nissan_manad_sol_kwh": cur["lite_sol_kwh"], "nissan_manad_kwh": cur["lite_kwh"],
                "tesla_manad_sol_kwh": cur["carport_sol_kwh"], "tesla_manad_kwh": cur["carport_kwh"],
                "ar_kwh": sm("lite_kwh", yr) + sm("carport_kwh", yr), "ar_sol_kwh": sm("lite_sol_kwh", yr) + sm("carport_sol_kwh", yr),
                "ar_sparat_kr": sm("lite_kr", yr) + sm("carport_kr", yr),
                "nissan_ar_sol_kwh": sm("lite_sol_kwh", yr), "nissan_ar_kwh": sm("lite_kwh", yr),
                "tesla_ar_sol_kwh": sm("carport_sol_kwh", yr), "tesla_ar_kwh": sm("carport_kwh", yr),
                "manader": [[to_ms(m["manad"]), m["lite_sol_kwh"], m["carport_sol_kwh"], m["lite_kwh"], m["carport_kwh"]] for m in evm[-24:]]})
    except Exception as e:
        print(f"⚠️ elbil_solel: {e}")
    return ent


def _loop():
    try:
        pump_runtime.ensure_and_backfill(engine)
    except Exception as e:
        print(f"⚠️ pump_runtime backfill: {e}")
    while True:
        try:
            homeassistant.publish_states(_collect())
        except Exception as e:  # ska aldrig påverka något annat
            print(f"⚠️ ha_publisher: {e}")
        time.sleep(INTERVAL_S)


_solar_cache = {"t": 0.0, "val": None}
_started = False


def start():
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop, name="ha_publisher", daemon=True).start()
    print("📡 ha_publisher startad (publicerar priser, effektfördelning, COP och besparing till HA)")
