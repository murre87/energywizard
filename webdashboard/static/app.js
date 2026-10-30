// EnergyWizard Webdashboard - Fas B: Översikt-sidan med riktig data (portad från
// smartdashboard/app.py:s page_overview()). Resten av sidorna byggs i senare steg.
let PAGES = [];
let currentPage = null;

function fmtKrOre(v) {
  if (v == null) return "–";
  return Math.abs(v) < 1 && v !== 0 ? `${Math.round(v * 100)} öre` : `${v.toFixed(2)} kr`;
}
function fmt(v, dec, unit) { return v == null ? "–" : `${v.toFixed(dec)}${unit}`; }

function metricCard(icon, label, value, sub) {
  return `<div class="card"><div class="note">${icon} ${label}</div><h2 style="margin-top:6px">${value}</h2>${sub ? `<div class="note">${sub}</div>` : ""}</div>`;
}

async function renderOversikt() {
  const main = document.getElementById("main");
  main.innerHTML = `<div class="placeholder">Laddar…</div>`;
  const d = await api("api/overview");
  if (!d.ok) { main.innerHTML = `<div class="placeholder">${d.error || "Kunde inte läsa data"}</div>`; return; }
  const emoji = d.mode === "CHEAP" ? "🟢" : d.mode === "EXPENSIVE" ? "🔴" : "⏸️";
  const netLabel = d.net_power_w != null && d.net_power_w < 0 ? "☀️ Netto (Säljer!)" : "🔌 Netto (Köper)";
  const tariff = d.is_high_load ? "🔴 Höglast" : "🟢 Baslast";
  main.innerHTML = `
    <div class="card" style="margin-bottom:16px">
      <div style="font-size:1.15rem;font-weight:700">${emoji} ${d.decision}</div>
      <div class="note" style="margin-top:4px">💸 ${fmtKrOre(d.price)}/kWh · 🌡️ Inne ${fmt(d.indoor_temp, 1, "°C")} (mål ${d.indoor_target.toFixed(0)}) · 🌳 Ute ${fmt(d.outdoor_temp, 1, "°C")}</div>
    </div>
    <div class="card" style="margin-bottom:16px"><span class="note">⚡ Aktuell effekttariff: ${tariff}</span></div>
    <div class="grid" style="margin-bottom:16px">
      ${metricCard("⚡", "Elpris just nu", fmtKrOre(d.price) + "/kWh")}
      ${metricCard("🌡️", "Inne", fmt(d.indoor_temp, 1, "°C"), `Mål ${d.indoor_target.toFixed(0)}°C${d.indoor_humidity != null ? " · 💧 " + d.indoor_humidity.toFixed(0) + "%" : ""}`)}
      ${metricCard("🌲", "Ute (Pump)", fmt(d.outdoor_temp, 1, "°C"))}
      ${metricCard(d.net_power_w < 0 ? "☀️" : "🔌", d.net_power_w < 0 ? "Netto (Säljer!)" : "Netto (Köper)", d.net_power_w != null ? (d.net_power_w / 1000).toFixed(2) + " kW" : "–")}
      ${metricCard("☀️", "PV-effekt", d.pv_power_w != null ? (d.pv_power_w / 1000).toFixed(2) + " kW" : "–")}
      ${metricCard("🛁", "Varmvatten", fmt(d.water_temp, 1, "°C"))}
      ${metricCard("🚗", "EV Laddning", d.ev_power_kw != null ? d.ev_power_kw.toFixed(1) + " kW" : "–")}
    </div>
    <div class="card"><h2>Elpris</h2><div class="note">Senaste dygnet + kommande priser</div><div id="pricechart" style="height:240px;margin-top:10px"></div></div>
    <div class="note" style="margin-top:10px">Senast mätt: ${d.sthlm_time}</div>`;
  if (d.price_24h && d.price_24h.length) {
    const chart = echarts.init(document.getElementById("pricechart"), null, { renderer: "svg" });
    chart.setOption({
      grid: { left: 46, right: 16, top: 16, bottom: 36 },
      xAxis: { type: "category", data: d.price_24h.map(p => p.t.slice(11, 16)), axisLabel: { interval: 3 }, axisLine: { lineStyle: { color: "#93a0b8" } } },
      yAxis: { type: "value", axisLine: { lineStyle: { color: "#93a0b8" } }, splitLine: { lineStyle: { color: "rgba(255,255,255,.08)" } } },
      series: [{ type: "line", data: d.price_24h.map(p => p.p), step: "end", lineStyle: { color: "#38bdf8", width: 2 }, areaStyle: { color: "rgba(56,189,248,.15)" }, symbol: "none" }],
    });
    new ResizeObserver(() => chart.resize()).observe(document.getElementById("pricechart"));
  }
}

