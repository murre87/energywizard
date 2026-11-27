"""#583: legionellaraden i översikten ska säga det verkliga läget (dagar, temperatur, skuggläge) och vara översatt."""
import re
from pathlib import Path

import i18n_py
import legionella_text as lt

OLD = "🦠 Prio 7 (LEGIONELLA): 14 dagar passerade -> Tvingande körning till 60°C."
OTHER = "🟢 Grundläge: Billig el (1.02 kr <= 1.13 kr). Värmepump och Varmvatten i normaldrift."


def test_verkliga_dagar_och_temperatur_i_stallet_for_gransen():
    out = lt.explain([OTHER, OLD], 23.4, 14, 60.0, False)
    assert out[0] == OTHER
    assert out[1] == ("🦠 Prio 7 (LEGIONELLA): 23 dagar sedan varmvattnet senast mättes på 60°C (gräns 14 dagar) "
                      "-> Tvingande körning till 60°C.")


def test_skugglage_sager_att_inget_skickas():
    out = lt.explain([OLD], 23.4, 14, 60.0, True)[0]
    assert "Skuggläge" in out and "Tvingande körning till" not in out


def test_aldrig_uppmatt_sager_det():
    out = lt.explain([OLD], 999.0, 14, 60.0, False)[0]
    assert "aldrig mätts på 60°C" in out and "999" not in out


def test_andra_rader_och_proaktiva_raden_lamnas_ororda():
    proaktiv = "🦠 Prio 7 (LEGIONELLA): Proaktiv körning (Dag 12+ och gynnsamt pris/sol) till 60°C."
    assert lt.explain([OTHER, proaktiv], 13, 14, 60.0, False) == [OTHER, proaktiv]


def test_alla_varianter_ar_oversatta_till_en_och_cs():
    for days in (23.4, 999.0):
        for shadow in (False, True):
            line = lt.explain([OLD], days, 14, 60.0, shadow)[0]
            for lang in ("en", "cs"):
                tr = i18n_py.tr(line, lang)
                assert tr != line and not re.search(r"dagar|Varmvatten|Skuggläge|Tvingande", tr), (lang, tr)


def test_motorn_skriver_om_raden_efter_gpm():
    src = (Path(__file__).resolve().parent.parent / "smartbox" / "main.py").read_text()
    assert "import legionella_text" in src
    i = src.index("gpm_actions = _planner.evaluate(gpm_engine, gpm_state)")
    assert "legionella_text.explain(gpm_actions[\"log\"]" in src[i:i + 600]
