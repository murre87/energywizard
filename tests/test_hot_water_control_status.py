"""Fresh owner-only control status; read-only API and sanitized real SQL path."""
from contextlib import contextmanager
import json
import os
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import psycopg
import pytest
from sqlalchemy import create_engine

import hot_water_status as status
from test_hot_water_owner_status import web, NOW
from test_hot_water_runtime import house


def report(**changes):
    return {**{'schema': 1, 'state': 'active', 'reported_at': NOW,
               'start': NOW-10, 'end': NOW+600, 'deadline': NOW+900}, **changes}


@pytest.mark.parametrize('changes', [{'reported_at': NOW-91}, {'reported_at': NOW+1},
    {'reported_at': True}, {'state': '<script>'}, {'schema': True}, {'end': NOW-11},
    {'start': float('nan')}])
def test_stale_malformed_or_future_reports_are_unknown(changes):
    assert status.decode(json.dumps(report(**changes)), NOW) == {'state': 'unknown', 'fresh': False}


def test_decoder_excludes_private_fields():
    decoded = status.decode(json.dumps(report(endpoint='private', reason='secret', token='abc')), NOW)
    assert decoded['fresh'] and decoded['state'] == 'active'
    assert not {'endpoint', 'reason', 'token'} & decoded.keys()


def test_status_worker_never_blocks_engine_and_keeps_only_latest_waiting_report():
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    received = []
    def slow(report):
        received.append(report)
        if len(received) == 1:
            entered.set()
            release.wait(3)
        else:
            finished.set()
    publisher = status.Publisher(writer=slow)
    assert publisher.thread is None
    runtime = SimpleNamespace(report={'state': 'guard_blocked', 'reason': 'private'}, controller=None)
    assert publisher.submit(runtime, NOW)
    assert entered.wait(2)
    try:
        assert publisher.submit(runtime, NOW+1)
        assert publisher.submit(runtime, NOW+2)
        assert publisher.queue.qsize() == 1
    finally:
        release.set()
    assert finished.wait(2)
    assert [r['reported_at'] for r in received] == [NOW, NOW+2]
    assert 'private' not in json.dumps(received)


def test_invalid_status_does_not_start_a_worker():
    publisher = status.Publisher()
    assert not publisher.submit(SimpleNamespace(report={'state': 'raw secret'}, controller=None), NOW)
    assert publisher.thread is None


def test_owner_required_before_configuration_or_database_access(web, monkeypatch):
    connect, load = Mock(), Mock()
    monkeypatch.setattr(web.ENGINE, 'connect', connect)
    monkeypatch.setattr(web.house_config, 'load_house_config', load)
    for role in (None, 'guest', 'family'):
        monkeypatch.setattr(web.AUTH, 'session', lambda request, role=role: (role, 'user'))
        assert web.api_hot_water_control_status(Mock()).status_code == 403
    connect.assert_not_called()
    load.assert_not_called()


def test_disabled_status_performs_no_database_access(web, monkeypatch):
    monkeypatch.setattr(web.house_config, 'load_house_config', lambda path: {})
    connect = Mock()
    monkeypatch.setattr(web.ENGINE, 'connect', connect)
    assert web.api_hot_water_control_status(Mock())['enabled'] is False
    connect.assert_not_called()


def test_config_and_database_failures_are_sanitized(web, monkeypatch):
    monkeypatch.setattr(web.house_config, 'load_house_config', lambda path: house())
    monkeypatch.setattr(web.ENGINE, 'connect', Mock(side_effect=OSError('secret endpoint')))
    result = web.api_hot_water_control_status(Mock())
    assert result['enabled'] is True and result['status']['state'] == 'unknown'
    assert 'secret' not in json.dumps(result)
    monkeypatch.setattr(web.house_config, 'load_house_config', Mock(side_effect=OSError('private path')))
    assert web.api_hot_water_control_status(Mock())['enabled'] is None


def test_actual_publication_and_owner_api_expire_without_private_fields(db, web, monkeypatch):
    import logger
    import time
    @contextmanager
    def connection():
        with db.transaction():
            yield db
    monkeypatch.setattr(logger, 'get_db', connection)
    db.execute('CREATE TABLE IF NOT EXISTS overrides(device text PRIMARY KEY,mode text,updated_at timestamptz DEFAULT NOW())')
    runtime = SimpleNamespace(report={'state': 'active', 'reason': 'secret'},
        controller=SimpleNamespace(state=report(endpoint='private')))
    status.publish(status.snapshot(runtime, NOW))
    raw = db.execute('SELECT mode FROM overrides WHERE device=%s', (status.DEVICE,)).fetchone()[0]
    assert 'private' not in raw and 'secret' not in raw
    engine = create_engine('postgresql+psycopg://', creator=lambda: psycopg.connect(db.info.dsn, password=os.environ['POSTGRES_PASSWORD']))
    monkeypatch.setattr(web, 'ENGINE', engine)
    monkeypatch.setattr(web.house_config, 'load_house_config', lambda path: house())
    monkeypatch.setattr(time, 'time', lambda: NOW+10)
    try:
        assert web.api_hot_water_control_status(Mock())['status']['state'] == 'active'
        monkeypatch.setattr(time, 'time', lambda: NOW+91)
        assert web.api_hot_water_control_status(Mock())['status']['state'] == 'unknown'
    finally:
        engine.dispose()
        db.execute('DELETE FROM overrides WHERE device=%s', (status.DEVICE,))
