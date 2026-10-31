"""set_nordpool_vat(): HA:s nordpool-integration saknar OptionsFlow/reconfigure (verifierat
i dess egen config_flow.py), så enda vägen att ändra VAT är radera+återskapa config entry via
HA:s config-flow-REST-API. Bevisar att övriga fält bevaras, att radera-lyckas-men-skapa-
misslyckas loggas KRITISKT (inte tyst), och att verifieringssteget väntar in sensorn. Mockar
requests helt - rör aldrig en riktig Home Assistant."""
from unittest.mock import MagicMock, patch

import homeassistant


_ENTRY = {
    "entry_id": "dbba443ae42b48a8589a1a26edea1c2e",
    "data": {
        "VAT": True,
        "additional_costs": "{{0.0|float}}",
        "currency": "SEK",
        "low_price_cutoff": 1.0,
        "precision": 3,
        "price_in_cents": False,
        "price_type": "kWh",
        "region": "SE3",
    },
}


def _resp(status_code=200, json_data=None):
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = json_data or {}
    r.raise_for_status = MagicMock()
    if status_code >= 400:
        r.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    return r


def test_get_nordpool_config_returnerar_forsta_traffen():
    with patch("homeassistant.requests.get", return_value=_resp(json_data=[_ENTRY])):
        cfg = homeassistant.get_nordpool_config()
    assert cfg == _ENTRY


def test_get_nordpool_config_tom_lista_ger_tomt_dict():
    with patch("homeassistant.requests.get", return_value=_resp(json_data=[])):
        assert homeassistant.get_nordpool_config() == {}


def test_lyckad_vaxling_bevarar_ovriga_falt_och_togglar_bara_vat():
    with patch("homeassistant.requests.get") as mock_get, \
         patch("homeassistant.requests.delete", return_value=_resp()) as mock_del, \
         patch("homeassistant.requests.post") as mock_post, \
         patch("homeassistant.time.sleep"):
        mock_get.side_effect = [
            _resp(json_data=[_ENTRY]),                         # get_nordpool_config
            _resp(json_data={"state": "2.05"}),                # verifieringspoll efteråt
        ]
        mock_post.side_effect = [
            _resp(json_data={"flow_id": "abc123"}),             # starta flow
            _resp(json_data={"type": "create_entry"}),          # skicka in data
        ]

        ok = homeassistant.set_nordpool_vat(False)

    assert ok is True
    mock_del.assert_called_once_with(
        f"{homeassistant._BASE}/config/config_entries/entry/dbba443ae42b48a8589a1a26edea1c2e",
        headers=homeassistant._HEADERS, timeout=10, verify=homeassistant._VERIFY,
    )
    flow_call, create_call = mock_post.call_args_list
    assert flow_call.kwargs["json"] == {"handler": "nordpool"}
    sent_data = create_call.kwargs["json"]
    assert sent_data["VAT"] is False
    # Alla andra fält oförändrade.
    for k, val in _ENTRY["data"].items():
        if k != "VAT":
            assert sent_data[k] == val


def test_entry_hittas_inte_ger_false_utan_att_radera_nagot():
    with patch("homeassistant.requests.get", return_value=_resp(json_data=[])), \
         patch("homeassistant.requests.delete") as mock_del:
        assert homeassistant.set_nordpool_vat(True) is False
    mock_del.assert_not_called()


def test_radering_misslyckas_ger_false():
    with patch("homeassistant.requests.get", return_value=_resp(json_data=[_ENTRY])), \
         patch("homeassistant.requests.delete", return_value=_resp(status_code=500)):
        assert homeassistant.set_nordpool_vat(True) is False


def test_skapande_misslyckas_efter_lyckad_radering_ger_false_kritiskt():
    """Värsta fallet: gamla raderad, nya kunde inte skapas - sensor.nordpool saknas helt.
    Måste returnera False (aldrig krascha main-loopen) så anroparen kan larma tydligt."""
    with patch("homeassistant.requests.get", return_value=_resp(json_data=[_ENTRY])), \
         patch("homeassistant.requests.delete", return_value=_resp()), \
         patch("homeassistant.requests.post", return_value=_resp(status_code=500)):
        assert homeassistant.set_nordpool_vat(True) is False


def test_verifiering_tar_nagra_forsok_innan_sensorn_svarar():
    with patch("homeassistant.requests.get") as mock_get, \
         patch("homeassistant.requests.delete", return_value=_resp()), \
         patch("homeassistant.requests.post") as mock_post, \
         patch("homeassistant.time.sleep"):
        mock_get.side_effect = [
            _resp(json_data=[_ENTRY]),             # get_nordpool_config
            _resp(status_code=404),                # verifiering 1: inte uppe än
            _resp(status_code=404),                # verifiering 2: inte uppe än
            _resp(json_data={"state": "2.05"}),    # verifiering 3: uppe
        ]
        mock_post.side_effect = [
            _resp(json_data={"flow_id": "abc123"}),
            _resp(json_data={"type": "create_entry"}),
        ]
        ok = homeassistant.set_nordpool_vat(True)
    assert ok is True


def test_verifiering_ger_upp_efter_max_forsok():
    with patch("homeassistant.requests.get") as mock_get, \
         patch("homeassistant.requests.delete", return_value=_resp()), \
         patch("homeassistant.requests.post") as mock_post, \
         patch("homeassistant.time.sleep"):
        mock_get.side_effect = [_resp(json_data=[_ENTRY])] + [_resp(status_code=404)] * 6
        mock_post.side_effect = [
            _resp(json_data={"flow_id": "abc123"}),
            _resp(json_data={"type": "create_entry"}),
        ]
        ok = homeassistant.set_nordpool_vat(True)
    assert ok is False
