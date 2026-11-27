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

import re

import yaml

import homeassistant
from drivers.battery import BatteryDriver, NullBatteryDriver
from drivers.battery_generic import GenericBatteryDriver
from drivers.battery_ferroamp import FerroampBatteryDriver
from drivers.car import NullCarDriver
from drivers.car_generic import GenericEvCarDriver, NissanCarDriver, TeslaCarDriver
from drivers.charger import NullChargerDriver
from drivers.charger_easee import EaseeChargerDriver
from drivers.charger_generic import GenericChargerDriver
from drivers.heatpump import HeatPumpDriver, NullHeatPumpDriver
from drivers.heatpump_generic import GenericClimateHeatPumpDriver
from drivers.heatpump_heishamon import HeishaMonHeatPumpDriver
from drivers.heatpump_thermiq import ThermIQHeatPumpDriver
from drivers.heatpump_ha_entities import HaEntitiesHeatPumpDriver
from drivers.heatpump_myuplink import MyUplinkHeatPumpDriver
from drivers.heatpump_nibe_local import NibeLocalHeatPumpDriver, NibeHotWaterOnlyDriver
from drivers.heatpump_thermia import ThermiaHusdataHeatPumpDriver
from drivers.solar import NullSolarDriver, SolarDriver
from drivers.solar_generic import GenericNumberSolarDriver
from drivers.solar_ferroamp import FerroampSolarDriver
from drivers.solar_huawei import HuaweiSolarServiceDriver
from drivers.solar_modbus_register import ModbusRegisterSolarDriver
from drivers.solar_solaredge import SolarEdgeSolarDriver
from drivers.spa import NullSpaDriver, SpaDriver
from drivers.spa_balboa import BalboaSpaDriver
from drivers.spa_gecko import GeckoSpaDriver
from drivers.spa_switch import SwitchSpaDriver

CAR_DRIVER_REGISTRY = {"generic_ev": GenericEvCarDriver, "nissan": NissanCarDriver, "tesla": TeslaCarDriver}
CHARGER_DRIVER_REGISTRY = {"easee": EaseeChargerDriver, "generic": GenericChargerDriver}
HEAT_PUMP_DRIVER_REGISTRY = {
    "thermia_husdata": ThermiaHusdataHeatPumpDriver, "generic_climate": GenericClimateHeatPumpDriver,
    # Anslutning/autentisering (host/användare/lösenord/cert-pin) kommer från .env
    # (NIBE_LOCAL_*), samma "driftsspecifikt, inte i checkad-in YAML"-princip som
    # Easee ovan. Se drivers/heatpump_nibe_local.py - ALDRIG verifierad mot en
    # riktig pump, bara mot NIBE S-seriens dokumenterade lokala REST-API.
    "nibe_local": NibeLocalHeatPumpDriver,
    # Molnbaserad (myUplink, OAuth) - täcker NIBE/Bosch/Atlantic/Daikin med EN
    # drivrutin, se drivers/heatpump_myuplink.py. Autentisering (client_id/secret/
    # refresh_token) från .env (MYUPLINK_*), samma "driftsspecifikt" princip som
    # NIBE_LOCAL_* ovan. ALDRIG verifierad mot ett riktigt myUplink-konto.
    "myuplink": MyUplinkHeatPumpDriver,
    # Panasonic Aquarea via HeishaMon, lokalt över HTTP (host i house_config.yaml). ALDRIG verifierad mot en riktig
    # pump, bara mot HeishaMons källkod; se drivers/heatpump_heishamon.py.
    "heishamon": HeishaMonHeatPumpDriver,
    # Thermia via ThermIQ-MQTT och ThermIQ:s HA-integration (prefix "thermiq_mqtt_<id>"). ALDRIG verifierad mot en
    # riktig pump, bara mot integrationens källkod; se drivers/heatpump_thermiq.py.
    "thermiq": ThermIQHeatPumpDriver,
    # Värmepump som redan finns i HA via en integration (t.ex. NIBE via HA:s myUplink), läst via entiteterna (#158).
    "ha_entities": HaEntitiesHeatPumpDriver,
}
SOLAR_DRIVER_REGISTRY = {"solaredge": SolarEdgeSolarDriver, "generic_number": GenericNumberSolarDriver,
                         "huawei_solar": HuaweiSolarServiceDriver, "modbus_register": ModbusRegisterSolarDriver,
                         "ferroamp_modbus": FerroampSolarDriver}
