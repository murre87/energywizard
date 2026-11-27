"""Kontrakten mellan Core och planeringen (contracts/*.schema.json, smartbox/contracts.py) och paritetsverktyget (smartbox/parity.py).

Facit är de riktiga anropen: 2 600 beslut ur gpm:s golden-scenarier (tests/gpm_golden_gen.py), en riktig laddplan ur
decisions.calculate_ev_charge_plan, batteriplaner ur battery_plan.optimize och drivrutinernas egna läsningar.
Ändras formen måste schemat ändras med, så att uppdelningen aldrig tappar något tyst."""
import copy
import importlib
import json
import sys
from unittest.mock import patch

import pytest

import jsonschema  # noqa: E402  (krävs: saknas det ska testet fallera, inte hoppas över; CI installerar det)

import contracts  # noqa: E402
import parity  # noqa: E402
import gpm_golden_gen as gen  # noqa: E402

DECISION = jsonschema.Draft202012Validator(contracts.schema("planner-decision"), format_checker=jsonschema.FormatChecker())
EVPLAN = jsonschema.Draft202012Validator(contracts.schema("ev-plan"), format_checker=jsonschema.FormatChecker())
BATTERY = jsonschema.Draft202012Validator(contracts.schema("battery-plan"), format_checker=jsonschema.FormatChecker())
DRIVER_STATE = jsonschema.Draft202012Validator(contracts.schema("driver-state"), format_checker=jsonschema.FormatChecker())
DRIVER_COMMAND = jsonschema.Draft202012Validator(contracts.schema("driver-command"), format_checker=jsonschema.FormatChecker())


def _engine_factory():
    import gpm
    def make():
        eng = gpm.GlobalPriorityManager()
        return lambda st: eng.evaluate(st)
    return make


@pytest.fixture(scope="module")
def golden_decisions():
    import gpm
    out = []
    with patch.object(gpm.GlobalPriorityManager, "_restore_compressor_lock", lambda self: None), patch("gpm.notifier"), \
            patch("gpm.logger"), patch("gpm.learning.get_optimal_pi_params", return_value=(0.5, 0.05)):
        for seq in gen.scenarios():
            eng = gpm.GlobalPriorityManager()
            for st in seq:
                out.append(contracts.decision_to_wire(eng.evaluate(dict(st))))
    return out


def test_schemas_are_valid_and_versioned():
    for name in ("planner-decision", "ev-plan", "battery-plan", "driver-state", "driver-command"):
        s = contracts.schema(name)
        jsonschema.Draft202012Validator.check_schema(s)
        assert s["x-api-version"] == contracts.API_VERSION and s["$id"].endswith(f"{name}.schema.json")


def test_every_real_decision_follows_the_contract(golden_decisions):
    assert len(golden_decisions) == 2600
    for i, d in enumerate(golden_decisions):
        errs = sorted(DECISION.iter_errors(d), key=lambda e: list(e.path))
        assert not errs, f"beslut {i}: {errs[0].message} @ {list(errs[0].path)}"
        json.dumps(d, allow_nan=False)                                    # går att skicka som JSON


