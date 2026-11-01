"""MyUplinkHeatPumpDriver: mockar alla HTTP-anrop helt - rör ALDRIG ett riktigt
myUplink-konto (inget finns i det här projektet). Bevisar bara att koden pratar
med API:et SOM DET ÄR DOKUMENTERAT (myUplinks egen swagger-spec + två oberoende,
community-rapporterade PATCH-anrop) - se modulens egen docstring för källorna och
den ärliga avgränsningen kring PATCH-kroppens form."""
import time
from unittest.mock import MagicMock, patch

import pytest

import drivers.heatpump_myuplink as myuplink


@pytest.fixture(autouse=True)
def _configured(monkeypatch):
    monkeypatch.setattr(myuplink, "_CLIENT_ID", "client")
    monkeypatch.setattr(myuplink, "_CLIENT_SECRET", "secret")
    monkeypatch.setattr(myuplink, "_REFRESH_TOKEN", "refresh-abc")
    monkeypatch.setattr(myuplink, "_DEVICE_ID", "device-123")


def _resp(status_code=200, json_data=None):
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = json_data if json_data is not None else {}
    r.raise_for_status = MagicMock()
    if status_code >= 400:
        r.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    return r


def test_refresh_access_token_anropar_ratt_endpoint_med_ratt_falt():
    driver = myuplink.MyUplinkHeatPumpDriver()
    token_resp = _resp(json_data={"access_token": "tok-1", "expires_in": 3600})
    with patch.object(myuplink.requests, "post", return_value=token_resp) as mock_post:
        token = driver._refresh_access_token()
    assert token == "tok-1"
    mock_post.assert_called_once_with(
        "https://api.myuplink.com/oauth/token",
        data={"grant_type": "refresh_token", "refresh_token": "refresh-abc",
              "client_id": "client", "client_secret": "secret"},
        timeout=10,
    )


def test_refresh_access_token_utan_konfiguration_ger_none(monkeypatch):
    monkeypatch.setattr(myuplink, "_CLIENT_ID", "")
    driver = myuplink.MyUplinkHeatPumpDriver()
    assert driver._refresh_access_token() is None


def test_refresh_access_token_natverksfel_ger_none_inte_krasch():
    driver = myuplink.MyUplinkHeatPumpDriver()
    with patch.object(myuplink.requests, "post", side_effect=RuntimeError("timeout")):
        assert driver._refresh_access_token() is None


def test_read_sensors_mappar_bara_konfigurerade_falt():
    driver = myuplink.MyUplinkHeatPumpDriver(entities={"indoor_temp": "40033", "room_target": "47398"})
    driver._access_token = "tok-1"
    driver._token_expiry = time.time() + 3600
    points_resp = _resp(json_data=[
        {"parameterId": "40033", "parameterName": "BT50 Room Temp", "value": 21.5, "writable": False},
        {"parameterId": "47398", "parameterName": "Room setpoint", "value": 21.0, "writable": True},
        {"parameterId": "99999", "parameterName": "Irrelevant", "value": 1, "writable": False},
    ])
    with patch.object(myuplink.requests, "get", return_value=points_resp) as mock_get:
        result = driver.read_sensors()
    assert result["indoor_temp"] == 21.5
    assert result["outdoor_temp"] is None  # inte konfigurerad -> None, ingen gissning
    assert driver._writable["room_target"] is True
    mock_get.assert_called_once()
    assert mock_get.call_args[0][0] == "https://api.myuplink.com/v2/devices/device-123/points"
    assert mock_get.call_args.kwargs["headers"]["Authorization"] == "Bearer tok-1"


def test_read_sensors_utan_konfigurerade_entiteter_ger_alla_none_ingen_api_anrop():
    driver = myuplink.MyUplinkHeatPumpDriver()
    with patch.object(myuplink.requests, "get") as mock_get:
        result = driver.read_sensors()
    assert all(v is None for v in result.values())
    mock_get.assert_not_called()


def test_set_room_temp_skriver_bara_om_punkten_var_markerad_skrivbar():
    driver = myuplink.MyUplinkHeatPumpDriver(entities={"room_target": "47398"})
    driver._access_token = "tok-1"
    driver._token_expiry = time.time() + 3600
    driver._writable["room_target"] = True
    patch_resp = _resp(json_data={"47398": "modified"})
    with patch.object(myuplink.requests, "patch", return_value=patch_resp) as mock_patch:
        ok = driver.set_room_temp(21.0)
    assert ok is True
    mock_patch.assert_called_once()
    assert mock_patch.call_args[0][0] == "https://api.myuplink.com/v2/devices/device-123/points"
    assert mock_patch.call_args.kwargs["json"] == {"47398": "21.0"}


def test_set_room_temp_nekas_om_punkten_inte_var_skrivbar_vid_senaste_lasning():
    driver = myuplink.MyUplinkHeatPumpDriver(entities={"room_target": "47398"})
    driver._writable["room_target"] = False
    with patch.object(myuplink.requests, "patch") as mock_patch:
        assert driver.set_room_temp(21.0) is False
    mock_patch.assert_not_called()


def test_set_room_temp_nekas_utan_konfigurerad_punkt():
    driver = myuplink.MyUplinkHeatPumpDriver()
    assert driver.set_room_temp(21.0) is False


def test_set_operating_mode_ger_alltid_false_inte_gissat_parameterid():
    driver = myuplink.MyUplinkHeatPumpDriver(entities={"room_target": "47398"})
    assert driver.set_operating_mode("heat") is False
