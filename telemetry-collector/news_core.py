"""Veckobrevets rena logik (ingen fastapi): adresskontroll, när en utgåva skickas och vilka som är utskickade. Delas av samlarens
ändpunkter (news.py), utskickaren (news_send.py) och testerna i den vanliga sviten."""
import glob
import json
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

SENDER_NAME = "EnergyWizards skapare"          # avsändarnamnet i veckobrevets mejl (Emil 2026-11-27): skaparen, inte en funktionsadress
LANGS = ("sv", "en", "cs")
BASE = os.environ.get("NEWS_BASE_URL", "https://energywizzard.profitalgos.com/telemetry").rstrip("/")
NEWS_DIR = os.environ.get("NEWS_DIR", "/data/news")


SCHEMA = """CREATE TABLE IF NOT EXISTS news_subscribers (
    email TEXT PRIMARY KEY, lang TEXT, status TEXT, token TEXT UNIQUE, client_token TEXT UNIQUE,
    created_at TEXT, confirmed_at TEXT, unsubscribed_at TEXT, last_confirm_mail REAL)"""
SENDS_SCHEMA = """CREATE TABLE IF NOT EXISTS news_sends (issue TEXT, email TEXT, at TEXT, PRIMARY KEY (issue, email))"""


def issue_time(issue_id):
    """När en utgåva skickas: torsdag kl 11 svensk tid den ISO-vecka id:t (ÅÅÅÅ-wVV) anger. None om id:t inte går att tolka."""
    try:
        y, w = str(issue_id).lower().split("-w")
        d = datetime.fromisocalendar(int(y), int(w), 4)
        return d.replace(hour=11, tzinfo=ZoneInfo("Europe/Stockholm"))
    except Exception:
        return None


def published_issues(lang, limit=8, now=None, folder=None):
    """Utgåvor vars torsdag kl 11 passerat, nyast först, med texterna på språket (annars engelska). Kommande utgåvor syns aldrig."""
    now = now or datetime.now(timezone.utc)
    out = []
    for path in glob.glob(os.path.join(folder or NEWS_DIR, "*.json")):
        try:
            issue = json.load(open(path, encoding="utf-8"))
        except Exception:
            continue
        iid = str(issue.get("id") or os.path.basename(path)[:-5])
        t = issue_time(iid)
        if t is None or t > now:
            continue
        def pick(d):
            return (d.get(lang) or d.get("en") or next(iter(d.values()), None)) if isinstance(d, dict) else None
        items = [[str(a), str(b)] for a, b in (pick(issue.get("items")) or []) if a]
        out.append({"id": iid, "period": pick(issue.get("period")) or "", "versions": issue.get("versions") or "", "items": items, "_t": t})
    out.sort(key=lambda x: x["_t"], reverse=True)
    for x in out:
        del x["_t"]
    return out[:max(1, min(int(limit), 26))]


def valid_email(e) -> bool:
    """Enkel, linjär kontroll (inga regex): en @, rimliga delar, punkt i domänen, inga blanksteg eller kontrolltecken."""
    if not isinstance(e, str) or not 6 <= len(e) <= 254 or e.count("@") != 1:
        return False
    if any(c.isspace() or ord(c) < 32 or c in '<>(),;:"\\[]' for c in e):
        return False
    local, domain = e.split("@")
    if not 1 <= len(local) <= 64 or ".." in e or local[0] == "." or local[-1] == ".":
        return False
    labels = domain.split(".")
    if len(labels) < 2 or any(not l or len(l) > 63 or l[0] == "-" or l[-1] == "-" for l in labels) or len(labels[-1]) < 2:
        return False
    return True


def from_header(addr) -> str:
    """Avsändaren: "EnergyWizards skapare <adress>". Ett namn som redan står i SMTP_FROM byts ut, så adressen är den enda delen som behålls."""
    from email.utils import formataddr, parseaddr
    a = parseaddr(str(addr or ""))[1]
    return formataddr((SENDER_NAME, a)) if a else ""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
