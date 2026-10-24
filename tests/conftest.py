"""Tester för smartbox: en riktig Postgres (i GitHub som tjänst, lokalt i en behållare) och inga mockade databasanrop,
så att samma SQL som körs i drift också körs här."""
import os
import sys
from pathlib import Path

import psycopg
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "smartbox"))

os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("POSTGRES_DB", "smartbox_test")
DB_HOST = os.environ.get("TEST_DB_HOST", "localhost")

SCHEMA = """
CREATE TABLE IF NOT EXISTS elpriser (time_start TIMESTAMPTZ PRIMARY KEY, sek_per_kwh NUMERIC);
CREATE TABLE IF NOT EXISTS weather_forecast (
    timestamp TIMESTAMPTZ PRIMARY KEY, temp NUMERIC, cloud_cover NUMERIC, wind_speed NUMERIC, wind_dir NUMERIC,
    precipitation_category NUMERIC, rain_probability NUMERIC, thunder_probability NUMERIC);
"""


@pytest.fixture(scope="session")
def db():
    """Anslutning till testdatabasen; skapar den om den saknas."""
    admin = psycopg.connect(f"host={DB_HOST} user={os.environ['POSTGRES_USER']} password={os.environ['POSTGRES_PASSWORD']} dbname=postgres", autocommit=True)
    if not admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (os.environ["POSTGRES_DB"],)).fetchone():
        admin.execute(f"CREATE DATABASE {os.environ['POSTGRES_DB']}")
    admin.close()
    conn = psycopg.connect(f"host={DB_HOST} user={os.environ['POSTGRES_USER']} password={os.environ['POSTGRES_PASSWORD']} dbname={os.environ['POSTGRES_DB']}", autocommit=True)
    conn.execute(SCHEMA)
    yield conn
    conn.close()


@pytest.fixture()
def smartbox(db, monkeypatch):
    """smartbox-moduler pekade mot testdatabasen (databasvärden är konstanter i modulerna)."""
    import logger

    monkeypatch.setattr(logger, "DB_HOST", DB_HOST)
    monkeypatch.setattr(logger, "_pool", None)
    db.execute("TRUNCATE elpriser, weather_forecast")
    yield logger
    if logger._pool is not None:
        logger._pool.close()
        logger._pool = None