def test_the_decision_contract_rejects_what_it_should(golden_decisions):
    base = next(d for d in golden_decisions if d["nissan_set_phases"] is not None)
    assert DECISION.is_valid(base)
    def broken(mutate):
        d = copy.deepcopy(base); mutate(d); return d
    bad = {
        "ny okänd nyckel": broken(lambda d: d.update(ny_nyckel=1)),
        "saknar pump_mode": broken(lambda d: d.pop("pump_mode")),
        "okänt pumpläge": broken(lambda d: d.update(pump_mode="TURBO")),
        "laddström över taket": broken(lambda d: d.update(tesla_limit_a=33)),
        "negativ laddström": broken(lambda d: d.update(nissan_limit_a=-1)),
        "bråktal som laddström": broken(lambda d: d.update(nissan_limit_a=6.5)),
        "fasläge 2": broken(lambda d: d.update(tesla_set_phases=2)),
        "solgräns över 100": broken(lambda d: d.update(solar_limit_pct=101)),
        "loggrad som inte är text": broken(lambda d: d["log"].append(5)),
        "solinfo saknar fält": broken(lambda d: d["solar_info"]["ev"].pop("wants")),
        "okänd sollast": broken(lambda d: d["solar_info"].update(garage={"active": True, "min_w": 1, "wants": True})),
        "solordning med okänd last": broken(lambda d: d.update(solar_order=["ev", "ufo"])),
        "bil utan limit_a": broken(lambda d: d["ev"]["nissan"].pop("limit_a")),
        "panic som tal": broken(lambda d: d.update(tesla_panic=1)),
    }
    for what, d in bad.items():
        assert not DECISION.is_valid(d), what


def test_new_cars_and_optional_keys_are_allowed_by_pattern(golden_decisions):
    d = copy.deepcopy(golden_decisions[0])
    d.update(id4_limit_a=10, id4_panic=False, id4_set_phases=None, heat_feedback_sp=21.5, heat_feedback_for_mode="CHEAP",
             heat_ml_rate=0.3, hw_ml_start=47.0, house_solar_active=True, solar_order=["ev", "battery", "spa", "hotwater", "house"])
    d["ev"]["id4"] = {"limit_a": 10, "panic": False, "set_phases": None}
    assert DECISION.is_valid(d), [e.message for e in DECISION.iter_errors(d)][:1]


def test_wire_conversion_is_json_safe():
    import datetime
    import numpy as np
    w = contracts.plain({"a": np.int64(3), "b": np.float64(1.5), "c": float("nan"), "d": float("inf"), "e": datetime.datetime(2026, 11, 27, 12, 0),
                         "f": (1, 2), "g": np.bool_(True), "h": None})
    assert w == {"a": 3, "b": 1.5, "c": None, "d": None, "e": "2026-11-27T12:00:00", "f": [1, 2], "g": True, "h": None}
    json.dumps(w, allow_nan=False)
    with pytest.raises(TypeError):
        contracts.plain({"x": object()})


@pytest.fixture
def real_plan(monkeypatch):
    import pandas as pd
    import test_ev_plan_heating as t
    for name, mod in t._stubs(8.0).items():
        monkeypatch.setitem(sys.modules, name, mod)
    monkeypatch.syspath_prepend(t.SMARTBOX)
    sys.modules.pop("decisions", None)
    decisions = importlib.import_module("decisions")
    monkeypatch.setattr(pd, "read_sql", t._read_sql_factory(8.0))
    def run(cars):
        specs = {c: {"name": c, "max_a": 16, "phases": "auto", "battery_kwh": 77, "max_charge_kw": 7.4} for c in cars}
        data = {"car_ids": cars, "car_specs": specs, "heating_model": t.MODEL}
        sched = {}
        for c in cars:
            data.update({f"{c}_soc": 50, f"{c}_plugged_in": True, f"{c}_phases": None})
            sched[c] = {0: {"enabled": True, "target_time": "07:00", "target_soc": 80, "panic_mode": False}}
        cfg = {"fuse_size_a": 20, "power_limit_kw_bas": 8.0, "power_limit_kw_hog": 8.0, "peak_shaving_enabled": True}
        return decisions.calculate_ev_charge_plan(t.NOW, sched, data, cfg)
    yield run
    sys.modules.pop("decisions", None)


