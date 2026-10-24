"""Planeringen över övergången sommartid/normaltid. Då finns timmen 02–03 två gånger (oktober) eller saknas (mars);
en gång kraschade hela huvudslingan på dubbletterna (cannot reindex on an axis with duplicate labels)."""
import zoneinfo
from datetime import datetime, timedelta

import pytest

SWE = zoneinfo.ZoneInfo("Europe/Stockholm")


def _fyll(db, start_utc: datetime, hours: int, step_min: int = 15):
    rows, t = [], start_utc
    end = start_utc + timedelta(hours=hours)
    while t < end:
        rows.append((t, 0.40 + 0.10 * ((t.hour * 4 + t.minute // 15) % 7)))
        t += timedelta(minutes=step_min)
    with db.cursor() as cur:
        cur.executemany("INSERT INTO elpriser (time_start, sek_per_kwh) VALUES (%s, %s) ON CONFLICT DO NOTHING", rows)
        cur.executemany(
            "INSERT INTO weather_forecast (timestamp, temp, cloud_cover) VALUES (%s, 5, 80) ON CONFLICT DO NOTHING",
            [(start_utc + timedelta(hours=h),) for h in range(hours)],
        )


def _schema():
    dag = {"enabled": True, "target_time": "07:00", "target_soc": 80}
    return {"nissan": {d: dict(dag) for d in range(7)}, "tesla": {d: dict(dag) for d in range(7)}}


def _bilar():
    return {"nissan_soc": 20, "tesla_soc": 40, "nissan_plugged_in": True, "tesla_plugged_in": True, "tesla_phases": "Three phases"}


@pytest.mark.parametrize(
    "nu, prisstart",
    [
        # Vintertid införs natten till söndag 25 oktober 2026 (03:00 → 02:00 lokal tid).
        (datetime(2026, 10, 24, 21, 0, tzinfo=SWE), datetime(2026, 10, 24, 20, 0, tzinfo=zoneinfo.ZoneInfo("UTC"))),
        (datetime(2026, 10, 25, 0, 30, tzinfo=SWE), datetime(2026, 10, 24, 20, 0, tzinfo=zoneinfo.ZoneInfo("UTC"))),
        # Sommartid införs natten till söndag 29 mars 2026 (02:00 → 03:00): en timme saknas.
        (datetime(2026, 3, 28, 21, 0, tzinfo=SWE), datetime(2026, 3, 28, 20, 0, tzinfo=zoneinfo.ZoneInfo("UTC"))),
        # En vanlig natt, som kontroll.
        (datetime(2026, 10, 20, 21, 0, tzinfo=SWE), datetime(2026, 10, 20, 19, 0, tzinfo=zoneinfo.ZoneInfo("UTC"))),
    ],
)
def test_elbilsplan_klarar_tidsomstallning(smartbox, db, nu, prisstart):
    import decisions

    _fyll(db, prisstart, hours=40)
    plan = decisions.calculate_ev_charge_plan(nu, _schema(), _bilar(), {})
    assert plan is not None and len(plan) > 0, "planen blev tom"
    # Varje tidslucka ska finnas en gång: dubbletter ger krasch längre fram.
    assert plan["t_slot"].is_unique
    assert (plan["nissan_kw"] + plan["tesla_kw"]).sum() > 0, "ingen laddning planerades trots att bilarna behöver ladda"


def test_planen_tal_prisdubbletter_fran_databasen(smartbox, db):
    """Samma prisrad två gånger i lokal tid (det som oktoberövergången ger) får inte krascha planeringen."""
    import decisions

    _fyll(db, datetime(2026, 10, 24, 20, 0, tzinfo=zoneinfo.ZoneInfo("UTC")), hours=40)
    nu = datetime(2026, 10, 24, 21, 0, tzinfo=SWE)
    # Ska inte kasta.
    decisions.calculate_ev_charge_plan(nu, _schema(), _bilar(), {})
