"""Laddar house_config.yaml och bygger upp drivrutinsregistret (smartbox/drivers/).

Fas 1: registren pekar nu på riktiga drivrutiner (easee, thermia_husdata, solaredge,
gecko, generic_ev, nissan, tesla) - tunna omslag kring homeassistant.py/pump.py:s
befintliga funktioner, se respektive fil i smartbox/drivers/. Ett namn som inte finns i
registret faller fortfarande tillbaka till Null, så en ofärdig/felstavad drivrutin i
configen är overksam snarare än ett kraschande fel.

main.py/gpm.py använder ÄNNU INTE de här drivrutinerna för den faktiska styrningen -
det är ett separat, senare steg (Fas 2-3) som görs varsamt medan systemet kör live.
Den här filen bygger bara upp och verifierar att drivrutinerna kan instansieras korrekt
från en riktig config (se tests/test_config_loader.py).
"""
from __future__ import annotations

import yaml

import homeassistant
from drivers.car import NullCarDriver
from drivers.car_generic import GenericEvCarDriver, NissanCarDriver, TeslaCarDriver
from drivers.charger import NullChargerDriver
from drivers.charger_easee import EaseeChargerDriver
from drivers.heatpump import HeatPumpDriver, NullHeatPumpDriver
from drivers.heatpump_thermia import ThermiaHusdataHeatPumpDriver
from drivers.solar import NullSolarDriver, SolarDriver
from drivers.solar_solaredge import SolarEdgeSolarDriver
from drivers.spa import NullSpaDriver, SpaDriver
from drivers.spa_gecko import GeckoSpaDriver

CAR_DRIVER_REGISTRY = {"generic_ev": GenericEvCarDriver, "nissan": NissanCarDriver, "tesla": TeslaCarDriver}
CHARGER_DRIVER_REGISTRY = {"easee": EaseeChargerDriver}
HEAT_PUMP_DRIVER_REGISTRY = {"thermia_husdata": ThermiaHusdataHeatPumpDriver}
SOLAR_DRIVER_REGISTRY = {"solaredge": SolarEdgeSolarDriver}
SPA_DRIVER_REGISTRY = {"gecko": GeckoSpaDriver}

# Easees två fysiska boxar har var sin läsfunktion i homeassistant.py (ingen generisk
# "läs valfri Easee-box"-funktion finns) - charger-configen pekar ut vilken via
# physical: lite|carport, och det faktiska Easee-ID:t kommer från .env (driftsspecifikt,
# samma mönster som värmepumpens modbus_host) snarare än att hårdkodas i en checkad-in YAML.
_EASEE_PHYSICAL = {
    "lite": (lambda: homeassistant.EASEE_LITE_ID, homeassistant.read_easee_lite),
    "carport": (lambda: homeassistant.EASEE_CARPORT_ID, homeassistant.read_easee_carport),
}


def load_house_config(path: str) -> dict:
    """Läser en house_config.yaml. En helt tom/minimal fil (bara house_id) är giltig."""
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    cfg.setdefault("evs", [])
    cfg.setdefault("heat_pump", {"enabled": False})
    cfg.setdefault("solar", {"enabled": False})
    cfg.setdefault("spa", {"enabled": False})
    cfg.setdefault("fuse", {"main_fuse_a": 25})
    cfg.setdefault("telemetry", {"enabled": True})
    cfg.setdefault("elomrade", None)
    return cfg


def build_car_drivers(cfg: dict) -> list:
    """En CarDriver per konfigurerad bil, i samma ordning som evs-listan. Tom lista
    på ett hus utan elbil (t.ex. husdata.example.yaml i grundläge)."""
    out = []
    for ev in cfg.get("evs", []):
        driver_cls = CAR_DRIVER_REGISTRY.get(ev.get("driver"), NullCarDriver)
        out.append(driver_cls(id=ev.get("id", ""), battery_kwh=ev.get("battery_kwh", 0.0), entities=ev.get("entities", {})))
    return out


def build_charger_drivers(cfg: dict) -> dict:
    """{car_id: ChargerDriver}, en per bil som har en charger-sektion i sin config."""
    out = {}
    for ev in cfg.get("evs", []):
        charger_cfg = ev.get("charger")
        car_id = ev.get("id", "")
        if not charger_cfg:
            out[car_id] = NullChargerDriver(id="")
            continue
        driver_name = charger_cfg.get("driver")
        driver_cls = CHARGER_DRIVER_REGISTRY.get(driver_name, NullChargerDriver)
        if driver_cls is EaseeChargerDriver:
            get_id, reader = _EASEE_PHYSICAL.get(charger_cfg.get("physical"), (lambda: charger_cfg.get("id", ""), lambda: {}))
            out[car_id] = EaseeChargerDriver(id=get_id(), reader=reader)
        else:
            out[car_id] = driver_cls(id=charger_cfg.get("id", ""))
    return out


def build_heat_pump_driver(cfg: dict) -> HeatPumpDriver:
    hp = cfg.get("heat_pump", {})
    if not hp.get("enabled"):
        return NullHeatPumpDriver()
    driver_cls = HEAT_PUMP_DRIVER_REGISTRY.get(hp.get("driver"), NullHeatPumpDriver)
    return driver_cls()


def build_solar_driver(cfg: dict) -> SolarDriver:
    sol = cfg.get("solar", {})
    if not sol.get("enabled"):
        return NullSolarDriver()
    driver_cls = SOLAR_DRIVER_REGISTRY.get(sol.get("driver"), NullSolarDriver)
    return driver_cls()


def build_spa_driver(cfg: dict) -> SpaDriver:
    spa = cfg.get("spa", {})
    if not spa.get("enabled"):
        return NullSpaDriver()
    driver_cls = SPA_DRIVER_REGISTRY.get(spa.get("driver"), NullSpaDriver)
    return driver_cls()
