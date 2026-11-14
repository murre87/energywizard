"""Alla synliga svenska texter i appen, webben och de delade skripten ska finnas på engelska och tjeckiska.
Söker igenom källkoden (text mellan taggar, strängar och mallar) efter svensk text och kör den genom översättningen.
Fallerar när en ny text saknar översättning - så att ingen ändring kan mergas utan den (Emil 2026-11-14)."""
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "smartbox"))

import i18n_py

FILES = [os.path.join(ROOT, "ewapp", "static", "app.js"), os.path.join(ROOT, "webdashboard", "static", "app.js")] + \
    [os.path.join(ROOT, "smartbox", "static", f) for f in sorted(os.listdir(os.path.join(ROOT, "smartbox", "static"))) if f.endswith(".js")]
SV_HINT = re.compile(r"[åäöÅÄÖ]|\b(och|inte|för|att|är|på|till|med|eller|när|kvar|idag|imorgon|ingen|laddar|laddat|veckan|månad|dygn|"
                     r"timmar|minuter|sparat|billig|dyr|elpris|bilen|huset|pumpen|planen|visa|stäng|spara|avbryt|välj|ladda|sol|nät|inne|"
                     r"ute|mål|läge|klar|borta|hemma|vilar|går|köper|säljer|totalt|senast|nästa|förra|alla|inga|okänd|saknas)\b", re.I)
SKIP = re.compile(r"[{}();=<>]|=>|\.\w+\(|^[a-z_]+$|^[a-z]+[A-Z]|https?:|/api/|#[0-9a-f]{3}|\bvar\(|px\b|rem\b")


def visible_texts(src):
    found = set()
    for rx in (r">([^<>${}`]{2,200})<", r"""["']([A-ZÅÄÖa-zåäö][^"'\\\n]{1,150})["']""", r"`([^`$]{2,200})`"):
        found.update(m.group(1) for m in re.finditer(rx, src))
    for s in found:
        t = re.sub(r"\s+", " ", s).strip()
        if len(t) >= 3 and re.search(r"[A-Za-zÅÄÖåäö]{3}", t) and not SKIP.search(t) and SV_HINT.search(t):
            yield t, s.strip()


def _translated(t, lang, raw=None):
    d = i18n_py._dict(lang)
    if t in d or (raw and raw in d) or re.sub(r"\d+(?:[.,]\d+)?", "#", t) in d:
        return True                       # finns i katalogen (även om översättningen råkar vara likadan, t.ex. "öre")
    return i18n_py.tr(t, lang) != t


def test_alla_synliga_texter_är_översatta():
    missing = {}
    for f in FILES:
        src = open(f, encoding="utf-8").read()
        for t, raw in visible_texts(src):
            for lang in ("en", "cs"):
                if not _translated(t, lang, raw):
                    missing.setdefault(f"{lang}: {t}", os.path.relpath(f, ROOT))
    assert not missing, "Saknar översättning:\n" + "\n".join(f"  {k}   ({v})" for k, v in sorted(missing.items()))


def test_avslutande_parentes_följer_med():
    """"Gråzon (1.39 kr)." tappade sin parentes vid uppslaget och stod kvar på svenska (i18n_py och i18n.js)."""
    assert i18n_py.tr("Gråzon (1.39 kr). Ligger kvar i läge 'EXPENSIVE'.", "en").startswith("Grey zone (1.39 kr).")
    js = open(os.path.join(ROOT, "smartbox", "i18n", "i18n.js"), encoding="utf-8").read()
    assert "en avslutande parentes som hör till texten" in js
