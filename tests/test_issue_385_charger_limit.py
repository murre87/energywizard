"""#385: förklara när laddboxen ger bilen mindre ström än EnergyWizard bad om - bara med laddboxens egna värden,
annars "orsaken är okänd". Ändrar aldrig styrningen."""
import os

import charger_limit as cl


def test_ingen_förklaring_när_bilen_får_det_vi_bad_om_eller_inte_laddar():
    assert cl.explain(16, {"current_a": 15.2}) is None
    assert cl.explain(16, {"current_a": 0.0}) is None
    assert cl.explain(0, {"current_a": 8.0}) is None
    assert cl.explain(None, {"current_a": 8.0}) is None


def test_laddboxens_erbjudna_ström_med_orsak():
    d = {"current_a": 11.8, "output_limit_a": 12, "reason_no_current": "max_dynamic_circuit_current_too_low"}
    assert cl.explain(16, d) == "Laddboxen begränsar till 12 A: lastbalansering. EnergyWizard bad om 16 A."


def test_erbjuden_ström_utan_orsak_men_med_kretsgräns():
    d = {"current_a": 10, "output_limit_a": 10, "circuit_limit_a": 10}
    assert "lastbalansering" in cl.explain(16, d)


def test_lastbalanseringens_kretsgräns():
    assert cl.explain(16, {"current_a": 9.9, "circuit_limit_a": 10}) == "Lastbalanseringen tillåter 10 A. EnergyWizard bad om 16 A."


def test_kretsens_märkström():
    assert cl.explain(20, {"current_a": 15.9, "circuit_rated_a": 16.0, "circuit_limit_a": 40}) == \
        "Laddboxens krets är på 16 A. EnergyWizard bad om 20 A."


def test_okänd_orsak_utan_gissning():
    assert cl.explain(16, {"current_a": 8.3, "circuit_limit_a": 40, "circuit_rated_a": 32}) == \
        "Laddboxen ger bilen 8 A av 16 A, orsaken är okänd."


def test_trasiga_värden_kraschar_inte():
    assert cl.explain("x", {"current_a": 8}) is None


def test_kopplat_i_motor_läsare_guide_och_app():
    root = os.path.join(os.path.dirname(__file__), "..")
    rd = lambda *p: open(os.path.join(root, *p), encoding="utf-8").read()
    assert "charger_limit.explain(last_sent_ev_limit.get(car_id), charger_data)" in rd("smartbox", "main.py")
    assert '"circuit_rated_a": _get_numeric_attribute(entities["status"], "circuit_ratedCurrent")' in rd("smartbox", "homeassistant.py")
    assert '"circuit_limit": pick("sensor", r"dynamisk.?krets|dynamic.?circuit")' in rd("smartbox", "discovery.py")
    assert '"limit_note":' in rd("ewapp", "app.py") and "c.limit_note" in rd("ewapp", "static", "app.js")
