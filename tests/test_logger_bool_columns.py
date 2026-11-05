"""sensor_log-flaggor är SMALLINT: bool från drivrutinerna måste bli 0/1 (issue #145)."""
from contextlib import contextmanager

import logger


def test_bool_pump_flags_are_logged_as_smallint(monkeypatch):
    seen = {}

    class Cur:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, sql, values=None):
            if sql.startswith("INSERT INTO sensor_log"):
                cols = sql.split("(", 1)[1].split(")", 1)[0].split(", ")
                seen.update(zip(cols, values))

    class Conn:
        def cursor(self): return Cur()
        def commit(self): pass

    @contextmanager
    def fake_db():
        yield Conn()

    monkeypatch.setattr(logger, "get_db", fake_db)
    monkeypatch.setattr(logger, "_ensure_car_column", lambda *a: None, raising=False)
    logger.log_status(1.0, 21.0, 50.0, 21.0, "normal", 30.0, 25.0, 30.0, -3.0,
                      1, 1, 1, 3, 0, 0, 0, 0, 0, 0, 0,
                      pump={"compressor_running": True, "pump_heat_running": False})
    assert seen["compressor_running"] == 1 and type(seen["compressor_running"]) is int
    assert seen["pump_heat_running"] == 0 and type(seen["pump_heat_running"]) is int
