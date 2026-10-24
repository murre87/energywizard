"""Dashboardens prediktor (smartdashboard/predictor.py) över tidsomställningen: samma dubbla timme som kraschade styrningen."""
import sys
import zoneinfo
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from conftest import DB_HOST
from test_dst import _fyll

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "smartdashboard"))
SWE = zoneinfo.ZoneInfo("Europe/Stockholm")
UTC = zoneinfo.ZoneInfo("UTC")


@pytest.fixture()
def predictor(smartbox, monkeypatch):
    import os

    import predictor as p

    eng = create_engine(f"postgresql+psycopg://{os.environ['POSTGRES_USER']}:{os.environ['POSTGRES_PASSWORD']}@{DB_HOST}/{os.environ['POSTGRES_DB']}")
    monkeypatch.setattr(p, "engine", eng)
    yield p
    eng.dispose()


def _frys(p, monkeypatch, nu: datetime):
    class Fryst(datetime):
        @classmethod
        def now(cls, tz=None):
            return nu if tz is None else nu.astimezone(tz)

    monkeypatch.setattr(p, "datetime", Fryst)


@pytest.mark.parametrize("nu", [datetime(2026, 10, 24, 21, 0, tzinfo=SWE), datetime(2026, 3, 28, 21, 0, tzinfo=SWE)])
def test_prognosen_klarar_tidsomstallning(predictor, db, monkeypatch, nu, capsys):
    _fyll(db, (nu - timedelta(hours=1)).astimezone(UTC).replace(minute=0), hours=60)
    _frys(predictor, monkeypatch, nu)
    ut = predictor.predict_schedule()
    assert ut, "prognosen blev tom"
    out = capsys.readouterr().out
    assert "duplicate labels" not in out and "Traceback" not in out, out[-600:]


def test_spa_planen_i_dashboarden(predictor, db, capsys):
    nu = datetime(2026, 10, 24, 21, 0, tzinfo=SWE)
    _fyll(db, (nu - timedelta(hours=1)).astimezone(UTC).replace(minute=0), hours=60)
    predictor.get_spa_schedule_plan(nu, nu + timedelta(hours=20), 34.0, 0.0, 0.02, 0.5, 0.01, 38.5, 40.0, 34.0, 5.0)
    out = capsys.readouterr().out
    assert "duplicate labels" not in out and "Traceback" not in out, out[-600:]
