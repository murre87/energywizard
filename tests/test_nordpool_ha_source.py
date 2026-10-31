"""Nord Pool-källbyte (opt-in): bevisar att fetch_ha_nordpool_and_save() parsar HA:s
sensor.nordpool-attribut korrekt och skriver samma (time_start, time_end, sek_per_kwh)-rader
som den befintliga fetch_api_and_save() - mot ett syntetiskt HA-svar, aldrig nätverket eller
riktig produktionsdata. Paritet mot den RIKTIGA källan (markup/moms kan skilja) verifieras
separat med scripts/compare_price_sources.py mot riktig data, inte här."""
from datetime import datetime
from unittest.mock import MagicMock, patch

import nordpool

# ensure_prices_exist() ger alltid ett tidszon-medvetet datetime (via now.replace(...)),
# aldrig ett bart date - testerna speglar det riktiga anropsmönstret.
_DAY = datetime(2026, 10, 31, tzinfo=nordpool.SWE_TZ)


def _ha_response(raw_today, raw_tomorrow=None):
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = {"attributes": {"raw_today": raw_today, "raw_tomorrow": raw_tomorrow or []}}
    return r


def test_sparar_dagens_rader_fran_raw_today():
    raw_today = [
        {"start": "2026-10-31T00:00:00+01:00", "end": "2026-10-31T00:15:00+01:00", "value": 0.45},
        {"start": "2026-10-31T00:15:00+01:00", "end": "2026-10-31T00:30:00+01:00", "value": 0.46},
    ]
    with patch("nordpool.requests.get", return_value=_ha_response(raw_today)) as mock_get, \
         patch("nordpool.get_db") as mock_get_db:
        conn = MagicMock()
        mock_get_db.return_value.__enter__.return_value = conn
        cur = conn.cursor.return_value.__enter__.return_value

        ok = nordpool.fetch_ha_nordpool_and_save(_DAY)

    assert ok is True
    mock_get.assert_called_once()
    assert cur.executemany.call_count == 1
    sql, records = cur.executemany.call_args[0]
    assert "INSERT INTO elpriser" in sql
    assert "ON CONFLICT (time_start) DO NOTHING" in sql
    assert records == [
        ("2026-10-31T00:00:00+01:00", "2026-10-31T00:15:00+01:00", 0.45),
        ("2026-10-31T00:15:00+01:00", "2026-10-31T00:30:00+01:00", 0.46),
    ]
    conn.commit.assert_called_once()


def test_filtrerar_bort_rader_for_fel_dygn():
    """raw_today + raw_tomorrow slås ihop - funktionen måste själv filtrera till det
    efterfrågade dygnet, annars blandas morgondagens rader in vid ett anrop för idag."""
    raw_today = [{"start": "2026-10-31T23:45:00+01:00", "end": "2026-11-01T00:00:00+01:00", "value": 0.30}]
    raw_tomorrow = [{"start": "2026-11-01T00:00:00+01:00", "end": "2026-11-01T00:15:00+01:00", "value": 0.31}]
    with patch("nordpool.requests.get", return_value=_ha_response(raw_today, raw_tomorrow)), \
         patch("nordpool.get_db") as mock_get_db:
        conn = MagicMock()
        mock_get_db.return_value.__enter__.return_value = conn
        cur = conn.cursor.return_value.__enter__.return_value

        nordpool.fetch_ha_nordpool_and_save(_DAY)

    _, records = cur.executemany.call_args[0]
    assert len(records) == 1
    assert records[0][0] == "2026-10-31T23:45:00+01:00"


def test_ha_svar_fel_statuskod_ger_false():
    r = MagicMock()
    r.status_code = 503
    with patch("nordpool.requests.get", return_value=r):
        assert nordpool.fetch_ha_nordpool_and_save(_DAY) is False


def test_tomt_raw_today_ger_false():
    with patch("nordpool.requests.get", return_value=_ha_response([])):
        assert nordpool.fetch_ha_nordpool_and_save(_DAY) is False


def test_natverksfel_ger_false_inte_krasch():
    with patch("nordpool.requests.get", side_effect=RuntimeError("timeout")):
        assert nordpool.fetch_ha_nordpool_and_save(_DAY) is False


# ---------- _fetch_and_save: källval + fallback ----------

def test_default_kalla_anvander_elprisetjustnu_direkt(monkeypatch):
    monkeypatch.setattr(nordpool, "PRICE_SOURCE", "elprisetjustnu")
    with patch("nordpool.fetch_api_and_save", return_value=True) as mock_old, \
         patch("nordpool.fetch_ha_nordpool_and_save") as mock_ha:
        assert nordpool._fetch_and_save(_DAY) is True
    mock_old.assert_called_once()
    mock_ha.assert_not_called()


def test_ha_kalla_lyckas_anropar_inte_fallback(monkeypatch):
    monkeypatch.setattr(nordpool, "PRICE_SOURCE", "ha_nordpool")
    with patch("nordpool.fetch_ha_nordpool_and_save", return_value=True) as mock_ha, \
         patch("nordpool.fetch_api_and_save") as mock_old:
        assert nordpool._fetch_and_save(_DAY) is True
    mock_ha.assert_called_once()
    mock_old.assert_not_called()


def test_ha_kalla_misslyckas_faller_tillbaka_samma_cykel(monkeypatch):
    monkeypatch.setattr(nordpool, "PRICE_SOURCE", "ha_nordpool")
    with patch("nordpool.fetch_ha_nordpool_and_save", return_value=False) as mock_ha, \
         patch("nordpool.fetch_api_and_save", return_value=True) as mock_old:
        assert nordpool._fetch_and_save(_DAY) is True
    mock_ha.assert_called_once()
    mock_old.assert_called_once()
