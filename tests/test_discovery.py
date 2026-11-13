"""Bevisar att smartbox/discovery.py:s kategori-regexer faktiskt hittar rätt
TYP av entitet i ett syntetiskt Home Assistant-svar (samma form som
/api/template ger) - inte bara att koden kör utan att krascha. Rör aldrig
riktig hårdvara/nätverk - entities skickas in direkt, read_all_entities()
anropas aldrig här."""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import discovery
from discovery import discover_house


def _hybrid_sensor(entity, name, unit="W", state="0", device="hybrid"):
    return dict(e="sensor." + entity, n=name, d=device, dn="SolaX Inverter",
                m="SolaX", mo="Hybrid", dc="power" if unit == "W" else "energy",
                u=unit, st=state)


def test_hybrid_pv_total_wins_over_grid_battery_and_strings_in_any_order():
    """A hybrid inverter's grid import must not appear as sunshine at night."""
    from itertools import permutations
    sensors = [
        _hybrid_sensor("energy_grid_solax_grid_import_solax_grid_export_net_power", "SolaX Grid Net Power", state="800"),
        _hybrid_sensor("solax_battery_power", "SolaX Inverter Battery Power", state="500"),
        _hybrid_sensor("solax_ac_power", "SolaX Inverter AC Power", state="500"),
        _hybrid_sensor("solax_pv_power_1", "SolaX Inverter PV Power 1"),
        _hybrid_sensor("solax_pv_power_total", "SolaX Inverter PV Power Total"),
    ]
    for ordered in permutations(sensors):
        solar = discover_house(list(ordered))["solar"]
        assert solar["pv_power_entity"] == "sensor.solax_pv_power_total"
        assert solar["generic_suggestion"]["entities"]["pv_power_w"] == "sensor.solax_pv_power_total"


def test_hybrid_daily_energy_is_solar_not_battery_or_grid():
    sensors = [
        _hybrid_sensor("solax_pv_power_total", "SolaX Inverter PV Power Total"),
        _hybrid_sensor("solax_battery_output_energy_today", "SolaX Battery Output Energy Today", "kWh", "12"),
        _hybrid_sensor("solax_today_s_import", "SolaX Inverter Today's Import", "kWh", "20"),
        _hybrid_sensor("solax_today_s_yield", "SolaX Inverter Today's Yield", "kWh", "15"),
        _hybrid_sensor("solax_today_s_solar_energy", "SolaX Inverter Today's Solar Energy", "kWh", "2"),
    ]
    for ordered in (sensors, list(reversed(sensors))):
        assert discover_house(ordered)["solar"]["today_kwh_entity"] == "sensor.solax_today_s_solar_energy"


def test_hybrid_without_pv_does_not_offer_grid_or_battery_as_solar():
    for entity, name in [
        ("solax_grid_power", "SolaX Inverter Grid Power"),
        ("solax_battery_power", "SolaX Inverter Battery Power"),
        ("solax_load_power", "SolaX Inverter Load Power"),
    ]:
        assert discover_house([_hybrid_sensor(entity, name)])["solar"] is None


def test_solar_daily_energy_requires_a_shared_device():
    sensors = [
        _hybrid_sensor("pv_power", "PV Power", device=None),
        _hybrid_sensor("solar_today", "Solar Energy Today", "kWh", device=None),
    ]
    assert discover_house(sensors)["solar"]["today_kwh_entity"] is None


def test_solar_daily_energy_rejects_non_solar_measurements():
    sensors = [_hybrid_sensor("pv_power", "PV Power")]
    for entity, name in [
        ("battery_today", "Battery Energy Today"),
        ("grid_import_today", "Grid Import Today"),
        ("grid_export_today", "Grid Export Today"),
    ]:
        assert discover_house(sensors + [_hybrid_sensor(entity, name, "kWh")])["solar"]["today_kwh_entity"] is None

