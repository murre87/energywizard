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

function heatBatteryHtml(hb, compact) {
  if (!hb) return "";
  const icon = hb.status === "Laddar" ? "🔥" : hb.status === "Vilar" ? "💤" : "🧊";
  const cls = hb.status === "Tömmer" ? " tomrer" : "";
  return `
    <div class="heatbatt${compact ? " compact" : ""}${cls}">
      <div class="tank"><div class="fill" style="height:${hb.charge_pct}%"></div></div>
      <div class="info">
        <div><b>${hb.charge_pct.toFixed(0)}%</b> <span class="note">${icon} ${hb.status}</span></div>
        <div class="note">${hb.water_temp.toFixed(0)}°C (${hb.floor.toFixed(0)}–${hb.ceiling.toFixed(0)}°C)</div>
      </div>
    </div>`;
}

async function renderOversikt() {
  const main = document.getElementById("main");
  main.innerHTML = `<div class="placeholder">Laddar…</div>`;
  const d = await api("api/overview");
  if (!d.ok) {
    // "Ingen data i sensor_log än" = smartbox har inget house_config ännu, oftast en
    // helt ny installation - en bar felrad ger ingen ledtråd om vad man ska göra.
    main.innerHTML = `<div class="card" style="margin-bottom:16px">
      <div style="font-size:1.1rem;font-weight:700">👋 Välkommen till EnergyWizard!</div>
      <div class="note" style="margin-top:6px">${d.error || "Ingen data än"} - troligen en ny installation. Gå till
        <b>Inställningar</b> och kör entitetsväljaren för att hitta din värmepump, bilar, solceller m.m. i Home
        Assistant, spara den genererade filen som din <code>house_config.yaml</code> och starta om smartbox.</div>
      <button class="icobtn" id="gotosettings" style="margin-top:10px">Gå till Inställningar</button>
    </div>`;
    document.getElementById("gotosettings").onclick = () => openPage("installningar");
    return;
  }
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
      <div class="card"><div class="note">🔋 Värmebatteri</div><div style="margin-top:8px">${heatBatteryHtml(d.heat_battery, true)}</div></div>
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

function badge(cls, text) { return `<span class="badge ${cls}">${text}</span>`; }

function statTile(label, value, sub) {
  return `<div class="stat"><div class="v">${value}</div><div class="l">${label}</div>${sub ? `<div class="l">${sub}</div>` : ""}</div>`;
}

function barRow(name, pct, valueLabel) {
  const p = pct == null ? 0 : Math.max(0, Math.min(100, pct));
  return `<div class="barrow"><div class="name">${name}</div><div class="track"><div class="fill" style="width:${p}%"></div></div><div class="val">${valueLabel}</div></div>`;
}

function lineChart(elId, series, opts) {
  const el = document.getElementById(elId);
  if (!el || !series.length) return;
  const chart = echarts.init(el, null, { renderer: "svg" });
  chart.setOption({
    grid: { left: 46, right: 16, top: 16, bottom: 36 },
    xAxis: { type: "category", data: series.map(p => p.t.slice(11, 16)), axisLabel: { interval: Math.ceil(series.length / 8) }, axisLine: { lineStyle: { color: "#93a0b8" } } },
    yAxis: { type: "value", axisLine: { lineStyle: { color: "#93a0b8" } }, splitLine: { lineStyle: { color: "rgba(255,255,255,.08)" } }, ...(opts && opts.yAxis) || {} },
    series: [{ type: "line", data: series.map(p => p[opts && opts.yKey || "p"]), step: opts && opts.step, lineStyle: { color: (opts && opts.color) || "#38bdf8", width: 2 }, areaStyle: { color: (opts && opts.areaColor) || "rgba(56,189,248,.15)" }, symbol: "none" }],
  });
  new ResizeObserver(() => chart.resize()).observe(el);
}

async function loadPage(path, build) {
  const main = document.getElementById("main");
  main.innerHTML = `<div class="placeholder">Laddar…</div>`;
  let d;
  try { d = await api(path); } catch (e) { main.innerHTML = `<div class="placeholder">${e.message}</div>`; return; }
  if (!d.ok) { main.innerHTML = `<div class="placeholder">${d.error || "Kunde inte läsa data"}</div>`; return; }
  main.innerHTML = build(d);
  return d;
}

async function renderElbil() {
  const d = await loadPage("api/car", (d) => `
    <div class="grid" style="margin-bottom:16px">
      ${d.cars.map(c => `<div class="card">
        <div style="font-size:1.05rem;font-weight:700">🚗 ${c.name}</div>
        <div class="v" style="margin:10px 0 2px;font-size:1.6rem">${fmt(c.soc, 0, "%")}</div>
        <div class="note">${c.stale ? badge("warn", "⚠️ gammalt värde") : badge("on", "live")} ${c.status ? "· " + c.status : ""}</div>
        <div class="note" style="margin-top:6px">⚡ ${fmt(c.power_kw, 1, " kW")} just nu${c.planned_kwh_today != null ? ` · 📅 ${c.planned_kwh_today.toFixed(1)} kWh planerat idag` : ""}</div>
        ${c.climate_state ? `<div class="note">🌡️ Klimat: ${c.climate_state}${c.climate_temp != null ? " (" + c.climate_temp.toFixed(0) + "°C)" : ""}</div>` : ""}
      </div>`).join("")}
    </div>
    <div class="card" style="margin-bottom:16px">
      <h2>📅 Dagens schema</h2>
      ${d.schedule_today.length ? d.schedule_today.map(s => `<div class="note" style="margin:4px 0">${s.car_id === "tesla" ? "🚗 Tesla" : "🚗 Nissan"}: klar ${s.target_time || "–"} till ${s.target_soc}% ${s.enabled ? badge("on", "på") : badge("off", "av")}</div>`).join("") : `<div class="note">Inget schema satt för idag.</div>`}
    </div>
    <div class="note">Laddström: ${fmt(d.current_a, 0, " A")} · Dynamisk gräns: ${fmt(d.dynamic_limit_a, 0, " A")} · Målgräns just nu: ${fmt(d.current_target_limit, 0, " A")}</div>`);
}

async function renderSolceller() {
  const d = await loadPage("api/solar", (d) => `
    <div class="grid" style="margin-bottom:16px">
      ${statTile("☀️ PV-effekt", fmt(d.pv_power_w != null ? d.pv_power_w / 1000 : null, 2, " kW"))}
      ${statTile("🔆 Idag", fmt(d.solar_today_kwh, 1, " kWh"))}
      ${statTile("📈 Prognos nu", fmt(d.solar_forecast_w != null ? d.solar_forecast_w / 1000 : null, 2, " kW"))}
      ${statTile("🚫 Exportgräns", d.solar_limit_pct != null ? d.solar_limit_pct.toFixed(0) + " %" : "Ingen", d.solar_limit_pct != null && d.solar_limit_pct < 100 ? "AI begränsar (minuspris)" : "")}
    </div>
    ${d.battery_soc != null ? `<div class="card" style="margin-bottom:16px">
      <h2>🔋 Husbatteri</h2>
      ${barRow("Laddning", d.battery_soc, d.battery_soc.toFixed(0) + "%")}
      <div class="note" style="margin-top:6px">${fmt(d.battery_power_w, 0, " W")} ${d.battery_power_w > 0 ? "(laddar)" : d.battery_power_w < 0 ? "(laddar ur)" : ""}</div>
    </div>` : ""}
    <div class="card"><h2>Elpris</h2><div class="note">Styr när exportbegränsningen slår till (minuspris)</div><div id="solarpricechart" style="height:220px;margin-top:10px"></div></div>`);
  if (d && d.price_24h) lineChart("solarpricechart", d.price_24h, { step: "end" });
}

async function renderEkonomi() {
  const d = await loadPage("api/economy", (d) => `
    <div class="grid" style="margin-bottom:16px">
      ${statTile("💸 Elpris just nu", fmtKrOre(d.price) + "/kWh")}
      ${statTile("📉 Lägst idag", fmtKrOre(d.price_min) + "/kWh")}
      ${statTile("📊 Snitt idag", fmtKrOre(d.price_avg) + "/kWh")}
      ${statTile("📈 Högst idag", fmtKrOre(d.price_max) + "/kWh")}
    </div>
    <div class="card" style="margin-bottom:16px">
      <h2>💰 Uppskattad kostnad idag</h2>
      <div class="v" style="font-size:1.8rem">${d.est_cost_today != null ? d.est_cost_today.toFixed(2) + " kr" : "–"}</div>
      <div class="note" style="margin-top:4px">${fmt(d.accumulated_consumption_kwh, 1, " kWh")} förbrukat × dagens snittpris - en grov uppskattning, inte en exakt timme-för-timme-kostnad.</div>
    </div>
    <div class="card"><h2>Elpris senaste dygnet</h2><div id="econpricechart" style="height:240px;margin-top:10px"></div></div>`);
  if (d && d.price_24h) lineChart("econpricechart", d.price_24h, { step: "end" });
}

async function renderElforbrukning() {
  await loadPage("api/consumption", (d) => {
    const b = d.breakdown;
    const maxW = b ? Math.max(b.total_w || 0, 1) : 1;
    return `
    <div class="grid" style="margin-bottom:16px">
      ${statTile("⚡ Just nu", fmt(d.avg_w_tot != null ? d.avg_w_tot / 1000 : null, 2, " kW"))}
      ${statTile("🏠 Hus (bas)", fmt(d.house_consumption_w != null ? d.house_consumption_w / 1000 : null, 2, " kW"))}
      ${statTile("📐 Prognos baslast", fmt(d.predicted_base_load_kw, 2, " kW"))}
      ${statTile("🛡️ Effektvakt", d.peak_shaving_active ? badge("warn", "griper in") : badge("on", "normal läge"))}
    </div>
    <div class="card" style="margin-bottom:16px">
      <h2>🔌 Faser</h2>
      ${barRow("L1", d.avg_w_l1 != null ? d.avg_w_l1 / maxW * 100 : 0, fmt(d.avg_w_l1, 0, " W"))}
      ${barRow("L2", d.avg_w_l2 != null ? d.avg_w_l2 / maxW * 100 : 0, fmt(d.avg_w_l2, 0, " W"))}
      ${barRow("L3", d.avg_w_l3 != null ? d.avg_w_l3 / maxW * 100 : 0, fmt(d.avg_w_l3, 0, " W"))}
    </div>
    ${b ? `<div class="card">
      <h2>📦 Vad drar strömmen</h2>
      ${barRow("🚗 Elbil", b.ev_w / maxW * 100, fmt(b.ev_w, 0, " W"))}
      ${barRow("♨️ Värmepump", b.pump_w / maxW * 100, fmt(b.pump_w, 0, " W"))}
      ${barRow("🛁 Spabad", b.spa_w / maxW * 100, fmt(b.spa_w, 0, " W"))}
      ${barRow("❓ Oförklarat", b.unexplained_w / maxW * 100, fmt(b.unexplained_w, 0, " W"))}
      ${barRow("Σ Totalt", 100, fmt(b.total_w, 0, " W"))}
    </div>` : `<div class="note">Ingen uppdelning loggad än.</div>`}`;
  });
}

async function renderSpabad() {
  await loadPage("api/spa", (d) => `
    <div class="grid" style="margin-bottom:16px">
      ${statTile("🛁 Temperatur", fmt(d.temp, 1, "°C"))}
      ${statTile("🎯 Mål", fmt(d.target, 1, "°C"))}
      ${statTile("🔥 Värmare", d.heater_running ? badge("on", "värmer") : badge("off", "av"))}
      ${statTile("⚡ Effekt", fmt(d.power_w, 0, " W"))}
    </div>
    <div class="card"><h2>📡 Trådlös anslutning</h2><div class="note">Signal: ${fmt(d.signal_pct, 0, "%")} · Kanal: ${d.rf_channel != null ? d.rf_channel : "–"}</div></div>`);
}

async function renderTemperaturer() {
  await loadPage("api/temperatures", (d) => `
    <div class="grid" style="margin-bottom:16px">
      ${statTile("🏠 Inne", fmt(d.indoor_temp, 1, "°C"), d.indoor_humidity != null ? "💧 " + d.indoor_humidity.toFixed(0) + "%" : "")}
      ${statTile("🌳 Ute", fmt(d.outdoor_temp, 1, "°C"))}
      ${statTile("🌬️ Ventilation in", fmt(d.vent_supply_temp, 1, "°C"))}
      ${statTile("🌬️ Ventilation ut", fmt(d.vent_exhaust_temp, 1, "°C"))}
    </div>
    <div class="card"><h2>🌡️ Rum</h2>
      ${d.rooms.length ? d.rooms.map(r => barRow(r.name, (r.temp + 10) * 3, r.temp.toFixed(1) + "°C")).join("") : `<div class="note">Inga rumsgivare hittade.</div>`}
    </div>`);
}

async function renderPrognos() {
  const d = await loadPage("api/forecast", (d) => `
    <div class="card" style="margin-bottom:16px"><h2>📅 Elpris kommande timmar</h2><div id="forecastpricechart" style="height:220px;margin-top:10px"></div></div>
    <div class="card"><h2>🌤️ Väderprognos</h2><div id="forecastweatherchart" style="height:220px;margin-top:10px"></div>
      <div class="note" style="margin-top:8px">Regnrisk/åskrisk anges i procent, molnighet i procent av himlen.</div></div>`);
  if (d) {
    if (d.prices.length) lineChart("forecastpricechart", d.prices, { step: "end" });
    if (d.weather.length) lineChart("forecastweatherchart", d.weather, { yKey: "temp", color: "#fbbf24", areaColor: "rgba(251,191,36,.15)" });
  }
}

async function renderHistorik() {
  await loadPage("api/historylog", (d) => `
    <div class="card">
      <h2>📈 Logg</h2>
      <div class="loglist">
        ${d.entries.length ? d.entries.map(e => `<div class="logrow"><div class="t">${new Date(e.ts).toLocaleString("sv-SE", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}</div><div>${e.user ? `<b>${esc(e.user)}:</b> ` : ""}${esc(e.text || "")}</div></div>`).join("") : `<div class="note">Inget loggat än.</div>`}
      </div>
    </div>`);
}

async function renderAviseringar() {
  const d = await loadPage("api/notifications", (d) => `
    <div class="card">
      <h2>🔔 Aviseringstyper</h2>
      <div class="note" style="margin-bottom:8px">Styr vilka händelser som skickar en avisering - samma inställning som i mobilappen.</div>
      ${d.items.map(i => `<div class="togglerow"><span>${esc(i.label)}</span><label class="switch"><input type="checkbox" class="notify-toggle" data-key="${i.key}" ${i.on ? "checked" : ""}><span class="slider"></span></label></div>`).join("")}
    </div>`);
  if (d) document.querySelectorAll(".notify-toggle").forEach(cb => {
    cb.onchange = () => api(`api/notifications/${cb.dataset.key}`, { method: "POST", body: JSON.stringify({ value: cb.checked }) }).catch(() => { cb.checked = !cb.checked; });
  });
}

function esc(s) { return String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }

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

async function renderVarmepump() {
  const main = document.getElementById("main");
  main.innerHTML = `<div class="placeholder">Laddar…</div>`;
  const d = await api("api/overview");
  if (!d.ok) { main.innerHTML = `<div class="placeholder">${d.error || "Kunde inte läsa data"}</div>`; return; }
  main.innerHTML = `
    <div class="card" style="margin-bottom:16px">
      <div style="font-size:1.1rem;font-weight:700">♨️ Värmepump</div>
      <div class="note" style="margin-top:4px">Ute ${fmt(d.outdoor_temp, 1, "°C")} · Inne ${fmt(d.indoor_temp, 1, "°C")} (mål ${d.indoor_target.toFixed(0)}°C)</div>
    </div>
    <div class="card">
      <h2>🔋 Varmvattenberedaren som värmebatteri</h2>
      <div class="note">Laddas till ${d.heat_battery ? d.heat_battery.ceiling.toFixed(0) : "–"}°C när elen är billig eller solen räcker - töms (kompressorn vilar) när elen är dyr.</div>
      <div style="margin-top:18px">${heatBatteryHtml(d.heat_battery, false)}</div>
    </div>`;
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

let _discovered = null;

async function renderInstallningar() {
  const main = document.getElementById("main");
  main.innerHTML = `
    <div class="card" style="margin-bottom:16px">
      <div style="font-size:1.1rem;font-weight:700">⚙️ Entitetsväljare</div>
      <div class="note" style="margin-top:4px">Skannar ditt Home Assistant efter värmepump, bilar, solceller, spa och laddare - du väljer vilka som stämmer, sen genererar du en färdig house_config.yaml att spara och starta om smartbox med.</div>
      <button class="icobtn" id="scanbtn" style="margin-top:10px">Skanna mitt Home Assistant</button>
    </div>
    <div class="card" style="margin-bottom:16px">
      <div style="font-size:1.1rem;font-weight:700">📡 Sök Modbus-värmepump på nätverket</div>
      <div class="note" style="margin-top:4px">Om din värmepump inte syns i Home Assistant alls (pratar direkt Modbus) kan den här knappen leta upp den på ditt lokala nätverk istället. Kan ta upp till en minut - söker bara, ändrar inget.</div>
      <button class="icobtn" id="scanmodbusbtn" style="margin-top:10px">Sök Modbus-värmepump på nätverket</button>
    </div>
    <div id="modbusScanResults"></div>
    <div id="discoverResults"></div>`;
  document.getElementById("scanbtn").onclick = runDiscovery;
  document.getElementById("scanmodbusbtn").onclick = runModbusScan;
}

async function runModbusScan() {
  const results = document.getElementById("modbusScanResults");
  results.innerHTML = `<div class="placeholder">Söker på nätverket... (kan ta upp till en minut)</div>`;
  let d;
  try { d = await api("api/discover-modbus", { method: "POST" }); } catch (e) { results.innerHTML = `<div class="placeholder">${e.message}</div>`; return; }
  if (!d.ok) { results.innerHTML = `<div class="placeholder">${d.error}</div>`; return; }
  if (!d.found.length) { results.innerHTML = `<div class="note">Ingen Husdata-värmepump hittades på nätverket.</div>`; return; }
  results.innerHTML = `<div class="card" style="margin-bottom:16px"><h2>📡 Hittat på nätverket</h2>` +
    d.found.map(f => `<div class="note">Husdata-pump hittad på <b>${f.ip}</b> - lägg till <code>PUMP_IP=${f.ip}</code> i din .env och starta om smartbox.</div>`).join("") +
    `</div>`;
}

async function runDiscovery() {
  const results = document.getElementById("discoverResults");
  results.innerHTML = `<div class="placeholder">Skannar... (kan ta en liten stund)</div>`;
  let d;
  try { d = await api("api/discover", { method: "POST" }); } catch (e) { results.innerHTML = `<div class="placeholder">${e.message}</div>`; return; }
  if (!d.ok) { results.innerHTML = `<div class="placeholder">${d.error}</div>`; return; }
  _discovered = d;

  const driverTag = (item, genericKey) => {
    if (item.driver_known) return `<span class="tag">drivrutin: ${item.driver}</span>`;
    const base = `<span class="tag warn">hittades (${item.maker || "okänt märke"}) - ingen drivrutin än, bidra gärna</span>`;
    if (!item.generic_suggestion || !genericKey) return base;
    return base + `<label style="display:block;margin-top:4px;font-size:.8rem">
      <input type="checkbox" class="generic-pick" data-key="${genericKey}"> Använd generisk styrning (grundläggande, inte märkets fulla funktioner)</label>`;
  };

  let html = "";

  html += `<div class="card" style="margin-bottom:16px"><h2>🚗 Bilar (${d.cars.length})</h2>`;
  d.cars.forEach((c, i) => {
    html += `<div class="note" style="margin:10px 0;padding:10px;border:1px solid var(--line);border-radius:10px">
      <label><input type="checkbox" class="car-pick" data-i="${i}" checked> <b>${c.device_name}</b></label> ${driverTag(c)}<br>
      id: <input type="text" class="car-id" data-i="${i}" value="${c.driver}" style="width:100px"> &nbsp;
      batteri (kWh): <input type="number" class="car-kwh" data-i="${i}" value="60" style="width:70px"><br>
      <span style="font-size:.8rem">SOC: ${c.soc_entity || "-"} · Kabel: ${c.plugged_in_entity || "-"} · Klimat: ${c.climate_entity || "-"}</span>
    </div>`;
  });
  if (!d.cars.length) html += `<div class="note">Inga bilar hittades.</div>`;
  html += `</div>`;

  const simpleCard = (icon, title, item, fields) => {
    if (!item) return `<div class="card" style="margin-bottom:16px"><h2>${icon} ${title}</h2><div class="note">Inget hittades i Home Assistant${title === "Värmepump" ? " - normalt om din pump pratar direkt via Modbus istället för via en HA-integration (t.ex. Thermia/Husdata). Sätt heat_pump.enabled: true och fyll i anslutningen för hand i den nedladdade filen efteråt." : ""}.</div></div>`;
    return `<div class="card" style="margin-bottom:16px"><h2>${icon} ${title}</h2>
      <label><input type="checkbox" class="pick" data-cat="${title}" checked> Använd detta fynd</label> ${driverTag(item, title)}
      <div class="note" style="margin-top:6px;font-size:.8rem">${fields}</div></div>`;
  };
  html += simpleCard("♨️", "Värmepump", d.heat_pump, d.heat_pump ? (d.heat_pump.note || `${d.heat_pump.device_name} (${d.heat_pump.entity_count} entiteter)`) : "");
  html += simpleCard("☀️", "Solceller", d.solar, d.solar ? `Effekt: ${d.solar.pv_power_entity || "-"} · Dagsenergi: ${d.solar.today_kwh_entity || "-"}` : "");
  html += simpleCard("🛁", "Spabad", d.spa, d.spa ? `Temp: ${d.spa.current_temp_entity || "-"} · Effekt: ${d.spa.power_entity || "-"}` : "");
  html += simpleCard("🔋", "Husbatteri", d.battery, d.battery ? `SOC: ${d.battery.soc_entity || "-"} · Effekt: ${d.battery.power_entity || "-"} · bara läsning/enkel styrning, EnergyWizard fattar inga automatiska laddningsbeslut - kör Predbat parallellt för det.` : "");

  html += `<div class="card" style="margin-bottom:16px"><h2>🔌 Laddare (${d.chargers.length})</h2>`;
  d.chargers.forEach((c, i) => {
    html += `<label style="display:block;margin:6px 0"><input type="checkbox" class="charger-pick" data-i="${i}" checked> ${c.device_name}</label> ${driverTag(c, `charger:${i}`)}`;
  });
  if (!d.chargers.length) html += `<div class="note">Inga laddare hittades.</div>`;
  html += `</div>`;

  html += `<div class="card" style="margin-bottom:16px"><h2>⚡ Elmätare / Tibber Pulse</h2>
    <div class="note">Bara informativt än - EnergyWizard läser idag nätimport hårdkodat (Tibber Pulse), inte via en insticksbar drivrutin. Visas så du vet vilka entiteter som finns, oavsett om du har Pulse, en smartmätare (HAN/P1), eller båda.</div>`;
  (d.grid_meters || []).forEach(g => {
    html += `<div class="note" style="margin-top:6px">• ${g.kind === "pulse" ? "Tibber Pulse" : "Smartmätare"}: ${g.power_entity} (${g.maker || "okänt märke"})</div>`;
  });
  if (!(d.grid_meters || []).length) html += `<div class="note" style="margin-top:6px">Ingen hittades.</div>`;
  html += `</div>`;

  html += `<button class="icobtn" id="genbtn" style="margin-top:6px">Generera house_config.yaml</button>`;
  results.innerHTML = html;
  document.getElementById("genbtn").onclick = generateConfig;

  // Kryssar man i "Använd generisk styrning" skrivs fyndets driver/entities om till
  // förslaget (generic_suggestion) - annars tillbaka till det ursprungliga (okänt märke,
  // ingen drivrutin). generateConfig() läser direkt ur _discovered, så det räcker att
  // mutera objektet här, ingen separat state behövs.
  const itemForKey = (key) => key.startsWith("charger:") ? _discovered.chargers[key.split(":")[1]]
    : key === "Värmepump" ? _discovered.heat_pump
    : key === "Solceller" ? _discovered.solar
    : key === "Husbatteri" ? _discovered.battery
    : null;
  document.querySelectorAll(".generic-pick").forEach(cb => {
    cb.onchange = () => {
      const item = itemForKey(cb.dataset.key);
      if (!item || !item.generic_suggestion) return;
      if (cb.checked) {
        item._original_driver_state = { driver: item.driver, entities: item.entities };
        item.driver = item.generic_suggestion.driver;
        item.entities = item.generic_suggestion.entities;
      } else if (item._original_driver_state) {
        item.driver = item._original_driver_state.driver;
        item.entities = item._original_driver_state.entities;
      }
    };
  });
}

async function generateConfig() {
  const sel = { cars: [], heat_pump: null, solar: null, spa: null, battery: null };
  const pickedChargers = [];
  document.querySelectorAll(".charger-pick:checked").forEach(cb => pickedChargers.push(_discovered.chargers[cb.dataset.i]));
  document.querySelectorAll(".car-pick:checked").forEach((cb, idx) => {
    const i = cb.dataset.i;
    const car = { ..._discovered.cars[i] };
    car.id = document.querySelector(`.car-id[data-i="${i}"]`).value || car.driver;
    car.battery_kwh = parseFloat(document.querySelector(`.car-kwh[data-i="${i}"]`).value) || 60;
    // Ihopparning laddare<->bil är en gissning (index-ordning) - markerad i YAML:ns
    // kommentar, inte tyst: handskakningen (se main.py) kan ändå byta dem vid behov.
    car.charger = pickedChargers[idx] || null;
    sel.cars.push(car);
  });
  document.querySelectorAll(".pick:checked").forEach(cb => {
    const cat = cb.dataset.cat;
    if (cat === "Värmepump") sel.heat_pump = _discovered.heat_pump;
    if (cat === "Solceller") sel.solar = _discovered.solar;
    if (cat === "Spabad") sel.spa = _discovered.spa;
    if (cat === "Husbatteri") sel.battery = _discovered.battery;
  });

  const r = await fetch("api/generate-house-config", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify(sel) });
  if (!r.ok) { alert("Kunde inte generera filen: " + (await r.json().catch(() => ({}))).error); return; }
  const blob = await r.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = "house_config.yaml"; a.click();
  URL.revokeObjectURL(url);
}

function openPage(id) {
  currentPage = id;
  renderSidebar();
  closeMobileMenu();
  if (id === "oversikt") {
    renderOversikt();
  } else if (id === "varmepump") {
    renderVarmepump();
  } else if (id === "system") {
    renderSystem();
  } else if (id === "installningar") {
    renderInstallningar();
  } else if (id === "elbil") {
    renderElbil();
  } else if (id === "solceller") {
    renderSolceller();
  } else if (id === "ekonomi") {
    renderEkonomi();
  } else if (id === "elforbrukning") {
    renderElforbrukning();
  } else if (id === "spabad") {
    renderSpabad();
  } else if (id === "temperaturer") {
    renderTemperaturer();
  } else if (id === "prognos") {
    renderPrognos();
  } else if (id === "historik") {
    renderHistorik();
  } else if (id === "aviseringar") {
    renderAviseringar();
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

function closeMobileMenu() {
  document.getElementById("sidebar").classList.remove("open");
  document.getElementById("sidebarbackdrop").classList.remove("open");
}
document.getElementById("menubtn").onclick = () => {
  document.getElementById("sidebar").classList.toggle("open");
  document.getElementById("sidebarbackdrop").classList.toggle("open");
};
document.getElementById("sidebarbackdrop").onclick = closeMobileMenu;

boot();