SPA_DRIVER_REGISTRY = {"gecko": GeckoSpaDriver, "balboa": BalboaSpaDriver, "switch": SwitchSpaDriver, "shelly": SwitchSpaDriver}
BATTERY_DRIVER_REGISTRY = {"generic": GenericBatteryDriver, "ferroamp_modbus": FerroampBatteryDriver}

# Easees två fysiska boxar har var sin läsfunktion i homeassistant.py (ingen generisk
# "läs valfri Easee-box"-funktion finns) - charger-configen pekar ut vilken via
# physical: lite|carport, och det faktiska Easee-ID:t kommer från .env (driftsspecifikt,
# samma mönster som värmepumpens modbus_host) snarare än att hårdkodas i en checkad-in YAML.


def merge_setup_config(existing: dict, generated: dict) -> dict:
    """Update setup-owned fields without discarding manually configured values."""
    from copy import deepcopy

    def merge(old, new):
        if isinstance(old, dict) and isinstance(new, dict):
            out = deepcopy(old)
            for key, value in new.items():
                out[key] = merge(old.get(key), value)
            return out
        return deepcopy(new)

    out = merge(existing, generated)
    if "house_id" in existing:
        out["house_id"] = existing["house_id"]
    if "fuse" in existing:
        out["fuse"] = deepcopy(existing["fuse"])
    for name in ("heat_pump", "battery"):
        old, new = existing.get(name), generated.get(name)
        if not isinstance(old, dict) or not isinstance(new, dict):
            continue
        if new.get("driver") and old.get("driver") != new["driver"]:
            out[name] = deepcopy(new)  # Never reuse another driver's connection or commands.
            continue
        defaults = ("capacity_kwh", "reserve_soc", "priority_soc", "max_power_w", "bank_kwh", "control") \
            if name == "battery" else ("connection", "host", "base_shift", "indoor_from_z1")
        for key in defaults:
            if key in old:
                out[name][key] = deepcopy(old[key])
    old_cars = {car.get("id"): car for car in existing.get("evs", []) if isinstance(car, dict)}
    out["evs"] = [merge(old_cars.get(car.get("id"), {}), car) for car in generated.get("evs", [])]
    return out


def load_house_config(path: str) -> dict:
    """Läser en house_config.yaml. En helt tom/minimal fil (bara house_id) är giltig."""
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    cfg.setdefault("evs", [])
    cfg.setdefault("heat_pump", {"enabled": False})
    cfg.setdefault("solar", {"enabled": False})
    cfg.setdefault("spa", {"enabled": False})
    cfg.setdefault("battery", {"enabled": False})
    cfg["_fuse_in_file"] = bool((cfg.get("fuse") or {}).get("main_fuse_a"))   # angav installationen säkringen själv?
    cfg.setdefault("fuse", {"main_fuse_a": 25})
    return cfg


def build_car_drivers(cfg: dict) -> list:
    """En CarDriver per konfigurerad bil, i samma ordning som evs-listan. Tom lista
    på ett hus utan elbil (t.ex. husdata.example.yaml i grundläge)."""
    out = []
    for ev in cfg.get("evs", []):
        driver_cls = CAR_DRIVER_REGISTRY.get(ev.get("driver"), NullCarDriver)
        out.append(driver_cls(id=ev.get("id", ""), battery_kwh=ev.get("battery_kwh", 0.0), entities=(ev.get("entities") or {})))
    return out


def car_specs(cfg: dict) -> dict:
    """{bil_id: {"name", "max_a", "phases"}} för gpm.py. phases ur evs[].charger.phases: 1 = alltid 1-fas
    (t.ex. Nissan Leaf), 3 = alltid 3-fas, auto = laddboxen får växla. max_a ur evs[].charger.max_a (standard 16)."""
    out = {}
    for ev in (cfg or {}).get("evs", []) or []:
        cid = ev.get("id")
        if not cid:
            continue
        ch = ev.get("charger") or {}
        ph = str(ch.get("phases", "auto")).strip().lower()
        try:
            max_a = int(ch.get("max_a") or 16)
        except (TypeError, ValueError):
            max_a = 16
        try:   # evs[].max_charge_kw: effekten bilen drar vid max_a (se ev_power.py); saknas den räknas 230 V x faser som förut
            max_kw = float(ev.get("max_charge_kw") or ch.get("max_charge_kw") or 0) or None
        except (TypeError, ValueError):
            max_kw = None
        out[cid] = {"name": ev.get("name") or cid.capitalize(), "max_a": max_a, "phases": ph if ph in ("1", "3", "auto") else "auto",
                    "battery_kwh": ev.get("battery_kwh"), "max_charge_kw": max_kw if max_kw and max_kw > 0 else None}
    return out


