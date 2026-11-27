#!/usr/bin/env python3
"""Drivrutinerna kommer från repot energywizard-drivers i en fastlåst version (steg 5c av uppdelningen, docs/uppdelning/PLAN.md).

  python scripts/sync_drivers.py --check     kontrollerar att smartbox/drivers är exakt den version release-manifest.json pekar ut
  python scripts/sync_drivers.py             hämtar den version manifestet pekar ut och lägger den i smartbox/drivers
  python scripts/sync_drivers.py --bump TAGG hämtar taggen, skriver in tagg, commit och innehållsstämpel i manifestet

Så ändras en drivrutin: ändra i energywizard-drivers, tagga, kör --bump här och skicka en PR. Core:s CI kör hela sviten mot den nya versionen."""
import hashlib
import io
import json
import shutil
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "release-manifest.json"
TARGET = ROOT / "smartbox" / "drivers"


def tree_hash(directory: Path) -> str:
    """Innehållsstämpel över alla filer (sökväg och innehåll, sorterat), utan __pycache__."""
    h = hashlib.sha256()
    for p in sorted(directory.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts:
            h.update(p.relative_to(directory).as_posix().encode() + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()


def load():
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def fetch(repo: str, ref: str, dest: Path) -> str:
    """Hämtar drivers/-katalogen för en tagg eller commit ur repots tarball. Ger commit-sha:n."""
    url = f"https://codeload.github.com/{repo}/tar.gz/{ref}"
    with urllib.request.urlopen(url, timeout=60) as r:
        data = r.read()
    sha = None
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as t:
        top = t.getmembers()[0].name.split("/")[0]
        dest.mkdir(parents=True)
        for m in t.getmembers():
            rel = m.name[len(top) + 1:]
            if m.isfile() and rel.startswith("drivers/") and "__pycache__" not in rel:
                out = dest / rel[len("drivers/"):]
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(t.extractfile(m).read())
        sha = (t.pax_headers or {}).get("comment")
    return sha or ""


def check() -> int:
    m = load()["drivers"]
    got = tree_hash(TARGET)
    if got != m["tree_sha256"]:
        print(f"FEL: smartbox/drivers stämmer inte med release-manifest.json (version {m['tag']}).\n"
              f"  Väntade {m['tree_sha256'][:12]}, fick {got[:12]}.\n"
              f"  Drivrutinerna ändras i {m['repo']} (ny tagg) och hämtas hit med: python scripts/sync_drivers.py --bump <tagg>")
        return 1
    print(f"OK: smartbox/drivers är {m['repo']} {m['tag']}")
    return 0


def sync(ref: str, repo: str, write_manifest: bool, tag: str | None = None) -> int:
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / "drivers"
        sha = fetch(repo, ref, dest)
        stamp = tree_hash(dest)
        if TARGET.exists():
            shutil.rmtree(TARGET)
        shutil.copytree(dest, TARGET)
    if write_manifest:
        MANIFEST.write_text(json.dumps({"drivers": {"repo": repo, "tag": tag, "commit": sha, "tree_sha256": stamp}}, indent=2) + "\n", encoding="utf-8")
    print(f"smartbox/drivers = {repo} {tag or ref} ({stamp[:12]})")
    return 0


if __name__ == "__main__":
    a = sys.argv[1:]
    if a == ["--check"]:
        sys.exit(check())
    if a[:1] == ["--bump"] and len(a) == 2:
        sys.exit(sync(a[1], load()["drivers"]["repo"], True, a[1]))
    if not a:
        d = load()["drivers"]
        sys.exit(sync(d["tag"], d["repo"], False, d["tag"]) or check())
    print(__doc__)
    sys.exit(2)
