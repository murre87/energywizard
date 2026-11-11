"""Exercise rendered UI strings through the browser translator and both catalogs."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js required for UI checks")
def test_rendered_ui_translations():
    result = subprocess.run(
        ["node", "scripts/test_ui_translations.cjs"],
        cwd=ROOT, text=True, capture_output=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
