"""#299: expected Modbus transport failures warn; unexpected faults stay visible."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pymodbus.exceptions import ConnectionException, ModbusIOException

import pump


@pytest.mark.parametrize("failure", [ConnectionException("offline"), ModbusIOException("no response")])
@pytest.mark.parametrize("stage", ["input", "holding"])
def test_modbus_transport_errors_warn_and_close(monkeypatch, capsys, failure, stage):
    monkeypatch.setattr(pump, "PUMP_IPS", ["test.invalid"])
    result = SimpleNamespace(isError=lambda: False, registers=[0] * 40)
    client = Mock()
    client.read_input_registers.return_value = result
    client.read_holding_registers.return_value = result
    getattr(client, f"read_{stage}_registers").side_effect = failure
    monkeypatch.setattr(pump, "_get_client", lambda: client)
    assert pump.read_sensors() is None
    client.close.assert_called_once()
    out = capsys.readouterr().out
    assert "⚠️" in out and "❌" not in out


def test_unexpected_modbus_fault_still_reports_error(monkeypatch, capsys):
    monkeypatch.setattr(pump, "PUMP_IPS", ["test.invalid"])
    client = Mock()
    client.read_input_registers.side_effect = ValueError("bad register decoder")
    monkeypatch.setattr(pump, "_get_client", lambda: client)
    assert pump.read_sensors() is None
    client.close.assert_called_once()
    assert "❌" in capsys.readouterr().out
