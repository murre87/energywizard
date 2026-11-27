"""#443 (Lars): Solis RC släpper tvångsladdning/håll efter sin RC Timeout (standard 5 min). Håll vid liv måste därför
anropas i 10-sekundersloopen, inte bara i kvartsstyrningen - och aldrig under säkerhetsregler eller utan styrning.
#615: reservnivåns håll är undantaget. Det är bara håll, så förnyelsen förlänger ingen laddning eller urladdning."""
import os
import re

SRC = open(os.path.join(os.path.dirname(__file__), "..", "smartbox", "main.py"), encoding="utf-8").read()


def test_håll_vid_liv_i_snabbloopen():
    fast = SRC.split("SNABB TASK", 1)[1].split("tibber = homeassistant.read_power_meter()", 1)[0]
    assert "battery_driver.refresh()" in fast
    assert 'battery_cfg["control"] == "styr"' in fast and "battery_control.keepalive_allowed" in fast
    assert "system_test.active()" in fast
    assert re.search(r'getattr\(battery_driver, "_keepalive"', fast)
    quarter = SRC.split("battery_driver.set_balancing", 1)[1].split("_battery[\"decision_rule\"]", 1)[0]
    assert "battery_control.keepalive_allowed" in quarter and "battery_driver.refresh()" in quarter