SYNTHETIC_ENTITIES = [
    # Tesla - battery + device_tracker
    {"e": "sensor.tesla_battery", "n": "Tesla Battery", "a": "Garage", "d": "dev_tesla", "dn": "Model Y",
     "m": "Tesla", "mo": "Model Y", "dc": "battery", "u": "%", "st": "62"},
    {"e": "device_tracker.tesla_location", "n": "Tesla Location", "a": "Garage", "d": "dev_tesla", "dn": "Model Y",
     "m": "Tesla", "mo": "Model Y", "dc": None, "u": None, "st": "home"},
    {"e": "climate.tesla_climate", "n": "Tesla Climate", "a": "Garage", "d": "dev_tesla", "dn": "Model Y",
     "m": "Tesla", "mo": "Model Y", "dc": None, "u": None, "st": "off"},

    # Nissan - battery + device_tracker
    {"e": "sensor.leaf_soc", "n": "Leaf SOC", "a": "Garage", "d": "dev_nissan", "dn": "Leaf",
     "m": "Nissan", "mo": "Leaf", "dc": "battery", "u": "%", "st": "54"},
    {"e": "device_tracker.leaf_location", "n": "Leaf Location", "a": "Garage", "d": "dev_nissan", "dn": "Leaf",
     "m": "Nissan", "mo": "Leaf", "dc": None, "u": None, "st": "home"},

    # Ett mobilbatteri (ska INTE räknas som bil trots battery-%)
    {"e": "sensor.iphone_battery", "n": "iPhone Battery", "a": None, "d": "dev_phone", "dn": "iPhone",
     "m": "Apple", "mo": "iPhone 15", "dc": "battery", "u": "%", "st": "80"},
    {"e": "device_tracker.iphone_location", "n": "iPhone Location", "a": None, "d": "dev_phone", "dn": "iPhone",
     "m": "Apple", "mo": "iPhone 15", "dc": None, "u": None, "st": "home"},

    # Thermia/Husdata värmepump
    {"e": "sensor.husdata_indoor_temp", "n": "Inomhustemperatur", "a": "Källare", "d": "dev_hp",
     "dn": "Husdata H66", "m": "Husdata", "mo": "H66", "dc": "temperature", "u": "°C", "st": "21.4"},
    {"e": "sensor.husdata_compressor", "n": "Kompressor", "a": "Källare", "d": "dev_hp",
     "dn": "Husdata H66", "m": "Husdata", "mo": "H66", "dc": None, "u": None, "st": "on"},

    # SolarEdge växelriktare
    {"e": "sensor.solaredge_power", "n": "SolarEdge Production Power", "a": "Garage", "d": "dev_inverter",
     "dn": "SolarEdge Inverter", "m": "SolarEdge", "mo": "SE10K", "dc": "power", "u": "W", "st": "2380"},
    {"e": "sensor.solaredge_today", "n": "SolarEdge Energy Today", "a": "Garage", "d": "dev_inverter",
     "dn": "SolarEdge Inverter", "m": "SolarEdge", "mo": "SE10K", "dc": "energy", "u": "kWh", "st": "14.2"},

    # Gecko spa
    {"e": "climate.spa_heater", "n": "Spa Heater", "a": "Trädgård", "d": "dev_spa",
     "dn": "Gecko in.touch2", "m": "Gecko", "mo": "in.touch2", "dc": None, "u": None, "st": "heat"},
    {"e": "sensor.spa_power", "n": "Spa Power", "a": "Trädgård", "d": "dev_spa",
     "dn": "Gecko in.touch2", "m": "Gecko", "mo": "in.touch2", "dc": "power", "u": "W", "st": "1800"},

    # Easee laddare
    {"e": "sensor.easee_status", "n": "Easee Status", "a": "Garage", "d": "dev_easee",
     "dn": "Easee Home", "m": "Easee", "mo": "Home", "dc": None, "u": None, "st": "charging"},

    # Ett okänt, oregistrerat värmepumpsmärke (ska hittas men flaggas utan drivrutin)
    {"e": "sensor.nibe_indoor_temp", "n": "Rumsgivare", "a": "Källare", "d": "dev_nibe",
     "dn": "NIBE F750", "m": "NIBE", "mo": "F750", "dc": "temperature", "u": "°C", "st": "20.8"},

    # Brus: en vanlig lampa, ska inte dyka upp i något fynd
    {"e": "light.vardagsrum", "n": "Vardagsrum", "a": "Vardagsrum", "d": "dev_light",
     "dn": "Lampa", "m": "IKEA", "mo": "TRADFRI", "dc": None, "u": None, "st": "on"},

    # Elmätare: både Tibber Pulse OCH en separat smartmätare - ska hittas BÅDA
    # (Emils egen poäng: inte antingen-eller).
    {"e": "sensor.tibber_pulse_power", "n": "Tibber Pulse Power", "a": "El", "d": "dev_pulse",
     "dn": "Tibber Pulse", "m": "Tibber", "mo": "Pulse", "dc": "power", "u": "W", "st": "1200"},
    {"e": "sensor.han_power", "n": "Elmätare effekt", "a": "El", "d": "dev_han",
     "dn": "HAN-läsare", "m": "Netmore", "mo": "HAN", "dc": "power", "u": "W", "st": "1180"},
]


def test_hittar_bada_bilarna_men_inte_mobilen():
    result = discover_house(SYNTHETIC_ENTITIES)
    assert len(result["cars"]) == 2
    makers = {c["maker"] for c in result["cars"]}
    assert makers == {"Tesla", "Nissan"}
    tesla = next(c for c in result["cars"] if c["maker"] == "Tesla")
    assert tesla["soc_entity"] == "sensor.tesla_battery"
    assert tesla["climate_entity"] == "climate.tesla_climate"
    assert tesla["driver"] == "tesla" and tesla["driver_known"] is True
    nissan = next(c for c in result["cars"] if c["maker"] == "Nissan")
    assert nissan["driver"] == "nissan" and nissan["driver_known"] is True


