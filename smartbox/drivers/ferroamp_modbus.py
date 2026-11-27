"""EnergyHub Modbus transport: zero-based addresses, float32 with low word first.

Register map: Ferroamp Modbus TCP Specification RevD, sections 6.5-6.9.
No connections or writes at construction. Hardware/firmware validation is still required.
"""
from contextlib import contextmanager
import logging
import math
import struct
import time

try:                                # pymodbus finns i motorns bild men inte i mobilappens; mobilappen läser bara
    from pymodbus.client import ModbusTcpClient          # installationen (house_config) och ansluter aldrig.
    from pymodbus.exceptions import ModbusException
except ImportError:                 # pragma: no cover
    ModbusTcpClient = None

    class ModbusException(Exception):
        pass

log = logging.getLogger(__name__)


def float_words(value):
    high, low = struct.unpack(">HH", struct.pack(">f", value))
    return [low, high]


def read_words(client, address, count, unit_id):
    result = client.read_input_registers(address=address, count=count, device_id=unit_id)
    if result.isError() or len(result.registers) != count:
        return None
    return result.registers


def read_float(client, address, unit_id):
    words = read_words(client, address, 2, unit_id)
    if words is None:
        return None
    value = struct.unpack(">f", struct.pack(">HH", words[1], words[0]))[0]
    return value if math.isfinite(value) else None


def write_word(client, address, value, unit_id):
    return not client.write_register(address=address, value=value, device_id=unit_id).isError()


def write_float(client, address, value, unit_id):
    return not client.write_registers(address=address, values=float_words(value), device_id=unit_id).isError()


class EnergyHubConnection:
    def __init__(self, modbus=None):
        cfg = modbus or {}
        self.host = str(cfg.get("host") or "").strip()
        self.port = int(cfg.get("port", 502))
        self.unit_id = int(cfg.get("unit_id", 1))
        self.timeout_s = float(cfg.get("timeout_s", 3.0))
        self.verify_timeout_s = float(cfg.get("verify_timeout_s", 2.0))
        if not 1 <= self.port <= 65535 or not 0 <= self.unit_id <= 247:
            raise ValueError("Invalid EnergyHub Modbus port or unit_id")
        for seconds in (self.timeout_s, self.verify_timeout_s):
            if not math.isfinite(seconds) or not 0 < seconds <= 10:
                raise ValueError("EnergyHub timeouts must be finite and within (0, 10] seconds")

    @contextmanager
    def connect(self):
        client = ModbusTcpClient(self.host, port=self.port, timeout=self.timeout_s, retries=0) if self.host and ModbusTcpClient else None
        try:
            try:
                connected = client if client and client.connect() else None
            except (OSError, ModbusException):
                log.warning("EnergyHub Modbus connection failed")
                connected = None
            try:
                yield connected
            except (OSError, ModbusException, ValueError, struct.error):
                # Do not retry writes after an ambiguous transport failure.
                log.warning("EnergyHub Modbus operation failed")
        finally:
            if client:
                client.close()

    def verify(self, predicate):
        deadline = time.monotonic() + self.verify_timeout_s
        while True:
            if predicate():
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(0.2, remaining))


def shadow_write(detail):
    from drivers.host import shadow
    if shadow.active():
        shadow.record("Ferroamp EnergyHub", detail)
        return True
    return False
