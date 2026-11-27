"""Veckobrevets rena logik, utan fastapi (telemetry-collector/news_core.py, news_mail.py, news_send.py): adresskontroll, utgåvornas
tider, mallen och utskicket. Samlarens ändpunkter (news.py) testas i telemetry-collector/test_app.py."""
import json
import os
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pytest

COLLECTOR = Path(__file__).resolve().parents[1] / "telemetry-collector"
sys.path.insert(0, str(COLLECTOR))
import news_core as nc  # noqa: E402
import news_mail as nm  # noqa: E402
import news_send as ns  # noqa: E402
sys.path.remove(str(COLLECTOR))        # samlarens app.py får inte skugga ewapp/webdashboard för senare tester i samma körning

ISSUE = {"id": "2099-w01", "period": {"sv": "1–8 jan", "en": "1–8 Jan"}, "versions": "1.2.1–1.2.9",
         "subject": {"sv": "Veckans nyheter", "en": "This week's news", "cs": "Novinky týdne"}, "preheader": {"en": "pre"},
         "items": {"sv": [["Rubrik <b>", "Text & mer"]], "en": [["Heading", "Body"]]}}


def test_avsandaren_ar_skaparen_och_behaller_bara_adressen():
    assert nc.from_header("info@example.com") == "EnergyWizards skapare <info@example.com>"
    assert nc.from_header("Någon Annan <info@example.com>") == "EnergyWizards skapare <info@example.com>"
    assert nc.from_header("") == "" and nc.from_header(None) == ""


def test_adresskontroll():
    assert nc.valid_email("anna@example.com") and nc.valid_email("a.b+c@sub.example.se")
    for bad in ("", None, "x", "a@b", "a b@example.com", "a@@example.com", "a@example..com", ".a@example.com", "<a>@example.com", "a@-x.com", "a@example.c", "a" * 300 + "@example.com"):
        assert not nc.valid_email(bad), bad


def test_utgavans_tid_och_vilka_som_visas(tmp_path):
    assert nc.issue_time("skräp") is None and nc.issue_time("2026-w48").isoformat().startswith("2026-11-26T11:00")
    for iid, sv in (("2026-w47", "Gammal"), ("2026-w48", "Veckans"), ("2026-w49", "Kommande")):
        (tmp_path / f"{iid}.json").write_text(json.dumps({"id": iid, "period": {"sv": "p"}, "versions": "1.2.1",
                                                         "items": {"sv": [[sv, "text"]], "en": [["EN " + sv, "text"]]}}), encoding="utf-8")
    (tmp_path / "trasig.json").write_text("{inte json", encoding="utf-8")
    (tmp_path / "konstigt.json").write_text(json.dumps({"id": "nej", "items": {"sv": [["x", "y"]]}}), encoding="utf-8")
    mid = datetime(2026, 11, 26, 10, 30, tzinfo=timezone.utc)                       # torsdag 11:30 svensk tid
    got = nc.published_issues("sv", now=mid, folder=str(tmp_path))
    assert [i["id"] for i in got] == ["2026-w48", "2026-w47"] and got[0]["items"] == [["Veckans", "text"]]
    assert [i["id"] for i in nc.published_issues("sv", now=datetime(2026, 11, 26, 9, 30, tzinfo=timezone.utc), folder=str(tmp_path))] == ["2026-w47"]
    assert nc.published_issues("cs", now=mid, folder=str(tmp_path))[0]["items"][0][0] == "EN Veckans"        # saknat språk: engelska
    assert len(nc.published_issues("sv", limit=1, now=mid, folder=str(tmp_path))) == 1


def test_mallen_escapar_valjer_sprak_och_har_avregistrering():
    html = nm.build_html(ISSUE, "sv", "https://x/unsub?t=1")
    assert "Rubrik &lt;b&gt;" in html and "Text &amp; mer" in html and "https://x/unsub?t=1" in html
    assert "Avsluta prenumerationen" in html and "Personuppgiftsansvarig" in html and "Familjetavlan" in html and "Strategy Library" in html
    assert "Heading" in nm.build_html(ISSUE, "cs", "u") and "Odhlásit odběr" in nm.build_html(ISSUE, "cs", "u")
    assert "Heading" in nm.build_html(ISSUE, "xx", "u") and nm.subject(ISSUE, "cs") == "Novinky týdne"
    assert "unsub?t=1" in nm.build_text(ISSUE, "en", "https://x/unsub?t=1")


class FakeSmtp:
    def __init__(self):
        self.sent = []

    def send_message(self, m):
        self.sent.append(m)

    def quit(self):
        pass


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "t.sqlite3")

    @contextmanager
    def ctx():
        c = sqlite3.connect(path)
        c.execute(nc.SCHEMA)
        c.execute(nc.SENDS_SCHEMA)
        try:
            yield c
            c.commit()
        finally:
            c.close()
    with ctx() as c:
        for em, lang, st in (("a@example.com", "sv", "confirmed"), ("b@example.com", "en", "confirmed"), ("c@example.com", "cs", "confirmed"), ("p@example.com", "en", "pending")):
            c.execute("INSERT INTO news_subscribers (email, lang, status, token, client_token, created_at) VALUES (?,?,?,?,?,?)", (em, lang, st, "tok-" + em, "ct-" + em, "x"))
    return ctx