def test_husdata_varmepump_hittas_med_kand_drivrutin():
    result = discover_house(SYNTHETIC_ENTITIES)
    assert result["heat_pump"] is not None
    assert result["heat_pump"]["maker"] == "Husdata"
    assert result["heat_pump"]["driver"] == "thermia_husdata"
    assert result["heat_pump"]["driver_known"] is True


def test_solaredge_hittas_med_bade_effekt_och_dagsenergi():
    result = discover_house(SYNTHETIC_ENTITIES)
    assert result["solar"] is not None
    assert result["solar"]["pv_power_entity"] == "sensor.solaredge_power"
    assert result["solar"]["today_kwh_entity"] == "sensor.solaredge_today"
    # Utan den äldre integrationens exportgräns-entitet: generiska drivrutinen, inte den hårdkodade.
    assert result["solar"]["driver"] is None and result["solar"]["generic_suggestion"]["driver"] == "generic_number"


def test_solaredge_med_aldre_integrationens_entitet_far_egna_drivrutinen():
    legacy = [e for e in SYNTHETIC_ENTITIES if e["e"].startswith("sensor.solaredge")] + [
        {"e": "number.solaredge_modbus_active_power_limit", "n": "Active Power Limit", "a": None, "d": "dev_inverter",
         "dn": "SolarEdge Inverter", "m": "SolarEdge", "mo": "SE10K", "dc": None, "u": "%", "st": "100"}]
    r = discover_house(legacy)
    assert r["solar"]["driver"] == "solaredge" and r["solar"]["driver_known"] is True


def test_solaredge_via_officiella_solaredge_modbus():
    """HA 2026.10: solaredge_modbus har 'Active power limit' i % på växelriktaren -> generisk drivrutin."""
    official = [
        {"e": "sensor.solaredge_se10k_power", "n": "SolarEdge SE10K Power", "a": None, "d": "dev_se",
         "dn": "SolarEdge SE10K", "m": "SolarEdge", "mo": "SE10K", "dc": "power", "u": "W", "st": "4100"},
        {"e": "number.solaredge_se10k_active_power_limit", "n": "SolarEdge SE10K Active power limit", "a": None, "d": "dev_se",
         "dn": "SolarEdge SE10K", "m": "SolarEdge", "mo": "SE10K", "dc": None, "u": "%", "st": "100"},
    ]
    r = discover_house(official)
    assert r["solar"]["generic_suggestion"] == {
        "driver": "generic_number",
        "entities": {"pv_power_w": "sensor.solaredge_se10k_power", "export_limit_pct": "number.solaredge_se10k_active_power_limit"},
    }


def test_gecko_spa_hittas():
    result = discover_house(SYNTHETIC_ENTITIES)
    assert result["spa"] is not None
    assert result["spa"]["current_temp_entity"] == "climate.spa_heater"
    assert result["spa"]["power_entity"] == "sensor.spa_power"
    assert result["spa"]["driver"] == "gecko" and result["spa"]["driver_known"] is True


def test_balboa_spa_hittas_med_egen_drivrutin():
    """Balboa fick tidigare gissningsvis Geckos drivrutin (kommentar: "byggd mot
    Balboa-liknande styrsystem") - rättat till en egen, verifierad drivrutin byggd
    mot HA:s officiella balboa-integrations dokumenterade entitetsformer."""
    balboa = [
        {"e": "climate.balboa_spa", "n": "Balboa Spa", "a": "Trädgård", "d": "dev_balboa",
         "dn": "Balboa Spa", "m": "Balboa", "mo": "BP Series", "dc": None, "u": None, "st": "heat"},
    ]
    result = discover_house(balboa)
    assert result["spa"] is not None
    assert result["spa"]["driver"] == "balboa" and result["spa"]["driver_known"] is True


def test_easee_laddare_hittas():
    result = discover_house(SYNTHETIC_ENTITIES)
    assert len(result["chargers"]) == 1
    assert result["chargers"][0]["maker"] == "Easee"
    assert result["chargers"][0]["driver"] == "easee" and result["chargers"][0]["driver_known"] is True


def test_easee_hubbenhet_utan_statussensor_listas_inte_som_laddare():
    """Easee-integrationen registrerar en egen konto-/hubb-enhet i HA:s enhetsregister
    (bekräftat live: 1 entitet, ingen statussensor) utöver de fysiska laddarna - den ska
    inte dyka upp som en falsk tredje laddare i gränssnittet."""
    hub_device = [{"e": "sensor.easee_cloud_version", "n": "Easee Firmware", "a": None, "d": "dev_easee_hub",
                   "dn": "Easee EV Charger", "m": "Easee", "mo": None, "dc": None, "u": None, "st": "0.9.74"}]
    result = discover_house(SYNTHETIC_ENTITIES + hub_device)
    assert len(result["chargers"]) == 1
    assert result["chargers"][0]["device_name"] == "Easee Home"


