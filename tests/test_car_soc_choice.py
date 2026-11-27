"""#596: laddnivåsensorn kan väljas, och bara den raden skrivs om."""
import shutil
import subprocess
from pathlib import Path

import pytest

from discovery import soc_options
from house_config import replace_car_soc

ROOT = Path(__file__).resolve().parents[1]

YAML = """house_id: "mitt"   # behåll
evs:
  - id: IONIQ
    driver: generic_ev
    entities:
      soc: sensor.old  # kommentar
      plugged_in: binary_sensor.plug
    charger:
      entities:
        soc: sensor.charger_soc
  - id: Traveller
    entities: {soc: sensor.traveller, plugged_in: binary_sensor.t}
"""


def test_byter_bara_bilens_laddniva():
    updated = replace_car_soc(YAML, "IONIQ", "sensor.ioniq_ev_battery_level")
    assert "soc: sensor.ioniq_ev_battery_level  # kommentar" in updated
    assert "sensor.old" not in updated
    assert "sensor.charger_soc" in updated
    assert "soc: sensor.traveller" in updated
    assert "# behåll" in updated


def test_flode_och_ny_rad():
    flow = "evs:\n  - id: bil\n    entities: {plugged_in: binary_sensor.plug}\n"
    updated = replace_car_soc(flow, "bil", "sensor.ev_battery_level")
    assert "soc: sensor.ev_battery_level" in updated and "binary_sensor.plug" in updated
    bare = "evs:\n  - id: bil\n    driver: generic_ev\n"
    inserted = replace_car_soc(bare, "bil", "sensor.ev_battery_level")
    assert "entities:\n" in inserted and "soc: sensor.ev_battery_level" in inserted
    assert "driver: generic_ev" in inserted


def test_okand_bil_och_ogiltig_sensor_andras_inte():
    with pytest.raises(KeyError):
        replace_car_soc(YAML, "saknas", "sensor.ev_battery_level")
    with pytest.raises(ValueError):
        replace_car_soc(YAML, "IONIQ", "sensor.Bad")


def test_samma_enhets_sensorer_ar_de_enda_valen():
    entities = [
        {"e": "sensor.ioniq_car_battery_level", "n": "Car battery level", "d": "car1", "dc": "battery", "u": "%", "st": "12,4"},
        {"e": "sensor.ioniq_ev_battery_level", "n": "EV battery level", "d": "car1", "dc": "battery", "u": "%", "st": "64"},
        {"e": "sensor.other_soc", "n": "Battery", "d": "other", "dc": "battery", "u": "%", "st": "80"},
    ]
    options = soc_options(entities, "sensor.ioniq_car_battery_level")
    assert [row["entity"] for row in options] == ["sensor.ioniq_ev_battery_level", "sensor.ioniq_car_battery_level"]
    assert options[1]["state"] == "12.4"
    assert soc_options([], "sensor.kept_soc") == [{"entity": "sensor.kept_soc", "name": "sensor.kept_soc", "state": None}]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js required")
def test_guiden_och_installningarna_anvander_vald_sensor():
    script = r"""
const fs = require("fs"), vm = require("vm"), assert = require("assert/strict");
const source = fs.readFileSync("webdashboard/static/app.js", "utf8");
const slice = (from, to) => source.slice(source.indexOf(from), source.indexOf(to));
const panel = {innerHTML: ""};
panel.querySelectorAll = () => [];
const document = {
  getElementById: (id) => id === "configuredCars" ? panel : null,
  querySelectorAll: (sel) => sel === ".car-pick:checked" ? [{dataset: {i: "0"}}] : [],
  querySelector: (sel) => ({
    '.car-id[data-i="0"]': {value: "ioniq"},
    '.car-kwh[data-i="0"]': {value: "38"},
    '.car-soc[data-i="0"]': {value: "sensor.ioniq_ev_battery_level"},
    '.car-pick[data-i="0"]': {checked: true},
  })[sel] || null,
  createElement: () => ({click() {}}),
};
let cars = [{
  id: "IONIQ", driver: "generic_ev", battery_kwh: 38, soc: "sensor.ioniq_car_battery_level",
  plugged_in: "binary_sensor.plug", climate: "climate.ioniq",
  soc_options: [
    {entity: "sensor.ioniq_ev_battery_level", name: "EV battery level", state: "64"},
    {entity: "sensor.ioniq_car_battery_level", name: "Car battery level", state: "12.4"},
  ],
}];
const sent = [];
const ctx = {
  document, esc: (s) => String(s), cars, panel, sent,
  _discovered: {cars: [{soc_entity: "sensor.ioniq_car_battery_level", driver: "generic_ev", soc_candidates: cars[0].soc_options}], chargers: [], radiators: []},
  api: async (path) => path.includes("house-config-status") ? {writable: true} : {cars},
  postJSON: async (path, body) => { sent.push({path, body}); return {message: "Sparat. Motorn startar om och läser in den nya inställningen inom en minut."}; },
  fetch: async (url, opts) => { ctx.downloaded = opts.body; return {ok: true, blob: async () => ({}), json: async () => ({})}; },
  wizardForm: () => ({}),
  URL: {createObjectURL: () => "blob:x", revokeObjectURL() {}},
  alert() {},
  window: {},
};
vm.createContext(ctx);
vm.runInContext(slice("function carSocChoices(", "async function renderInstallningar(")
  + slice("async function generateConfig(", "\nfunction openPage("), ctx);
const html = ctx.carSocSelect(ctx._discovered.cars[0], 0, "car-soc");
assert(html.indexOf("sensor.ioniq_ev_battery_level") < html.indexOf("sensor.ioniq_car_battery_level"));
assert(html.includes("selected") && html.includes("64"));
(async () => {
  await ctx.mountConfiguredCars();
  assert(panel.innerHTML.includes("cfg-car-soc") && panel.innerHTML.includes("Spara laddnivå"));
  assert(panel.innerHTML.includes("Välj bilens laddnivå, inte 12 V-batteriet."));
  const btn = {dataset: {i: "0"}};
  panel.querySelector = (sel) => sel.includes("cfg-car-soc-msg") ? {textContent: ""} : {value: "sensor.ioniq_ev_battery_level"};
  panel.querySelectorAll = () => [btn];
  await ctx.mountConfiguredCars();
  await btn.onclick();
  assert.equal(sent.at(-1).path, "api/house-config/car-soc");
  assert.equal(sent.at(-1).body.soc, "sensor.ioniq_ev_battery_level");
  assert.equal(sent.at(-1).body.id, "IONIQ");
  await ctx.generateConfig(false);
  assert.equal(JSON.parse(ctx.downloaded).cars[0].soc_entity, "sensor.ioniq_ev_battery_level");
})().catch((error) => { console.error(error); process.exitCode = 1; });
"""
    completed = subprocess.run(["node", "-e", script], cwd=ROOT, check=False, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stdout + completed.stderr
