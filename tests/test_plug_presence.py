from unittest.mock import Mock

import pytest

from plug_presence import Watcher, present, run, vacation_active

T = 1794528000.0


def presence(**devices):
    body = dict(devices)
    body.setdefault("devices", [dict(
        switch="switch.screen", occupancy="binary_sensor.office", unoccupied_minutes=5)])
    return dict(presence=body)


def test_present_and_vacation_readings():
    assert present("person.emil", "home") is True
    assert present("device_tracker.phone", "not_home") is False
    assert present("device_tracker.phone", "Work") is False
    assert present("binary_sensor.office", "on") is True
    assert present("binary_sensor.office", "off") is False
    assert present("input_boolean.home", "ON") is True
    for state in ("unavailable", "unknown", "", None, True):
        assert present("person.emil", state) is None
    assert vacation_active("on") is True
    assert vacation_active("off") is False
    assert vacation_active("unknown") is None


def test_missing_presence_does_nothing():
    assert Watcher(None).devices == []
    assert Watcher({}).devices == []
    assert Watcher(dict(enabled=True)).devices == []


@pytest.mark.parametrize("config", [
    dict(presence=[]),
    dict(presence=dict(devices=[])),
    dict(presence=dict(devices=[dict(switch="switch.screen")])),
    dict(presence=dict(devices=[dict(switch="light.screen", occupancy="binary_sensor.office")])),
    dict(presence=dict(devices=[dict(switch="switch.screen", occupancy="sensor.office")])),
    dict(presence=dict(devices=[dict(switch="switch.screen", away=True)])),
    dict(presence=dict(away="person.emil", devices=[dict(switch="switch.screen", vacation=True)])),
    dict(presence=dict(vacation="person.emil", devices=[dict(switch="switch.screen", vacation=True)])),
    dict(presence=dict(devices=[dict(switch="switch.screen", occupancy="binary_sensor.office",
                                     unoccupied_minutes=4)])),
    dict(presence=dict(away_minutes=True, away="person.emil",
                       devices=[dict(switch="switch.screen", away=True)])),
    dict(presence=dict(devices=[dict(switch="switch.screen", occupancy="binary_sensor.office")] * 2)),
    dict(presence=dict(devices=[dict(switch=f"switch.p{i}", occupancy="binary_sensor.office")
                                for i in range(33)])),
])
def test_invalid_presence_is_rejected(config):
    with pytest.raises(ValueError):
        Watcher(config)


def note(notes):
    def record(*args):
        notes.append(args)
    return record


def test_room_empty_is_logged_once_and_restored_after_the_same_dwell():
    notes = []
    watcher = Watcher(presence())
    read = Mock(return_value="off")
    watcher.tick(T, read, note(notes))
    watcher.tick(T + 299, read, note(notes))
    assert notes == []
    watcher.tick(T + 300, read, note(notes))
    watcher.tick(T + 600, read, note(notes))
    assert notes == [("switch.screen", "presence would turn off (room empty)")]
    read.return_value = "on"
    watcher.tick(T + 601, read, note(notes))
    watcher.tick(T + 900, read, note(notes))
    assert len(notes) == 1
    watcher.tick(T + 901, read, note(notes))
    assert notes[-1] == ("switch.screen", "presence would turn on")


def test_unknown_is_not_empty_and_does_not_restore():
    notes = []
    watcher = Watcher(presence())
    read = Mock(return_value="unavailable")
    watcher.tick(T, read, note(notes))
    watcher.tick(T + 1000, read, note(notes))
    assert notes == []
    read.return_value = "off"
    watcher.tick(T + 1000, read, note(notes))
    watcher.tick(T + 1300, read, note(notes))
    assert notes == [("switch.screen", "presence would turn off (room empty)")]
    read.side_effect = RuntimeError("ha")
    watcher.tick(T + 2000, read, note(notes))
    watcher.tick(T + 4000, read, note(notes))
    assert len(notes) == 1


def test_away_and_vacation_combine_without_a_room_sensor():
    notes = []
    watcher = Watcher(presence(
        away="person.emil", vacation="input_boolean.semester", away_minutes=5, vacation_minutes=10,
        devices=[dict(switch="switch.screen", away=True, vacation=True)]))
    states = {"person.emil": "home", "input_boolean.semester": "off"}

    def read(entity):
        return states[entity]

    watcher.tick(T, read, note(notes))
    states["person.emil"] = "not_home"
    watcher.tick(T + 300, read, note(notes))
    assert notes == []
    watcher.tick(T + 600, read, note(notes))
    assert notes == [("switch.screen", "presence would turn off (house away)")]
    states["input_boolean.semester"] = "on"
    watcher.tick(T + 600, read, note(notes))
    watcher.tick(T + 1200, read, note(notes))
    assert notes[-1] == ("switch.screen", "presence would turn off (house away, vacation)")
    states["person.emil"] = "home"
    states["input_boolean.semester"] = "off"
    watcher.tick(T + 1200, read, note(notes))
    watcher.tick(T + 1500, read, note(notes))
    assert len(notes) == 2
    watcher.tick(T + 1800, read, note(notes))
    assert notes[-1] == ("switch.screen", "presence would turn on")


def test_a_device_only_follows_the_policies_it_opted_into():
    notes = []
    watcher = Watcher(presence(
        away="person.emil",
        devices=[dict(switch="switch.screen", occupancy="binary_sensor.office", unoccupied_minutes=5)]))
    states = {"person.emil": "not_home", "binary_sensor.office": "on"}
    watcher.tick(T, lambda entity: states[entity], note(notes))
    watcher.tick(T + 1000, lambda entity: states[entity], note(notes))
    assert notes == []


def test_failed_log_is_retried_and_a_backwards_clock_restarts_the_dwell():
    watcher = Watcher(presence())

    def boom(*_args):
        raise RuntimeError("log")

    read = Mock(return_value="off")
    watcher.tick(T, read, boom)
    watcher.tick(T + 300, read, boom)
    notes = []
    watcher.tick(T + 300, read, note(notes))
    assert notes == [("switch.screen", "presence would turn off (room empty)")]
    read.return_value = "on"
    watcher.tick(T + 200, read, note(notes))
    watcher.tick(T + 500, read, note(notes))
    assert notes[-1] == ("switch.screen", "presence would turn on")


def test_adapter_only_gets_states(monkeypatch):
    import homeassistant as ha
    body = {
        "binary_sensor.office": dict(entity_id="binary_sensor.office", state="off"),
        "switch.screen": dict(entity_id="switch.screen", state="on"),
    }

    def get(url, **kwargs):
        assert kwargs["verify"] == ha._VERIFY and kwargs["timeout"] == 5
        entity = url.rsplit("/", 1)[-1]
        return Mock(json=Mock(return_value=body[entity]))

    get_mock = Mock(side_effect=get)
    post = Mock()
    monkeypatch.setattr(ha.requests, "get", get_mock)
    monkeypatch.setattr(ha.requests, "post", post)
    watcher = Watcher(presence())
    run(watcher, T)
    run(watcher, T + 300)
    assert [call.args[0].rsplit("/", 1)[-1] for call in get_mock.call_args_list] == [
        "binary_sensor.office", "binary_sensor.office"]
    post.assert_not_called()


def test_disabled_adapter_does_not_touch_home_assistant(monkeypatch):
    import homeassistant as ha
    get = Mock()
    monkeypatch.setattr(ha.requests, "get", get)
    run(Watcher(None), T)
    get.assert_not_called()
