"""Bevisar: nytt hus -> ett mejl. Samma hus igen -> inget mejl. Mejl av om
SMTP_HOST/ALERT_EMAIL_TO saknas (standardläget). Mockar smtplib helt - rör
aldrig ett riktigt SMTP-nät."""
import importlib
import os
import tempfile
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


def _client(monkeypatch, smtp_host="", alert_to=""):
    db_fd, db_path = tempfile.mkstemp()
    os.close(db_fd)
    os.remove(db_path)
    monkeypatch.setenv("TELEMETRY_DB_PATH", db_path)
    monkeypatch.setenv("SMTP_HOST", smtp_host)
    monkeypatch.setenv("ALERT_EMAIL_TO", alert_to)
    import app as collector_app
    importlib.reload(collector_app)
    return TestClient(collector_app.app), collector_app


def test_nytt_hus_skickar_ett_mejl(monkeypatch):
    client, mod = _client(monkeypatch, smtp_host="smtp.example.com", alert_to="emil@example.com")
    with patch("app.smtplib.SMTP") as mock_smtp:
        instance = MagicMock()
        mock_smtp.return_value.__enter__.return_value = instance
        r = client.post("/ingest/drivers", json={"house": "abc123", "version": "x", "drivers": []})
    assert r.status_code == 200
    instance.send_message.assert_called_once()


def test_samma_hus_igen_skickar_inget_mejl(monkeypatch):
    client, mod = _client(monkeypatch, smtp_host="smtp.example.com", alert_to="emil@example.com")
    with patch("app.smtplib.SMTP") as mock_smtp:
        instance = MagicMock()
        mock_smtp.return_value.__enter__.return_value = instance
        client.post("/ingest/drivers", json={"house": "abc123", "version": "x", "drivers": []})
        client.post("/ingest/drivers", json={"house": "abc123", "version": "x", "drivers": []})
    assert instance.send_message.call_count == 1


def test_av_utan_smtp_konfiguration(monkeypatch):
    client, mod = _client(monkeypatch, smtp_host="", alert_to="")
    with patch("app.smtplib.SMTP") as mock_smtp:
        client.post("/ingest/drivers", json={"house": "nytt-hus", "version": "x", "drivers": []})
    mock_smtp.assert_not_called()


def test_mejlfel_kraschar_inte_ingest(monkeypatch):
    client, mod = _client(monkeypatch, smtp_host="smtp.example.com", alert_to="emil@example.com")
    with patch("app.smtplib.SMTP", side_effect=RuntimeError("timeout")):
        r = client.post("/ingest/drivers", json={"house": "hus-x", "version": "x", "drivers": []})
    assert r.status_code == 200


def test_stats_raknar_aktiva_och_utrustning_utan_husidentiteter(monkeypatch):
    client, _ = _client(monkeypatch)
    a, b = "0123456789abcdef", "fedcba9876543210"
    client.post("/ingest/drivers", json={"house": a, "version": "v1", "drivers": ["heatpump:thermia_husdata", "battery:generic@FoxESS"]})
    client.post("/ingest/drivers", json={"house": a, "version": "v2", "drivers": ["heatpump:thermia_husdata", "battery:generic@FoxESS"]})
    client.post("/ingest/drivers", json={"house": b, "version": "v2", "drivers": ["battery:generic@FoxESS", "car:tesla"]})
    client.post("/ingest/drivers", json={"house": "testverify", "version": "x", "drivers": ["car:nissan"]})
    s = client.get("/api/stats").json()
    assert s["active"] == 2 and s["total_known"] == 2 and s["new_last_7d"] == 2
    assert s["equipment"]["battery"] == {"generic@FoxESS": 2}
    client.post("/ingest/drivers", json={"house": b, "version": "v2", "drivers": ["charger:easee", "charger:easee", "car:tesla"]})
    assert client.get("/api/stats").json()["equipment"]["charger"] == {"easee": 2}
    assert s["equipment"]["heatpump"] == {"thermia_husdata": 1} and "nissan" not in str(s)
    assert s["versions"] == {"v2": 2}
    assert a not in str(s) and b not in str(s)


