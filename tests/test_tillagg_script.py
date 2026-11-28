"""scripts/tillagg.sh och changelog.d/: versionen sätts rätt både med det gamla sättet (rubrik överst i CHANGELOG.md) och med fragment,
och två merger efter varandra krockar inte. Körs mot ett riktigt git-repo (bart ursprung) och en falsk docker."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ha-addon" / "smartbox"))
import addon_version as av  # noqa: E402

FAKE_DOCKER = r'''#!/usr/bin/env python3
import json, os, sys
state_path = os.environ["FAKE_DOCKER_STATE"]
state = json.load(open(state_path)) if os.path.exists(state_path) else {}
a = sys.argv[1:]
assert a[:2] == ["buildx", "imagetools"], a
if a[2] == "inspect":
    ref = a[-1]
    if ref not in state:
        sys.exit(1)
    if "--format" in a:
        print(state[ref])
    else:
        print("Name: " + ref + "\nPlatform: linux/amd64\nPlatform: linux/arm64")
elif a[2] == "create":
    tag = a[a.index("-t") + 1]
    src = a[-1]
    state[tag] = state.get(src, "digest-of-" + src)
    json.dump(state, open(state_path, "w"))
    open(os.environ["FAKE_DOCKER_LOG"], "a").write("create " + tag + " <- " + src + "\n")
'''

CONFIG = 'name: "EnergyWizard"\nversion: "1.2.195"\nimage: "ghcr.io/murre87/energywizard"\nslug: "energywizard"\n'
CHANGELOG = "# Ändringar\n\nIntro.\n\n## 1.2.195 (2026-11-27)\n- **Gammal.** Text.\n\n## 1.2.194 (2026-11-26)\n- **Äldre.** Text.\n"


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    work = tmp_path / "work"
    subprocess.run(["git", "clone", "-q", str(origin), str(work)], check=True, capture_output=True)
    git(work, "checkout", "-q", "-b", "main")
    (work / "ha-addon" / "smartbox").mkdir(parents=True)
    (work / "scripts").mkdir()
    (work / "changelog.d").mkdir()
    shutil.copy(ROOT / "ha-addon" / "smartbox" / "addon_version.py", work / "ha-addon" / "smartbox" / "addon_version.py")
    shutil.copy(ROOT / "scripts" / "tillagg.sh", work / "scripts" / "tillagg.sh")
    (work / "ha-addon" / "smartbox" / "config.yaml").write_text(CONFIG, encoding="utf-8")
    (work / "ha-addon" / "smartbox" / "CHANGELOG.md").write_text(CHANGELOG, encoding="utf-8")
    (work / "changelog.d" / "README.md").write_text("# readme\n", encoding="utf-8")
    git(work, "add", "-A")
    git(work, "commit", "-qm", "start")
    git(work, "push", "-q", "origin", "main")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "docker").write_text(FAKE_DOCKER, encoding="utf-8")
    (bindir / "docker").chmod(0o755)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "FAKE_DOCKER_STATE": str(tmp_path / "docker.json"), "FAKE_DOCKER_LOG": str(tmp_path / "docker.log"),
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    return work, origin, env, tmp_path


def push_commit(work, files: dict, remove=(), message="pr"):
    git(work, "fetch", "-q", "origin", "main")
    git(work, "reset", "-q", "--hard", "origin/main")
    for name, text in files.items():
        p = work / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    for name in remove:
        (work / name).unlink()
    git(work, "add", "-A")
    git(work, "commit", "-qm", message)
    git(work, "push", "-q", "origin", "main")
    return git(work, "rev-parse", "HEAD")


def build(env, sha):
    """Imagen för en commit finns (bygget klart): den falska dockern känner igen <bild>:<sha>."""
    state_path = Path(env["FAKE_DOCKER_STATE"])
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    state[f"ghcr.io/murre87/energywizard:{sha}"] = "digest-" + sha[:8]
    state_path.write_text(json.dumps(state))


def run(work, env, sha):
    git(work, "fetch", "-q", "origin", "main")
    git(work, "reset", "-q", "--hard", "origin/main")
    return subprocess.run(["bash", "scripts/tillagg.sh", sha], cwd=work, env=env, capture_output=True, text=True)


def show(work, path):
    git(work, "fetch", "-q", "origin", "main")
    return git(work, "show", f"origin/main:{path}")


def test_legacy_mode_uses_the_heading_in_the_built_commit(repo):
    work, origin, env, tmp = repo
    sha = push_commit(work, {"ha-addon/smartbox/CHANGELOG.md": CHANGELOG.replace("## 1.2.195", "## 1.2.196 (2026-11-28)\n- **Ny.** Text.\n\n## 1.2.195", 1)})
    build(env, sha)
    r = run(work, env, sha)
    assert r.returncode == 0, r.stdout + r.stderr
    assert 'version: "1.2.196"' in show(work, "ha-addon/smartbox/config.yaml")
    assert "create ghcr.io/murre87/energywizard:1.2.196" in (tmp / "docker.log").read_text()
    assert "Tillägg 1.2.196" in git(work, "log", "-1", "--format=%s", "origin/main")


def test_fragments_are_compiled_into_the_next_version_and_removed(repo):
    work, origin, env, tmp = repo
    sha = push_commit(work, {"changelog.d/issue-1.md": "- **Första (#1).** En sak.\n", "changelog.d/issue-2.md": "- **Andra (#2).** Mer.\n  Fortsättning på nästa rad.\n"})
    build(env, sha)
    r = run(work, env, sha)
    assert r.returncode == 0, r.stdout + r.stderr
    cl = show(work, "ha-addon/smartbox/CHANGELOG.md")
    assert cl.index("## 1.2.196") < cl.index("## 1.2.195")
    assert "- **Första (#1).** En sak.\n- **Andra (#2).** Mer.\n  Fortsättning på nästa rad." in cl
    assert 'version: "1.2.196"' in show(work, "ha-addon/smartbox/config.yaml")
    tree = git(work, "ls-tree", "-r", "--name-only", "origin/main")
    assert "changelog.d/issue-1.md" not in tree and "changelog.d/issue-2.md" not in tree and "changelog.d/README.md" in tree
    assert "create ghcr.io/murre87/energywizard:1.2.196 <- ghcr.io/murre87/energywizard:" + sha in (tmp / "docker.log").read_text()


def test_two_merges_in_a_row_get_one_version_each_and_no_fragment_is_counted_twice(repo):
    work, origin, env, tmp = repo
    a = push_commit(work, {"changelog.d/a.md": "- **A.** a.\n"})
    b = push_commit(work, {"changelog.d/b.md": "- **B.** b.\n"})          # B byggs medan A:s fragment ännu inte är inräknat
    build(env, a)
    build(env, b)
    assert run(work, env, a).returncode == 0                                # A:s jobb: bara a.md fanns i A:s commit
    cl = show(work, "ha-addon/smartbox/CHANGELOG.md")
    assert "- **A.** a." in cl and "- **B.** b." not in cl and "## 1.2.196" in cl
    assert run(work, env, b).returncode == 0                                # B:s jobb (B:s commit innehåller a.md och b.md; a.md är redan borta)
    cl = show(work, "ha-addon/smartbox/CHANGELOG.md")
    assert cl.count("- **A.** a.") == 1 and cl.count("- **B.** b.") == 1
    assert cl.index("## 1.2.197") < cl.index("## 1.2.196") < cl.index("## 1.2.195")
    assert 'version: "1.2.197"' in show(work, "ha-addon/smartbox/config.yaml")
    log = (tmp / "docker.log").read_text()
    assert "1.2.196 <- ghcr.io/murre87/energywizard:" + a in log and "1.2.197 <- ghcr.io/murre87/energywizard:" + b in log


def test_a_rerun_of_the_same_job_does_nothing_more(repo):
    work, origin, env, tmp = repo
    sha = push_commit(work, {"changelog.d/a.md": "- **A.** a.\n"})
    build(env, sha)
    assert run(work, env, sha).returncode == 0
    head = git(work, "rev-parse", "origin/main")
    r = run(work, env, sha)
    assert r.returncode == 0 and "redan inräknade" in r.stdout
    git(work, "fetch", "-q", "origin", "main")
    assert git(work, "rev-parse", "origin/main") == head


def test_a_leftover_tag_on_another_image_is_skipped(repo):
    work, origin, env, tmp = repo
    sha = push_commit(work, {"changelog.d/a.md": "- **A.** a.\n"})
    build(env, sha)
    state = json.loads(Path(env["FAKE_DOCKER_STATE"]).read_text())
    state["ghcr.io/murre87/energywizard:1.2.196"] = "digest-of-something-else"       # kvarlevande tagg från ett misslyckat försök
    Path(env["FAKE_DOCKER_STATE"]).write_text(json.dumps(state))
    r = run(work, env, sha)
    assert r.returncode == 0, r.stdout + r.stderr
    assert 'version: "1.2.197"' in show(work, "ha-addon/smartbox/config.yaml")
    assert "## 1.2.197" in show(work, "ha-addon/smartbox/CHANGELOG.md") and "## 1.2.196" not in show(work, "ha-addon/smartbox/CHANGELOG.md")


def test_a_broken_fragment_stops_the_release_instead_of_publishing(repo):
    work, origin, env, tmp = repo
    sha = push_commit(work, {"changelog.d/dalig.md": "bara text utan punkt\n"})
    build(env, sha)
    r = run(work, env, sha)
    assert r.returncode != 0
    assert 'version: "1.2.195"' in show(work, "ha-addon/smartbox/config.yaml")       # config.yaml höjs inte


def test_compile_changelog_unit():
    text = "# Ändringar\n\n## 1.2.9 (x)\n- a\n"
    out = av.compile_changelog(text, "1.2.10", "2026-11-28", [("b.md", "- **B.** b\n"), ("a.md", "- **A.** a\n- **A2.** a2\n")])
    assert out == "# Ändringar\n\n## 1.2.10 (2026-11-28)\n- **A.** a\n- **A2.** a2\n- **B.** b\n\n## 1.2.9 (x)\n- a\n"
    assert av.next_version(text) == "1.2.10" and av.succ("1.2.99") == "1.2.100"
    with pytest.raises(ValueError):
        av.compile_changelog(text, "1.2.9", "d", [("a.md", "- a\n")])
    with pytest.raises(ValueError):
        av.compile_changelog(text, "1.2.10", "d", [("a.md", "ingen punkt\n")])
    with pytest.raises(ValueError):
        av.compile_changelog(text, "1.2.10", "d", [("a.md", "\n\n")])
