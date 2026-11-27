"""
easee_account.py - Easee-konto och laddboxens egen laddningshistorik (#605).

Easees moln har månadssummor långt bakåt i tiden. De är laddboxens mätare och går före EnergyWizards
uppskattning av elbilens last. Anropen är kraftigt begränsade (månadsvyn högst 10 gånger i timmen,
listan över laddboxar högst 2 gånger i minuten), så resultatet sparas och hämtas om högst en gång per dygn.

Lösenordet och token sparas i samma inställningsfil som Home Assistant-token (ew_settings) och skickas
aldrig tillbaka till webben. Nätanropen går genom en funktion som testerna byter ut, så inget test
pratar med Easee.

Dokumentation: https://developer.easee.com (login, refresh_token, /api/chargers, månadssummering).
"""

import re
from datetime import datetime, timedelta, timezone

BASE = "https://api.easee.com"
MAX_CHARGERS = 8                 # ett listanrop + åtta månadsanrop håller sig under gränsen 10/timme
AUTO_AGE = timedelta(hours=20)
MANUAL_AGE = timedelta(minutes=15)
_ID = re.compile(r"^[A-Za-z0-9]{4,32}$")


class EaseeError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def requests_http(method, path, body=None, token=None, timeout=15):
    """Ett anrop mot api.easee.com. Kastar EaseeError vid nätfel. Svarets text loggas inte."""
    import requests
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    try:
        response = requests.request(method, BASE + path, json=body, headers=headers, timeout=timeout)
    except requests.RequestException:
        raise EaseeError("Fick inget svar från Easee") from None
    try:
        data = response.json()
    except ValueError:
        data = None
    return response.status_code, data


def parse_token(body):
    if not isinstance(body, dict) or not body.get("accessToken"):
        raise EaseeError("Easee svarade utan en nyckel")
    return {"access_token": body["accessToken"], "refresh_token": body.get("refreshToken") or "",
            "expires_in": int(body.get("expiresIn") or 3600)}


def parse_chargers(body):
    if not isinstance(body, list):
        raise EaseeError("Easee svarade inte med en lista över laddboxar")
    out = []
    for row in body:
        if not isinstance(row, dict):
            continue
        cid = str(row.get("id") or "")
        if not _ID.match(cid):
            continue
        out.append({"id": cid, "name": str(row.get("name") or cid)[:80]})
    return out


def parse_monthly(body):
    """[{month, kwh, cost, currency}] sorterat. En rad utan år eller månad hoppas över."""
    if not isinstance(body, list):
        raise EaseeError("Easee svarade inte med månadssummor")
    rows = []
    for row in body:
        if not isinstance(row, dict):
            continue
        year, month = row.get("year"), row.get("month")
        if not isinstance(year, int) or not isinstance(month, int) or not 1 <= month <= 12 or not 1990 <= year <= 2100:
            continue
        energy = row.get("totalEnergyUsage")
        if not isinstance(energy, (int, float)) or isinstance(energy, bool) or energy < 0:
            continue
        cost = row.get("totalCost")
        cost = float(cost) if isinstance(cost, (int, float)) and not isinstance(cost, bool) and cost >= 0 else None
        rows.append({"month": f"{year}-{month:02d}", "kwh": float(energy), "cost": cost,
                     "currency": str(row.get("currencyId") or "")[:8]})
    rows.sort(key=lambda r: r["month"])
    return rows


def summarize_years(months):
    years = {}
    for row in months:
        slot = years.setdefault(row["month"][:4], {"year": row["month"][:4], "kwh": 0.0, "cost": 0.0,
                                                   "cost_months": 0, "months": 0, "currency": ""})
        slot["kwh"] += row["kwh"]
        slot["months"] += 1
        if row["cost"] is not None:
            slot["cost"] += row["cost"]
            slot["cost_months"] += 1
            slot["currency"] = row["currency"] or slot["currency"]
    return [{"year": y["year"], "kwh": round(y["kwh"], 3), "months": y["months"],
             "cost": round(y["cost"], 2) if y["cost_months"] else None, "currency": y["currency"]}
            for y in years.values()]


def same_months_last_year(months, today):
    """Hittills i år mot samma månader förra året. En månad som saknas i år räknas inte som noll,
    och jämförelsen uteblir om förra året saknar någon av de månader som finns i år."""
    by = {r["month"]: r["kwh"] for r in months}
    have = [f"{today.year}-{m:02d}" for m in range(1, today.month + 1) if f"{today.year}-{m:02d}" in by]
    prev = [f"{today.year - 1}-{k[5:]}" for k in have]
    if not have or any(k not in by for k in prev):
        return None
    return {"this_kwh": round(sum(by[k] for k in have), 3), "last_kwh": round(sum(by[k] for k in prev), 3),
            "last_year": str(today.year - 1), "months": len(have)}