def test_statistiken_kraver_nyckel_nar_den_ar_satt(monkeypatch):
    monkeypatch.setenv("STATS_TOKEN", "hemlig")
    client, _ = _client(monkeypatch)
    assert client.get("/api/stats").status_code == 403
    assert client.get("/api/recent").status_code == 403
    assert client.get("/api/stats", headers={"X-Stats-Token": "fel"}).status_code == 403
    assert client.get("/api/stats", headers={"X-Stats-Token": "hemlig"}).status_code == 200
    monkeypatch.delenv("STATS_TOKEN")


def test_per_installation_anonymt_och_easee_ihop(monkeypatch):
    client, _ = _client(monkeypatch)
    a, b = "0123456789abcdef", "fedcba9876543210"
    client.post("/ingest/drivers", json={"house": a, "version": "v", "drivers": ["charger:easee", "charger:easee", "car:tesla@Tesla"]})
    client.post("/ingest/drivers", json={"house": b, "version": "v", "drivers": ["charger:easee@Easee", "battery:generic@Solis"]})
    s = client.get("/api/stats", params={"me": a}).json()
    assert s["equipment"]["charger"] == {"easee": 3}
    assert [h["label"] for h in s["houses"]] == ["Hus 1", "Hus 2"] and s["houses"][0]["mine"] and not s["houses"][1]["mine"]
    assert s["houses"][1]["devices"]["battery"] == ["generic@Solis"]
    assert a not in str(s) and b not in str(s)


def test_error_groups_grupperar_utan_hus(monkeypatch):
    monkeypatch.setenv("STATS_TOKEN", "hemlig")
    c, mod = _client(monkeypatch)
    for h in ("a" * 16, "b" * 16, "a" * 16):
        c.post("/ingest/error", json={"house": h, "version": "1.50", "module": "logger.log_data", "error_type": "UndefinedColumn"})
    c.post("/ingest/drivers", json={"house": "a" * 16, "version": "1.50", "drivers": ["battery:generic@Solis"]})
    assert c.get("/api/error-groups").status_code == 403
    g = c.get("/api/error-groups", headers={"X-Stats-Token": "hemlig"}).json()["groups"]
    assert g[0]["key"] == "logger.log_data: UndefinedColumn" and g[0]["houses"] == 2 and g[0]["reports"] == 3
    assert g[0]["versions"] == ["1.50"]
    assert "a" * 16 not in str(g)
    s = c.get("/api/stats", headers={"X-Stats-Token": "hemlig"}).json()
    assert s["error_groups"][0]["versions"] == ["1.50"]
    assert s["houses"][0]["errors"] == ["logger.log_data: UndefinedColumn"] and s["houses"][0]["version"] == "1.50"


def test_installationer_visar_bara_fel_som_kvarstar(monkeypatch):
    """Fel som upphört (inte rapporterat på 75 min) eller hör till en äldre version visas inte."""
    import sqlite3
    from datetime import datetime, timedelta, timezone
    c, mod = _client(monkeypatch)
    h = "c" * 16
    c.post("/ingest/error", json={"house": h, "version": "1.0", "module": "gammal", "error_type": "RattadISenare"})
    c.post("/ingest/error", json={"house": h, "version": "2.0", "module": "nu", "error_type": "Kvarstar"})
    c.post("/ingest/error", json={"house": h, "version": "2.0", "module": "forr", "error_type": "Upphort"})
    c.post("/ingest/drivers", json={"house": h, "version": "2.0", "drivers": ["battery:generic@Solis"]})
    old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    with sqlite3.connect(mod.DB_PATH) as db:
        db.execute("UPDATE errors SET received_at = ? WHERE module = 'forr'", (old,))
    s = c.get("/api/stats").json()
    assert s["houses"][0]["errors"] == ["nu: Kvarstar"]