def _easee_driver(charger_cfg: dict):
    """Easee ur installationen: id (laddboxens serienummer) + entities + enable_switch. Inga inbyggda laddboxar."""
    if not charger_cfg.get("entities"):
        print(f"⚠️ Easee {charger_cfg.get('id') or '?'}: inga entiteter i installationen - kör Skanna mitt Home Assistant.")
    return EaseeChargerDriver(id=str(charger_cfg.get("id", "")), entities=charger_cfg.get("entities") or {},
                              enable_switch=charger_cfg.get("enable_switch"))


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
            out[car_id] = _easee_driver(charger_cfg)
        elif driver_cls is GenericChargerDriver:
            out[car_id] = GenericChargerDriver(id=charger_cfg.get("id", ""), entities=(charger_cfg.get("entities") or {}),
                                               current_limit_service=charger_cfg.get("current_limit_service"))
        else:
            out[car_id] = driver_cls(id=charger_cfg.get("id", ""))
    return out


def build_physical_charger_drivers(cfg: dict) -> dict:
    """{fysiskt_laddar_id: ChargerDriver} - samma drivrutiner som build_charger_drivers,
    men nycklade på laddarens EGEN identitet istället för bilens. Det är poolen
    smartbox/ev_handshake.py:s handskakning väljer ur när flera bilar kan dela samma
    uppsättning laddare (Steg 4:4 - se husets config: evs[].charger.physical)."""
    out = {}
    for ev in cfg.get("evs", []):
        charger_cfg = ev.get("charger")
        if not charger_cfg:
            continue
        driver_name = charger_cfg.get("driver")
        driver_cls = CHARGER_DRIVER_REGISTRY.get(driver_name, NullChargerDriver)
        if driver_cls is EaseeChargerDriver:
            drv = _easee_driver(charger_cfg)
            physical_id = drv.id
            out[physical_id] = drv
        elif driver_cls is GenericChargerDriver:
            physical_id = charger_cfg.get("id", "")
            out[physical_id] = GenericChargerDriver(id=physical_id, entities=(charger_cfg.get("entities") or {}),
                                                    current_limit_service=charger_cfg.get("current_limit_service"))
        else:
            physical_id = charger_cfg.get("id", "")
            out[physical_id] = driver_cls(id=physical_id)
    return out


def build_default_car_per_charger(cfg: dict) -> dict:
    """{fysiskt_laddar_id: bil_id} - vilken bil husets config pekar ut som
    "hemmahörande" på varje fysisk laddare. Prioriteras först av den bilen i
    ev_handshake.resolve_charger_allocations() om flera bilar har kabeln i."""
    out = {}
    for ev in cfg.get("evs", []):
        charger_cfg = ev.get("charger")
        if not charger_cfg:
            continue
        driver_name = charger_cfg.get("driver")
        if CHARGER_DRIVER_REGISTRY.get(driver_name) is EaseeChargerDriver:
            out[str(charger_cfg.get("id", ""))] = ev.get("id", "")
        else:
            out[charger_cfg.get("id", "")] = ev.get("id", "")
    return out


def build_heat_pump_driver(cfg: dict) -> HeatPumpDriver:
    hp = (cfg.get("heat_pump") or {})
    if not hp.get("enabled"):
        return NullHeatPumpDriver()
    driver_cls = HEAT_PUMP_DRIVER_REGISTRY.get(hp.get("driver"), NullHeatPumpDriver)
    if driver_cls is GenericClimateHeatPumpDriver:
        return GenericClimateHeatPumpDriver(entity_id=(hp.get("entities") or {}).get("climate"), entities=(hp.get("entities") or {}))
    if driver_cls is MyUplinkHeatPumpDriver:
        return MyUplinkHeatPumpDriver(entities=(hp.get("entities") or {}))
    if driver_cls is NibeLocalHeatPumpDriver:
        return NibeLocalHeatPumpDriver(connection=hp.get("connection"), points=hp.get("points"),
                                       control_enabled=hp.get("control_enabled", False),
                                       mode_values=hp.get("mode_values"), offset=hp)
    if driver_cls is HeishaMonHeatPumpDriver:
        return HeishaMonHeatPumpDriver(host=hp.get("host"), base_shift=hp.get("base_shift", 0),
                                       indoor_from_z1=hp.get("indoor_from_z1", False))
    if driver_cls is ThermiaHusdataHeatPumpDriver:
        import pump
        pump.configure((hp.get("connection") or {}).get("modbus_host"))
        return ThermiaHusdataHeatPumpDriver()
    if driver_cls is HaEntitiesHeatPumpDriver:
        return HaEntitiesHeatPumpDriver(entities=(hp.get("entities") or {}), cfg=hp)
    if driver_cls is ThermIQHeatPumpDriver:
        return ThermIQHeatPumpDriver(prefix=hp.get("prefix"))
    return driver_cls()


