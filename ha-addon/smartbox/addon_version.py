"""Tilläggets version (används av CI-jobbet tillagg i .github/workflows/docker.yml och av testerna).

  addon_version.py changelog [fil]    -> versionen överst i CHANGELOG.md ("## 1.2.17 (2026-11-06)")
  addon_version.py newer <a> <b>      -> exit 0 om a är nyare än b
  addon_version.py config             -> versionen i config.yaml
  addon_version.py set <ver> <image>  -> skriver version och image i config.yaml; exit 0 om något ändrades, 1 annars

Versionen i config.yaml höjs bara av CI, efter att den färdiga bilden <image>:<ver> finns (annars skulle Home
Assistant erbjuda en uppdatering vars bild inte går att hämta). För en ny version: lägg en ny rubrik överst i
CHANGELOG.md - rör inte config.yaml.

Ändringslogg utan krockar (steg ur uppdelningsplanen): en PR kan i stället lägga en egen liten fil i changelog.d/ (se README där) och inte
röra CHANGELOG.md alls. Releasejobbet (scripts/tillagg.sh) slår ihop fragmenten till nästa version när bilden är byggd:

  addon_version.py next               -> nästa version (översta + 1 i patch)
  addon_version.py succ <ver>         -> versionen efter <ver> (patch + 1)
  addon_version.py compile <ver> <datum> <fragmentfil>...   -> lägger en ny rubrik med fragmentens punkter överst i CHANGELOG.md
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHANGELOG = HERE / "CHANGELOG.md"
CONFIG = HERE / "config.yaml"
_VER = r"(\d+\.\d+\.\d+)"


def changelog_version(text: str | None = None) -> str:
    text = CHANGELOG.read_text(encoding="utf-8") if text is None else text
    m = re.search(rf"^## {_VER}\b", text, re.M)
    if not m:
        raise SystemExit("ingen versionsrubrik (## x.y.z) i CHANGELOG.md")
    return m.group(1)


def config_version(text: str | None = None) -> str:
    text = CONFIG.read_text(encoding="utf-8") if text is None else text
    m = re.search(rf'^version: "{_VER}"', text, re.M)
    if not m:
        raise SystemExit('ingen rad version: "x.y.z" i config.yaml')
    return m.group(1)


def _key(v: str) -> tuple:
    return tuple(int(x) for x in v.split("."))


def next_version(text: str | None = None) -> str:
    """Nästa version: översta versionen i CHANGELOG.md med patch + 1."""
    a, b, c = (int(x) for x in changelog_version(text).split("."))
    return f"{a}.{b}.{c + 1}"


def succ(version: str) -> str:
    a, b, c = (int(x) for x in version.split("."))
    return f"{a}.{b}.{c + 1}"


def fragment_bullets(text: str) -> list[str]:
    """Punkterna i ett fragment: varje punkt börjar med "- " och kan fortsätta på följande rader (indragna eller tomma rader hör till den)."""
    bullets, cur = [], None
    for line in text.replace("\r\n", "\n").split("\n"):
        if line.startswith("- "):
            if cur is not None:
                bullets.append(cur.rstrip())
            cur = line
        elif cur is not None and (line.startswith(" ") or not line.strip()):
            cur += "\n" + line
        elif line.strip():
            raise ValueError(f"fragment: raden måste börja med '- ': {line[:60]!r}")
    if cur is not None:
        bullets.append(cur.rstrip())
    if not bullets:
        raise ValueError("fragment: ingen punkt ('- ...')")
    return bullets


def compile_changelog(text: str, version: str, date: str, fragments: list[tuple[str, str]]) -> str:
    """Lägger en ny rubrik "## version (datum)" med alla fragmentens punkter ovanför den första versionsrubriken. fragments: [(filnamn, text)] i filnamnsordning."""
    if _key(version) <= _key(changelog_version(text)):
        raise ValueError(f"{version} är inte nyare än översta versionen {changelog_version(text)}")
    bullets = []
    for name, body in sorted(fragments):
        try:
            bullets += fragment_bullets(body)
        except ValueError as e:
            raise ValueError(f"{name}: {e}") from None
    entry = f"## {version} ({date})\n" + "\n".join(bullets) + "\n\n"
    m = re.search(rf"^## {_VER}\b", text, re.M)
    return text[:m.start()] + entry + text[m.start():]


def set_version(text: str, version: str, image: str) -> str:
    if _key(version) < _key(config_version(text)):
        raise SystemExit(f"{version} är äldre än config.yaml:s {config_version(text)}")
    text = re.sub(r'^version: ".*"$', f'version: "{version}"', text, count=1, flags=re.M)
    line = f'image: "{image}"'
    if re.search(r"^image:.*$", text, re.M):
        text = re.sub(r"^image:.*$", line, text, count=1, flags=re.M)
    else:
        text = re.sub(r'^(version: ".*")$', lambda m: m.group(1) + "\n" + line, text, count=1, flags=re.M)
    return text


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "changelog":
        print(changelog_version(open(sys.argv[2], encoding="utf-8").read() if len(sys.argv) > 2 else None))
    elif cmd == "newer" and len(sys.argv) == 4:
        sys.exit(0 if _key(sys.argv[2]) > _key(sys.argv[3]) else 1)
    elif cmd == "config":
        print(config_version())
    elif cmd == "next":
        print(next_version())
    elif cmd == "succ" and len(sys.argv) == 3:
        print(succ(sys.argv[2]))
    elif cmd == "compile" and len(sys.argv) >= 5:
        version, date, files = sys.argv[2], sys.argv[3], sys.argv[4:]
        frags = [(Path(p).name, Path(p).read_text(encoding="utf-8")) for p in files]
        CHANGELOG.write_text(compile_changelog(CHANGELOG.read_text(encoding="utf-8"), version, date, frags), encoding="utf-8")
    elif cmd == "set" and len(sys.argv) == 4:
        old = CONFIG.read_text(encoding="utf-8")
        new = set_version(old, sys.argv[2], sys.argv[3])
        if new == old:
            sys.exit(1)
        CONFIG.write_text(new, encoding="utf-8")
    else:
        raise SystemExit(__doc__)