def test_en_nyckel_per_administrator_och_granskningslogg(monkeypatch):
    monkeypatch.setenv("STATS_TOKENS", "emil:nyckel-e,lazgeo:nyckel-l")
    monkeypatch.delenv("STATS_TOKEN", raising=False)
    c, _ = _client(monkeypatch)
    c.post("/ingest/error", json={"house": "a" * 16, "version": "1.2", "module": "database", "error_type": "X",
                                  "support": "❌ fel i databasen"})
    assert c.get("/api/support").status_code == 403
    assert c.get("/api/support", headers={"X-Stats-Token": "fel"}).status_code == 403
    r = c.get("/api/support", params={"module": "database", "error_type": "X"}, headers={"X-Stats-Token": "nyckel-l"})
    assert r.status_code == 200 and r.json()["items"][0]["support"] == "❌ fel i databasen"
    assert r.json()["items"][0]["house"] == "aaaaaaaa" and "a" * 16 not in str(r.json())       # bara 8 tecken av hashen
    assert c.get("/api/stats", headers={"X-Stats-Token": "nyckel-e"}).status_code == 200
    log = c.get("/api/admin-access", headers={"X-Stats-Token": "nyckel-e"}).json()["items"]
    assert log[0]["admin"] == "lazgeo" and "database: X" in log[0]["detail"]
    assert c.get("/api/admin-access").status_code == 403


def test_gamla_delade_nyckeln_galler_kvar_som_emil(monkeypatch):
    monkeypatch.setenv("STATS_TOKEN", "gammal")
    monkeypatch.delenv("STATS_TOKENS", raising=False)
    c, _ = _client(monkeypatch)
    assert c.get("/api/support", headers={"X-Stats-Token": "gammal"}).status_code == 200
    assert c.get("/api/admin-access", headers={"X-Stats-Token": "gammal"}).json()["items"][0]["admin"] == "emil"
    monkeypatch.delenv("STATS_TOKEN")


def test_loggsidan_innehaller_ingen_data(monkeypatch):
    c, _ = _client(monkeypatch)
    r = c.get("/admin/logs")
    assert r.status_code == 200 and "api/support" in r.text and "❌" not in r.text


def test_felsokningsinfo_far_en_referens_och_bara_administratorer_kan_lasa_den(monkeypatch):
    monkeypatch.setenv("STATS_TOKENS", "emil:nyckel-e,lazgeo:nyckel-l")
    monkeypatch.delenv("STATS_TOKEN", raising=False)
    c, _ = _client(monkeypatch)
    r = c.post("/ingest/support-bundle", json={"house": "a" * 16, "version": "1.2", "text": "❌ fel i databasen\nip 192.168.1.50"})
    ref = r.json()["ref"]
    import re
    assert r.status_code == 200 and re.fullmatch(r"EW-[A-HJ-KM-NP-Z2-9]{5}", ref) and r.json()["expires_days"] == 7
    assert c.get("/api/bundle", params={"ref": ref}).status_code == 403                                      # utan nyckel
    g = c.get("/api/bundle", params={"ref": ref.lower()}, headers={"X-Stats-Token": "nyckel-l"})               # gemener går bra
    assert g.status_code == 200 and "fel i databasen" in g.json()["text"] and g.json()["house"] == "aaaaaaaa"
    assert "192.168.1.50" not in g.json()["text"]                                                              # saneras igen i samlaren
    log = c.get("/api/admin-access", headers={"X-Stats-Token": "nyckel-e"}).json()["items"]
    assert log[0]["admin"] == "lazgeo" and log[0]["what"] == "bundle" and ref in log[0]["detail"]
    assert c.get("/api/bundle", params={"ref": "EW-ZZZZZ"}, headers={"X-Stats-Token": "nyckel-l"}).status_code == 404


