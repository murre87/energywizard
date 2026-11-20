from unittest.mock import Mock

import pytest

from plug_presence import Watch, present, run, vacation_on

T = 1794528000.


def config(**changes):
    device = dict(enabled=True, nonessential=True, switch='switch.tv', occupied='binary_sensor.office')
    device.update(changes.pop('device', {}))
    base = dict(enabled=True, devices=[device])
    base.update(changes)
    return base


def snap(entity, state):
    return dict(entity_id=entity, state=state)


def test_presence_states():
    assert present(snap('binary_sensor.office', 'on')) is True
    assert present(snap('input_boolean.home', 'off')) is False
    assert present(snap('person.emil', 'home')) is True
    assert present(snap('device_tracker.phone', 'not_home')) is False
    for entity, state in (
        ('binary_sensor.office', 'unavailable'),
        ('binary_sensor.office', 'unknown'),
        ('person.emil', 'work'),
        ('sensor.office', 'off'),
        ('binary_sensor.office', 'ON'),
    ):
        assert present(snap(entity, state)) is None
    assert present(None) is None
    assert present({'state': 'off'}) is None
    assert vacation_on(snap('input_boolean.vacation', 'on')) is True
    assert vacation_on(snap('input_boolean.vacation', 'off')) is False
    assert vacation_on(snap('person.emil', 'home')) is False
    assert vacation_on(snap('binary_sensor.vacation', 'unknown')) is False


def test_defaults_and_invalid_occupancy():
    room = Watch(config()).rooms[0]
    assert room['delay'] == 15 * 60 and room['label'] == '15'
    assert not Watch(None).active
    assert not Watch(dict(enabled=False, home='nope')).active
    for changes in (
        dict(device=dict(occupied='switch.tv')),
        dict(device=dict(occupied='binary_sensor.Bad')),
        dict(device=dict(unoccupied_minutes=4)),
        dict(device=dict(unoccupied_minutes=True)),
        dict(device=dict(occupied=None, unoccupied_minutes=15)),
        dict(away_minutes=15),
        dict(home='person.Bad'),
        dict(home='binary_sensor.home', away_minutes=4),
        dict(vacation='person.emil'),
        dict(vacation='input_boolean.Vacation'),
        dict(device=dict(presence_off='yes')),
        dict(device=dict(presence_off=True, away=True)),
        dict(device=dict(vacation=True)),
        dict(home='person.emil', device=dict(presence_off=True, vacation=True)),
    ):
        with pytest.raises(ValueError):
            Watch(config(**changes))
    skipped = config(device=dict(always_on=True, occupied='not a sensor'))
    assert not Watch(skipped).active


def record_into(notes):
    def record(*args):
        notes.append(args)
    return record


def test_room_empty_is_logged_once_and_unknown_is_not_empty():
    notes = []
    watch = Watch(config(device=dict(occupied='binary_sensor.office', unoccupied_minutes=5)))
    states = {'binary_sensor.office': 'off'}

    def read(entity):
        return snap(entity, states[entity])

    record = record_into(notes)
    watch.tick(T, read, record)
    watch.tick(T + 299, read, record)
    assert notes == []
    watch.tick(T + 300, read, record)
    watch.tick(T + 600, read, record)
    assert notes == [('switch.tv', 'room empty for 5 min')]
    states['binary_sensor.office'] = 'on'
    watch.tick(T + 601, read, record)
    states['binary_sensor.office'] = 'unavailable'
    watch.tick(T + 602, read, record)
    watch.tick(T + 1000, read, record)
    assert notes == [('switch.tv', 'room empty for 5 min')]
    states['binary_sensor.office'] = 'off'
    watch.tick(T + 1001, read, record)
    watch.tick(T + 1301, read, record)
    assert notes[-1] == ('switch.tv', 'room empty for 5 min')
    assert len(notes) == 2


def test_clock_backwards_restarts_the_wait_and_a_failed_log_retries():
    notes = []
    watch = Watch(config(device=dict(unoccupied_minutes=5)))
    read = lambda entity: snap(entity, 'off')
    record = record_into(notes)
    watch.tick(T + 100, read, record)
    watch.tick(T, read, record)
    watch.tick(T + 299, read, record)
    assert notes == []
    watch.tick(T + 300, read, record)
    assert len(notes) == 1

    def boom(*_args):
        raise RuntimeError('log')

    again = Watch(config(device=dict(unoccupied_minutes=5)))
    again.tick(T, read, boom)
    again.tick(T + 300, read, boom)
    again.tick(T + 301, read, record)
    assert notes[-1][0] == 'switch.tv'


