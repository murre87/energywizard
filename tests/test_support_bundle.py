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


def test_note_and_build_include_ring():
    support_bundle._ring.clear()
    with mock.patch.object(support_bundle, "enabled", return_value=True):
        with mock.patch("logger.get_db", side_effect=Exception("no db")):
            support_bundle.note_error_line("❌ nordpool fail sensor.x")
            out = support_bundle.build("nordpool.fetch", "Error")
    assert "module=nordpool.fetch" in out
    assert "<entitet>" in out
    assert "recent_errors" in out
