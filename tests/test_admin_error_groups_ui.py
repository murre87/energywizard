"""Admin error groups expose build evidence without leaking raw telemetry HTML."""
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which('node') is None, reason='Node.js required')
def test_error_group_versions_are_visible_and_escaped():
    script = r'''
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const source = fs.readFileSync('webdashboard/static/app.js', 'utf8');
const start = source.indexOf('const gRow = (g) =>');
assert(start >= 0);
const context = {TRANS: /ConnectionError$/, ago: () => '3 min',
  esc: s => String(s).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')};
vm.createContext(context);
vm.runInContext(source.slice(start, source.indexOf('const errCard', start)) + ';globalThis.render = gRow;', context);
const group = {key: 'main_loop: TypeError', houses: 13, reports: 165, last: 1,
  versions: ['old-build', '<img src=x onerror=alert(1)>']};
const html = context.render(group);
assert(html.includes('old-build'));
assert(html.includes('&lt;img'));
assert(!html.includes('<img'));
assert(html.includes('13 hus'));
delete group.versions;
assert(!context.render(group).includes('Version:'));
assert(context.render({...group, key: 'ha: ConnectionError'}).includes('color:var(--mut)'));
'''
    run = subprocess.run(['node', '-e', script], cwd=Path(__file__).resolve().parents[1],
                         text=True, capture_output=True)
    assert run.returncode == 0, run.stdout + run.stderr
