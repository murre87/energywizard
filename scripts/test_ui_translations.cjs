const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');

async function runtime(lang) {
  const dict = lang === 'sv' ? {} : JSON.parse(fs.readFileSync(`smartbox/i18n/${lang}.json`, 'utf8'));
  const ctx = { window: {}, document: { readyState: 'loading', addEventListener() {} },
    localStorage: { getItem: () => lang },
    fetch: async url => ({ ok: true, json: async () => url.endsWith('config')
      ? { languages: { sv: 'Svenska', en: 'English', cs: 'Čeština' } } : dict }) };
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync('smartbox/i18n/i18n.js', 'utf8'), ctx);
  await ctx.window.I18N.ready;
  return ctx.window.I18N;
}

// Rendered strings from dashboard, mobile and journal, including dynamic values.
const cases = [
  ['🟢 Låglast', '🟢 Low load', '🟢 Nízké zatížení'],
  ['⚡ Tidstariff just nu: 🟢 Låglast', '⚡ Current time-of-use tariff: 🟢 Low load', '⚡ Aktuální časový tarif: 🟢 Nízké zatížení'],
  ['Ändra', 'Change', 'Změnit'],
  ['solvärme', 'solar heating', 'solární ohřev'],
  ['pumpen går', 'pump running', 'čerpadlo běží'],
  ['Ladda en bil som inte är din på den här laddboxen', 'Charge someone else’s car on this charger', 'Nabíjet na této nabíječce cizí auto'],
  ['🔥 Värmen är på · 21 °', '🔥 Heating is on · 21 °', '🔥 Topení je zapnuté · 21 °'],
  ['förinställning my_preset_1', 'preset my_preset_1', 'předvolba my_preset_1'],
  ['(inlärt av laddningarna)', '(learned from charging sessions)', '(naučeno z nabíjení)'],
  ['(huvudsäkring 25 A, full stapel = 150 %)', '(main fuse 25 A, full bar = 150 %)', '(hlavní jistič 25 A, plný sloupec = 150 %)'],
  ['Senast mätt: 2026-11-11 12:30', 'Last measured: 2026-11-11 12:30', 'Poslední měření: 2026-11-11 12:30'],
  ['Köpt 12.50 Kč (5.0 kWh)', 'Bought 12.50 Kč (5.0 kWh)', 'Nákup 12.50 Kč (5.0 kWh)'],
  ['Sålt 4.20 A$', 'Sold 4.20 A$', 'Prodej 4.20 A$'],
  ['Mål 21° · ute –° · pump 500 W', 'Target 21° · outside –° · pump 500 W', 'Cíl 21° · venku –° · čerpadlo 500 W'],
  ['Sparat idag 12.5 Kč · förbrukat 3 kWh', 'Saved today 12.5 Kč · consumed 3 kWh', 'Dnes ušetřeno 12.5 Kč · spotřeba 3 kWh'],
  ['Ute – · Inne 21°C (mål 22°C)', 'Outside – · Inside 21°C (target 22°C)', 'Venku – · Uvnitř 21°C (cíl 22°C)'],
  ['Auto 1 laddar på 1-fas.', 'Auto 1 charges on one phase.', 'Auto 1 se nabíjí na jedné fázi.'],
  ['SolarEdge begränsad till 50 % (minuspris)', 'SolarEdge limited to 50 % (negative price)', 'SolarEdge omezen na 50 % (záporná cena)'],
  ['Laddström: 6 A · Dynamisk gräns: 16 A · Målgräns just nu: –', 'Charging current: 6 A · Dynamic limit: 16 A · Current target limit: –', 'Nabíjecí proud: 6 A · Dynamický limit: 16 A · Aktuální cílový limit: –'],
  ['Inget att visa än idag. Journalen fylls varje minut när EnergyWizard styr (inte i skuggläge).', 'Nothing to show yet today. The journal fills every minute while EnergyWizard controls (not in shadow mode).', 'Za dnešek zatím není co zobrazit. Deník se plní každou minutu, když EnergyWizard řídí zařízení (nikoli ve stínovém režimu).'],
];

(async () => {
  const catalogs = ['en', 'cs'].map(lang => JSON.parse(fs.readFileSync(`smartbox/i18n/${lang}.json`, 'utf8')));
  for (const key of Object.keys(catalogs[0])) assert.ok(key in catalogs[1], `Missing Czech key: ${key}`);
  for (const dict of catalogs) for (const [key, value] of Object.entries(dict)) {
    if (key.startsWith('_') || typeof value !== 'string' || !value) continue;
    assert.equal((key.match(/#/g) || []).length, (value.match(/#/g) || []).length, key);
    const names = s => [...new Set(s.match(/\{[a-zA-Z][a-zA-Z0-9_]*\}/g) || [])].sort();
    assert.deepEqual(names(key), names(value), key);
  }
  for (const [lang, index] of [['sv', 0], ['en', 1], ['cs', 2]]) {
    const i18n = await runtime(lang);
    for (const row of cases) assert.equal(i18n.tr(row[0]), row[index], `${lang}: ${row[0]}`);
  }
  console.log(`UI translations: ${cases.length * 3} checks and catalog parity passed`);
})().catch(error => { console.error(error); process.exitCode = 1; });