def test_tom_logg_nekas_och_gamla_raderas_efter_sju_dagar(monkeypatch):
    c, mod = _client(monkeypatch)
    assert c.post("/ingest/support-bundle", json={"house": "a" * 16, "text": "  \n "}).status_code == 400
    ref = c.post("/ingest/support-bundle", json={"house": "a" * 16, "text": "gammal"}).json()["ref"]
    with mod._db() as conn:
        conn.execute("UPDATE support_bundles SET received_at = '2020-01-01T00:00:00+00:00' WHERE ref = ?", (ref,))
    c.post("/ingest/support-bundle", json={"house": "b" * 16, "text": "ny"})                                    # raderar de gamla
    assert c.get("/api/bundle", params={"ref": ref}).status_code == 404


# ---- veckobrevet: anmälan med dubbel opt-in, avregistrering, skydd mot missbruk ----
def _news(monkeypatch):
    monkeypatch.setenv("SMTP_FROM", "info@example.com")
    client, mod = _client(monkeypatch, smtp_host="smtp.example.com", alert_to="")
    sent = []
    inst = MagicMock()
    inst.send_message.side_effect = lambda m: sent.append(m)
    return client, mod, sent, inst


def _mail_token(msg, kind):
    import re
    body = " ".join(p.get_payload(decode=True).decode() for p in msg.walk() if p.get_content_type() == "text/plain")
    return re.search(rf"/news/{kind}\?t=([A-Za-z0-9_-]+)", body).group(1)


def test_anmalan_kraver_bekraftelse_och_ger_status(monkeypatch):
    client, mod, sent, inst = _news(monkeypatch)
    with patch("app.smtplib.SMTP") as smtp:
        smtp.return_value.__enter__.return_value = inst
        r = client.post("/news/subscribe", json={"email": "Anna@Example.com", "lang": "sv"})
        assert r.status_code == 200 and r.json()["ok"] and r.json()["t"]
        ct = r.json()["t"]
        assert len(sent) == 1 and sent[0]["To"] == "anna@example.com" and "Bekräfta" in sent[0]["Subject"]
        assert sent[0]["From"] == "EnergyWizards skapare <info@example.com>"
        assert client.get("/news/status", params={"t": ct}).json()["status"] == "pending"
        tok = _mail_token(sent[0], "confirm")
        assert "Du är anmäld" not in client.get("/news/confirm", params={"t": "fel"}).text          # fel länk bekräftar inget
        assert client.get("/news/status", params={"t": ct}).json()["status"] == "pending"
        page = client.get("/news/confirm", params={"t": tok})
        assert page.status_code == 200 and "Tack, du är anmäld" in page.text
        assert client.get("/news/status", params={"t": ct}).json()["status"] == "confirmed"


def test_bekraftad_adress_far_ingen_hemlighet_tillbaka_och_inget_nytt_mejl(monkeypatch):
    client, mod, sent, inst = _news(monkeypatch)
    with patch("app.smtplib.SMTP") as smtp:
        smtp.return_value.__enter__.return_value = inst
        ct = client.post("/news/subscribe", json={"email": "a@example.com", "lang": "en"}).json()["t"]
        client.get("/news/confirm", params={"t": _mail_token(sent[0], "confirm")})
        r = client.post("/news/subscribe", json={"email": "a@example.com", "lang": "en"})
        assert r.json() == {"ok": True, "already": True} and len(sent) == 1       # ingen token ut, inget nytt mejl
        # och en främling som känner till adressen kan inte avregistrera den: bara den riktiga hemligheten räcker
        assert client.post("/news/cancel", json={"t": "gissning"}).json()["removed"] is False
        assert client.get("/news/status", params={"t": ct}).json()["status"] == "confirmed"