def test_ocpp_laddare_hittas_via_entity_id_inte_markestext():
    """lbbrhzn/ocpp (HA:s OCPP-serverintegration) namnger entiteter efter laddpunktens
    "charge point ID", inte efter ett märke - en Zaptec-laddare kopplad via OCPP har t.ex.
    ingen "Zaptec" i tillverkartexten. Matchning sker därför mot entity_id-suffixet
    (switch.<cpid>_charge_control / number.<cpid>_maximum_current), inte CHARGER_MAKERS."""
    ocpp = [
        {"e": "switch.laddpunkt1_charge_control", "n": "Charge Control", "a": "Garage",
         "d": "dev_ocpp", "dn": "Laddpunkt 1", "m": None, "mo": None, "dc": None, "u": None, "st": "on"},
        {"e": "number.laddpunkt1_maximum_current", "n": "Maximum Current", "a": "Garage",
         "d": "dev_ocpp", "dn": "Laddpunkt 1", "m": None, "mo": None, "dc": None, "u": "A", "st": "16"},
        {"e": "sensor.laddpunkt1_status", "n": "Status", "a": "Garage",
         "d": "dev_ocpp", "dn": "Laddpunkt 1", "m": None, "mo": None, "dc": None, "u": None, "st": "Charging"},
    ]
    result = discover_house(ocpp)
    assert len(result["chargers"]) == 1
    charger = result["chargers"][0]
    assert charger["driver"] is None and charger["driver_known"] is False
    assert charger["generic_suggestion"]["driver"] == "generic"
    assert charger["generic_suggestion"]["entities"]["switch"] == "switch.laddpunkt1_charge_control"
    # maximum_current är laddboxens BESTÅENDE tak och ska aldrig skrivas varje minut (SpotNav-lärdom).
    assert "current_limit" not in charger["generic_suggestion"]["entities"]


def test_ocpp_anvander_sessionens_stromgrans_och_connectorns_sensorer():
    def e(eid, name, u=None, st="1"):
        return {"e": eid, "n": name, "a": None, "d": "dev_cp", "dn": "Charge Amps HALO", "m": None, "mo": None,
                "dc": None, "u": u, "st": st}
    ocpp = [e("switch.halo_charge_control", "Charge Control", st="on"),
            e("number.halo_maximum_current", "Maximum Current", "A", "32"),
            e("number.halo_session_current_limit", "Session Current Limit", "A", "unavailable"),
            e("sensor.halo_status_connector", "Status Connector", st="Charging"),
            e("sensor.halo_current_import", "Current Import", "A", "15.8")]
    ent = discover_house(ocpp)["chargers"][0]["generic_suggestion"]["entities"]
    assert ent == {"switch": "switch.halo_charge_control", "status": "sensor.halo_status_connector",
                   "current_limit": "number.halo_session_current_limit", "current_import": "sensor.halo_current_import"}


def test_okant_varmepumpsmarke_flaggas_utan_drivrutin_inte_tyst_fel_eller_kraschar():
    """NIBE hittas (matchar HEATPUMP-regexen) men har ingen registrerad drivrutin -
    ska synas med driver_known=False, inte krascha och inte tyst väljas som Husdata."""
    only_nibe = [e for e in SYNTHETIC_ENTITIES if e["d"] in ("dev_nibe",)]
    result = discover_house(only_nibe)
    assert result["heat_pump"] is not None
    assert result["heat_pump"]["maker"] == "NIBE"
    assert result["heat_pump"]["driver"] is None
    assert result["heat_pump"]["driver_known"] is False


def test_okant_varmepumpsmarke_med_climate_entitet_foreslar_generisk_drivrutin():
    """Samma NIBE-scenario, men med en climate-entitet på enheten (vanligt för
    integrationer som exponerar värmepumpen via HA:s climate-domän) - ska föreslå
    GenericClimateHeatPumpDriver istället för att bara vara en återvändsgränd."""
    nibe_with_climate = [e for e in SYNTHETIC_ENTITIES if e["d"] == "dev_nibe"] + [
        {"e": "climate.nibe_heatpump", "n": "NIBE Climate", "a": "Källare", "d": "dev_nibe",
         "dn": "NIBE F750", "m": "NIBE", "mo": "F750", "dc": None, "u": None, "st": "heat"},
    ]
    result = discover_house(nibe_with_climate)
    assert result["heat_pump"]["driver"] is None
    assert result["heat_pump"]["generic_suggestion"] == {
        "driver": "generic_climate", "entities": {"climate": "climate.nibe_heatpump"},
    }


