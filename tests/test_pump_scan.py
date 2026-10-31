"""pump.scan_for_husdata(): söker efter en Husdata-värmepump på det lokala nätverket,
för installationer utan PUMP_IP satt alls. Mockar socket/Modbus helt - rör aldrig ett
riktigt nätverk eller riktig hårdvara. Viktigast: en enhet som bara svarar på TCP-porten
men INTE har Husdatas registerinnehåll ska avvisas, inte räknas som en falsk träff."""
from unittest.mock import MagicMock, patch

import pump


def _mock_modbus_response(registers):
    res = MagicMock()
    res.isError.return_value = False
    res.registers = registers
    return res


def _husdata_registers(outdoor_c=5.0, indoor_c=21.0):
    """reg[4]=outdoor, reg[5]=indoor, ×10 enligt pump.py:s get_temp-konvention."""
    return [0, 0, 0, 0, int(outdoor_c * 10), int(indoor_c * 10)]


def test_probe_modbus_port_oppen_port_ger_true():
    with patch("pump.socket.create_connection") as mock_conn:
        mock_conn.return_value.__enter__.return_value = MagicMock()
        assert pump._probe_modbus_port("192.168.1.50") is True


def test_probe_modbus_port_stangd_port_ger_false():
    with patch("pump.socket.create_connection", side_effect=OSError("refused")):
        assert pump._probe_modbus_port("192.168.1.50") is False


def test_confirm_husdata_rimliga_temperaturer_ger_true():
    with patch("pump.ModbusTcpClient") as MockClient:
        client = MockClient.return_value
        client.connect.return_value = True
        client.read_input_registers.return_value = _mock_modbus_response(_husdata_registers())
        assert pump._confirm_husdata("192.168.1.50") is True


def test_confirm_husdata_orimliga_temperaturer_avvisas():
    """En annan Modbus-enhet som råkar svara på port 502 men inte har Husdatas
    registerlayout ska INTE räknas som en Husdata-pump - orimliga värden avslöjar det."""
    with patch("pump.ModbusTcpClient") as MockClient:
        client = MockClient.return_value
        client.connect.return_value = True
        # Helt orimliga "temperaturer" - typiskt för fel enhet/fel registerkarta.
        client.read_input_registers.return_value = _mock_modbus_response(_husdata_registers(outdoor_c=500.0, indoor_c=-200.0))
        assert pump._confirm_husdata("192.168.1.50") is False


def test_confirm_husdata_felsvar_avvisas_inte_kraschar():
    with patch("pump.ModbusTcpClient") as MockClient:
        client = MockClient.return_value
        client.connect.return_value = True
        res = MagicMock()
        res.isError.return_value = True
        client.read_input_registers.return_value = res
        assert pump._confirm_husdata("192.168.1.50") is False


def test_confirm_husdata_kan_inte_ansluta_avvisas():
    with patch("pump.ModbusTcpClient") as MockClient:
        MockClient.return_value.connect.return_value = False
        assert pump._confirm_husdata("192.168.1.50") is False


def test_confirm_husdata_exception_ger_false_inte_krasch():
    with patch("pump.ModbusTcpClient", side_effect=RuntimeError("timeout")):
        assert pump._confirm_husdata("192.168.1.50") is False


def test_local_subnet_fran_pump_ip(monkeypatch):
    monkeypatch.setenv("PUMP_IP", "192.168.1.179")
    assert pump._local_subnet() == "192.168.1"


def test_local_subnet_faller_tillbaka_pa_ha_ip(monkeypatch):
    monkeypatch.delenv("PUMP_IP", raising=False)
    with patch("homeassistant.HA_IP", "10.0.0.50"):
        assert pump._local_subnet() == "10.0.0"


def test_scan_for_husdata_bara_bekraftade_trafar_returneras():
    """254 kandidat-IP:er probas, men bara den som BÅDE har öppen port OCH rätt
    registerinnehåll ska hamna i resultatet."""
    def fake_probe(ip, timeout=0.3):
        return ip in ("192.168.1.50", "192.168.1.99")  # två öppna portar

    def fake_confirm(ip, timeout=3.0):
        return ip == "192.168.1.50"  # bara en av dem är faktiskt Husdata

    with patch("pump._probe_modbus_port", side_effect=fake_probe), \
         patch("pump._confirm_husdata", side_effect=fake_confirm):
        found = pump.scan_for_husdata(subnet="192.168.1")

    assert found == [{"ip": "192.168.1.50", "driver": "thermia_husdata"}]


def test_scan_for_husdata_inget_hittat_ger_tom_lista():
    with patch("pump._probe_modbus_port", return_value=False):
        assert pump.scan_for_husdata(subnet="192.168.1") == []
