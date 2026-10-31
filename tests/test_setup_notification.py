"""homeassistant.get_own_base_url()/send_persistent_notification(): grunden för
main.py:s engångs-notis i HA:s eget notisfält vid en ny, i princip tom installation
(se main.py - ingen hourly-timer, en vanlig persistent_notification istället).
Mockar requests helt - rör aldrig en riktig Home Assistant."""
from unittest.mock import MagicMock, patch

import homeassistant


def _resp(status_code=200, json_data=None):
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = json_data if json_data is not None else {}
    r.raise_for_status = MagicMock()
    if status_code >= 400:
        r.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    return r


def test_get_own_base_url_foredrar_internal_url():
    with patch("homeassistant.requests.get", return_value=_resp(json_data={
        "internal_url": "https://192.168.1.109:8123", "external_url": "https://murrehtpc.axfors.se:8123",
    })):
        assert homeassistant.get_own_base_url() == "https://192.168.1.109:8123"


def test_get_own_base_url_faller_tillbaka_pa_external_url():
    with patch("homeassistant.requests.get", return_value=_resp(json_data={
        "internal_url": None, "external_url": "https://murrehtpc.axfors.se:8123",
    })):
        assert homeassistant.get_own_base_url() == "https://murrehtpc.axfors.se:8123"


def test_get_own_base_url_natverksfel_ger_none_inte_krasch():
    with patch("homeassistant.requests.get", side_effect=RuntimeError("timeout")):
        assert homeassistant.get_own_base_url() is None


def test_send_persistent_notification_anropar_ratt_tjanst():
    with patch("homeassistant.requests.post", return_value=_resp()) as mock_post:
        ok = homeassistant.send_persistent_notification("energywizard_setup", "Titel", "Meddelande")
    assert ok is True
    mock_post.assert_called_once_with(
        f"{homeassistant._BASE}/services/persistent_notification/create",
        headers=homeassistant._HEADERS,
        json={"notification_id": "energywizard_setup", "title": "Titel", "message": "Meddelande"},
        timeout=5, verify=homeassistant._VERIFY,
    )


def test_send_persistent_notification_fel_ger_false_inte_krasch():
    with patch("homeassistant.requests.post", side_effect=RuntimeError("fel")):
        assert homeassistant.send_persistent_notification("id", "t", "m") is False
