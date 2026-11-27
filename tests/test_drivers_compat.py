"""Steg 5c: Core och drivrutinerna är skrivna mot samma huvudversion av kontraktet, och motorn kontrollerar det vid start."""
import contract_guard  # noqa: F401  (testmiljön)
import pytest

import contracts
from drivers import host


def test_core_and_drivers_agree_on_the_contract_major():
    host.check_compat(contracts.API_VERSION)
    assert str(host.REQUIRES_CONTRACT_MAJOR) == contracts.API_VERSION.split(".")[0]


def test_a_different_major_stops_the_start():
    with pytest.raises(RuntimeError):
        host.check_compat(f"{host.REQUIRES_CONTRACT_MAJOR + 1}.0.0")


def test_main_checks_it_before_anything_runs():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "smartbox" / "main.py").read_text(encoding="utf-8")
    assert "_drivers_host.check_compat(contracts.API_VERSION)" in src
    assert src.index("_drivers_host.check_compat") < src.index("_planner = planner_bridge.Bridge()")
