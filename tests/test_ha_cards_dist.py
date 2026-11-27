"""HACS hämtar korten ur dist/ (hacs.json i roten). ha-cards/ är källan och förhandsvisningen; de två filerna måste vara lika."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_dist_ar_samma_fil_som_kallan():
    assert (ROOT / "dist" / "energywizard-cards.js").read_text(encoding="utf-8") == \
        (ROOT / "ha-cards" / "energywizard-cards.js").read_text(encoding="utf-8"), "kopiera ha-cards/energywizard-cards.js till dist/"


def test_hacs_json_pekar_pa_filen():
    h = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))
    assert h["filename"] == "energywizard-cards.js" and (ROOT / "dist" / h["filename"]).is_file()


def test_korten_ar_registrerade():
    js = (ROOT / "dist" / "energywizard-cards.js").read_text(encoding="utf-8")
    for tag in ("energywizard-house-card", "energywizard-heat-card", "energywizard-car-card", "energywizard-economy-card", "energywizard-battery-card", "energywizard-bath-card"):
        assert f'customElements.define("{tag}"' in js
    assert "a.eco" in js and "button[data-period]" in js and "Sparat genom tajmning" in js
    assert "Mot självförbrukning" in js and 'data-period="all"' not in js and "data-period=\"all\"" not in js
    assert "a.batt" in js and "a.solar" in js and "Sparar" in js
    assert "a.bath" in js and "Uppvärmning planeras inför badtiden" in js


def test_bilkortets_knappar_anropar_ha_och_visas_bara_med_vaeljare():
    js = (ROOT / "dist" / "energywizard-cards.js").read_text(encoding="utf-8")
    assert 'callService("select", "select_option"' in js and "select.energywizard_ev_${c.id}_mode" in js
    assert "controls !== false" in js            # kan stängas av i kortets inställningar
