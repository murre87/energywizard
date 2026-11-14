"""Konfigurerbar elmätare (homeassistant.read_power_meter / detect_tibber_pulse, house_config,
entitetsväljaren). Förut hårdkodad till ett enda hus Tibber Pulse."""
from unittest.mock import patch

import homeassistant as ha
from discovery import discover_house
from house_config import power_meter_entities

STATE = {}


def _num(e):
    return STATE.get(e)


def _with(entities, states):
    STATE.clear(); STATE.update(states)
    ha.configure_power_meter(entities)


def test_per_fas_spanning_och_strom():
    _with({f"voltage_l{n}": f"s.v{n}" for n in (1, 2, 3)} | {f"current_l{n}": f"s.i{n}" for n in (1, 2, 3)},
          {"s.v1": 230, "s.v2": 230, "s.v3": 230, "s.i1": 10, "s.i2": -2, "s.i3": 0})
    with patch.object(ha, "_get_numeric_state", _num):
        r = ha.read_power_meter()
    assert r == {"net_power_w": 230 * 8, "l1_a": 10, "l2_a": -2, "l3_a": 0}


def test_nettoeffekt_med_och_utan_teckenvandning():
    _with({"power_w": "s.p"}, {"s.p": 1500})
    with patch.object(ha, "_get_numeric_state", _num):
        assert ha.read_power_meter() == {"net_power_w": 1500, "l1_a": None, "l2_a": None, "l3_a": None}
    _with({"power_w": "s.p", "power_w_invert": True}, {"s.p": 1500})
    with patch.object(ha, "_get_numeric_state", _num):
        assert ha.read_power_meter()["net_power_w"] == -1500


def test_import_export_p1():
    _with({"import_w": "s.imp", "export_w": "s.exp", "current_l1": "s.i1"}, {"s.imp": 200, "s.exp": 3200, "s.i1": -13})
    with patch.object(ha, "_get_numeric_state", _num):
        r = ha.read_power_meter()
    assert r["net_power_w"] == -3000 and r["l1_a"] == -13 and r["l2_a"] is None


def _esphome_p1(prefix="", device="p1"):
    def sensor(name, unit, value):
        return dict(e=f"sensor.{prefix}{name}", n=name.replace("_", " ").title(),
                    d=device, dn="ESP P1 reader", m="ESPHome", u=unit,
                    dc="current" if unit == "A" else "power", st=str(value))
    return ([sensor(f"current_phase_{ph}", "A", ph) for ph in (1, 2, 3)]
            + [sensor(f"momentary_active_{direction}_phase_{ph}", "kW", 99)
               for direction in ("import", "export") for ph in (1, 2, 3)]
            + [sensor("momentary_reactive_import", "kvar", 99),
               sensor("momentary_active_import", "kW", 0.2),
               sensor("momentary_active_export", "kW", 3.2)])


def test_esphome_p1_discovery_and_signed_power_with_phase_currents():
    for prefix in ("", "garage_"):
        entities = _esphome_p1(prefix)
        mapping = discover_house(entities)["power_meter"]["entities"]
        assert mapping == dict(import_w=f"sensor.{prefix}momentary_active_import",
                               export_w=f"sensor.{prefix}momentary_active_export",
                               **{f"current_l{ph}": f"sensor.{prefix}current_phase_{ph}" for ph in (1, 2, 3)})
        cache = {e["e"]: {"attributes": {"unit_of_measurement": e["u"]}} for e in entities}
        _with(mapping, {e["e"]: float(e["st"]) for e in entities})
        with patch.object(ha, "_get_numeric_state", _num), patch.object(ha, "_states_cache", cache):
            assert ha.read_power_meter() == dict(net_power_w=-3000, l1_a=1, l2_a=2, l3_a=3)
        ha.configure_power_meter({})


def test_esphome_p1_never_pairs_devices_or_ambiguous_total_entities():
    entities = _esphome_p1()
    entities[-1]["d"] = "other"
    result = discover_house(entities)["power_meter"]
    assert not result or "import_w" not in result["entities"]
    entities = _esphome_p1()
    entities.append(dict(entities[-1], e="sensor.duplicate_momentary_active_export"))
    result = discover_house(entities)["power_meter"]
    assert not result or "import_w" not in result["entities"]


def test_mataren_svarar_inte():
    _with({"power_w": "s.p"}, {})
    with patch.object(ha, "_get_numeric_state", _num):
        assert ha.read_power_meter() is None


def test_tibber_pulse_hittas_automatiskt_svenska_och_engelska_namn():
    sv = [f"sensor.tibber_pulse_hemma_spanning_fas{n}" for n in (1, 2, 3)] + [f"sensor.tibber_pulse_hemma_strom_fas{n}" for n in (1, 2, 3)] \
        + ["sensor.tibber_pulse_hemma_ackumulerad_forbrukning_under_aktuell_timme", "sensor.annat"]
    d = ha.detect_tibber_pulse(sv)
    assert d["voltage_l1"] == "sensor.tibber_pulse_hemma_spanning_fas1" and d["current_l3"] == "sensor.tibber_pulse_hemma_strom_fas3"
    assert d["hour_kwh"].endswith("_ackumulerad_forbrukning_under_aktuell_timme")
    en = [f"sensor.tibber_pulse_home_voltage_phase{n}" for n in (1, 2, 3)] + [f"sensor.tibber_pulse_home_current_l{n}" for n in (1, 2, 3)]
    assert ha.detect_tibber_pulse(en)["current_l2"] == "sensor.tibber_pulse_home_current_l2"
    assert ha.detect_tibber_pulse(sv[:4]) == {}                      # ofullständig Pulse räknas inte


def test_utan_config_anvands_automatiskt_hittad_pulse():
    ids = [f"sensor.tibber_pulse_x_spanning_fas{n}" for n in (1, 2, 3)] + [f"sensor.tibber_pulse_x_strom_fas{n}" for n in (1, 2, 3)]
    _with({}, {i: (230 if "spanning" in i else 1) for i in ids})
    with patch.object(ha, "_states_cache", {i: {} for i in ids}), patch.object(ha, "_get_numeric_state", _num):
        assert ha.read_power_meter()["net_power_w"] == 690
    ha.configure_power_meter({})


def test_house_config_power_meter():
    cfg = {"power_meter": {"driver": "power_w", "power_w_invert": True, "entities": {"power_w": "sensor.p1"}}}
    assert power_meter_entities(cfg) == {"power_w": "sensor.p1", "power_w_invert": True}
    assert power_meter_entities({}) == {}


def test_entitetsvaljaren_foreslar_pulse_och_annars_effektsensor():
    pulse = [{"e": f"sensor.tibber_pulse_hem_{k}_fas{n}", "n": f"{k} fas{n}", "a": None, "d": "dev_p", "dn": "Pulse", "m": "Tibber",
              "mo": "Pulse", "dc": "voltage" if k == "spanning" else "current", "u": "V" if k == "spanning" else "A", "st": "1"}
             for k in ("spanning", "strom") for n in (1, 2, 3)]
    r = discover_house(pulse)
    assert r["power_meter"]["driver"] == "tibber_pulse" and r["power_meter"]["entities"]["current_l1"] == "sensor.tibber_pulse_hem_strom_fas1"
    p1 = [{"e": "sensor.p1_power", "n": "P1 Power meter", "a": None, "d": "dev_han", "dn": "HAN", "m": "Easee", "mo": "Equalizer",
           "dc": "power", "u": "W", "st": "900"}]
    r2 = discover_house(p1)
    assert r2["power_meter"] == {"driver": "power_w", "entities": {"power_w": "sensor.p1_power"}}
