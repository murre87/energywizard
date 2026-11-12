"""Nord Pool-källbyte (opt-in): bevisar att fetch_ha_nordpool_and_save() parsar HA:s
sensor.nordpool-attribut korrekt och skriver samma (time_start, time_end, sek_per_kwh)-rader
som den befintliga fetch_api_and_save() - mot ett syntetiskt HA-svar, aldrig nätverket eller
riktig produktionsdata. Paritet mot den RIKTIGA källan (markup/moms kan skilja) verifieras
separat med scripts/compare_price_sources.py mot riktig data, inte här."""
import time
from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
import requests

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


@pytest.mark.parametrize("error", [requests.ConnectionError, requests.Timeout])
def test_transport_failure_warns_without_writing_or_caching(error, capsys, monkeypatch):
    monkeypatch.setattr(nordpool, "_ha_refresh_state", {})
    with patch("nordpool.requests.get", side_effect=error("HA unavailable")), \
         patch("nordpool.get_db") as db:
        assert nordpool.fetch_ha_nordpool_and_save(_DAY) is False
    db.assert_not_called()
    assert nordpool._ha_refresh_state == {}
    output = capsys.readouterr().out
    assert "⚠️" in output and "HA unavailable" in output
    assert "❌" not in output


@pytest.mark.parametrize("failed_index", [0, 1])
def test_transport_failure_keeps_prices_from_other_sensor(failed_index, monkeypatch):
    entities = ["sensor.octopus_current_day_rates", "sensor.octopus_next_day_rates"]
    monkeypatch.setattr(nordpool, "_price_entities", lambda: entities)
    monkeypatch.setattr(nordpool, "_ha_refresh_state", {})
    row = {"start": "2026-10-31T00:00:00+01:00", "end": "2026-10-31T00:15:00+01:00", "value": 0.45}
    responses = [_ha_response([row]), _ha_response([row])]
    responses[failed_index] = requests.ConnectionError("HA unavailable")
    with patch("nordpool.requests.get", side_effect=responses) as get, \
         patch("nordpool.get_db") as db:
        assert nordpool.fetch_ha_nordpool_and_save(_DAY) is True
    assert get.call_count == 2
    conn = db.return_value.__enter__.return_value
    records = conn.cursor.return_value.__enter__.return_value.executemany.call_args[0][1]
    assert records == [(row["start"], row["end"], row["value"])]
    conn.commit.assert_called_once()


def test_transport_failure_recovers_on_next_call(monkeypatch):
    monkeypatch.setattr(nordpool, "_ha_refresh_state", {})
    row = {"start": "2026-10-31T00:00:00+01:00", "end": "2026-10-31T00:15:00+01:00", "value": 0.45}
    with patch("nordpool.requests.get", side_effect=[requests.ConnectionError("HA unavailable"), _ha_response([row])]), \
         patch("nordpool.get_db") as db:
        assert nordpool.fetch_ha_nordpool_and_save(_DAY) is False
        assert nordpool._ha_refresh_state == {}
        db.assert_not_called()
        assert nordpool.fetch_ha_nordpool_and_save(_DAY) is True
        assert nordpool._ha_refresh_state


@pytest.mark.parametrize("country, fallback_calls", [("SE", 1), ("CZ", 0), ("AU", 0)])
def test_transport_failure_preserves_country_fallback(country, fallback_calls, monkeypatch):
    monkeypatch.setattr(nordpool, "price_source", lambda: "ha_nordpool")
    monkeypatch.setattr(nordpool, "cost_settings", lambda: {"country": country})
    with patch("nordpool.requests.get", side_effect=requests.ConnectionError("HA unavailable")), \
         patch("nordpool.fetch_api_and_save", return_value=True) as fallback, \
         patch("nordpool.get_db") as db:
        assert nordpool._fetch_and_save(_DAY) is (country == "SE")
    assert fallback.call_count == fallback_calls
    db.assert_not_called()


def test_ha_avhugget_svar_ar_varning(capsys, monkeypatch):
    monkeypatch.setattr(nordpool, "_ha_refresh_state", {})
    with patch("nordpool.requests.get", side_effect=requests.exceptions.ChunkedEncodingError("cut")), \
         patch("nordpool.get_db") as db:
        assert nordpool.fetch_ha_nordpool_and_save(_DAY) is False
    db.assert_not_called()
    out = capsys.readouterr().out
    assert "⚠️" in out and "❌" not in out


def test_unexpected_failure_still_reports_error(capsys):
    with patch("nordpool.requests.get", side_effect=RuntimeError("unexpected defect")), \
         patch("nordpool.get_db") as db:
        assert nordpool.fetch_ha_nordpool_and_save(_DAY) is False
    db.assert_not_called()
    assert "❌" in capsys.readouterr().out


def test_invalid_json_from_ha_warns_not_error(capsys):
    r = MagicMock()
    r.status_code = 200
    r.json.side_effect = ValueError("No JSON")
    with patch("nordpool.requests.get", return_value=r), patch("nordpool.get_db") as db:
        assert nordpool.fetch_ha_nordpool_and_save(_DAY) is False
    db.assert_not_called()
    out = capsys.readouterr().out
    assert "⚠️" in out and "❌" not in out


def test_missing_today_prices_warns_not_program_error(monkeypatch, capsys):
    """#210: KRITISKT utan exception ska inte bli Admin-gruppen Error via ❌."""
    monkeypatch.setattr(nordpool, "price_source", lambda: "ha_nordpool")
    monkeypatch.setattr(nordpool, "price_timezone", lambda: ZoneInfo("Europe/Stockholm"))
    monkeypatch.setattr(nordpool, "_ha_source_key", lambda: "k")
    monkeypatch.setattr(nordpool, "_ha_refresh_state", {"k": (time.monotonic(), False)})
    monkeypatch.setattr(
        nordpool, "cost_settings",
        lambda: {"country": "SE", "area": "SE3", "timezone": "Europe/Stockholm"})
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = (0,)
    fixed = datetime(2026, 11, 12, 10, 0, tzinfo=ZoneInfo("Europe/Stockholm"))
    with patch("nordpool.get_db") as db, \
         patch("nordpool._fetch_and_save", return_value=False), \
         patch("nordpool.datetime") as dt:
        db.return_value.__enter__.return_value = conn
        dt.now.return_value = fixed
        nordpool.ensure_prices_exist()
    out = capsys.readouterr().out
    assert "KRITISKT" in out and "⚠️" in out
    assert "❌" not in out


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
