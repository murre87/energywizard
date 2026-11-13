"""#303: reset during connect must close the client and permit the next read."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import pump


@pytest.mark.parametrize("fallback", [False, True])
def test_connection_reset_closes_failed_client(monkeypatch, capsys, fallback):
    monkeypatch.setattr(pump, "PUMP_IPS", ["primary.invalid", "fallback.invalid"])
    monkeypatch.setattr(pump, "_active_ip_index", 0)
    failed = Mock()
    failed.connect.side_effect = ConnectionResetError("peer reset")
    clients = [failed]
    if fallback:
        primary = Mock()
        primary.connect.return_value = False
        clients.insert(0, primary)
    factory = Mock(side_effect=clients)
    monkeypatch.setattr(pump, "ModbusTcpClient", factory)

    assert pump.read_sensors() is None
    for client in clients:
        client.close.assert_called_once()
        client.read_input_registers.assert_not_called()
    assert factory.call_count == len(clients)
    assert pump._active_ip_index == 0
    out = capsys.readouterr().out
    assert "⚠️" in out and "❌" not in out

    # No failed client is reused; the next polling cycle can read successfully.
    recovered = Mock()
    recovered.connect.return_value = True
    recovered.read_input_registers.return_value = SimpleNamespace(
        isError=lambda: False, registers=[0] * 40)
    recovered.read_holding_registers.return_value = SimpleNamespace(
        isError=lambda: False, registers=[0] * 11)
    monkeypatch.setattr(pump, "ModbusTcpClient", Mock(return_value=recovered))
    result = pump.read_sensors()
    assert result is not None and result["power_consumption_w"] == 0
    recovered.close.assert_called_once()