def build_hot_water_driver(cfg: dict, primary=None) -> HeatPumpDriver:
    """An optional isolated local boost driver leaves the room driver unchanged."""
    hp = cfg.get('heat_pump') or {}
    hw = hp.get('hot_water_control') or {}
    if 'driver' not in hw:
        return primary if primary is not None else build_heat_pump_driver(cfg)
    if not (hp.get('enabled') is True and hw.get('enabled') is True and hw.get('driver') == 'nibe_local'):
        return NullHeatPumpDriver()
    live = (hw.get('live_control_confirmed') is True and hw.get('exclusive_owner_confirmed') is True
            and hw.get('temperature_role_verified') is True)
    return NibeHotWaterOnlyDriver(connection=hw.get('connection'), points=hw.get('points'),
                                 control_enabled=live, live_in_shadow=live)


def power_meter_entities(cfg: dict) -> dict:
    """Elmätarens entiteter ur power_meter: (se homeassistant.configure_power_meter för formerna).
    Tom dict = ingen elmätare konfigurerad."""
    pm = (cfg or {}).get("power_meter") or {}
    ents = dict(pm.get("entities") or {})
    for k in ("power_w_invert", "frame_timestamp", "frame_coherent", "max_age_s"):
        if k in pm and k not in ents:
            ents[k] = pm[k]
    return ents


def battery_settings(cfg: dict) -> dict:
    """Hur EnergyWizard förhåller sig till batteriet (battery: i house_config.yaml):
      control: samarbete (standard - läs bara, ett annat system styr), styr, eller av
      reserve_soc / priority_soc / max_soc: procent (se battery_control.py)."""
    bat = (cfg or {}).get("battery") or {}
    control = str(bat.get("control", "samarbete")).strip().lower()
    import battery_balance
    if control not in ("styr", "samarbete", "av"):
        control = "samarbete"
    def f(k, d, positive=False):
        """Tomt, ogiltigt eller (för storheter som måste vara > 0) 0 = standardvärdet. FTW 0.158.3 (2026-11-05):
        ett tömt fält sparades som 0 och blev batteriets laddtak, så batteriet slutade ladda helt."""
        v = bat.get(k)
        try:
            v = float(v) if v is not None and str(v).strip() != "" else None
        except (TypeError, ValueError):
            v = None
        return d if v is None or v != v or (positive and v <= 0) else v
    directional = {}
    keys = ("charge_efficiency", "discharge_efficiency")
    if any(bat.get(k) not in (None, "") for k in keys):
        from battery_efficiency import resolve
        try:
            if any(isinstance(bat.get(k), bool) for k in keys):
                raise ValueError()
            directional = {k: float(bat[k]) for k in keys}
            resolve(0.9, **directional)
        except (KeyError, TypeError, ValueError, OverflowError):
            raise ValueError("Configure both battery directional efficiencies in (0, 1]") from None
    return {**directional, "control": control if bat.get("enabled") else "av", "reserve_soc": f("reserve_soc", 20.0),
            "priority_soc": f("priority_soc", 50.0), "max_soc": f("max_soc", 100.0, True),
            "normal_max_soc": bat.get("normal_max_soc"),
            "discharge_buffer_soc": bat.get("discharge_buffer_soc", 0.0),
            "max_power_w": f("max_power_w", 5000.0, True),
            # Växelriktarens faser (1 eller 3): hur nätladdningen fördelas mot säkringen (#399)
            "phases": 1 if str(bat.get("phases", 3)).strip() == "1" else 3,
            # Valfria tak för vad dygnsplanen får anta (#251). Tomt = max_power_w, sedan inlärd hållen effekt.
            "max_charge_w": f("max_charge_w", None, True), "max_discharge_w": f("max_discharge_w", None, True),
            "capacity_kwh": f("capacity_kwh", None, True),
            "efficiency": f("efficiency", 0.9, True),
            # Batteriets slitage, kr per urladdad kWh: cellernas pris / (kapacitet x antal cykler).
            # T.ex. 40 000 kr / (10 kWh x 6000 cykler) ≈ 0,67 kr; 0,30 kr är ett försiktigt standardvärde.
            "cycle_cost": f("cycle_cost", 0.30),
            # Valfria extra slitagekostnader per lagrad kWh (utöver cycle_cost).
            "charge_wear_cost_sek_per_kwh": f("charge_wear_cost_sek_per_kwh", 0.0),
            "discharge_wear_cost_sek_per_kwh": f("discharge_wear_cost_sek_per_kwh", 0.0),
            "reversal_cost_sek": f("reversal_cost_sek", 0.0),
            "min_change_minutes": f("min_change_minutes", 5.0),
            "standby_for_hold": bat.get("standby_for_hold") is True,
            "standby_reference_w": f("standby_reference_w", 10.0, True),
            # Dygnsplan (battery_plan.py) - bara i läget styr; plan: false = bara reglerna
            "plan": str(bat.get("plan", True)).lower() not in ("false", "0", "nej", "no"),
            # planeringsstil (very_careful/careful/balanced/bold/very_bold) och om batteriet får
            # sälja till nätet - kan också ändras i webben (sparas då i /data/energywizard.json)
            "plan_style": str(bat.get("plan_style", "balanced")),
            "allow_export": str(bat.get("allow_export", True)).lower() not in ("false", "0", "nej", "no"),
            "balance": battery_balance.settings(bat)}


