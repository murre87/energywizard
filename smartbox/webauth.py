"""Delad autentisering för EnergyWizards webbgränssnitt (ewapp, webdashboard).

Flyttad hit från ewapp/app.py (EnergyWizard Open, Fas A) så den nya dator-
dashboarden kan återanvända samma roll-/cookie-system istället för att bygga
ett nytt - signerad HMAC-cookie, tre roller (owner/family/guest), inget
serversidigt sessionslager.

Varje app skapar sin egen Auth-instans med ett eget `salt` (håller cookien
skild mellan apparna, och - för ewapp specifikt - bevarar exakt samma SECRET
som innan flytten, "ewapp|"+PASSWORD, så befintliga inloggningar inte blir
ogiltiga). `family_write_prefixes` låter varje app bestämma vilka skriv-vägar
en "family"-användare (inte ägaren) får nå - det är appspecifikt routing, inte
generisk autentisering, så det ligger kvar som en parameter, inte hårdkodat här.
"""
import hashlib
import hmac
import ipaddress
import os
import time

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "")
GUEST_USER, GUEST_PASS = os.environ.get("GUEST_USER", ""), os.environ.get("GUEST_PASS", "")
EXTRA_USERS: dict = {}
EXTRA_ROLES: dict = {}
for _pair in os.environ.get("EW_USERS", "").split(","):
    _parts = _pair.strip().split(":")
    if len(_parts) >= 2 and _parts[0].strip() and _parts[1].strip():
        EXTRA_USERS[_parts[0].strip().lower()] = _parts[1].strip()
        EXTRA_ROLES[_parts[0].strip().lower()] = _parts[2].strip() if len(_parts) > 2 and _parts[2].strip() in ("owner", "family") else "family"


class Auth:
    def __init__(self, salt: str, family_write_prefixes: tuple = ()):
        self.secret = hashlib.sha256((salt + "|" + PASSWORD).encode()).digest()
        self.family_write_prefixes = family_write_prefixes
        self._fails: dict = {}

    def sign(self, exp: int, role: str = "owner", user: str = "") -> str:
        user = (user or role).replace(".", "_")
        return f"{exp}.{role}.{user}.{hmac.new(self.secret, f'{exp}.{role}.{user}'.encode(), hashlib.sha256).hexdigest()}"

    def session(self, request: Request):
        """(roll, användare) ur kakan, eller (None, None)."""
        v = request.cookies.get("ew", "")
        try:
            exp, role, user, sig = v.split(".", 3)
            if int(exp) > time.time() and role in ("owner", "family", "guest") and hmac.compare_digest(sig, hmac.new(self.secret, f"{exp}.{role}.{user}".encode(), hashlib.sha256).hexdigest()):
                return role, user
        except Exception:
            pass
        return None, None

    def role(self, request: Request):
        return self.session(request)[0]

    def ok(self, request: Request) -> bool:
        return self.role(request) is not None

    def user_password(self, user: str):
        """Lösenordet för den inloggade användaren (t.ex. för omverifiering vid känsliga åtgärder)."""
        if user == "owner":
            return PASSWORD
        return EXTRA_USERS.get(user.lower())

    @staticmethod
    def client_ip(request: Request) -> str:
        """Klientens IP. X-Forwarded-For litas bara när anropet kommer från vårt eget nät -
        annars kan klienten förfalska den och kringgå inloggningsspärren."""
        peer = request.client.host if request.client else "?"
        try:
            trusted = ipaddress.ip_address(peer).is_private
        except ValueError:
            trusted = False
        xff = [x.strip() for x in request.headers.get("x-forwarded-for", "").split(",") if x.strip()]
        return xff[-1] if (xff and trusted) else peer

    async def login(self, request: Request) -> JSONResponse:
        ip = self.client_ip(request)
        if self._fails.get(ip, (0, 0))[0] >= 8 and time.time() - self._fails[ip][1] < 600:
            raise HTTPException(429, "För många försök – vänta några minuter")
        body = await request.json()
        user, pw = str(body.get("user", "")).strip(), str(body.get("password", ""))
        role = who = None
        if not user and PASSWORD and hmac.compare_digest(pw, PASSWORD):
            role, who = "owner", "owner"
        elif user.lower() in EXTRA_USERS and hmac.compare_digest(pw, EXTRA_USERS[user.lower()]):
            role, who = EXTRA_ROLES.get(user.lower(), "family"), user.lower()
        elif GUEST_USER and GUEST_PASS and hmac.compare_digest(user.lower(), GUEST_USER.lower()) and hmac.compare_digest(pw, GUEST_PASS):
            role, who = "guest", GUEST_USER.lower()
        if not role:
            n = self._fails.get(ip, (0, 0))[0] + 1
            self._fails[ip] = (n, time.time())
            raise HTTPException(401, "Fel användarnamn eller lösenord")
        self._fails.pop(ip, None)
        print(f"🔑 inloggning: {who} ({role})", flush=True)
        r = JSONResponse({"ok": True, "role": role, "user": who})
        days = 90 if role in ("owner", "family") else 30
        r.set_cookie("ew", self.sign(int(time.time()) + days * 86400, role, who), max_age=days * 86400, httponly=True, secure=True, samesite="lax", path="/")
        return r

    @staticmethod
    def logout() -> JSONResponse:
        r = JSONResponse({"ok": True})
        for k in ("ew", "ew2"):
            r.delete_cookie(k, path="/")
        return r

    def guard_response(self, request: Request):
        """None om anropet är tillåtet, annars ett JSONResponse-felsvar att returnera direkt."""
        p = request.url.path
        if not (p.startswith("/api/") and p not in ("/api/login", "/api/logout")):
            return None
        role = self.role(request)
        if role is None:
            return JSONResponse({"detail": "Inte inloggad"}, status_code=401)
        if role == "guest" and request.method != "GET" and p != "/api/clienterr":
            return JSONResponse({"detail": "Gästläge: du kan bara titta, inte ändra något"}, status_code=403)
        if role == "family" and request.method != "GET" and not p.startswith(self.family_write_prefixes):
            return JSONResponse({"detail": "Det här kan bara administratören ändra"}, status_code=403)
        return None


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer",
    "Strict-Transport-Security": "max-age=31536000",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
}
