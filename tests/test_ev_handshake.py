"""Steg 4 (4/4): bevisar att smartbox/ev_handshake.py:s generiska allokering ger
BIT-FÖR-BIT samma resultat som den gamla hårdkodade if/elif-logiken (main.py, innan
denna ändring) för Emils faktiska 2-bilars-fall, över alla rimliga kombinationer av
indata - innan den hårdkodade logiken i main.py byts ut. Det här styr golvgarantin
för elbilsladdning, så det här är det viktigaste testet i hela
drivrutins-ihopkopplingen."""
import itertools

from ev_handshake import resolve_charger_allocations


def _old_hardcoded_logic(lite_conn, carport_conn, nissan_plugged, tesla_plugged, prior):
    """Ordagrann kopia av den gamla logiken (main.py, rad ~879-913, innan Steg 4:4
    bytte ut den) - referensen det nya ska matcha exakt."""
    ev_allocations = dict(prior)
    if lite_conn and ev_allocations['easee_lite'] is None:
        if nissan_plugged and ev_allocations['carport'] != 'nissan':
            ev_allocations['easee_lite'] = 'nissan'
        elif tesla_plugged and ev_allocations['carport'] != 'tesla':
            ev_allocations['easee_lite'] = 'tesla'
        else:
            ev_allocations['easee_lite'] = 'guest'

    if carport_conn and ev_allocations['carport'] is None:
        if tesla_plugged and ev_allocations['easee_lite'] != 'tesla':
            ev_allocations['carport'] = 'tesla'
        elif nissan_plugged and ev_allocations['easee_lite'] != 'nissan':
            ev_allocations['carport'] = 'nissan'
        else:
            ev_allocations['carport'] = 'guest'
    return ev_allocations


def test_generisk_allokering_matchar_gamla_logiken_exakt_for_tva_bilar():
    """Alla kombinationer av anslutning/kabel och tidigare tillstånd (inkl. redan
    tilldelade laddare, "guest", och olika körordning) - den nya generiska funktionen
    måste ge EXAKT samma resultat som den gamla hårdkodade för Nissan/Tesla-fallet."""
    bools = [True, False]
    prior_states = [None, "nissan", "tesla", "guest"]
    cases = 0
    for lite_conn, carport_conn, nissan_plugged, tesla_plugged, p_lite, p_carport in itertools.product(
        bools, bools, bools, bools, prior_states, prior_states
    ):
        prior = {"easee_lite": p_lite, "carport": p_carport}
        expected = _old_hardcoded_logic(lite_conn, carport_conn, nissan_plugged, tesla_plugged, prior)

        physical_chargers = {"easee_lite": lite_conn, "carport": carport_conn}
        car_plugged = {"nissan": nissan_plugged, "tesla": tesla_plugged}
        default_car = {"easee_lite": "nissan", "carport": "tesla"}
        actual = resolve_charger_allocations(physical_chargers, car_plugged, prior, default_car)

        assert actual == expected, (
            f"lite_conn={lite_conn} carport_conn={carport_conn} nissan_plugged={nissan_plugged} "
            f"tesla_plugged={tesla_plugged} prior={prior}: fick {actual}, väntade {expected}"
        )
        cases += 1
    assert cases == 2**4 * 4 * 4  # sanity: alla kombinationer verkligen körda


def test_redan_tilldelad_laddare_rors_inte():
    prior = {"easee_lite": "nissan", "carport": None}
    result = resolve_charger_allocations(
        {"easee_lite": True, "carport": True}, {"nissan": True, "tesla": True}, prior
    )
    assert result["easee_lite"] == "nissan"  # oförändrad, redan tilldelad


def test_ingen_bil_ansluten_ger_guest():
    result = resolve_charger_allocations(
        {"easee_lite": True}, {"nissan": False, "tesla": False}, {"easee_lite": None}
    )
    assert result["easee_lite"] == "guest"


def test_fronkopplad_laddare_tilldelas_inte_alls():
    result = resolve_charger_allocations(
        {"easee_lite": False}, {"nissan": True}, {"easee_lite": None}
    )
    assert result["easee_lite"] is None


def test_genuin_n_generalitet_tre_bilar_tre_laddare():
    """Bevisar att funktionen faktiskt generaliserar, inte bara råkar stämma för två -
    ett syntetiskt 3-bilars/3-laddar-hus som aldrig funnits i den gamla hårdkodade
    logiken (den stödde bara exakt två)."""
    physical = {"laddare_a": True, "laddare_b": True, "laddare_c": True}
    plugged = {"bil_1": True, "bil_2": True, "bil_3": True}
    result = resolve_charger_allocations(physical, plugged, {k: None for k in physical})
    # Alla tre laddare anslutna, alla tre bilar har kabeln i NÅGON laddare ->
    # var och en ska få en egen, unik laddare (ingen krock, ingen "guest").
    assigned_cars = [v for v in result.values() if v != "guest"]
    assert len(assigned_cars) == 3
    assert len(set(assigned_cars)) == 3  # alla olika - ingen bil dubbeltilldelad


def test_fler_bilar_an_laddare_en_blir_utan():
    """Tre bilar, bara två laddare - en bil kan inte få plats denna omgång (inte en
    krasch, bara ingen tilldelning för den som blir över)."""
    physical = {"laddare_a": True, "laddare_b": True}
    plugged = {"bil_1": True, "bil_2": True, "bil_3": True}
    result = resolve_charger_allocations(physical, plugged, {k: None for k in physical})
    assigned_cars = {v for v in result.values() if v != "guest"}
    assert len(assigned_cars) == 2
    assert assigned_cars.issubset({"bil_1", "bil_2", "bil_3"})
