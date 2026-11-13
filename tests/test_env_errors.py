"""Full disk och databasen nere: användarens miljö, aldrig ett felärende (Emil 2026-11-13)."""
import builtins
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "smartbox"))
import env_errors  # noqa: E402


def test_klassning():
    for t in ("DiskFull", "PoolTimeout", "OperationalError"):
        assert env_errors.is_env(t)
    assert not env_errors.is_env("TypeError")
    assert env_errors.is_env_key("logger.log_status: DiskFull")
    assert not env_errors.is_env_key("gpm.evaluate: TypeError")


def test_ingen_rapport_men_besked(monkeypatch):
    import telemetry
    sent, noted = [], []
    monkeypatch.setattr(telemetry, "report_error", lambda *a: sent.append(a))
    monkeypatch.setattr(env_errors, "note", lambda t: noted.append(t))
    monkeypatch.setattr(telemetry, "OPT_IN", True)
    orig = builtins.print
    try:
        telemetry.install_error_hook({})
        try:
            raise type("PoolTimeout", (Exception,), {})("couldn't get a connection after 30.00 sec")
        except Exception as e:
            print(f"❌ get_all_overrides(): {e}")
        try:
            raise type("TypeError", (Exception,), {})("x")
        except Exception:
            print("❌ något gick fel")
    finally:
        builtins.print = orig
    import time
    time.sleep(0.3)
    assert noted == ["PoolTimeout"]
    assert len(sent) == 1 and sent[0][2] == "TypeError"


def test_samlaren_listar_samma_typer():
    src = (ROOT / "telemetry-collector/app.py").read_text()
    for t in env_errors.TYPES:
        assert f'"{t}"' in src, t


def test_husets_logg_visar_varning():
    import ew_journal
    assert ew_journal.level_of("❌ get_settings: couldn't get a connection after 30.00 sec") == "varning"
    assert ew_journal.level_of("❌ Fel vid loggning till databas: DiskFull") == "varning"
    assert ew_journal.level_of("❌ något annat") == "fel"