def build_solar_driver(cfg: dict) -> SolarDriver:
    sol = (cfg.get("solar") or {})
    if not sol.get("enabled"):
        return NullSolarDriver()
    if sol.get("driver") == "ftw":                     # Sourcefuls FTW-drivrutin direkt mot växelriktaren (ftw_device.py)
        from drivers.ftw_device import FtwSolarDriver
        return FtwSolarDriver(sol.get("ftw") or {}, control_unverified=bool(sol.get("control_unverified")))
    driver_cls = SOLAR_DRIVER_REGISTRY.get(sol.get("driver"), NullSolarDriver)
    if driver_cls is GenericNumberSolarDriver:
        return GenericNumberSolarDriver(entities=(sol.get("entities") or {}))
    if driver_cls is HuaweiSolarServiceDriver:
        return HuaweiSolarServiceDriver(entities=(sol.get("entities") or {}))
    if driver_cls is ModbusRegisterSolarDriver:
        return ModbusRegisterSolarDriver(entities=(sol.get("entities") or {}), modbus=(sol.get("modbus") or {}))
    if driver_cls is SolarEdgeSolarDriver:
        return SolarEdgeSolarDriver(entities=(sol.get("entities") or {}),
                                    limit_entity=(sol.get("curtailment") or {}).get("entity"))
    if driver_cls is FerroampSolarDriver:
        return FerroampSolarDriver(modbus=sol.get("modbus"), control_enabled=sol.get("control_enabled", False),
                                  max_export_w=sol.get("max_export_w"))
    return driver_cls()


def build_spa_driver(cfg: dict) -> SpaDriver:
    spa = (cfg.get("spa") or {})
    if not spa.get("enabled"):
        return NullSpaDriver()
    driver_cls = SPA_DRIVER_REGISTRY.get(spa.get("driver"), NullSpaDriver)
    if driver_cls in (BalboaSpaDriver, SwitchSpaDriver, GeckoSpaDriver):
        return driver_cls(entities=(spa.get("entities") or {}))
    return driver_cls()