def test_avregistrering_raderar_adressen_via_lank_ett_klick_och_appen(monkeypatch):
    client, mod, sent, inst = _news(monkeypatch)
    with patch("app.smtplib.SMTP") as smtp:
        smtp.return_value.__enter__.return_value = inst
        for em in ("a@example.com", "b@example.com", "c@example.com"):
            client.post("/news/subscribe", json={"email": em, "lang": "en"})
        toks = [_mail_token(m, "confirm") for m in sent]
        for t in toks:
            client.get("/news/confirm", params={"t": t})
        with mod._db() as c:
            utok = dict(c.execute("SELECT email, token FROM news_subscribers").fetchall())
        # GET visar bara en bekräftelseknapp (en mejlskanner får inte avregistrera någon)
        page = client.get("/news/unsubscribe", params={"t": utok["a@example.com"]})
        assert "Yes, unsubscribe" in page.text
        with mod._db() as c:
            assert c.execute("SELECT COUNT(*) FROM news_subscribers").fetchone()[0] == 3
        # knappen (formulär) raderar raden
        r = client.post("/news/unsubscribe", content=f"t={utok['a@example.com']}", headers={"content-type": "application/x-www-form-urlencoded"})
        assert "You are unsubscribed" in r.text
        # mejlklientens ett-klicks-avregistrering: token i adressen
        r = client.post(f"/news/unsubscribe?t={utok['b@example.com']}", content="List-Unsubscribe=One-Click", headers={"content-type": "application/x-www-form-urlencoded"})
        assert "You are unsubscribed" in r.text
        with mod._db() as c:
            assert [x[0] for x in c.execute("SELECT email FROM news_subscribers").fetchall()] == ["c@example.com"]
        # ogiltig länk: ingenting händer
        assert "not valid" in client.post("/news/unsubscribe", content="t=x", headers={"content-type": "application/x-www-form-urlencoded"}).text


def test_ogiltig_adress_nekas_och_skydd_mot_mejlbomb(monkeypatch):
    client, mod, sent, inst = _news(monkeypatch)
    with patch("app.smtplib.SMTP") as smtp:
        smtp.return_value.__enter__.return_value = inst
        for bad in ("", "x", "a@b", "a b@example.com", "a@@example.com", "a@example..com", "<a>@example.com", "a@example.c", "a" * 300 + "@example.com"):
            assert client.post("/news/subscribe", json={"email": bad}).status_code == 400, bad
        assert client.post("/news/subscribe", data="inte json").status_code == 400
        assert sent == []
        assert client.post("/news/subscribe", json={"email": "x@example.com"}).status_code == 200
        r = client.post("/news/subscribe", json={"email": "x@example.com"})        # samma adress igen inom tio minuter
        assert r.status_code == 429 and len(sent) == 1
        mod.news.HOURLY_MAIL_CAP = 3                                                # timtak för alla adresser
        for i in range(2):
            assert client.post("/news/subscribe", json={"email": f"u{i}@example.com"}).status_code == 200
        assert client.post("/news/subscribe", json={"email": "u9@example.com"}).status_code == 429


def test_sprak_faller_tillbaka_pa_engelska_och_mejlfel_ger_502(monkeypatch):
    client, mod, sent, inst = _news(monkeypatch)
    with patch("app.smtplib.SMTP") as smtp:
        smtp.return_value.__enter__.return_value = inst
        client.post("/news/subscribe", json={"email": "k@example.com", "lang": "xx"})
        assert "Confirm your subscription" in sent[0]["Subject"]
        client.post("/news/subscribe", json={"email": "cz@example.com", "lang": "cs"})
        assert "Potvrďte" in sent[1]["Subject"]
        inst.send_message.side_effect = RuntimeError("smtp nere")
        assert client.post("/news/subscribe", json={"email": "z@example.com"}).status_code == 502


# ---- veckobrevets utskick ----
import json as _json
import news_mail as _nm
import news_send as _ns

_ISSUE = {"id": "2099-w01", "period": {"sv": "1–8 jan", "en": "1–8 Jan"}, "versions": "1.2.1–1.2.9",
          "subject": {"sv": "Veckans nyheter", "en": "This week's news", "cs": "Novinky týdne"}, "preheader": {"en": "pre"},
          "items": {"sv": [["Rubrik <b>", "Text & mer"]], "en": [["Heading", "Body"]]}}


def _issue_file(tmp_path):
    p = tmp_path / "2099-w01.json"
    p.write_text(_json.dumps(_ISSUE), encoding="utf-8")
    return str(p)


