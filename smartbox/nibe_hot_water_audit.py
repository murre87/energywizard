"""Read-only audit of captured NIBE metadata; never constructs a device client."""
from drivers.heatpump_nibe_local import NibeLocalHeatPumpDriver, LocalRestError, _number

ROLES = ("boost", "demand_mode", "top_temperature", "charging_temperature", "electrical_power")
COMMANDS = {"boost", "demand_mode"}


def audit(points, bindings):
    """Validate explicit role bindings against a captured point dictionary.

    Metadata consistency is not firmware semantics, watchdog behavior, physical
    delivery, release qualification, measurement freshness or actuator permission.
    """
    if not isinstance(points, dict) or len(points) > 10000 or not isinstance(bindings, dict):
        raise ValueError("Captured point dictionary and explicit bindings required")
    results, identities = {}, {}
    for role in ROLES:
        binding = bindings.get(role)
        if not isinstance(binding, dict):
            results[role] = {"state": "blocked", "reason": "binding_missing"}
            continue
        if not {"register", "register_type", "variable_id", "unit"} <= binding.keys():
            results[role] = {"state": "blocked", "reason": "explicit_identity_required"}
            continue
        try:
            if isinstance(binding["variable_id"], bool) or not str(binding["variable_id"]).isdigit():
                raise LocalRestError("invalid variable identity")
            key, point = NibeLocalHeatPumpDriver._resolve(points, binding, writable=role in COMMANDS)
            meta = point["metadata"]
            value = _number(point)
            if meta["modbusRegisterType"] not in {"MODBUS_INPUT_REGISTER", "MODBUS_HOLDING_REGISTER"}:
                raise LocalRestError("invalid register type")
            if role in COMMANDS:
                if meta["modbusRegisterType"] != "MODBUS_HOLDING_REGISTER" or meta["divisor"] != 1:
                    raise LocalRestError("invalid command type or scale")
                allowed = binding.get("allowed_values")
                names = ("start_value", "release_value") if role == "boost" else ("requested_value", "release_value")
                values = [binding.get(name) for name in names]
                if (not isinstance(allowed, list) or not allowed or len(allowed) > 256
                        or any(type(v) is not int for v in allowed + values)
                        or any(v not in allowed for v in values) or value not in allowed
                        or (role == "boost" and values[0] == values[1])):
                    results[role] = {"state": "blocked", "reason": "enum_configuration_invalid"}
                    continue
                low, high = meta.get("minValue"), meta.get("maxValue")
                if type(low) is not int or type(high) is not int or low >= high:
                    results[role] = {"state": "blocked", "reason": "metadata_bounds_unknown"}
                    continue
                if any(not low <= v <= high for v in allowed):
                    raise LocalRestError("enum outside declared bounds")
                for candidate in allowed:
                    _number({"metadata": meta, "value": {**point["value"], "integerValue": candidate}})
            elif role in {"top_temperature", "charging_temperature"}:
                if binding["unit"] != "°C" or not -80 <= value <= 150:
                    raise LocalRestError("invalid temperature")
            elif (binding["unit"] not in {"W", "kW"} or value < 0
                  or binding.get("boundary") != "hot_water_electrical"):
                results[role] = {"state": "blocked", "reason": "electrical_boundary_unqualified"}
                continue
            identity = (meta["modbusRegisterType"], meta["modbusRegisterID"])
            identities[role] = (key, identity)
            results[role] = {"state": "metadata_consistent", "variable_id": int(key),
                             "register": meta["modbusRegisterID"], "current_value": value,
                             "unit": "native_enum" if role in COMMANDS else binding["unit"]}
        except (LocalRestError, KeyError, TypeError, ValueError, OverflowError):
            results[role] = {"state": "blocked", "reason": "point_validation_failed"}
    # Two semantic roles must not silently share a point or a register address.
    for role, (key, identity) in identities.items():
        if any(other != role and (other_key == key or other_identity == identity)
               for other, (other_key, other_identity) in identities.items()):
            results[role] = {"state": "blocked", "reason": "ambiguous_role_identity"}
    return {"metadata_consistent": all(r["state"] == "metadata_consistent" for r in results.values()),
            "control_ready": False, "physical_verified": False, "release_verified": False,
            "timing_verified": False, "freshness_verified": False, "roles": results}
