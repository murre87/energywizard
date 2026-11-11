const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const element = () => ({ innerHTML: '', style: { setProperty() {} }, classList: { add() {}, remove() {} },
  setAttribute() {}, removeAttribute() {}, addEventListener() {}, querySelectorAll: () => [] });
const app = element(), tabs = element();
let savedPrimary = '';
const ctx = vm.createContext({ console, document: { documentElement: element(), body: element(),
  querySelector: s => s === '#app' ? app : s === '#tabs' ? tabs : null, addEventListener() {} },
  localStorage: { getItem: k => k === 'ew_primary' ? savedPrimary : null }, navigator: {}, location: { search: '' }, URLSearchParams,
  innerWidth: 400, innerHeight: 800, history: { replaceState() {} }, addEventListener() {},
  matchMedia: () => ({ matches: false }), setTimeout() {}, clearTimeout() {}, setInterval() {} });
ctx.window = ctx;
vm.runInContext(fs.readFileSync('ewapp/static/app.js', 'utf8').replace(/\nstart\(\);\s*$/, ''), ctx);
vm.runInContext('fit = () => {};', ctx);
for (const saved of ['', 'old-car']) {
  savedPrimary = saved;
  for (const role of ['owner', 'family', 'guest']) {
    vm.runInContext(`ROLE = ${JSON.stringify(role)}; S = {ok: true, cars: []}; render();`, ctx);
    assert.match(app.innerHTML, /Inga bilar hittades/);
    assert.match(app.innerHTML, /data-a="settings"/);
    assert.match(tabs.innerHTML, /data-v="hem"/);
    vm.runInContext('S = {ok: false, cars: [], error: "HA <unavailable>"}; render();', ctx);
    assert.match(app.innerHTML, /HA &lt;unavailable&gt;/);
    assert.doesNotMatch(app.innerHTML, /Vilken bil kör du mest/);
  }
}
savedPrimary = '';
vm.runInContext('S = {ok: true, cars: [{key: "ev", name: "My EV"}]}; render();', ctx);
assert.match(app.innerHTML, /data-p="ev"/);
console.log('Empty-car navigation, server errors, saved preferences, roles and car picker passed');