def test_home_and_vacation_log_without_a_plug_write():
    notes = []
    watch = Watch(config(home='person.emil', away_minutes=5, vacation='input_boolean.vacation'))
    states = {'binary_sensor.office': 'on', 'person.emil': 'home', 'input_boolean.vacation': 'off'}

    def read(entity):
        return snap(entity, states[entity])

    record = record_into(notes)
    watch.tick(T, read, record)
    states['person.emil'] = 'not_home'
    states['input_boolean.vacation'] = 'on'
    watch.tick(T, read, record)
    watch.tick(T + 299, read, record)
    assert notes == [('vacation', 'vacation')]
    watch.tick(T + 300, read, record)
    watch.tick(T + 600, read, record)
    assert notes == [('vacation', 'vacation'), ('home', 'home empty for 5 min')]
    states['input_boolean.vacation'] = 'unknown'
    watch.tick(T + 601, read, record)
    states['input_boolean.vacation'] = 'on'
    watch.tick(T + 602, read, record)
    assert notes[-1] == ('vacation', 'vacation')
    assert all(note[0] != 'write' for note in notes)


def test_read_errors_do_not_count_as_empty_and_disabled_run_is_silent(monkeypatch):
    import homeassistant as ha
    get = Mock(side_effect=OSError('down'))
    post = Mock()
    monkeypatch.setattr(ha.requests, 'get', get)
    monkeypatch.setattr(ha.requests, 'post', post)
    watch = Watch(config(device=dict(unoccupied_minutes=5), home='binary_sensor.home'))
    run(watch, T)
    run(watch, T + 1000)
    post.assert_not_called()
    assert get.call_count == 4
    run(Watch(dict(enabled=True, devices=[])), T)
    assert get.call_count == 4


def test_adapter_gets_the_named_entity_and_never_posts(monkeypatch, capsys):
    import homeassistant as ha
    watch = Watch(config(device=dict(occupied='binary_sensor.office', unoccupied_minutes=5),
                         vacation='input_boolean.vacation'))

    def get(url, **kwargs):
        assert kwargs['verify'] == ha._VERIFY and kwargs['timeout'] == 5
        entity = url.rsplit('/', 1)[-1]
        if entity == 'binary_sensor.office':
            get.office += 1
            body = snap('binary_sensor.other', 'off') if get.office > 1 else snap(entity, 'off')
        else:
            body = snap(entity, 'on')
        return Mock(json=Mock(return_value=body))

    get.office = 0
    get_mock = Mock(side_effect=get)
    post = Mock()
    monkeypatch.setattr(ha.requests, 'get', get_mock)
    monkeypatch.setattr(ha.requests, 'post', post)
    run(watch, T)
    run(watch, T + 300)
    urls = [call.args[0] for call in get_mock.call_args_list]
    assert any(url.endswith('/binary_sensor.office') for url in urls)
    assert any(url.endswith('/input_boolean.vacation') for url in urls)
    post.assert_not_called()
    err = capsys.readouterr().out
    assert 'Smart plugs: vacation' in err
    assert 'room empty' not in err


def test_presence_off_without_a_signal_is_rejected():
    bare = dict(enabled=True, nonessential=True, switch='switch.tv', presence_off=True)
    with pytest.raises(ValueError):
        Watch(dict(enabled=True, devices=[bare]))
    assert Watch(None).switches_to_cut() == ()


