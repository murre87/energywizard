"""Skickar veckobrevet till bekräftade prenumeranter. Körs i samlarens container, från värdens cron:

    docker exec telemetry-collector python news_send.py /data/news/2026-w48.json            # torrkörning (skickar inget)
    docker exec telemetry-collector python news_send.py /data/news/2026-w48.json --go       # skickar på riktigt, men bara torsdag kl 11 svensk tid
    ... --go --now                                                                           # skickar oavsett tid (provutskick, manuellt)
    ... --go --now --only a@b.se,c@d.se                                                      # bara dessa (måste vara bekräftade)

Cron går två gånger (09 och 10 UTC): bara den körning där klockan i Stockholm är 11 skickar, så sommar- och vintertid sköter sig själva.
Varje (utgåva, adress) skickas högst en gång. Finns ingen veckofil, eller ligger en `.hold` bredvid den, skickas inget.
"""
import argparse
import json
import os
import smtplib
import sys
import time
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo

import news_core
import news_mail


def in_send_window(now=None):
    n = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo("Europe/Stockholm"))
    return n.weekday() == 3 and n.hour == 11


def build_message(issue, row, smtp_from):
    email, lang, token = row
    lang = lang if lang in news_mail.LABELS else "en"
    unsub = f"{news_core.BASE}/news/unsubscribe?t={token}"
    msg = MIMEMultipart("alternative")
    msg["Subject"] = news_mail.subject(issue, lang)
    msg["From"] = news_core.from_header(smtp_from)
    msg["To"] = email
    msg["List-Unsubscribe"] = f"<{news_core.BASE}/news/unsubscribe?t={token}>"
    msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    msg.attach(MIMEText(news_mail.build_text(issue, lang, unsub), "plain", "utf-8"))
    msg.attach(MIMEText(news_mail.build_html(issue, lang, unsub), "html", "utf-8"))
    return msg


def run(path, go=False, now=False, only=None, sleep=0.5, db=None, smtp_factory=None, clock=None):
    """Returnerar (skickade, fel, hoppade). `db` och `smtp_factory` kan bytas i tester."""
    if db is None:
        import app as collector
        db = collector._db
    if not os.path.exists(path):
        print(f"Ingen veckofil ({path}): inget skickas.")
        return 0, 0, 0
    if os.path.exists(path + ".hold") or os.path.exists(os.path.join(os.path.dirname(path), ".hold")):
        print("Spärrfil (.hold) finns: inget skickas.")
        return 0, 0, 0
    issue = json.load(open(path, encoding="utf-8"))
    iid = str(issue.get("id") or os.path.basename(path))
    if go and not now and not in_send_window(clock):
        print("Inte torsdag kl 11 svensk tid: inget skickas.")
        return 0, 0, 0
    with db() as c:
        rows = c.execute("SELECT email, lang, token FROM news_subscribers WHERE status='confirmed' ORDER BY email").fetchall()
        done = {r[0] for r in c.execute("SELECT email FROM news_sends WHERE issue = ?", (iid,)).fetchall()}
    if only:
        rows = [r for r in rows if r[0] in only]
    todo = [r for r in rows if r[0] not in done]
    by = {}
    for r in todo:
        by[r[1]] = by.get(r[1], 0) + 1
    print(f"utgåva {iid}: bekräftade {len(rows)}, redan skickat {len(rows) - len(todo)}, att skicka {len(todo)} {by}")
    if not go:
        print("torrkörning – inget skickat")
        return 0, 0, len(todo)
    host, port = os.environ.get("SMTP_HOST", ""), int(os.environ.get("SMTP_PORT", "587") or 587)
    user, pw = os.environ.get("SMTP_USER", ""), os.environ.get("SMTP_PASSWORD", "")
    frm = os.environ.get("SMTP_FROM", "").strip() or user
    ok = fail = 0
    smtp = (smtp_factory or (lambda: smtplib.SMTP(host, port, timeout=30)))()
    try:
        if not smtp_factory:
            smtp.starttls()
            if user:
                smtp.login(user, pw)
        for r in todo:
            try:
                smtp.send_message(build_message(issue, r, frm))
                with db() as c:                                           # markeras direkt, så en avbruten körning inte skickar dubbelt
                    c.execute("INSERT OR IGNORE INTO news_sends (issue, email, at) VALUES (?,?,?)", (iid, r[0], news_core._now()))
                ok += 1
            except Exception as ex:
                fail += 1
                print("FEL", type(ex).__name__)
            time.sleep(sleep)
    finally:
        try:
            smtp.quit()
        except Exception:
            pass
    print(f"skickade {ok} fel {fail}")
    return ok, fail, 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("issue")
    ap.add_argument("--go", action="store_true")
    ap.add_argument("--now", action="store_true")
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    ok, fail, _ = run(a.issue, a.go, a.now, {x.strip().lower() for x in a.only.split(",") if x.strip()} or None)
    sys.exit(1 if fail else 0)
