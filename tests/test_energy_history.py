"""Historikvyn (smartbox/energy_history.py): periodgränser i svensk tid och sammanfattningen."""
import os
import sys
from datetime import datetime
import json
import pytest
import psycopg
from sqlalchemy import create_engine, text

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "smartbox")))

from energy_history import SWE, period_start, summarize, RANGES


def test_perioder_borjar_vid_svensk_midnatt():
    now = datetime(2026, 11, 2, 14, 30, tzinfo=SWE)
    assert period_start(now, "today") == datetime(2026, 11, 2, tzinfo=SWE)
    assert period_start(now, "7d") == datetime(2026, 10, 27, tzinfo=SWE)
    assert period_start(now, "30d") == datetime(2026, 10, 4, tzinfo=SWE)


def test_sammanfattning_sol_och_batteri():
    t = {"used_kwh": 12.0, "solar_kwh": 29.0, "bought_kwh": 2.7, "sold_kwh": 14.0, "battery_in_kwh": 5.7, "battery_out_kwh": 0.0}
    txt = summarize(t)
    assert "Solen gav 242 % av det huset använde." in txt
    assert "78 % av förbrukningen täcktes utan att köpa el." in txt
    assert "Batteriet tog in 5.7 kWh och gav tillbaka 0.0 kWh." in txt


def test_sammanfattning_utan_sol_eller_data():
    assert summarize({"used_kwh": 10.0, "solar_kwh": None, "bought_kwh": 10.0}) is None
    assert summarize(None) is None and summarize({"used_kwh": 0}) is None


def test_alla_intervall_har_hinkstorlek():
    assert set(RANGES) == {"24h", "7d", "30d", "1y"}


def test_oandliga_tal_blir_tomma():
    """#186: 'Infinity'/'NaN' i äldre loggrader gjorde att historiken inte gick att skicka som JSON (tom sida)."""
    import energy_history as eh
    assert eh._fin(float("inf")) is None and eh._fin(float("nan")) is None and eh._fin(None) is None
    assert eh._fin(1.5) == 1.5
    from decimal import Decimal
    assert eh._fin(Decimal("Infinity")) is None and eh._fin(Decimal("2.25")) == 2.25


@pytest.fixture
def history_conn(db):
    """Session-local sensor_log: never modify existing test/installation rows."""
    params = dict(db.info.get_parameters())
    params["password"] = os.environ["POSTGRES_PASSWORD"]
    engine = create_engine("postgresql+psycopg://", creator=lambda: psycopg.connect(**params))
    try:
        with engine.connect() as conn:
            conn.execute(text("""CREATE TEMP TABLE sensor_log (
                timestamp TIMESTAMPTZ, net_power NUMERIC, pv_power_w NUMERIC,
                house_consumption_w NUMERIC, battery_power_w NUMERIC, battery_soc NUMERIC)
            """))
            yield conn
    finally:
        engine.dispose()


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity"])
@pytest.mark.parametrize("rng", list(RANGES))
def test_full_history_payload_with_legacy_nonfinite_rows(history_conn, bad, rng):
    import energy_history as eh

    now = datetime(2026, 11, 12, 10, 3, tzinfo=SWE)
    history_conn.execute(text("""INSERT INTO sensor_log VALUES
        ('2026-11-12 10:00:00+01',1000,500,NULL,-200,42),
        ('2026-11-12 10:01:00+01',1000,500,NULL,-200,43),
        ('2026-11-12 10:02:00+01',CAST(:bad AS NUMERIC),CAST(:bad AS NUMERIC),
         CAST(:bad AS NUMERIC),CAST(:bad AS NUMERIC),CAST(:bad AS NUMERIC))"""), {"bad": bad})
    payload = eh.history_payload(history_conn, rng, now)
    json.dumps(payload, allow_nan=False)  # Same strict finite-value requirement as the API response.
    assert payload["ok"] is True
    assert payload["series"]["grid_kw"] and set(payload["series"]["grid_kw"]) == {1.0}
    assert set(payload["series"]["house_kw"]) == {1.7}
    for totals in payload["totals"].values():
        assert totals["used_kwh"] > 0
    assert all(v is None for k, v in payload["latest"].items() if k != "ts")


def test_history_without_rows_is_valid_json(history_conn):
    import energy_history as eh

    payload = eh.history_payload(history_conn)
    json.dumps(payload, allow_nan=False)
    assert all(v is None for v in payload["totals"].values())
    assert payload["series"]["t"] == [] and payload["latest"] is None
