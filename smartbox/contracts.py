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


# ---- planeringens indata (Core -> planering) ----
def planner_input_to_wire(state: dict) -> dict:
    """Det Core lämnar till planeringen (gpm_state i main.py) som JSON-säker dict enligt planner-input.schema.json. Laddplanen (en
    pandas.DataFrame) blir {"rows": [...]}; tidpunkter blir ISO-text; övrigt rensas som i plain(). Inget filtreras bort."""
    out = dict(state)
    if "ev_plan" in out and out["ev_plan"] is not None and hasattr(out["ev_plan"], "columns"):
        out["ev_plan"] = ev_plan_to_wire(out["ev_plan"])
    return plain(out)


# ---- batteri: plan och beslut ----
def battery_plan_to_wire(plan: dict) -> dict:
    """Batteriplanen (battery_plan.plan_from_db) som JSON-säker dict enligt battery-plan.schema.json."""
    return plain(dict(plan))


def battery_decision_to_wire(decision: dict) -> dict:
    """Batteribeslutet (battery_control.decide) som JSON-säker dict enligt battery-decision.schema.json."""
    return plain(dict(decision))


# ---- drivrutiner: state och kommandon ----
STATE_KINDS = ("battery", "car", "charger", "heatpump_state", "heatpump_sensors", "solar", "spa_state", "spa_activities", "spa_power_detail")
# De få fält där drivrutiner i dag lämnar sluddriga typer. Omvandlingen är medvetet liten och uppräknad: allt annat lämnas som det är,
# så att en ny avvikelse syns i kontraktstestet i stället för att döljas här.
BOOL_FIELDS = {"car": {"plugged_in"}, "charger": {"current_is_limit"}, "heatpump_state": {"running", "defrosting"},
               "heatpump_sensors": {"compressor_running", "alarm_active", "hot_water_boost_active"}}
STR_FIELDS = {"solar": {"status"}, "battery": {"mode"}, "heatpump_state": {"mode", "fault"}, "heatpump_sensors": {"operating_mode"}}
DROPPED_FIELDS = {"_raw"}                   # rådata från enheten: stort, märkesspecifikt och inte en del av kontraktet


def _boolish(v):
    if v is None or isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        t = v.strip().lower()
        return True if t in {"1", "true", "on", "yes"} else False if t in {"0", "false", "off", "no"} else None
    return None


def normalize_driver_state(kind: str, state: dict) -> dict:
    """En drivrutins read_state/read_sensors/read_production som JSON-säker dict enligt driver-state.schema.json (#/$defs/<kind>)."""
    if kind not in STATE_KINDS:
        raise ValueError(f"okänd typ: {kind}")
    out = {k: v for k, v in dict(state or {}).items() if k not in DROPPED_FIELDS}
    for k in BOOL_FIELDS.get(kind, ()):
        if k in out:
            out[k] = _boolish(out[k])
    for k in STR_FIELDS.get(kind, ()):
        if k in out and out[k] is not None and not isinstance(out[k], str):
            out[k] = str(out[k])
    return plain(out)


# Kommandon per enhet: namn -> argumentnamn i den ordning drivrutinsmetoden tar dem. Allt annat på gränssnitten är läsning, förmåga
# eller livscykel (NON_COMMANDS). tests/test_contracts_drivers.py kräver att varje publik metod står i exakt en av listorna.
COMMANDS = {
    "battery": {"apply_intent": ("intent", "power_w"), "set_mode": ("mode",)},
    "car": {"set_climate": ("hvac_mode", "temperature")},
    "charger": {"set_limit_a": ("amps", "reason"), "set_phases": ("phases",), "turn_on": (), "turn_off": ()},
    "heatpump": {"adjust_curve": ("delta",), "set_curve_offset": ("offset",), "reset_curve_offset": (), "pause": ("minutes", "now"), "resume": (),
                 "set_hot_water_boost": ("active",), "set_operating_mode": ("mode",), "set_room_temp": ("target_c",),
                 "set_heating_start_temp": ("target_c",), "set_water_start_temp": ("target_c",), "set_water_stop_temp": ("target_c",)},
    "solar": {"set_export_limit_pct": ("pct",)},
    "spa": {"set_target_temp": ("temp_c",), "set_economy": ("enable",), "set_plug_power": ("on",)},
}
NON_COMMANDS = {
    "battery": {"read_state", "refresh", "set_balancing", "supported_intents", "supports_control", "supports_maintenance"},
    "car": {"read_state"},
    "charger": {"read_state"},
    "heatpump": {"capabilities", "read_hot_water_boost", "read_room_target", "read_sensors", "read_state", "tick"},
    "solar": {"get_export_limit_pct", "read_production", "supports_curtailment"},
    "spa": {"read_activities", "read_power_detail", "read_power_w", "read_state"},
}
