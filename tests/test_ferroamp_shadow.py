"""Shadow requests must stop before Lua commands, broker clients or device I/O."""
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import shadow
import battery_commands
from drivers.ftw_device import FtwDevice,FtwBatteryDriver
from lua_host import LuaDriver


@pytest.fixture
def shadow_log(monkeypatch):
    monkeypatch.setattr(shadow,'active',lambda:True)
    record=Mock();monkeypatch.setattr(shadow,'record',record)
    return record


@pytest.mark.parametrize('intent',['charge','discharge','hold','idle','auto'])
def test_ferroamp_intents_are_shadow_only_and_not_physically_accepted(shadow_log,intent):
    dev=FtwDevice.__new__(FtwDevice)
    dev.name='ferroamp';dev._cmd_lock=threading.Lock()
    default=Mock(return_value=True)
    dev.drv=SimpleNamespace(command=Mock(return_value=True),
        L=SimpleNamespace(globals=lambda:SimpleNamespace(driver_default_mode=default)))
    battery=FtwBatteryDriver.__new__(FtwBatteryDriver)
    battery._control=True;battery._dev=dev;battery._pmax=5000;battery._last=None;battery._balance=False
    events=[];tracker=battery_commands.Tracker(events.append)
    assert battery_commands.apply(tracker,battery,intent,1000)
    dev.drv.command.assert_not_called();default.assert_not_called()
    assert events[-1]['reason']=='shadow_mode_no_physical_command'
    assert tracker.current['accepted'] is False
    assert shadow_log.call_count==1
    if intent=='charge':
        assert not battery.refresh()
        dev.drv.command.assert_not_called()
    assert battery._last is None


def test_balance_request_does_not_wait_for_poll_lock_or_enter_lua(shadow_log):
    dev=FtwDevice.__new__(FtwDevice);dev.name='ferroamp'
    class RejectLock:
        def __enter__(self):raise AssertionError('shadow must not wait for a device poll')
        def __exit__(self,*args):pass
    dev._cmd_lock=RejectLock()
    dev.drv=Mock()
    assert dev.command('battery',1000,balance=True)
    assert dev.default_mode()
    dev.drv.command.assert_not_called()
    assert 'balance' in shadow_log.call_args_list[0].args[1]


def test_entering_shadow_clears_keepalive_without_resuming_it_later(shadow_log,monkeypatch):
    dev=FtwDevice.__new__(FtwDevice);dev.name='ferroamp';dev._cmd_lock=threading.Lock();dev.drv=Mock()
    battery=FtwBatteryDriver.__new__(FtwBatteryDriver)
    battery._control=True;battery._dev=dev;battery._pmax=5000;battery._last=('charge',1000);battery._balance=False
    assert battery.refresh()
    assert battery._last is None
    monkeypatch.setattr(shadow,'active',lambda:False)  # Local stub only; no live setting is changed.
    assert not battery.refresh()
    dev.drv.command.assert_not_called()


def test_mqtt_shadow_guard_also_covers_poll_and_cleanup(shadow_log):
    driver=LuaDriver.__new__(LuaDriver)
    driver.path='/private/path/ferroamp.lua';driver.allow_write=True
    driver._mqtt_client=Mock(side_effect=AssertionError('must not connect to broker'))
    assert driver._mqtt_publish('private-device-topic','private-payload-token')
    driver._mqtt_client.assert_not_called()
    assert shadow_log.call_args.args==('FTW MQTT publish','ferroamp.lua')


def test_read_only_gate_remains_before_shadow_success(shadow_log):
    driver=LuaDriver.__new__(LuaDriver);driver.path='ferroamp.lua';driver.allow_write=False
    driver._log=Mock();driver._mqtt_client=Mock()
    assert driver._mqtt_publish('topic','payload') is False
    driver._mqtt_client.assert_not_called();shadow_log.assert_not_called()


def test_nonshadow_dispatch_and_mqtt_return_values_are_unchanged(monkeypatch):
    monkeypatch.setattr(shadow,'active',lambda:False)
    dev=FtwDevice.__new__(FtwDevice);dev.name='ferroamp';dev._cmd_lock=threading.Lock()
    default=Mock(return_value=True);command=Mock(return_value=True)
    dev.drv=SimpleNamespace(command=command,L=SimpleNamespace(globals=lambda:SimpleNamespace(driver_default_mode=default)))
    assert dev.command('battery',1000,balance=True) and dev.default_mode()
    command.assert_called_once_with('battery',1000,{'source':'energywizard','duration_ms':120000,'balance':True})
    default.assert_called_once()
    driver=LuaDriver.__new__(LuaDriver);driver.path='ferroamp.lua';driver.allow_write=True
    publish=Mock(return_value=SimpleNamespace(rc=0))
    driver._mqtt_client=Mock(return_value=SimpleNamespace(publish=publish))
    assert driver._mqtt_publish('topic','payload')
    publish.assert_called_once_with('topic','payload')
