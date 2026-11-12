"""#227: sanerat supportutdrag, på som standard."""
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "smartbox"))
import support_bundle  # noqa: E402


def test_sanitize_strips_entities_and_ips():
    t = support_bundle.sanitize("Fel på sensor.garage_temp från 192.168.1.10 /home/emil/opt/x")
    assert "sensor." not in t
    assert "192.168" not in t
    assert "/home/emil" not in t
    assert "<entitet>" in t and "<ip>" in t


def test_enabled_defaults_on_when_unset():
    import ew_settings
    with mock.patch.object(ew_settings, "get", return_value=None):
        assert support_bundle.enabled() is True
    with mock.patch.object(ew_settings, "get", return_value=False):
        assert support_bundle.enabled() is False
    with mock.patch.object(ew_settings, "get", return_value="off"):
        assert support_bundle.enabled() is False


def test_build_empty_when_disabled():
    support_bundle._ring.clear()
    with mock.patch.object(support_bundle, "enabled", return_value=False):
        assert support_bundle.build("m", "E") == ""


def test_ftw_pollfel_tar_med_lua_text_utan_adress(monkeypatch):
    """#297: Lua-felet ska synas i supportutdraget. Adress och sökväg ska inte följa med till ärendet."""
    from drivers.ftw_device import note_poll_failure, poll_failure_note
    support_bundle._ring.clear()
    exc = RuntimeError(
        '[string "/app/smartbox/ftw_drivers/deye-svk.lua"]:353: '
        "attempt to perform arithmetic on a nil value (192.168.1.50)")
    line = poll_failure_note("deye-svk", "192.168.1.50", exc)
    assert "deye-svk.lua" in line and "nil value" in line
    assert "192.168" not in line and "/app/" not in line and "<värd>" in line
    seen = {}

    def fake_report(cfg, module, kind):
        seen["module"] = module
        seen["kind"] = kind
        seen["excerpt"] = support_bundle.build(module, kind)

    monkeypatch.setattr("telemetry.report_error", fake_report)
    with mock.patch.object(support_bundle, "enabled", return_value=True):
        with mock.patch("logger.get_db", side_effect=Exception("no db")):
            note_poll_failure("deye-svk", "192.168.1.50", exc)
    assert seen["module"] == "ftw_deye-svk.poll" and seen["kind"] == "RuntimeError"
    assert "nil value" in seen["excerpt"] and "192.168" not in seen["excerpt"]


def test_note_and_build_include_ring():
    support_bundle._ring.clear()
    with mock.patch.object(support_bundle, "enabled", return_value=True):
        with mock.patch("logger.get_db", side_effect=Exception("no db")):
            support_bundle.note_error_line("❌ nordpool fail sensor.x")
            out = support_bundle.build("nordpool.fetch", "Error")
    assert "module=nordpool.fetch" in out
    assert "<entitet>" in out
    assert "recent_errors" in out
