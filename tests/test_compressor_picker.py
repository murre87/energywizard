from pathlib import Path
import shutil
import subprocess
from unittest.mock import patch

import pytest
import yaml
import discovery
from house_config import build_heat_pump_driver
from test_solax_modbus_battery import _builder


def test_text_and_binary_compressor_sensors_are_available_without_numeric_state(monkeypatch):
    monkeypatch.setattr(discovery, '_check_configured_heat_pump', lambda: None)
    entities = [{'e': 'sensor.status_kompressor_43427', 'n': 'Status kompressor', 'st': 'Kör'},
                {'e': 'binary_sensor.compressor_running', 'n': 'Compressor', 'st': 'off'},
                {'e': 'sensor.bt1', 'n': 'Outdoor', 'st': '5'}]
    options = discovery.discover_house(entities)['compressor_sensors']
    assert {e['entity'] for e in options} == {entities[0]['e'], entities[1]['e']}
    assert next(e for e in options if e['entity'] == entities[0]['e'])['state'] == 'Kör'


@pytest.mark.parametrize('state,running', [('Kör', True), ('Från', False)])
def test_picked_status_survives_yaml_and_reaches_driver(state, running):
    cfg = yaml.safe_load(_builder()({'heat_pump': {'driver': 'ha_entities', 'entities': {
        'outdoor_temp': 'sensor.bt1', 'compressor': 'sensor.status_kompressor_43427'}}}))
    driver = build_heat_pump_driver(cfg)
    with patch('drivers.heatpump_ha_entities.homeassistant') as ha:
        ha._get_numeric_state.return_value = None
        ha._get_raw_state.return_value = state
        assert driver.read_sensors()['compressor_running'] is running
        ha._get_raw_state.assert_called_once_with('sensor.status_kompressor_43427')


@pytest.mark.skipif(shutil.which('node') is None, reason='Node required')
def test_rendered_picker_selection_and_saved_form():
    subprocess.run(['node', 'scripts/test_compressor_picker.cjs'], cwd=Path(__file__).resolve().parents[1], check=True)
