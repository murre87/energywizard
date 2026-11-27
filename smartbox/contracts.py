"""Kontrakten mellan Core och planeringen (contracts/*.schema.json): hur ett beslut och en laddplan ser ut på tråden.

Idag körs planeringen i samma process (gpm.py, decisions.py). Uppdelningen i egna delar (docs/uppdelning/PLAN.md) kräver att det som
passerar gränsen är en ren, JSON-säker datastruktur med ett versionerat schema. Den här modulen gör just omvandlingen och rör
ingen beslutslogik. Den används av testerna (tests/test_contracts.py) och av paritetsverktyget (parity.py); senare av själva gränssnittet.

Schemafilerna ligger i contracts/ i repot (de ingår inte i Docker-imagen: validering är ett test- och utvecklingsverktyg).
"""
import json
import math
import os
from datetime import date, datetime

API_VERSION = "1.0.0"                      # samma som x-api-version i schemafilerna
CONTRACTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "contracts")
INTERNAL_PLAN_COLUMNS = {"t_hour"}         # hjälpkolumn i planeringen, ingår inte i kontraktet


def schema(name: str) -> dict:
    """Schemat `contracts/<name>.schema.json` som dict."""
    with open(os.path.join(CONTRACTS_DIR, f"{name}.schema.json"), encoding="utf-8") as f:
        return json.load(f)


def plain(v):
    """JSON-säkert värde: numpy-tal blir vanliga tal, NaN och oändligheter blir None, datum blir ISO-text, samlingar rensas rekursivt."""
    if v is None or isinstance(v, (bool, str)):
        return v
    if isinstance(v, dict):
        return {str(k): plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [plain(x) for x in v]
    if isinstance(v, (datetime, date)) or hasattr(v, "isoformat"):
        return v.isoformat()
    if hasattr(v, "item") and not isinstance(v, (int, float)):         # numpy-skalärer
        return plain(v.item())
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, int):
        return v
    raise TypeError(f"Värde som inte går att skicka som JSON: {type(v).__name__}")


def decision_to_wire(actions: dict) -> dict:
    """Planeringens beslut (GlobalPriorityManager.evaluate) som JSON-säker dict enligt planner-decision.schema.json.
    Ingenting filtreras bort: en ny eller felaktig nyckel ska synas i kontraktstestet, inte döljas här."""
    return plain(dict(actions))


def ev_plan_to_wire(df) -> dict:
    """Laddplanen (pandas.DataFrame från decisions.calculate_ev_charge_plan) som {"rows": [...]} enligt ev-plan.schema.json.
    En tom plan ger tom lista. Rutans start skrivs som ISO-text utan tidszon (lokal tid, som planeringen räknar)."""
    if df is None or len(df) == 0:
        return {"rows": []}
    cols = [c for c in df.columns if c not in INTERNAL_PLAN_COLUMNS]
    rows = []
    for rec in df[cols].to_dict("records"):
        rows.append({k: plain(v) for k, v in rec.items()})
    return {"rows": rows}
