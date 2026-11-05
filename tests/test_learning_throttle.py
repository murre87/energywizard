"""För lite historik ska inte ge ny träning (DB-fråga + loggrad) vid varje anrop (#145)."""
from contextlib import contextmanager

import pandas as pd

import learning


def test_too_little_history_is_not_retrained_every_call(monkeypatch, capsys):
    calls = []

    class Cur:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, *a): pass
        def fetchone(self): return None

    class Conn:
        def cursor(self): return Cur()
        def commit(self): pass

    @contextmanager
    def fake_db():
        yield Conn()

    monkeypatch.setattr(learning.sm_logger, "get_db", fake_db)
    monkeypatch.setattr(learning.pd, "read_sql", lambda *a, **k: calls.append(1) or pd.DataFrame())
    for name in ("_cached_solar_profile", "_solar_too_little_until",
                 "_cached_base_load_profile", "_base_load_too_little_until"):
        monkeypatch.setattr(learning, name, None)
    for _ in range(5):
        assert learning.get_solar_profile() == {}
        assert learning.get_base_load_profile() == {}
    assert len(calls) == 2
    assert capsys.readouterr().out.count("Tränar ML-modell") == 2
