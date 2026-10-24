"""Simulerade dygn genom beslutskärnan (planering + prioritetshanteraren) i femminutersteg, med riktig databas.

Det som ska gå igenom utan fel: en vanlig natt, natten då klockan går tillbaka (oktober: timmen 02–03 finns två gånger)
och natten då den går fram (mars: timmen saknas). Bilarna laddas av det styrningen faktiskt beslutar, och ska vara
laddade till morgonens mål."""
import math
import zoneinfo
from datetime import datetime, timedelta

import pytest

SWE = zoneinfo.ZoneInfo("Europe/Stockholm")
UTC = zoneinfo.ZoneInfo("UTC")
NISSAN_KWH, TESLA_KWH = 40.0, 75.0


def pris(t_utc: datetime) -> float:
    """Ett vanligt dygn: billigt på natten, dyrt på morgon och kväll."""
    h = t_utc.astimezone(SWE).hour
    bas = {range(0, 6): 0.15, range(6, 9): 0.95, range(9, 16): 0.55, range(16, 21): 1.10, range(21, 24): 0.45}
    return next(v for r, v in bas.items() if h in r) + 0.02 * ((t_utc.minute // 15) % 3)


def sol_w(t_utc: datetime) -> float:
    h = t_utc.astimezone(SWE).hour + t_utc.minute / 60
    return max(0.0, 2500 * math.sin((h - 8) / 8 * math.pi)) if 8 <= h <= 16 else 0.0


def fyll_databas(db, start_utc: datetime, timmar: int):
    rader = []
    t = start_utc
    while t < start_utc + timedelta(hours=timmar):
        rader.append((t, pris(t)))
        t += timedelta(minutes=15)
    with db.cursor() as cur:
        cur.executemany("INSERT INTO elpriser (time_start, sek_per_kwh) VALUES (%s, %s) ON CONFLICT DO NOTHING", rader)
        cur.executemany(
            "INSERT INTO weather_forecast (timestamp, temp, cloud_cover) VALUES (%s, 5, 70) ON CONFLICT DO NOTHING",
            [(start_utc + timedelta(hours=h),) for h in range(timmar)],
        )


SCENARION = [
    pytest.param(datetime(2026, 10, 20, 19, 0, tzinfo=UTC), id="vanlig-natt"),
    pytest.param(datetime(2026, 10, 24, 19, 0, tzinfo=UTC), id="oktober-normaltid"),
    pytest.param(datetime(2026, 3, 28, 19, 0, tzinfo=UTC), id="mars-sommartid"),
]


@pytest.mark.parametrize("start", SCENARION)
def test_natten_igenom(smartbox, db, start, capsys):
    import decisions
    from gpm import GlobalPriorityManager

    fyll_databas(db, start - timedelta(hours=3), 48)
    motor = GlobalPriorityManager()
    dag = {"enabled": True, "target_time": "07:00", "target_soc": 80}
    schema = {"nissan": {d: dict(dag) for d in range(7)}, "tesla": {d: dict(dag) for d in range(7)}}
    soc = {"nissan": 20.0, "tesla": 40.0}
    kwh = {"nissan": NISSAN_KWH, "tesla": TESLA_KWH}
    fas = {"nissan": 1, "tesla": 3}
    plan = None
    morgon_utc = None
    slut = start + timedelta(hours=16)
    t = start
    while t < slut:
        nu = t.astimezone(SWE)
        if nu.hour == 7 and nu.minute == 0 and morgon_utc is None:
            morgon_utc = t
        if plan is None or nu.minute % 15 == 0:
            plan = decisions.calculate_ev_charge_plan(
                nu, schema, {"nissan_soc": soc["nissan"], "tesla_soc": soc["tesla"], "nissan_plugged_in": True, "tesla_plugged_in": True, "tesla_phases": "Three phases"}, {}
            )
            assert plan is not None and (len(plan) == 0 or plan["t_slot"].is_unique), f"planen blev trasig {nu}"
        framat = [pris(t + timedelta(minutes=15 * i)) for i in range(96)]
        stat = {
            "now": nu, "current_price": pris(t), "all_prices": framat, "pv_power_w": sol_w(t), "avg_net_w": 400.0 - sol_w(t),
            "house_consumption_w": 900.0, "predicted_base_load_kw": 1.0, "grid_import_w": max(0.0, 900.0 - sol_w(t)),
            "consumed_kwh_this_hour": 1.0, "power_limit_kw": 11.0, "predicted_cooling_rate": 0.05, "base_load_profile": {},
            "peak_shaving_enabled": True, "solar_is_shaky": False, "indoor_temp": 21.0, "indoor_min": 19.0, "indoor_max": 22.5,
            "water_temp": 50.0, "water_target_normal": 50.0, "spa_temp": 38.0, "spa_normal_temp": 34.0, "days_since_legionella": 1,
            "last_heartbeat": nu, "legionella_max_days": 7, "spa_max_temp": 40.0, "spa_low_temp": 15.0,
            "hysteresis": 0.10, "dynamic_limit": 0.6, "max_fuse_a": 20, "house_load_a": 3.0, "ev_actual_a": 0,
            "current_solar_limit_pct": 100, "current_target_limit": 100,
            "nissan_soc": soc["nissan"], "tesla_soc": soc["tesla"], "nissan_connected": True, "tesla_connected": True,
            "ev_min_charge_a": 6, "ev_max_charge_a": 20, "nissan_charge_completed": soc["nissan"] >= 80, "tesla_charge_completed": soc["tesla"] >= 80,
            "nissan_phases": "SinglePhase", "tesla_phases": "ThreePhase", "ev_plan": plan, "nissan_prio": 2, "tesla_prio": 1,
            "outdoor_temp": 5.0, "outdoor_avg_5d": 5.0,
        }
        ak = motor.evaluate(stat)
        for bil, nyckel, tak in (("nissan", "nissan_limit_a", 20), ("tesla", "tesla_limit_a", 16)):
            a = ak.get(nyckel, 0) or 0
            assert 0 <= a <= tak, f"{bil} fick {a} A vid {nu}"
            # Laddningen följer det styrningen beslutar (230 V, antal faser), fem minuter i taget.
            soc[bil] = min(100.0, soc[bil] + a * 230 * fas[bil] / 1000 * (5 / 60) / kwh[bil] * 100 * 0.9)
        t += timedelta(minutes=5)

    ut = capsys.readouterr().out
    for fel in ("KRITISKT FEL", "Fel i check_spa_schedule_plan", "Traceback"):
        assert fel not in ut, f"'{fel}' i loggen:\n{ut[-800:]}"
    # Bilarna ska vara laddade till morgonens mål (80 % kl 07; golvet är 50 %).
    assert soc["nissan"] >= 75, f"Nissan nådde bara {soc['nissan']:.0f} % till morgonen"
    assert soc["tesla"] >= 75, f"Tesla nådde bara {soc['tesla']:.0f} % till morgonen"
