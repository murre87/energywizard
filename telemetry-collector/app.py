"""EnergyWizard telemetri-samlare: en EGEN, fristående tjänst - driftsätts EN gång
av Emil (inte av varje betatestare). Varje smartbox pekar via TELEMETRY_ENDPOINT
mot den här enda instansen, bara om TELEMETRY_OPT_IN=true är satt lokalt hos dem
(se smartbox/telemetry.py - strikt opt-in, av som standard).

Tar bara emot och lagrar det smartbox/telemetry.py redan sanerat: en hashad
husidentifierare, drivrutinkategorier, feltyper, version, tidsstämpel. Inget UI
än - bara lagring + /api/recent för att själv fråga ut det senaste.
"""
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

DB_PATH = os.environ.get("TELEMETRY_DB_PATH", "/data/telemetry.sqlite3")

app = FastAPI(title="EnergyWizard Telemetri-samlare")


@contextmanager
def _db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS driver_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT, received_at TEXT, house TEXT,
            version TEXT, drivers TEXT, ts TEXT)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS errors (
            id INTEGER PRIMARY KEY AUTOINCREMENT, received_at TEXT, house TEXT,
            version TEXT, module TEXT, error_type TEXT, ts TEXT)""")
        yield conn
        conn.commit()
    finally:
        conn.close()


@app.on_event("startup")
async def _print_welcome():
    print("")
    print("=" * 60)
    print("📡  EnergyWizard telemetri-samlare är igång!")
    print(f"    Lagrar i {DB_PATH} - bara det betatestare själva slagit på.")
    print("=" * 60)
    print("")


def _str_field(d: dict, key: str, max_len: int = 200) -> str:
    v = d.get(key)
    return str(v)[:max_len] if v is not None else ""


@app.post("/ingest/drivers")
async def ingest_drivers(request: Request):
    body = await request.json()
    with _db() as c:
        c.execute(
            "INSERT INTO driver_snapshots (received_at, house, version, drivers, ts) VALUES (?, ?, ?, ?, ?)",
            (
                datetime.now(timezone.utc).isoformat(),
                _str_field(body, "house", 64),
                _str_field(body, "version", 64),
                ",".join(str(x) for x in (body.get("drivers") or []))[:2000],
                _str_field(body, "ts", 64),
            ),
        )
    return {"ok": True}


@app.post("/ingest/error")
async def ingest_error(request: Request):
    body = await request.json()
    with _db() as c:
        c.execute(
            "INSERT INTO errors (received_at, house, version, module, error_type, ts) VALUES (?, ?, ?, ?, ?, ?)",
            (
                datetime.now(timezone.utc).isoformat(),
                _str_field(body, "house", 64),
                _str_field(body, "version", 64),
                _str_field(body, "module", 100),
                _str_field(body, "error_type", 100),
                _str_field(body, "ts", 64),
            ),
        )
    return {"ok": True}


@app.get("/api/recent")
async def recent(limit: int = 50):
    limit = max(1, min(limit, 500))
    with _db() as c:
        drivers = c.execute(
            "SELECT received_at, house, version, drivers FROM driver_snapshots ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        errors = c.execute(
            "SELECT received_at, house, version, module, error_type FROM errors ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return JSONResponse({
        "driver_snapshots": [{"received_at": r[0], "house": r[1], "version": r[2], "drivers": r[3].split(",") if r[3] else []} for r in drivers],
        "errors": [{"received_at": r[0], "house": r[1], "version": r[2], "module": r[3], "error_type": r[4]} for r in errors],
    })


@app.get("/api/ping")
async def ping():
    return {"ok": True}
