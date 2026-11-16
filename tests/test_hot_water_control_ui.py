"""Control card translation, expiry, escaping and read-only polling behavior."""
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which('node') is None, reason='Node.js required')
def test_control_status_card_in_english_and_czech():
    script = r'''
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const source = fs.readFileSync('webdashboard/static/app.js', 'utf8');
const start = source.indexOf('function hotWaterControlHtml(');
assert(start >= 0);
const card = {hidden: true}, body = {isConnected: true, innerHTML: ''};
const context = {Date, Number, Object, window: {},
  document: {getElementById: id => id === 'hotwatercontrolcard' ? card : body},
  setTimeout: () => 1, clearTimeout: () => {},
  esc: value => String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;')};
Date.now = () => 1794823200000;
vm.createContext(context);
vm.runInContext(source.slice(start, source.indexOf('async function mountMqtt()', start)), context);
const status = {fresh:true, state:'active', reported_at:Date.now()/1000, start:Date.now()/1000-30,
  end:Date.now()/1000+600, deadline:Date.now()/1000+900, endpoint:'<script>secret</script>'};
for (const lang of ['en','cs']) {
  const dict = JSON.parse(fs.readFileSync('smartbox/i18n/'+lang+'.json', 'utf8'));
  context.I18N = {lang, tr: text => { assert(Object.hasOwn(dict,text), text); return dict[text]; }};
  context.window.I18N = context.I18N;
  const html = context.hotWaterControlHtml(status);
  assert(html.includes(dict['Varmvattenboost är aktiv']));
  assert(!html.includes('secret') && !html.includes('<script>'));
  for (const state of ['planned','start_pending','release_pending','recovery_required','storage_error',
    'interrupted','complete','control_blocked','guard_blocked','schedule_unavailable']) {
    assert(!context.hotWaterControlHtml({...status,state}).includes('undefined'));
  }
  assert(context.hotWaterControlHtml({...status,reported_at:status.reported_at-91}).includes(dict['Okänd eller inaktuell status']));
  assert(context.hotWaterControlHtml({...status,reported_at:status.reported_at+1}).includes(dict['Okänd eller inaktuell status']));
  assert(!context.hotWaterControlHtml({...status,state:'<img src=x onerror=alert(1)>'}).includes('<img'));
}
(async () => {
  context.api = async path => {assert.equal(path,'api/hot-water-control-status'); return {enabled:false};};
  await context.mountHotWaterControl(); assert(card.hidden);
  context.api = async () => ({enabled:true,status});
  await context.mountHotWaterControl(); assert(!card.hidden);
  assert(body.innerHTML.includes('aktivní'));
  context.api = async () => {throw Error('private error');};
  await context.mountHotWaterControl(); assert(!body.innerHTML.includes('private'));
  body.isConnected = false; body.innerHTML = 'left-page';
  await context.mountHotWaterControl(); assert.equal(body.innerHTML,'left-page');
})().catch(error => { console.error(error); process.exitCode=1; });
'''
    result = subprocess.run(['node', '-e', script], cwd=Path(__file__).resolve().parents[1],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