def test_okant_laddarmarke_med_switch_foreslar_generisk_drivrutin():
    zaptec = [
        {"e": "sensor.zaptec_status", "n": "Zaptec Status", "a": "Garage", "d": "dev_zaptec",
         "dn": "Zaptec Go", "m": "Zaptec", "mo": "Go", "dc": None, "u": None, "st": "charging"},
        {"e": "switch.zaptec_charging", "n": "Zaptec Charging", "a": "Garage", "d": "dev_zaptec",
         "dn": "Zaptec Go", "m": "Zaptec", "mo": "Go", "dc": None, "u": None, "st": "on"},
    ]
    result = discover_house(zaptec)
    assert len(result["chargers"]) == 1
    assert result["chargers"][0]["driver"] is None
    assert result["chargers"][0]["generic_suggestion"] == {
        "driver": "generic", "entities": {"switch": "switch.zaptec_charging", "status": "sensor.zaptec_status"},
    }


def test_okant_laddarmarke_utan_switch_far_inget_forslag():
    """Ingen switch-entitet alls = inget att koppla GenericChargerDriver mot -
    ska flaggas utan drivrutin, inte föreslå en drivrutin som ändå inte kan göra något."""
    zaptec_no_switch = [
        {"e": "sensor.zaptec_status", "n": "Zaptec Status", "a": "Garage", "d": "dev_zaptec2",
         "dn": "Zaptec Go", "m": "Zaptec", "mo": "Go", "dc": None, "u": None, "st": "charging"},
    ]
    result = discover_house(zaptec_no_switch)
    assert result["chargers"][0]["driver"] is None
    assert "generic_suggestion" not in result["chargers"][0]


def test_okant_solcellsmarke_med_exportgrans_foreslar_generisk_drivrutin():
    fronius = [
        {"e": "sensor.fronius_power", "n": "Fronius Solar Power", "a": "Garage", "d": "dev_fronius",
         "dn": "Fronius Inverter", "m": "Fronius", "mo": "Symo", "dc": "power", "u": "W", "st": "3200"},
        {"e": "number.fronius_export_limit", "n": "Export Limit", "a": "Garage", "d": "dev_fronius",
         "dn": "Fronius Inverter", "m": "Fronius", "mo": "Symo", "dc": None, "u": "%", "st": "100"},
    ]
    result = discover_house(fronius)
    assert result["solar"]["driver"] is None
    assert result["solar"]["generic_suggestion"] == {
        "driver": "generic_number",
        "entities": {"pv_power_w": "sensor.fronius_power", "export_limit_pct": "number.fronius_export_limit"},
    }


def test_exportgrans_i_watt_foreslas_inte_som_procent():
    """Sungrow-Modbus/Huawei har exportgränsen i W. Den generiska drivrutinen skriver 0-100 %,
    så en W-gräns får inte föreslås - då skulle 100 % bli 100 W."""
    sungrow = [
        {"e": "sensor.total_dc_power", "n": "Total DC power", "a": None, "d": "dev_sg",
         "dn": "Sungrow SH10RT", "m": "Sungrow", "mo": "SH10RT", "dc": "power", "u": "W", "st": "4100"},
        {"e": "number.export_power_limit", "n": "Export power limit", "a": None, "d": "dev_sg",
         "dn": "Sungrow SH10RT", "m": "Sungrow", "mo": "SH10RT", "dc": "power", "u": "W", "st": "10000"},
    ]
    result = discover_house(sungrow)
    assert result["solar"]["pv_power_entity"] == "sensor.total_dc_power"
    assert "export_limit_pct" not in result["solar"]["generic_suggestion"]["entities"]
    assert result["solar"]["generic_suggestion"]["entities"]["export_limit_w"] == "number.export_power_limit"


def test_huawei_foreslar_tjanstedrivrutinen_med_enhetens_id():
    huawei = [
        {"e": "sensor.inverter_input_power", "n": "Inverter Input power", "a": None, "d": "dev_hw",
         "dn": "SUN2000-10KTL-M1", "m": "Huawei", "mo": "SUN2000-10KTL-M1", "dc": "power", "u": "W", "st": "5200"},
        {"e": "sensor.inverter_daily_yield", "n": "Inverter Daily yield", "a": None, "d": "dev_hw",
         "dn": "SUN2000-10KTL-M1", "m": "Huawei", "mo": "SUN2000-10KTL-M1", "dc": "energy", "u": "kWh", "st": "12.3"},
    ]
    result = discover_house(huawei)
    assert result["solar"]["generic_suggestion"] == {
        "driver": "huawei_solar",
        "entities": {"pv_power_w": "sensor.inverter_input_power", "device_id": "dev_hw"},
    }


def test_tomt_hus_ger_inga_fynd_kraschar_inte():
    with patch("discovery._check_configured_heat_pump", return_value=None):
        result = discover_house([])
    assert result == {"cars": [], "heat_pump": None, "solar": None, "spa": None, "chargers": [], "grid_meters": [], "power_meter": None, "battery": None, "power_sensors": [], "compressor_sensors": []}


def test_ha_fynd_vinner_over_serverchecken_inte_overskrivs():
    """Om HA-sökningen redan hittade en pump (t.ex. NIBE utan drivrutin) ska servercheckens
    Husdata-gissning inte tränga undan ett RIKTIGT HA-fynd."""
    only_nibe = [e for e in SYNTHETIC_ENTITIES if e["d"] in ("dev_nibe",)]
    with patch("discovery._check_configured_heat_pump", return_value={"maker": "Husdata"}) as mock_check:
        result = discover_house(only_nibe)
    assert result["heat_pump"]["maker"] == "NIBE"
    mock_check.assert_not_called()


