"""EnergyHub wire format, confirmed commands and opt-in behavior; no network I/O."""
from unittest.mock import Mock

import pytest
from pymodbus.exceptions import ModbusException

from drivers.battery_ferroamp import FerroampBatteryDriver
from drivers.solar_ferroamp import FerroampSolarDriver
from drivers.ferroamp_modbus import float_words
from house_config import build_battery_driver, build_solar_driver

MODBUS = {"host": "192.0.2.10", "unit_id": 7, "verify_timeout_s": 0.001}


class Reply:
    def __init__(self, registers=(), error=False):
        self.registers, self.error = list(registers), error

    def isError(self):
        return self.error


class Hub:
    def __init__(self):
        self.inputs = {6016: float_words(60), 6100: float_words(2), 6008: float_words(10),
                       6104: [0], 6106: float_words(0), 5100: float_words(3), 2000: [2],
                       8010: [0], 8012: float_words(0)}
        self.writes = []
        self.reads = []
        self.closed = False
        self.fail_address = None
        self.accept = True
        self.pending = {}

    def connect(self):
        return True

    def close(self):
        self.closed = True

    def read_input_registers(self, address, *, count, device_id):
        assert device_id == 7
        self.reads.append(address)
        return Reply(self.inputs.get(address, []))

    def write_register(self, address, value, *, device_id):
        assert device_id == 7
        self.writes.append((address, value))
        if address == self.fail_address:
            return Reply(error=True)
        self.pending[address] = value
        if self.accept:
            if address == 6000:
                self.inputs[6104] = [value]
            if address == 8016:
                self.inputs[8010] = [self.pending[8010]]
                if 8012 in self.pending:
                    self.inputs[8012] = self.pending[8012]
        return Reply()

    def write_registers(self, address, values, *, device_id):
        assert device_id == 7
        self.writes.append((address, values))
        if address == self.fail_address:
            return Reply(error=True)
        self.pending[address] = values
        if self.accept and address == 6064:
            self.inputs[6106] = values
        return Reply()


@pytest.fixture
def hub(monkeypatch):
    import shadow
    import drivers.ferroamp_modbus as wire
    hub = Hub()
    monkeypatch.setattr(wire, "ModbusTcpClient", lambda *a, **kw: hub)
    monkeypatch.setattr(shadow, "active", lambda: False)
    return hub


def battery(**kwargs):
    return FerroampBatteryDriver(modbus=MODBUS, control_enabled=True, default_mode_verified=True, **kwargs)


def solar(**kwargs):
    return FerroampSolarDriver(modbus=MODBUS, control_enabled=True, **kwargs)


def test_reads_aggregate_battery_and_dc_power_sign(hub):
    state = battery().read_state()
    assert state.pop("power_sample_at") > 0
    assert state.pop("soc_sample_at") > 0
    assert state.pop("soc_source") == "modbus_received"
    assert state == {"soc_pct": 60, "power_w": -2000, "capacity_kwh": 10, "mode": "0"}
    hub.inputs[6100] = float_words(-1.25)
    assert battery().read_state()["power_w"] == 1250
    assert hub.closed


def test_pv_telemetry_does_not_mislabel_lifetime_energy(hub):
    assert solar().read_production() == {"pv_power_w": 3000, "today_kwh": None, "status": "2"}
    assert 5064 not in hub.reads


@pytest.mark.parametrize("intent,kw,words", [("charge", -3.5, [0, 0xC060]), ("discharge", 3.5, [0, 0x4060])])
def test_signed_kw_reference_is_low_word_first_and_written_before_mode(hub, intent, kw, words):
    assert float_words(kw) == words
    assert battery().apply_intent(intent, 3500)
    assert hub.writes == [(6064, words), (6000, 1)]
    assert 6104 in hub.reads and 6106 in hub.reads


def test_release_works_without_soc_and_checks_system_mode(hub):
    hub.inputs[6016] = []
    assert battery().apply_intent("auto")
    assert hub.writes == [(6000, 0)]


def test_battery_control_is_opt_in_and_requires_verified_release(hub):
    for drv in (FerroampBatteryDriver(modbus=MODBUS),
                FerroampBatteryDriver(modbus=MODBUS, control_enabled=True),
                FerroampBatteryDriver(control_enabled=True, default_mode_verified=True)):
        assert not drv.supports_control()
        assert not drv.apply_intent("charge", 1000)
    assert not hub.writes


@pytest.mark.parametrize("intent", ["hold", "idle", "Power-mode", "unknown"])
def test_unsupported_intents_never_send_commands(hub, intent):
    assert not battery().apply_intent(intent)
    assert not hub.writes


@pytest.mark.parametrize("state", [{"soc": 20}, {"soc": 60, "ev_charging_grid": True},
                                    {"soc": 60, "ev_solar_active": True}])
def test_house_rules_fall_back_to_auto_for_unsupported_hold_and_idle(hub, state):
    from battery_control import decide
    decision = decide(state, {"control": "styr"}, battery().supported_intents())
    assert decision["intent"] == "auto"
    assert not hub.writes


@pytest.mark.parametrize("value", [-1, 0, float("nan"), float("inf"), "bad", True])
def test_invalid_power_never_writes(hub, value):
    assert not battery().apply_intent("charge", value)
    assert not hub.writes