def build_battery_driver(cfg: dict) -> BatteryDriver:
    """Batteriets drivrutin. Besluten fattas i battery_control.py (se battery_settings)."""
    bat = (cfg.get("battery") or {})
    if not bat.get("enabled"):
        return NullBatteryDriver()
    if bat.get("driver") == "ftw":                     # Sourcefuls FTW-drivrutin direkt mot batteriet (ftw_device.py)
        from drivers.ftw_device import FtwBatteryDriver
        return FtwBatteryDriver(bat.get("ftw") or {}, capacity_kwh=bat.get("capacity_kwh"),
                                control=str(bat.get("control", "samarbete")).strip().lower(),
                                control_unverified=bool(bat.get("control_unverified")), max_power_w=bat.get("max_power_w", 5000))
    driver_cls = BATTERY_DRIVER_REGISTRY.get(bat.get("driver"), NullBatteryDriver)
    if driver_cls is GenericBatteryDriver:
        return GenericBatteryDriver(capacity_kwh=bat.get("capacity_kwh"), entities=(bat.get("entities") or {}),
                                    modes=(bat.get("modes") or {}), power_invert=bat.get("power_invert"),
                                    keepalive_s=bat.get("keepalive_s"), max_power_w=bat.get("max_power_w"))
    if driver_cls is FerroampBatteryDriver:
        import battery_limits, ew_settings
        limits = battery_limits.resolve(battery_settings(cfg), ew_settings.load())
        balance = battery_settings(cfg)['balance']
        return FerroampBatteryDriver(modbus=bat.get("modbus"),
                                     control_enabled=str(bat.get("control", "samarbete")).strip().lower() == "styr",
                                     default_mode_verified=bat.get("default_mode_verified", False),
                                     command_transport=bat.get('command_transport', 'modbus'),
                                     mqtt=bat.get('mqtt'), mqtt_control_verified=bat.get('mqtt_control_verified', False),
                                     live_control_confirmed=bat.get("live_control_confirmed", False),
                                     exclusive_owner_confirmed=bat.get("exclusive_owner_confirmed", False),
                                     standby_reference_w=bat.get("standby_reference_w"),
                                     standby_verified=bat.get("standby_verified", False),
                                     module_telemetry=bat.get('module_telemetry'),
                                     maintenance_soc=balance['target_soc'] if balance['enabled'] and balance['full_charge_verified'] and balance['standby_dwell_verified'] else None,
                                     max_power_w=bat.get("max_power_w", 5000),
                                     reserve_soc=bat.get("reserve_soc", 20), max_soc=bat.get("max_soc", 100),
                                     normal_max_soc=limits['normal_max_soc'],
                                     discharge_buffer_soc=limits['discharge_buffer_soc'])
    return driver_cls()


def custom_loads(cfg: dict) -> list:
    """#192 (Lars): egna laster med effektsensor, t.ex. smartpluggar på tvättmaskin eller bastu.
        loads:
          - name: Tvättmaskin
            power: sensor.tvattmaskin_power
          - name: Bastu
            power: [sensor.bastu_l1_power, sensor.bastu_l2_power]   # lista summeras
    Returnerar [{"name", "entities": [...]}]. Poster utan namn eller sensor och dubblettnamn hoppas över."""
    out, seen = [], set()
    for item in (cfg or {}).get("loads") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        ents = item.get("power")
        ents = [ents] if isinstance(ents, str) else ents if isinstance(ents, list) else []
        ents = [e.strip() for e in ents if isinstance(e, str) and "." in e]
        if not name or not ents or name.lower() in seen:
            continue
        seen.add(name.lower())
        out.append({"name": name[:40], "entities": ents})
    return out


_SOC_ENTITY = re.compile(r"sensor\.[a-z0-9_]{1,128}")
_CAR_ID_LINE = re.compile(r"^-\s+id:\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s#]+))")
_SOC_VALUE = re.compile(r"^(\s*soc\s*:\s*)(?:\"[^\"]*\"|'[^']*'|[^\s#]+)")
_FLOW_SOC = re.compile(r"(\bsoc\s*:\s*)(?:\"[^\"]*\"|'[^']*'|[^,}\s#]+)")


def _yaml_indent(line: str) -> str:
    return line[:len(line) - len(line.lstrip(" \t"))]


def _car_id_on_line(stripped: str):
    match = _CAR_ID_LINE.match(stripped)
    if not match:
        return None
    return next(group for group in match.groups() if group is not None)


def _swap_block_soc(line: str, soc: str):
    match = _SOC_VALUE.match(line)
    return None if match is None else match.group(1) + soc + line[match.end():]


def _swap_flow_soc(line: str, soc: str):
    if not _FLOW_SOC.search(line):
        return None
    return _FLOW_SOC.sub(lambda match: match.group(1) + soc, line, count=1)