def _issue(tmp_path):
    p = tmp_path / "2099-w01.json"
    p.write_text(json.dumps(ISSUE), encoding="utf-8")
    return str(p)


def test_utskick_bara_bekraftade_en_gang_per_utgava(db, tmp_path, monkeypatch):
    monkeypatch.setenv("SMTP_FROM", "info@example.com")
    smtp, path = FakeSmtp(), _issue(tmp_path)
    assert ns.run(path, go=False, db=db, smtp_factory=lambda: smtp) == (0, 0, 3) and smtp.sent == []
    assert ns.run(path, go=True, now=True, sleep=0, db=db, smtp_factory=lambda: smtp) == (3, 0, 0)
    assert sorted(m["To"] for m in smtp.sent) == ["a@example.com", "b@example.com", "c@example.com"]          # inte "pending"
    m = [x for x in smtp.sent if x["To"] == "a@example.com"][0]
    assert m["List-Unsubscribe"].endswith("/news/unsubscribe?t=tok-a@example.com>") and m["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert m["Subject"] == "Veckans nyheter"
    assert m["From"] == "EnergyWizards skapare <info@example.com>"              # avsändaren är skaparen (Emil 2026-11-27)
    assert ns.run(path, go=True, now=True, sleep=0, db=db, smtp_factory=lambda: smtp) == (0, 0, 0) and len(smtp.sent) == 3
    with db() as c:
        c.execute("INSERT INTO news_subscribers (email, lang, status, token, client_token, created_at) VALUES ('d@example.com','en','confirmed','tok-d','ct-d','x')")
    smtp2 = FakeSmtp()
    assert ns.run(path, go=True, now=True, sleep=0, db=db, smtp_factory=lambda: smtp2) == (1, 0, 0) and [x["To"] for x in smtp2.sent] == ["d@example.com"]
    smtp3 = FakeSmtp()
    assert ns.run(path, go=True, now=True, sleep=0, only={"zzz@example.com"}, db=db, smtp_factory=lambda: smtp3) == (0, 0, 0) and smtp3.sent == []


def test_utskick_en_trasig_mottagare_stoppar_inte_resten(db, tmp_path):
    class Flaky(FakeSmtp):
        def send_message(self, m):
            if m["To"] == "b@example.com":
                raise OSError("avvisad")
            super().send_message(m)
    smtp = Flaky()
    assert ns.run(_issue(tmp_path), go=True, now=True, sleep=0, db=db, smtp_factory=lambda: smtp) == (2, 1, 0)
    with db() as c:
        assert sorted(r[0] for r in c.execute("SELECT email FROM news_sends")) == ["a@example.com", "c@example.com"]   # den misslyckade kan försöka igen


def test_utskick_bara_torsdag_11_svensk_tid_och_hold(db, tmp_path):
    path, smtp = _issue(tmp_path), FakeSmtp()
    winter, summer = datetime(2026, 11, 26, 10, 0, tzinfo=timezone.utc), datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc)
    assert ns.in_send_window(winter) and ns.in_send_window(summer)
    assert not ns.in_send_window(datetime(2026, 11, 26, 9, 0, tzinfo=timezone.utc)) and not ns.in_send_window(datetime(2026, 11, 27, 10, 0, tzinfo=timezone.utc))
    assert ns.run(path, go=True, sleep=0, db=db, smtp_factory=lambda: smtp, clock=datetime(2026, 11, 26, 9, 0, tzinfo=timezone.utc)) == (0, 0, 0) and smtp.sent == []
    open(path + ".hold", "w").close()
    assert ns.run(path, go=True, now=True, sleep=0, db=db, smtp_factory=lambda: smtp) == (0, 0, 0) and smtp.sent == []
    os.remove(path + ".hold")
    assert ns.run(str(tmp_path / "saknas.json"), go=True, now=True, db=db, smtp_factory=lambda: smtp) == (0, 0, 0)
    assert ns.run(path, go=True, sleep=0, db=db, smtp_factory=lambda: smtp, clock=winter) == (3, 0, 0)


def test_forsta_utgavan_ar_giltig_och_komplett_pa_alla_sprak():
    issue = json.load(open(Path(__file__).resolve().parents[1] / "newsletter" / "issues" / "2026-w48.json", encoding="utf-8"))
    for lang in ("sv", "en", "cs"):
        assert len(issue["items"][lang]) == len(issue["items"]["sv"]) == 7 and issue["subject"][lang] and issue["preheader"][lang]
        assert all(len(x) == 2 and x[0] and x[1] for x in issue["items"][lang])
    assert nc.issue_time(issue["id"]).isoformat().startswith("2026-11-26T11:00")
