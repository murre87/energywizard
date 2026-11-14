"""Optional dedicated electrical-load evidence; no device or network calls."""
from datetime import datetime
import math

KEYS = ("hot_water_power_w", "hot_water_power_sample_at", "hot_water_power_basis", "hot_water_power_source")


def _empty():
    return dict.fromkeys(KEYS)


def _stamp(value):
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.utcoffset() is None:
            return None
        seconds = stamp.timestamp()
        return seconds if math.isfinite(seconds) and seconds >= 0 else None
    except (ValueError, TypeError, AttributeError, OverflowError):
        return None


def log_fields(values):
    """Only code-owned provenance and finite nonnegative dedicated watts."""
    watts = values.get("hot_water_power_w")
    source = values.get("hot_water_power_source")
    if (isinstance(watts, bool) or not isinstance(watts, (int, float)) or not math.isfinite(watts)
            or watts < 0 or source not in {"ha_sensor", "nibe_local"}):
        return _empty()
    stamp = values.get("hot_water_power_sample_at")
    basis = values.get("hot_water_power_basis")
    dated = (not isinstance(stamp, bool) and isinstance(stamp, (int, float)) and math.isfinite(stamp)
             and stamp >= 0 and basis in {"ha_report", "local_receipt"})
    return dict(zip(KEYS, (float(watts), float(stamp) if dated else None, basis if dated else "unknown", source)))


def read(heat_pump, sensors, cache):
    """Read explicit native mapping or an explicitly dedicated cached HA meter.

    Local REST stays exclusive when selected. Never use compressor/whole-system
    power, a tank heat estimate or cache-read time as dedicated hot-water evidence.
    """
    try:
        if heat_pump.get("enabled") is not True:
            return _empty()
        if heat_pump.get("driver") == "nibe_local":
            binding = (heat_pump.get("points") or {}).get("hot_water_power_w") or {}
            if binding.get("boundary") != "hot_water_electrical":
                return _empty()
            return log_fields(dict(zip(KEYS, (sensors.get("hot_water_power_w"), _stamp(sensors.get("_received_at")),
                                             "local_receipt", "nibe_local"))))
        meter = heat_pump.get("hot_water_meter") or {}
        if meter.get("boundary") != "hot_water_electrical" or not meter.get("entity_id"):
            return _empty()
        raw = cache.get(meter["entity_id"]) or {}
        attrs = raw.get("attributes") or {}
        if attrs.get("device_class") != "power" or attrs.get("unit_of_measurement") not in {"W", "kW"}:
            return _empty()
        value = raw.get("state")
        if isinstance(value, bool):
            return _empty()
        watts = float(value) * (1000 if attrs["unit_of_measurement"] == "kW" else 1)
        stamp = _stamp(raw.get("last_reported") or raw.get("last_updated"))
        return log_fields(dict(zip(KEYS, (watts, stamp, "ha_report", "ha_sensor"))))
    except (ValueError, TypeError, AttributeError, KeyError, OverflowError):
        return _empty()
