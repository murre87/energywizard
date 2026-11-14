"""Replay real Ferroamp Lua with in-memory MQTT; never connect to a device."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("lupa")
from lua_host import LuaDriver, FTW_DIR
from drivers.ftw_device import FtwBatteryDriver
from battery_commands import Tracker


@pytest.fixture
def replay(monkeypatch):
    monkeypatch.setattr(LuaDriver, "_mqtt_subscribe", lambda *args: True)
    monkeypatch.setattr(LuaDriver, "_mqtt_publish", lambda *args: False)
    driver = LuaDriver(str(Path(FTW_DIR) / "ferroamp.lua"), log=lambda *args: None)
    tick = [10000]
    driver.L.globals().host.millis = lambda: tick[0]
    driver.L.globals().host.unix_ms = lambda: 1000000 + tick[0]
    return driver, tick


def packet(topic, data, stamp=None):
    return {"topic": "extapi/data/" + topic, "payload": json.dumps(data), "received_at": stamp}


def poll(driver, packets):
    driver._mqtt_buf.extend(packets)
    return driver.poll()[0]["battery"]


def eso(name, stamp):
    return packet("eso", {"id": {"val": name}, "ubat": {"val": 50}, "ibat": {"val": -10}}, stamp)


def test_oldest_contributor_survives_polling_and_tracks_only_new_measurements(replay):
    driver, tick = replay
    battery = poll(driver, [eso("a", 1001), eso("b", 1005)])
    assert battery["w"] == 1000
    assert battery["power_sample_at"] == 1001
    tick[0] += 10000
    assert poll(driver, [eso("b", 1015)])["power_sample_at"] == 1001
    assert poll(driver, [eso("a", 1016)])["power_sample_at"] == 1015
    adapter = FtwBatteryDriver.__new__(FtwBatteryDriver)
    adapter.capacity_kwh = 10
    adapter._dev = SimpleNamespace(emits=driver.emits, fresh=lambda: True)
    state = adapter.read_state()
    assert state["power_sample_at"] == 1015
    events = []
    tracker = Tracker(sink=events.append)
    command = tracker.begin("charge", 1000, 1015)
    tracker.sent(command, True, 1015)
    tracker.observe(command, state, 1016)
    assert events[-1]["state"] == "unconfirmed"  # receipt predates the send
    command = tracker.begin("charge", 1000, 1014)
    tracker.sent(command, True, 1014)
    tracker.observe(command, state, 1016)
    assert events[-1]["state"] == "physically_applied"
    tracker.observe(command, state, 1200)
    assert events[-1]["state"] == "unconfirmed"
    adapter._dev.fresh = lambda: False
    assert adapter.read_state().get("power_sample_at") is None


def test_missing_receipt_and_retained_data_do_not_gain_poll_timestamps(replay):
    driver, tick = replay
    assert poll(driver, [eso("a", 1001), eso("b", None)]).get("power_sample_at") is None
    tick[0] += 10000
    assert poll(driver, []).get("power_sample_at") is None


def test_ehub_fallback_uses_its_own_receipt_not_unrelated_packets(replay):
    driver, tick = replay
    assert poll(driver, [packet("ehub", {"pbat": {"val": -500}}, 1001)])["power_sample_at"] == 1001
    tick[0] += 10000
    assert poll(driver, [packet("sso", {}, 1015)])["power_sample_at"] == 1001
    assert poll(driver, [packet("ehub", {"pbat": {"val": -500}})]).get("power_sample_at") is None


def test_mqtt_callback_dates_arrival_before_poll_and_excludes_retained(monkeypatch):
    import paho.mqtt.client as mqtt
    client = SimpleNamespace(connect=lambda *a, **k: None, loop_start=lambda: None)
    monkeypatch.setattr(mqtt, "Client", lambda *a, **k: client)
    driver = LuaDriver.__new__(LuaDriver)
    driver._mqtt = None
    driver._cfg_raw = {}
    driver._mqtt_buf = []
    driver._mb_args = ("192.0.2.1", 1883, 1, 1)
    driver.path = "ferroamp.lua"
    monkeypatch.setattr("lua_host.time.time", lambda: 1001)
    driver._mqtt_client()
    for retained in (False, True):
        client.on_message(None, None, SimpleNamespace(topic="extapi/data/eso", payload=b"{}", retain=retained))
    assert [m["received_at"] for m in driver._mqtt_buf] == [1001, None]
