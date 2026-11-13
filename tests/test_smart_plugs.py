from unittest.mock import Mock

import pytest
from smart_plugs import Controller,run,policy_price

T=1794528000.


def snapshot(state='on',context='initial'):
    return dict(entity_id='switch.tv',state=state,context={'id':context},last_changed='2026-11-01T00:00:00+00:00')


def config(**changes):
    return dict(enabled=True,devices=[dict(enabled=True,nonessential=True,switch='switch.tv',
        off_above=2.,restore_below=1.,min_on_minutes=5,min_off_minutes=5,**changes)])


def test_fallback_missing_and_invalid_prices_are_not_used():
    transform=Mock(return_value=2.)
    for spot,strategy in [(None,{}),(float('nan'),{'price_fallback':False}),
                           (1,{}),(1,{'price_fallback':True})]:
        assert policy_price(spot,strategy,T,transform) is None
    transform.assert_not_called()
    assert policy_price(-1,{'price_fallback':False},T,transform)==2
    transform.assert_called_once_with(-1,T)


def test_disabled_adapter_has_no_ha_or_shadow_calls(monkeypatch):
    import homeassistant as ha,shadow
    get=Mock();active=Mock()
    monkeypatch.setattr(ha.requests,'get',get);monkeypatch.setattr(shadow,'active',active)
    run(Controller(None),3,T)
    get.assert_not_called();active.assert_not_called()


def test_defaults_critical_and_always_on_are_excluded():
    assert not Controller(None).devices
    c=config();c['enabled']=False
    assert not Controller(c).devices
    for key,value in [('nonessential',False),('always_on',True),('enabled',False)]:
        c=config();c['devices'][0][key]=value
        assert not Controller(c).devices


@pytest.mark.parametrize('key,value',[('off_above',float('nan')),('restore_below',2),
    ('min_on_minutes',0),('min_off_minutes',True),('switch','switch.tv, switch.fridge')])
def test_invalid_policy_is_rejected(key,value):
    c=config();c['devices'][0][key]=value
    with pytest.raises(ValueError):Controller(c)
    c=config();c['devices']*=2
    with pytest.raises(ValueError):Controller(c)


def test_price_hysteresis_dwell_and_owned_restoration():
    c=Controller(config());read=Mock(return_value=snapshot());write=Mock(return_value=snapshot('off','ew-off'))
    c.tick(3,T,read,write)
    c.tick(3,T+299,read,write);write.assert_not_called()
    c.tick(2,T+300,read,write);write.assert_not_called()
    c.tick(3,T+300,read,write);write.assert_called_once_with('switch.tv',False)
    read.return_value=snapshot('off','ew-off');write.reset_mock()
    c.tick(.5,T+599,read,write);write.assert_not_called()
    c.tick(1.5,T+600,read,write);write.assert_not_called()
    write.return_value=snapshot('on','ew-on')
    c.tick(.5,T+600,read,write);write.assert_called_once_with('switch.tv',True)


def test_initially_off_and_restart_never_gain_restore_authority():
    for c in (Controller(config()),Controller(config())):
        write=Mock();read=Mock(return_value=snapshot('off'))
        c.tick(.1,T,read,write);c.tick(.1,T+1000,read,write)
        write.assert_not_called()


@pytest.mark.parametrize('observation',[None,snapshot('unavailable'),snapshot('on','manual'),snapshot('off','manual')])
def test_manual_changes_and_missing_evidence_suspend_without_retry(observation):
    c=Controller(config());read=Mock(return_value=snapshot());write=Mock(return_value=snapshot('off','ew-off'))
    c.tick(3,T,read,write);c.tick(3,T+300,read,write);write.reset_mock()
    read.return_value=observation
    c.tick(.1,T+600,read,write)
    read.return_value=snapshot('off','ew-off')
    c.tick(.1,T+1200,read,write)
    write.assert_not_called()


@pytest.mark.parametrize('response',[None,{},snapshot('off','initial')])
def test_ambiguous_write_is_not_retried_or_restored(response):
    c=Controller(config());read=Mock(return_value=snapshot());write=Mock(return_value=response)
    c.tick(3,T,read,write);c.tick(3,T+300,read,write)
    c.tick(3,T+1000,read,write)
    assert write.call_count==1


def test_shadow_and_missing_price_never_write_or_keep_authority():
    c=Controller(config());read=Mock(return_value=snapshot());write=Mock(return_value=snapshot('off','ew-off'))
    c.tick(3,T,read,write);c.tick(3,T+300,read,write);write.reset_mock()
    c.tick(None,T+600,read,write);write.assert_not_called()
    c.tick(.1,T+900,read,write,shadow=True)
    assert c.state=={}
    read.return_value=snapshot('off','ew-off')
    c.tick(.1,T+1200,read,write);c.tick(.1,T+1800,read,write)
    write.assert_not_called()


def test_adapter_uses_fresh_get_and_changed_state_context(monkeypatch):
    import homeassistant as ha,shadow
    monkeypatch.setattr(shadow,'active',lambda:False)
    get=Mock(return_value=Mock(json=Mock(return_value=snapshot())))
    post=Mock(return_value=Mock(json=Mock(return_value=[snapshot('off','ew-off')])))
    monkeypatch.setattr(ha.requests,'get',get);monkeypatch.setattr(ha.requests,'post',post)
    c=Controller(config());run(c,3,T);run(c,3,T+300)
    assert get.call_count==2
    assert post.call_args.kwargs['json']=={'entity_id':'switch.tv'}
    assert post.call_args.kwargs['verify']==ha._VERIFY
    assert c.state['switch.tv']['owned']
