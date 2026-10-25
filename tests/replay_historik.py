"""Spelar upp EnergyWizards beslutskärna (planering + prioritetshanteraren) mot HISTORISK data ur databasen, dag för dag,
och letar fel: undantag, rader som koden skriver när den sväljer ett fel, och orimliga beslut.

Kör mot en KOPIA av databasen (aldrig driftdatabasen):
    docker exec postgres-smartbox pg_dump -U postgres -d smartbox_database -t sensor_log -t elpriser -t weather_forecast ... | psql <testdb>
    TEST_DB_HOST=<värd> POSTGRES_DB=smartbox_hist python tests/replay_historik.py [--från 2026-04-01] [--till 2026-10-24] [--plan-var 2]

Per dag, i kvartssteg: det som loggades på riktigt (pris, sol, nät, temperaturer) matas in i gpm.evaluate; på kvällen
(18–06) räknas laddplanen om och två bilar laddas av det styrningen beslutar. Rapporten jämför också styrningens
pumpläge med det som loggades (ÖVERENS = hur ofta kärnan hade gjort som verkligheten)."""
import argparse
import collections
import contextlib
import io
import math
import os
import re
import sys
import traceback
import zoneinfo
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import psycopg

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "smartbox"))
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("POSTGRES_DB", "smartbox_hist")
HOST = os.environ.get("TEST_DB_HOST", "localhost")
SWE = zoneinfo.ZoneInfo("Europe/Stockholm")
UTC = zoneinfo.ZoneInfo("UTC")
NISSAN_KWH, TESLA_KWH = 40.0, 75.0
FEL_MONSTER = re.compile(r"(❌|Traceback|KRITISKT|Fel i |Fel vid)")