# ---------- _check_configured_heat_pump: pumpen svarar redan via Modbus på servern ----------

def test_check_configured_heat_pump_ingen_fardsk_rad_ger_none(smartbox):
    with smartbox.get_db() as conn:
        conn.execute("TRUNCATE sensor_log")
        conn.commit()
    assert discovery._check_configured_heat_pump() is None


def _husdata_cfg(monkeypatch, tmp_path, driver="thermia_husdata"):
    cfg = tmp_path / "house.yaml"
    cfg.write_text(f"heat_pump:\n  enabled: true\n  driver: {driver}\n")
    monkeypatch.setenv("HOUSE_CONFIG_PATH", str(cfg))


def test_check_configured_heat_pump_fardsk_rad_hittas(smartbox, monkeypatch, tmp_path):
    _husdata_cfg(monkeypatch, tmp_path)
    with smartbox.get_db() as conn, conn.cursor() as cur:
        cur.execute("TRUNCATE sensor_log")
        cur.execute(
            "INSERT INTO sensor_log (timestamp, indoor_temp, forward_temp) VALUES (%s, %s, %s)",
            (datetime.now(timezone.utc), 21.3, 35.0),
        )
        conn.commit()

    result = discovery._check_configured_heat_pump()
    assert result is not None
    assert result["driver"] == "thermia_husdata" and result["driver_known"] is True
    assert result["source"] == "modbus_configured_on_server"


def test_innetemp_fran_rumsgivare_ar_ingen_husdata(smartbox, monkeypatch, tmp_path):
    """#162: en NIBE-ägare med innetemperatur från HA-givare fick "Husdata redan ansluten"."""
    _husdata_cfg(monkeypatch, tmp_path, driver="ha_entities")
    with smartbox.get_db() as conn, conn.cursor() as cur:
        cur.execute("TRUNCATE sensor_log")
        cur.execute("INSERT INTO sensor_log (timestamp, indoor_temp) VALUES (%s, %s)", (datetime.now(timezone.utc), 18.2))
        conn.commit()
    assert discovery._check_configured_heat_pump() is None
    _husdata_cfg(monkeypatch, tmp_path)                   # Husdata vald men pumpen har inte loggat framledning
    assert discovery._check_configured_heat_pump() is None


def test_check_configured_heat_pump_gammal_rad_raknas_inte(smartbox):
    with smartbox.get_db() as conn, conn.cursor() as cur:
        cur.execute("TRUNCATE sensor_log")
        cur.execute(
            "INSERT INTO sensor_log (timestamp, indoor_temp) VALUES (%s, %s)",
            (datetime.now(timezone.utc) - timedelta(hours=2), 21.3),
        )
        conn.commit()

    assert discovery._check_configured_heat_pump() is None


def test_pulse_och_smartmatare_hittas_bada_inte_bara_en():
    """Emils egen poäng (2026-10-30): ett hus kan ha Pulse, en smartmätare, eller
    båda - discovery ska lista alla matchande, inte bara returnera den första."""
    result = discover_house(SYNTHETIC_ENTITIES)
    assert len(result["grid_meters"]) == 2
    kinds = {g["kind"] for g in result["grid_meters"]}
    assert kinds == {"pulse", "smartmätare"}
    # Solcellssensorn (också en power-sensor) ska INTE räknas som elmätare.
    grid_entities = {g["power_entity"] for g in result["grid_meters"]}
    assert "sensor.solaredge_power" not in grid_entities


# ---------- Husbatteri ----------

def test_kant_batterimarke_hittas_och_foreslar_generisk_drivrutin():
    givenergy = [
        {"e": "sensor.givenergy_soc", "n": "Battery SOC", "a": "Garage", "d": "dev_battery",
         "dn": "GivEnergy", "m": "GivEnergy", "mo": "AIO", "dc": "battery", "u": "%", "st": "72"},
        {"e": "sensor.givenergy_power", "n": "Battery Power", "a": "Garage", "d": "dev_battery",
         "dn": "GivEnergy", "m": "GivEnergy", "mo": "AIO", "dc": "power", "u": "W", "st": "-850"},
    ]
    result = discover_house(givenergy)
    assert result["battery"] is not None
    assert result["battery"]["maker"] == "GivEnergy"
    assert result["battery"]["driver"] is None
    assert result["battery"]["driver_known"] is False
    assert result["battery"]["generic_suggestion"] == {
        "driver": "generic", "entities": {"soc": "sensor.givenergy_soc", "power": "sensor.givenergy_power"},
    }


