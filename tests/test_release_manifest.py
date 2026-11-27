"""Steg 5c: smartbox/drivers är exakt den version av energywizard-drivers som release-manifest.json pekar ut (ingen lokal ändring förbi det repot)."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import sync_drivers  # noqa: E402


def test_the_manifest_is_well_formed():
    d = json.loads((ROOT / "release-manifest.json").read_text(encoding="utf-8"))["drivers"]
    assert d["repo"] == "murre87/energywizard-drivers" and re.fullmatch(r"v\d+\.\d+\.\d+", d["tag"])
    assert re.fullmatch(r"[0-9a-f]{40}", d["commit"]) and re.fullmatch(r"[0-9a-f]{64}", d["tree_sha256"])


def test_vendored_drivers_equal_the_pinned_release(capsys):
    assert sync_drivers.check() == 0, capsys.readouterr().out


def test_a_local_edit_of_a_driver_is_caught(tmp_path, monkeypatch):
    import shutil
    copy = tmp_path / "drivers"
    shutil.copytree(sync_drivers.TARGET, copy, ignore=shutil.ignore_patterns("__pycache__"))
    monkeypatch.setattr(sync_drivers, "TARGET", copy)
    assert sync_drivers.check() == 0
    (copy / "host.py").write_text((copy / "host.py").read_text(encoding="utf-8") + "\n# lokal ändring\n", encoding="utf-8")
    assert sync_drivers.check() == 1
    (copy / "host.py").write_text((copy / "host.py").read_text(encoding="utf-8").replace("\n# lokal ändring\n", ""), encoding="utf-8")
    (copy / "ny.py").write_text("x = 1\n", encoding="utf-8")                 # en ny fil räknas också
    assert sync_drivers.check() == 1
