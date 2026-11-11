"""Empty car lists must not trap mobile users in the initial car picker."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js required for mobile UI checks")
def test_empty_car_navigation_and_picker_recovery():
    result = subprocess.run(
        ["node", "scripts/test_ewapp_empty_cars.cjs"],
        cwd=ROOT, text=True, capture_output=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
