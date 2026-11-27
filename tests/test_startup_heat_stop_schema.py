"""Regressions for #449/#464: nullable pump values and fresh-install readers."""
import ast
import os
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

pytestmark = pytest.mark.no_planner_input_guard      # testar att planeringen tål minimal och konstig indata, inte kontraktet
from sqlalchemy import create_engine

import gpm
import ha_publisher
import logger
import nordpool
import settings
import weather


@pytest.mark.parametrize('average', [None, 0, 10, 14, 16, 17, 20])
def test_explicit_null_heat_stop_matches_absent_register(average, db):
    state = dict(now=datetime(2026, 11, 16, 12), car_ids=[], outdoor_avg_5d=average,
                 indoor_temp=21, has_spa=False, has_heat_pump=False)
    missing = gpm.GlobalPriorityManager().evaluate(state)
    explicit = gpm.GlobalPriorityManager().evaluate({**state, 'heat_stop_outdoor': None})
    assert explicit == missing


def test_unknown_outdoor_average_uses_existing_missing_value_default(db):
    state = dict(now=datetime(2026, 11, 16, 12), car_ids=[], heat_stop_outdoor=None)
    assert gpm.GlobalPriorityManager().evaluate({**state, 'outdoor_avg_5d': None}) == \
        gpm.GlobalPriorityManager().evaluate(state)


@pytest.fixture
def fresh_schema(db, monkeypatch):
    schema = 'startup_' + uuid4().hex
    db.execute(f'CREATE SCHEMA {schema}')
    db.execute(f'SET search_path TO {schema}')

    @contextmanager
    def connection():
        yield db

    for module in (logger, nordpool, settings, weather):
        monkeypatch.setattr(module, 'get_db', connection)
    engine = create_engine('postgresql+psycopg://', creator=lambda: psycopg.connect(
        db.info.dsn, password=os.environ['POSTGRES_PASSWORD'], options=f'-c search_path={schema}'))
    monkeypatch.setattr(ha_publisher, 'engine', engine)
    try:
        yield db
    finally:
        engine.dispose()
        db.execute('SET search_path TO public')
        db.execute(f'DROP SCHEMA {schema} CASCADE')


def startup():
    # Execute the actual initializer block, without importing the live main loop.
    tree = ast.parse((Path(__file__).resolve().parents[1]/'smartbox/main.py').read_text(encoding='utf-8'))
    start = next(i for i, node in enumerate(tree.body) if isinstance(node, ast.Expr)
                 and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Attribute)
                 and ast.unparse(node.value.func) == 'logger.init_log_db')
    nodes = []
    for node in tree.body[start:]:
        if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
            break
        nodes.append(node)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'startup_initializers', 'exec'),
         dict(logger=logger, nordpool=nordpool, settings=settings, weather=weather))


def test_startup_creates_empty_tables_before_any_successful_cycle(fresh_schema):
    db = fresh_schema
    assert db.execute("SELECT to_regclass('load_breakdown'), to_regclass('elpriser')").fetchone() == (None, None)
    startup()
    assert db.execute('SELECT count(*) FROM load_breakdown').fetchone() == (0,)
    assert db.execute('SELECT count(*) FROM elpriser').fetchone() == (0,)
    entities = ha_publisher._collect()  # Real publisher SQL, no HA/MQTT writes or provider fetches.
    assert 'sensor.smartbox_puls' in entities
    assert entities['sensor.smartbox_prisprognos'][1]['idag'] == []
    assert 'sensor.smartbox_effekt_total' not in entities  # No fabricated zero measurements.


def test_upgrade_preserves_load_history_and_migrates_extra_column(fresh_schema):
    db = fresh_schema
    db.execute('CREATE TABLE load_breakdown (id BIGSERIAL PRIMARY KEY, timestamp TIMESTAMPTZ DEFAULT now(), '
               'total_w REAL, ev_w REAL, pump_w REAL, spa_w REAL, unexplained_w REAL)')
    db.execute('INSERT INTO load_breakdown(total_w) VALUES (1234)')
    logger.init_load_breakdown_db()
    logger.init_load_breakdown_db()
    assert db.execute('SELECT total_w, extra_w FROM load_breakdown').fetchall() == [(1234, None)]
    assert logger.log_load_breakdown(2000, 500, 700, 300, 500, extra={'lamp': 20})
    assert db.execute('SELECT total_w, extra_w FROM load_breakdown ORDER BY id DESC LIMIT 1').fetchone() == \
        (2000, '{"lamp": 20}')
