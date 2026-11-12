"""#271: etikett och rörligt värde får inte dela textnod, och startnotisen ska följa språket.

Webbens ordlista slår upp hela textnoden. Sitter entitets-id eller värdens adress i samma nod
blir nyckeln unik för den installationen och översätts aldrig. Korta etiketter i egna noder,
och URL som platshållare i HA-notisen, går att översätta på alla språk.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

import i18n_py

ROOT = Path(__file__).resolve().parents[1]
TITLE = "EnergyWizard: slutför installationen"
MSG = ("Inget hittat än i din house_config.yaml. Gå till [entitetsväljaren](URL) "
       "för att hitta din värmepump, bilar, solceller m.m. automatiskt.")
URL = "http://192.168.1.10:8503"


def test_setup_notice_keeps_the_link_and_follows_the_language():
    src = (ROOT / "smartbox/main.py").read_text(encoding="utf-8")
    assert TITLE in src
    assert "entitetsväljaren](URL)" in src
    assert "solceller m.m. automatiskt." in src
    assert 'i18n_py.tr(_msg, _lang).replace("URL", dashboard_url)' in src
    assert "entitetsväljaren]({dashboard_url})" not in src

    assert i18n_py.tr(TITLE, "sv") == TITLE
    assert i18n_py.tr(MSG, "sv").replace("URL", URL) == MSG.replace("URL", URL)
    en = i18n_py.tr(MSG, "en").replace("URL", URL)
    assert en == ("Nothing found in your house_config.yaml yet. Go to the [entity picker]"
                  f"({URL}) to find your heat pump, cars, solar panels and more automatically.")
    assert "8503" in en and "URL" not in en
    cs = i18n_py.tr(MSG, "cs").replace("URL", URL)
    assert URL in cs and "výběr entit" in cs and "URL" not in cs
    assert i18n_py.tr(TITLE, "en") == "EnergyWizard: finish the installation"
    assert i18n_py.tr(TITLE, "cs") == "EnergyWizard: dokončete instalaci"


def test_discovery_labels_are_separate_text_nodes():
    app = (ROOT / "webdashboard/static/app.js").read_text(encoding="utf-8")
    assert '<span>Effekt</span>' in app and '<span>Dagsenergi</span>' in app
    assert '<span>Använd</span>' in app and '<span>effektsensorn</span>' in app
    assert '<span>ström per fas</span>' in app and '<span>köp- och säljeffekt</span>' in app
    assert 'esc(g.maker || "okänt märke")' in app
    # Värdet (entitets-id) ska inte ligga inuti etikettens span.
    assert "<span>effektsensorn ${" not in app
    assert "<span>Dagsenergi:" not in app


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js required")
def test_browser_dictionary_translates_the_split_labels_and_meter_markup():
    js = r'''
const fs = require("node:fs"), vm = require("node:vm"), assert = require("node:assert/strict");
const root = process.cwd();
function translator(lang) {
  const dict = JSON.parse(fs.readFileSync(root + "/smartbox/i18n/" + lang + ".json", "utf8"));
  const ctx = vm.createContext({console, document:{readyState:"loading", currentScript:null, documentElement:{}, addEventListener(){}},
    localStorage:{getItem:() => lang}, navigator:{}, location:{},
    fetch: async (url) => ({ok:true, json: async () => String(url).endsWith("config")
      ? {default: lang, languages:{sv:"Svenska", en:"English", cs:"Čeština"}} : dict})});
  ctx.window = ctx;
  vm.runInContext(fs.readFileSync(root + "/smartbox/i18n/i18n.js", "utf8"), ctx);
  return ctx;
}
function textNodes(html) {
  return html.split(/<[^>]+>/).map((t) => t.trim()).filter((t) => /\p{L}/u.test(t));
}
(async () => {
  const en = translator("en"), cs = translator("cs");
  await en.I18N.ready; await cs.I18N.ready;
  for (const [src, enT, csT] of [
    ["Använd", "Use", "Použít"],
    ["effektsensorn", "the power sensor", "senzor výkonu"],
    ["Dagsenergi", "Energy today", "Dnešní energie"],
    ["Effekt", "Power", "Výkon"],
    ["ström per fas", "current per phase", "proud po fázích"],
    ["köp- och säljeffekt", "import and export power", "příkon a výkon dodávky"],
    ["okänt märke", "unknown brand", "neznámá značka"],
    ["Smartmätare", "Smart meter", "Chytrý elektroměr"],
  ]) {
    assert.equal(en.I18N.tr(src), enT, src);
    assert.equal(cs.I18N.tr(src), csT, src);
  }
  const app = fs.readFileSync(root + "/webdashboard/static/app.js", "utf8");
  const m = app.match(/const useMeter = \(pm\) =>[\s\S]*?;\r?\n/);
  assert.ok(m, "useMeter");
  const ctx = vm.createContext({esc(s){return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}});
  vm.runInContext(m[0] + "\nthis.useMeter = useMeter;", ctx);
  const tibber = ctx.useMeter({driver:"tibber_pulse", entities:{import_w:"sensor.import", current_l1:"sensor.l1"}});
  assert.deepEqual(textNodes(tibber), ["Använd", "Tibber Pulse (", "köp- och säljeffekt", "ström per fas"]);
  const sensor = ctx.useMeter({driver:"generic", entities:{power_w:"sensor.p1_<power>"}});
  assert.deepEqual(textNodes(sensor), ["Använd", "effektsensorn", "sensor.p1_&lt;power&gt;"]);
  assert.equal(en.I18N.tr(textNodes(sensor)[0]) + " " + en.I18N.tr(textNodes(sensor)[1]), "Use the power sensor");
})().catch((e) => { console.error(e); process.exitCode = 1; });
'''
    result = subprocess.run(["node", "-e", js], cwd=ROOT, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr + result.stdout
