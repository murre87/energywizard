"""Steg 5a av uppdelningen: drivrutinerna når resten av EnergyWizard bara genom drivers/host.py.

Det är sömmen som gör att drivers/ kan flytta till ett eget repo (energywizard-drivers): där binds en falsk värd i stället för motorns moduler.
Testerna håller sömmen tät: ingen drivrutin importerar något ur motorn förbi värden, och det de FÅR använda (SURFACE) är exakt det de använder."""
import ast
import os
from pathlib import Path

import pytest

import contract_guard  # noqa: F401  (testmiljön)
from drivers import host

ROOT = Path(__file__).resolve().parents[1]
SMARTBOX = ROOT / "smartbox"
DRIVERS = SMARTBOX / "drivers"
FILES = sorted(p for p in DRIVERS.glob("*.py") if p.name not in ("__init__.py", "host.py"))
ENGINE_MODULES = {p.stem for p in SMARTBOX.glob("*.py")}          # allt som ligger utanför drivers/ i smartbox


def _imports(tree):
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                yield a.name.split(".")[0], None, n
        elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
            yield n.module.split(".")[0], n.module, n


def test_no_driver_imports_the_engine_except_through_the_host():
    for f in FILES:
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for top, module, node in _imports(tree):
            if top in ENGINE_MODULES and top != "drivers":
                pytest.fail(f"{f.name} rad {node.lineno}: importerar motorns modul '{top}' direkt (använd: from drivers.host import ...)")


def _usage():
    """(modul -> använda attribut, från-importerade namn) i alla drivrutiner."""
    attrs = {m: set() for m in host.SURFACE}
    names = set()
    for f in FILES:
        tree = ast.parse(f.read_text(encoding="utf-8"))
        local = {}
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and n.module == "drivers.host":
                for a in n.names:
                    if a.name in host.SURFACE:
                        local[a.asname or a.name] = a.name
                    else:
                        names.add(a.name)
        for n in ast.walk(tree):
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id in local:
                attrs[local[n.value.id]].add(n.attr)
    for n in names:                                       # namn som importeras direkt räknas som användning av modulens attribut
        if n in host.NAMES:
            attrs[host.NAMES[n][0]].add(host.NAMES[n][1])
    return attrs, names


def test_the_surface_is_exactly_what_the_drivers_use():
    attrs, names = _usage()
    for mod, used in attrs.items():
        assert used == host.SURFACE[mod], f"{mod}: används men inte i SURFACE: {sorted(used - host.SURFACE[mod])}; i SURFACE men oanvänt: {sorted(host.SURFACE[mod] - used)}"
    assert names == set(host.NAMES)
    for mod, attr in host.NAMES.values():
        assert attr in host.SURFACE[mod]


def test_every_host_module_exists_in_the_engine_and_has_what_the_surface_promises():
    import importlib
    for mod, wanted in host.SURFACE.items():
        real = importlib.import_module(mod)
        assert wanted <= set(dir(real)), f"{mod} saknar {sorted(wanted - set(dir(real)))}"


def test_bind_resolves_lazily_forwards_writes_and_unbind_restores():
    class FakeShadow:
        active = staticmethod(lambda: "falsk")
    host.bind(shadow=FakeShadow)
    try:
        assert host.shadow.active() == "falsk" and host.resolve("shadow") is FakeShadow
        host.shadow.record = "skriven"                              # skrivning går till den bundna modulen, inte till ombudet
        assert FakeShadow.record == "skriven" and "record" not in vars(host.shadow)
        del host.shadow.record
        assert not hasattr(FakeShadow, "record")
    finally:
        host.unbind()
    import shadow as real
    assert host.resolve("shadow") is real and callable(host.shadow.active)
    with pytest.raises(KeyError):
        host.bind(ingen_modul=object())
    with pytest.raises(KeyError):
        host.resolve("ingen_modul")
    from drivers.host import temperature
    import hot_water_observation
    assert temperature is hot_water_observation.temperature
    with pytest.raises(ImportError):                    # Python gör om modulens AttributeError till ImportError vid "from ... import"
        from drivers.host import finns_inte  # noqa: F401


def test_a_real_driver_runs_against_a_fake_host_with_no_engine_homeassistant():
    """Drivrutinen läser sin data ur den bundna värden: samma som i drivrutinsrepot, där motorns homeassistant inte finns."""
    from drivers.car_generic import GenericEvCarDriver
    calls = []
    class FakeHA:
        @staticmethod
        def _get_numeric_state(e):
            calls.append(("num", e)); return {"sensor.soc": 64.0, "binary_sensor.plug": 1.0}[e]
        @staticmethod
        def _get_numeric_attribute(e, a):
            return 21.5
        @staticmethod
        def _get_raw_state(e):
            return "heat"
    host.bind(homeassistant=FakeHA)
    try:
        car = GenericEvCarDriver("c", 60.0, {"soc": "sensor.soc", "plugged_in": "binary_sensor.plug", "climate": "climate.c"})
        assert car.read_state() == {"soc": 64.0, "plugged_in": 1.0, "climate_temp": 21.5, "climate_state": "heat"}
        assert ("num", "sensor.soc") in calls
    finally:
        host.unbind()


def test_all_engine_modules_the_drivers_need_are_covered_by_the_host():
    """Täcker värden alla moduler som drivrutinerna använde före steg 5a? (Listan kommer ur mätningen i PLAN.md.)"""
    assert set(host.SURFACE) == {"homeassistant", "shadow", "hot_water_observation", "ew_settings", "nordpool", "hot_water_runtime", "support_bundle",
                                 "lua_host", "telemetry", "notifier", "hot_water_reservations", "pump", "spa_entities"}