@pytest.mark.parametrize("cars", [["id4"], ["nissan", "tesla"]])
def test_the_real_ev_plan_follows_the_contract(real_plan, cars):
    df = real_plan(cars)
    wire = contracts.ev_plan_to_wire(df)
    assert len(wire["rows"]) == len(df) > 20
    errs = list(EVPLAN.iter_errors(wire))
    assert not errs, f"{errs[0].message} @ {list(errs[0].path)}"
    for c in cars:
        assert all(f"{c}_kw" in r and f"{c}_panic" in r for r in wire["rows"])
    assert all("t_hour" not in r for r in wire["rows"]) and "t_hour" in df.columns      # intern kolumn följer inte med
    assert any(r[f"{cars[0]}_kw"] > 0 for r in wire["rows"])                           # planen laddar faktiskt
    json.dumps(wire, allow_nan=False)


def test_ev_plan_contract_rejects_bad_rows_and_empty_plan_is_ok(real_plan):
    assert contracts.ev_plan_to_wire(None) == {"rows": []} and EVPLAN.is_valid({"rows": []})
    good = contracts.ev_plan_to_wire(real_plan(["id4"]))
    for what, mutate in {
        "okänd kolumn": lambda r: r.update(hemlig=1),
        "negativ effekt": lambda r: r.update(id4_kw=-1.0),
        "panic som text": lambda r: r.update(id4_panic="ja"),
        "saknar t_slot": lambda r: r.pop("t_slot"),
        "tid som tal": lambda r: r.update(t_slot=5),
    }.items():
        d = copy.deepcopy(good)
        mutate(d["rows"][3])
        assert not EVPLAN.is_valid(d), what


# ---- paritetsverktyget ----
def test_diff_finds_values_keys_lengths_and_types():
    assert parity.diff({"a": 1, "b": [1, 2]}, {"a": 1, "b": [1, 2]}) == []
    got = {p: (x, y) for p, x, y in parity.diff({"a": 1.0, "b": [1, 2], "c": "x", "d": True, "e": None, "g": 1},
                                                {"a": 1.5, "b": [1, 2, 3], "c": "y", "d": 1, "f": 2, "e": 0, "g": 1})}
    assert got["a"] == (1.0, 1.5) and got["b[len]"] == (2, 3) and got["c"] == ("x", "y")
    assert "d" in got and "e" in got                                   # True != 1 och None != 0 räknas som skillnader
    assert got["f"] == ("<saknas>", 2)
    assert parity.diff(1.0, 1.0 + 1e-12) == [] and parity.diff(1.0, 1.1, tol=0.2) == []


def test_the_engine_is_deterministic_across_all_golden_scenarios():
    """Samma indata genom två nya instanser ger exakt samma beslut: förutsättningen för att kunna jämföra gammalt och nytt."""
    import gpm
    with patch.object(gpm.GlobalPriorityManager, "_restore_compressor_lock", lambda self: None), patch("gpm.notifier"), \
            patch("gpm.logger"), patch("gpm.learning.get_optimal_pi_params", return_value=(0.5, 0.05)):
        rep = parity.compare(gen.scenarios(n=60), _engine_factory(), _engine_factory(), normalize=contracts.decision_to_wire)
    assert rep.ok, rep.summary()
    assert rep.scenarios == 60 and rep.steps == 600


def test_parity_reports_a_changed_implementation_with_where_and_what():
    import gpm
    make = _engine_factory()
    def drifting():
        f = make()
        def step(st):
            a = f(st)
            a["pump_target_temp"] = round(a["pump_target_temp"] + 0.5, 3)          # den "nya" implementationen avviker
            a["log"] = a["log"] + ["extra rad"]
            return a
        return step
    with patch.object(gpm.GlobalPriorityManager, "_restore_compressor_lock", lambda self: None), patch("gpm.notifier"), \
            patch("gpm.logger"), patch("gpm.learning.get_optimal_pi_params", return_value=(0.5, 0.05)):
        rep = parity.compare(gen.scenarios(n=3, steps=4), make, drifting, normalize=contracts.decision_to_wire)
    assert not rep.ok
    paths = {p for _, _, p, _, _ in rep.diffs}
    assert "pump_target_temp" in paths and any(p.startswith("log[") for p in paths)
    assert "pump_target_temp" in rep.summary()
    cut = parity.compare(gen.scenarios(n=3, steps=4), lambda: (lambda st: {"x": 1}), lambda: (lambda st: {"x": 2}), max_diffs=5)
    assert len(cut.diffs) == 5 and cut.truncated