def test_okant_batterimarke_med_soc_och_effekt_hittas_anda():
    """Inget känt märke i BATTERY_MAKERS, men BÅDE en battery-%-sensor OCH en
    effektsensor (laddar/laddar ur) på samma enhet räcker för att misstänka ett
    husbatteri - soc ensam räcker inte (se false-positive-testet nedan)."""
    unknown_battery = [
        {"e": "sensor.acme_batt_soc", "n": "State of Charge", "a": "Garage", "d": "dev_acme",
         "dn": "Acme Battery", "m": "Acme", "mo": "X1", "dc": "battery", "u": "%", "st": "55"},
        {"e": "sensor.acme_batt_power", "n": "Battery Power", "a": "Garage", "d": "dev_acme",
         "dn": "Acme Battery", "m": "Acme", "mo": "X1", "dc": "power", "u": "W", "st": "-400"},
    ]
    result = discover_house(unknown_battery)
    assert result["battery"] is not None
    assert result["battery"]["maker"] == "Acme"


def test_batteridriven_sensor_med_eget_myntcellsbatteri_feltolkas_inte_som_husbatteri():
    """Bekräftat live mot Emils riktiga HA: en vanlig temperatur-/fuktgivare med eget
    myntcellsbatteri (battery-%, men INGEN effektsensor) gav en falsk träff innan
    effektkravet lades till - en battery-%-sensor ensam är för löst, alla
    batteridrivna prylar (dörrsensorer, fjärrkontroller, IKEA-givare m.fl.) har en."""
    coin_cell_sensor = [
        {"e": "sensor.tempsensor_battery", "n": "Battery", "a": "Vardagsrum", "d": "dev_tempsensor",
         "dn": "Temp/Fukt-givare", "m": "IKEA of Sweden", "mo": "VINDSTYRKA", "dc": "battery", "u": "%", "st": "87"},
        {"e": "sensor.tempsensor_temp", "n": "Temperatur", "a": "Vardagsrum", "d": "dev_tempsensor",
         "dn": "Temp/Fukt-givare", "m": "IKEA of Sweden", "mo": "VINDSTYRKA", "dc": "temperature", "u": "°C", "st": "21.0"},
    ]
    result = discover_house(coin_cell_sensor)
    assert result["battery"] is None


def test_bilens_batteriprocent_feltolkas_inte_som_husbatteri():
    """Kritisk avgränsning: Teslans battery-%-sensor (redan klassad som bil) ska INTE
    också dyka upp som ett husbatteri-fynd."""
    only_tesla = [e for e in SYNTHETIC_ENTITIES if e["d"] == "dev_tesla"]
    result = discover_house(only_tesla)
    assert len(result["cars"]) == 1
    assert result["battery"] is None


def test_mobilens_batteri_raknas_inte_som_husbatteri():
    only_phone = [e for e in SYNTHETIC_ENTITIES if e["d"] == "dev_phone"]
    result = discover_house(only_phone)
    assert result["battery"] is None


def test_solaredge_lagringsniva_pa_vaxelriktaren_feltolkas_inte_som_husbatteri():
    """Bekräftat live mot Emils riktiga HA: SolarEdges integration skapar alltid en
    'Lagringsnivå' (storage-%) -sensor på VÄXELRIKTARENS egen enhet, oavsett om man
    faktiskt har ett batteri (state 'unknown' utan ett) - och dess effektsensor är
    bara soleffekten, inte batterieffekt. Samma enhet som redan är solcellsfyndet
    ska inte DUBBELT också räknas som ett separat husbatteri."""
    solaredge_no_battery = SYNTHETIC_ENTITIES + [
        {"e": "sensor.solaredge_storage_level", "n": "Lagringsnivå", "a": "Garage", "d": "dev_inverter",
         "dn": "SolarEdge Inverter", "m": "SolarEdge", "mo": "SE10K", "dc": "battery", "u": "%", "st": "unknown"},
    ]
    result = discover_house(solaredge_no_battery)
    assert result["solar"] is not None
    assert result["battery"] is None


def test_inget_batteri_ger_none_inte_krasch():
    result = discover_house([e for e in SYNTHETIC_ENTITIES if e["d"] == "dev_light"])
    assert result["battery"] is None


def _inverter(entity, name, device, maker="Growatt", unit="W", state="1000"):
    return {"e": entity, "n": name, "a": "Tak", "d": device, "dn": device, "m": maker, "mo": "X",
            "dc": "power" if unit == "W" else "energy", "u": unit, "st": state}


