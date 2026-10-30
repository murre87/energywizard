"""Laddar house_config.yaml och bygger upp drivrutinsregistret (smartbox/drivers/).

Fas 0: bara inläsning + Null-drivrutiner. DRIVER_REGISTRY är tomt tills Fas 1 fyller i
riktiga drivrutiner (easee, thermia_husdata, solaredge, gecko, ...) - fram tills dess
faller ALLA namngivna drivrutiner tillbaka till Null, även om de nämns i configen
(se emil_house.yaml, som redan listar riktiga entiteter men ännu inte konsumeras på
riktigt). Det håller Fas 0 rent additiv: att lägga till den här filen och de nya
YAML-exemplen ändrar inget i den befintliga körningen.
"""
from __future__ import annotations

import yaml

from drivers.car import NullCarDriver
from drivers.charger import NullChargerDriver
from drivers.heatpump import HeatPumpDriver, NullHeatPumpDriver
from drivers.solar import NullSolarDriver, SolarDriver
from drivers.spa import NullSpaDriver, SpaDriver

# Fylls i allteftersom Fas 1 flyttar in konkreta drivrutiner, t.ex.
# CAR_DRIVER_REGISTRY["generic_ev"] = GenericEvCarDriver
CAR_DRIVER_REGISTRY: dict = {}
CHARGER_DRIVER_REGISTRY: dict = {}
HEAT_PUMP_DRIVER_REGISTRY: dict = {}
SOLAR_DRIVER_REGISTRY: dict = {}
SPA_DRIVER_REGISTRY: dict = {}


def load_house_config(path: str) -> dict:
    """Läser en house_config.yaml. En helt tom/minimal fil (bara house_id) är giltig."""
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    cfg.setdefault("evs", [])
    cfg.setdefault("heat_pump", {"enabled": False})
    cfg.setdefault("solar", {"enabled": False})
    cfg.setdefault("spa", {"enabled": False})
    cfg.setdefault("fuse", {"main_fuse_a": 25})
    return cfg


def build_car_drivers(cfg: dict) -> list:
    """En CarDriver per konfigurerad bil, i samma ordning som evs-listan. Tom lista
    på ett hus utan elbil (t.ex. husdata.example.yaml i grundläge)."""
    out = []
    for ev in cfg.get("evs", []):
        driver_cls = CAR_DRIVER_REGISTRY.get(ev.get("driver"), NullCarDriver)
        out.append(driver_cls(id=ev.get("id", ""), battery_kwh=ev.get("battery_kwh", 0.0)))
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
        driver_cls = CHARGER_DRIVER_REGISTRY.get(charger_cfg.get("driver"), NullChargerDriver)
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
