"""Schedule IDs must survive discovery names longer than the old VARCHAR(20) limit."""
from contextlib import contextmanager
from datetime import time
from uuid import uuid4

import pytest

import settings


@pytest.fixture
def schedule_db(db, monkeypatch):
    schema = 'schedule_test_' + uuid4().hex
    db.execute(f'CREATE SCHEMA {schema}')
    db.execute(f'SET search_path TO {schema}')

    @contextmanager
    def get_db():
        yield db

    monkeypatch.setattr(settings, 'get_db', get_db)
    try:
        yield db
    finally:
        db.execute('SET search_path TO public')
        db.execute(f'DROP SCHEMA {schema} CASCADE')


@pytest.mark.parametrize('legacy', [False, True])
def test_ev_schedule_long_ids(schedule_db, legacy):
    db = schedule_db
    if legacy:
        # Also exercise migration of installations predating panic_mode.
        db.execute('''CREATE TABLE ev_charging_schedule (
            car_id VARCHAR(20), day_of_week INTEGER, target_time TIME,
            target_soc INTEGER DEFAULT 100, enabled BOOLEAN DEFAULT FALSE,
            PRIMARY KEY (car_id, day_of_week))''')
        db.execute("INSERT INTO ev_charging_schedule VALUES ('old_car', 0, '07:00', 80, TRUE)")

    cars = ['garage_skoda_enyaq_vehicle_one', 'garage_skoda_enyaq_vehicle_two']
    settings.get_ev_schedule(cars)
    settings.save_ev_schedule_day(cars[0], 1, '08:15', 85, True, True)
    settings.save_ev_schedule_day(cars[1], 1, '09:30', 90, True)
    settings.save_ev_schedule_db(cars[0], {
        1: dict(target_time='08:45', target_soc=95, enabled=True, panic_mode=False)})

    loaded = settings.get_ev_schedule()
    assert loaded[cars[0]][1] == dict(
        target_time='08:45', target_soc=95, enabled=True, panic_mode=False)
    assert loaded[cars[1]][1]['target_soc'] == 90
    assert loaded[cars[1]][1]['target_time'] == '09:30'
    assert db.execute('SELECT count(*) FROM ev_charging_schedule WHERE day_of_week=1').fetchone()[0] == 2
    if legacy:
        assert loaded['old_car'][0]['target_soc'] == 80


def test_ev_schedule_save_migrates_without_prior_load(schedule_db):
    """#298: auto-schema can INSERT before get_ev_schedule ever ran on this box."""
    db = schedule_db
    db.execute('''CREATE TABLE ev_charging_schedule (
        car_id VARCHAR(20), day_of_week INTEGER, target_time TIME,
        target_soc INTEGER DEFAULT 100, enabled BOOLEAN DEFAULT FALSE,
        PRIMARY KEY (car_id, day_of_week))''')
    car = 'garage_skoda_enyaq_vehicle_one'
    settings.save_ev_schedule_day(car, 2, '07:30', 80, True, False)
    row = db.execute(
        'SELECT car_id, target_soc FROM ev_charging_schedule WHERE day_of_week=2').fetchone()
    assert row == (car, 80)
    length = db.execute("""
        SELECT character_maximum_length FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name = 'ev_charging_schedule'
          AND column_name = 'car_id'""").fetchone()[0]
    assert length is None


@pytest.mark.parametrize('legacy', [False, True])
def test_climate_schedule_long_ids(schedule_db, legacy):
    db = schedule_db
    if legacy:
        db.execute('''CREATE TABLE climate_schedule (
            car_id VARCHAR(20) PRIMARY KEY, target_time TIME,
            target_temp NUMERIC, enabled BOOLEAN DEFAULT FALSE)''')
        db.execute("INSERT INTO climate_schedule VALUES ('old_car', '07:00', 21, TRUE)")

    car = 'garage_skoda_enyaq_vehicle_one'
    settings.get_climate_schedule([car])
    settings.save_climate_schedule_db(car, True, '08:15', 22)
    loaded = settings.get_climate_schedule()
    assert loaded[car] == dict(enabled=True, target_time='08:15', target_temp=22.0)
    assert db.execute('SELECT target_time FROM climate_schedule WHERE car_id=%s', (car,)).fetchone()[0] == time(8, 15)
    if legacy:
        assert loaded['old_car']['target_temp'] == 21.0