async function api(path, opts) {
  const r = await fetch(path, { credentials: "same-origin", headers: { "Content-Type": "application/json" }, ...opts });
  if (r.status === 401) { showLogin(); throw new Error("not authed"); }
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}

function showLogin() {
  document.getElementById("login").classList.remove("off");
  document.getElementById("shell").classList.remove("on");
}

function showShell() {
  document.getElementById("login").classList.add("off");
  document.getElementById("shell").classList.add("on");
}

function renderSidebar() {
  const nav = document.getElementById("sidebar");
  nav.innerHTML = PAGES.map(p =>
    `<button class="navitem${p.id === currentPage ? " on" : ""}" data-page="${p.id}">${p.icon} ${p.name}</button>`
  ).join("");
  nav.querySelectorAll(".navitem").forEach(b => b.onclick = () => openPage(b.dataset.page));
}

async function renderSystem() {
  const main = document.getElementById("main");
  main.innerHTML = `<div class="placeholder">Laddar…</div>`;
  await loadUpdates(false);
}

async function loadUpdates(force) {
  const main = document.getElementById("main");
  const d = await api(`api/updates${force ? "?force=1" : ""}`);
  if (!d.ok) { main.innerHTML = `<div class="placeholder">${d.error}</div>`; return; }
  const when = d.checked_at ? new Date(d.checked_at * 1000).toLocaleString("sv-SE") : "–";
  const rows = d.pending.length
    ? d.pending.map(n => `<div class="card" style="margin-bottom:8px">🆕 <b>${n}</b> <span class="note">har en nyare version - Watchtower uppdaterar den vid nästa schemalagda körning (08:00)</span></div>`).join("")
    : `<div class="card">✅ Allt uppdaterat - inga nya versioner hittade bland ${d.total} containrar.</div>`;
  main.innerHTML = `
    <div class="card" style="margin-bottom:16px">
      <div style="font-size:1.1rem;font-weight:700">🛠️ Systemuppdateringar</div>
      <div class="note" style="margin-top:4px">Watchtower håller koll på alla ${d.total} containrar på servern och uppdaterar dem automatiskt. Senast kollad: ${when}.</div>
      <button class="icobtn" id="checknowbtn" style="margin-top:10px">Kolla nu</button>
    </div>
    ${rows}`;
  document.getElementById("checknowbtn").onclick = () => loadUpdates(true);
}

function openPage(id) {
  currentPage = id;
  renderSidebar();
  if (id === "oversikt") {
    renderOversikt();
  } else if (id === "system") {
    renderSystem();
  } else {
    document.getElementById("main").innerHTML = `<div class="placeholder">"${PAGES.find(p => p.id === id)?.name}" byggs i en senare fas.</div>`;
  }
}

async function boot() {
  try {
    const me = await api("api/me");
    if (!me.role) { showLogin(); return; }
    PAGES = me.pages;
    showShell();
    openPage("oversikt");
  } catch (e) { showLogin(); }
}

document.getElementById("loginform").onsubmit = async (e) => {
  e.preventDefault();
  const err = document.getElementById("loginerr");
  err.textContent = "";
  try {
    await api("api/login", { method: "POST", body: JSON.stringify({ user: document.getElementById("user").value, password: document.getElementById("pw").value }) });
    boot();
  } catch (e) { err.textContent = e.message || "Fel användarnamn eller lösenord"; }
};

document.getElementById("logoutbtn").onclick = async () => { await api("api/logout", { method: "POST" }); showLogin(); };

boot();