def test_presence_off_selects_only_opted_in_signals_and_a_failed_log_still_counts():
    logged = Watch(config(device=dict(unoccupied_minutes=5)))
    read = lambda entity: snap(entity, 'off')
    logged.tick(T, read, record_into([]))
    logged.tick(T + 300, read, record_into([]))
    assert logged.switches_to_cut() == ()

    notes = []
    watch = Watch(config(
        home='person.emil', away_minutes=5, vacation='input_boolean.vacation',
        device=dict(unoccupied_minutes=5, presence_off=True, away=True)))
    states = {'binary_sensor.office': 'on', 'person.emil': 'home', 'input_boolean.vacation': 'off'}

    def read_states(entity):
        return snap(entity, states[entity])

    record = record_into(notes)
    watch.tick(T, read_states, record)
    assert watch.switches_to_cut() == ()
    states['binary_sensor.office'] = 'off'
    states['person.emil'] = 'not_home'
    states['input_boolean.vacation'] = 'on'
    watch.tick(T, read_states, record)
    assert notes == [('vacation', 'vacation')]
    assert watch.switches_to_cut() == ()
    watch.tick(T + 300, read_states, record)
    assert watch.switches_to_cut() == ('switch.tv',)
    states['binary_sensor.office'] = 'on'
    states['person.emil'] = 'home'
    states['input_boolean.vacation'] = 'off'
    watch.tick(T + 600, read_states, record)
    assert watch.switches_to_cut() == ()

    def boom(*_args):
        raise RuntimeError('log')

    armed = Watch(config(device=dict(unoccupied_minutes=5, presence_off=True)))
    armed.tick(T, read, boom)
    armed.tick(T + 300, read, boom)
    assert armed.switches_to_cut() == ('switch.tv',)


def test_away_and_vacation_cut_only_the_plugs_that_opted_in():
    devices = [
        dict(enabled=True, nonessential=True, switch='switch.screen', occupied='binary_sensor.office',
             unoccupied_minutes=5, presence_off=True),
        dict(enabled=True, nonessential=True, switch='switch.lamp', presence_off=True, away=True, vacation=True),
    ]
    watch = Watch(dict(
        enabled=True, home='person.emil', away_minutes=5, vacation='input_boolean.vacation', devices=devices))
    states = {'binary_sensor.office': 'on', 'person.emil': 'home', 'input_boolean.vacation': 'on'}

    def read(entity):
        return snap(entity, states[entity])

    record = record_into([])
    watch.tick(T, read, record)
    assert watch.switches_to_cut() == ('switch.lamp',)
    states['input_boolean.vacation'] = 'off'
    states['person.emil'] = 'not_home'
    watch.tick(T, read, record)
    assert watch.switches_to_cut() == ()
    watch.tick(T + 300, read, record)
    assert watch.switches_to_cut() == ('switch.lamp',)
    states['binary_sensor.office'] = 'off'
    watch.tick(T + 300, read, record)
    assert watch.switches_to_cut() == ('switch.lamp',)
    watch.tick(T + 600, read, record)
    assert watch.switches_to_cut() == ('switch.screen', 'switch.lamp')


def test_presence_run_never_posts_and_the_controller_cuts_once(monkeypatch):
    import homeassistant as ha
    import shadow
    from smart_plugs import Controller
    from smart_plugs import run as plug_run
    monkeypatch.setattr(shadow, 'active', lambda: False)
    switch = dict(entity_id='switch.tv', state='on', context={'id': 'initial'},
                  last_changed='2026-11-01T00:00:00+00:00')
    bodies = {'binary_sensor.office': snap('binary_sensor.office', 'off'), 'switch.tv': switch}

    def get(url, **kwargs):
        assert kwargs['verify'] == ha._VERIFY and kwargs['timeout'] == 5
        return Mock(json=Mock(return_value=bodies[url.rsplit('/', 1)[-1]]))

    post = Mock(return_value=Mock(json=Mock(return_value=[dict(
        entity_id='switch.tv', state='off', context={'id': 'ew-off'},
        last_changed='2026-11-01T00:05:00+00:00')])))
    monkeypatch.setattr(ha.requests, 'get', Mock(side_effect=get))
    monkeypatch.setattr(ha.requests, 'post', post)
    watch = Watch(config(device=dict(unoccupied_minutes=5, presence_off=True)))
    run(watch, T)
    run(watch, T + 300)
    post.assert_not_called()
    assert watch.switches_to_cut() == ('switch.tv',)
    controller = Controller(dict(enabled=True, devices=[dict(
        enabled=True, nonessential=True, switch='switch.tv', off_above=2., restore_below=1.,
        min_on_minutes=5, min_off_minutes=5)]))
    plug_run(controller, 0.2, T, watch.switches_to_cut())
    post.assert_not_called()
    plug_run(controller, 0.2, T + 300, watch.switches_to_cut())
    assert post.call_count == 1
    assert post.call_args.args[0].endswith('/services/switch/turn_off')
    assert post.call_args.kwargs['json'] == {'entity_id': 'switch.tv'}
    assert controller.state['switch.tv']['reason'] == 'presence'
