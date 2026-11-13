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
  ['EnergyWizard visar vad den hade gjort men styr ingenting.', 'EnergyWizard shows what it would have done but controls nothing.', 'EnergyWizard ukazuje, co by udělal, ale nic neovládá.'],
  ['🌳 Ute 8.7°C', '🌳 Outside 8.7°C', '🌳 Venku 8.7°C'],
  ['🩺 Felsökningsutdrag vid fel', '🩺 Diagnostic excerpts on errors', '🩺 Diagnostické výpisy při chybách'],
  ['Felsökningsutdrag är på', 'Diagnostic excerpts are on', 'Diagnostické výpisy jsou zapnuté'],
  ['Felsökningsutdrag är av', 'Diagnostic excerpts are off', 'Diagnostické výpisy jsou vypnuté'],
];

const esc = s => String(s ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const decode = s => s.replace(/&(amp|lt|gt|quot|#39);/g,(_,x)=>({amp:'&',lt:'<',gt:'>',quot:'"','#39':"'"}[x]));
// Translate each actual rendered text node, rather than a concatenated card.
const text = (html,tr) => html.replace(/<[^>]*>/g,'\0').split('\0').map(decode).map(tr).join('').replace(/\s+/g,' ').trim();
const web = fs.readFileSync('webdashboard/static/app.js','utf8');
const mobile = fs.readFileSync('ewapp/static/app.js','utf8');
function checkScreenshotCards(lang,tr) {
  const parts=['Just nu: ','Jämn komfort hela dygnet','. Härnäst ','imorgon 00:00–imorgon 24:00',': ','Jämn komfort hela dygnet','.'];
  const plan={headline:parts.join(''),headline_parts:parts,items:[],note:''};
  const ctx=vm.createContext({window:{EWPlanView:true},esc,PL:plan,EN:{now:[]},PC:null,
    sunDaysHtml:()=>'',savingsPeriod:'week',SAVINGS_PERIODS:[],symbol:'€'});
  ctx.moneyUnit=()=>ctx.symbol;
  vm.runInContext(web.slice(web.indexOf('function decisionHeadlineHtml('),web.indexOf('async function mountPlan(')),ctx);
  vm.runInContext(web.slice(web.indexOf('function savingsCardHtml('),web.indexOf('// Kostnad per dag')),ctx);
  vm.runInContext(mobile.slice(mobile.indexOf('function planNow('),mobile.indexOf('async function roomsSheet(')),ctx);
  vm.runInContext(mobile.slice(mobile.indexOf('function planList()'),mobile.indexOf('function pagePlan()')),ctx);
  const expected={sv:plan.headline,en:'Right now: Even comfort all day. Next tomorrow 00:00–tomorrow 24:00: Even comfort all day.',
    cs:'Právě teď: Stálý komfort po celý den. Dále zítra 00:00–zítra 24:00: Stálý komfort po celý den.'}[lang];
  for(const html of [ctx.planCardHtml(plan),ctx.planNow(),ctx.planList()])assert(text(html,tr).includes(expected),`${lang}: ${text(html,tr)}`);
  const decision='Värmepump: Anti-Short-Cycle – Låst i läge EXPENSIVE till 14:43.';
  const status=text(ctx.decisionHeadlineHtml(decision),tr);
  assert.equal(status,{sv:decision,en:'Heat pump: Anti-short-cycle – locked in mode EXPENSIVE until 14:43.',cs:'Tepelné čerpadlo: Ochrana proti častému spínání – režim EXPENSIVE uzamčen do 14:43.'}[lang]);
  assert(!ctx.decisionHeadlineHtml('Värmepump: <img src=x>').includes('<img'));
  assert.equal(ctx.decisionHeadlineHtml('Utvärderar…'),'Utvärderar…');
  // Older servers still render their legacy headline safely.
  assert(ctx.planCardHtml({headline:'<old>',items:[]}).includes('&lt;old&gt;'));
  for(const currency of ['€','Kč','kr']){
    ctx.symbol=currency;
    const rendered=text(ctx.savingsCardHtml({periods:{week:{saved_kr:11,paid_kr:39,kwh:94,days:5}}}),tr);
    const line={sv:`94 kWh köpt för 39 ${currency}, mot 50 ${currency} i ett vanligt hushåll utan styrning (inkl. moms)`,en:`94 kWh bought for 39 ${currency}, compared with 50 ${currency} in an ordinary household without control (incl. VAT)`,cs:`94 kWh nakoupeno za 39 ${currency} oproti 50 ${currency} v běžné domácnosti bez řízení (včetně DPH)`}[lang];
    assert(rendered.includes(line),`${lang}: ${rendered}`);
  }
  const shadow=web.match(/🕶️ <b>Skuggläge:<\/b>[\s\S]*?<\/div>/)[0];
  const support=web.slice(web.indexOf('id="supportcard"'),web.indexOf('id="sensorcard"'));
  const description=support.match(/<div class="note"[^>]*>([\s\S]*?)<\/div>/)[1];
  for(const html of [shadow,description]){
    const rendered=text(html,tr);
    if(lang!=='sv')assert(!/visar vad|utdrag|skickas|felklass|På som standard/.test(rendered),`${lang}: ${rendered}`);
  }
}

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
    checkScreenshotCards(lang,i18n.tr);
  }
  console.log(`UI translations: ${cases.length * 3} checks and catalog parity passed`);
})().catch(error => { console.error(error); process.exitCode = 1; });