def _insert_flow_soc(line: str, soc: str):
    end = line.rfind("}")
    if end < 0:
        return None
    prefix = line[:end].rstrip()
    joiner = "" if prefix.endswith("{") else ", "
    return prefix + joiner + "soc: " + soc + line[end:]


def replace_car_soc(text: str, car_id: str, soc: str) -> str:
    """Byter entities.soc för en bil och lämnar övriga rader, kommentarer och andra bilars laddnivå orörda."""
    if not isinstance(soc, str) or not _SOC_ENTITY.fullmatch(soc):
        raise ValueError("soc")
    if not isinstance(car_id, str) or not car_id or any(ch in car_id for ch in "\n\r") or len(car_id) > 80:
        raise ValueError("id")
    loaded = yaml.safe_load(text) or {}
    cars = loaded.get("evs") if isinstance(loaded, dict) else None
    if not isinstance(cars, list) or not any(isinstance(car, dict) and car.get("id") == car_id for car in cars):
        raise KeyError(car_id)
    lines = text.splitlines(keepends=True)
    in_evs = False
    evs_indent = 0
    in_car = False
    car_indent = 0
    direct_indent = None
    entities_at = None
    entities_flow = False
    inside_entities = False
    soc_at = None
    car_start = None
    car_end = None

    def finish_car(at):
        nonlocal in_car, inside_entities, car_end
        if in_car and car_end is None:
            car_end = at
        in_car = False
        inside_entities = False

    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" \t"))
        if not in_car and re.match(r"evs\s*:", stripped):
            in_evs = True
            evs_indent = indent
            continue
        if in_evs and not in_car and indent <= evs_indent and not stripped.startswith("-"):
            in_evs = False
        if not in_evs:
            continue
        if stripped.startswith("- "):
            if in_car and indent <= car_indent:
                finish_car(index)
            if not in_car and _car_id_on_line(stripped) == car_id:
                in_car = True
                car_indent = indent
                direct_indent = None
                entities_at = None
                entities_flow = False
                inside_entities = False
                soc_at = None
                car_start = index
                car_end = None
            continue
        if not in_car:
            continue
        if indent <= car_indent:
            finish_car(index)
            if indent <= evs_indent:
                in_evs = False
            continue
        if direct_indent is None:
            direct_indent = indent
        if inside_entities and indent <= direct_indent:
            inside_entities = False
        if entities_at is None and indent == direct_indent and re.match(r"entities\s*:", stripped):
            entities_at = index
            entities_flow = "{" in stripped
            inside_entities = not entities_flow
            if entities_flow and re.search(r"\bsoc\s*:", stripped):
                soc_at = index
            continue
        if inside_entities and soc_at is None and re.match(r"soc\s*:", stripped):
            soc_at = index
    if in_car and car_end is None:
        car_end = len(lines)
    if car_start is None:
        raise KeyError(car_id)
    if soc_at is not None:
        swapped = _swap_flow_soc(lines[soc_at], soc) if entities_flow else _swap_block_soc(lines[soc_at], soc)
        if swapped is None:
            raise ValueError("soc")
        lines[soc_at] = swapped
    elif entities_at is not None and entities_flow:
        swapped = _insert_flow_soc(lines[entities_at], soc)
        if swapped is None:
            raise ValueError("soc")
        lines[entities_at] = swapped
    elif entities_at is not None:
        indent = _yaml_indent(lines[entities_at])
        child = indent + ("\t" if "\t" in indent else "  ")
        if not lines[entities_at].endswith("\n"):
            lines[entities_at] += "\n"
        lines.insert(entities_at + 1, f"{child}soc: {soc}\n")
    else:
        key_indent = None
        for line in lines[car_start + 1:car_end]:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and not stripped.startswith("-"):
                key_indent = _yaml_indent(line)
                break
        if key_indent is None:
            base = _yaml_indent(lines[car_start])
            key_indent = base + ("\t" if "\t" in base else "  ")
        child = key_indent + ("\t" if "\t" in key_indent else "  ")
        block = f"{key_indent}entities:\n{child}soc: {soc}\n"
        if car_end == len(lines) and lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.insert(car_end, block)
    updated = "".join(lines)
    checked = yaml.safe_load(updated)
    found = next(car for car in checked.get("evs", []) if isinstance(car, dict) and car.get("id") == car_id)
    if (found.get("entities") or {}).get("soc") != soc:
        raise ValueError("soc")
    return updated
