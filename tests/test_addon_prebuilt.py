"""HA-tillägget som färdig bild: CI höjer config.yaml:s version först när bilden finns (ha-addon/smartbox/addon_version.py,
jobbet tillagg i .github/workflows/docker.yml)."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("addon_version", ROOT / "ha-addon" / "smartbox" / "addon_version.py")
av = importlib.util.module_from_spec(spec)
spec.loader.exec_module(av)
IMG = "ghcr.io/murre87/energywizard"


def test_changelog_ar_samma_eller_nyare_an_config():
    assert av._key(av.changelog_version()) >= av._key(av.config_version())


def test_set_skriver_version_och_bild():
    cfg = 'name: "EnergyWizard"\nversion: "1.2.16"\nslug: "smartbox"\n'
    out = av.set_version(cfg, "1.2.17", IMG)
    assert out == f'name: "EnergyWizard"\nversion: "1.2.17"\nimage: "{IMG}"\nslug: "smartbox"\n'
    assert av.set_version(out, "1.2.17", IMG) == out                  # inget att ändra
    assert av.config_version(av.set_version(out, "1.2.18", IMG)) == "1.2.18"


def test_set_vagrar_aldre_version():
    with pytest.raises(SystemExit):
        av.set_version('version: "1.2.17"\n', "1.2.16", IMG)


def test_ci_tar_bilden_innan_versionen_hojs():
    wf = (ROOT / ".github" / "workflows" / "docker.yml").read_text(encoding="utf-8")
    job = wf[wf.index("  tillagg:"):]
    assert "needs: allt-i-ett" in job
    assert 'bash scripts/tillagg.sh "${{ github.sha }}"' in job            # logiken ligger i skriptet (steg: changelog.d)
    script = (ROOT / "scripts" / "tillagg.sh").read_text(encoding="utf-8")
    assert script.index("imagetools create") < script.index("$AV set ")      # bilden taggas innan versionen höjs (båda lägena)
    assert script.rindex("imagetools create") < script.rindex("$AV set ")
    assert "provenance: false" in wf


def test_bilden_byggs_fran_exakt_commit():
    df = (ROOT / "ha-addon" / "smartbox" / "Dockerfile").read_text(encoding="utf-8")
    assert 'git -C /src checkout -q "${ENERGYWIZARD_COMMIT}"' in df


def test_aldre_korning_hojer_aldrig_bakat():
    import subprocess, sys as _s
    script = str(ROOT / "ha-addon" / "smartbox" / "addon_version.py")
    assert subprocess.run([_s.executable, script, "newer", "1.2.28", "1.2.26"]).returncode == 0
    assert subprocess.run([_s.executable, script, "newer", "1.2.26", "1.2.27"]).returncode == 1
    assert subprocess.run([_s.executable, script, "newer", "1.2.27", "1.2.27"]).returncode == 1
    wf = (ROOT / ".github" / "workflows" / "docker.yml").read_text(encoding="utf-8")
    script = (ROOT / "scripts" / "tillagg.sh").read_text(encoding="utf-8")
    assert "ref: main" in wf and 'exit 1' in script and "git show" in script
