"""Veckobrevet (nyheter varje torsdag kl 11): anmälan, bekräftelse (dubbel opt-in), avregistrering och status.

Bara den som själv skriver in sin e-postadress i EnergyWizard (appens första sida eller installationsguiden) hamnar här, och
först när hen klickar på länken i bekräftelsemejlet räknas det. Adressen används bara till veckobrevet, lämnas inte vidare och
raderas vid avregistrering. Inget hus-ID sparas här, så listan kan inte kopplas till telemetrin.

Två hemligheter per rad: `token` står i mejlens länkar (bekräfta, avregistrera), `client_token` får bara installationen som anmälde sig
(status och avbryt i appen). En bekräftad adress får aldrig tillbaka någon hemlighet, så ingen kan avregistrera andra genom att känna
till adressen.
"""
import html
import os
import secrets
import smtplib
import time
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.parse import parse_qs

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse

from news_core import SCHEMA, SENDS_SCHEMA, BASE, from_header, LANGS, NEWS_DIR, _now, issue_time, published_issues, valid_email  # noqa: F401  (NEWS_DIR m.fl. nås som news.NEWS_DIR i testerna)
RESEND_MIN_S = 600          # samma adress får ett nytt bekräftelsemejl högst var tionde minut
HOURLY_MAIL_CAP = 60        # skydd mot att tjänsten missbrukas för att mejla andra: högst så många bekräftelsemejl per timme
TXT = {
 "sv": dict(subj="Bekräfta din prenumeration på EnergyWizards veckobrev", hi="Hej!",
   body="Du (eller någon som angav din adress) vill få EnergyWizards veckobrev: en kort sammanfattning av nyheterna, varje torsdag kl 11. Klicka på länken för att bekräfta. Har du inte bett om det kan du bara strunta i det här mejlet, då händer inget.",
   btn="Bekräfta prenumerationen", ctl="Personuppgiftsansvarig är EnergyWizards skapare. Din e-postadress används bara för veckobrevet, lämnas inte vidare och raderas när du avslutar prenumerationen.",
   ok_h="Tack, du är anmäld", ok_p="Du får EnergyWizards veckobrev varje torsdag kl 11. Du kan avsluta när som helst med länken längst ner i varje brev.",
   bad_h="Länken gäller inte", bad_p="Länken är ogiltig eller redan använd.",
   un_h="Avsluta prenumerationen?", un_p="Du slutar få EnergyWizards veckobrev och din e-postadress raderas.", un_btn="Ja, avsluta",
   unok_h="Du är avregistrerad", unok_p="Din e-postadress är raderad och du får inga fler veckobrev."),
 "en": dict(subj="Confirm your subscription to the EnergyWizard weekly letter", hi="Hello!",
   body="You (or someone who entered your address) want to get the EnergyWizard weekly letter: a short summary of the news, every Thursday at 11:00 (Swedish time). Click the link to confirm. If you did not ask for it, just ignore this email and nothing happens.",
   btn="Confirm subscription", ctl="The data controller is EnergyWizard's creator. Your email address is used only for the weekly letter, is not passed on, and is deleted when you unsubscribe.",
   ok_h="Thanks, you are subscribed", ok_p="You will get the EnergyWizard weekly letter every Thursday at 11:00 (Swedish time). You can unsubscribe at any time with the link at the bottom of each letter.",
   bad_h="The link is not valid", bad_p="The link is invalid or has already been used.",
   un_h="Unsubscribe?", un_p="You stop getting the EnergyWizard weekly letter and your email address is deleted.", un_btn="Yes, unsubscribe",
   unok_h="You are unsubscribed", unok_p="Your email address is deleted and you will get no more weekly letters."),
 "cs": dict(subj="Potvrďte odběr týdenního zpravodaje EnergyWizard", hi="Dobrý den!",
   body="Vy (nebo někdo, kdo zadal vaši adresu) chcete dostávat týdenní zpravodaj EnergyWizard: krátké shrnutí novinek každý čtvrtek v 11:00 (švédského času). Potvrďte odkazem. Pokud jste o něj nežádali, tento e-mail ignorujte, nic se nestane.",
   btn="Potvrdit odběr", ctl="Správcem osobních údajů je tvůrce EnergyWizard. Vaše e-mailová adresa se používá pouze pro týdenní zpravodaj, nepředává se dál a po odhlášení se smaže.",
   ok_h="Děkujeme, odběr je potvrzen", ok_p="Týdenní zpravodaj EnergyWizard budete dostávat každý čtvrtek v 11:00 (švédského času). Odhlásit se můžete kdykoli odkazem na konci každého zpravodaje.",
   bad_h="Odkaz neplatí", bad_p="Odkaz je neplatný nebo už byl použit.",
   un_h="Odhlásit odběr?", un_p="Přestanete dostávat týdenní zpravodaj EnergyWizard a vaše e-mailová adresa bude smazána.", un_btn="Ano, odhlásit",
   unok_h="Odběr je zrušen", unok_p="Vaše e-mailová adresa je smazána a už nedostanete žádný zpravodaj."),
}