# ---- batteriplanen (battery_plan.optimize) ----
def _battery_slots(n=8):
    from datetime import datetime, timedelta, timezone
    start = datetime(2026, 11, 27, tzinfo=timezone.utc)
    out = []
    for i in range(n):
        buy = 0.4 if i < n // 2 else 3.0
        out.append({"t": start + timedelta(minutes=15 * i), "buy": buy, "sell": buy * 0.6,
                    "load_kw": 0.5, "solar_kw": 2.0 if n // 3 <= i < n // 2 else 0.0, "ev_kw": 0.0})
    return out


def _assert_valid(validator, value, what):
    errs = sorted(validator.iter_errors(value), key=lambda e: list(e.path))
    assert not errs, f"{what}: {errs[0].message} @ {list(errs[0].path)}"
    json.dumps(value, allow_nan=False)


def test_real_battery_plans_follow_the_contract():
    from battery_plan import ACTIONS, optimize
    assert set(contracts.schema("battery-plan")["$defs"]["row"]["properties"]["action"]["enum"]) == set(ACTIONS) | {"standby"}
    plans = [
        optimize(_battery_slots(), 2.0, 10.0, 2.0, 10.0, 3.0, 3.0),
        optimize([], 0, 10, 2, 10, 3, 3),
        optimize(_battery_slots(1), 0, None, 2, 10, 3, 3),
        contracts.battery_plan_to_wire(None),
    ]
    start = _battery_slots(4)
    plans.append(optimize(start, 1, 2, 0, 2, 1, 1, allowed=("auto",),
                          balance_target_kwh=2, balance_hold_slots=1, balance_standby=True))
    kept = optimize(_battery_slots(6), 1, 2, 0, 1.5, 2, 2, eff=1, step_kwh=0.5, switch_cost=0, terminal_pct=0,
                    allowed=("charge", "hold", "auto"), balance_target_kwh=2, balance_hold_slots=1)
    plans.append(kept)
    assert any(row.get("balance") or row.get("balance_hold") or row.get("balance_ceiling") for row in kept["rows"])
    assert plans[4]["balance_feasible"] is False and plans[4]["rows"] == []
    for i, plan in enumerate(plans):
        wire = plan if i == 3 else contracts.battery_plan_to_wire(plan)
        _assert_valid(BATTERY, wire, f"plan {i}")
        if wire["rows"]:
            assert "T" in wire["rows"][0]["t"]


def test_battery_plan_contract_rejects_a_new_key_and_a_bad_row():
    from battery_plan import optimize
    wire = contracts.battery_plan_to_wire(optimize(_battery_slots(4), 2, 10, 2, 10, 3, 3))
    assert BATTERY.is_valid(wire)
    extra = copy.deepcopy(wire)
    extra["plan_id"] = "hör till steg 3"
    assert not BATTERY.is_valid(extra)
    row = copy.deepcopy(wire)
    row["rows"][0]["action"] = "turbo"
    assert not BATTERY.is_valid(row)
    missing = copy.deepcopy(wire)
    missing["rows"][0].pop("direction_reversal")
    assert not BATTERY.is_valid(missing)


# ---- drivrutinernas läge och kommandon ----
def _command_methods(cls):
    import inspect
    found = {}
    for name, fn in inspect.getmembers(cls, inspect.isfunction):
        if name.startswith("_"):
            continue
        if name.startswith(("set_", "apply_", "turn_", "adjust_", "reset_")) or name in ("pause", "resume"):
            found[name] = fn
    return found


def test_null_and_real_driver_reads_follow_the_state_contract():
    import threading
    from unittest.mock import patch
    from drivers.battery import NullBatteryDriver
    from drivers.battery_generic import GenericBatteryDriver
    from drivers.car import NullCarDriver
    from drivers.car_generic import GenericEvCarDriver
    from drivers.charger import NullChargerDriver
    from drivers.charger_easee import EaseeChargerDriver
    from drivers.charger_generic import GenericChargerDriver
    from drivers.ferroamp_modules import ModuleTelemetry
    from drivers.ftw_device import FtwBatteryDriver
    from drivers.heatpump import NullHeatPumpDriver
    from drivers.heatpump_generic import GenericClimateHeatPumpDriver
    from drivers.solar import NullSolarDriver
    from drivers.solar_generic import GenericNumberSolarDriver
    from drivers.spa import NullSpaDriver
    from drivers.spa_gecko import GeckoSpaDriver
    from drivers.spa_switch import SwitchSpaDriver

    nulls = {
        "battery": NullBatteryDriver(),
        "car": NullCarDriver(id="id4", battery_kwh=77),
        "charger": NullChargerDriver(id="box"),
        "solar": NullSolarDriver(),
        "spa": NullSpaDriver(),
        "heatpump": NullHeatPumpDriver(),
    }
    for kind, drv in nulls.items():
        wire = contracts.driver_state_to_wire(kind, drv)
        _assert_valid(DRIVER_STATE, wire, f"null {kind}")
    assert nulls and contracts.driver_state_to_wire("car", nulls["car"])["id"] == "id4"

    with patch("drivers.battery_generic.homeassistant") as ha:
        ha._get_numeric_state.return_value = 55.0
        ha.get_power_w.return_value = -800.0
        ha._get_raw_state.return_value = "Self use"
        ha._states_cache = {
            "sensor.soc": {"state": "55.0", "last_reported": "2026-11-27T06:00:00+00:00"},
            "sensor.power": {"state": "-800", "last_updated": "2026-11-27T06:00:01+00:00"},
        }
        bat = GenericBatteryDriver(10.0, {"soc": "sensor.soc", "power": "sensor.power", "mode_select": "select.mode"})
        wire = contracts.driver_state_to_wire("battery", bat)
    _assert_valid(DRIVER_STATE, wire, "generic battery")
    assert wire["state"]["soc_source"] == "ha_reported" and wire["state"]["power_w"] == -800.0

    mt = ModuleTelemetry.__new__(ModuleTelemetry)
    mt.lock, mt.connected, mt.unexpected = threading.Lock(), True, False
    mt.ids, mt.clock = {"eso-1", "eso-2"}, lambda: 2000.0
    mt.samples = {
        "eso-1": {"soc_pct": 60.0, "sample_at": 1990.0, "timestamp_basis": "mqtt_receipt"},
        "eso-2": {"soc_pct": 40.0, "sample_at": 1000.0, "timestamp_basis": "mqtt_receipt"},
    }
    dev = type("Dev", (), {})()
    dev.fresh = lambda: True
    dev.emits = {"battery": {
        "soc": 0.5, "w": 400, "power_sample_at": 1700000000.0, "soc_sample_at": 1700000000.0,
        "modules": {**mt.snapshot(), "42": {"soc_pct": 50.0, "sample_at": 1700000000.0}},
        "available_charge_W": 3000, "available_discharge_W": 2800, "capacity_wh": 10000,
    }}
    ftw = FtwBatteryDriver.__new__(FtwBatteryDriver)
    ftw.capacity_kwh, ftw._name, ftw._dev = None, "ferroamp", dev
    wire = contracts.driver_state_to_wire("battery", ftw)
    _assert_valid(DRIVER_STATE, wire, "ftw battery")
    assert wire["state"]["soc_pct"] == 50.0 and wire["state"]["soc_source"] == "ferroamp_mqtt_received"
    assert wire["state"]["available_charge_w"] == 3000
    assert any(v == {} for v in wire["state"]["modules"].values())
    assert any(v.get("timestamp_basis") == "mqtt_receipt" for v in wire["state"]["modules"].values())

    with patch("drivers.car_generic.homeassistant") as ha:
        ha._get_numeric_state.side_effect = lambda e: {"sensor.soc": 50.0, "binary_sensor.plug": 1.0}.get(e)
        ha._get_numeric_attribute.return_value = 21.5
        ha._get_raw_state.side_effect = lambda e: {"climate.bil": "heat", "binary_sensor.ch": "on"}.get(e)
        car = GenericEvCarDriver("id4", 77, {"soc": "sensor.soc", "plugged_in": "binary_sensor.plug",
                                             "climate": "climate.bil", "charging": "binary_sensor.ch"})
        wire = contracts.driver_state_to_wire("car", car)
    _assert_valid(DRIVER_STATE, wire, "generic car")
    assert wire["state"]["charging_state"] == "charging" and wire["id"] == "id4"

    with patch("drivers.charger_generic.homeassistant") as ha:
        ha._get_raw_state.return_value = "charging"
        ha._get_numeric_state.return_value = 10.0
        ch = GenericChargerDriver("box", {"status": "sensor.s", "current_limit": "number.n"})
        _assert_valid(DRIVER_STATE, contracts.driver_state_to_wire("charger", ch), "generic charger")
    easee = {
        "power_kw": 3.2, "current_a": 14.0, "current_l1": 14.0, "current_l2": 0.0, "current_l3": 0.0,
        "dynamic_limit_a": 16.0, "output_limit_a": 32.0, "max_limit_a": 32.0, "circuit_limit_a": 20.0,
        "circuit_rated_a": 25.0, "session_kwh": 4.0, "lifetime_kwh": 100.0, "status": "charging",
        "online": True, "reason_no_current": None, "phases": "ThreePhase",
    }
    _assert_valid(DRIVER_STATE, contracts.driver_state_to_wire("charger", EaseeChargerDriver("box", reader=lambda: easee)), "easee")

    with patch("drivers.solar_generic.homeassistant") as ha:
        ha._get_numeric_state.return_value = 1500.0
        ha._get_raw_state.return_value = "producing"
        sol = GenericNumberSolarDriver({"pv_power_w": "sensor.pv", "today_kwh": "sensor.today", "status": "sensor.st"})
        _assert_valid(DRIVER_STATE, contracts.driver_state_to_wire("solar", sol), "generic solar")

    with patch("drivers.heatpump_generic.homeassistant") as ha:
        ha._get_numeric_attribute.return_value = 21.0
        ha._get_raw_state.return_value = "heat"
        ha._get_numeric_state.return_value = 48.0
        hp = GenericClimateHeatPumpDriver("climate.vp", {"outdoor_temp": "sensor.ute", "water_temp": "sensor.vv"})
        wire = contracts.driver_state_to_wire("heatpump", hp)
    _assert_valid(DRIVER_STATE, wire, "generic heatpump")
    assert wire["state"]["mode"] == "heat" and wire["state"]["dhw_temp"] == 48.0
    assert wire["state"]["dhw_temp_observation"]["timestamp_basis"] == "unknown"

    _assert_valid(DRIVER_STATE, contracts.driver_state_to_wire("spa", SwitchSpaDriver({})), "switch spa")
    with patch("drivers.spa_gecko.spa_entities.complete_gecko", lambda entities, names: entities), \
            patch("drivers.spa_gecko.homeassistant") as ha:
        ha.read_gecko.return_value = {"current_temp": 38.0, "target_temp": 38.0, "heater_state": "heating", "economy_mode": "on"}
        ha.read_spa_power.return_value = {
            "phase_a_w": 2000.0, "phase_b_w": None, "phase_c_w": None, "total_w": 2000.0,
            "overcurrent": False, "overvoltage": False, "overheated": False, "power_exceeded": False,
        }
        ha.read_spa_activities.return_value = {"heating": True, "blower": False}
        gecko = GeckoSpaDriver({"climate": "climate.spa"})
        wire = contracts.driver_state_to_wire("spa", gecko)
    _assert_valid(DRIVER_STATE, wire, "gecko")
    assert wire["state"]["economy_mode"] == "on" and wire["activities"]["heating"] is True

    broken = contracts.driver_state_to_wire("battery", NullBatteryDriver())
    broken["state"]["hemlig"] = 1
    assert not DRIVER_STATE.is_valid(broken)
    with pytest.raises(ValueError):
        contracts.driver_state_to_wire("växelriktare", NullSolarDriver())


def test_driver_commands_match_the_base_class_and_run_on_the_null_drivers():
    import inspect
    from drivers.battery import INTENTS, BatteryDriver, NullBatteryDriver
    from drivers.car import CarDriver, NullCarDriver
    from drivers.charger import ChargerDriver, NullChargerDriver
    from drivers.heatpump import HeatPumpDriver, NullHeatPumpDriver
    from drivers.solar import NullSolarDriver, SolarDriver
    from drivers.spa import NullSpaDriver, SpaDriver

    classes = {"battery": BatteryDriver, "car": CarDriver, "charger": ChargerDriver,
               "solar": SolarDriver, "spa": SpaDriver, "heatpump": HeatPumpDriver}
    nulls = {"battery": NullBatteryDriver(), "car": NullCarDriver(), "charger": NullChargerDriver(),
             "solar": NullSolarDriver(), "spa": NullSpaDriver(), "heatpump": NullHeatPumpDriver()}
    samples = {
        "intent": "hold", "power_w": None, "mode": "Self use", "active": False, "hvac_mode": "heat",
        "temperature": None, "amps": 0, "reason": None, "phases": 1, "pct": 100, "temp_c": 37.0,
        "enable": True, "on": False, "target_c": 20.5, "offset": 0.0, "delta": 0.5, "minutes": 15, "now": None,
    }
    branches = {}
    for branch in contracts.schema("driver-command")["oneOf"]:
        target = branch["$ref"].rsplit("/", 1)[-1]
        spec = contracts.schema("driver-command")["$defs"][target]
        branches[(spec["properties"]["kind"]["const"], spec["properties"]["op"]["const"])] = spec
    assert set(branches) == {(kind, op) for kind, cls in classes.items() for op in _command_methods(cls)}
    intent = branches[("battery", "apply_intent")]["properties"]["intent"]["enum"]
    assert set(intent) == set(INTENTS)
    for (kind, op), spec in branches.items():
        params = [p for name, p in inspect.signature(_command_methods(classes[kind])[op]).parameters.items() if name != "self"]
        assert set(spec["properties"]) - {"kind", "op"} == {p.name for p in params}
        assert set(spec["required"]) - {"kind", "op"} == {p.name for p in params if p.default is inspect.Parameter.empty}
        args = {p.name: samples[p.name] for p in params}
        wire = contracts.driver_command_to_wire(kind, op, args)
        _assert_valid(DRIVER_COMMAND, wire, f"{kind}.{op}")
        getattr(nulls[kind], op)(**args)
        if any(p.default is not inspect.Parameter.empty for p in params):
            minimal = {p.name: samples[p.name] for p in params if p.default is inspect.Parameter.empty}
            _assert_valid(DRIVER_COMMAND, contracts.driver_command_to_wire(kind, op, minimal), f"{kind}.{op} minimal")
    mode = contracts.driver_command_to_wire("heatpump", "set_operating_mode", {"mode": 1})
    _assert_valid(DRIVER_COMMAND, mode, "rått pumpläge")
    extra = contracts.driver_command_to_wire("battery", "apply_intent", {"intent": "auto", "power_w": None, "force": True})
    assert not DRIVER_COMMAND.is_valid(extra)
    assert not DRIVER_COMMAND.is_valid({"kind": "battery", "op": "refresh"})
