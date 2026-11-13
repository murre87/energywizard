import errno
import json
import os
import threading
from queue import Queue
from unittest.mock import Mock

import pytest
import psycopg
import plan_snapshot as S
import snapshot_status as D
from test_plan_snapshot import example


@pytest.fixture(autouse=True)
def reset(monkeypatch):
    monkeypatch.setenv('EW_PLAN_SNAPSHOTS','1')
    monkeypatch.setattr(S,'_stats',dict(session='00000000-0000-0000-0000-000000000001',failed=0,dropped=0,
        last_saved_at=None,last_failure_at=None,saving=False))


def test_disabled_and_bad_capture_are_reported_without_configuration(monkeypatch):
    monkeypatch.setenv('EW_PLAN_SNAPSHOTS','0')
    assert S.capture(*example()) is None and S.status()['state']=='disabled'
    monkeypatch.setenv('EW_PLAN_SNAPSHOTS','1')
    args=list(example());args[1]={**args[1],'token':'private-secret'}
    assert S.capture(*args) is None
    status=S.status()
    assert status['failed']==1 and status['state']=='failed'
    assert 'private-secret' not in json.dumps(status)


def test_full_disk_queue_drop_and_later_success_remain_observable(monkeypatch):
    entered,release=threading.Event(),threading.Event()
    calls=[]
    def store(*args):
        calls.append(args)
        if len(calls)==1:
            entered.set();assert release.wait(3)
            raise OSError(errno.ENOSPC,'private/path/token')
    monkeypatch.setattr(S,'store',store)
    monkeypatch.setattr(S,'_queue',Queue(maxsize=1))
    monkeypatch.setattr(S,'_worker',None)
    try:
        assert S.capture(*example()) and entered.wait(2)
        assert S.status()['state']=='saving'
        assert S.capture(*example())
        assert S.capture(*example()) is None
        assert S.status()['pending']==1 and S.status()['dropped']==1
        # Publication can observe the stalled writer independently.
        sink=Mock();publisher=D.Publisher(S.status,sink)
        assert publisher.tick(100)
        assert sink.call_args.args[0]['dropped']==1
    finally:
        release.set();S._queue.join()
    status=S.status()
    assert status['failed']==1 and status['dropped']==1
    assert status['state']=='saved' and status['last_saved_at']>=status['last_failure_at']
    assert 'private/path' not in json.dumps(status)


def test_publisher_retries_only_diagnostics_and_heartbeats():
    report=S.status();sink=Mock(side_effect=[OSError('database'),None,None])
    publisher=D.Publisher(lambda:report,sink)
    assert publisher.tick(100) is False
    assert publisher.tick(105) is True
    assert publisher.tick(110) is False
    assert publisher.tick(165) is True
    assert sink.call_count==3


def test_reader_is_bounded_allowlisted_and_rejects_stale_future_reports():
    report={**S.status(),'reported_at':100,'raw_config':'private'}
    result=D.decode(json.dumps(report),110)
    assert result['fresh'] and result['state']=='waiting' and 'raw_config' not in result
    for value in [None,'x'*4097,'[]','{',json.dumps({**report,'reported_at':0}),
                  json.dumps({**report,'reported_at':116}),json.dumps({**report,'failed':True}),
                  json.dumps({**report,'last_saved_at':float('nan')}),json.dumps({**report,'schema':True})]:
        assert D.decode(value,110)==dict(state='unknown',fresh=False)


def test_owner_api_denies_other_roles_and_does_not_dump_errors(monkeypatch):
    import importlib.util
    from pathlib import Path
    spec=importlib.util.spec_from_file_location('snapshot_web',Path(__file__).resolve().parents[1]/'webdashboard/app.py')
    web=importlib.util.module_from_spec(spec)
    monkeypatch.chdir(Path(__file__).resolve().parents[1]/'webdashboard')
    spec.loader.exec_module(web)
    connection=Mock()
    monkeypatch.setattr(web.ENGINE,'connect',connection)
    for role in (None,'guest','family'):
        monkeypatch.setattr(web.AUTH,'session',lambda _req,r=role:(r,'user'))
        assert web.api_snapshot_status(Mock()).status_code==403
    connection.assert_not_called()
    monkeypatch.setattr(web.AUTH,'session',lambda _req:('owner','owner'))
    connection.side_effect=OSError('private database details')
    assert web.api_snapshot_status(Mock())==dict(ok=True,status=dict(state='unknown',fresh=False))


def test_status_crosses_process_boundary_via_real_database(db,monkeypatch):
    import logger
    from contextlib import contextmanager
    from sqlalchemy import create_engine
    db.execute('CREATE TABLE IF NOT EXISTS overrides (device TEXT PRIMARY KEY,mode TEXT,updated_at TIMESTAMPTZ DEFAULT NOW())')
    @contextmanager
    def connection():
        with db.transaction():yield db
    monkeypatch.setattr(logger,'get_db',connection)
    now=1000
    source={**S.status(),'state':'failed','failed':1,'dropped':2,'last_failure_at':999}
    assert D.Publisher(lambda:source,D.write).tick(now)
    engine=create_engine('postgresql+psycopg://',creator=lambda: psycopg.connect(db.info.dsn,password=os.environ['POSTGRES_PASSWORD']))
    try:
        with engine.connect() as conn:
            import snapshot_status
            monkeypatch.setattr(snapshot_status.time,'time',lambda:1010)
            result=D.read(conn)
        assert result['fresh'] and result['failed']==1 and result['dropped']==2
        # A recovered save retains cumulative failures; restart resets via a new session.
        source.update(state='saved',last_saved_at=1011)
        assert D.Publisher(lambda:source,D.write).tick(1012)
        with engine.connect() as conn:
            assert D.read(conn)['state']=='saved'
    finally:
        engine.dispose()
        db.execute('DELETE FROM overrides WHERE device=%s',(D.DEVICE,))


def test_queued_state_and_blocked_publication_do_not_block_capture(monkeypatch):
    queue=Queue(maxsize=1);queue.put_nowait('pending')
    monkeypatch.setattr(S,'_queue',queue)
    assert S.status()['state']=='queued'
    queue.get_nowait();queue.task_done()
    entered,release=threading.Event(),threading.Event()
    def blocked(_):entered.set();release.wait(3)
    publisher=D.Publisher(S.status,blocked)
    thread=threading.Thread(target=lambda:publisher.tick(100))
    thread.start()
    monkeypatch.setattr(S,'_worker',Mock())  # Queue can accept without a running writer.
    try:
        assert entered.wait(2)
        assert S.capture(*example())  # No publication/storage work on this caller.
    finally:
        release.set();thread.join(3)
