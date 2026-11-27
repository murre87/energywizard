"""Beror på-kontrollen: raderna tolkas rätt, och en PR som beror på en ej mergad PR blockeras."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import check_depends_on as c  # noqa: E402


def test_parse_lines_and_references():
    body = "Text\nBeror på: murre87/energywizard-drivers#12, #7\nberor pa: x\nDepends on: a/b#3\n  Beror på:  #7"
    assert c.parse(body, "murre87/energywizard") == [("murre87/energywizard-drivers", 12), ("murre87/energywizard", 7), ("a/b", 3)]
    assert c.parse("Beror på: ingen", "o/r") == [] and c.parse(None, "o/r") == [] and c.parse("Se #5 för bakgrund", "o/r") == []


def test_blockers():
    prs = {("o/r", 1): {"merged": True}, ("o/r", 2): {"merged": False, "state": "open", "title": "öppen"},
           ("o/r", 3): {"merged": False, "state": "closed", "title": "avvisad"}}

    def fetch(path):
        _, repo_owner, repo, _, num = path.split("/")
        return prs[(f"{repo_owner}/{repo}", int(num))]
    assert c.blockers([("o/r", 1)], fetch) == []
    got = c.blockers([("o/r", 1), ("o/r", 2), ("o/r", 3), ("o/r", 4)], fetch)
    assert len(got) == 3 and "inte mergad än" in got[0] and "stängd utan merge" in got[1] and "kunde inte läsas" in got[2]
