"""Kontraktsvakten: varje gång en drivrutin lämnar ett state, varje gång batteriplanen eller batteribeslutet räknas och varje gång planeringen får sin indata (GlobalPriorityManager.evaluate), under HELA testsviten,
normaliseras resultatet och kontrolleras mot schemat i contracts/. Det gör de tusentals befintliga testerna till mätkorpus för kontraktet:
börjar en drivrutin lämna en ny nyckel med fel typ, eller ändras batteribeslutets form, blir just det testet rött med exakt vad som avviker.

Ett test som med flit lämnar ogiltiga data (t.ex. för att prova felhantering) märks med @pytest.mark.no_contract_guard; ett test som med flit ger planeringen ofullständig eller konstig indata
(minimala bilspecar, testnycklar) märks med @pytest.mark.no_planner_input_guard, som bara stänger av indatakontrollen.
Mock-objekt hoppas över. Importeras av tests/conftest.py."""
import json
import threading

import pytest

try:
    import jsonschema
except ImportError:                                                     # CI installerar jsonschema; lokalt utan det är vakten av
    jsonschema = None

VIOLATIONS = []
# Sex nycklar som main.py skickade före steg 4a men som gpm aldrig läste. Äldre testfixturer har dem kvar; planeringen ignorerar dem, så vakten gör det också.
LEGACY_INPUT_KEYS = {"base_load_profile", "ev_max_charge_a", "ev_min_charge_a", "grid_import_w", "house_consumption_w", "power_limit_kw"}
INPUT_OFF = {"v": False}                  # satt av @pytest.mark.no_planner_input_guard: bara indatakontrollen av, övrig vakt gäller
_LOCK = threading.Lock()
_INSTALLED = {"done": False}
_VALIDATORS = {}


def _is_mock(v):
    return type(v).__module__.startswith("unittest.mock")


def has_mock(v):
    if _is_mock(v):
        return True
    if isinstance(v, dict):
        return any(has_mock(x) for x in v.values())
    if isinstance(v, (list, tuple, set)):
        return any(has_mock(x) for x in v)
    return False


def _validator(name, sub=None):
    key = (name, sub)
    if key not in _VALIDATORS:
        import contracts
        s = contracts.schema(name)
        if sub:
            s = {"$schema": s["$schema"], "$ref": f"#/$defs/{sub}", "$defs": s["$defs"]}
        _VALIDATORS[key] = jsonschema.Draft202012Validator(s, format_checker=jsonschema.FormatChecker())
    return _VALIDATORS[key]


def check(kind, obj):
    """Lista med avvikelser (tom = följer kontraktet). kind: ett av contracts.STATE_KINDS, 'battery_plan' eller 'battery_decision'."""
    import contracts
    if kind == "planner_input":
        wire, v = contracts.planner_input_to_wire({k: x for k, x in obj.items() if k not in LEGACY_INPUT_KEYS}), _validator("planner-input")
    elif kind == "battery_plan":
        wire, v = contracts.battery_plan_to_wire(obj), _validator("battery-plan")
    elif kind == "battery_decision":
        wire, v = contracts.battery_decision_to_wire(obj), _validator("battery-decision")
    else:
        wire, v = contracts.normalize_driver_state(kind, obj), _validator("driver-state", kind)
    json.dumps(wire, allow_nan=False)
    return [f"{kind}: {'/'.join(str(p) for p in e.path) or '<rot>'}: {e.message[:140]}" for e in v.iter_errors(wire)]


def _report(kind, r):
    if kind == "planner_input" and INPUT_OFF["v"]:
        return
    try:
        if isinstance(r, dict) and not has_mock(r):
            bad = check(kind, r)
            if bad:
                with _LOCK:
                    VIOLATIONS.extend(bad)
    except Exception as e:                                              # ett ej JSON-bart värde m.m. räknas också som avvikelse
        with _LOCK:
            VIOLATIONS.append(f"{kind}: {type(e).__name__}: {str(e)[:140]}")


def _wrap(cls, name, kind):
    fn = cls.__dict__.get(name)
    if fn is None or getattr(fn, "_contract_guard", False):
        return
    def w(*a, **k):
        r = fn(*a, **k)
        _report(kind, r)
        return r
    w._contract_guard = True
    w.__name__ = fn.__name__
    w.__doc__ = fn.__doc__
    setattr(cls, name, w)


def _all(cls):
    for s in cls.__subclasses__():
        yield s
        yield from _all(s)


def install():
    if _INSTALLED["done"] or jsonschema is None:
        return
    import importlib
    import pkgutil
    import drivers
    for m in pkgutil.iter_modules(drivers.__path__):
        try:
            importlib.import_module(f"drivers.{m.name}")
        except Exception:
            pass
    from drivers import battery, car, charger, heatpump, solar, spa
    plan = {battery.BatteryDriver: {"read_state": "battery"}, car.CarDriver: {"read_state": "car"}, charger.ChargerDriver: {"read_state": "charger"},
            heatpump.HeatPumpDriver: {"read_state": "heatpump_state", "read_sensors": "heatpump_sensors"}, solar.SolarDriver: {"read_production": "solar"},
            spa.SpaDriver: {"read_state": "spa_state", "read_power_detail": "spa_power_detail", "read_activities": "spa_activities"}}
    for base, names in plan.items():
        for cls in [base, *_all(base)]:
            for name, kind in names.items():
                _wrap(cls, name, kind)
    import battery_control
    import battery_plan
    for mod, fn, kind in ((battery_plan, "plan_from_db", "battery_plan"), (battery_control, "decide", "battery_decision")):
        orig = getattr(mod, fn)
        if getattr(orig, "_contract_guard", False):
            continue
        def mk(orig, kind):
            def w(*a, **k):
                r = orig(*a, **k)
                _report(kind, r)
                return r
            w._contract_guard = True
            w.__name__ = orig.__name__
            w.__doc__ = orig.__doc__
            return w
        setattr(mod, fn, mk(orig, kind))
    import gpm
    ev = gpm.GlobalPriorityManager.evaluate
    if not getattr(ev, "_contract_guard", False):
        def evaluate(self, state, *a, **k):
            _report("planner_input", state)
            return ev(self, state, *a, **k)
        evaluate._contract_guard = True
        evaluate.__name__ = ev.__name__
        evaluate.__doc__ = ev.__doc__
        gpm.GlobalPriorityManager.evaluate = evaluate
    _INSTALLED["done"] = True


@pytest.fixture(scope="session", autouse=True)
def _contract_guard_install():
    install()
    yield


@pytest.fixture(autouse=True)
def contract_guard(request, _contract_guard_install):
    with _LOCK:
        VIOLATIONS.clear()
    INPUT_OFF["v"] = bool(request.node.get_closest_marker("no_planner_input_guard"))
    yield
    INPUT_OFF["v"] = False
    if request.node.get_closest_marker("no_contract_guard"):
        with _LOCK:
            VIOLATIONS.clear()
        return
    with _LOCK:
        bad, uniq = list(VIOLATIONS), sorted(set(VIOLATIONS))
        VIOLATIONS.clear()
    assert not bad, "Ett drivrutinssvar, en batteriplan eller ett batteribeslut följer inte kontraktet (contracts/):\n  " + "\n  ".join(uniq[:8])
