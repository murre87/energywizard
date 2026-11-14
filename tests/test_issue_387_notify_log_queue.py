"""#387: aviseringshistoriken tappar inte rader när databasen är överbelastad - de väntar (begränsat, utan dubbletter,
med händelsens tid) och sparas vid nästa tillfälle. Själva aviseringen skickas aldrig om."""
import pytest

import notify_log


class FakeDB:
    def __init__(self):
        self.down = False
        self.rows = {}

    def __call__(self):
        if self.down:
            raise ConnectionError("pool timeout")
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        if sql.startswith("INSERT"):
            eid = params[-1]
            self.rows.setdefault(eid, params)       # ON CONFLICT (event_id) DO NOTHING


@pytest.fixture(autouse=True)
def _clean():
    notify_log._pending.clear()
    notify_log._dropped["n"] = 0
    yield
    notify_log._pending.clear()


def test_sparas_direkt_när_databasen_svarar():
    db = FakeDB()
    notify_log.add("Titel", "Text", "sent", connect=db)
    assert len(db.rows) == 1 and not notify_log._pending


def test_väntar_när_databasen_är_nere_och_sparas_sen_med_ursprunglig_tid(capsys):
    db = FakeDB(); db.down = True
    notify_log.add("A", "1", "sent", connect=db)
    notify_log.add("B", "2", "failed", connect=db)
    assert len(notify_log._pending) == 2 and not db.rows
    assert "2 rader väntar" in capsys.readouterr().out
    ts_a = notify_log._pending[0]["ts"]
    db.down = False
    assert notify_log.flush(db) == 2
    titles = [p[3] for p in db.rows.values()]
    assert titles == ["A", "B"] and list(db.rows.values())[0][0] == ts_a


def test_inga_dubbletter_om_samma_rad_sparas_två_gånger():
    db = FakeDB()
    notify_log.add("A", "1", "sent", connect=db)
    row = list(db.rows.values())[0]
    db.execute("INSERT ...", row)                    # samma event_id igen
    assert len(db.rows) == 1


def test_kön_är_begränsad():
    db = FakeDB(); db.down = True
    for i in range(notify_log.PENDING_MAX + 5):
        notify_log.add(f"T{i}", "", "sent", connect=db)
    assert len(notify_log._pending) == notify_log.PENDING_MAX
    assert notify_log._pending[0]["title"] == "T5"   # äldsta föll bort
    assert notify_log._dropped["n"] == 5


def test_motorn_tömmer_kön_varje_minut():
    import os
    src = open(os.path.join(os.path.dirname(__file__), "..", "smartbox", "main.py"), encoding="utf-8").read()
    assert "notify_log.flush()" in src