def _confirmed(mod, rows):
    with mod._db() as c:
        for em, lang in rows:
            c.execute("INSERT INTO news_subscribers (email, lang, status, token, client_token, created_at) VALUES (?,?,?,?,?,?)",
                      (em, lang, "confirmed", "tok-" + em, "ct-" + em, "x"))
        c.execute("INSERT INTO news_subscribers (email, lang, status, token, client_token, created_at) VALUES (?,?,?,?,?,?)",
                  ("pending@example.com", "en", "pending", "tok-p", "ct-p", "x"))


class _FakeSmtp:
    def __init__(self):
        self.sent = []
    def send_message(self, m):
        self.sent.append(m)
    def quit(self):
        pass


def test_mallen_escapar_text_valjer_sprak_och_har_avregistrering(monkeypatch):
    html = _nm.build_html(_ISSUE, "sv", "https://x/unsub?t=1")
    assert "Rubrik &lt;b&gt;" in html and "Text &amp; mer" in html and "https://x/unsub?t=1" in html
    assert "Avsluta prenumerationen" in html and "Personuppgiftsansvarig" in html and "Familjetavlan" in html and "Strategy Library" in html
    assert "Heading" in _nm.build_html(_ISSUE, "cs", "u")                        # saknat språk: engelska innehåll
    assert "Odhlásit odběr" in _nm.build_html(_ISSUE, "cs", "u")                 # men tjeckiska ramtexter
    assert "Heading" in _nm.build_html(_ISSUE, "xx", "u") and _nm.subject(_ISSUE, "cs") == "Novinky týdne"
    assert "unsub?t=1" in _nm.build_text(_ISSUE, "en", "https://x/unsub?t=1")


def test_utskick_bara_bekraftade_en_gang_per_utgava_med_avregistreringsrubriker(monkeypatch, tmp_path):
    client, mod = _client(monkeypatch)
    _confirmed(mod, [("a@example.com", "sv"), ("b@example.com", "en"), ("c@example.com", "cs")])
    smtp = _FakeSmtp()
    path = _issue_file(tmp_path)
    assert _ns.run(path, go=False, db=mod._db, smtp_factory=lambda: smtp) == (0, 0, 3) and smtp.sent == []      # torrkörning
    assert _ns.run(path, go=True, now=True, sleep=0, db=mod._db, smtp_factory=lambda: smtp) == (3, 0, 0)
    assert sorted(m["To"] for m in smtp.sent) == ["a@example.com", "b@example.com", "c@example.com"]          # inte "pending"
    m = [x for x in smtp.sent if x["To"] == "a@example.com"][0]
    assert m["List-Unsubscribe"].endswith("/news/unsubscribe?t=tok-a@example.com>") and m["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert m["Subject"] == "Veckans nyheter"
    assert _ns.run(path, go=True, now=True, sleep=0, db=mod._db, smtp_factory=lambda: smtp) == (0, 0, 0) and len(smtp.sent) == 3   # aldrig dubbelt
    smtp2 = _FakeSmtp()
    _confirmed_late = ("d@example.com", "en")
    with mod._db() as c:
        c.execute("INSERT INTO news_subscribers (email, lang, status, token, client_token, created_at) VALUES ('d@example.com','en','confirmed','tok-d','ct-d','x')")
    assert _ns.run(path, go=True, now=True, sleep=0, db=mod._db, smtp_factory=lambda: smtp2) == (1, 0, 0)       # bara den nya
    assert [x["To"] for x in smtp2.sent] == ["d@example.com"]


def test_utskick_kraver_torsdag_kl_11_svensk_tid_och_respekterar_hold(monkeypatch, tmp_path):
    from datetime import datetime, timezone
    client, mod = _client(monkeypatch)
    _confirmed(mod, [("a@example.com", "en")])
    path = _issue_file(tmp_path)
    smtp = _FakeSmtp()
    thu_winter = datetime(2026, 11, 26, 10, 0, tzinfo=timezone.utc)      # 11:00 CET
    thu_summer = datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc)          # 11:00 CEST
    assert _ns.in_send_window(thu_winter) and _ns.in_send_window(thu_summer)
    assert not _ns.in_send_window(datetime(2026, 11, 26, 9, 0, tzinfo=timezone.utc))      # 10:00 svensk tid
    assert not _ns.in_send_window(datetime(2026, 11, 27, 10, 0, tzinfo=timezone.utc))     # fredag
    assert _ns.run(path, go=True, sleep=0, db=mod._db, smtp_factory=lambda: smtp, clock=datetime(2026, 11, 26, 9, 0, tzinfo=timezone.utc)) == (0, 0, 0)
    assert smtp.sent == []
    open(path + ".hold", "w").close()
    assert _ns.run(path, go=True, now=True, sleep=0, db=mod._db, smtp_factory=lambda: smtp) == (0, 0, 0) and smtp.sent == []
    os.remove(path + ".hold")
    assert _ns.run(str(tmp_path / "saknas.json"), go=True, now=True, db=mod._db, smtp_factory=lambda: smtp) == (0, 0, 0)
    assert _ns.run(path, go=True, sleep=0, db=mod._db, smtp_factory=lambda: smtp, clock=thu_winter) == (1, 0, 0)


