from unittest.mock import patch, call
import pytest
import yaml
import discovery
from house_config import build_battery_driver
from test_solax_modbus_battery import _builder


def entities():
    def e(kind,key,name,unit=None,dc=None,state='1',**extra):
        return {'e': f'{kind}.solinteg_{key}', 'n': name, 'd': 'inv1', 'dn': 'Solinteg MHT', 'm': 'Solinteg',
                'u': unit, 'dc': dc, 'st': state, **extra}
    return [e('sensor','battery_soc','Battery SOC','%','battery','60'),
            e('sensor','battery_power','Battery Power','W','power','-2500'),
            e('select','working_mode','Working Mode',options=['General','EMS BattCtrl']),
            e('number','battery_charge_discharge_power_target','EMS BattCtrl Charge Discharge Power Target','kW')]


def config(rows):
    return yaml.safe_load(_builder()({'battery': discovery.discover_house(rows)['battery']}))


def test_complete_preset_preserves_units_sign_and_read_only_default(monkeypatch):
    monkeypatch.setattr(discovery, '_check_configured_heat_pump', lambda: None)
    cfg = config(entities())
    assert cfg['battery']['control'] == 'samarbete'
    assert cfg['battery']['power_invert'] is True
    driver = build_battery_driver(cfg)
    assert driver.supported_intents() == {'auto','hold','charge','discharge'}
    with patch('drivers.battery_generic.homeassistant') as ha:
        ha._get_numeric_state.return_value = 60
        ha.get_power_w.return_value = -2500
        assert driver.read_state()['power_w'] == 2500


@pytest.mark.parametrize('intent,value', [('charge',-2.5), ('discharge',2.5)])
def test_signed_target_is_converted_before_selecting_ems(intent,value):
    driver = build_battery_driver(config(entities()))
    with patch('drivers.battery_generic.homeassistant') as ha:
        ha.get_attribute.side_effect = lambda entity,key: {'unit_of_measurement':'kW','min':-200,'max':200}.get(key)
        ha.set_number.return_value = ha.call_service.return_value = True
        assert driver.apply_intent(intent,2500)
        assert ha.mock_calls.index(call.set_number('number.solinteg_battery_charge_discharge_power_target',value)) < ha.mock_calls.index(call.call_service('select','select_option',{'entity_id':'select.solinteg_working_mode','option':'EMS BattCtrl'}))


def test_target_bounds_and_failed_target_cannot_switch_mode():
    driver = build_battery_driver(config(entities()))
    with patch('drivers.battery_generic.homeassistant') as ha:
        ha.get_attribute.side_effect = lambda entity,key: {'unit_of_measurement':'W','min':-1000,'max':2000}.get(key)
        ha.set_number.return_value = False
        assert not driver.apply_intent('charge',5000)
        ha.set_number.assert_called_once_with('number.solinteg_battery_charge_discharge_power_target',-1000)
        ha.call_service.assert_not_called()


@pytest.mark.parametrize('missing', ['mode','target','options','other_device'])
def test_incomplete_control_contract_only_monitors(missing):
    rows=entities()
    if missing=='mode': rows=rows[:2]+rows[3:]
    if missing=='target': rows=rows[:3]
    if missing=='options': rows[2]['options']=['Economic']
    if missing=='other_device': rows[3]['d']='another'
    cfg=config(rows)
    assert cfg['battery']['power_invert'] is True
    assert not build_battery_driver(cfg).supported_intents()


def test_unknown_runtime_units_refuse_forced_control_but_allow_general():
    driver=build_battery_driver(config(entities()))
    with patch('drivers.battery_generic.homeassistant') as ha:
        ha.get_attribute.return_value='unknown'
        assert not driver.apply_intent('charge',2500)
        ha.set_number.assert_not_called()
        ha.call_service.return_value=True
        assert driver.apply_intent('auto')
        ha.call_service.assert_called_once_with('select','select_option',{'entity_id':'select.solinteg_working_mode','option':'General'})
