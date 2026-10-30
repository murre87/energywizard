"""EnergyWizard Webdashboard: ny dator-/surfplatte-dashboard, ersätter smartdashboard
(Streamlit) stegvis (EnergyWizard Open, Fas A-F - se /home/emil/.claude/plans/
glowing-moseying-octopus.md). Byggd på samma mönster som ewapp (FastAPI, inget
byggsteg, delad databas) men med en desktop-layout (sidomeny, flera sidor samtidigt
synliga, vanlig scroll) istället för ewapp:s enda-skärm-mobillayout.

Fas A: bara inloggning (delad med ewapp via smartbox/webauth.py), sidomeny-skal med
alla 13 planerade sidor, och en testgraf som bevisar att ECharts-pipen fungerar.
Ingen sida har riktigt innehåll än - det är Fas B och framåt.
"""
import os
import sys
import time

sys.path.insert(0, "/smartbox")
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine

import webauth

ENGINE = create_engine(
    f"postgresql+psycopg://{os.environ['POSTGRES_USER']}:{os.environ['POSTGRES_PASSWORD']}@{os.environ.get('POSTGRES_HOST', 'postgres-smartbox')}/{os.environ['POSTGRES_DB']}",
    pool_pre_ping=True, pool_size=3,
)

# Eget salt ("webdash") -> egen cookie-scope, skild session från ewapp även om PASSWORD
# är detsamma. family-rollen har inga skriv-vägar än (Fas A har inga formulär alls).
AUTH = webauth.Auth(salt="webdash", family_write_prefixes=())

# De 13 sidorna enligt inventeringen av smartdashboard (se planfilen) - tomma till Fas B+.
PAGES = [
    {"id": "oversikt", "name": "Översikt", "icon": "📊"},
    {"id": "ekonomi", "name": "Ekonomi", "icon": "💰"},
    {"id": "elforbrukning", "name": "Elförbrukning", "icon": "🔌"},
    {"id": "elbil", "name": "Elbil", "icon": "⚡"},
    {"id": "varmepump", "name": "Värmepump", "icon": "♨️"},
    {"id": "solceller", "name": "Solceller", "icon": "☀️"},
    {"id": "spabad", "name": "Spabad", "icon": "🛁"},
    {"id": "temperaturer", "name": "Temperaturer", "icon": "🌡️"},
    {"id": "prognos", "name": "Prognos", "icon": "📅"},
    {"id": "historik", "name": "Historik", "icon": "📈"},
    {"id": "installningar", "name": "Inställningar", "icon": "⚙️"},
    {"id": "aviseringar", "name": "Aviseringar", "icon": "🔔"},
    {"id": "system", "name": "System", "icon": "🛠️"},
]

app = FastAPI(title="EnergyWizard Webdashboard")


@app.middleware("http")
async def guard(request: Request, call_next):
    err = AUTH.guard_response(request)
    if err is not None:
        return err
    resp = await call_next(request)
    resp.headers.update(webauth.SECURITY_HEADERS)
    if request.url.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.post("/api/login")
async def login(request: Request):
    return await AUTH.login(request)


@app.post("/api/logout")
async def logout():
    return AUTH.logout()


@app.get("/api/me")
async def me(request: Request):
    role, user = AUTH.session(request)
    return {"role": role, "user": user, "pages": PAGES}


@app.get("/api/ping")
async def ping():
    """Bevisar att databaskopplingen fungerar - samma ENGINE-mönster som ewapp/smartbox."""
    with ENGINE.connect() as c:
        c.exec_driver_sql("SELECT 1")
    return {"ok": True, "ts": int(time.time())}


@app.get("/api/testgraf")
async def testgraf():
    """Dummy-data i ECharts-format, bara för att bevisa att diagram-pipen (CDN-skript ->
    JSON-data -> renderad graf) fungerar innan riktiga sidor byggs i Fas B."""
    import random
    hours = [f"{h:02d}:00" for h in range(24)]
    return {"hours": hours, "values": [round(random.uniform(0.5, 3.0), 2) for _ in hours]}


app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/{full_path:path}")
async def spa(full_path: str):
    return FileResponse("static/index.html")