def test_forsta_utgavan_ar_giltig_och_komplett_pa_alla_sprak():
    p = os.path.join(os.path.dirname(__file__), "..", "newsletter", "issues", "2026-w48.json")
    issue = _json.load(open(p, encoding="utf-8"))
    for lang in ("sv", "en", "cs"):
        assert len(issue["items"][lang]) == len(issue["items"]["sv"]) == 7 and issue["subject"][lang] and issue["preheader"][lang]
        assert all(len(x) == 2 and x[0] and x[1] for x in issue["items"][lang])


def test_flik_nyheter_visar_bara_utskickade_utgavor_pa_ratt_sprak(monkeypatch, tmp_path):
    from datetime import datetime, timezone
    client, mod = _client(monkeypatch)
    for iid, sv in (("2026-w47", "Gammal"), ("2026-w48", "Veckans"), ("2026-w49", "Kommande")):
        (tmp_path / f"{iid}.json").write_text(_json.dumps({"id": iid, "period": {"sv": "p", "en": "p"}, "versions": "1.2.1",
                                                          "items": {"sv": [[sv, "text"]], "en": [["EN " + sv, "text"]]}}), encoding="utf-8")
    (tmp_path / "trasig.json").write_text("{inte json", encoding="utf-8")
    (tmp_path / "konstigt-id.json").write_text(_json.dumps({"id": "nej", "items": {"sv": [["x", "y"]]}}), encoding="utf-8")
    mod.news.NEWS_DIR = str(tmp_path); import news_core as _nc; _nc.NEWS_DIR = str(tmp_path)
    mid = datetime(2026, 11, 26, 10, 30, tzinfo=timezone.utc)          # torsdag 11:30 svensk tid: w48 skickad, w49 inte
    got = mod.news.published_issues("sv", now=mid)
    assert [i["id"] for i in got] == ["2026-w48", "2026-w47"] and got[0]["items"] == [["Veckans", "text"]]
    assert [i["id"] for i in mod.news.published_issues("sv", now=datetime(2026, 11, 26, 9, 30, tzinfo=timezone.utc))] == ["2026-w47"]   # före kl 11 syns w48 inte
    assert mod.news.published_issues("cs", now=mid)[0]["items"][0][0] == "EN Veckans"                                                    # saknat språk: engelska
    r = client.get("/news/issues", params={"lang": "en", "limit": 1})
    assert r.status_code == 200 and r.json()["ok"] and len(r.json()["issues"]) <= 1 and "max-age" in r.headers["cache-control"]
    assert mod.news.issue_time("skräp") is None and mod.news.issue_time("2026-w48").isoformat().startswith("2026-11-26T11:00")