def num(v, default=None):
    try:
        f = float(v)
        return default if math.isnan(f) else f
    except (TypeError, ValueError):
        return default


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--från", dest="fran", default=None)
    ap.add_argument("--till", dest="till", default=None)
    ap.add_argument("--plan-var", type=int, default=2, help="räkna om laddplanen var N:e timme under natten (0 = aldrig)")
    a = ap.parse_args()

    import decisions
    import logger
    from gpm import GlobalPriorityManager

    logger.DB_HOST = HOST
    conn = psycopg.connect(f"host={HOST} user={os.environ['POSTGRES_USER']} password={os.environ['POSTGRES_PASSWORD']} dbname={os.environ['POSTGRES_DB']}")
    # Bara de kolumner som spelas upp, som flyttal: SELECT * på ~250 000 rader med numeric-kolumner tog slut på minne (OOM-dödad 2026-10-25).
    kol = ("price", "indoor_temp", "water_temp", "outdoor_temp", "brine_out_temp", "pv_power_w", "net_power", "consumed_kwh")
    sl = pd.read_sql("SELECT timestamp, active_mode, " + ", ".join(f"{k}::float8 AS {k}" for k in kol) + " FROM sensor_log ORDER BY timestamp", conn)
    pr = pd.read_sql("SELECT time_start, sek_per_kwh FROM elpriser ORDER BY time_start", conn)
    sl["timestamp"] = pd.to_datetime(sl["timestamp"], utc=True)
    pr["time_start"] = pd.to_datetime(pr["time_start"], utc=True)
    price = pr.set_index("time_start")["sek_per_kwh"].astype(float)
    price = price[~price.index.duplicated(keep="first")]
    # Kvartspris: håll värdet tills nästa (priserna kan vara timvisa).
    qidx = pd.date_range(price.index.min(), price.index.max() + timedelta(hours=1), freq="15min", tz="UTC")
    price15 = price.reindex(qidx).ffill()
    sl15 = sl.set_index("timestamp").sort_index().resample("15min").last()

    first = pd.Timestamp(a.fran, tz=SWE) if a.fran else sl15.index.min().tz_convert(SWE).normalize() + pd.Timedelta(days=1)
    last = pd.Timestamp(a.till, tz=SWE) if a.till else sl15.index.max().tz_convert(SWE).normalize() - pd.Timedelta(days=1)
    dagar = pd.date_range(first.tz_localize(None), last.tz_localize(None), freq="D")
    print(f"Spelar upp {len(dagar)} dygn ({dagar[0].date()} – {dagar[-1].date()}), {len(sl):,} loggrader, {len(price):,} priser")

    dag_ak = {"nissan": {d: {"enabled": True, "target_time": "07:00", "target_soc": 80} for d in range(7)},
              "tesla": {d: {"enabled": True, "target_time": "07:00", "target_soc": 80} for d in range(7)}}
    rapport = collections.Counter()
    fel_exempel: dict[str, list[str]] = collections.defaultdict(list)
    dagfel = collections.defaultdict(int)
    overens = collections.defaultdict(lambda: [0, 0])
    slagen = []
    motor = GlobalPriorityManager()

    def anteckna(typ, dag, text):
        rapport[typ] += 1
        dagfel[dag] += 1
        if len(fel_exempel[typ]) < 4:
            fel_exempel[typ].append(f"{dag}: {text[:260]}")

    for dag in dagar:
        dagnamn = str(dag.date())
        # Varje dygn från 18:00 lokal tid till 12:00 nästa dag (laddfönstret och dagen efter) i kvartssteg, i UTC så att dubbla/saknade timmar blir riktiga.
        start = pd.Timestamp(dag.year, dag.month, dag.day, 18, tzinfo=SWE)
        soc = {"nissan": 30.0, "tesla": 40.0}
        kwh = {"nissan": NISSAN_KWH, "tesla": TESLA_KWH}
        fas = {"nissan": 1, "tesla": 3}
        plan, senaste_plan_h = None, None
        med_data = 0
        buf = io.StringIO()
        t = start.tz_convert(UTC)
        slut = (start + pd.Timedelta(hours=18)).tz_convert(UTC)
        with contextlib.redirect_stdout(buf):
            while t < slut:
                nu = t.tz_convert(SWE).to_pydatetime()
                rad = sl15.loc[t] if t in sl15.index else None
                if rad is None or pd.isna(rad.get("price")) and pd.isna(rad.get("indoor_temp")):
                    t += pd.Timedelta(minutes=15)
                    continue
                med_data += 1
                p_nu = float(price15.get(t, num(rad.get("price"), 0.5)))
                framat = [float(price15.get(t + pd.Timedelta(minutes=15 * i), p_nu)) for i in range(96)]
                if a.plan_var and nu.minute == 0 and (nu.hour >= 18 or nu.hour < 7) and ((nu.hour - 18) % (24 if a.plan_var <= 0 else a.plan_var) == 0 or plan is None):
                    try:
                        plan = decisions.calculate_ev_charge_plan(
                            nu, dag_ak, {"nissan_soc": soc["nissan"], "tesla_soc": soc["tesla"], "nissan_plugged_in": True, "tesla_plugged_in": True, "tesla_phases": "Three phases"}, {})
                        if plan is not None and len(plan) and not plan["t_slot"].is_unique:
                            anteckna("plan-dubbletter", dagnamn, f"{nu}")
                    except Exception as e:  # noqa: BLE001
                        anteckna("plan-undantag", dagnamn, f"{nu}: {type(e).__name__}: {e}")
                        plan = None
                pv = num(rad.get("pv_power_w"), 0.0)
                net = num(rad.get("net_power"), 0.0)
                stat = {
                    "now": nu, "current_price": p_nu, "all_prices": framat, "pv_power_w": pv, "avg_net_w": net,
                    "house_consumption_w": max(0.0, net + pv), "predicted_base_load_kw": 1.0, "grid_import_w": max(0.0, net),
                    "consumed_kwh_this_hour": num(rad.get("consumed_kwh"), 1.0) or 1.0, "power_limit_kw": 11.0, "predicted_cooling_rate": 0.05,
                    "base_load_profile": {}, "peak_shaving_enabled": True, "solar_is_shaky": False,
                    "indoor_temp": num(rad.get("indoor_temp"), 21.0), "indoor_min": 19.0, "indoor_max": 22.5,
                    "water_temp": num(rad.get("water_temp"), 50.0), "water_target_normal": 50.0, "spa_temp": 38.0, "spa_normal_temp": 34.0,
                    "days_since_legionella": 1, "last_heartbeat": nu, "legionella_max_days": 7, "spa_max_temp": 40.0, "spa_low_temp": 15.0,
                    "hysteresis": 0.10, "dynamic_limit": 0.6, "max_fuse_a": 20, "house_load_a": max(0.0, (net + pv)) / 230.0 / 3,
                    "ev_actual_a": 0, "current_solar_limit_pct": 100, "current_target_limit": 100,
                    "nissan_soc": soc["nissan"], "tesla_soc": soc["tesla"], "nissan_connected": True, "tesla_connected": True,
                    "ev_min_charge_a": 6, "ev_max_charge_a": 20, "nissan_charge_completed": soc["nissan"] >= 80, "tesla_charge_completed": soc["tesla"] >= 80,
                    "nissan_phases": "SinglePhase", "tesla_phases": "ThreePhase", "ev_plan": plan, "nissan_prio": 2, "tesla_prio": 1,
                    "outdoor_temp": num(rad.get("outdoor_temp"), 5.0), "outdoor_avg_5d": num(rad.get("outdoor_temp"), 5.0),
                    "brine_out_temp": num(rad.get("brine_out_temp")),
                }
                try:
                    ak = motor.evaluate(stat)
                except Exception as e:  # noqa: BLE001
                    anteckna("evaluate-undantag", dagnamn, f"{nu}: {type(e).__name__}: {e} @ {traceback.format_exc().splitlines()[-3].strip()}")
                    t += pd.Timedelta(minutes=15)
                    continue
                for bil, nyckel, tak in (("nissan", "nissan_limit_a", 20), ("tesla", "tesla_limit_a", 16)):
                    amp = ak.get(nyckel, 0) or 0
                    if not (0 <= amp <= tak):
                        anteckna("ström-utanför-gränser", dagnamn, f"{bil} {amp} A vid {nu}")
                        amp = max(0, min(tak, amp))
                    soc[bil] = min(100.0, soc[bil] + amp * 230 * fas[bil] / 1000 * 0.25 / kwh[bil] * 100 * 0.9)
                if os.environ.get("TRACE"):
                    print(f"TRACE {nu:%m-%d %H:%M} pris {p_nu:.2f} net {net:.0f}W pv {pv:.0f}W  N {ak.get('nissan_limit_a')}A/{soc['nissan']:.0f}%  T {ak.get('tesla_limit_a')}A/{soc['tesla']:.0f}%  plan={'ja' if plan is not None and len(plan) else 'nej'}", file=sys.__stdout__)
                mode = ak.get("pump_mode") or ak.get("mode")
                logged = rad.get("active_mode")
                if isinstance(logged, str) and isinstance(mode, str):
                    o = overens[dag.strftime("%Y-%m")]
                    o[1] += 1
                    o[0] += int(mode.upper() == logged.upper())
                t += pd.Timedelta(minutes=15)
        for rad in buf.getvalue().splitlines():
            if FEL_MONSTER.search(rad):
                anteckna("sväljt-fel-i-loggen", dagnamn, rad.strip())
        slagen.append((dagnamn, soc["nissan"], soc["tesla"], med_data))
        # Målet 80 % kl 07 (golv 50 %): kontrollera vid dygnets slut (12:00 nästa dag) att bilarna nått minst golvet.
        if soc["nissan"] < 50 or soc["tesla"] < 50:
            anteckna("bil-under-golvet", dagnamn, f"Nissan {soc['nissan']:.0f} %, Tesla {soc['tesla']:.0f} %")

    print("\n=== RAPPORT ===")
    print(f"dygn uppspelade: {len(slagen)}")
    if not rapport:
        print("inga fel hittades")
    for typ, n in rapport.most_common():
        print(f"- {typ}: {n} st")
        for ex in fel_exempel[typ]:
            print(f"    {ex}")
    if overens:
        print("\nPumpläge: styrningen mot det som loggades (per månad):")
        for m in sorted(overens):
            ok, tot = overens[m]
            print(f"  {m}: {100 * ok / max(tot, 1):.0f} % överens ({tot} kvartar)")
    svar = sorted(dagfel.items(), key=lambda x: -x[1])[:5]
    if svar:
        print("\nDagar med flest anmärkningar:", ", ".join(f"{d} ({n})" for d, n in svar))
    lag = [(d, n, t, k) for d, n, t, k in slagen if n < 75 or t < 75]
    print(f"\nDygn där en bil inte nådde 75 % till middagstid: {len(lag)} av {len(slagen)} (kvartar med loggdata av 72 i fönstret 18–12)")
    for d, n, t, k in lag:
        print(f"    {d}: Nissan {n:.0f} %, Tesla {t:.0f} %, data {k}/72")
    full = [x for x in lag if x[3] >= 66]
    print(f"  varav med nästan full loggdata (≥66/72): {len(full)}")


if __name__ == "__main__":
    main()
