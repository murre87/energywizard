import copy
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from queue import Queue
import subprocess
import threading

import pytest
import battery_plan
import plan_snapshot as S


def example():
    now = datetime(2026, 10, 25, 0, tzinfo=timezone.utc)
    slots = [{'t': now + timedelta(minutes=15*i), 'buy': price, 'sell': price/2,
              'load_kw': 1.0, 'solar_kw': 0, 'ev_kw': 0, 'ha_token': 'must-not-leak'}
             for i, price in enumerate([0.2, 2, -0.1, 1])]
    params = dict(soc0_kwh=1, capacity_kwh=2, reserve_kwh=0.2, max_kwh=2,
                  charge_kw=1, discharge_kw=1, eff=0.9, allowed={'auto', 'charge', 'hold', 'discharge'})
    result = battery_plan.optimize(slots, **params)
    return slots, params, result, now


def test_snapshot_replays_exactly_without_live_dependencies(tmp_path):
    snapshot = S.build(*example())
    assert S.replay(json.loads(S.canonical(snapshot)))['matches']
    assert 'must-not-leak' not in S.canonical(snapshot)
    assert 'ha_token' not in S.canonical(snapshot)
    S.store(snapshot, tmp_path)
    path = tmp_path / (snapshot['plan_id'] + '.json')
    assert path.stat().st_mode & 0o777 == 0o600
    cli = subprocess.run([os.sys.executable, 'scripts/replay_battery_plan.py', str(path)],
                         capture_output=True, text=True)
    assert cli.returncode == 0, cli.stderr
    assert json.loads(cli.stdout)['matches']


@pytest.mark.parametrize('change', ['schema', 'code', 'content', 'time', 'secret', 'nonfinite'])
def test_invalid_or_incompatible_evidence_rejected(change):
    slots, params, result, now = example()
    snap = S.build(slots, params, result, now)
    if change in ('schema', 'code', 'content'):
        key = {'schema': 'schema_version', 'code': 'planner_hash', 'content': 'made_at'}[change]
        snap[key] = 'changed'
        with pytest.raises(ValueError): S.replay(snap)
    else:
        if change == 'time': slots[0]['t'] = now.replace(tzinfo=None)
        if change == 'secret': params['token'] = 'private'
        if change == 'nonfinite': slots[0]['buy'] = float('nan')
        with pytest.raises(ValueError): S.build(slots, params, result, now)


def test_retention_limits_count_and_age(tmp_path, monkeypatch):
    snap = S.build(*example())
    monkeypatch.setattr(S, 'MAX_FILES', 3)
    for i in range(5):
        path = tmp_path / f'{i}.json';path.write_text('{}')
        os.utime(path, (i+1, i+1))
    S.store(snap, tmp_path)
    assert len(list(tmp_path.glob('*.json'))) == 1  # all old files expired
    for i in range(4): (tmp_path / f'new{i}.json').write_text('{}')
    S.store(snap, tmp_path)
    assert len(list(tmp_path.glob('*.json'))) <= 3


def test_stalled_storage_never_blocks_capture(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    def stalled(*args): entered.set();release.wait(5)
    monkeypatch.setattr(S, 'store', stalled)
    monkeypatch.setattr(S, '_queue', Queue(maxsize=1))
    monkeypatch.setattr(S, '_worker', None)
    try:
        assert S.capture(*example())
        assert entered.wait(2)
        assert S.capture(*example())  # one bounded pending item
        assert S.capture(*example()) is None  # drop instead of wait
    finally:
        release.set()
        S._queue.join()


def test_storage_error_and_disabled_capture_do_not_break_control(monkeypatch):
    monkeypatch.setenv('EW_PLAN_SNAPSHOTS', '0')
    assert S.capture(*example()) is None
    slots, params, result, now = example()
    params['credential'] = 'secret'
    monkeypatch.setenv('EW_PLAN_SNAPSHOTS', '1')
    assert S.capture(slots, params, result, now) is None
    assert battery_plan.optimize(slots, **example()[1]) == result
