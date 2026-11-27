"""Enkel installation: HA-adress som http/https, omstart när house_config.yaml ändras, och
entitetsväljarens "Spara och starta" (bara när install.sh gjort filen skrivbar, bara ägaren)."""
import asyncio
import importlib.util
import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "smartbox"))

import config_watch  # noqa: E402
import homeassistant  # noqa: E402


@pytest.mark.parametrize("given,expected", [
    ("192.168.1.10", "http://192.168.1.10:8123"),
    ("homeassistant.local:8124/", "http://homeassistant.local:8124"),
    ("http://10.0.0.2:8123/api", "http://10.0.0.2:8123"),
    ("https://ha.example.se", "https://ha.example.se"),        # bakom proxy på 443: rörs inte
    ("https://ha.example.se:8123/", "https://ha.example.se:8123"),
])
def test_normalize_ha_url(given, expected):
    assert homeassistant.normalize_ha_url(given) == expected


def test_config_watch_sees_change(tmp_path):
    p = tmp_path / "house_config.yaml"
    p.write_text('house_id: "a"\n')
    before = config_watch._signature(str(p))
    assert config_watch.changed(str(p), before) is None
    time.sleep(0.01)
    with open(p, "w") as f:                       # på plats, som webben skriver
        f.write('house_id: "a"\nfuse:\n  main_fuse_a: 20\n')
    assert config_watch.changed(str(p), before) is not None
    p.unlink()
    assert config_watch.changed(str(p), before) is None   # borttagen fil -> ingen omstart