def _page(lang: str, head: str, para: str, form: str = "") -> HTMLResponse:
    return HTMLResponse(f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
                        f'<title>EnergyWizard</title></head><body style="margin:0;background:#f1f5f9;font-family:Inter,Arial,sans-serif;color:#0f172a">'
                        f'<div style="max-width:480px;margin:40px auto;padding:0 16px"><div style="font-size:22px;font-weight:700;margin-bottom:14px">Energy<span style="color:#04ce78">Wizard</span></div>'
                        f'<div style="background:#fff;border:1px solid #e8eef3;border-radius:18px;padding:24px"><h1 style="font-size:22px;margin:0 0 10px">{html.escape(head)}</h1>'
                        f'<p style="line-height:1.5;color:#475569">{html.escape(para)}</p>{form}</div></div></body></html>')


def register(app, db, smtp_send):
    """Lägger in anmälningsvägarna i samlaren. `db` är samlarens databaskontext, `smtp_send(msg)` skickar ett färdigt mejl."""

    def confirm_mail(email, lang, token):
        t = TXT[lang]
        link = f"{BASE}/news/confirm?t={token}"
        msg = MIMEMultipart("alternative")
        msg["Subject"] = t["subj"]
        msg["To"] = email
        plain = f"{t['hi']}\n\n{t['body']}\n\n{link}\n\n{t['ctl']}\n"
        msg.attach(MIMEText(plain, "plain", "utf-8"))
        msg.attach(MIMEText(
            f'<div style="font-family:Inter,Arial,sans-serif;max-width:520px;color:#0f172a"><p>{html.escape(t["hi"])}</p><p style="line-height:1.5">{html.escape(t["body"])}</p>'
            f'<p><a href="{link}" style="display:inline-block;background:#04ce78;color:#04210f;font-weight:700;text-decoration:none;padding:12px 20px;border-radius:12px">{html.escape(t["btn"])}</a></p>'
            f'<p style="font-size:12px;color:#64748b;line-height:1.5">{html.escape(t["ctl"])}</p></div>', "html", "utf-8"))
        smtp_send(msg)

    @app.post("/news/subscribe")
    async def subscribe(request: Request):
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"ok": False, "error": "bad request"}, status_code=400)
        email = str((body or {}).get("email") or "").strip().lower()
        lang = str((body or {}).get("lang") or "en")[:2].lower()
        lang = lang if lang in LANGS else "en"
        if not valid_email(email):
            return JSONResponse({"ok": False, "error": "invalid email"}, status_code=400)
        now = time.time()
        with db() as c:
            row = c.execute("SELECT status, last_confirm_mail FROM news_subscribers WHERE email = ?", (email,)).fetchone()
            if row and row[0] == "confirmed":
                return {"ok": True, "already": True}
            recent = c.execute("SELECT COUNT(*) FROM news_subscribers WHERE last_confirm_mail > ?", (now - 3600,)).fetchone()[0]
            if recent >= HOURLY_MAIL_CAP:
                return JSONResponse({"ok": False, "error": "busy, try again later"}, status_code=429)
            if row and row[1] and now - row[1] < RESEND_MIN_S:
                return JSONResponse({"ok": False, "error": "wait a few minutes before asking for a new email"}, status_code=429)
            token, ctoken = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
            if row:
                c.execute("UPDATE news_subscribers SET lang=?, status='pending', token=?, client_token=?, unsubscribed_at=NULL, last_confirm_mail=? WHERE email=?",
                          (lang, token, ctoken, now, email))
            else:
                c.execute("INSERT INTO news_subscribers (email, lang, status, token, client_token, created_at, last_confirm_mail) VALUES (?,?,?,?,?,?,?)",
                          (email, lang, "pending", token, ctoken, _now(), now))
        try:
            confirm_mail(email, lang, token)
        except Exception as e:
            print(f"❌ Kunde inte skicka bekräftelsemejl: {type(e).__name__}")
            return JSONResponse({"ok": False, "error": "could not send email"}, status_code=502)
        return {"ok": True, "t": ctoken}

    @app.get("/news/confirm")
    async def confirm(t: str = ""):
        with db() as c:
            row = c.execute("SELECT email, lang, status FROM news_subscribers WHERE token = ?", (t,)).fetchone() if t else None
            if row and row[2] in ("pending", "confirmed"):
                c.execute("UPDATE news_subscribers SET status='confirmed', confirmed_at=COALESCE(confirmed_at, ?) WHERE email=?", (_now(), row[0]))
                lang = row[1] if row[1] in TXT else "en"
                return _page(lang, TXT[lang]["ok_h"], TXT[lang]["ok_p"])
        return _page("en", TXT["en"]["bad_h"], TXT["en"]["bad_p"])

    def _unsub(c, where, val):
        row = c.execute(f"SELECT email, lang FROM news_subscribers WHERE {where} = ?", (val,)).fetchone() if val else None
        if not row:
            return None
        c.execute("DELETE FROM news_subscribers WHERE email = ?", (row[0],))       # raderas: inget behålls efter avregistrering
        return row[1] if row[1] in TXT else "en"

    @app.get("/news/unsubscribe")
    async def unsubscribe_page(t: str = ""):
        with db() as c:
            row = c.execute("SELECT lang FROM news_subscribers WHERE token = ?", (t,)).fetchone() if t else None
        if not row:
            return _page("en", TXT["en"]["bad_h"], TXT["en"]["bad_p"])
        lang = row[0] if row[0] in TXT else "en"
        x = TXT[lang]
        form = (f'<form method="post" action="{BASE}/news/unsubscribe"><input type="hidden" name="t" value="{html.escape(t)}">'
                f'<button style="background:#0f172a;color:#fff;border:0;border-radius:12px;padding:12px 20px;font-weight:700;font-size:15px;cursor:pointer">{html.escape(x["un_btn"])}</button></form>')
        return _page(lang, x["un_h"], x["un_p"], form)

    @app.post("/news/unsubscribe")
    async def unsubscribe_post(request: Request):
        """Knappen på sidan och mejlklienternas ett-klicks-avregistrering (List-Unsubscribe-Post). Token i adressen eller formuläret."""
        t = request.query_params.get("t", "")
        if not t:                                   # formuläret på sidan (utan python-multipart): t=<token>
            try:
                t = parse_qs((await request.body()).decode("utf-8", "replace")).get("t", [""])[0]
            except Exception:
                t = ""
        with db() as c:
            lang = _unsub(c, "token", t)
        if lang is None:
            return _page("en", TXT["en"]["bad_h"], TXT["en"]["bad_p"])
        return _page(lang, TXT[lang]["unok_h"], TXT[lang]["unok_p"])

    @app.get("/news/issues")
    async def issues(lang: str = "en", limit: int = 8):
        """Det utskickade veckobrevets innehåll, för fliken Nyheter i appen och webben. Publikt (samma text som i mejlet), inga personuppgifter."""
        return JSONResponse({"ok": True, "issues": published_issues(lang if lang in LANGS else "en", limit)},
                            headers={"Cache-Control": "public, max-age=300"})

    @app.get("/news/status")
    async def status(t: str = ""):
        with db() as c:
            row = c.execute("SELECT status FROM news_subscribers WHERE client_token = ?", (t,)).fetchone() if t else None
        return {"ok": True, "status": row[0] if row else "none"}

    @app.post("/news/cancel")
    async def cancel(request: Request):
        """Appens knapp Avsluta (med installationens egen hemlighet)."""
        try:
            t = str(((await request.json()) or {}).get("t") or "")
        except Exception:
            t = ""
        with db() as c:
            done = _unsub(c, "client_token", t) is not None
        return {"ok": True, "removed": done}