@pytest.mark.parametrize("soc,intent", [(20, "discharge"), (100, "charge"), (-1, "charge"), (float("nan"), "discharge")])
def test_fresh_soc_guards_forced_power(hub, soc, intent):
    hub.inputs[6016] = float_words(soc)
    assert not battery().apply_intent(intent, 1000)
    assert not hub.writes


def test_power_is_clamped_to_installation_limit(hub):
    assert battery(max_power_w=2000).apply_intent("discharge", 5000)
    assert hub.writes[0] == (6064, float_words(2))


def test_reference_failure_prevents_activation(hub):
    hub.fail_address = 6064
    assert not battery().apply_intent("charge", 1000)
    assert hub.writes == [(6064, float_words(-1))]


def test_rejected_activation_attempts_release_and_returns_failure(hub):
    hub.accept = False
    assert not battery().apply_intent("charge", 1000)
    assert hub.writes[-1] == (6000, 0)


def test_mode_acceptance_with_wrong_reference_is_not_success(hub):
    original = hub.write_registers

    def wrong_reference(address, values, *, device_id):
        result = original(address, values, device_id=device_id)
        hub.inputs[6106] = float_words(9)
        return result

    hub.write_registers = wrong_reference
    assert not battery().apply_intent("charge", 1000)
    assert hub.writes[-1] == (6000, 0)


def test_zero_export_stages_applies_and_verifies(hub):
    drv = solar()
    assert drv.set_export_limit_pct(0)
    assert hub.writes == [(8010, 1), (8012, [0, 0]), (8016, 1)]
    assert drv.get_export_limit_pct() == 0


def test_export_percentage_requires_configured_watt_boundary(hub):
    assert not solar().set_export_limit_pct(50)
    assert not hub.writes
    drv = solar(max_export_w=6000)
    assert drv.set_export_limit_pct(50)
    assert hub.writes[1] == (8012, float_words(3000))
    assert drv.get_export_limit_pct() == 50


def test_export_release_does_not_overwrite_threshold(hub):
    assert solar().set_export_limit_pct(100)
    assert hub.writes == [(8010, 0), (8016, 1)]
    assert solar().get_export_limit_pct() == 100


@pytest.mark.parametrize("address", [8010, 8012, 8016])
def test_export_write_failure_never_reports_success(hub, address):
    hub.fail_address = address
    assert not solar().set_export_limit_pct(0)
    assert hub.writes[-1][0] == address


def test_export_rejected_readback_is_failure(hub):
    hub.accept = False
    assert not solar().set_export_limit_pct(0)
    assert solar().get_export_limit_pct() == 100


@pytest.mark.parametrize("value", [-1, 101, float("nan"), float("inf"), "bad", True])
def test_bad_export_percentage_never_writes(hub, value):
    assert not solar().set_export_limit_pct(value)
    assert not hub.writes


def test_unavailable_and_error_responses_are_unknown(hub):
    hub.inputs = {}
    assert battery().read_state()["soc_pct"] is None
    assert solar().get_export_limit_pct() is None
    hub.read_input_registers = Mock(return_value=Reply(error=True))
    assert battery().read_state()["soc_pct"] is None
    hub.read_input_registers.side_effect = ModbusException("unavailable")
    assert battery().read_state()["soc_pct"] is None
    assert hub.closed


def test_connect_failure_and_transport_error_do_not_report_success(hub):
    hub.connect = Mock(return_value=False)
    assert not solar().set_export_limit_pct(0)
    hub.connect.side_effect = OSError("offline")
    assert not battery().apply_intent("auto")
    assert hub.closed


def test_shadow_mode_records_without_connecting(hub, monkeypatch):
    import shadow
    monkeypatch.setattr(shadow, "active", lambda: True)
    record = Mock()
    monkeypatch.setattr(shadow, "record", record)
    hub.connect = Mock(side_effect=AssertionError("shadow must not connect for writes"))
    assert battery().apply_intent("charge", 1000)
    assert solar().set_export_limit_pct(0)
    assert record.call_count == 2


def test_builders_register_drivers_without_enabling_writes(hub):
    cfg = {"battery": {"enabled": True, "driver": "ferroamp_modbus", "modbus": MODBUS},
           "solar": {"enabled": True, "driver": "ferroamp_modbus", "modbus": MODBUS}}
    assert isinstance(build_battery_driver(cfg), FerroampBatteryDriver)
    assert not build_battery_driver(cfg).supports_control()
    assert not build_solar_driver(cfg).supports_curtailment()
    cfg["battery"].update(control="styr", default_mode_verified=True)
    assert build_battery_driver(cfg).supported_intents() == {"auto", "charge", "discharge"}


@pytest.mark.parametrize("control", ["samarbete", "av", "unknown"])
def test_read_only_control_modes_disable_direct_writes(hub, control):
    drv = build_battery_driver({"battery": {"enabled": True, "driver": "ferroamp_modbus", "modbus": MODBUS,
                                           "control": control, "default_mode_verified": True}})
    assert not drv.apply_intent("auto")
    assert not hub.writes


@pytest.mark.parametrize("cfg", [{"timeout_s": 0}, {"verify_timeout_s": float("nan")}, {"port": -1}, {"unit_id": 999}])
def test_invalid_transport_config_is_rejected(cfg):
    with pytest.raises(ValueError):
        FerroampBatteryDriver(modbus={**MODBUS, **cfg})
