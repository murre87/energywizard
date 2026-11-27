"""Ekonomisidans vy Månader ritas av samma funktion som webben (#599)."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js required for frontend rendering checks")
def test_manadsvyn_valjer_senaste_manaden_och_lamnar_idag():
    script = r"""
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const element = { style: { setProperty() {} }, classList: { add() {}, remove() {} },
  setAttribute() {}, removeAttribute() {}, addEventListener() {}, innerHTML: "" };
const charts = [];
const ctx = vm.createContext({
  document: { documentElement: element, getElementById: () => element,
    querySelector: () => element, querySelectorAll: () => [], addEventListener() {} },
  window: { addEventListener() {}, matchMedia: () => ({ matches: true }) },
  localStorage: { getItem() { return null; } },
  navigator: {}, location: { search: "" }, URLSearchParams, history: { replaceState() {} },
  matchMedia: () => ({ matches: false }), innerWidth: 1200, innerHeight: 800,
  setInterval() {}, setTimeout() {}, clearTimeout() {}, console,
  getComputedStyle: () => ({ getPropertyValue: () => "" }),
  ResizeObserver: class { observe() {} },
  echarts: { init() { return { setOption(o) { charts.push(o); }, resize() {} }; } },
});
vm.runInContext(fs.readFileSync("webdashboard/static/app.js", "utf8").replace(/\nboot\(\);\s*$/, ""), ctx);
ctx.economy = {
  ok: true, price: 1.2, price_min: 0.4, price_avg: 0.8, price_max: 1.5,
  price_buy_min: 0.9, price_buy_avg: 1.3, price_buy_max: 2.0, price_24h: null,
  symbol: "kr", electricity_support_area: null,
  money_days: [{day: "2026-11-03", cost: 25, bought_kwh: 10, sold_kwh: 2, income: 3, net: 22}],
  money: {
    today: {cost: 25, bought_kwh: 10, sold_kwh: 2, income: 3, net: 22, avg_paid: 2.5, avg_sold: 1.5, days: 1},
    week: {cost: 75, bought_kwh: 30, sold_kwh: 7, income: 7, net: 68, avg_paid: 2.5, avg_sold: 1, days: 2},
    month: {cost: 75, bought_kwh: 30, sold_kwh: 7, income: 7, net: 68, avg_paid: 2.5, avg_sold: 1, days: 2},
  },
  timing: {
    today: {saved_kr: 2, pct: 20, days: 1},
    week: {saved_kr: 4, pct: 20, days: 2},
    month: {saved_kr: 4, pct: 20, days: 2},
  },
  months: [
    {month: "2026-10", money: {cost: 30, bought_kwh: 10, sold_kwh: 0, income: 0, net: 30, avg_paid: 3, avg_sold: null, days: 1}, timing: {saved_kr: 2, pct: 20, days: 1}},
    {month: "2026-11", money: {cost: 75, bought_kwh: 30, sold_kwh: 7, income: 7, net: 68, avg_paid: 2.5, avg_sold: 1, days: 2}, timing: {saved_kr: 4, pct: 20, days: 2}},
  ],
};
vm.runInContext("api = async (path) => { if (path === 'api/economy') return economy; if (path === 'api/savings') return {ok:true, days:[{day:'2026-11-03', saved_kr:2}]}; throw new Error(path); };", ctx);

(async () => {
  await vm.runInContext("renderEkonomi()", ctx);
  const today = element.innerHTML;
  assert.match(today, /data-econ="today"/);
  assert.match(today, /data-econ="months"/);
  assert.doesNotMatch(today, /data-econ="all"/);
  assert.match(today, /Kostnad per dag/);
  assert.match(today, /Senaste 31 dagarna/);
  assert.doesNotMatch(today, /Kostnad per månad/);
  assert.equal(charts.at(-1).xAxis.data[0], "11-03");

  charts.length = 0;
  vm.runInContext('econPeriod = "months"', ctx);
  await vm.runInContext("renderEkonomi()", ctx);
  const months = element.innerHTML;
  assert.match(months, /Kostnad per månad/);
  assert.match(months, /Sparat per månad/);
  assert.match(months, /En stapel per månad med data/);
  assert.match(months, /data-econ-month="2026-11"/);
  assert.match(months, /data-econ-month="2026-10"/);
  assert.doesNotMatch(months, /2026-09/);
  assert.match(months, /75,00 kr/);
  assert.match(months, /2 dagar med data/);
  assert.match(months, /vald månad/);
  assert.deepEqual(charts[0].xAxis.data, ["2026-10", "2026-11"]);
  assert.deepEqual(charts[1].xAxis.data, ["2026-10", "2026-11"]);
  assert.deepEqual(charts[0].series[0].data.map((p) => p.value), [30, 68]);
  assert.deepEqual(charts[1].series[0].data.map((p) => p.value), [2, 4]);

  vm.runInContext('econMonth = "2026-10"', ctx);
  await vm.runInContext("renderEkonomi()", ctx);
  assert.match(element.innerHTML, /30,00 kr/);
  assert.match(element.innerHTML, /1 dagar med data/);
  assert.doesNotMatch(element.innerHTML, /75,00 kr/);

  vm.runInContext('econPeriod = "today"', ctx);
  await vm.runInContext("renderEkonomi()", ctx);
  assert.match(element.innerHTML, /Kostnad per dag/);
  assert.doesNotMatch(element.innerHTML, /data-econ-month=/);
})().catch((e) => { console.error(e); process.exitCode = 1; });
"""
    result = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
