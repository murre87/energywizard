"""Värden: drivrutinernas ENDA väg in i resten av EnergyWizard (steg 5a av uppdelningen, docs/uppdelning/PLAN.md).

Drivrutinerna importerar aldrig motorns moduler (homeassistant, shadow, ew_settings, ...) direkt. De hämtar dem härifrån:

    from drivers.host import homeassistant, shadow          # fungerar som "import homeassistant" förut
    from drivers.host import temperature, Journal, LuaDriver  # namn som tidigare importerades med "from modul import namn"

Varje modulnamn är ett lätt ombud som slår upp den bundna modulen först när något används (alltså ingen import vid laddning, inga importcykler).
Utan bindning används motorns egna moduler, så motorn behöver inte göra något. I drivrutinsrepot (energywizard-drivers) och i tester binds en falsk värd:

    host.bind(homeassistant=FakeHA(), shadow=FakeShadow())

Det som drivrutinerna FÅR använda av varje modul står i SURFACE. tests/test_drivers_host.py kräver att ingen drivrutin använder mer, och att ingen drivrutin importerar
något ur motorn förbi värden. Vill en drivrutin ha något nytt läggs det till i SURFACE (och därmed i kontraktet) först."""
import importlib

# modul -> de attribut drivrutinerna använder (uppmätt före steg 5a)
SURFACE = {
    "homeassistant": {
        "HA_IP", "_climate_now", "_get_numeric_attribute", "_get_numeric_state", "_get_raw_state", "_states_cache", "all_entity_names", "call_service",
        "get_attribute", "get_power_w", "post_service", "press_button", "report_failure", "set_climate_temperature", "set_number", "set_select",
        "set_switch", "update_states"},
    "shadow": {"active", "record"},
    "hot_water_observation": {"temperature"},
    "ew_settings": {"PATH", "get"},
    "nordpool": {"price_timezone"},
    "hot_water_runtime": {"Journal"},
    "support_bundle": {"note_error_line", "sanitize"},
    "telemetry": {"report_error"},
    "notifier": {"send_emil"},
    "hot_water_reservations": {"boost_fields"},
}
# namn som drivrutiner importerar direkt (from drivers.host import NAMN): namn -> (modul, attribut)
NAMES = {"temperature": ("hot_water_observation", "temperature"), "Journal": ("hot_water_runtime", "Journal")}

# Kontraktets huvudversion (x-api-version i Core:s contracts/) som den här versionen av drivrutinerna är skriven mot. Core jämför vid start
# och vägrar starta vid fel huvudversion: en brytande kontraktsändring kräver att drivrutinerna släpps tillsammans med Core.
REQUIRES_CONTRACT_MAJOR = 1


def check_compat(contract_version: str) -> None:
    """Kastar RuntimeError om Core:s kontrakt har en annan huvudversion än drivrutinerna kräver."""
    try:
        major = int(str(contract_version).split(".")[0])
    except ValueError:
        raise RuntimeError(f"Drivrutinerna: okänd kontraktsversion {contract_version!r}")
    if major != REQUIRES_CONTRACT_MAJOR:
        raise RuntimeError(f"Drivrutinerna kräver kontrakt {REQUIRES_CONTRACT_MAJOR}.x men Core har {contract_version}. "
                           "Uppdatera drivrutinerna (energywizard-drivers) till en version för det kontraktet.")


_bound = {}


def bind(**modules):
    """Binder moduler (eller falska objekt) till värden. Namnen måste finnas i SURFACE."""
    unknown = set(modules) - set(SURFACE)
    if unknown:
        raise KeyError(f"okända värdmoduler: {sorted(unknown)}")
    _bound.update(modules)


def unbind(*names):
    """Tar bort bindningar (alla om inga namn anges): tillbaka till motorns egna moduler."""
    for n in (names or list(_bound)):
        _bound.pop(n, None)


def resolve(name):
    """Den modul eller det objekt som just nu står för värdmodulen `name`."""
    if name not in SURFACE:
        raise KeyError(name)
    return _bound[name] if name in _bound else importlib.import_module(name)


class _Proxy:
    """Ombud för en värdmodul: läs, skriv och ta bort attribut går till den bundna modulen (så att monkeypatch på ombudet fungerar som på modulen förut)."""

    def __init__(self, name):
        object.__setattr__(self, "_name", name)

    def __getattr__(self, attr):
        return getattr(resolve(object.__getattribute__(self, "_name")), attr)

    def __setattr__(self, attr, value):
        setattr(resolve(object.__getattribute__(self, "_name")), attr, value)

    def __delattr__(self, attr):
        delattr(resolve(object.__getattribute__(self, "_name")), attr)

    def __dir__(self):
        return dir(resolve(object.__getattribute__(self, "_name")))

    def __repr__(self):
        return f"<värdmodul {object.__getattribute__(self, '_name')}>"


homeassistant = _Proxy("homeassistant")
shadow = _Proxy("shadow")
hot_water_observation = _Proxy("hot_water_observation")
ew_settings = _Proxy("ew_settings")
nordpool = _Proxy("nordpool")
hot_water_runtime = _Proxy("hot_water_runtime")
support_bundle = _Proxy("support_bundle")
telemetry = _Proxy("telemetry")
notifier = _Proxy("notifier")
hot_water_reservations = _Proxy("hot_water_reservations")


def __getattr__(name):
    """from drivers.host import temperature / Journal / LuaDriver: slås upp i den bundna modulen vid importen."""
    if name in NAMES:
        mod, attr = NAMES[name]
        return getattr(resolve(mod), attr)
    raise AttributeError(name)
