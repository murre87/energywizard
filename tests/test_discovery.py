"""Bevisar att smartbox/discovery.py:s kategori-regexer faktiskt hittar rätt
TYP av entitet i ett syntetiskt Home Assistant-svar (samma form som
/api/template ger) - inte bara att koden kör utan att krascha. Rör aldrig
riktig hårdvara/nätverk - entities skickas in direkt, read_all_entities()
anropas aldrig här."""
from discovery import discover_house

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
    assert result["solar"]["driver"] == "solaredge" and result["solar"]["driver_known"] is True


def test_gecko_spa_hittas():
    result = discover_house(SYNTHETIC_ENTITIES)
    assert result["spa"] is not None
    assert result["spa"]["current_temp_entity"] == "climate.spa_heater"
    assert result["spa"]["power_entity"] == "sensor.spa_power"
    assert result["spa"]["driver"] == "gecko" and result["spa"]["driver_known"] is True


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


def test_okant_varmepumpsmarke_flaggas_utan_drivrutin_inte_tyst_fel_eller_kraschar():
    """NIBE hittas (matchar HEATPUMP-regexen) men har ingen registrerad drivrutin -
    ska synas med driver_known=False, inte krascha och inte tyst väljas som Husdata."""
    only_nibe = [e for e in SYNTHETIC_ENTITIES if e["d"] in ("dev_nibe",)]
    result = discover_house(only_nibe)
    assert result["heat_pump"] is not None
    assert result["heat_pump"]["maker"] == "NIBE"
    assert result["heat_pump"]["driver"] is None
    assert result["heat_pump"]["driver_known"] is False


def test_tomt_hus_ger_inga_fynd_kraschar_inte():
    result = discover_house([])
    assert result == {"cars": [], "heat_pump": None, "solar": None, "spa": None, "chargers": [], "grid_meters": []}


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
