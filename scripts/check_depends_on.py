"""Beror på-kontrollen (docs/uppdelning/PLAN.md, "Så håller vi ihop releaserna", punkt 4).

En PR som beror på en annan skriver en rad i beskrivningen:

    Beror på: murre87/energywizard-drivers#12      (eller bara #123 för en PR i samma repo)

Kontrollen blir röd tills varje PR den pekar på är mergad (eller stängd utan merge: då måste raden tas bort). Utan sådana rader är den grön.
Flera rader eller flera referenser på en rad går bra."""
import json
import os
import re
import sys
from urllib.request import Request, urlopen

LINE = re.compile(r"^\s*(?:beror på|depends on)\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
REF = re.compile(r"(?:([\w.-]+/[\w.-]+))?#(\d+)")


def parse(body: str, this_repo: str):
    """[(repo, nummer)] ur PR-beskrivningen."""
    out = []
    for m in LINE.finditer(body or ""):
        for repo, num in REF.findall(m.group(1)):
            ref = (repo or this_repo, int(num))
            if ref not in out:
                out.append(ref)
    return out


def blockers(refs, fetch):
    """De beroenden som inte är mergade, med orsak."""
    out = []
    for repo, num in refs:
        try:
            pr = fetch(f"repos/{repo}/pulls/{num}")
        except Exception as e:
            out.append(f"{repo}#{num}: kunde inte läsas ({type(e).__name__})")      # kan inte avgöra: släpp inte igenom
            continue
        if pr.get("merged"):
            continue
        out.append(f"{repo}#{num}: {'stängd utan merge' if pr.get('state') == 'closed' else 'inte mergad än'} ({pr.get('title', '')})")
    return out


def main():
    def fetch(path):
        req = Request(os.environ["GITHUB_API_URL"] + "/" + path,
                      headers={"Authorization": "Bearer " + os.environ["GH_TOKEN"], "Accept": "application/vnd.github+json"})
        with urlopen(req, timeout=15) as r:
            return json.load(r)

    with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as f:
        event = json.load(f)
    repo = os.environ["GITHUB_REPOSITORY"]
    pr = event.get("pull_request")
    if not pr:
        print("Ingen PR: inget att kontrollera.")
        return 0
    refs = parse(pr.get("body") or "", repo)
    if not refs:
        print("Inga 'Beror på'-rader.")
        return 0
    bad = blockers(refs, fetch)
    if bad:
        print("Den här PR:en beror på ändringar som inte är mergade:\n  " + "\n  ".join(bad))
        return 1
    print("Alla beroenden är mergade: " + ", ".join(f"{r}#{n}" for r, n in refs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
