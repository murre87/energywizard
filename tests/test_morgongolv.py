"""Användarregel (2026-10-25): bilarna ska alltid ha minst 50 % kl 06:00 varje morgon. Annars gäller schemat."""
import zoneinfo
from datetime import datetime, timedelta

SWE = zoneinfo.ZoneInfo("Europe/Stockholm")
UTC = zoneinfo.ZoneInfo("UTC")


def _schema(tid, mal=80, aktiv=True):
    dag = {"enabled": aktiv, "target_time": tid, "target_soc": mal}
    return {"nissan": {d: dict(dag) for d in range(7)}}


def test_inget_aktivt_schema_ger_golv_kl_06(smartbox):
    import decisions
    nu = datetime(2026, 10, 26, 22, 0)
    dl, mal, kwh, _ = decisions.get_car_plan_details(nu, "nissan", _schema("07:00", aktiv=False), 30.0, 40)
    assert dl == datetime(2026, 10, 27, 6, 0) and mal == 50 and kwh > 0


def test_schemat_galler_som_vanligt_i_get_car_plan_details(smartbox):
    import decisions
    nu = datetime(2026, 10, 26, 22, 0)
    dl, mal, kwh, _ = decisions.get_car_plan_details(nu, "nissan", _schema("07:00"), 30.0, 40)
    assert dl == datetime(2026, 10, 27, 7, 0) and mal == 80 and kwh > 0


def test_golvets_delmal(smartbox):
    import decisions
    nu = datetime(2026, 10, 26, 22, 0)
    f = decisions.get_morning_floor(nu, 30.0, 40, datetime(2026, 10, 27, 7, 0))
    assert f is not None and f[0] == datetime(2026, 10, 27, 6, 0) and abs(f[1] - 0.20 * 40 * 1.12) < 1e-6
    assert decisions.get_morning_floor(nu, 60.0, 40, datetime(2026, 10, 27, 7, 0)) is None       # redan över golvet
    assert decisions.get_morning_floor(nu, 30.0, 40, datetime(2026, 10, 27, 5, 30)) is None      # schemat är redan före kl 06


def test_planen_laddar_golvet_fore_06_aven_nar_06_07_ar_billigast(smartbox, db):
    """Teslan (11 kW) kan ta hela behovet under den billiga timmen 06-07. Utan golvet väntar planen dit, och bilen är då kvar på 45 % kl 06."""
    import decisions
    from test_simulering import fyll_databas
    start = datetime(2026, 11, 10, 17, 0, tzinfo=UTC)          # 18:00 svensk tid
    with db.cursor() as cur:
        t = start
        while t < start + timedelta(hours=40):
            h = t.astimezone(SWE).hour
            cur.execute("INSERT INTO elpriser (time_start, sek_per_kwh) VALUES (%s, %s) ON CONFLICT DO NOTHING", (t, 0.05 if h == 6 else 1.0))
            t += timedelta(minutes=15)
    fyll_databas(db, start - timedelta(hours=1), 40)
    nu = start.astimezone(SWE).replace(tzinfo=None)
    dag = {"enabled": True, "target_time": "07:00", "target_soc": 50}
    schema = {"tesla": {d: dict(dag) for d in range(7)}}
    plan = decisions.calculate_ev_charge_plan(nu, schema, {"tesla_soc": 45.0, "tesla_plugged_in": True, "tesla_phases": "Three phases"}, {})
    fore_06 = plan[plan["t_slot"] < datetime(2026, 11, 11, 6, 0)]["tesla_kw"].sum() / 4.0
    behov = 0.05 * 75 * 1.12
    assert fore_06 >= behov - 0.3, f"bara {fore_06:.1f} kWh före kl 06 (behov {behov:.1f})"
