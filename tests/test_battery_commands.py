import json
import sqlite3
from unittest.mock import Mock
import pytest
import battery_commands as B


def tracker():
    events=[];t=B.Tracker(events.append)
    cid=t.begin('charge',1000,100)
    t.sent(cid,True,101)
    return t,cid,events


def test_driver_provenance_is_code_owned_and_survives_transitions(monkeypatch):
    import shadow
    from drivers.battery_generic import GenericBatteryDriver
    monkeypatch.setattr(shadow,'active',lambda:False)
    driver=GenericBatteryDriver(entities={'power':'sensor.private_installation'})
    monkeypatch.setattr(driver,'apply_intent',Mock(return_value=True))
    events=[];t=B.Tracker(events.append)
    assert B.apply(t,driver,'charge',1000,now=100)
    assert {event['driver_kind'] for event in events}=={'generic_ha'}
    assert 'private_installation' not in json.dumps(events)
    driver.apply_intent.assert_called_once_with('charge',1000)
    t.begin('hold',None,200,driver_kind='secret-host.example')
    assert events[-2]['driver_kind']=='generic_ha'
    assert events[-1]['driver_kind']=='unknown'


def test_unknown_driver_and_legacy_callers_are_not_brand_qualified(monkeypatch):
    import shadow
    monkeypatch.setattr(shadow,'active',lambda:False)
    events=[];t=B.Tracker(events.append)
    B.apply(t,Mock(), 'hold',None)
    assert all(event['driver_kind']=='unknown' for event in events)
    t.begin('hold',None,200)
    assert events[-1]['driver_kind']=='unknown'


def test_ack_readback_and_physical_evidence_are_distinct():
    t,cid,events=tracker()
    assert events[-1]['state']=='sent'
    t.sent(cid,True,101,reference_verified=True)
    assert events[-1]['state']=='reference_verified'
    t.observe(cid,{'power_w':1000,'power_sample_at':102},103)
    assert events[-1]['state']=='physically_applied'
    assert events[-1]['latency_s']==1


@pytest.mark.parametrize('stamp,power', [(None,1000),(100,1000),(1,1000),(400,1000),(102,None),(102,float('nan'))])
def test_unconfirmed_is_not_failed_or_applied_for_missing_stale_or_future_data(stamp,power):
    t,cid,events=tracker()
    t.observe(cid,{'power_w':power,'power_sample_at':stamp},200)
    assert events[-1]['state']=='unconfirmed'


def test_wrong_direction_settling_limits_and_supersession():
    t,cid,events=tracker()
    t.observe(cid,{'power_w':-1000,'power_sample_at':102},103)
    assert events[-1]['reason']=='settling'
    t.observe(cid,{'power_w':-1000,'power_sample_at':230},230)
    assert events[-1]['state']=='failed'
    newer=t.begin('hold',None,240)
    before=len(events)
    t.observe(cid,{'power_w':1000,'power_sample_at':250},250)
    assert len(events)==before and t.current['command_id']==newer
    # Full SOC explains curtailed charging, but does not prove application.
    t,cid,events=tracker()
    t.observe(cid,{'power_w':0,'power_sample_at':250,'soc_pct':100},250,max_soc=100)
    assert events[-1]['reason']=='autonomous_or_soc_limited'


def test_restart_never_restores_command_authority():
    old,cid,events=tracker();new=B.Tracker(events.append)
    new.observe(cid,{'power_w':1000,'power_sample_at':500},500)
    assert new.current is None and old.session_id!=new.session_id


def test_apply_calls_driver_once_and_preserves_errors_when_tracking_storage_fails(monkeypatch):
    import shadow
    monkeypatch.setattr(shadow,'active',lambda:False)
    driver=Mock();driver.command_reference_verified=False;driver.apply_intent.return_value=True
    t=B.Tracker(lambda _: (_ for _ in ()).throw(OSError('disk full')))
    assert B.apply(t,driver,'charge',1000)
    driver.apply_intent.assert_called_once_with('charge',1000)
    driver.apply_intent.side_effect=RuntimeError('transport')
    with pytest.raises(RuntimeError):B.apply(t,driver,'hold',None)
    assert driver.apply_intent.call_count==2


def test_shadow_does_not_claim_physical_command(monkeypatch):
    import shadow
    monkeypatch.setattr(shadow,'active',lambda:True)
    events=[];t=B.Tracker(events.append);d=Mock();d.apply_intent.return_value=True
    B.apply(t,d,'charge',1000)
    assert events[-1]['reason']=='shadow_mode_no_physical_command'
    assert not t.current['accepted']


def test_persistence_is_bounded_and_private(tmp_path,monkeypatch):
    monkeypatch.setattr(B,'MAX_EVENTS',3)
    path=tmp_path/'commands.sqlite3'
    t,cid,events=tracker()
    import time
    for i in range(6):B.persist({**events[0],'at':time.time(),'sequence':i},path)
    with sqlite3.connect(path) as db:
        rows=db.execute('SELECT payload FROM command_events ORDER BY id').fetchall()
    assert len(rows)==3 and json.loads(rows[-1][0])['sequence']==5
    assert path.stat().st_mode & 0o777 == 0o600


def test_generic_driver_uses_source_timestamp_not_read_time(monkeypatch):
    import homeassistant
    from drivers.battery_generic import GenericBatteryDriver
    d=GenericBatteryDriver(entities={'power':'sensor.battery'})
    monkeypatch.setattr(homeassistant,'get_power_w',lambda _:1000)
    monkeypatch.setattr(homeassistant,'_states_cache',{'sensor.battery':{'state':'1000','last_updated':'2026-11-11T01:00:00+00:00'}})
    assert d.read_state()['power_sample_at']==1794358800
    homeassistant._states_cache['sensor.battery']['last_updated']='unknown'
    assert d.read_state()['power_sample_at'] is None
