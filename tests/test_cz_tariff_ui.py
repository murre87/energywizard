"""Contract errors and Czech price labels use the existing browser translator."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which('node') is None, reason='Node.js required')
def test_contract_errors_and_currency_labels_translate():
    js = r'''
const fs=require('node:fs'), vm=require('node:vm'), assert=require('node:assert/strict');
async function check(lang) {
 const dict=JSON.parse(fs.readFileSync('smartbox/i18n/'+lang+'.json','utf8'));
 const el={style:{setProperty(){}},classList:{add(){},remove(){}},setAttribute(){},addEventListener(){}};
 const ctx=vm.createContext({console,document:{readyState:'loading',currentScript:null,documentElement:el,addEventListener(){},getElementById:()=>el,querySelector:()=>el},
 localStorage:{getItem:()=>lang},navigator:{},location:{search:''},URLSearchParams,history:{replaceState(){}},
 innerWidth:400,innerHeight:800,matchMedia:()=>({matches:true}),setTimeout(){},clearTimeout(){},setInterval(){},
 fetch:async url=>url.endsWith('config')?{ok:true,json:async()=>({default:lang,languages:{sv:'Svenska',en:'English',cs:'Čeština'}})}:
 url.endsWith('.json')?{ok:true,json:async()=>dict}:{ok:false,status:400,statusText:'Bad Request',json:async()=>({error:'Ange båda slutpriserna för NT och VT'})}});
 ctx.window=ctx; vm.runInContext(fs.readFileSync('smartbox/i18n/i18n.js','utf8'),ctx); await ctx.I18N.ready;
 vm.runInContext(fs.readFileSync('webdashboard/static/app.js','utf8').replace(/\nboot\(\);\s*$/,''),ctx);
 let error; try { await vm.runInContext('postJSON("api/price-settings", {})',ctx); } catch(e) { error=e.message; }
 assert.equal(ctx.I18N.tr(error),lang==='cs'?'Zadejte obě konečné ceny NT a VT':'Enter both final NT and VT prices');
 assert.equal(ctx.I18N.tr('Slutpris NT'),lang==='cs'?'Konečná cena NT':'Final low-tariff price');
 assert.equal(ctx.I18N.tr('inkl. moms'),lang==='cs'?'včetně DPH':'incl. VAT');
}
Promise.all(['cs','en'].map(check)).catch(e=>{console.error(e);process.exitCode=1});
'''
    run=subprocess.run(['node','-e',js],cwd=ROOT,text=True,capture_output=True)
    assert run.returncode == 0, run.stderr
