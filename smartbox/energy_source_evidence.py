"""Optional raw AC evidence from explicit cache mappings; no control or I/O."""
from datetime import datetime, timezone
import hashlib
import json
import math
from uuid import uuid4

from hot_water_power import _stamp, log_fields

_SESSION = uuid4().hex


def _reading(cache, entity):
    if not isinstance(entity, str) or not entity:
        return None, None, None
    raw = cache.get(entity) or {}
    attrs = raw.get("attributes") or {}
    if attrs.get("device_class") != "power" or attrs.get("unit_of_measurement") not in {"W", "kW"}:
        return None, None, None
    value = raw.get("state")
    if isinstance(value, bool):
        return None, None, None
    try:
        watts = float(value) * (1000 if attrs["unit_of_measurement"] == "kW" else 1)
    except (ValueError, TypeError, OverflowError):
        return None, None, None
    if not math.isfinite(watts):
        return None, None, None
    stamp = _stamp(raw.get("last_reported") or raw.get("last_updated"))
    return watts, stamp, "ha_report" if stamp is not None else "unknown"


def capture(house, cache, pump, *, now):
    """Capture independent raw evidence, not rolling/corrected display values.

    Declared AC boundary and signs are operator assertions, not physical
    qualification. Missing sources never become zero. No source IDs are logged.
    """
    try:
        cfg = house.get("energy_source_evidence") or {}
        if cfg.get("enabled") is not True or cfg.get("boundary") != "ac_household":
            return None
        if isinstance(now, bool) or not isinstance(now, (int, float)) or not math.isfinite(now):
            return None
        mappings = {role: cfg.get(role) or {} for role in ("grid", "pv", "battery")}
        hp = house.get("heat_pump") or {}
        water = log_fields(pump or {})
        local = hp.get("driver") == "nibe_local"
        native = ((hp.get("points") or {}).get("hot_water_power_w") or {}) if local else {}
        meter = (hp.get("hot_water_meter") or {}) if not local else {}
        expected_source = "nibe_local" if local else "ha_sensor"
        if (native if local else meter).get("boundary") != "hot_water_electrical" or water["hot_water_power_source"] != expected_source:
            water = dict.fromkeys(water)
        context = {"boundary": "ac_household", "session": _SESSION,
                   "channels": {role: {k: mapping.get(k) for k in ("entity_id", "positive")}
                                for role, mapping in mappings.items()},
                   "water": {"driver": hp.get("driver"), "entity_id": meter.get("entity_id"),
                             "native": {k: native.get(k) for k in ("register", "register_type", "variable_id", "unit", "boundary")}}}
        fingerprint = hashlib.sha256(json.dumps(context, sort_keys=True, allow_nan=False).encode()).hexdigest()
        entities = {role: mapping.get("entity_id") for role, mapping in mappings.items()}
        if not local:
            entities["water"] = meter.get("entity_id")
        duplicates = {role for role, entity in entities.items() if entity and any(
            other != role and entity == other_entity for other, other_entity in entities.items())}
        result = {"schema": 1, "timestamp": datetime.fromtimestamp(now, timezone.utc).isoformat(),
                  "boundary": "ac_household", "physical_verified": False, "source_context": fingerprint}
        for role, mapping in mappings.items():
            value, stamp, basis = _reading(cache, mapping.get("entity_id"))
            sign = mapping.get("positive")
            valid = (role not in duplicates and ((role == "pv" and sign in {None, "generation"}) or
                     (role == "grid" and sign in {"import", "export"}) or
                     (role == "battery" and sign in {"charge", "discharge"})))
            if not valid or (role == "pv" and value is not None and value < 0):
                value, stamp, basis = None, None, None
            elif role != "pv" and value is not None and sign in {"export", "discharge"}:
                value = -value
            result.update({role+"_w": value, role+"_sample_at": stamp, role+"_basis": basis})
        if "water" in duplicates:
            water = dict.fromkeys(water)
        result.update(water)
        return result
    except (ValueError, TypeError, AttributeError, OverflowError):
        return None


def log_value(evidence):
    """Strict allowlist for the optional JSON log column; no raw config or IDs."""
    if not isinstance(evidence, dict):
        return None
    try:
        if (type(evidence["schema"]) is not int or evidence["schema"] != 1
                or evidence["boundary"] != "ac_household" or evidence["physical_verified"] is not False):
            return None
        context = evidence["source_context"]
        if not isinstance(context, str) or len(context) != 64 or any(c not in "0123456789abcdef" for c in context):
            return None
        if _stamp(evidence["timestamp"]) is None:
            return None
        result = {k: evidence[k] for k in ("schema", "timestamp", "boundary", "physical_verified", "source_context")}
        fields = [(r+"_w", r+"_sample_at", r+"_basis") for r in ("grid", "pv", "battery")]
        fields.append(("hot_water_power_w", "hot_water_power_sample_at", "hot_water_power_basis"))
        for watts, date, basis in fields:
            value, stamp, label = (evidence[k] for k in (watts, date, basis))
            if value is None:
                if stamp is not None or label is not None:
                    return None
            elif (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
                  or (watts in {"pv_w", "hot_water_power_w"} and value < 0)):
                return None
            elif stamp is None:
                if label != "unknown":
                    return None
            elif (isinstance(stamp, bool) or not isinstance(stamp, (int, float)) or not math.isfinite(stamp)
                  or stamp < 0 or label not in {"source", "ha_report", "local_receipt"}):
                return None
            result.update({watts: value, date: stamp, basis: label})
        source = evidence.get("hot_water_power_source")
        if source not in {None, "ha_sensor", "nibe_local"}:
            return None
        if result["hot_water_power_w"] is not None and source is None:
            return None
        if source == "ha_sensor" and result["hot_water_power_basis"] not in {"ha_report", "unknown"}:
            return None
        if source == "nibe_local" and result["hot_water_power_basis"] not in {"local_receipt", "unknown"}:
            return None
        result["hot_water_power_source"] = source
        return result
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        return None
