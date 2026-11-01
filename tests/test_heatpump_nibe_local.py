"""NibeLocalHeatPumpDriver: mockar alla HTTPS-anrop helt - rör ALDRIG en riktig pump
(ingen finns i det här projektet). Bevisar bara att koden pratar med det API:et SOM
DET ÄR DOKUMENTERAT (srcfl/ftw:s nibe-local.md + nibe_local.lua-källan), inte att
drivrutinen faktiskt fungerar mot en riktig NIBE S-serie-pump - se modulens egen
docstring för den ärliga avgränsningen (styrning är medvetet inte implementerad)."""
from unittest.mock import MagicMock, patch

import pytest

import drivers.heatpump_nibe_local as nibe_local


@pytest.fixture(autouse=True)
def _configured(monkeypatch):
    monkeypatch.setattr(nibe_local, "_HOST", "10.0.0.50")
    monkeypatch.setattr(nibe_local, "_USERNAME", "user")
    monkeypatch.setattr(nibe_local, "_PASSWORD", "pass")


def _resp(status_code=200, json_data=None):
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = json_data if json_data is not None else {}
    r.raise_for_status = MagicMock()
    if status_code >= 400:
        r.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    return r


def test_detect_serial_anropar_ratt_endpoint():
    driver = nibe_local.NibeLocalHeatPumpDriver()
    devices_resp = _resp(json_data={"data": {"devices": [{"product": {
        "serialNumber": "1234567890", "name": "NIBE S735", "firmwareId": "42", "manufacturer": "NIBE",
    }}]}})
    with patch.object(nibe_local.requests.Session, "get", return_value=devices_resp) as mock_get:
        serial = driver._detect_serial()
    assert serial == "1234567890"
    mock_get.assert_called_once()
    assert mock_get.call_args[0][0] == "https://10.0.0.50:8443/api/v1/devices"


def test_detect_serial_utan_konfiguration_ger_none_inte_krasch(monkeypatch):
    monkeypatch.setattr(nibe_local, "_HOST", "")
    driver = nibe_local.NibeLocalHeatPumpDriver()
    assert driver._detect_serial() is None


def test_read_sensors_las_points_men_normaliserade_falt_ar_overifierade_darfor_none():
    """De normaliserade fälten (indoor_temp m.fl.) ska vara None - vi har ingen
    bekräftad register-karta för dem, så vi gissar inte."""
    driver = nibe_local.NibeLocalHeatPumpDriver()
    driver._serial = "1234567890"
    points_resp = _resp(json_data={
        "40033": {"title": "BT50 Room Temp", "metadata": {"divisor": 10, "modbusRegisterID": 40033}, "value": {"integerValue": 215}},
        "40004": {"title": "BT1 Outdoor Temp", "metadata": {"divisor": 10, "modbusRegisterID": 40004}, "value": {"integerValue": 32}},
    })
    with patch.object(nibe_local.requests.Session, "get", return_value=points_resp):
        result = driver.read_sensors()
    assert result["indoor_temp"] is None
    assert result["outdoor_temp"] is None
    assert result["operating_mode"] is None
    assert result["_raw_point_count"] == 2


def test_read_sensors_utan_serial_ger_tomt_dict():
    driver = nibe_local.NibeLocalHeatPumpDriver()
    with patch.object(nibe_local.requests.Session, "get", side_effect=RuntimeError("timeout")):
        assert driver.read_sensors() == {}


def test_alla_skrivmetoder_ger_false_inte_gissade_kommandon():
    """Kärnan i drivrutinens ärlighetsprincip: ingen bekräftad register-karta för
    styrning -> inget skrivs, aldrig en gissning."""
    driver = nibe_local.NibeLocalHeatPumpDriver()
    assert driver.set_room_temp(21.0) is False
    assert driver.set_water_stop_temp(45.0) is False
    assert driver.set_water_start_temp(40.0) is False
    assert driver.set_heating_start_temp(17.0) is False
    assert driver.set_operating_mode("heat") is False


def test_pinned_cert_adapter_satter_fingerprint_istallet_for_att_sla_av_verifiering():
    adapter = nibe_local._PinnedCertAdapter("AA:BB:CC")
    conn = MagicMock()
    with patch.object(nibe_local.requests.adapters.HTTPAdapter, "cert_verify") as mock_super:
        adapter.cert_verify(conn, "https://10.0.0.50:8443", True, None)
    mock_super.assert_called_once()
    assert mock_super.call_args.kwargs["verify"] is False
    assert conn.assert_fingerprint == "aabbcc"
