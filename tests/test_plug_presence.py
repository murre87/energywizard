"""#217: tomt rum och bortaläge noteras. Reläet ändras inte."""
from unittest.mock import Mock

import plug_presence
from plug_presence import Watch, select


T = 1794528000.0


def enrolled(*entities):
    return [{"entity": entity} for entity in entities]


def test_invalid_presence_is_ignored_and_only_enrolled_plugs_are_kept():
    devices = select(enrolled("switch.tv"), [
        {"switch": "switch.tv", "presence": "sensor.rum"},
        {"switch": "switch.other", "presence": "binary_sensor.other"},
    ])
    assert devices == [{"entity": "switch.tv", "presence": None, "unoccupied_s": 15 * 60}]
    custom = select(enrolled("switch.tv"), [{
        "switch": "switch.tv", "presence": "input_boolean.kontor", "unoccupied_minutes": 4}])
    assert custom[0]["presence"] == "input_boolean.kontor"
    assert custom[0]["unoccupied_s"] == 15 * 60
    assert select([], [{"switch": "switch.tv", "presence": "binary_sensor.rum"}]) == []


def test_empty_room_is_logged_once_and_unknown_does_not_count():
    watch = Watch(select(enrolled("switch.kontor"), [{
        "switch": "switch.kontor", "presence": "binary_sensor.kontor", "unoccupied_minutes": 15}]))
    notes = []
    switch = Mock(return_value="on")
    presence = Mock(return_value=False)

    def record(*args):
        notes.append(args)

    watch.tick(T, False, switch, presence, record)
    watch.tick(T + 14 * 60, False, switch, presence, record)
    assert notes == []
    watch.tick(T + 15 * 60, False, switch, presence, record)
    watch.tick(T + 40 * 60, False, switch, presence, record)
    assert notes == [("switch.kontor", "rummet har varit tomt, slår inte av")]
    presence.return_value = None
    watch.tick(T + 41 * 60, False, switch, presence, record)
    presence.return_value = False
    watch.tick(T + 42 * 60, False, switch, presence, record)
    watch.tick(T + 57 * 60 - 1, False, switch, presence, record)
    assert len(notes) == 1
    watch.tick(T + 57 * 60, False, switch, presence, record)
    watch.tick(T + 80 * 60, False, switch, presence, record)
    assert notes[-1] == ("switch.kontor", "rummet har varit tomt, slår inte av")
    assert len(notes) == 2


def test_off_occupied_and_clock_backwards_restart_the_wait():
    watch = Watch(select(enrolled("switch.tv"), [{
        "switch": "switch.tv", "presence": "binary_sensor.tv", "unoccupied_minutes": 5}]))
    notes = []

    def record(entity, detail):
        notes.append((entity, detail))

    switch = Mock(return_value="on")
    presence = Mock(return_value=True)
    watch.tick(T, False, switch, presence, record)
    presence.return_value = False
    watch.tick(T + 60, False, switch, presence, record)
    switch.return_value = "off"
    watch.tick(T + 10 * 60, False, switch, presence, record)
    switch.return_value = "on"
    started = T + 11 * 60
    watch.tick(started, False, switch, presence, record)
    started -= 5
    watch.tick(started, False, switch, presence, record)
    watch.tick(started + 5 * 60 - 1, False, switch, presence, record)
    assert notes == []
    watch.tick(started + 5 * 60, False, switch, presence, record)
    assert notes == [("switch.tv", "rummet har varit tomt, slår inte av")]


def test_away_logs_an_on_plug_once_and_does_not_read_presence():
    watch = Watch(select(enrolled("switch.tv", "switch.lampa"), [
        {"switch": "switch.tv", "presence": "binary_sensor.tv"},
        {"switch": "switch.lampa"},
    ]))
    notes = []

    def record(entity, detail):
        notes.append((entity, detail))

    switch = Mock(side_effect=lambda entity: "on" if entity == "switch.tv" else "off")
    presence = Mock(return_value=False)
    watch.tick(T, True, switch, presence, record)
    watch.tick(T + 3600, True, switch, presence, record)
    assert notes == [("switch.tv", "bortaläge, slår inte av")]
    presence.assert_not_called()
    watch.tick(T + 3601, False, switch, presence, record)
    watch.tick(T + 3601 + 15 * 60, False, switch, presence, record)
    assert notes[-1] == ("switch.tv", "rummet har varit tomt, slår inte av")
    notes.clear()
    watch.tick(T + 9000, True, switch, presence, record)
    assert notes == [("switch.tv", "bortaläge, slår inte av")]


def test_failed_log_and_failed_read_do_not_raise():
    watch = Watch(select(enrolled("switch.tv"), [{
        "switch": "switch.tv", "presence": "binary_sensor.tv", "unoccupied_minutes": 5}]))

    def boom(*_args):
        raise RuntimeError("log")

    watch.tick(T, True, Mock(return_value="on"), Mock(return_value=False), boom)
    watch.tick(T + 60, True, Mock(return_value="on"), Mock(return_value=False), boom)
    notes = []
    watch.tick(T + 120, True, Mock(side_effect=OSError("ha")), Mock(), notes.append)
    assert notes == []
    watch.tick(float("nan"), True, Mock(return_value="on"), Mock(), notes.append)
    assert notes == []


def test_adapter_reads_states_and_never_posts(monkeypatch, capsys):
    import homeassistant as ha

    def get(url, **kwargs):
        assert kwargs["verify"] == ha._VERIFY and kwargs["timeout"] == 5
        if url.endswith("/binary_sensor.kontor"):
            body = {"entity_id": "binary_sensor.kontor", "state": "off"}
        elif url.endswith("/switch.kontor"):
            body = {"entity_id": "switch.kontor", "state": "on"}
        else:
            body = {"entity_id": "other", "state": "on"}
        return Mock(json=Mock(return_value=body))

    get_mock = Mock(side_effect=get)
    post = Mock()
    monkeypatch.setattr(ha.requests, "get", get_mock)
    monkeypatch.setattr(ha.requests, "post", post)
    watch = Watch(select(enrolled("switch.kontor"), [{
        "switch": "switch.kontor", "presence": "binary_sensor.kontor", "unoccupied_minutes": 5}]))
    plug_presence.run(watch, T, False)
    plug_presence.run(watch, T + 5 * 60, False)
    post.assert_not_called()
    urls = [call.args[0] for call in get_mock.call_args_list]
    assert any(url.endswith("/switch.kontor") for url in urls)
    assert any(url.endswith("/binary_sensor.kontor") for url in urls)
    assert "rummet har varit tomt, slår inte av" in capsys.readouterr().out
    plug_presence.run(Watch([]), T, True)
    post.assert_not_called()
