"""Steg 5b: märkeskoden (Easee, SolarEdge, Gecko, bilklimat) bor i drivers/ha_*.py och använder bara värdens generella delar.
Bevis: (1) modulerna fungerar mot en falsk värd utan motorns homeassistant, med exakt de HA-anrop som förut; (2) de gamla namnen i homeassistant.py
ger samma anrop (vidarekopplingar); (3) märkesnamnen finns inte längre i värdens yta."""
import contract_guard  # noqa: F401  (testmiljön)
import pytest

from drivers import host, ha_car, ha_easee, ha_gecko, ha_solaredge


class FakeHA:
    """Värden som drivrutinsrepot skulle ha: bara det generella."""
    def __init__(self, states=None, attrs=None, fail=None):
        self.calls, self.failures = [], []
        self.states, self.attrs, self.fail = states or {}, attrs or {}, fail
    def post_service(self, path, payload, timeout=5):
        self.calls.append((path, payload, timeout))
        if self.fail:
            raise self.fail
    def report_failure(self, text, err):
        self.failures.append(text)
    def _get_raw_state(self, e):
        return self.states.get(e)
    def _get_numeric_state(self, e):
        v = self.states.get(e)
        return None if v is None else (1.0 if v == "on" else 0.0 if v == "off" else float(v))   # som den riktiga: on/off blir 1/0
    def _get_numeric_attribute(self, e, a):
        return self.attrs.get((e, a))
    def _climate_now(self, e):
        return self.states.get(e)


@pytest.fixture
def fake():
    def make(**kw):
        f = FakeHA(**kw)
        host.bind(homeassistant=f)
        return f
    yield make
    host.unbind()


def test_easee_calls_are_the_same_ha_services_as_before(fake):
    f = fake()
    assert ha_easee.set_dynamic_limit("EH1", 40, reason="x") is True
    assert ha_easee.set_dynamic_limit("EH1", 3) is True            # 1-5 A klämms till 6, 0 stannar
    assert ha_easee.set_dynamic_limit("EH1", 0) is True
    assert ha_easee.set_phases("EH1", 1) is True and ha_easee.set_phases("EH1", 2) is False
    assert ha_easee.turn_on("EH1", "switch.box") is True and ha_easee.turn_off("EH1", None) is False
    assert f.calls == [
        ("easee/set_charger_dynamic_limit", {"charger_id": "EH1", "current": 32}, 5),
        ("easee/set_charger_dynamic_limit", {"charger_id": "EH1", "current": 6}, 5),
        ("easee/set_charger_dynamic_limit", {"charger_id": "EH1", "current": 0}, 5),
        ("easee/set_charger_phase_mode", {"charger_id": "EH1", "phase_mode": "1_phase"}, 10),
        ("switch/turn_on", {"entity_id": "switch.box"}, 5)]
    assert ha_easee.read_charger({"status": "x"}, "EH1")["phases"] == "SinglePhase"     # minnet av senast satta fasläge
    assert ha_easee._PHASE_STATE == {"EH1": "SinglePhase"}


def test_easee_read_phase_currents_from_both_attribute_names(fake):
    fake(states={"sensor.s": "charging", "sensor.a": "0"}, attrs={("sensor.a", "inCurrentT4"): 7.5})
    r = ha_easee.read_charger({"status": "sensor.s", "current_a": "sensor.a"}, "ny")
    assert r["current_l2"] == 7.5 and r["current_a"] == 7.5 and r["status"] == "charging"


def test_failures_are_reported_through_the_host_not_raised(fake):
    f = fake(fail=RuntimeError("nere"))
    assert ha_easee.set_dynamic_limit("EH1", 10) is False and ha_solaredge.set_limit(50) is False
    assert ha_gecko.set_target(38.0, "climate.spa") is False and ha_gecko.toggle_plug(True, "switch.p") is False
    assert ha_car.set_climate("climate.bil", "heat_cool", 21.0) is False
    assert len(f.failures) == 5


def test_solaredge_gecko_and_car_against_a_fake_host(fake):
    f = fake(states={"sensor.pv": "2380", "number.lim": "77", "sensor.t": "36.5", "switch.eco": "on"})
    assert ha_solaredge.read({"pv_power_w": "sensor.pv"})["pv_power_w"] == 2380.0
    assert ha_solaredge.get_limit("number.lim") == 77.0 and ha_solaredge.set_limit(50, "number.lim") is True
    assert ha_gecko.read({"current_temp": "sensor.t", "economy_mode": "switch.eco"})["economy_mode"] == 1.0
    assert ha_gecko.set_economy(True, "switch.eco") and ha_gecko.set_target(39, "climate.spa") and ha_gecko.toggle_plug(False, "switch.p")
    assert ha_car.set_climate("climate.bil", "heat_cool", 21.0) and ha_car.set_climate("climate.bil", "off", 21.0)
    assert f.calls == [
        ("number/set_value", {"entity_id": "number.lim", "value": "50"}, 5),
        ("switch/turn_on", {"entity_id": "switch.eco"}, 5),
        ("climate/set_temperature", {"entity_id": "climate.spa", "temperature": 39.0}, 5),
        ("switch/turn_off", {"entity_id": "switch.p"}, 5),
        ("climate/set_hvac_mode", {"entity_id": "climate.bil", "hvac_mode": "heat_cool"}, 60),
        ("climate/set_temperature", {"entity_id": "climate.bil", "temperature": 21.0}, 60),
        ("climate/set_hvac_mode", {"entity_id": "climate.bil", "hvac_mode": "off"}, 60)]      # ingen temperatur när klimatet stängs av


def test_the_old_names_in_homeassistant_forward_to_the_brand_modules(monkeypatch):
    import homeassistant as h
    seen = []
    monkeypatch.setattr(h, "post_service", lambda path, payload, timeout=5: seen.append((path, payload, timeout)))
    assert h.set_ev_dynamic_limit("EH1", 16, reason="r") is True and h.set_easee_phases("EH1", 3) is True
    assert h.turn_on_charger("EH1", "switch.b") is True and h.set_solaredge_limit(60) is True
    assert h.set_gecko_target(38.0, "climate.spa") is True and h.toggle_spa_plug(True, "switch.p") is True and h.set_car_climate("climate.b", "off") is True
    assert [p for p, _, _ in seen] == ["easee/set_charger_dynamic_limit", "easee/set_charger_phase_mode", "switch/turn_on", "number/set_value",
                                       "climate/set_temperature", "switch/turn_on", "climate/set_hvac_mode"]
    assert seen[3][1]["entity_id"] == h.SOLAREDGE_DEFAULT_LIMIT and h.CAR_CLIMATE_TIMEOUT_S == 60


def test_the_host_surface_no_longer_contains_brand_names():
    brand = {"read_solaredge", "set_solaredge_limit", "get_solaredge_limit", "read_gecko", "set_gecko_target", "set_gecko_economy", "toggle_spa_plug",
             "read_spa_power", "read_spa_activities", "set_ev_dynamic_limit", "set_easee_phases", "turn_on_charger", "turn_off_charger",
             "set_car_climate", "_read_easee_charger", "_BASE", "_HEADERS", "_VERIFY"}
    assert not brand & host.SURFACE["homeassistant"]