def _stamp(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def due(fetched_at, now, minimum):
    then = _stamp(fetched_at)
    return then is None or now - then >= minimum


class Client:
    def __init__(self, http=requests_http):
        self.http = http

    def _call(self, method, path, body=None, token=None, denied="Easee nekade anropet"):
        status, data = self.http(method, path, body, token)
        if status == 401:
            raise EaseeError(denied, status=401)
        if status == 429:
            raise EaseeError("Easee tar emot för många frågor just nu.", status=429)
        if status >= 400 or data is None:
            raise EaseeError("Easee svarade inte.", status=status)
        return data

    def login(self, username, password):
        return parse_token(self._call("POST", "/api/accounts/login", {"userName": username, "password": password},
                                      denied="Easee tog inte emot kontot. Kontrollera e-post och lösenord."))

    def refresh(self, refresh_token):
        return parse_token(self._call("POST", "/api/accounts/refresh_token", {"refreshToken": refresh_token}))

    def chargers(self, token):
        return parse_chargers(self._call("GET", "/api/chargers", token=token))

    def monthly(self, charger_id, token):
        if not _ID.match(charger_id):
            raise EaseeError("Ogiltigt id på laddboxen")
        return parse_monthly(self._call("GET", f"/api/sessions/charger/{charger_id}/monthly", token=token))


def _token_valid(stored, now):
    until = _stamp(stored.get("access_until"))
    return bool(stored.get("access_token")) and until is not None and until > now + timedelta(seconds=60)


def authenticate(stored, client, now):
    """Ny access-token. Försöker den sparade först, sedan förnyelse, sedan lösenordet. Lösenordet lämnar inte stored."""
    if _token_valid(stored, now):
        return stored
    refresh = stored.get("refresh_token") or ""
    token = None
    if refresh:
        try:
            token = client.refresh(refresh)
        except EaseeError as exc:
            if exc.status not in (401, None):
                raise
    if token is None:
        if not stored.get("username") or not stored.get("password"):
            raise EaseeError("Easee-kontot saknar lösenord. Fyll i det igen.")
        token = client.login(stored["username"], stored["password"])
    stored = dict(stored)
    stored["access_token"] = token["access_token"]
    if token["refresh_token"]:
        stored["refresh_token"] = token["refresh_token"]
    stored["access_until"] = (now + timedelta(seconds=max(60, token["expires_in"] - 120))).isoformat()
    return stored


def public_view(stored, today, error=None, stale=False):
    """Det webben får se. Inga lösenord, inga token."""
    chargers = []
    for ch in stored.get("chargers") or []:
        months = [{"month": m["month"], "kwh": round(float(m["kwh"]), 3),
                   "cost": None if m.get("cost") is None else round(float(m["cost"]), 2),
                   "currency": m.get("currency") or ""} for m in ch.get("months") or []]
        chargers.append({"id": ch.get("id"), "name": ch.get("name"), "months": months,
                         "years": summarize_years(months), "compare": same_months_last_year(months, today)})
    return {"configured": bool(stored.get("username")), "username": stored.get("username") or "",
            "fetched_at": stored.get("fetched_at"), "stale": stale, "error": error, "chargers": chargers}


def _fetch(stored, client, now):
    stored = authenticate(stored, client, now)
    found = client.chargers(stored["access_token"])[:MAX_CHARGERS]
    stored["chargers"] = [{**ch, "months": client.monthly(ch["id"], stored["access_token"])} for ch in found]
    stored["fetched_at"] = now.isoformat()
    return stored


def sync(stored, client, now, today, force=False):
    """Hämtar månaderna om de är gamla. Vid fel behålls den sparade historiken och felet skickas med."""
    stored = dict(stored or {})
    if not stored.get("username"):
        return stored, public_view(stored, today)
    minimum = MANUAL_AGE if force else AUTO_AGE
    if not due(stored.get("fetched_at"), now, minimum):
        if force:
            return stored, public_view(stored, today, error="Vänta en stund innan nästa hämtning. Easee tillåter bara några frågor i timmen.", stale=True)
        return stored, public_view(stored, today)
    try:
        stored = _fetch(stored, client, now)
        return stored, public_view(stored, today)
    except EaseeError as exc:
        had_token = bool(stored.get("access_token") or stored.get("refresh_token"))
        if exc.status == 401 and had_token and stored.get("password"):
            for key in ("access_token", "refresh_token", "access_until"):
                stored.pop(key, None)
            try:
                stored = _fetch(stored, client, now)
                return stored, public_view(stored, today)
            except EaseeError as again:
                exc = again
        return stored, public_view(stored, today, error=str(exc), stale=bool(stored.get("chargers")))


def apply_credentials(stored, username, password):
    """Nytt konto. Tomt lösenord behåller det sparade. Byter man konto eller lösenord glöms token och cachen."""
    username = (username or "").strip()
    if not username or len(username) > 200 or any(c in username for c in "\r\n\t"):
        raise EaseeError("Skriv e-postadressen till Easee-kontot")
    stored = dict(stored or {})
    changed = username != stored.get("username") or bool(password)
    if password:
        if len(password) > 200:
            raise EaseeError("Lösenordet är för långt")
        stored["password"] = password
    elif not stored.get("password"):
        raise EaseeError("Skriv lösenordet till Easee-kontot")
    stored["username"] = username
    if changed:
        for key in ("access_token", "refresh_token", "access_until", "fetched_at", "chargers"):
            stored.pop(key, None)
    return stored