def test_config_watch_thread_calls_on_change(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("a\n")
    hits = []
    config_watch.start(str(p), on_change=lambda: hits.append(1), every_s=0.05)
    time.sleep(0.1)
    p.write_text("abc\n")
    for _ in range(60):
        if hits:
            break
        time.sleep(0.1)
    assert hits == [1]


class _FakeRequest:
    def __init__(self, body=None, cookies=None):
        self._body = body or {}
        self.cookies = cookies or {}
        self.headers = {}
        self.client = type("c", (), {"host": "10.0.0.5"})()

    async def json(self):
        return self._body


@pytest.fixture(scope="module")
def wd():
    mp = pytest.MonkeyPatch()
    mp.setenv("DASHBOARD_PASSWORD", "hemligt123")
    import webauth
    mp.setattr(webauth, "PASSWORD", "hemligt123")
    cwd = Path.cwd()
    os.chdir(ROOT / "webdashboard")
    try:
        spec = importlib.util.spec_from_file_location("webdashboard_app_install", ROOT / "webdashboard" / "app.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules["webdashboard_app_install"] = mod
        spec.loader.exec_module(mod)
    finally:
        os.chdir(cwd)
    yield mod
    mp.undo()


def _cookie(wd, role="owner"):
    return {wd.AUTH.cookie: wd.AUTH.sign(int(time.time()) + 3600, role, role)}


SEL = {"cars": [], "heat_pump": None, "solar": None, "spa": None, "battery": None}


def test_configured_cars_read_current_yaml_without_discovery(wd, tmp_path, monkeypatch):
    import yaml

    config = tmp_path / "house_config.yaml"
    monkeypatch.setattr(wd, "HOUSE_CONFIG_FILE", str(config))
    monkeypatch.setattr(wd, "_last_discovery_path", lambda: str(tmp_path / "last_discovery.json"))
    (tmp_path / "last_discovery.json").write_text('{"ok":true,"cars":[{"id":"old-scan"}]}', encoding="utf-8")
    request = _FakeRequest(cookies=_cookie(wd))
    assert asyncio.run(wd.api_configured_cars(request)) == {"cars": []}

    car = {"id": "IONIQ", "driver": "generic_ev", "battery_kwh": 38, "entities": {
        "soc": "sensor.ioniq_ev_battery_level", "plugged_in": "binary_sensor.ioniq_ev_battery_plug",
        "climate": "climate.ioniq", "private": "omit",
    }}
    config.write_text(yaml.safe_dump({"evs": [car]}), encoding="utf-8")
    assert asyncio.run(wd.api_configured_cars(request)) == {"cars": [{
        "id": "IONIQ", "driver": "generic_ev", "battery_kwh": 38, "soc": "sensor.ioniq_ev_battery_level",
        "plugged_in": "binary_sensor.ioniq_ev_battery_plug", "climate": "climate.ioniq",
    }]}
    denied = asyncio.run(wd.api_configured_cars(_FakeRequest(cookies=_cookie(wd, "guest"))))
    assert denied.status_code == 403

    config.write_text(yaml.safe_dump({"evs": [{**car, "id": "Traveller", "battery_kwh": 65}]}), encoding="utf-8")
    updated = asyncio.run(wd.api_configured_cars(request))["cars"]
    assert [(row["id"], row["battery_kwh"]) for row in updated] == [("Traveller", 65)]
    config.write_text("evs: []\n", encoding="utf-8")
    assert asyncio.run(wd.api_configured_cars(request)) == {"cars": []}
    config.write_text("evs: [broken\n", encoding="utf-8")
    assert asyncio.run(wd.api_configured_cars(request)).status_code == 500


def test_save_refused_without_installer_flag(wd, tmp_path, monkeypatch):
    p = tmp_path / "house_config.yaml"
    p.write_text('house_id: "mitt"\n')
    monkeypatch.setattr(wd, "HOUSE_CONFIG_FILE", str(p))
    monkeypatch.delenv("HOUSE_CONFIG_WRITABLE", raising=False)
    st = asyncio.run(wd.api_house_config_status(_FakeRequest(cookies=_cookie(wd))))
    assert st == {"writable": False}
    r = asyncio.run(wd.api_save_house_config(_FakeRequest(SEL, _cookie(wd))))
    assert r.status_code == 409
    assert p.read_text() == 'house_id: "mitt"\n'          # handskriven config rörs aldrig


def test_save_only_for_owner(wd, tmp_path, monkeypatch):
    p = tmp_path / "house_config.yaml"
    p.write_text('house_id: "mitt"\n')
    monkeypatch.setattr(wd, "HOUSE_CONFIG_FILE", str(p))
    monkeypatch.setenv("HOUSE_CONFIG_WRITABLE", "1")
    r = asyncio.run(wd.api_save_house_config(_FakeRequest(SEL, _cookie(wd, "guest"))))
    assert r.status_code == 403
    assert p.read_text() == 'house_id: "mitt"\n'


def test_save_writes_in_place(wd, tmp_path, monkeypatch):
    p = tmp_path / "house_config.yaml"
    p.write_text('house_id: "mitt"\n')
    inode = p.stat().st_ino
    monkeypatch.setattr(wd, "HOUSE_CONFIG_FILE", str(p))
    monkeypatch.setenv("HOUSE_CONFIG_WRITABLE", "1")
    st = asyncio.run(wd.api_house_config_status(_FakeRequest(cookies=_cookie(wd))))
    assert st == {"writable": True}
    r = asyncio.run(wd.api_save_house_config(_FakeRequest(SEL, _cookie(wd))))
    assert r["ok"] is True
    text = p.read_text()
    assert "main_fuse_a" in text
    assert p.stat().st_ino == inode                       # samma fil: Docker-monteringen ser ändringen
    import house_config
    house_config.load_house_config(str(p))                # och motorn kan läsa den


def test_setup_save_preserves_manual_configuration(wd, tmp_path, monkeypatch):
    import yaml
    original = {"house_id": "my-house", "loads": [{"id": "oven", "power_w": 2200}],
                "fuse": {"main_fuse_a": 16, "custom_limit": 12},
                "battery": {"enabled": True, "driver": "generic", "capacity_kwh": 24,
                            "reserve_soc": 35, "control": "av", "normal_max_soc": 85,
                            "entities": {"soc": "sensor.old", "manual": "sensor.custom"}},
                "extensions": {"nested": [1, 2]}}
    p = tmp_path / "house_config.yaml"
    p.write_text(yaml.safe_dump(original), encoding="utf-8")
    inode = p.stat().st_ino
    monkeypatch.setattr(wd, "HOUSE_CONFIG_FILE", str(p))
    monkeypatch.setenv("HOUSE_CONFIG_WRITABLE", "1")
    selected = {**SEL, "battery": {"driver": "generic", "soc_entity": "sensor.new"}}
    r = asyncio.run(wd.api_save_house_config(_FakeRequest(selected, _cookie(wd))))
    assert r["ok"] is True
    saved = yaml.safe_load(p.read_text())
    for key in ("house_id", "loads", "fuse", "extensions"):
        assert saved[key] == original[key]
    for key in ("capacity_kwh", "reserve_soc", "control", "normal_max_soc"):
        assert saved["battery"][key] == original["battery"][key]
    assert saved["battery"]["entities"] == {"soc": "sensor.new", "manual": "sensor.custom"}
    assert p.stat().st_ino == inode


@pytest.mark.parametrize("text", ["loads: [broken", "- not-a-mapping"])
def test_setup_save_refuses_invalid_existing_file(wd, tmp_path, monkeypatch, text):
    p = tmp_path / "house_config.yaml"
    p.write_text(text)
    monkeypatch.setattr(wd, "HOUSE_CONFIG_FILE", str(p))
    monkeypatch.setenv("HOUSE_CONFIG_WRITABLE", "1")
    result = asyncio.run(wd.api_save_house_config(_FakeRequest(SEL, _cookie(wd))))
    assert result.status_code == 409
    assert p.read_text() == text


def test_car_soc_choices_and_save_only_that_line(wd, tmp_path, monkeypatch):
    text = '''house_id: "mitt"   # behåll
evs:
  - id: "IONIQ"
    driver: generic_ev
    battery_kwh: 38
    entities:
      soc: sensor.ioniq_car_battery_level  # 12 V
      plugged_in: binary_sensor.ioniq_plug
    charger:
      entities:
        status: sensor.do_not_touch
  - id: Traveller
    entities:
      soc: sensor.traveller_battery
'''
    config = tmp_path / "house_config.yaml"
    config.write_text(text, encoding="utf-8")
    inode = config.stat().st_ino
    monkeypatch.setattr(wd, "HOUSE_CONFIG_FILE", str(config))
    monkeypatch.setenv("HOUSE_CONFIG_WRITABLE", "1")
    entities = [
        {"e": "sensor.ioniq_car_battery_level", "n": "Car battery level", "d": "car1", "dc": "battery", "u": "%", "st": "12.4"},
        {"e": "sensor.ioniq_ev_battery_level", "n": "EV battery level", "d": "car1", "dc": "battery", "u": "%", "st": "64"},
        {"e": "sensor.other_soc", "n": "Battery", "d": "other", "dc": "battery", "u": "%", "st": "80"},
    ]
    monkeypatch.setattr(wd.discovery, "read_all_entities", lambda: entities)
    owner = _FakeRequest(cookies=_cookie(wd))
    owner.query_params = {"choices": "1"}
    listed = asyncio.run(wd.api_configured_cars(owner))
    assert [row["entity"] for row in listed["cars"][0]["soc_options"]] == [
        "sensor.ioniq_ev_battery_level", "sensor.ioniq_car_battery_level"]
    assert "soc_options" not in asyncio.run(wd.api_configured_cars(_FakeRequest(cookies=_cookie(wd))))["cars"][0]

    saved = asyncio.run(wd.api_set_car_soc(_FakeRequest(
        {"id": "IONIQ", "soc": "sensor.ioniq_ev_battery_level"}, _cookie(wd))))
    assert saved["ok"] is True
    written = config.read_text(encoding="utf-8")
    assert "soc: sensor.ioniq_ev_battery_level  # 12 V" in written
    assert "sensor.ioniq_car_battery_level" not in written
    assert "sensor.traveller_battery" in written and "sensor.do_not_touch" in written and "# behåll" in written
    assert config.stat().st_ino == inode
    again = asyncio.run(wd.api_set_car_soc(_FakeRequest(
        {"id": "IONIQ", "soc": "sensor.ioniq_ev_battery_level"}, _cookie(wd))))
    assert again["message"] == "Laddnivån är redan vald."
    assert config.read_text(encoding="utf-8") == written


def test_car_soc_refuses_other_device_guest_and_locked_file(wd, tmp_path, monkeypatch):
    text = "evs:\n  - id: IONIQ\n    entities:\n      soc: sensor.ioniq_car_battery_level\n"
    config = tmp_path / "house_config.yaml"
    config.write_text(text, encoding="utf-8")
    monkeypatch.setattr(wd, "HOUSE_CONFIG_FILE", str(config))
    monkeypatch.setenv("HOUSE_CONFIG_WRITABLE", "1")
    monkeypatch.setattr(wd.discovery, "read_all_entities", lambda: [
        {"e": "sensor.ioniq_car_battery_level", "n": "Car battery level", "d": "car1", "dc": "battery", "u": "%", "st": "12"},
        {"e": "sensor.ioniq_ev_battery_level", "n": "EV battery level", "d": "car1", "dc": "battery", "u": "%", "st": "64"},
    ])
    other = asyncio.run(wd.api_set_car_soc(_FakeRequest({"id": "IONIQ", "soc": "sensor.other_house"}, _cookie(wd))))
    assert other.status_code == 400
    missing = asyncio.run(wd.api_set_car_soc(_FakeRequest({"id": "saknas", "soc": "sensor.ioniq_ev_battery_level"}, _cookie(wd))))
    assert missing.status_code == 404
    guest = asyncio.run(wd.api_set_car_soc(_FakeRequest({"id": "IONIQ", "soc": "sensor.ioniq_ev_battery_level"}, _cookie(wd, "guest"))))
    assert guest.status_code == 403
    monkeypatch.setattr(wd.discovery, "read_all_entities", lambda: [])
    offline = asyncio.run(wd.api_set_car_soc(_FakeRequest({"id": "IONIQ", "soc": "sensor.ioniq_ev_battery_level"}, _cookie(wd))))
    assert offline.status_code == 409
    assert config.read_text(encoding="utf-8") == text
    monkeypatch.delenv("HOUSE_CONFIG_WRITABLE", raising=False)
    locked = asyncio.run(wd.api_set_car_soc(_FakeRequest({"id": "IONIQ", "soc": "sensor.ioniq_ev_battery_level"}, _cookie(wd))))
    assert locked.status_code == 409
    assert config.read_text(encoding="utf-8") == text


def test_setup_merge_updates_car_fields_and_replaces_changed_driver():
    import house_config
    existing = {"evs": [{"id": "car", "battery_kwh": 75, "manual": True,
                         "charger": {"phases": 1, "max_a": 10}}, {"id": "removed"}],
                "battery": {"driver": "old", "host": "old-device", "modes": {"charge": "old-command"}}}
    new = {"evs": [{"id": "car", "battery_kwh": 60, "charger": {"id": "selected"}}],
           "battery": {"driver": "generic", "enabled": True}}
    merged = house_config.merge_setup_config(existing, new)
    assert merged["evs"] == [{"id": "car", "battery_kwh": 60, "manual": True,
                              "charger": {"phases": 1, "max_a": 10, "id": "selected"}}]
    assert merged["battery"] == new["battery"]
    assert existing["battery"]["host"] == "old-device"
