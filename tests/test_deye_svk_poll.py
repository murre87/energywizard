"""#297: deye-svk ska inte kasta LuaError när Modbus svarar (nil, fel) utan att kasta.

lua_host returnerar just den tupeln vid läsfel. pcall blir då sann och registertabellen
är nil. driver_poll anropas varje varv medan märkeffekten fortfarande är 0.
"""
import os

import pytest

pytest.importorskip("lupa")
from lua_host import FTW_DIR, LuaDriver  # noqa: E402

PATH = os.path.join(FTW_DIR, "deye-svk.lua")


def _no_sleep(monkeypatch):
    monkeypatch.setattr("lua_host.time.sleep", lambda *_a, **_k: None)


def _serial(L):
    raw = b"SN1234567890ABCD"
    vals = [((raw[i] << 8) | raw[i + 1]) for i in range(0, 16, 2)]
    return L.table_from(vals)


def _rated(L, watts):
    """Regs 20-21 are U32 LE × 0.1 W."""
    raw = int(watts * 10)
    return L.table_from([raw & 0xFFFF, (raw >> 16) & 0xFFFF])


def test_poll_kastar_inte_nar_bussen_svarar_med_fel(monkeypatch):
    _no_sleep(monkeypatch)

    def fake(self, addr, count, kind="holding"):
        return None, "modbus fel"

    monkeypatch.setattr(LuaDriver, "_modbus_read", fake)
    d = LuaDriver(PATH, host="192.0.2.1", port=502, log=lambda *_: None)
    em, nxt = d.poll()
    assert nxt == 5000 and em == {}
    em2, nxt2 = d.poll()
    assert nxt2 == 5000 and em2 == {}


def test_init_overlever_nar_serienummer_finns_men_ovriga_register_saknas(monkeypatch):
    _no_sleep(monkeypatch)

    def fake(self, addr, count, kind="holding"):
        if int(addr) == 3:
            return _serial(self.L)
        return None, "modbus fel"

    monkeypatch.setattr(LuaDriver, "_modbus_read", fake)
    d = LuaDriver(PATH, host="192.0.2.1", port=502, log=lambda *_: None)
    assert d.info.get("sn") == "SN1234567890ABCD"
    assert d.info.get("rated_w") == 0
    em, nxt = d.poll()
    assert nxt == 5000 and em == {}


def test_poll_laser_batteriet_nar_registren_svarar(monkeypatch):
    _no_sleep(monkeypatch)

    def fake(self, addr, count, kind="holding"):
        a = int(addr)
        if a == 3:
            return _serial(self.L)
        if a == 0:
            return self.L.table_from([0x0600])          # HV
        if a == 20:
            return _rated(self.L, 10000)
        if a == 587:
            # 588 = 50 %, 590 = 100 → HV ×10, tecken vänt: −1000 W
            return self.L.table_from([0, 50, 0, 100])
        return None, "modbus fel"

    monkeypatch.setattr(LuaDriver, "_modbus_read", fake)
    d = LuaDriver(
        PATH, host="192.0.2.1", port=502, log=lambda *_: None,
        config={"battery_capacity_wh": 10000},
    )
    assert d.info.get("model") == "Deye-HV" and d.info.get("rated_w") == 10000
    em, nxt = d.poll()
    bat = em["battery"]
    assert nxt == 5000
    assert bat["W"] == -1000
    assert bat["SoC_nom_fract"] == pytest.approx(0.5)
    assert bat["available_charge_Wh"] == 5000
    assert bat["available_discharge_Wh"] == 5000
