"""set_nordpool_vat(): HA:s nordpool-integration saknar OptionsFlow/reconfigure (verifierat
i dess egen config_flow.py), så enda vägen att ändra VAT är radera+återskapa config entry via
HA:s config-flow-REST-API. HA:s GET /api/config/config_entries/entry exponerar BARA metadata,
aldrig entry.data (bekräftat live mot riktig HA under utveckling - en första version av den
här koden antog fel) - så region/currency/price_in_cents rekonstrueras istället från
sensor.nordpool:s publika attribut, och resten sätts till integrationens egna schema-defaults.
VAT:s nuvarande värde går inte att läsa tillbaka alls. Mockar requests helt - rör aldrig en
riktig Home Assistant."""
from unittest.mock import MagicMock, patch

import homeassistant


_ENTRY_META = [{"entry_id": "dbba443ae42b48a8589a1a26edea1c2e", "domain": "nordpool", "title": "Nordpool"}]
_SENSOR_ATTRS = {
    "region": "SE3", "currency": "SEK", "price_in_cents": False,
    "additional_costs_current_hour": 0.0, "unit_of_measurement": "SEK/kWh",
}


def _resp(status_code=200, json_data=None):
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = json_data if json_data is not None else {}
    r.raise_for_status = MagicMock()
    if status_code >= 400:
        r.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    return r


def _sensor_resp(attrs=None):
    return _resp(json_data={"attributes": attrs if attrs is not None else _SENSOR_ATTRS})


# ---------- get_nordpool_config ----------

def test_rekonstruerar_fran_sensorattribut_inte_fran_entry_data():
    with patch("homeassistant.requests.get") as mock_get:
        mock_get.side_effect = [_resp(json_data=_ENTRY_META), _sensor_resp()]
        cfg = homeassistant.get_nordpool_config()
    assert cfg["entry_id"] == "dbba443ae42b48a8589a1a26edea1c2e"
    assert cfg["region"] == "SE3"
    assert cfg["currency"] == "SEK"
    assert cfg["price_in_cents"] is False
    assert "VAT" not in cfg  # kan aldrig läsas tillbaka - får inte gissas fram


def test_entry_hittas_inte_ger_tomt_dict():
    with patch("homeassistant.requests.get", return_value=_resp(json_data=[])):
        assert homeassistant.get_nordpool_config() == {}


def test_sensorn_svarar_inte_ger_tomt_dict():
    with patch("homeassistant.requests.get") as mock_get:
        mock_get.side_effect = [_resp(json_data=_ENTRY_META), _resp(status_code=404)]
        assert homeassistant.get_nordpool_config() == {}


# ---------- set_nordpool_vat ----------

def test_lyckad_vaxling_anvander_rekonstruerade_falt_och_schema_defaults():
    with patch("homeassistant.requests.get") as mock_get, \
         patch("homeassistant.requests.delete", return_value=_resp()) as mock_del, \
         patch("homeassistant.requests.post") as mock_post, \
         patch("homeassistant.time.sleep"):
        mock_get.side_effect = [
            _resp(json_data=_ENTRY_META),      # _nordpool_entry_id
            _sensor_resp(),                    # get_nordpool_config: sensor.nordpool
            _sensor_resp(),                    # verifieringspoll efteråt
        ]
        mock_post.side_effect = [
            _resp(json_data={"flow_id": "abc123"}),
            _resp(json_data={"type": "create_entry"}),
        ]

        ok = homeassistant.set_nordpool_vat(False)

    assert ok is True
    mock_del.assert_called_once_with(
        f"{homeassistant._BASE}/config/config_entries/entry/dbba443ae42b48a8589a1a26edea1c2e",
        headers=homeassistant._HEADERS, timeout=10, verify=homeassistant._VERIFY,
    )
    flow_call, create_call = mock_post.call_args_list
    assert flow_call.kwargs["json"] == {"handler": "nordpool"}
    sent = create_call.kwargs["json"]
    assert sent["VAT"] is False
    assert sent["region"] == "SE3"
    assert sent["currency"] == "SEK"
    assert sent["price_in_cents"] is False
    assert sent["precision"] == homeassistant._NORDPOOL_DEFAULT_PRECISION
    assert sent["additional_costs"] == homeassistant._NORDPOOL_DEFAULT_ADDITIONAL_COSTS


def test_vagrar_vaxla_om_anpassad_avgift_skulle_tappas_bort():
    """additional_costs_current_hour != 0 tyder på en anpassad mall vi inte kan återskapa -
    måste vägra, inte tyst nolla ut den."""
    attrs = dict(_SENSOR_ATTRS, additional_costs_current_hour=0.35)
    with patch("homeassistant.requests.get") as mock_get, \
         patch("homeassistant.requests.delete") as mock_del:
        mock_get.side_effect = [_resp(json_data=_ENTRY_META), _sensor_resp(attrs)]
        assert homeassistant.set_nordpool_vat(True) is False
    mock_del.assert_not_called()


def test_entry_hittas_inte_ger_false_utan_att_radera_nagot():
    with patch("homeassistant.requests.get", return_value=_resp(json_data=[])), \
         patch("homeassistant.requests.delete") as mock_del:
        assert homeassistant.set_nordpool_vat(True) is False
    mock_del.assert_not_called()


def test_radering_misslyckas_ger_false():
    with patch("homeassistant.requests.get") as mock_get, \
         patch("homeassistant.requests.delete", return_value=_resp(status_code=500)):
        mock_get.side_effect = [_resp(json_data=_ENTRY_META), _sensor_resp()]
        assert homeassistant.set_nordpool_vat(True) is False


def test_skapande_misslyckas_efter_lyckad_radering_ger_false_kritiskt():
    """Värsta fallet: gamla raderad, nya kunde inte skapas - sensor.nordpool saknas helt.
    Måste returnera False (aldrig krascha main-loopen) så anroparen kan larma tydligt."""
    with patch("homeassistant.requests.get") as mock_get, \
         patch("homeassistant.requests.delete", return_value=_resp()), \
         patch("homeassistant.requests.post", return_value=_resp(status_code=500)):
        mock_get.side_effect = [_resp(json_data=_ENTRY_META), _sensor_resp()]
        assert homeassistant.set_nordpool_vat(True) is False


def test_verifiering_tar_nagra_forsok_innan_sensorn_svarar():
    with patch("homeassistant.requests.get") as mock_get, \
         patch("homeassistant.requests.delete", return_value=_resp()), \
         patch("homeassistant.requests.post") as mock_post, \
         patch("homeassistant.time.sleep"):
        mock_get.side_effect = [
            _resp(json_data=_ENTRY_META),
            _sensor_resp(),
            _resp(status_code=404),                # verifiering 1: inte uppe än
            _resp(status_code=404),                # verifiering 2: inte uppe än
            _sensor_resp(),                         # verifiering 3: uppe
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
        mock_get.side_effect = [_resp(json_data=_ENTRY_META), _sensor_resp()] + [_resp(status_code=404)] * 6
        mock_post.side_effect = [
            _resp(json_data={"flow_id": "abc123"}),
            _resp(json_data={"type": "create_entry"}),
        ]
        ok = homeassistant.set_nordpool_vat(True)
    assert ok is False
