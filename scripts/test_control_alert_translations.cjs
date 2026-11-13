const fs = require('fs'), vm = require('vm'), assert = require('assert/strict');
const alerts = JSON.parse(fs.readFileSync(0, 'utf8'));
const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
(async () => {
  for (const lang of ['sv', 'en', 'cs']) {
    const dict = lang === 'sv' ? {} : JSON.parse(fs.readFileSync(`smartbox/i18n/${lang}.json`, 'utf8'));
    const ctx = vm.createContext({ window: {}, document: {readyState:'loading', addEventListener(){}},
      localStorage:{getItem:()=>lang}, fetch:async url=>({ok:true,json:async()=>url.endsWith('config')?{languages:{sv:'Svenska',en:'English',cs:'Čeština'}}:dict}), esc,
      EN:{alerts,solar:{},grid:{}}, FL:null,flowCard:()=>'',planNow:()=>'',quickGrid:()=>'',carsRow:()=>'',ljusRow:()=>'', CL:()=>false, r:{alerts} });   // CL: appens stilval (ny = false)
    vm.runInContext(fs.readFileSync('smartbox/i18n/i18n.js','utf8'),ctx);
    await ctx.window.I18N.ready;
    const tr=ctx.window.I18N.tr;
    const app=fs.readFileSync('ewapp/static/app.js','utf8');
    vm.runInContext(app.slice(app.indexOf('function pageHem()'),app.indexOf('async function spaBathSheet()')),ctx);
    const mobile=ctx.pageHem();
    const web=fs.readFileSync('webdashboard/static/app.js','utf8');
    const start=web.indexOf('r.alerts.map((a) =>');
    const desktop=vm.runInContext(web.slice(start,web.indexOf('.join("")',start)+'.join("")'.length),ctx);
    for(const html of [mobile,desktop]) {
      assert(html.includes('<span>Tesla &lt;42&gt;</span>: <span>Laddar långsammare än planen</span>'));
      assert(!html.includes('<span>Tesla <42>'));
    }
    for(const alert of alerts)for(const key of ['title','text','hint']){
      const translated=tr(alert[key]);
      assert(lang==='sv'?translated===alert[key]:translated!==alert[key],`${lang}: ${alert[key]}`);
      assert.deepEqual(translated.match(/\d+/g),alert[key].match(/\d+/g));
      if(key==='text'&&alert.text.includes('max circuit current too low'))assert(translated.includes('max circuit current too low'));
    }
  }
  console.log('Control alert rendering and translations passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