def test_flera_vaxelriktare_summeras_utan_strangar():
    """Guiden tar en solgivare per växelriktare. Totalen vinner över samma växelriktares strängar."""
    ents = [
        _inverter("sensor.east_pv_power_total", "PV power total", "dev_east"),
        _inverter("sensor.east_mppt_module_0_dc_power", "MPPT module 0 DC power", "dev_east", state="400"),
        _inverter("sensor.west_pv_power", "PV power", "dev_west", maker="Solis"),
        _inverter("sensor.east_today", "Today's yield", "dev_east", unit="kWh", state="6"),
        _inverter("sensor.west_today", "Today's yield", "dev_west", maker="Solis", unit="kWh", state="4"),
        _inverter("number.east_export_limit", "Export limit", "dev_east", unit="%", state="100"),
    ]
    solar = discover_house(ents)["solar"]
    sug = solar["generic_suggestion"]
    assert sug["driver"] == "generic_number"
    assert sug["entities"]["pv_power_w"] == ["sensor.east_pv_power_total", "sensor.west_pv_power"]
    assert sug["entities"]["sum_inverters"] is True
    assert sug["entities"]["today_kwh"] == ["sensor.east_today", "sensor.west_today"]
    assert "export_limit_pct" not in sug["entities"] and "export_limit_w" not in sug["entities"]
    assert solar["driver"] is None


def test_fronius_mppt_moduler_summeras():
    """#139: Fronius GEN24 har en DC-effekt per MPPT-modul. Guiden föreslår alla moduler summerade, aldrig AC-effekten
    (den innehåller batteriets urladdning) och aldrig en totalgivare två gånger."""
    d = dict(a="Garage", d="dev_gen24", dn="Fronius GEN24", m="Fronius", mo="Symo GEN24 8.0 Plus", dc="power", u="W")
    ents = [
        {"e": "sensor.fronius_symo_gen24_8_0_plus_mppt_module_0_dc_power", "n": "MPPT module 0 DC power", "st": "2100", **d},
        {"e": "sensor.fronius_symo_gen24_8_0_plus_mppt_module_1_dc_power", "n": "MPPT module 1 DC power", "st": "1700", **d},
    ]
    sug = discover_house(ents)["solar"]["generic_suggestion"]
    assert sug["entities"]["pv_power_w"] == [ents[0]["e"], ents[1]["e"]] and sug["entities"]["sum_inverters"] is True
    one = discover_house(ents[:1])["solar"]["generic_suggestion"]
    assert one["entities"]["pv_power_w"] == ents[0]["e"] and "sum_inverters" not in one["entities"]


def test_guidens_yaml_med_summerade_moduler_blir_lista_och_ja():
    import importlib.util, os, sys
    from pathlib import Path
    import yaml
    root = Path(__file__).resolve().parent.parent
    cwd = os.getcwd()
    os.chdir(root / "webdashboard")
    try:
        mod = sys.modules.get("webdashboard_app")
        if mod is None:
            spec = importlib.util.spec_from_file_location("webdashboard_app", root / "webdashboard" / "app.py")
            mod = importlib.util.module_from_spec(spec)
            sys.modules["webdashboard_app"] = mod
            spec.loader.exec_module(mod)
        sol = {"driver": "generic_number", "entities": {"pv_power_w": ["sensor.m0_dc_power", "sensor.m1_dc_power"], "sum_inverters": True}}
        cfg = yaml.safe_load(mod._build_house_config_yaml({"solar": sol}))
    finally:
        os.chdir(cwd)
    assert cfg["solar"]["entities"] == {"pv_power_w": ["sensor.m0_dc_power", "sensor.m1_dc_power"], "sum_inverters": True}


def test_tibbers_produktion_blir_inte_solceller():
    """Telemetri 2026-11-07: guiden valde Tibber Pulses 'power production' (exporten) som solproduktion."""
    ents = [{"e": "sensor.tibber_pulse_hemma_power_production", "n": "Power production", "a": None, "d": "dev_tibber",
             "dn": "Hemma", "m": "Tibber", "mo": "Price Sensor", "dc": "power", "u": "W", "st": "0"}]
    assert discover_house(ents)["solar"] is None
    ents.append({"e": "sensor.solis_pv_power", "n": "PV Power", "a": None, "d": "dev_solis", "dn": "Solis",
                 "m": "Solis", "mo": "S6", "dc": "power", "u": "W", "st": "1200"})
    assert discover_house(ents)["solar"]["pv_power_entity"] == "sensor.solis_pv_power"


def test_nibe_myuplink_kompressor_kopplas():
    """#184: kompressorns frekvens kopplas så att flödet vet om pumpen går (inte starttider eller drifttimmar)."""
    from discovery import _nibe_bt_entities
    base = dict(dc="temperature", u="°C", d="dev", m="NIBE")
    ents = [{"e": "sensor.f750_bt1", "n": "F750 Utomhustemperatur (BT1)", **base},
            {"e": "sensor.f750_bt2", "n": "F750 Framledning (BT2)", **base},
            {"e": "sensor.f750_kompressor_starter", "n": "F750 Kompressor starter", "dc": None, "u": None, "d": "dev", "m": "NIBE"},
            {"e": "sensor.f750_kompressorfrekvens", "n": "F750 Kompressorfrekvens, aktuell", "dc": "frequency", "u": "Hz", "d": "dev", "m": "NIBE"}]
    assert _nibe_bt_entities(ents)["compressor"] == "sensor.f750_kompressorfrekvens"
