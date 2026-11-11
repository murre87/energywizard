// EnergyWizard Webdashboard - Fas B: Översikt-sidan med riktig data (portad från
// smartdashboard/app.py:s page_overview()). Resten av sidorna byggs i senare steg.
let moneyCurrency = "SEK", moneySymbol = "kr";
const moneyUnit = () => moneySymbol;
let PAGES = [];
let currentPage = null;

// Glas + dygnsfärger på som standard - samma designspråk som ewapp (html[data-glass]/
// html[data-ambient][data-tod]), inte en egen plattare stil. localStorage-nycklarna är
// delade namn med ewapp men EGEN lagring (skild origin) - "0" = avstängt av användaren.
(function applyAmbientTheme() {
  const de = document.documentElement;
  const todOf = (h) => (h >= 5 && h < 10 ? "morning" : h >= 10 && h < 16 ? "day" : h >= 16 && h < 21 ? "evening" : "night");
  let glass = "1", amb = "1";
  try { glass = localStorage.getItem("ew_glass") ?? "1"; amb = localStorage.getItem("ew_ambient") ?? "1"; } catch (e) { /* privat läge etc - kör med standard */ }
  if (glass !== "0") de.setAttribute("data-glass", "1"); else de.removeAttribute("data-glass");
  if (amb !== "0") { de.setAttribute("data-ambient", "1"); de.setAttribute("data-tod", todOf(new Date().getHours())); } else { de.removeAttribute("data-ambient"); de.removeAttribute("data-tod"); }
})();

function fmtKrOre(v) {
  if (v == null) return "–";
  return moneyCurrency === "SEK" && Math.abs(v) < 1 && v !== 0 ? `${Math.round(v * 100)} öre` : `${v.toFixed(2)} ${moneyUnit()}`;
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

// ---------- Besparing (inspirerat av FTW:s savings-kort, egen implementation) ----------
// Vad samma el hade kostat i ett vanligt hushåll utan styrning (toppar morgon och kväll), minus vad den kostade,
// inklusive moms (smartbox/savings.py). Negativa dagar visas som de är.
const SAVINGS_PERIODS = [["today", "Idag"], ["week", "7 dagar"], ["month", "Månad"]];
let savingsPeriod = "week";
try { savingsPeriod = localStorage.getItem("ew_savings_period") || "week"; } catch (e) { /* privat läge */ }


function savingsCardHtml(d) {
  const p = d.periods[savingsPeriod] || d.periods.week;
  const pos = p.saved_kr >= 0;
  const sign = p.saved_kr > 0 ? "+" : p.saved_kr < 0 ? "−" : "";
  const kr = `${sign}${Math.abs(p.saved_kr).toFixed(0)} ${moneyUnit()}`;
  const pct = p.pct != null ? ` <span style="font-size:1rem;font-weight:700;opacity:.8">(${p.pct > 0 ? "+" : ""}${p.pct.toFixed(0)} %)</span>` : "";
  const sub = p.days
    ? `${p.kwh.toFixed(0)} kWh köpt för ${p.paid_kr.toFixed(0)} ${moneyUnit()}, mot ${(p.paid_kr + p.saved_kr).toFixed(0)} ${moneyUnit()} i ett vanligt hushåll utan styrning (inkl. moms)${p.days > 1 ? ` · ${p.days} dagar med data` : ""}`
    : "Ingen mätdata för perioden än.";
  return `
    <div class="card" id="savingscard">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap">
        <h2 style="margin:0">💰 Sparat genom smart tajmning</h2>
        <div class="seg" id="savingsseg">${SAVINGS_PERIODS.map(([k, l]) => `<button data-p="${k}" class="${k === savingsPeriod ? "on" : ""}">${l}</button>`).join("")}</div>
      </div>
      <div style="font-size:2.1rem;font-weight:800;margin-top:10px;color:${pos ? "var(--acc)" : "var(--bad)"};font-variant-numeric:tabular-nums">${kr}${pct}</div>
      <div class="note">${sub}</div>
      <div id="savingsbars" style="height:90px;margin-top:8px"></div>
    </div>`;
}

// Kostnad per dag (Ekonomi): uppåt = kostnad, nedåt (grönt) = dagar då solen gav mer än elen kostade.
function costBars(elId, days, sym) {
  const el = document.getElementById(elId);
  if (!el || !days.length) return;
  const chart = echarts.init(el, null, { renderer: "svg" });
  const css = getComputedStyle(document.documentElement);
  const blue = css.getPropertyValue("--acc2").trim() || "#38bdf8", good = css.getPropertyValue("--acc").trim() || "#22d3a0";
  chart.setOption({
    grid: { left: 44, right: 4, top: 6, bottom: 30 },
    tooltip: { trigger: "axis", formatter: (ps) => { const r = days[ps[0].dataIndex];
      return `${r.day}<br>Köpt ${r.cost.toFixed(2)} ${sym} (${r.bought_kwh.toFixed(1)} kWh)<br>Sålt ${r.income.toFixed(2)} ${sym}<br><b>Netto ${r.net.toFixed(2)} ${sym}</b>`; } },
    xAxis: { type: "category", data: days.map((r) => r.day.slice(5)), axisLabel: { color: "#93a0b8" } },
    yAxis: { type: "value", splitLine: { lineStyle: { color: "rgba(255,255,255,.08)" } }, axisLabel: { color: "#93a0b8" } },
    series: [{ type: "bar", data: days.map((r) => ({ value: r.net, itemStyle: { color: r.net >= 0 ? blue : good, borderRadius: r.net >= 0 ? [3, 3, 0, 0] : [0, 0, 3, 3] } })), barMaxWidth: 14 }],
  });
  window.addEventListener("resize", () => chart.resize());
}

function savingsBars(elId, days, height) {
  const el = document.getElementById(elId);
  if (!el || !days || !days.length) return;
  const chart = echarts.init(el, null, { renderer: "svg" });
  const css = getComputedStyle(document.documentElement);
  const good = css.getPropertyValue("--acc").trim() || "#22d3a0", bad = css.getPropertyValue("--bad").trim() || "#f87171";
  chart.setOption({
    grid: { left: height ? 40 : 4, right: 4, top: 6, bottom: height ? 30 : 4 },
    tooltip: { trigger: "axis", formatter: (ps) => `${ps[0].name}: ${ps[0].value >= 0 ? "+" : ""}${ps[0].value.toFixed(2)} ${moneyUnit()}` },
    xAxis: { type: "category", data: days.map((r) => r.day.slice(5)), show: !!height, axisLabel: { color: "#93a0b8" } },
    yAxis: { type: "value", show: !!height, splitLine: { lineStyle: { color: "rgba(255,255,255,.08)" } }, axisLabel: { color: "#93a0b8" } },
    series: [{ type: "bar", data: days.map((r) => ({ value: r.saved_kr, itemStyle: { color: r.saved_kr >= 0 ? good : bad, borderRadius: r.saved_kr >= 0 ? [3, 3, 0, 0] : [0, 0, 3, 3] } })), barMaxWidth: 14 }],
  });
  new ResizeObserver(() => chart.resize()).observe(el);
}

async function mountSavings(slotId) {
  const slot = document.getElementById(slotId);
  if (!slot) return;
  let d;
  try { d = await api("api/savings"); } catch (e) { slot.innerHTML = ""; return; }
  if (!d.ok) { slot.innerHTML = ""; return; }
  const draw = () => {
    slot.innerHTML = savingsCardHtml(d);
    const n = savingsPeriod === "today" ? 1 : savingsPeriod === "week" ? 7 : d.days.filter((r) => r.day.startsWith(d.today.slice(0, 7))).length;
    savingsBars("savingsbars", d.days.slice(-Math.max(n, 7)));
    slot.querySelectorAll("#savingsseg button").forEach((b) => b.onclick = () => {
      savingsPeriod = b.dataset.p;
      try { localStorage.setItem("ew_savings_period", savingsPeriod); } catch (e) { /* privat läge */ }
      draw();
    });
  };
  draw();
  return d;
}

// ---------- Planen framåt i klartext (inspirerat av FTW:s plan brief) ----------
// Beskriver motorns egen plan - elbilens laddpass och värmepumpens grundläge enligt
// elpriset (smartbox/plan_brief.py). Inga nya beslut fattas här.
// Solprognos per dygn (smartbox/solar_days.py): samma timprognos som motorn planerar efter.
function sunDaysHtml(sd) {
  if (!sd || sd.today_kwh == null) return "";
  const f = (v) => v == null ? "–" : (v >= 10 ? v.toFixed(0) : v.toFixed(1).replace(".", ","));
  const tile = (label, v, sub) => `<div class="stat" style="flex:1;min-width:110px;padding:10px 12px">
      <div class="note">${label}</div><div style="font-size:1.25rem;font-weight:700">${f(v)} <span class="note">kWh</span></div>
      ${sub ? `<div class="note">${sub}</div>` : ""}</div>`;
  const today = [sd.today_left_kwh != null ? `${f(sd.today_left_kwh)} kvar` : "", sd.produced_today_kwh != null ? `${f(sd.produced_today_kwh)} hittills` : ""].filter(Boolean).join(" · ");
  return `<div style="margin:0 0 10px"><div class="note" style="margin-bottom:6px">☀️ Solprognos</div>
    <div style="display:flex;gap:8px;flex-wrap:wrap">${tile("Idag", sd.today_kwh, today)}${tile("Imorgon", sd.tomorrow_kwh)}${sd.day_after_kwh != null ? tile("I övermorgon", sd.day_after_kwh) : ""}</div></div>`;
}

// ---------- Planklockan (idé från FTW, egen implementation) ----------
// De kommande 24 timmarna som en urtavla: ett streck per kvart, färgat efter priset (grönt billigt, rött dyrt),
// visaren på nu. Ringar innanför: värmepumpen laddar huset, elbilarna laddar, batteriet laddar/laddar ur.
// Under: en remsa för de närmaste 12 timmarna och bilarnas mål. Spot/totalt växlar priset (totalt = inkl.
// moms, nätavgift och skatt, samma som motorn räknar med). Bara visning - inga nya beslut fattas här.
let clockPriceMode = localStorage.getItem("ew_clock_price") || "total";
const CLOCK_COL = { cheap: "#22d3a0", mid: "#38bdf8", dear: "#f87171", heat: "#fb923c", charge: "#22d3a0", discharge: "#fbbf24",
  hold: "#38bdf8", idle: "#94a3b8", export: "#d946ef" };   // export = laddar ur och säljer överskottet (egen färg, Anders på Discord)
const CAR_COL = ["#38bdf8", "#a78bfa", "#f472b6", "#22d3a0"];
const kr = (v) => v == null ? "–" : v.toFixed(2).replace(".", ",");
const hhmm = (t) => new Date(t).toLocaleTimeString("sv-SE", { hour: "2-digit", minute: "2-digit" });

function priceColor(p, lo, hi) {
  if (hi - lo < 1e-6) return CLOCK_COL.mid;
  const x = (p - lo) / (hi - lo);
  return x < 0.33 ? CLOCK_COL.cheap : x < 0.66 ? CLOCK_COL.mid : CLOCK_COL.dear;
}

function planClockHtml(d) {
  if (!d.prices || !d.prices.length) return "";
  const C = 170, now = new Date(d.now), key = clockPriceMode === "spot" ? "spot" : "total";
  const ang = (t) => { const x = new Date(t); return ((x.getHours() + x.getMinutes() / 60) / 24) * 2 * Math.PI - Math.PI / 2; };
  const pt = (a, r) => [C + r * Math.cos(a), C + r * Math.sin(a)];
  const vals = d.prices.map((p) => p[key]), lo = Math.min(...vals), hi = Math.max(...vals);
  let ticks = "";
  d.prices.forEach((p) => {
    const a = ang(p.t), [x1, y1] = pt(a, 122), [x2, y2] = pt(a, 150);
    ticks += `<line x1="${x1.toFixed(1)}" y1="${y1.toFixed(1)}" x2="${x2.toFixed(1)}" y2="${y2.toFixed(1)}" stroke="${priceColor(p[key], lo, hi)}" stroke-width="5.2" stroke-linecap="round"><title>${hhmm(p.t)} · ${kr(p[key])} ${moneyUnit()}/kWh</title></line>`;
  });
  const end24 = new Date(now.getTime() + 24 * 3600e3);
  const arc = (start, end, r, col, w, title) => {
    const s = new Date(Math.max(new Date(start), now)), e = new Date(Math.min(new Date(end), end24));
    if (e <= s) return "";
    let a0 = ang(s), a1 = ang(e);
    if (a1 <= a0) a1 += 2 * Math.PI;
    const [x0, y0] = pt(a0, r), [xe, ye] = pt(a1, r), large = a1 - a0 > Math.PI ? 1 : 0;
    return `<path d="M${x0.toFixed(1)} ${y0.toFixed(1)} A${r} ${r} 0 ${large} 1 ${xe.toFixed(1)} ${ye.toFixed(1)}" fill="none" stroke="${col}" stroke-width="${w}" stroke-linecap="round"><title>${esc(title)}</title></path>`;
  };
  const cars = [...new Set(d.items.filter((i) => i.kind === "ev").map((i) => i.car))];
  const rings = [];
  if (d.items.some((i) => i.kind === "heat")) rings.push({ kind: "heat" });
  cars.forEach((c, k) => rings.push({ kind: "ev", car: c, col: CAR_COL[k % CAR_COL.length] }));
  if (d.items.some((i) => i.kind === "battery")) rings.push({ kind: "battery" });
  let ringSvg = "";
  rings.slice(0, 4).forEach((rg, k) => {
    const r = 106 - k * 15;
    ringSvg += `<circle cx="${C}" cy="${C}" r="${r}" fill="none" stroke="var(--line)" stroke-width="8"/>`;
    d.items.filter((i) => i.kind === rg.kind && (rg.kind !== "ev" || i.car === rg.car)).forEach((i) => {
      if (rg.kind === "heat" && i.mode !== "CHEAP") return;
      const col = rg.kind === "heat" ? CLOCK_COL.heat : rg.kind === "ev" ? rg.col : (CLOCK_COL[i.action] || CLOCK_COL.hold);
      ringSvg += arc(i.start, i.end, r, col, 8, `${i.title} ${i.when}`);
    });
  });
  let labels = "";
  [0, 3, 6, 9, 12, 15, 18, 21].forEach((h) => {
    const a = (h / 24) * 2 * Math.PI - Math.PI / 2, [x, y] = pt(a, 162), big = h % 6 === 0;
    labels += `<text x="${x.toFixed(1)}" y="${(y + 4).toFixed(1)}" text-anchor="middle" font-size="${big ? 12 : 10}" font-weight="${big ? 700 : 400}" fill="var(--mut)">${String(h).padStart(2, "0")}</text>`;
  });
  const an = ang(now), [hx, hy] = pt(an, 152);
  const cur = d.prices.find((p) => new Date(p.t) <= now && now < new Date(new Date(p.t).getTime() + 15 * 60e3)) || d.prices[0];
  const hand = `<line x1="${(C + 58 * Math.cos(an)).toFixed(1)}" y1="${(C + 58 * Math.sin(an)).toFixed(1)}" x2="${hx.toFixed(1)}" y2="${hy.toFixed(1)}" stroke="var(--txt)" stroke-width="2.5" stroke-linecap="round" opacity=".85"/>
    <circle cx="${hx.toFixed(1)}" cy="${hy.toFixed(1)}" r="5" fill="var(--txt)"/>`;
  const cr = Math.max(30, 106 - Math.min(rings.length, 4) * 15 - 6);
  const center = `<circle cx="${C}" cy="${C}" r="${cr}" fill="var(--bg)"/><circle cx="${C}" cy="${C}" r="${cr}" fill="var(--card2)"/>
    <text x="${C}" y="${C - 2}" text-anchor="middle" font-size="26" font-weight="800" fill="${priceColor(cur[key], lo, hi)}">${kr(cur[key])}</text>
    <text x="${C}" y="${C + 18}" text-anchor="middle" font-size="11" fill="var(--mut)">${moneyUnit()}/kWh ${key === "spot" ? "spot" : "totalt"}</text>`;
  const legend = [["Billigt", CLOCK_COL.cheap], ["Mellan", CLOCK_COL.mid], ["Dyrt", CLOCK_COL.dear]].map(([t, c]) =>
    `<span style="display:inline-flex;align-items:center;gap:5px;margin-right:12px"><span style="width:10px;height:10px;border-radius:3px;background:${c}"></span>${t}</span>`).join("")
    + rings.slice(0, 4).map((rg) => {
      const [t, c] = rg.kind === "heat" ? ["Värmepumpen laddar huset", CLOCK_COL.heat] : rg.kind === "ev" ? [`${rg.car.charAt(0).toUpperCase() + rg.car.slice(1)} laddar`, rg.col]
        : ["Batteriet laddar", CLOCK_COL.charge];
      return `<span style="display:inline-flex;align-items:center;gap:5px;margin-right:12px"><span style="width:14px;height:4px;border-radius:2px;background:${c}"></span>${t}</span>`;
    }).join("")
    + [["discharge", "Laddar ur (eget bruk)"], ["export", "Laddar ur och säljer"]].filter(([a]) => d.items.some((i) => i.kind === "battery" && i.action === a))
      .map(([a, t]) => `<span style="display:inline-flex;align-items:center;gap:5px;margin-right:12px"><span style="width:14px;height:4px;border-radius:2px;background:${CLOCK_COL[a]}"></span>${t}</span>`).join("");
  const svg = `<svg viewBox="0 0 340 340" style="width:100%;max-width:340px;height:auto;display:block;margin:0 auto" role="img" aria-label="Planklocka: de kommande 24 timmarna">${labels}${ticks}${ringSvg}${hand}${center}</svg>`;
  return `<div class="planclock" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,300px),1fr));gap:16px;align-items:center;margin:4px 0 14px">
      <div>${svg}<div class="note" style="text-align:center;margin-top:6px">${legend}</div>
        <div style="display:flex;justify-content:center;gap:6px;margin-top:8px">
          <button class="icobtn" data-clockprice="total"${key === "total" ? ` style="border-color:var(--acc);color:var(--acc)"` : ""}>Totalt pris</button>
          <button class="icobtn" data-clockprice="spot"${key === "spot" ? ` style="border-color:var(--acc);color:var(--acc)"` : ""}>Spotpris</button></div></div>
      <div>${planStripHtml(d, now)}</div>
    </div>`;
}

// Remsan: de närmaste 12 timmarna, en rad per sak som planeras, med rutor "Ladda 01:00–03:45".
// Batteriraden i planklockan: "Laddar ur till 09:45 · 80→35 % · 8,6 kWh · toppris 4,31 kr" (önskemål från HannesB).
const BAT_VERB = { charge: "Laddar", discharge: "Laddar ur", export: "Laddar ur och säljer", hold: "Sparas", idle: "Vilar" };
function batteryLaneText(i, now) {
  const on = new Date(i.start) <= now;
  const verb = BAT_VERB[i.action] || "Batteri";
  const parts = on ? [`${verb} till ${hhmm(new Date(i.end))}`] : [verb, i.when];
  if (i.soc_from != null && i.soc_to != null && i.soc_from !== i.soc_to) parts.push(`${i.soc_from}→${i.soc_to} %`);
  else if (i.soc_to != null) parts.push(`${i.soc_to} %`);
  if (i.kwh) parts.push(`${String(i.kwh).replace(".", ",")} kWh`);
  if (i.price_peak != null) parts.push(`${i.action === "discharge" || i.action === "export" ? "toppris" : "lägsta pris"} ${i.price_peak.toFixed(2).replace(".", ",")} ${moneyUnit()}`);
  return parts.map((p) => `<span>${esc(p)}</span>`).join(" · ");   // en textnod per del, så att översättningen hittar dem
}

function planStripHtml(d, now) {
  const end = new Date(now.getTime() + 12 * 3600e3), span = end - now;
  const pos = (t) => Math.max(0, Math.min(100, ((new Date(t) - now) / span) * 100));
  const cars = [...new Set(d.items.filter((i) => i.kind === "ev").map((i) => i.car))];
  const lanes = [];
  if (d.items.some((i) => i.kind === "heat")) lanes.push(["🌡️", "Värmepump", (i) => i.kind === "heat" && i.mode === "CHEAP", () => CLOCK_COL.heat]);
  cars.forEach((c, k) => lanes.push(["🚗", c.charAt(0).toUpperCase() + c.slice(1), (i) => i.kind === "ev" && i.car === c, () => CAR_COL[k % CAR_COL.length]]));
  if (d.items.some((i) => i.kind === "battery")) lanes.push(["🔋", "Batteri", (i) => i.kind === "battery", (i) => CLOCK_COL[i.action] || CLOCK_COL.hold]);
  const rows = lanes.map(([ico, name, match, col]) => {
    const segs = d.items.filter(match).filter((i) => new Date(i.end) > now && new Date(i.start) < end).map((i) => {
      const l = pos(i.start), w = Math.max(1.5, pos(i.end) - l);
      return `<div title="${esc(i.title + " " + i.when)}" style="position:absolute;left:${l}%;width:${w}%;top:0;bottom:0;border-radius:6px;background:${col(i)};opacity:.85"></div>`;
    }).join("");
    const next = d.items.filter(match).find((i) => new Date(i.end) > now);
    const txt = next ? (next.kind === "battery" ? batteryLaneText(next, now) : `${esc(next.title.replace(/^\S+\s/, ""))} · ${esc(next.when)}`) : "Inget planerat";
    return `<div style="margin-bottom:12px"><div style="display:flex;justify-content:space-between;gap:8px;font-size:.92rem">
        <span style="white-space:nowrap"><b>${ico} ${esc(name)}</b></span><span class="note" style="text-align:right;min-width:0">${txt}</span></div>
      <div style="position:relative;height:14px;margin-top:5px;border-radius:7px;background:var(--line)">${segs}</div></div>`;
  }).join("");
  const ticks = [0, 3, 6, 9, 12].map((h) => {
    const t = new Date(now.getTime() + h * 3600e3);
    return `<span style="position:absolute;left:${(h / 12) * 100}%;transform:translateX(${h === 0 ? "0" : h === 12 ? "-100%" : "-50%"})">${h === 0 ? "nu" : hhmm(t)}</span>`;
  }).join("");
  const goals = (d.car_goals || []).map((g) => {
    const day = new Date(g.at).toDateString() === now.toDateString() ? "" : goalDay(g.at) + " ";
    const off = g.plugged === false;
    return `<div class="stat" style="padding:8px 12px;flex:1;min-width:140px${off ? ";opacity:.6" : ""}"><div class="note">🚗 ${esc(g.car.charAt(0).toUpperCase() + g.car.slice(1))}${off ? " · 🔌 inte ansluten" : ""}</div>
      <div style="font-weight:700">${off ? `Mål ${g.soc != null ? g.soc + " % " : ""}${day}${hhmm(g.at)}` : `${g.soc != null ? g.soc + " % " : ""}klar ${day}${hhmm(g.at)}`}</div>
      ${off ? `<div class="note">Laddar när kabeln sätts i</div>` : ""}</div>`;
  }).join("");
  return `<div class="note" style="margin-bottom:8px">De närmaste 12 timmarna</div>${rows || `<div class="note">Inget planerat.</div>`}
    <div class="note" style="position:relative;height:16px;font-size:.75rem">${ticks}</div>
    ${goals ? `<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:12px">${goals}</div>` : ""}`;
}

function planCardHtml(d) {
  // Tid och text sida vid sida när det får plats, annars tiden ovanför (förut bröts texten i en smal kolumn).
  const row = (i, hidden) => `
    <div class="planrow"${hidden ? " hidden" : ""} style="display:flex;flex-wrap:wrap;column-gap:14px;row-gap:2px;padding:9px 0;border-top:1px solid var(--line)${i.active ? ";font-weight:600" : ""}">
      <div style="flex:0 0 auto;min-width:150px;white-space:nowrap;font-variant-numeric:tabular-nums">${i.active ? `<span class="badge on" style="margin-right:6px">Nu</span>` : ""}${esc(i.when)}</div>
      <div style="flex:1 1 240px;min-width:0"><div>${esc(i.title)}</div><div class="note">${esc(i.detail)}</div></div>
    </div>`;
  const SHOW = 4;
  const rows = d.items.slice(0, 12).map((i, k) => row(i, k >= SHOW)).join("")
    + (d.items.length > SHOW ? `<button class="icobtn" style="margin-top:8px" onclick="this.parentElement.querySelectorAll('.planrow[hidden]').forEach(r=>r.hidden=false);this.remove()">Visa alla (${Math.min(d.items.length, 12)})</button>` : "");
  return `
    <div class="card">
      <h2>🗓️ Planen framåt</h2>
      <div style="font-size:1.02rem;margin:4px 0 10px">${esc(d.headline)}</div>
      ${window.EWPlanView ? `<div class="ewpcslot" style="margin:6px 0 14px"></div>` : planClockHtml(d)}
      ${sunDaysHtml(d.solar_days)}
      ${rows || ""}
      ${d.items.length ? `<div class="note" style="margin-top:8px">${esc(d.note)}</div>` : ""}
    </div>`;
}

async function mountPlan(slotId) {
  const slot = document.getElementById(slotId);
  if (!slot) return;
  try {
    const d = await api("api/plan");
    slot.innerHTML = d.ok ? planCardHtml(d) : "";
    const pcs = slot.querySelector(".ewpcslot");
    if (pcs) api("api/planclock").then((pc) => { if (pc && pc.ok) EWPlanView.mount(pcs, pc, { lang: (window.I18N && I18N.lang) || "sv", unit: moneyUnit() }); }).catch(() => {});
    slot.querySelectorAll("[data-clockprice]").forEach((b) => b.onclick = () => {
      clockPriceMode = b.dataset.clockprice; localStorage.setItem("ew_clock_price", clockPriceMode); mountPlan(slotId);
    });
  } catch (e) { slot.innerHTML = ""; }
}

// ---------- Just nu: levande energiflöde (bara det huset har) ----------
// Huset i mitten, källor till vänster (sol, nät, batteri), förbrukare till höger. Prickarnas fart
// följer effekten, riktningen visar köp/sälj. Inaktivt tonas ned. Klick öppnar enhetens sida.
const FLOW_COL = { sol: "#fbbf24", nat: "#38bdf8", natut: "#22d3a0", batteri: "#0e7490", varmepump: "#fb923c", varmvatten: "#60a5fa", spabad: "#a78bfa", ev: "#22d3a0" };
const reduceMotion = () => { try { return matchMedia("(prefers-reduced-motion: reduce)").matches; } catch (e) { return false; } };
let flowTimer = null;

function flowSvg(d) {                    // delad med mobilappen (smartbox/static/liveflow.js) - samma bild och regler
  return window.EWLiveFlow ? EWLiveFlow.svg(d, { attrs: (n) => `class="fnode${n.active ? " on" : ""}" data-page="${n.page}"`, hubAttrs: 'class="fnode on" data-page="oversikt"' }) : "";
}

async function mountFlow(slotId) {
  const draw = async () => {
    const slot = document.getElementById(slotId);
    if (!slot) { clearInterval(flowTimer); return; }
    let d; try { d = await api("api/flow"); } catch (e) { return; }
    if (!d.ok) { slot.innerHTML = ""; return; }
    const whyRows = d.nodes.filter((n) => d.why[n.key]).map((n) => `<div style="display:flex;gap:10px;align-items:baseline;padding-top:8px;border-top:1px solid var(--line)"><span>${esc(n.icon)}</span><div><b>${esc(n.label)}</b> <span class="note" style="font-size:.9rem">${esc(d.why[n.key])}</span></div></div>`).join("");
    // #166: batterisensorn verkar ha omvänt tecken (huset räknas negativt) - föreslå att vända det
    const bs = d.battery_sign, kw = (w) => (w / 1000).toFixed(1).replace(".", ",");
    const parts = bs ? `Sol ${kw(bs.pv_w)} + nät ${kw(bs.net_w)}${bs.battery_w != null ? ` − batteri ${kw(bs.battery_w)}` : ""} = ${kw(bs.house_w)} kW.` : "";
    const signBox = !bs ? "" : `<div class="note" style="margin-top:10px;padding:10px 12px;border:1px solid var(--warn);border-radius:12px;line-height:1.45">
        ${bs.battery_implausible ? `⚠️ Batteriets effekt visar ${kw(bs.battery_w)} kW, vilket är orimligt för ett husbatteri. Troligen har fel givare valts (t.ex. energi i kWh eller växelriktarens totala effekt), så den räknas inte in i husets förbrukning. Välj batteriets <b>effekt</b> (W eller kW, + när det laddar) under Inställningar → Skanna mitt Home Assistant.`
        : `⚠️ Husets förbrukning blir ${kw(bs.house_w)} kW, vilket inte går, så den visas som 0. ${parts}`}
        ${bs.battery_implausible ? "" : bs.flip_ok ? ` Batteriets effekt verkar ha omvänt tecken: vänt blir huset ${kw(bs.house_w_flipped)} kW.
          ${bs.locked ? "Tecknet är låst i house_config.yaml (battery.power_invert) - ändra det där." : `<br><button class="icobtn" id="batinv" style="margin-top:8px">Vänd tecknet på batteriets effekt</button>`}`
        : ` Någon av givarna visar fel: kontrollera att nätets effekt är + när du köper och − när du säljer, att solcellerna visar produktionen${bs.battery_w != null ? " och att batteriet är + när det laddar" : ""}, och att enheten (W eller kW) stämmer.`}</div>`;
    slot.innerHTML = `<div class="card"><div style="display:flex;justify-content:space-between;align-items:baseline"><h2 style="margin:0">⚡ Just nu</h2><span class="note">${esc(d.ts || "")}</span></div>${flowSvg(d)}${signBox}${whyRows ? `<div style="display:grid;gap:8px;margin-top:6px">${whyRows}</div>` : ""}</div>`;
    const bi = slot.querySelector("#batinv");
    if (bi) bi.onclick = async () => { try { await postJSON("api/battery-invert", {}); toast("Tecknet är vänt - syns i bilden inom en minut"); } catch (e) { toast(e.message); } };
    slot.querySelectorAll(".fnode[data-page]").forEach((g) => g.addEventListener("click", () => { const pg = g.dataset.page; if (pg && pg !== "oversikt" && PAGES.some((p) => p.id === pg)) openPage(pg); }));
  };
  clearInterval(flowTimer);
  await draw();
  flowTimer = setInterval(() => { if (currentPage === "oversikt") draw(); else clearInterval(flowTimer); }, 15000);
}

// ---------- Dygnet timme för timme: uppmätt bakåt, planerat framåt ----------
function timelineChart(elId, d) {
  const el = document.getElementById(elId);
  if (!el || !d || !d.hours.length) return;
  const chart = echarts.init(el, null, { renderer: "svg" });
  const css = getComputedStyle(document.documentElement), mut = "#93a0b8";
  const labels = d.hours.map((h) => h.slice(11, 13));
  const nowIdx = d.hours.indexOf(d.now);
  const lanes = d.lanes, n = labels.length;
  const laneData = [];
  lanes.forEach((ln, li) => ln.values.forEach((v, i) => { if (v != null && v > 0.02) laneData.push([i, li, v, d.future[i] ? 1 : 0]); }));
  const futArea = nowIdx >= 0 ? [[{ xAxis: labels[nowIdx], itemStyle: { color: "rgba(148,163,184,.08)" } }, { xAxis: labels[n - 1] }]] : [];
  // Mobil: smalare etikettkolumn, färre klockslag och axelnamnen i förklaringen (förut överlappade allt)
  const narrow = el.clientWidth < 560, L = narrow ? 70 : 120, R = narrow ? 30 : 52;
  const short = (t) => (narrow && t.length > 9 ? t.split(" ")[0].slice(0, 9) : t);
  const step = Math.max(1, Math.ceil(n / Math.max(4, Math.floor((el.clientWidth - L - R) / 34))));
  chart.setOption({
    axisPointer: { link: [{ xAxisIndex: "all" }] },
    grid: [{ left: L, right: R, top: 30, height: "36%" }, { left: L, right: R, top: "52%", bottom: 34 }],
    legend: { data: ["Elpris", "Sol"], top: 0, left: narrow ? "center" : L, itemWidth: 14, itemHeight: 8, textStyle: { color: mut, fontSize: narrow ? 11 : 12 },
              formatter: (nm) => (nm === "Elpris" ? `Elpris ${moneyUnit()}/kWh` : "Sol kW") },
    xAxis: [
      { type: "category", data: labels, gridIndex: 0, axisLabel: { show: false }, axisTick: { show: false }, axisLine: { lineStyle: { color: mut } } },
      { type: "category", data: labels, gridIndex: 1, axisLabel: { color: mut, interval: step - 1, fontSize: narrow ? 10 : 12 }, axisTick: { interval: step - 1 }, axisLine: { lineStyle: { color: mut } } },
    ],
    yAxis: [
      { type: "value", gridIndex: 0, axisLabel: { color: mut, fontSize: narrow ? 10 : 12 }, splitLine: { lineStyle: { color: "rgba(148,163,184,.12)" } } },
      { type: "value", gridIndex: 0, axisLabel: { color: mut, fontSize: narrow ? 10 : 12 }, splitLine: { show: false } },
      { type: "category", gridIndex: 1, data: lanes.map((l) => short(l.label)), inverse: true, axisLabel: { color: css.getPropertyValue("--txt").trim() || "#fff", fontWeight: 600, fontSize: narrow ? 11 : 12 }, axisLine: { show: false }, axisTick: { show: false } },
    ],
    tooltip: {
      trigger: "axis",
      formatter: (ps) => {
        const i = ps[0].dataIndex, h = d.hours[i];
        const head = `<b>${h.slice(11, 16)}${d.future[i] ? " · planerat" : ""}</b>`;
        const pr = d.price[i] != null ? `Elpris ${d.price[i].toFixed(2)} ${moneyUnit()}/kWh` : "";
        const sol = d.solar_kw[i] != null ? `Sol ${d.solar_kw[i].toFixed(1)} kW${d.future[i] ? " (prognos)" : ""}` : "";
        return [head, pr, sol, ...lanes.map((l) => `${esc(l.label)}: ${esc(l.text[i] || "–")}`)].filter(Boolean).join("<br>");
      },
    },
    series: [
      { name: "Sol", type: "bar", color: "#fbbf24", xAxisIndex: 0, yAxisIndex: 1, data: d.solar_kw.map((v, i) => ({ value: v, itemStyle: { color: "#fbbf24", opacity: d.future[i] ? 0.35 : 0.75 } })), barWidth: "70%" },
      { name: "Elpris", type: "line", color: "#38bdf8", step: "middle", xAxisIndex: 0, yAxisIndex: 0, data: d.price, symbol: "none", lineStyle: { color: "#38bdf8", width: 2 },
        markLine: nowIdx >= 0 ? { symbol: "none", label: { formatter: "nu", color: mut, position: "insideStartTop" }, lineStyle: { color: mut, type: "dashed" }, data: [{ xAxis: labels[nowIdx] }] } : undefined,
        markArea: { silent: true, data: futArea } },
      { type: "custom", xAxisIndex: 1, yAxisIndex: 2, data: laneData, renderItem: (params, api) => {
          const i = api.value(0), li = api.value(1), v = api.value(2), fut = api.value(3);
          const p0 = api.coord([i, li]), bw = api.size([1, 0])[0], bh = api.size([0, 1])[1] * 0.62;
          const color = lanes[li].color;
          const gap = bw > 8 ? 1 : 0.25;
          return { type: "rect", shape: { x: p0[0] - bw / 2 + gap, y: p0[1] - bh / 2, width: Math.max(1, bw - 2 * gap), height: bh, r: bw > 8 ? 4 : 1 },
                   style: { fill: color, opacity: (fut ? 0.12 : 0.2) + v * (fut ? 0.45 : 0.8), stroke: fut ? color : null, lineDash: fut ? [3, 3] : null, lineWidth: fut ? 1 : 0 } };
        } },
    ],
  });
  new ResizeObserver(() => chart.resize()).observe(el);
}

async function mountTimeline(slotId) {
  const slot = document.getElementById(slotId);
  if (!slot) return;
  let d; try { d = await api("api/timeline"); } catch (e) { slot.innerHTML = ""; return; }
  if (!d.ok) { slot.innerHTML = ""; return; }
  slot.innerHTML = `<div class="card"><h2>🕒 Dygnet timme för timme</h2><div class="note">Till vänster om strecket: det som hände (uppmätt). Till höger: det som är planerat. Starkare färg = mer.</div><div id="timelinechart" style="height:${260 + d.lanes.length * 34}px;margin-top:10px"></div></div>`;
  timelineChart("timelinechart", d);
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
        Assistant. Kryssa i det du har och tryck <b>Spara och starta</b> (eller ladda ner filen som din
        <code>house_config.yaml</code> och starta om smartbox, om du skrivit din config själv).</div>
      <button class="icobtn" id="gotosettings" style="margin-top:10px">Gå till Inställningar</button>
    </div>`;
    document.getElementById("gotosettings").onclick = () => openPage("installningar");
    return;
  }
  const emoji = d.mode === "CHEAP" ? "🟢" : d.mode === "EXPENSIVE" ? "🔴" : "⏸️";
  const netLabel = d.net_power_w != null && d.net_power_w < 0 ? "☀️ Netto (Säljer!)" : "🔌 Netto (Köper)";
  // #180: bara för den som har en effekttariff (egna tider) eller tidstariff inställd - inte standardtiderna
  const tariffRow = d.high_load_source === "egen" ? `⚡ Aktuell effekttariff: ${d.is_high_load ? "🔴 Höglast" : "🟢 Baslast"}`
    : d.high_load_source === "tidstariff" ? `⚡ Tidstariff just nu: ${d.is_high_load ? "🔴 Höglast" : "🟢 Låglast"}` : "";
  main.innerHTML = `
    <div class="card" style="margin-bottom:16px">
      <div style="font-size:1.15rem;font-weight:700">${emoji} ${d.decision}</div>
      <div class="note" style="margin-top:4px">💸 ${fmtKrOre(d.price)}/kWh · 🌡️ Inne ${fmt(d.indoor_temp, 1, "°C")} (mål ${d.indoor_target.toFixed(0)}) · 🌳 Ute ${fmt(d.outdoor_temp, 1, "°C")}</div>
    </div>
    ${(d.ftw_problems || []).map((s) => `<div class="card" style="margin-bottom:16px;border-color:var(--warn,#f59e0b)">
      <b>⚠️ Växelriktaren svarar inte (FTW-drivrutinen ${esc(s.driver)}, ${esc(s.host || "")}:${esc(String(s.port || ""))})</b>
      <div class="note" style="margin-top:6px;line-height:1.5">Därför saknas sol och batteri på Översikt, Solceller och Historik. Fel: ${esc(s.error || "inget svar")}.<br>
      Kontrollera IP-adress och port i Inställningar → Skanna mitt Home Assistant (FTW-drivrutin), och att växelriktarens lokala gränssnitt är påslaget
      (Fronius: <i>Solar API</i> för port 80 eller <i>Modbus TCP</i> för port 502 i växelriktarens webbsida). Får du data i Home Assistant redan kan du i stället välja de entiteterna och ingen FTW-drivrutin.</div></div>`).join("")}
    <div id="flowslot" style="margin-bottom:16px"></div>
    <div id="planslot" style="margin-bottom:16px"></div>
    <div id="savingsslot" style="margin-bottom:16px"></div>
    ${tariffRow ? `<div class="card" style="margin-bottom:16px"><span class="note">${tariffRow}</span></div>` : ""}
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
    <div id="timelineslot"></div>
    <div class="note" style="margin-top:10px">Senast mätt: ${esc(String(d.sthlm_time || "").slice(0, 16))}</div>`;
  mountFlow("flowslot");
  mountSavings("savingsslot");
  mountPlan("planslot");
  api("api/control-alerts").then((r) => {                // en enhet som inte gör som den blir tillsagd syns överst
    if (!r || !r.alerts || !r.alerts.length || document.getElementById("ctrlalerts")) return;
    main.insertAdjacentHTML("afterbegin", `<div id="ctrlalerts">${r.alerts.map((a) => `<div class="card" style="margin-bottom:16px;border:1.5px solid ${a.level === "info" ? "#38bdf8" : "#ef4444"}">
      <b>${a.level === "info" ? "ℹ️" : "⚠️"} ${esc(a.device)}: ${esc(a.title)}</b><div style="margin-top:4px">${esc(a.text)}</div><div class="note">${esc(a.hint)}</div></div>`).join("")}</div>`);
  }).catch(() => {});
  api("api/shadow").then((sh) => {                       // skuggläget syns alltid överst, så ingen tror att huset styrs
    if (!sh || !sh.active || document.getElementById("shadowbanner")) return;
    main.insertAdjacentHTML("afterbegin", `<div class="card" id="shadowbanner" style="margin-bottom:16px;border-color:var(--warn)">
      🕶️ <b>Skuggläge:</b> EnergyWizard visar vad den hade gjort men styr ingenting. <a href="#" id="shadowgo">Se vad den hade gjort</a></div>`);
    document.getElementById("shadowgo").onclick = (e) => { e.preventDefault(); openPage("installningar"); };
  }).catch(() => {});
  mountTimeline("timelineslot");
}

function badge(cls, text) { return `<span class="badge ${cls}">${text}</span>`; }

function statTile(label, value, sub) {
  return `<div class="stat"><div class="v">${value}</div><div class="l">${label}</div>${sub ? `<div class="l">${sub}</div>` : ""}</div>`;
}

function barRow(name, pct, valueLabel, color) {
  const p = pct == null ? 0 : Math.max(0, Math.min(100, pct));
  const bg = color ? `;background:${color}` : "";
  return `<div class="barrow"><div class="name">${name}</div><div class="track"><div class="fill" style="width:${p}%${bg}"></div></div><div class="val">${valueLabel}</div></div>`;
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

function evPlanChart(elId, d) {
  const el = document.getElementById(elId);
  if (!el) return;
  const mut = "#93a0b8";
  const times = [...new Set([...d.plan.map((p) => p.t.slice(0, 16)), ...d.plan_prices.map((p) => p.t.slice(0, 16))])].sort();
  const first = d.plan[0].t.slice(0, 16), last = d.plan[d.plan.length - 1].t.slice(0, 16);
  const ts = times.filter((t) => t >= first.slice(0, 13) && t <= last);       // planens första timme -> sista slotten
  const cars = [...new Set(d.plan.map((p) => p.car))];
  const byKey = {}; d.plan.forEach((p) => { byKey[p.car + p.t.slice(0, 16)] = p; });
  const priceAt = (t) => { let v = null; d.plan_prices.forEach((p) => { if (p.t.slice(0, 16) <= t) v = p.p; }); return v; };
  const chart = echarts.init(el, null, { renderer: "svg" });
  chart.setOption({
    grid: { left: 46, right: 56, top: 30, bottom: 30 }, legend: { top: 0, textStyle: { color: mut } },
    tooltip: { trigger: "axis", formatter: (ps) => { const t = ts[ps[0].dataIndex];
      return [`<b>${t.slice(5, 10).replace("-", "/")} ${t.slice(11, 16)}</b>`, ...cars.map((c) => { const p = byKey[c + t]; return p ? `${c[0].toUpperCase() + c.slice(1)}: ${p.kw.toFixed(1)} kW${p.soc0 != null ? ` · ${Math.round(p.soc0)} → ${Math.round(p.soc1)} %` : ""}` : null; }).filter(Boolean),
        priceAt(t) != null ? `Elpris ${priceAt(t).toFixed(2)} ${moneyUnit()}/kWh` : ""].filter(Boolean).join("<br>"); } },
    xAxis: { type: "category", data: ts.map((t) => t.slice(11, 16)), axisLabel: { color: mut, interval: (i) => ts[i].slice(14, 16) === "00" && Number(ts[i].slice(11, 13)) % 2 === 0 } },
    yAxis: [{ type: "value", name: "kW", nameTextStyle: { color: mut }, axisLabel: { color: mut }, splitLine: { lineStyle: { color: "rgba(148,163,184,.12)" } } },
            { type: "value", name: moneyUnit() + "/kWh", nameTextStyle: { color: mut }, axisLabel: { color: mut }, splitLine: { show: false } }],
    series: [...cars.map((c) => ({ name: c[0].toUpperCase() + c.slice(1), type: "bar", stack: "ev", color: CAR_COL[cars.indexOf(c) % CAR_COL.length], data: ts.map((t) => (byKey[c + t] ? byKey[c + t].kw : 0)), itemStyle: { color: CAR_COL[cars.indexOf(c) % CAR_COL.length], borderRadius: 2 } })),
             { name: "Elpris", type: "line", color: "#fbbf24", step: "end", yAxisIndex: 1, data: ts.map(priceAt), symbol: "none", lineStyle: { color: "#fbbf24", width: 2 } }],
  });
  new ResizeObserver(() => chart.resize()).observe(el);
}

const WD = ["Mån", "Tis", "Ons", "Tor", "Fre", "Lör", "Sön"];
const WD_LONG = ["måndag", "tisdag", "onsdag", "torsdag", "fredag", "lördag", "söndag"];
// "Planen räknar nu med: fredag 07:00 · 100 %" - det mål motorn faktiskt använder (#142)
function goalDay(at) {
  const d = new Date(at), now = new Date(), tm = new Date(now.getTime() + 864e5);
  return d.toDateString() === now.toDateString() ? "idag" : d.toDateString() === tm.toDateString() ? "imorgon" : WD_LONG[(d.getDay() + 6) % 7];
}
function goalText(g) {
  if (!g) return `<span class="note">Inget påslaget schema - planen följer elpriset (och morgongolvet om det är på).</span>`;
  return `Planen räknar nu med: ${goalDay(g.at)} ${hhmm(new Date(g.at))}${g.soc != null ? " · " + g.soc + " %" : ""}`;
}

async function renderElbil() {
  const d = await loadPage("api/car", (d) => `
    <div class="grid" style="margin-bottom:16px">
      ${d.cars.map(c => {
        const wk = (d.schedule || {})[c.id] || [];
        return `<div class="card">
        <div style="font-size:1.05rem;font-weight:700">🚗 ${c.name}</div>
        <div class="v" style="margin:10px 0 2px;font-size:1.6rem">${fmt(c.soc, 0, "%")}</div>
        <div class="note">${c.stale ? badge("warn", "⚠️ gammalt värde") : badge("on", "live")} ${c.status ? "· " + c.status : ""}</div>
        <div class="note" style="margin-top:6px">⚡ ${fmt(c.power_kw, 1, " kW")} just nu${c.planned_kwh_today != null ? ` · 📅 ${c.planned_kwh_today.toFixed(1)} kWh planerat idag` : ""}</div>
        ${c.limits ? `<div class="note">🔌 ${c.limits.phases === "auto" ? "Faser: auto" : c.limits.phases + "-fas"}${c.limits.phases_src === "inlärt" ? " (inlärt)" : ""} · max ${c.limits.max_a} A${c.limits.max_a_src === "inlärt" ? " (inlärt av laddningarna)" : c.limits.max_a_src === "standard" ? " (standard)" : ""}</div>` : ""}
        ${c.climate_state ? `<div class="note">🌡️ Klimat: ${c.climate_state}${c.climate_temp != null ? " (" + c.climate_temp.toFixed(0) + "°C)" : ""}</div>` : ""}
        ${(() => { const ma = (c.limits || {}).max_a || 16;           // #182: förklaring på varje knapp
          const t = { start: `Laddar nu med ${ma} A, före planen och elpriset. Gäller tills du trycker Auto eller Stoppa. Säkringsskyddet gäller fortfarande.`,
            max: `Laddar med full ström (${ma} A) direkt, oavsett elpris. Gäller tills du trycker Auto eller Stoppa. Säkringsskyddet gäller fortfarande.`,
            stop: "Stoppar laddningen och låter planen vila tills du trycker Auto.",
            auto: "Tillbaka till automatiken: laddar efter planen, elpriset, solen och laddschemat.",
            heat_on: "Startar kupévärmen i bilen nu.", heat_off: "Stänger av kupévärmen." };
          const b = (k, label) => `<button data-car="${c.id}" data-kind="${k}" title="${t[k]}" aria-label="${label}: ${t[k]}">${label}</button>`;
          return `<div class="seg" style="margin-top:12px;flex-wrap:wrap">${b("start", "Ladda nu")}${b("max", `Max ${ma} A`)}${b("stop", "Stoppa")}${b("auto", "Auto")}</div>
        <div class="seg" style="margin-top:6px">${b("heat_on", "🔥 Värm")}${b("heat_off", "Stoppa värme")}</div>`; })()}
        <div class="card" style="margin-top:12px;padding:12px">
          <div class="note">📅 Laddschema - klar till klockslag och nivå, per veckodag</div>
          <div style="margin:6px 0 8px;font-weight:600">${goalText(c.next_goal)}</div>
          ${wk.map((x) => `<div class="schrow" style="display:flex;align-items:center;gap:8px;padding:4px 0;border-top:1px solid var(--line)">
            <span style="width:34px;font-weight:600">${WD[x.day]}</span>
            <label class="switch" style="flex:none"><input type="checkbox" class="sch-en" data-car="${c.id}" data-day="${x.day}" ${x.enabled ? "checked" : ""}><span class="slider"></span></label>
            <input type="time" class="sch-t" data-car="${c.id}" data-day="${x.day}" value="${x.time}" style="flex:1 1 90px;min-width:0">
            <input type="number" class="sch-s" data-car="${c.id}" data-day="${x.day}" min="20" max="100" value="${x.soc}" style="width:64px"> %
          </div>`).join("")}
          <div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:8px">
            <button class="icobtn sch-save" data-car="${c.id}">Spara veckan</button>
            <button class="icobtn sch-all" data-car="${c.id}" title="Måndagens rad gäller alla dagar">Samma som måndag alla dagar</button>
          </div>
        </div>
      </div>`;
      }).join("")}
    </div>
    <div class="card" style="margin-bottom:16px"><h2>🔌 Laddplanen</h2><div class="note">Planerad laddeffekt per kvart mot elpriset. Håll muspekaren över en stapel för batterinivån.</div>${d.plan && d.plan.length ? `<div id="evplanchart" style="height:260px;margin-top:10px"></div>` : `<div class="note" style="margin-top:8px">Ingen laddning planerad just nu.</div>`}</div>
    <div class="note">Laddström: ${fmt(d.current_a, 0, " A")} · Dynamisk gräns: ${fmt(d.dynamic_limit_a, 0, " A")} · Målgräns just nu: ${fmt(d.current_target_limit, 0, " A")}</div>
    <div id="tesla-access" style="margin-top:16px"></div>`);
  if (!d) return;
  if (d.plan && d.plan.length) evPlanChart("evplanchart", d);
  document.querySelectorAll("[data-kind]").forEach(b => b.onclick = () => postAction(`api/car/${b.dataset.car}/action`, { kind: b.dataset.kind }).then(renderElbil));
  loadTeslaAccess();
  const rowOf = (car, day) => ({ time: document.querySelector(`.sch-t[data-car="${car}"][data-day="${day}"]`).value,
    soc: parseInt(document.querySelector(`.sch-s[data-car="${car}"][data-day="${day}"]`).value, 10),
    enabled: document.querySelector(`.sch-en[data-car="${car}"][data-day="${day}"]`).checked });
  document.querySelectorAll(".sch-save").forEach(b => b.onclick = async () => {        // alla sju dagarna (#142)
    const car = b.dataset.car;
    try { for (let day = 0; day < 7; day++) await postJSON("api/schedule", { car, day, ...rowOf(car, day) }); toast("Schemat sparat för hela veckan"); }
    catch (e) { toast(e.message); }
    renderElbil();
  });
  document.querySelectorAll(".sch-all").forEach(b => b.onclick = () => {
    const car = b.dataset.car;
    postAction("api/schedule", { car, days: [0, 1, 2, 3, 4, 5, 6], ...rowOf(car, 0) }, "Måndagens schema gäller nu alla dagar").then(renderElbil);
  });
  if (d) api("api/ev-cost").then((ec) => {                // laddat idag/veckan/månaden och vad det kostade
    const g = document.querySelector("#main .grid"), html = ec && ec.ok && window.EWJournal ? EWJournal.evCostHtml(ec, { unit: moneyUnit() }) : "";
    if (g && html && currentPage === "elbil" && !document.getElementById("evcost")) g.insertAdjacentHTML("afterend", `<div class="card" id="evcost" style="margin-bottom:16px">${html}</div>`);
  }).catch(() => {});
}

// Lås/luckor - eget omverifieringssteg (samma princip som ewapp: lösenordet igen, 10 min)
// innan själva kommandot går igenom. Se webdashboard/app.py:s /api/secure + /api/tesla/access.
async function loadTeslaAccess() {
  const box = document.getElementById("tesla-access");
  if (!box) return;
  let d;
  try { d = await api("api/tesla/access-state"); } catch { return; }
  const a = d.access;
  if (!a) return;
  box.innerHTML = `<div class="card">
    <div style="font-size:1.05rem;font-weight:700">🔒 Tesla – lås &amp; luckor</div>
    <div class="note" style="margin-top:4px">Bilen är ${a.locked ? "<b>låst</b>" : "<b style='color:var(--warn,#e8973a)'>upplåst</b>"}. Upplåsning och luckor kräver lösenordet igen (gäller i 10 min).</div>
    <div class="seg" style="margin-top:10px;flex-wrap:wrap">
      <button data-access="${a.locked ? "unlock" : "lock"}">${a.locked ? "Lås upp" : "Lås"}</button>
      <button data-access="trunk">${a.trunk ? "Stäng baklucka" : "Öppna baklucka"}</button>
      <button data-access="frunk">${a.frunk ? "Stäng framlucka" : "Öppna framlucka"}</button>
    </div>
  </div>`;
  box.querySelectorAll("[data-access]").forEach(b => b.onclick = () => teslaAccess(b.dataset.access));
}

async function teslaAccess(what) {
  try {
    const d = await api("api/tesla/access", { method: "POST", body: JSON.stringify({ what }) });
    toast(d.msg || "Klart");
    loadTeslaAccess();
  } catch (e) {
    if (e.message !== "secure") { toast("⚠️ " + e.message); return; }
    const pw = prompt("För din säkerhet krävs lösenordet igen för att låsa upp bilen eller öppna luckor:");
    if (!pw) return;
    try {
      await api("api/secure", { method: "POST", body: JSON.stringify({ password: pw }) });
    } catch (e2) { toast("⚠️ " + e2.message); return; }
    teslaAccess(what);
  }
}

async function renderSolceller() {
  const d = await loadPage("api/solar", (d) => `
    <div class="grid" style="margin-bottom:16px">
      ${statTile("☀️ PV-effekt", fmt(d.pv_power_w != null ? d.pv_power_w / 1000 : null, 2, " kW"))}
      ${statTile("🔆 Idag", fmt(d.solar_today_kwh, 1, " kWh"))}
      ${statTile("📈 Prognos nu", fmt(d.solar_forecast_w != null ? d.solar_forecast_w / 1000 : null, 2, " kW"))}
      ${statTile("🚫 Exportgräns", d.solar_limit_pct != null ? d.solar_limit_pct.toFixed(0) + " %" : "Ingen", d.ai_limit ? "automatiken begränsar (minuspris)" : "")}
    </div>
    ${d.battery_soc != null ? `<div class="card" style="margin-bottom:16px">
      <h2>🔋 Husbatteri</h2>
      ${barRow("Laddning", d.battery_soc, d.battery_soc.toFixed(0) + "%")}
      <div class="note" style="margin-top:6px">${fmt(d.battery_power_w, 0, " W")} ${d.battery_power_w > 0 ? "(laddar)" : d.battery_power_w < 0 ? "(laddar ur)" : ""}</div>
    </div>` : ""}
    <div class="card" style="margin-bottom:16px">
      <div class="togglerow" style="align-items:flex-start;gap:14px"><div>
        <h2 style="margin:0">🤖 Automatisk exportstyrning</h2>
        <div style="margin-top:6px;font-weight:600">${!d.auto_export ? "Av – du styr exportgränsen själv" : d.ai_limit ? "Aktiv nu: minuspris, solelen används hemma i stället för att säljas" : "På – väntar på minuspris (exporten är fri)"}</div></div>
        <label class="switch" style="flex:0 0 auto"><input type="checkbox" id="solarauto" ${d.auto_export ? "checked" : ""}><span class="slider"></span></label></div>
      <div class="note" style="margin-top:10px;line-height:1.5"><b>Vad den gör:</b> när elpriset blir negativt får du betala för att sälja.
        Då sänker EnergyWizard växelriktarens exportgräns steg för steg så att nästan ingenting går ut på nätet, och huset använder solen själv.
        Vid minuspris laddas också elbilen och spabadet gärna med den gratis elen. När priset blir positivt igen släpps gränsen till 100 %.</div>
      <div class="note" style="margin-top:8px;line-height:1.5"><b>Det här kan du göra:</b> låta automatiken sköta allt (rekommenderas),
        eller stänga av den och sätta en egen gräns nedan, t.ex. om elnätsbolaget kräver en exportgräns.</div>
      <div class="togglerow" style="margin-top:10px"><span>Avisera när exporten begränsas</span><label class="switch"><input type="checkbox" id="solarnotify" ${d.notify ? "checked" : ""}><span class="slider"></span></label></div>
    </div>
    <div class="card${d.ai_limit ? " row-disabled" : ""}" style="margin-bottom:16px">
      <h2>🎚️ Manuell exportgräns${d.ai_limit ? " · automatiken styr just nu" : ""}</h2>
      <div class="note">${d.auto_export ? "Gäller tills nästa minuspris, då tar automatiken över." : "Ligger kvar tills du ändrar den."}</div>
      <div class="numfield" style="margin-top:8px"><input type="range" id="solarlimit" min="0" max="100" step="5" value="${d.solar_limit_pct != null ? d.solar_limit_pct : 100}"><span id="solarlimitval" style="min-width:48px;text-align:right;font-weight:700">${d.solar_limit_pct != null ? d.solar_limit_pct.toFixed(0) : 100} %</span></div>
      <button class="icobtn" id="setsolarlimitbtn" style="margin-top:10px">Sätt gräns</button>
    </div>
    <div class="card" id="solarforecastsettings" style="margin-bottom:16px"><h2>📈 Källa för solprognosen</h2><div class="note">Läser inställningarna för solprognosen…</div></div>
    <div class="card"><h2>Elpris</h2><div class="note">Styr när exportbegränsningen slår till (minuspris)</div><div id="solarpricechart" style="height:220px;margin-top:10px"></div></div>`);
  if (d && d.price_24h) lineChart("solarpricechart", d.price_24h, { step: "end" });
  if (d) {
    renderSolarForecastSettings();
    const rangeEl = document.getElementById("solarlimit"), valEl = document.getElementById("solarlimitval");
    rangeEl.oninput = () => valEl.textContent = rangeEl.value + " %";
    document.getElementById("setsolarlimitbtn").onclick = () => postAction("api/energy-action/limit", { value: parseInt(rangeEl.value, 10) }).then(renderSolceller);
    document.getElementById("solarauto").onchange = (e) => postAction("api/energy-action/auto", { value: e.target.checked }).then(renderSolceller);
    document.getElementById("solarnotify").onchange = (e) => postAction("api/energy-action/notify", { value: e.target.checked });
  }
}

async function renderSolarForecastSettings() {
  const root = document.getElementById("solarforecastsettings");
  if (!root) return;
  try {
    const d = await api("api/solar-forecast-settings");
    if (!root.isConnected) return;
    const statuses = {disabled: "Husets egen prognos används", ready: "Solcast-data finns tillgängliga",
      partial: "Delvis Solcast-data; husets prognos används där data saknas",
      unavailable: "Solcast-data saknas eller är för gamla; husets prognos används",
      conflict: "Överlappande prognoser stämmer inte överens; husets prognos används"};
    const candidates = new Map(d.candidates.map(c => [c.entity, c.name]));
    d.entities.forEach(e => { if (!candidates.has(e)) candidates.set(e, e); });
    root.innerHTML = `<h2>📈 Källa för solprognosen</h2>
      <label for="solarforecastsource">Prognoskälla</label>
      <select id="solarforecastsource"><option value="internal">Husets egen prognos</option><option value="solcast_ha">Solcast via Home Assistant</option></select>
      <div class="note" style="margin-top:8px">${statuses[d.status] || statuses.unavailable}</div>
      <div class="note" style="margin-top:8px">Välj de sammanlagda dygnssensorerna för idag, imorgon och kommande dagar. Välj inte både totalsensorer och enskilda takytor.</div>
      <div id="solarforecastentities" style="margin-top:8px;display:grid;gap:8px">
        ${[...candidates].map(([entity, name]) => `<label><input type="checkbox" value="${esc(entity)}" ${d.entities.includes(entity) ? "checked" : ""}> <span data-noi18n>${esc(name)} <small>${esc(entity)}</small></span></label>`).join("") || `<div class="note">Inga detaljerade Solcast-sensorer hittades i Home Assistant.</div>`}
      </div>
      <button class="icobtn" id="savesolarforecast" style="margin-top:12px">Spara prognoskälla</button>
      <details style="margin-top:14px" ${!candidates.size ? "open" : ""}><summary>Så ställer du in Solcast</summary>
        <ol class="note" style="line-height:1.6">
          <li>Skapa ett Solcast-konto och konfigurera dina takytor, panelernas effekt, riktning och lutning.</li>
          <li>Installera Solcast PV Solar Forecast i Home Assistant via HACS och lägg till integrationen under Inställningar → Enheter och tjänster.</li>
          <li>Ange Solcast-nyckeln i Home Assistant. Nyckeln ska inte anges i EnergyWizard.</li>
          <li>Aktivera detaljerade prognosattribut i integrationens alternativ och kontrollera att dygnssensorerna har detailedForecast eller detailedHourly.</li>
          <li>Låt HA-integrationen sköta uppdateringar och API-gränser. EnergyWizard läser bara data som redan finns i Home Assistant.</li>
          <li>Välj Solcast via Home Assistant ovan, markera dygnssensorerna och spara.</li>
        </ol>
        <a href="https://github.com/BJReplay/ha-solcast-solar#installation" target="_blank" rel="noopener">Installationsguide för Solcast-integrationen</a>
        <span> · </span><a href="https://hacs.xyz/docs/use/" target="_blank" rel="noopener">Kom igång med HACS</a>
        <div class="note" style="margin-top:8px">Om data saknas, är äldre än 36 timmar eller inte täcker en tidsperiod används husets befintliga prognos för den perioden. Uppmätt solel påverkas inte.</div>
      </details>`;
    const source = root.querySelector("#solarforecastsource");
    source.value = d.source;
    const refresh = () => root.querySelectorAll('input[type="checkbox"]').forEach(el => { el.disabled = source.value !== "solcast_ha"; });
    source.onchange = refresh;
    refresh();
    root.querySelector("#savesolarforecast").onclick = async () => {
      const button = root.querySelector("#savesolarforecast");
      button.disabled = true;
      try {
        await postJSON("api/solar-forecast-settings", {source: source.value,
          entities: [...root.querySelectorAll('input[type="checkbox"]:checked')].map(el => el.value)});
        toast("Prognoskällan är sparad");
        await renderSolarForecastSettings();
      } catch (e) { toast(e.message); button.disabled = false; }
    };
  } catch (e) {
    if (root.isConnected) root.innerHTML = `<h2>📈 Källa för solprognosen</h2><div class="note">${esc(e.message)}</div>`;
  }
}

let econPeriod = "today";
async function renderEkonomi() {
  const d = await loadPage("api/economy", (d) => {
    const m = d.money[econPeriod], t = d.timing[econPeriod] || {}, sym = d.symbol || "kr";
    const money = (v) => v == null ? "–" : `${v.toFixed(v >= 100 || v <= -100 ? 0 : 2).replace(".", ",")} ${sym}`;
    const chip = (k, label) => `<button class="icobtn" data-econ="${k}"${k === econPeriod ? ` style="border-color:var(--acc);color:var(--acc)"` : ""}>${label}</button>`;
    const label = { today: "idag", week: "senaste 7 dagarna", month: "den här månaden" }[econPeriod];
    return `
    <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px">${chip("today", "Idag")}${chip("week", "7 dagar")}${chip("month", "Månad")}</div>
    <div class="grid" style="margin-bottom:16px">
      ${statTile("🧾 Köpt el", money(m.cost), `${fmt(m.bought_kwh, 1, " kWh")}${m.avg_paid != null ? " · snitt " + m.avg_paid.toFixed(2).replace(".", ",") + " " + sym + "/kWh" : ""}`)}
      ${statTile("☀️ Såld el", money(m.income), fmt(m.sold_kwh, 1, " kWh"))}
      ${statTile("💰 Netto", money(m.net), "köpt minus sålt")}
      ${statTile("🎯 Sparat genom tajmning", t.saved_kr != null ? (t.saved_kr >= 0 ? "+" : "") + money(t.saved_kr) : "–", t.pct != null ? `${t.pct.toFixed(0)} % billigare än dygnets snitt` : "")}
    </div>
    <div class="card" style="margin-bottom:16px"><h2>💸 Kostnad per dag</h2>
      <div class="note">Köpt el inklusive moms, nätavgift och skatt, minus såld el. Senaste 31 dagarna.</div>
      <div id="econcostbars" style="height:220px;margin-top:10px"></div></div>
    <div class="card" style="margin-bottom:16px"><h2>📊 Sparat per dag</h2><div class="note">Jämfört med ett vanligt hushåll utan styrning, inkl. moms. Grönt = billigare, rött = dyrare.</div><div id="econsavingsbars" style="height:220px;margin-top:10px"></div></div>
    <div class="grid" style="margin-bottom:16px">
      ${statTile("💸 Elpris just nu", fmtKrOre(d.price) + "/kWh", "spotpris")}
      ${statTile("📉 Lägst idag", fmtKrOre(d.price_min) + "/kWh")}
      ${statTile("📊 Snitt idag", fmtKrOre(d.price_avg) + "/kWh")}
      ${statTile("📈 Högst idag", fmtKrOre(d.price_max) + "/kWh")}
    </div>
    <div class="card"><h2>Elpris senaste dygnet</h2><div id="econpricechart" style="height:240px;margin-top:10px"></div></div>
    <div class="note" style="margin-top:10px">Beloppen räknas minut för minut med dina inställningar under Inställningar → Elpris och avgifter (${esc(label)}).</div>`;
  });
  if (!d) return;
  document.querySelectorAll("[data-econ]").forEach((b) => b.onclick = () => { econPeriod = b.dataset.econ; renderEkonomi(); });
  if (d.price_24h) lineChart("econpricechart", d.price_24h, { step: "end" });
  costBars("econcostbars", d.money_days || [], d.symbol || "kr");
  api("api/savings").then((sv) => { if (sv.ok) savingsBars("econsavingsbars", sv.days, 220); }).catch(() => {});
}

// Fasström i A mot huvudsäkringen: full stapel = 150 % av säkringen, gul från 80 %, röd över säkringen (#130)
function phaseBar(name, amps, fuse) {
  if (amps == null) return barRow(name, 0, "–");
  const color = amps > fuse ? "#e5484d" : amps > fuse * 0.8 ? "#f5a524" : null;
  return barRow(name, amps / (fuse * 1.5) * 100, fmt(amps, 1, " A"), color);
}

// ---------- Logg: allt installationen läst, beslutat, skickat och fått för fel (smartbox/ew_journal.py) ----------
let loggF = { hours: 6, lvl: "", src: "", q: "" };
let loggTimer = null;                 // #154: Live-uppdatering medan Logg-fliken är öppen
const loggLive = () => { try { return localStorage.getItem("ewLoggLive") !== "0"; } catch (e) { return true; } };
const LVL_COL = { fel: "var(--bad, #ef4444)", varning: "var(--warn, #f59e0b)", notis: "#a78bfa", info: "var(--mut)" };
async function renderLogg() {
  const main = document.getElementById("main");
  const sel = (id, opts, cur) => `<select id="${id}">${opts.map(([v, t]) => `<option value="${v}"${String(cur) === String(v) ? " selected" : ""}>${t}</option>`).join("")}</select>`;
  main.innerHTML = `<div class="card" style="margin-bottom:16px">
      <h2>📜 Logg</h2>
      <div class="note">Allt EnergyWizard läser in, bestämmer (med orsak), skickar till dina enheter, aviserar och får för fel - från motorn, appen och webben. Sparas i ditt hus i två veckor och lämnar det aldrig av sig själv.</div>
      <div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:12px;align-items:center">
        ${sel("lgh", [[1, "Senaste timmen"], [6, "6 timmar"], [24, "Dygnet"], [72, "3 dygn"], [336, "14 dygn"]], loggF.hours)}
        ${sel("lgl", [["", "Alla nivåer"], ["fel", "Fel"], ["varning", "Varningar"], ["notis", "Notiser"], ["info", "Info"]], loggF.lvl)}
        ${sel("lgs", [["", "Alla delar"], ["motor", "Motorn"], ["app", "Appen"], ["webb", "Webben"]], loggF.src)}
        <input id="lgq" type="search" placeholder="Sök (t.ex. batteri, Easee, ❌)" value="${esc(loggF.q)}" style="flex:1 1 180px;min-width:0">
        <label style="display:flex;gap:6px;align-items:center;font-size:.85rem;white-space:nowrap"><input type="checkbox" id="lglive"${loggLive() ? " checked" : ""}> Live (10 s)</label>
        <button class="icobtn" id="lgdl">⬇️ Ladda ner (2 dygn)</button>
      </div>
      <div class="note" id="lgts" style="margin-top:6px;font-size:.8rem"></div></div>
    <div class="card"><div id="lgrows" class="note">Laddar…</div></div>`;
  const load = async () => {
    loggF = { hours: +document.getElementById("lgh").value, lvl: document.getElementById("lgl").value, src: document.getElementById("lgs").value, q: document.getElementById("lgq").value };
    const qs = new URLSearchParams({ hours: loggF.hours, lvl: loggF.lvl, src: loggF.src, q: loggF.q, limit: 800 });
    let d; try { d = await api("api/journal?" + qs); } catch (e) { document.getElementById("lgrows").textContent = e.message; return; }
    const box = document.getElementById("lgrows");
    if (!box) return;                                  // fliken lämnad medan hämtningen pågick
    const ts = document.getElementById("lgts"); if (ts) ts.textContent = "Uppdaterad " + new Date().toLocaleTimeString("sv-SE");
    if (!d.rows.length) { box.innerHTML = `<div class="note">Inget i loggen för det urvalet.</div>`; return; }
    box.classList.remove("note");
    box.innerHTML = d.rows.map((r) => `<div style="display:flex;flex-wrap:wrap;column-gap:10px;padding:6px 0;border-top:1px solid var(--line);font-size:.85rem">
        <span style="flex:0 0 auto;font-variant-numeric:tabular-nums;color:var(--mut)">${esc(new Date(r.ts).toLocaleString("sv-SE", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" }))}</span>
        <span style="flex:0 0 auto;color:${LVL_COL[r.lvl] || "var(--mut)"};font-weight:600">${esc(r.lvl)}</span>
        <span style="flex:0 0 auto;color:var(--mut)">${esc(r.src)} · ${esc(r.mod)}</span>
        <span style="flex:1 1 100%;min-width:0;white-space:pre-wrap;overflow-wrap:anywhere">${esc(r.msg)}</span></div>`).join("")
      + (d.rows.length >= 800 ? `<div class="note" style="margin-top:8px">Visar de 800 senaste - snäva in med sök eller nivå.</div>` : "");
  };
  ["lgh", "lgl", "lgs"].forEach((id) => document.getElementById(id).onchange = load);
  let t = null; document.getElementById("lgq").oninput = () => { clearTimeout(t); t = setTimeout(load, 350); };
  document.getElementById("lgdl").onclick = () => { location.href = "api/journal/download?days=2"; };
  // Live: hämta om var 10:e sekund så länge Logg-fliken är öppen, webbläsarfliken syns och Live är ikryssat
  document.getElementById("lglive").onchange = (e) => { try { localStorage.setItem("ewLoggLive", e.target.checked ? "1" : "0"); } catch (_) {} if (e.target.checked) load(); };
  clearInterval(loggTimer);
  loggTimer = setInterval(() => {
    const live = document.getElementById("lglive");
    if (currentPage !== "logg" || !live) { clearInterval(loggTimer); return; }
    if (live.checked && !document.hidden) load();
  }, 10000);
  load();
}

// Effektavgift efter månadens högsta timmar (#141, Norges effektledd m.fl.)
async function mountCapacityTariff(slotId) {
  const slot = document.getElementById(slotId);
  if (!slot) return;
  let d; try { d = await api("api/capacity-tariff"); } catch (e) { return; }
  if (!d.ok) return;
  const st = d.status || {}, kw = (v) => v == null ? "–" : String(Math.round(v * 10) / 10).replace(".", ",") + " kW";
  slot.innerHTML = `<div class="card" style="margin-top:16px">
    <h2>📊 Effektavgift efter högsta timmar</h2>
    <div class="note">För nätbolag som tar betalt efter snittet av månadens högsta timmar i trappsteg (Norges effektledd, vissa svenska nätbolag). Då ersätter den här den fasta effektgränsen: varje timme får gå så högt som möjligt utan att snittet går upp ett steg.</div>
    <div class="togglerow" style="margin-top:8px"><span>Använd effektavgift efter högsta timmar</span><label class="switch"><input type="checkbox" id="ctOn" ${d.enabled ? "checked" : ""}><span class="slider"></span></label></div>
    <div class="numfield" style="margin-top:8px;flex-wrap:wrap;gap:8px">Antal timmar <input type="number" id="ctN" min="1" max="10" value="${d.top_n}" style="width:64px">
      <label style="display:flex;align-items:center;gap:6px"><input type="checkbox" id="ctDist" ${d.distinct_days ? "checked" : ""}> på olika dygn</label></div>
    <div class="numfield" style="margin-top:8px">Trappsteg (kW) <input type="text" id="ctSteps" value="${esc((d.steps || []).join(", "))}" style="flex:1;min-width:0"></div>
    <div class="numfield" style="margin-top:8px">Sikta på steget upp till <input type="number" id="ctTarget" step="1" value="${d.target_kw ?? ""}" style="width:80px"> kW <span class="note">(tomt = det steg du redan är i)</span></div>
    <button class="icobtn" id="ctSave" style="margin-top:10px">Spara</button>
    <div class="note" style="margin-top:12px">Just nu: snitt ${kw(st.avg_kw)} (steg ${kw(st.step && st.step[0])}–${kw(st.step && st.step[1])}) · gräns för den här timmen <b>${kw(st.limit_kw)}</b>${st.free_below_kw ? ` · under ${kw(st.free_below_kw)} påverkar inte avgiften alls` : ""}</div>
    <div class="note">Månadens högsta: ${(st.top_days || []).map(([dd, k]) => `${esc(dd.slice(5))} ${kw(k)}`).join(" · ") || "–"}</div>
  </div>`;
  document.getElementById("ctSave").onclick = async () => {
    try {
      await postJSON("api/capacity-tariff", { enabled: document.getElementById("ctOn").checked, top_n: +document.getElementById("ctN").value,
        distinct_days: document.getElementById("ctDist").checked, steps: document.getElementById("ctSteps").value.split(/[;,\s]+/).filter(Boolean),
        target_kw: document.getElementById("ctTarget").value });
      toast("Sparat"); mountCapacityTariff(slotId);
    } catch (e) { toast(e.message); }
  };
}

async function renderElforbrukning() {
  const d = await loadPage("api/consumption", (d) => {
    const b = d.breakdown;
    const maxW = b ? Math.max(b.total_w || 0, 1) : 1;
    const fuse = d.fuse_size_a || 25;
    return `
    <div class="grid" style="margin-bottom:16px">
      ${statTile("⚡ Just nu", fmt(d.avg_w_tot != null ? d.avg_w_tot / 1000 : null, 2, " kW"))}
      ${statTile("🏠 Hus (bas)", fmt(d.house_consumption_w != null ? d.house_consumption_w / 1000 : null, 2, " kW"))}
      ${statTile("📐 Prognos baslast", fmt(d.predicted_base_load_kw, 2, " kW"))}
      ${statTile("🛡️ Effektvakt", d.peak_shaving_active ? badge("warn", "griper in") : badge("on", "normal läge"))}
    </div>
    <div class="card" style="margin-bottom:16px">
      <h2>🔌 Faser <span class="muted" style="font-weight:400;font-size:.8em">(huvudsäkring ${fmt(fuse, 0, " A")}, full stapel = 150 %)</span></h2>
      ${["l1", "l2", "l3"].map((ph) => phaseBar(ph.toUpperCase(), d["avg_w_" + ph], fuse)).join("")}
    </div>
    ${b ? `<div class="card">
      <h2>📦 Vad drar strömmen</h2>
      ${d.has_ev === false ? "" : barRow("🚗 Elbil", b.ev_w / maxW * 100, fmt(b.ev_w, 0, " W"))}
      ${d.has_heat === false ? "" : barRow("♨️ Värmepump", b.pump_w / maxW * 100, fmt(b.pump_w, 0, " W"))}
      ${d.has_spa === false ? "" : barRow("🛁 Spabad", b.spa_w / maxW * 100, fmt(b.spa_w, 0, " W"))}
      ${(b.extra || []).map((x) => barRow("🔌 " + esc(x.name), x.w / maxW * 100, fmt(x.w, 0, " W"))).join("")}
      ${barRow("❓ Oförklarat", b.unexplained_w / maxW * 100, fmt(b.unexplained_w, 0, " W"))}
      ${barRow("Σ Totalt", 100, fmt(b.total_w, 0, " W"))}
    </div>` : `<div class="note">Ingen uppdelning loggad än.</div>`}
    <div class="card" style="margin-top:16px">
      <h2>🛡️ Effektvakt (peak shaving)</h2>
      <div class="togglerow"><span>Effektvakt på</span><label class="switch"><input type="checkbox" id="peakenabled" ${d.peak_shaving_enabled ? "checked" : ""}><span class="slider"></span></label></div>
      <div class="numfield${d.peak_shaving_enabled ? "" : " row-disabled"}" style="margin-top:8px" id="peaklimitrow">Gräns: <input type="number" id="peaklimit" step="0.5" min="1" value="${d.power_limit_kw != null ? d.power_limit_kw : ""}"> kW <button class="icobtn" id="peaklimitbtn">Spara</button></div>
    </div>
    <div id="captariffslot"></div>`;
  });
  if (d) {
    document.getElementById("peakenabled").onchange = (e) => postAction("api/settings-action", { key: "peak_shaving_enabled", value: e.target.checked }).then(renderElforbrukning);
    const btn = document.getElementById("peaklimitbtn");
    if (btn) btn.onclick = () => postAction("api/settings-action", { key: "power_limit_kw", value: parseFloat(document.getElementById("peaklimit").value) }).then(renderElforbrukning);
    mountCapacityTariff("captariffslot");
  }
}

async function renderSpabad() {
  const d = await loadPage("api/spa", (d) => `
    <div class="grid" style="margin-bottom:16px">
      ${statTile("🛁 Temperatur", fmt(d.temp, 1, "°C"))}
      ${statTile("🎯 Mål", fmt(d.target, 1, "°C"))}
      ${statTile("🔥 Värmare", d.heater_running ? badge("on", "värmer") : badge("off", "av"))}
      ${statTile("⚡ Effekt", fmt(d.power_w, 0, " W"))}
    </div>
    <div class="card" style="margin-bottom:16px">
      <h2>🎛️ Styrning</h2>
      <div class="togglerow"><span>Tvångsvärme (värm nu, oavsett pris)</span><label class="switch"><input type="checkbox" id="spaforce" ${d.force_heat ? "checked" : ""}><span class="slider"></span></label></div>
      <div class="togglerow"><span>Eco-läge (håll nere temperaturen)</span><label class="switch"><input type="checkbox" id="spaeco" ${d.eco ? "checked" : ""}><span class="slider"></span></label></div>
      <button class="icobtn" id="spaautobtn" style="margin-top:10px">Auto (följ schemat)</button>
    </div>
    <div class="grid" style="margin-bottom:16px">
      <div class="card">
        <h2>🌡️ Temperaturer</h2>
        <div class="note">Som värmepumpens: vad motorn håller badet på i de olika lägena.</div>
        <div class="numfield" style="margin-top:10px;flex-wrap:wrap;gap:10px">
          <label>Normal <input type="number" id="spanormal" step="0.5" min="20" max="40" value="${d.normal_temp ?? ""}"> °C</label>
          <label>Max (minuspris/sol) <input type="number" id="spamax" step="0.5" min="30" max="40" value="${d.max_temp ?? ""}"> °C</label>
          <label>Eco-golv <input type="number" id="spalow" step="0.5" min="10" max="30" value="${d.low_temp ?? ""}"> °C</label>
        </div>
        <div class="note" style="margin-top:6px">Max är aldrig över 40 °C - motorns säkerhetsgräns.</div>
        <button class="icobtn" id="spatempsave" style="margin-top:10px">Spara temperaturer</button>
      </div>
      <div class="card">
        <h2>⏰ Klart till</h2>
        <div class="note">${d.ready_enabled && d.ready_at ? `Aktivt: ${d.ready_at.replace("T", " ")} · ${fmt(d.ready_temp, 1, "°C")}. Motorn värmer på de billigaste timmarna fram till dess.` : "Av - badet följer sitt vanliga läge."}</div>
        <div class="numfield" style="margin-top:10px;flex-wrap:wrap;gap:10px">
          <input type="datetime-local" id="spareadyat" value="${d.ready_at || ""}">
          <input type="number" id="spareadytemp" step="0.5" min="20" max="40" value="${d.ready_temp ?? 38}"> °C
        </div>
        <div style="display:flex;gap:8px;margin-top:10px"><button class="icobtn" id="spareadysave">Spara</button>${d.ready_enabled ? `<button class="icobtn" id="spareadyoff">Stäng av</button>` : ""}</div>
      </div>
    </div>
    <div class="card" style="margin-bottom:16px"><h2>🗓️ Badtider</h2>
      <div class="note">När brukar ni bada? Utanför badtiderna får badet svalna till eco-golvet (${fmt(d.low_temp, 0, " °C")}) och värms upp i tid före nästa badtid, på de billigaste timmarna. Inga badtider = badet hålls varmt som idag.</div>
      <div style="display:grid;gap:6px;margin-top:10px">${(d.bath_windows || []).map((w, i) => `<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
        <label style="display:flex;align-items:center;gap:8px;width:118px"><input type="checkbox" class="bathon" data-i="${i}"${w.on ? " checked" : ""}> ${["Måndag", "Tisdag", "Onsdag", "Torsdag", "Fredag", "Lördag", "Söndag"][i]}</label>
        <input type="time" class="bathfrom" data-i="${i}" value="${w.from}" style="width:110px"> – <input type="time" class="bathto" data-i="${i}" value="${w.to}" style="width:110px"></div>`).join("")}</div>
      <button class="icobtn" id="bathsave" style="margin-top:10px">Spara badtider</button></div>
    <div class="card" style="margin-bottom:16px"><h2>📈 Senaste dygnet</h2><div class="note">Temperatur mot mål. Skuggat = värmaren gick.</div><div id="spachart" style="height:240px;margin-top:10px"></div></div>
    <div class="card"><h2>📡 Trådlös anslutning</h2><div class="note">Signal: ${fmt(d.signal_pct, 0, "%")} · Kanal: ${d.rf_channel != null ? d.rf_channel : "–"}</div></div>`);
  if (d) {
    document.getElementById("bathsave").onclick = async () => {
      const q = (cls, i) => document.querySelector(`.${cls}[data-i="${i}"]`);
      const windows = [0, 1, 2, 3, 4, 5, 6].map((i) => ({ on: q("bathon", i).checked, from: q("bathfrom", i).value, to: q("bathto", i).value }));
      try { const j = await postJSON("api/spa-bath", { windows }); toast(j.message || "Sparat"); } catch (e) { toast(e.message); }
    };
    document.getElementById("spatempsave").onclick = async () => {
      for (const [id, key] of [["spanormal", "spa_normal_temp"], ["spamax", "spa_max_temp"], ["spalow", "spa_low_temp"]]) {
        const v = parseFloat(document.getElementById(id).value);
        if (!isNaN(v)) await postAction("api/settings-action", { key, value: v });
      }
      renderSpabad();
    };
    document.getElementById("spareadysave").onclick = () => {
      const when = document.getElementById("spareadyat").value;
      if (!when) return;
      postAction("api/home-action/spa_ready", { when, temp: parseFloat(document.getElementById("spareadytemp").value) }).then(renderSpabad);
    };
    const off = document.getElementById("spareadyoff");
    if (off) off.onclick = () => postAction("api/home-action/spa_ready", { off: true }).then(renderSpabad);
    if (d.history && d.history.length) {
      const el = document.getElementById("spachart"), chart = echarts.init(el, null, { renderer: "svg" }), mut = "#93a0b8";
      chart.setOption({
        grid: { left: 46, right: 16, top: 24, bottom: 30 }, legend: { top: 0, textStyle: { color: mut } }, tooltip: { trigger: "axis" },
        xAxis: { type: "category", data: d.history.map((h) => h.t.slice(11, 16)), axisLabel: { color: mut, interval: 2 } },
        yAxis: { type: "value", scale: true, name: "°C", axisLabel: { color: mut }, splitLine: { lineStyle: { color: "rgba(148,163,184,.12)" } } },
        series: [
          { name: "Temperatur", type: "line", color: "#a78bfa", data: d.history.map((h) => h.temp), symbol: "none", smooth: true, lineStyle: { color: "#a78bfa", width: 2.5 },
            markArea: { silent: true, itemStyle: { color: "rgba(167,139,250,.12)" }, data: d.history.map((h, i) => h.heating > 0.2 ? [{ xAxis: i }, { xAxis: Math.min(i + 1, d.history.length - 1) }] : null).filter(Boolean) } },
          { name: "Mål", type: "line", color: "#93a0b8", step: "middle", data: d.history.map((h) => h.target), symbol: "none", lineStyle: { color: mut, type: "dashed" } },
        ],
      });
      new ResizeObserver(() => chart.resize()).observe(el);
    }
    document.getElementById("spaforce").onchange = (e) => postAction("api/home-action/spa_heat", { value: e.target.checked });
    document.getElementById("spaeco").onchange = (e) => postAction("api/home-action/spa_eco", { value: e.target.checked });
    document.getElementById("spaautobtn").onclick = () => postAction("api/home-action/spa_auto", {}).then(renderSpabad);
  }
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

// ---------- Historik (inspirerat av FTW:s History-vy, egen implementation) ----------
// Summor Idag/7 dagar/30 dagar + effekt över tid + senaste värden (smartbox/energy_history.py).
let histPeriod = "today", histRange = "24h";
try { histPeriod = localStorage.getItem("ew_hist_period") || "today"; histRange = localStorage.getItem("ew_hist_range") || "24h"; } catch (e) { /* privat läge */ }
const HIST_COL = { grid: "#e11d74", solar: "#b38b00", battery: "#0e7490", house: "#64748b" };

function kwhTile(label, v, sub, color) {
  return `<div class="stat" style="border-left-color:${color}"><div class="l" style="text-transform:none;font-size:.85rem">${label}</div><div class="v">${v != null ? (v >= 100 ? v.toFixed(0) : v.toFixed(1)) : "–"} <span style="font-size:.9rem;font-weight:600;color:var(--mut)">kWh</span></div><div class="l" style="text-transform:none">${sub}</div></div>`;
}
function fmtW(w) { return w == null ? "–" : Math.abs(w) >= 1000 ? `${(w / 1000).toFixed(1)} kW` : `${Math.round(w)} W`; }

function historyHtml(d) {
  const t = d.totals[histPeriod];
  const seg = (id, cur, opts) => `<div class="seg" id="${id}">${opts.map(([k, l]) => `<button data-v="${k}" class="${k === cur ? "on" : ""}">${l}</button>`).join("")}</div>`;
  const tiles = t ? [
    kwhTile("Förbrukat hemma", t.used_kwh, "allt huset drog", HIST_COL.house),
    t.solar_kwh != null ? kwhTile("Solel", t.solar_kwh, "vad panelerna gav", HIST_COL.solar) : "",
    kwhTile("Köpt", t.bought_kwh, "från elnätet", HIST_COL.grid),
    kwhTile("Sålt", t.sold_kwh, "ut på elnätet", HIST_COL.grid),
    t.battery_in_kwh != null ? kwhTile("Batteri", t.battery_in_kwh, `in · ${t.battery_out_kwh.toFixed(1)} kWh ut`, HIST_COL.battery) : "",
  ].join("") : `<div class="note">Ingen mätdata för perioden än.</div>`;
  const L = d.latest || {};
  const latest = [["Nät", HIST_COL.grid, L.grid_w == null ? "–" : fmtW(Math.abs(L.grid_w)), L.grid_w == null ? "" : L.grid_w < -50 ? "säljer" : "köper"],
    ["Sol", HIST_COL.solar, fmtW(L.solar_w), "producerar"],
    ...(L.battery_w != null ? [["Batteri", HIST_COL.battery, fmtW(Math.abs(L.battery_w)), Math.abs(L.battery_w) < 30 ? "vilar" : L.battery_w > 0 ? "laddar" : "laddar ur"]] : []),
    ["Hus", HIST_COL.house, fmtW(L.house_w), "använder"]]
    .map(([n, c, v, s]) => `<div style="border-left:3px solid ${c};padding-left:10px"><div class="note" style="text-transform:uppercase;letter-spacing:.04em;font-size:.72rem">${n}</div><div style="font-size:1.25rem;font-weight:800">${v}</div><div class="note" style="font-size:.72rem;text-transform:uppercase">${s}</div></div>`).join("");
  return `
    <div class="card" style="margin-bottom:16px">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap"><h2 style="margin:0">⚡ Energi</h2>${seg("histperiod", histPeriod, [["today", "Idag"], ["7d", "7 dagar"], ["30d", "30 dagar"]])}</div>
      <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(170px,1fr));margin-top:12px">${tiles}</div>
      ${t && t.summary ? `<div class="note" style="margin-top:10px">${esc(t.summary)}</div>` : ""}
    </div>
    <div class="card" style="margin-bottom:16px">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap"><h2 style="margin:0">📈 Effekt över tid</h2>${seg("histrange", histRange, [["24h", "24 h"], ["7d", "7 d"], ["30d", "30 d"], ["1y", "1 år"]])}</div>
      <div id="histchart" style="height:300px;margin-top:10px"></div>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:12px;margin-top:12px">${latest}</div>
      <div class="note" style="margin-top:8px">Uppåt = in i huset (köpt), nedåt = ut (sålt, solproduktion). Senast mätt ${L.ts ? new Date(L.ts).toLocaleTimeString("sv-SE", { hour: "2-digit", minute: "2-digit" }) : "–"}.</div>
    </div>`;
}

function historyChart(sr) {
  const el = document.getElementById("histchart");
  if (!el || !sr || !sr.t.length) return;
  const chart = echarts.init(el, null, { renderer: "svg" });
  const fmtT = sr.range === "24h" ? (x) => x.slice(11, 16) : sr.range === "1y" ? (x) => x.slice(5, 10) : (x) => `${x.slice(8, 10)}/${x.slice(5, 7)} ${x.slice(11, 13)}`;
  const line = (name, data, color) => ({ name, type: "line", data, symbol: "none", connectNulls: false, lineStyle: { width: 2, color }, itemStyle: { color } });
  const series = [line("Nät", sr.grid_kw, HIST_COL.grid),
    line("Sol", sr.solar_kw.map((v) => (v == null ? null : -v)), HIST_COL.solar),
    line("Hus", sr.house_kw, HIST_COL.house)];
  if (sr.battery_kw.some((v) => v != null)) series.push(line("Batteri", sr.battery_kw, HIST_COL.battery));
  chart.setOption({
    grid: { left: 52, right: 16, top: 30, bottom: 36 },
    legend: { top: 0, textStyle: { color: "#93a0b8" } },
    tooltip: { trigger: "axis", valueFormatter: (v) => (v == null ? "–" : `${v.toFixed(2)} kW`) },
    xAxis: { type: "category", data: sr.t.map(fmtT), axisLabel: { color: "#93a0b8" }, axisLine: { lineStyle: { color: "#93a0b8" } } },
    yAxis: { type: "value", name: "kW", nameTextStyle: { color: "#93a0b8" }, axisLabel: { color: "#93a0b8" }, splitLine: { lineStyle: { color: "rgba(255,255,255,.08)" } } },
    series,
  });
  new ResizeObserver(() => chart.resize()).observe(el);
}

async function renderHistorik() {
  const main = document.getElementById("main");
  main.innerHTML = `<div class="placeholder">Laddar…</div>`;
  let d, log;
  try { [d, log] = await Promise.all([api("api/energyhistory?range=" + histRange), api("api/historylog").catch(() => null)]); }
  catch (e) { main.innerHTML = `<div class="placeholder">${esc(e.message)}</div>`; return; }
  const logHtml = log && log.ok ? `
    <div class="card">
      <h2>📜 Logg</h2>
      <div class="loglist">
        ${log.entries.length ? log.entries.map(e => `<div class="logrow"><div class="t">${new Date(e.ts).toLocaleString("sv-SE", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}</div><div>${e.user ? `<b>${esc(e.user)}:</b> ` : ""}${esc(e.text || "")}</div></div>`).join("") : `<div class="note">Inget loggat än.</div>`}
      </div>
    </div>` : "";
  let jBack = 1, jData = await api("api/control-journal?back=1").catch(() => null);
  const jHtml = () => window.EWJournal && jData && jData.ok ? `<div class="card" id="journalcard">${EWJournal.html(jData, { back: jBack })}</div>` : "";
  const jWire = () => main.querySelectorAll("#journalcard [data-jback]").forEach((b) => b.onclick = async () => {
    jBack = +b.dataset.jback; jData = await api("api/control-journal?back=" + jBack).catch(() => jData);
    const el = document.getElementById("journalcard"); if (el) { el.outerHTML = jHtml(); jWire(); }
  });
  const draw = () => {
    main.innerHTML = historyHtml(d) + jHtml() + logHtml;
    jWire();
    historyChart(d.series);
    main.querySelectorAll("#histperiod button").forEach((b) => b.onclick = () => { histPeriod = b.dataset.v; try { localStorage.setItem("ew_hist_period", histPeriod); } catch (e) {} draw(); });
    main.querySelectorAll("#histrange button").forEach((b) => b.onclick = async () => {
      histRange = b.dataset.v; try { localStorage.setItem("ew_hist_range", histRange); } catch (e) {}
      try { d = await api("api/energyhistory?range=" + histRange); } catch (e) { /* behåll förra */ }
      draw();
    });
  };
  if (!d.ok) { main.innerHTML = `<div class="placeholder">Ingen data än</div>` + logHtml; return; }
  draw();
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
  const nl = await api("api/notify-log?days=7").catch(() => null);      // skickade aviseringar med leveransstatus
  if (nl && nl.ok && window.EWJournal && currentPage === "aviseringar") document.getElementById("main").insertAdjacentHTML("beforeend", `<div class="card" id="notifylog">${EWJournal.notifyHtml(nl)}</div>`);
}

function esc(s) { return String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }

let _toastT = null;
function toast(msg) {
  const t = document.getElementById("toast");
  t.textContent = window.I18N ? I18N.tr(msg) : msg;
  t.classList.add("show");
  clearTimeout(_toastT);
  _toastT = setTimeout(() => t.classList.remove("show"), 3200);
}

// Skriv-knapparna proxas vidare till ewapp (se webdashboard/app.py:s _ewapp_proxy) -
// samma kommandon som mobilappens knappar, ingen egen hårdvarulogik här.
async function postAction(path, body, okMsg) {
  try {
    const d = await api(path, { method: "POST", body: JSON.stringify(body || {}) });
    toast(okMsg || d.msg || "Klart");
    return d;
  } catch (e) {
    toast("⚠️ " + e.message);
    throw e;
  }
}

async function api(path, opts) {
  const r = await fetch(path, { credentials: "same-origin", headers: { "Content-Type": "application/json" }, ...opts });
  if (r.status === 401) { showLogin(); throw new Error("not authed"); }
  if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.detail || e.error || r.statusText || `Servern svarade med fel ${r.status}`); }   // HTTP/2 (Ingress) har ingen statustext
  return r.json();
}

function showLogin() {
  hideSetup();
  mountLangSelect("loginlang", false);
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
  nav.innerHTML += `<a class="navitem sponsor" href="${SPONSOR_URL}" target="_blank" rel="noopener">❤️ Sponsra EnergyWizard</a>`;
  nav.querySelectorAll(".navitem[data-page]").forEach(b => b.onclick = () => openPage(b.dataset.page));
}

// ---------- Sponsring: länk överallt + en vänlig ruta en gång i månaden (kan stängas av) ----------
const SPONSOR_URL = "https://github.com/sponsors/murre87";
async function showSponsorBanner() {
  const el = document.getElementById("sponsorbanner");
  let st;
  try { st = await api("api/sponsor?lang=" + (window.I18N ? I18N.lang : "sv")); } catch (e) { return; }
  if (!st || !st.show) { el.hidden = true; return; }
  el.innerHTML = `<div class="sponsorcard" data-noi18n>
      <div style="font-size:1.6rem">❤️</div>
      <div class="txt"><b>${esc(st.title)}</b><div style="margin-top:6px">${esc(st.text)}</div>
        <div class="btns"><a class="go" href="${esc(st.url)}" target="_blank" rel="noopener">${esc(st.button)}</a>
        <button class="icobtn" id="sponsorlater">${I18N.lang === "sv" ? "Inte nu" : "Not now"}</button></div></div></div>`;
  el.hidden = false;
  const close = () => { el.hidden = true; api("api/sponsor/dismiss", { method: "POST" }).catch(() => {}); };
  document.getElementById("sponsorlater").onclick = close;
  el.querySelector("a.go").addEventListener("click", close);
}

const BAT_STYLES = {
  very_careful: ["Mycket försiktig", "Planerar för en dålig dag: mycket mindre sol och mer förbrukning än prognosen. Sparar mest i batteriet."],
  careful: ["Försiktig", "Räknar med lite mindre sol och lite mer förbrukning än prognosen."],
  balanced: ["Balanserad", "Planerar på prognosen och sparar en del i batteriet till senare. Standard."],
  bold: ["Djärv", "Planerar nära prognosen och använder batteriet mer."],
  very_bold: ["Mycket djärv", "Planerar på prognosen som den är. Tjänar mest när den stämmer och kostar mer när den slår fel."],
};
// Home Assistant via MQTT (smartbox/mqtt_bridge.py): broker + status. Bara ägaren ser kortet.
async function mountMqtt() {
  let d;
  try { d = await api("api/mqtt-settings"); } catch (e) { return; }
  const card = document.getElementById("mqttcard"), body = document.getElementById("mqttbody");
  if (!card || !d.ok) return;
  card.hidden = false;
  const st = d.status;
  const stat = !d.host ? "Av" : !st ? "Ansluter… (inom en minut)" : (st.ok ? "✅ " : "⚠️ ") + st.msg;
  const fld = (id, label, val, type, ph) => `<label style="display:flex;flex-direction:column;gap:4px;flex:1 1 150px;min-width:0"><span class="note">${label}</span>
      <input id="${id}" type="${type || "text"}" value="${esc(val ?? "")}" placeholder="${esc(ph || "")}" style="width:100%" autocomplete="off"></label>`;
  body.innerHTML = `<div style="display:flex;gap:10px;flex-wrap:wrap">
      ${fld("mqhost", "Broker (adress)", d.host, "text", d.suggested_host)}${fld("mqport", "Port", d.port, "number")}
      ${fld("mquser", "Användare", d.user)}${fld("mqpass", "Lösenord", "", "password", d.has_password ? "(sparat - lämna tomt)" : "")}</div>
    <div style="margin-top:8px;font-weight:600">Status: ${esc(stat)}</div>
    <button class="icobtn" id="mqsave" style="margin-top:8px">Spara</button>`;
  document.getElementById("mqsave").onclick = async () => {
    const v = (id) => document.getElementById(id).value;
    try { await postJSON("api/mqtt-settings", { host: v("mqhost"), port: v("mqport"), user: v("mquser"), password: v("mqpass") });
      toast(v("mqhost") ? "Sparat - EnergyWizard ansluter inom en minut" : "MQTT avstängt"); setTimeout(mountMqtt, 70000); mountMqtt(); }
    catch (e) { toast(e.message); }
  };
}

// Skuggläge (smartbox/shadow.py): brytare + vad EnergyWizard hade gjort.
async function mountShadow() {
  let d;
  try { d = await api("api/shadow"); } catch (e) { return; }
  const t = document.getElementById("shadowtoggle"), list = document.getElementById("shadowlist");
  if (!t) return;
  t.checked = d.active;
  t.disabled = d.forced_by_env;
  t.onchange = async () => {
    try { await postJSON("api/shadow", { active: t.checked }); toast(t.checked ? "Skuggläge på - EnergyWizard styr ingenting" : "Skuggläge av - EnergyWizard styr igen"); mountShadow(); }
    catch (e) { t.checked = !t.checked; toast(e.message); }
  };
  list.innerHTML = (d.forced_by_env ? `<div class="note">Påslaget med SHADOW_MODE i miljön.</div>` : "")
    + (d.actions.length ? `<div class="note" style="margin-bottom:6px">Hade gjort (senaste först):</div>` + d.actions.slice(0, 30).map((a) =>
      `<div style="display:flex;flex-wrap:wrap;column-gap:12px;padding:6px 0;border-top:1px solid var(--line)"><span class="note" style="min-width:120px">${esc(a.ts)}</span>
        <span style="flex:1 1 220px;min-width:0;overflow-wrap:anywhere"><b>${esc(a.what)}</b> <span class="note">${esc(a.detail || "")}</span></span></div>`).join("")
      : d.active ? `<div class="note">Inget ännu - åtgärder dyker upp här när EnergyWizard hade velat ändra något.</div>` : "");
}

// Elpris och avgifter per land (smartbox/nordpool.py cost_settings): land, elområde, moms, avgifter.
// #171: vänd tecknet på nätets och batteriets effekt (ew_settings; house_config.yaml går före om den anger det)
async function mountSignSettings() {
  let d; try { d = await api("api/sign-settings"); } catch (e) { return; }
  const card = document.getElementById("signcard"), body = document.getElementById("signbody");
  if (!card || !d || !d.ok) return;
  card.hidden = false;
  const row = (key, label, on, locked) => `<div class="togglerow" style="padding:6px 0;gap:12px"><span style="flex:1 1 auto;min-width:0">${label}${locked ? `<div class="note">Låst i house_config.yaml</div>` : ""}</span>
      <label class="switch" style="flex:none"><input type="checkbox" data-sign="${key}" ${on ? "checked" : ""} ${locked ? "disabled" : ""}><span class="slider"></span></label></div>`;
  body.innerHTML = row("grid", "Vänd tecknet på nätets effekt", d.grid, d.grid_locked) + (d.has_battery ? row("battery", "Vänd tecknet på batteriets effekt", d.battery, d.battery_locked) : "");
  body.querySelectorAll("[data-sign]").forEach((cb) => cb.onchange = async () => {
    try { await postJSON("api/sign-settings", { [cb.dataset.sign]: cb.checked }); toast("Sparat - syns i Översikt inom en minut"); }
    catch (e) { cb.checked = !cb.checked; toast(e.message); }
  });
}

async function mountPhoneSetting() {
  let d;
  try { d = await api("api/notify-target"); } catch (e) { return; }
  const card = document.getElementById("phonecard"), body = document.getElementById("phonebody");
  if (!card || !d) return;
  card.hidden = false;
  if (!d.ok) { body.innerHTML = `<div class="note">${esc(d.error || "")}</div>`; return; }
  if (d.env) { body.innerHTML = `<div class="note">Styrs av NOTIFY_TARGET i miljön: ${esc(d.env)}</div>`; return; }
  const opt = (v, label) => `<option value="${esc(v)}"${v === d.selected ? " selected" : ""}>${esc(label)}</option>`;
  const grp = (label, items) => items.length ? `<optgroup label="${label}">${items.join("")}</optgroup>` : "";
  body.innerHTML = `<select id="phonesel" style="width:100%"><option value="">Första telefonen i Home Assistant${d.phones[0] ? " (" + esc(d.phones[0]) + ")" : ""}</option>
      ${grp("Telefoner", d.phones.map((p) => opt(p, p.replace(/^mobile_app_/, ""))))}
      ${grp("Andra notify-tjänster", (d.others || []).map((p) => opt(p, "notify." + p)))}
      ${grp("Egna skript", (d.scripts || []).map((x) => opt(x.id, x.name)))}</select>
    <div class="note" style="margin-top:6px">Ett skript anropas med variablerna <code>title</code> (rubrik) och <code>message</code> (texten), t.ex. för att skicka vidare till högtalare, Telegram eller flera telefoner.</div>
    <label style="display:flex;gap:8px;align-items:flex-start;margin-top:10px"><input type="checkbox" id="phonehome"${d.home_only ? " checked" : ""} style="margin-top:3px">
      <span>Bara till den som är hemma<br><span class="note">Aviseringar om huset går till telefonerna som är hemma enligt Home Assistant. Är ingen hemma går de till alla. Vet Home Assistant inte var någon är går de till telefonen ovan.</span></span></label>
    <button class="icobtn" id="phonesave" style="margin-top:10px">Spara</button>`;
  document.getElementById("phonesave").onclick = async () => {
    try { const j = await postJSON("api/notify-target", { target: document.getElementById("phonesel").value, home_only: document.getElementById("phonehome").checked }); toast(j.message || "Sparat"); }
    catch (e) { toast(e.message); }
  };
}

// Notiser: en strömbrytare per kategori (smartbox/notify_prefs.py). Sparas direkt när man slår om.
async function mountNotifyPrefs() {
  let d;
  try { d = await api("api/notify-prefs"); } catch (e) { return; }
  const card = document.getElementById("notifycard"), body = document.getElementById("notifybody");
  if (!card || !d || !d.ok) return;
  card.hidden = false;
  body.innerHTML = d.categories.map((c) => `<div class="togglerow" style="align-items:flex-start;gap:12px;padding:6px 0">
      <span style="flex:1 1 auto;min-width:0"><b>${esc(c.label)}</b><div class="note">${esc(c.desc)}</div></span>
      <label class="switch" style="flex:none"><input type="checkbox" data-notify="${esc(c.key)}" ${c.on ? "checked" : ""}><span class="slider"></span></label></div>`).join("");
  body.querySelectorAll("[data-notify]").forEach((cb) => cb.onchange = async () => {
    try { await postJSON("api/notify-prefs", { on: { [cb.dataset.notify]: cb.checked } }); toast(cb.checked ? "Notisen är på" : "Notisen är avstängd"); }
    catch (e) { cb.checked = !cb.checked; toast(e.message); }
  });
}

// Givare: innegivare (med korrigering och fukt), utegivare. Inget förval i koden - förslagen kommer från namnen i HA.
async function mountSensorSettings() {
  let d;
  try { d = await api("api/sensors"); } catch (e) { return; }
  const card = document.getElementById("sensorcard"), body = document.getElementById("sensorbody");
  if (!card || !d || !d.ok) { if (card && d && d.error) { card.hidden = false; body.innerHTML = `<div class="note">${esc(d.error)}</div>`; } return; }
  card.hidden = false;
  const sel = {}; (d.selected.indoor || []).forEach((x) => sel[x.entity] = x);
  const num = (v) => v == null ? "–" : `${String(v).replace(".", ",")} °C`;
  // Fuktgivaren på samma enhet hittas på namnet (…_temperature -> …_humidity)
  const humFor = (e) => { const base = e.replace(/_(temperature|temperatur|temp)(_\d+)?$/, "");
    const h = d.humidities.find((x) => x.entity.startsWith(base) && /humid|fukt/.test(x.entity)); return h ? h.entity : ""; };
  const anySel = Object.keys(sel).length > 0;
  const rows = d.temperatures.map((t) => {
    const cur = sel[t.entity] || {};
    if (t.suggest_outdoor)            // utegivare räknas aldrig in i innetemperaturen (issue #149) - välj den nedan
      return `<div class="sensrow" data-e="${esc(t.entity)}" data-out="1" style="display:flex;flex-wrap:wrap;gap:6px 12px;align-items:center;padding:7px 0;border-top:1px solid var(--line)">
        <span style="flex:1 1 220px;min-width:0;overflow-wrap:anywhere">🌳 ${esc(t.name)} <span class="note">${num(t.value)}</span>
        <div class="note">Utegivare – räknas inte in i innetemperaturen. Välj den som utegivare nedan.</div></span></div>`;
    const on = sel[t.entity] || (!anySel && t.suggest_indoor);
    return `<div class="sensrow" data-e="${esc(t.entity)}" style="display:flex;flex-wrap:wrap;gap:6px 12px;align-items:center;padding:7px 0;border-top:1px solid var(--line)">
      <label style="display:flex;gap:8px;align-items:center;flex:1 1 220px;min-width:0"><input type="checkbox" class="senson"${on ? " checked" : ""}>
        <span style="min-width:0;overflow-wrap:anywhere">${t.suggest_indoor ? "⭐ " : ""}${esc(t.name)} <span class="note">${num(t.value)}</span></span></label>
      <label class="note" style="display:flex;gap:6px;align-items:center">Korrigering <input class="sensoff" inputmode="decimal" style="width:64px" value="${cur.offset ? String(cur.offset).replace(".", ",") : ""}" placeholder="0"> °C</label>
      <input type="hidden" class="senshum" value="${esc(cur.humidity || humFor(t.entity))}"></div>`;
  }).join("");
  const outdoor = d.selected.outdoor || (d.temperatures.find((t) => t.suggest_outdoor) || {}).entity || "";
  body.innerHTML = `
    <div class="note" style="margin-bottom:6px">${d.temperatures.length} temperaturgivare i Home Assistant${anySel ? "" : " - förslagen är förkryssade, kontrollera och spara"}.</div>
    <input id="sensfilter" placeholder="Sök givare…" style="width:100%;margin-bottom:6px">
    <div id="senslist" style="max-height:420px;overflow-y:auto">${rows || `<div class="note">Inga temperaturgivare hittades.</div>`}</div>
    <label style="display:flex;flex-direction:column;gap:4px;margin-top:12px"><span class="note">Utegivare (annars används värmepumpens)</span>
      <select id="sensout"><option value="">– ingen –</option>${d.temperatures.map((t) => `<option value="${esc(t.entity)}"${t.entity === outdoor ? " selected" : ""}>${t.suggest_outdoor ? "⭐ " : ""}${esc(t.name)} (${num(t.value)})</option>`).join("")}</select></label>
    <button class="icobtn" id="senssave" style="margin-top:10px">Spara givare</button>`;
  document.getElementById("sensfilter").oninput = (ev) => {
    const q = ev.target.value.toLowerCase();
    body.querySelectorAll(".sensrow").forEach((r) => r.hidden = q && !r.textContent.toLowerCase().includes(q) && !r.dataset.e.includes(q));
  };
  document.getElementById("senssave").onclick = async () => {
    const indoor = [...body.querySelectorAll(".sensrow:not([data-out])")].filter((r) => r.querySelector(".senson").checked).map((r) => {
      const t = d.temperatures.find((x) => x.entity === r.dataset.e);
      return { entity: r.dataset.e, label: (sel[r.dataset.e] || {}).label || t.name, offset: r.querySelector(".sensoff").value, humidity: r.querySelector(".senshum").value };
    });
    try {
      const j = await postJSON("api/sensors", { indoor, outdoor: document.getElementById("sensout").value });
      toast(j.message || "Sparat"); mountSensorSettings();
    } catch (e) { toast(e.message); }
  };
}

async function mountPriceSettings() {
  let d, schedules = [];
  try { d = await api("api/price-settings"); } catch (e) { return; }
  const card = document.getElementById("pricecard"), body = document.getElementById("pricebody");
  if (!card || !d.ok) return;
  card.hidden = false;
  moneyCurrency = d.currency;
  moneySymbol = d.symbol;
  const field = (id, label, val, hint, mode = "decimal") => `<label style="display:flex;flex-direction:column;gap:4px;flex:1 1 170px;min-width:0">
      <span class="note">${label}</span><input id="${id}" inputmode="${mode}" value="${val ?? ""}" style="width:100%">${hint ? `<span class="note" style="font-size:.78rem">${hint}</span>` : ""}</label>`;
  const draw = () => {
    const c = d.countries[d.country] || d.countries.SE, sym = d.symbol;
    body.innerHTML = `
      <div style="display:flex;gap:10px;flex-wrap:wrap">
        <label style="display:flex;flex-direction:column;gap:4px;flex:1 1 170px"><span class="note">Land</span>
          <select id="pcountry">${Object.entries(d.countries).map(([k, v]) => `<option value="${k}"${k === d.country ? " selected" : ""}>${esc(v.name)}</option>`).join("")}</select></label>
        <label style="display:flex;flex-direction:column;gap:4px;flex:1 1 170px"><span class="note">Elområde</span>
          <select id="parea">${c.areas.map((a) => `<option${a === d.area ? " selected" : ""}>${a}</option>`).join("")}</select></label>
      </div>
      <div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:10px">
        ${field("ptimezone", "Price timezone", d.timezone, "E.g. Australia/Sydney, Australia/Brisbane or Australia/Adelaide", "text")}
        ${field("pvat", "Moms (%)", d.vat_pct, `Standard för ${esc(c.name)}: ${String(c.vat_pct).replace(".", ",")} %`)}
        ${field("pbuy", `<span>Avgifter vid köp</span> (${esc(sym)}/kWh, <span>inkl. moms</span>)`, d.buy_extra, "Nätöverföring + energiskatt + elhandlarens påslag")}
        ${field("psell", `<span>Ersättning vid försäljning</span> (${esc(sym)}/kWh)`, d.sell_extra, "Utöver spotpriset, t.ex. nätnytta")}
      </div>
      <div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:10px">
        <label style="display:flex;flex-direction:column;gap:4px;flex:1 1 170px;min-width:0"><span class="note">Köpavtal</span><select id="pbuymode"><option value="spot"${!["fixed", "hdo"].includes(d.buy_mode) ? " selected" : ""}>Spotpris</option><option value="fixed"${d.buy_mode === "fixed" ? " selected" : ""}>Fast pris</option>${d.country === "CZ" ? `<option value="hdo"${d.buy_mode === "hdo" ? " selected" : ""}>NT/VT enligt HDO</option>` : ""}</select></label>
        ${field("pbuyfixed", `<span>Fast inköpspris</span> (${esc(sym)}/kWh, <span>inkl. moms</span>)`, d.buy_fixed ?? "", "Endast elhandel; avgifter och distribution läggs till separat")}
        <label style="display:flex;flex-direction:column;gap:4px;flex:1 1 170px;min-width:0"><span class="note">Säljavtal</span><select id="psellmode"><option value="spot"${d.sell_mode !== "fixed" ? " selected" : ""}>Spotpris</option><option value="fixed"${d.sell_mode === "fixed" ? " selected" : ""}>Fast pris</option></select></label>
        ${field("psellfixed", `<span>Fast försäljningspris</span> (${esc(sym)}/kWh)`, d.sell_fixed ?? "", "Slutpris enligt avtal; justeringen ovan läggs till")}
      </div>
      <div class="note">Även fasta priser och HDO kräver en fungerande spotprissensor för EnergyWizards planering och försäljningspris.</div>
      <details id="phdodetails" style="margin-top:12px"${d.country !== "CZ" ? " hidden" : ""}${(d.hdo_entity || d.buy_mode === "hdo") && d.country === "CZ" ? " open" : ""}><summary><b>HDO-schema och distribution</b></summary>
        <label style="display:flex;flex-direction:column;margin-top:8px"><span class="note">HDO-schema från Home Assistant</span>
          <select id="phdo"><option value="">Av</option>${schedules.map(e => `<option value="${esc(e.entity_id)}"${e.entity_id === d.hdo_entity ? " selected" : ""}>${esc(e.name)} · ${esc(e.entity_id)}</option>`).join("")}${d.hdo_entity && !schedules.some(e => e.entity_id === d.hdo_entity) ? `<option value="${esc(d.hdo_entity)}" selected>${esc(d.hdo_entity)} (otillgänglig)</option>` : ""}</select></label>
        <div id="phdostatus" class="note" role="status" hidden></div>
        <div id="phdobuy" style="margin-top:10px">
          <label style="display:flex;flex-direction:column;gap:4px"><span class="note">Priskälla för NT/VT</span><select id="phdopricesource"><option value="manual"${d.hdo_price_source !== "ha" ? " selected" : ""}>Ange priser manuellt</option><option value="ha"${d.hdo_price_source === "ha" ? " selected" : ""}>Hämta båda priserna från ČEZ HDO</option></select></label>
          <div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:8px">
            ${field("pbuynt", `<span>Slutpris NT</span> (${esc(sym)}/kWh, <span>inkl. moms</span>)`, d.buy_nt ?? "", "")}
            ${field("pbuyvt", `<span>Slutpris VT</span> (${esc(sym)}/kWh, <span>inkl. moms</span>)`, d.buy_vt ?? "", "")}
          </div>
          <div class="note">Ange slutpriser inklusive moms, distribution och leverantörens avgifter. Samma gäller priser hämtade från ČEZ HDO. Inga köpavgifter, tidstariffer eller distributionspåslag läggs till i detta läge.</div>
          <div class="note">Båda priskällorna kräver HDO-schemat ovan. Saknas framtida intervall används det högre priset. Vid avbrott i Home Assistant används senast sparade NT/VT-priser.</div>
        </div>
        <details id="phdohelp" style="margin-top:8px"><summary>Hur installerar jag ČEZ HDO?</summary>
          <div class="note" style="margin-top:8px">För anslutningar hos ČEZ Distribuce. En separat Home Assistant-integration behövs; EnergyWizard installerar den inte automatiskt.</div>
          <ol class="note" style="padding-left:24px;line-height:1.6">
            <li>Öppna HACS, eller Inställningar → Marketplace i nyare Home Assistant, och sök efter ČEZ HDO. Om den saknas, lägg till Cmajda/ha_cez_distribuce som ett eget integrationsarkiv.</li>
            <li>Installera ČEZ HDO och starta om Home Assistant enligt integrationens anvisningar.</li>
            <li>Öppna Inställningar → Enheter och tjänster → Lägg till integration → ČEZ HDO. Ange anläggningens EAN och HDO-signal och slutför eventuell CAPTCHA.</li>
            <li>När HDO-schemat finns, ladda om EnergyWizard och välj anläggningens schemasensor här. Välj sedan köpavtal och fyll i motsvarande priser från din faktura.</li>
          </ol>
          <div class="note">Välj schemasensorn, inte sensorn för aktuell total elpris. För andra nätägare stöds ännu inte hämtning av HDO-schema här.</div>
          <div style="display:flex;gap:12px;flex-wrap:wrap;margin-top:8px">
            <a href="https://my.home-assistant.io/redirect/hacs_repository/?category=Integration&amp;owner=Cmajda&amp;repository=ha_cez_distribuce" target="_blank" rel="noopener noreferrer">Öppna ČEZ HDO i HACS / Marketplace</a>
            <a href="https://github.com/Cmajda/ha_cez_distribuce/wiki/User-Guide-CS" target="_blank" rel="noopener noreferrer">Installationsguide för ČEZ HDO</a>
            <a href="https://www.hacs.xyz/docs/marketplace/" target="_blank" rel="noopener noreferrer">HACS och Marketplace</a>
          </div>
        </details>
        <div id="phdodistribution" style="margin-top:8px">
        <div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:8px">
          ${field("pnt", `<span>Distribution NT</span> (${esc(sym)}/kWh, <span>inkl. moms</span>)`, d.distribution_nt ?? "", "Endast rörlig distribution, inte elhandel")}
          ${field("pvt", `<span>Distribution VT</span> (${esc(sym)}/kWh, <span>inkl. moms</span>)`, d.distribution_vt ?? "", "Ta bort samma avgift från köpavgiften ovan")}
        </div>
        <div class="note">Använder framtida NT/VT-intervall från ČEZ HDO. Saknas schema används den högre distributionsavgiften. Fasta månadsavgifter ingår inte. HDO påverkar bara köp.</div>
        </div>
      </details>
      <label style="display:flex;gap:8px;align-items:center;margin-top:10px"><input type="checkbox" id="psellvat"${d.sell_vat ? " checked" : ""}> Moms på såld el (oftast nej för privatpersoner)</label>
      <details id="ptoudetails" style="margin-top:12px"${d.tou_extra ? " open" : ""}><summary><b>Tidstariff</b> <span class="note">(dyrare nätavgift under höglasttid)</span></summary>
        <div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:8px">
          ${field("ptou", `Tillägg under höglast (${sym}/kWh, inkl. moms)`, d.tou_extra || "", "0 eller tomt = ingen tidstariff")}
          ${field("ptouh", "Timmar", d.tou_hours, "T.ex. 6-22 = 06:00–21:59", "text")}
          ${field("ptoum", "Månader", d.tou_months, "T.ex. 11-3 = november–mars", "text")}
        </div>
        <label style="display:flex;gap:8px;align-items:center;margin-top:8px"><input type="checkbox" id="ptouwd"${d.tou_weekdays ? " checked" : ""}> Bara vardagar</label>
        <div class="note" style="margin-top:6px">Står på elräkningen eller nätbolagets sida (t.ex. Ellevio, E.ON, Vattenfall). Batteriplanen, planklockan och kostnaderna räknar med den.</div>
      </details>
      <details style="margin-top:12px"${["egen", "av"].includes((d.power_high || {}).choice) ? " open" : ""}><summary><b>Effekttariff</b> <span class="note">(höglasttid för effektvaktens gränser)</span></summary>
        <label style="display:flex;flex-direction:column;gap:4px;margin-top:8px;max-width:420px"><span class="note">Höglasttid</span>
          <select id="phchoice">
            <option value="tidstariff"${!["egen", "av"].includes((d.power_high || {}).choice) ? " selected" : ""}>Samma tider som tidstariffen (eller 07–20 vardagar nov–mars)</option>
            <option value="egen"${(d.power_high || {}).choice === "egen" ? " selected" : ""}>Egna tider</option>
            <option value="av"${(d.power_high || {}).choice === "av" ? " selected" : ""}>Ingen höglasttid</option>
          </select></label>
        <div id="phown" style="display:${(d.power_high || {}).choice === "egen" ? "block" : "none"}">
          <div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:8px">
            ${field("phh", "Timmar", (d.power_high || {}).hours || "7-20", "T.ex. 7-20 = 07:00–19:59", "text")}
            ${field("phm", "Månader", (d.power_high || {}).months || "11-3", "T.ex. 11-3 = november–mars", "text")}
          </div>
          <label style="display:flex;gap:8px;align-items:center;margin-top:8px"><input type="checkbox" id="phwd"${(d.power_high || {}).weekdays !== false ? " checked" : ""}> Bara vardagar</label>
        </div>
        <div class="note" style="margin-top:6px">Effektavgift tas efter din högsta timme under höglasttid. Står på nätbolagets sida.</div>
      </details>
      <div id="pricesrc" style="margin-top:12px"></div>
      <div id="priceexample" style="margin-top:12px;padding:10px 12px;border:1px solid var(--line);border-radius:12px;background:var(--card2);line-height:1.5">
        Exempel: spotpris 1,00 ${sym} (exkl. moms) blir <b>${kr(d.example.buy)} ${sym}/kWh</b> att köpa och <b>${kr(d.example.sell)} ${sym}/kWh</b> att sälja.</div>
      <button class="icobtn" id="psave" style="margin-top:10px">Spara</button>`;
    const loadSchedules = async () => {
      if (d.country !== "CZ" || !document.getElementById("phdodetails").open) return;
      const select = document.getElementById("phdo");
      try {
        const h = await api("api/distribution-schedules");
        if (!select.isConnected || !h.ok) return;
        const selected = select.value;
        schedules = h.entities || [];
        const status = document.getElementById("phdostatus");
        status.hidden = schedules.length > 0;
        status.textContent = schedules.length ? "" : "Inget kompatibelt HDO-schema hittades. Följ installationsguiden nedan eller kontrollera din ČEZ HDO-integration.";
        if (!schedules.length) document.getElementById("phdohelp").open = true;
        select.innerHTML = `<option value="">Av</option>${schedules.map(e => `<option value="${esc(e.entity_id)}"${e.entity_id === selected ? " selected" : ""}>${esc(e.name)} · ${esc(e.entity_id)}</option>`).join("")}${selected && !schedules.some(e => e.entity_id === selected) ? `<option value="${esc(selected)}" selected>${esc(selected)} (otillgänglig)</option>` : ""}`;
        showHdoPrices();
      } catch (e) { /* keep selected entity if HA is temporarily unavailable */ }
    };
    const showHdoPrices = () => {
      const fromHa = document.getElementById("phdopricesource").value === "ha";
      const row = schedules.find(e => e.entity_id === document.getElementById("phdo").value);
      for (const [id, key] of [["pbuynt", "nt"], ["pbuyvt", "vt"]]) {
        const input = document.getElementById(id);
        input.disabled = fromHa;
        if (fromHa) input.value = row && row[key] != null && Number.isFinite(Number(row[key])) ? row[key] : "";
      }
    };
    document.getElementById("phdopricesource").onchange = showHdoPrices;
    document.getElementById("phdo").onchange = showHdoPrices;
    document.getElementById("phdodetails").ontoggle = loadSchedules;
    showHdoPrices();
    if (d.country === "CZ" && d.hdo_entity) loadSchedules();
    for (const [mode, fixed] of [["pbuymode", "pbuyfixed"], ["psellmode", "psellfixed"]]) {
      const select = document.getElementById(mode), field = document.getElementById(fixed).parentElement;
      const show = () => {
        field.style.display = select.value === "fixed" ? "flex" : "none";
        if (mode === "psellmode") d.sell_mode = select.value;
        document.getElementById("priceexample").hidden = d.buy_mode !== "spot" || d.sell_mode !== "spot" || select.value !== "spot";
        if (mode === "pbuymode") {
          d.buy_mode = select.value;
          const hdo = d.country === "CZ" && select.value === "hdo";
          document.getElementById("phdobuy").hidden = !hdo;
          document.getElementById("phdodistribution").hidden = hdo;
          document.getElementById("priceexample").hidden = d.buy_mode !== "spot" || d.sell_mode !== "spot";
          document.getElementById("ptoudetails").hidden = hdo;
          document.getElementById("pbuy").parentElement.style.display = hdo ? "none" : "flex";
          if (hdo) document.getElementById("phdodetails").open = true;
        }
      };
      select.onchange = show; show();
    }
    document.getElementById("pcountry").onchange = (e) => {
      const k = e.target.value, cc = d.countries[k];
      Object.assign(d, { country: k, area: cc.areas[0], vat_pct: cc.vat_pct, currency: cc.currency, symbol: cc.symbol, timezone: cc.timezone,
        buy_mode: k !== "CZ" && d.buy_mode === "hdo" ? "spot" : d.buy_mode,
        buy_extra: k === "SE" ? 0.62675 : 0, sell_extra: k === "SE" ? 0.02125 : 0 });
      draw();
      mountPriceSource("pricesrc", d.country);
    };
    document.getElementById("phchoice").onchange = (e) => { document.getElementById("phown").style.display = e.target.value === "egen" ? "block" : "none"; };
    document.getElementById("psave").onclick = async () => {
      const v = (id) => (document.getElementById(id) || {}).value;
      try {
        await postJSON("api/price-settings", { country: v("pcountry"), area: v("parea"), timezone: v("ptimezone"), vat_pct: v("pvat"), buy_extra: v("pbuy"),
          buy_mode: v("pbuymode"), buy_fixed: v("pbuyfixed"), sell_mode: v("psellmode"), sell_fixed: v("psellfixed"),
          hdo_entity: v("phdo"), distribution_nt: v("pnt"), distribution_vt: v("pvt"),
          buy_nt: v("pbuynt"), buy_vt: v("pbuyvt"), hdo_price_source: v("phdopricesource"),
          sell_extra: v("psell"), sell_vat: document.getElementById("psellvat").checked,
          tou_extra: v("ptou"), tou_hours: v("ptouh"), tou_months: v("ptoum"), tou_weekdays: document.getElementById("ptouwd").checked,
          power_high: { choice: v("phchoice"), hours: v("phh"), months: v("phm"), weekdays: document.getElementById("phwd").checked } });
        toast("Sparat - priser och kostnader räknas om inom en minut");
        mountPriceSettings();
      } catch (e) { toast(e.message); }
    };
  };
  draw();
  mountPriceSource("pricesrc", d.country);
}

// Priskälla: en prissensor i Home Assistant (Nord Pool, ENTSO-e, EPEX Spot, Energi Data Service, Octopus, Amber ...)
// eller standard (elprisetjustnu.se, bara Sverige). Visas både under Inställningar och i entitetsväljaren.
async function mountPriceSource(slotId, country) {
  const slot = document.getElementById(slotId);
  if (!slot) return;
  slot.innerHTML = `<div class="note">Letar efter prissensorer i Home Assistant…</div>`;
  let d;
  try { d = await api("api/price-entities"); } catch (e) { slot.innerHTML = ""; return; }
  if (!slot.isConnected) return;                           // fliken byttes medan hämtningen pågick
  const opts = [`<option value="">${country && country !== "SE" ? "Ingen vald" : "Standard: elprisetjustnu.se (Sverige)"}</option>`]
    .concat(d.entities.map((e) => `<option value="${esc(e.entity_id)}"${e.entity_id === d.selected ? " selected" : ""}>${esc(e.name)} · ${esc(e.integration)}${e.unit ? " · " + esc(e.unit) : ""}</option>`));
  slot.innerHTML = `
    <label style="display:flex;flex-direction:column;gap:4px"><span class="note">Priskälla (spotpriset per kvart/timme)</span>
      <select id="psrc" style="max-width:100%">${opts.join("")}</select></label>
    <div class="note" style="margin-top:4px">${d.entities.length ? `${d.entities.length} prissensor${d.entities.length > 1 ? "er" : ""} hittades i Home Assistant.`
      : `Ingen prissensor hittades. Installera t.ex. <a href="https://github.com/custom-components/nordpool" target="_blank" rel="noopener">Nord Pool</a>,
        <a href="https://github.com/JaccoR/hass-entso-e" target="_blank" rel="noopener">ENTSO-e</a> (hela Europa),
        Energi Data Service (Danmark) eller Octopus Energy (Storbritannien) i Home Assistant och skanna igen.`}</div>
    ${country === "CZ" ? `<div class="note">Råa OTE-spotpriser är normalt utan moms. Kontrollera om den valda sensorn redan inkluderar moms innan du sparar.</div>` : ""}
    <label style="display:flex;gap:8px;align-items:center;margin-top:8px"><input type="checkbox" id="psrcvat"${d.includes_vat ? " checked" : ""}>
      Priset i sensorn är redan inklusive moms (Nord Pool och Octopus brukar vara det, ENTSO-e och EPEX inte)</label>
    <label style="display:flex;flex-direction:column;gap:4px;margin-top:8px">Published prices
      <select id="psrcfinal">
        <option value="auto"${d.final === "auto" ? " selected" : ""}>Automatic (Amber refreshes every 5 minutes)</option>
        <option value="true"${d.final === "true" ? " selected" : ""}>Final once published (day-ahead prices)</option>
        <option value="false"${d.final === "false" ? " selected" : ""}>Refresh current and future prices every 5 minutes</option>
      </select></label>
    <label style="display:flex;flex-direction:column;gap:4px;margin-top:8px">Current price sensor (optional)
      <input id="psrccurrent" value="${esc(d.current_entity || "")}" placeholder="sensor.amber_general_price">
      <span class="note">Use the current price, not the forecast. Amber's matching _price sensor is tried automatically; select it here if renamed.</span></label>
    <button class="icobtn" id="psrcsave" style="margin-top:8px">Använd priskällan</button>`;
  slot.querySelector("#psrcsave").onclick = async () => {
    try { await postJSON("api/price-source", { ha_entity: slot.querySelector("#psrc").value, includes_vat: slot.querySelector("#psrcvat").checked,
      final: slot.querySelector("#psrcfinal").value, current_entity: slot.querySelector("#psrccurrent").value });
      toast("Priskällan sparad - priserna hämtas om inom en minut"); }
    catch (e) { toast(e.message); }
  };
}

async function mountBatteryPlanSettings() {
  let d;
  try { d = await api("api/battery-plan-settings"); } catch (e) { return; }
  if (!d.has_battery) return;
  document.getElementById("batplancard").hidden = false;
  const draw = () => {
    document.getElementById("batstyle").innerHTML = d.styles.map((k) =>
      `<button class="icobtn${k === d.style ? " on" : ""}" data-style="${k}" style="${k === d.style ? "outline:2px solid var(--acc)" : ""}">${esc(BAT_STYLES[k][0])}</button>`).join("");
    document.getElementById("batstyledesc").textContent = BAT_STYLES[d.style][1];
    document.querySelectorAll("#batstyle [data-style]").forEach((b) => b.onclick = async () => {
      try { await postJSON("api/battery-plan-settings", { style: b.dataset.style }); d.style = b.dataset.style; draw(); toast("Sparat - gäller från nästa plan (inom 15 min)"); }
      catch (e) { toast(e.message); }
    });
  };
  draw();
  const cb = document.getElementById("batexport");
  cb.checked = d.allow_export;
  cb.onchange = () => postJSON("api/battery-plan-settings", { allow_export: cb.checked }).catch(() => { cb.checked = !cb.checked; });
}

function mountLangSelect(slotId, saveForInstall) {
  const slot = document.getElementById(slotId);
  if (!slot || !window.I18N) return;
  I18N.ready.then(() => {
    slot.innerHTML = I18N.selectHtml(slotId + "_sel");
    document.getElementById(slotId + "_sel").onchange = async (e) => {
      const lang = e.target.value;
      if (saveForInstall) { try { await postJSON("api/setup/language", { language: lang }); } catch (err) { /* bara den här enheten */ } }
      I18N.set(lang);
    };
  });
}

// Värmepumpens mätvärden (frekvens, el, framledning/retur och COP). Visas bara de som pumpen faktiskt ger.
function pumpCardHtml(p) {
  if (!p) return "";
  const tiles = [];
  const tile = (label, value) => tiles.push(`<div><div class="note">${label}</div><div style="font-size:1.25rem;font-weight:700">${value}</div></div>`);
  if (p.compressor_running != null) tile("Kompressor", Number(p.compressor_running) ? "Går" : "Vilar");
  if (p.compressor_frequency_hz != null) tile("Frekvens", `${fmt(p.compressor_frequency_hz, 0, "")} Hz`);
  if (p.compressor_power_w != null) tile("El in", `${fmt(p.compressor_power_w, 0, "")} W`);
  if (p.forward_temp != null) tile("Framledning", fmt(p.forward_temp, 1, "°C"));
  if (p.return_temp != null) tile("Retur", fmt(p.return_temp, 1, "°C"));
  if (p.cop_1h != null) tile("COP, senaste timmen", fmt(p.cop_1h, 1, ""));
  else if (p.cop_est != null) tile("COP (skattad)", fmt(p.cop_est, 1, ""));
  if (!tiles.length) return "";
  const hour = p.heat_produced_kwh_1h != null && p.electric_used_kwh_1h != null
    ? `<div class="note" style="margin-top:10px">Senaste timmen: ${fmt(p.heat_produced_kwh_1h, 2, "")} kWh värme för ${fmt(p.electric_used_kwh_1h, 2, "")} kWh el (pumpens egen energilogg).</div>` : "";
  return `<div class="card" style="margin-bottom:16px"><h2>📈 Just nu</h2>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:14px;margin-top:8px">${tiles.join("")}</div>${hour}</div>`;
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
    ${pumpCardHtml(d.pump)}
    <div class="card" style="margin-bottom:16px">
      <h2>🔋 Varmvattenberedaren som värmebatteri</h2>
      <div class="note">Laddas till ${d.heat_battery ? d.heat_battery.ceiling.toFixed(0) : "–"}°C när elen är billig eller solen räcker - töms (kompressorn vilar) när elen är dyr.</div>
      <div style="margin-top:18px">${heatBatteryHtml(d.heat_battery, false)}</div>
    </div>
    <div class="grid" style="margin-bottom:16px">
      <div class="card">
        <h2>🌡️ Rumsvärme</h2>
        <div class="note" style="margin-bottom:8px">Auto = AI:n styr efter elpriset (normalläget). Tvinga PÅ/AV håller tills du väljer Auto igen.</div>
        <div class="seg" id="heatseg">${["auto", "on", "off"].map(m => `<button data-m="${m}" class="${d.heat_mode === m ? "on" : ""}">${{ auto: "Auto", on: "Tvinga PÅ", off: "Tvinga AV" }[m]}</button>`).join("")}</div>
      </div>
      <div class="card">
        <h2>🚿 Varmvatten</h2>
        <div class="note" style="margin-bottom:8px">Samma princip som rumsvärmen, egen överstyrning.</div>
        <div class="seg" id="hotwaterseg">${["auto", "on", "off"].map(m => `<button data-m="${m}" class="${d.hotwater_mode === m ? "on" : ""}">${{ auto: "Auto", on: "Tvinga PÅ", off: "Tvinga AV" }[m]}</button>`).join("")}</div>
      </div>
    </div>
    <div class="card">
      <h2>🎯 Måltemperatur (Auto-läget)</h2>
      <div class="note">Vid billig el / Auto: ${fmt(d.temp_cheap, 1, "°C")} · Vid dyr el: ${fmt(d.temp_expensive, 1, "°C")}</div>
      <div class="numfield" style="margin-top:10px">Billigt: <input type="number" id="tempcheap" step="0.5" min="16" max="26" value="${d.temp_cheap != null ? d.temp_cheap : ""}"> °C
        Dyrt: <input type="number" id="tempexpensive" step="0.5" min="14" max="24" value="${d.temp_expensive != null ? d.temp_expensive : ""}"> °C
        <button class="icobtn" id="savetempbtn">Spara</button></div>
    </div>`;
  document.querySelectorAll("#heatseg button").forEach(b => b.onclick = () => postAction("api/home-action/heat", { value: b.dataset.m }).then(renderVarmepump));
  document.querySelectorAll("#hotwaterseg button").forEach(b => b.onclick = () => postAction("api/home-action/hotwater", { value: b.dataset.m }).then(renderVarmepump));
  document.getElementById("savetempbtn").onclick = async () => {
    await postAction("api/settings-action", { key: "temp_cheap", value: parseFloat(document.getElementById("tempcheap").value) });
    await postAction("api/settings-action", { key: "temp_expensive", value: parseFloat(document.getElementById("tempexpensive").value) });
    renderVarmepump();
  };
}

async function renderSystem() {
  const main = document.getElementById("main");
  main.innerHTML = `<div class="placeholder">Laddar…</div>`;
  await loadUpdates(false);
}

// Installationer: siffrorna överst, sedan ett kort per användare (anonymt, ditt hus först), totalen hopfälld längst ner.
async function renderInstalls() {
  const main = document.getElementById("main");
  main.innerHTML = `<div class="placeholder">Laddar…</div>`;
  const d = await api("api/installs").catch(() => null);
  if (!d || !d.configured) { main.innerHTML = `<div class="placeholder">Inte tillgängligt.</div>`; return; }
  if (!d.ok) { main.innerHTML = installsCard(d); return; }
  const SIZE_PRE = { battery_: "batteri ", car_: "elbil ", fuse_: "huvudsäkring " };
  const prettyDrv = (drv) => {
    if (DRIVER_NAMES[drv]) return DRIVER_NAMES[drv];
    if (drv.startsWith("preset_")) return "förinställning " + drv.slice(7);
    if (drv.startsWith("ftw-")) return "FTW-drivrutin " + drv.slice(4);
    let m;
    if ((m = drv.match(/^ha_sensors_(\d+)$/))) return `${m[1]} givare i HA`;
    if (drv === "heatpump") return "värmepumpens givare";
    if (drv === "none") return "ingen";
    if (drv === "mixed") return "flera märken";
    if ((m = drv.match(/^(inne|ute)_(-?\d+)C$/))) return `${m[1]} ${m[2]} °C`;
    const pre = Object.keys(SIZE_PRE).find((p) => drv.startsWith(p));
    return pre ? SIZE_PRE[pre] + drv.slice(pre.length).replace(/(\d)(kWh|A)$/, "$1 $2") : drv;
  };
  const labelOf = (k) => { const [drv, brandModel] = k.split("@"); const dn = prettyDrv(drv);
    const brand = brandModel ? brandModel.replace("#", " ") : brandModel;
    return brand && brand.toLowerCase() !== dn.toLowerCase() ? `<b>${esc(brand)}</b> <span class="note">${esc(dn)}</span>` : `<b>${esc(dn)}</b>`; };
  const big = (n, t) => `<div><div style="font-size:2rem;font-weight:800">${n}</div><div class="note">${t}</div></div>`;
  const summary = `<div class="card" style="margin-bottom:16px"><div style="font-size:1.1rem;font-weight:700">👥 Installationer</div>
    <div style="display:flex;gap:28px;flex-wrap:wrap;margin-top:10px">${big(d.active, `aktiva (hörda senaste ${d.active_days} dygnen)`)}${big(d.total_known, "totalt sedan start")}${big(d.new_last_7d, "nya senaste veckan")}</div>
    <div class="note" style="margin-top:10px">Ett kort per användare, anonymt numrerade i den ordning de kom. Bara drivrutin och märke, aldrig vem eller var.${d.ping_only ? ` ${d.ping_only} kör en äldre version som bara skickar version (anonymt) – de visar sin utrustning när de uppdaterat till 1.2.45, där telemetrin är obligatorisk.` : ""}</div></div>`;
  const houses = [...(d.houses || [])].sort((x, y) => (y.mine ? 1 : 0) - (x.mine ? 1 : 0));
  const cardHtml = (h) => {
    const n = Object.values(h.devices).reduce((a, l) => a + l.length, 0);
    const rows = INSTALL_CATS.map(([cat, ico, name]) => {
      const list = h.devices[cat] || [];
      if (!list.length && ["meter", "price", "country", "size", "indoor", "temp", "mode"].includes(cat)) return "";   // äldre versioner skickar inte dessa
      const counts = {}; list.forEach((x) => counts[x] = (counts[x] || 0) + 1);
      const val = list.length ? Object.entries(counts).map(([k, c]) => labelOf(k) + (c > 1 ? ` × ${c}` : "")).join(", ") : `<span class="note">–</span>`;
      return `<div style="display:flex;gap:10px;padding:6px 0;border-top:1px solid var(--line)"><span style="flex:0 0 26px">${ico}</span>
        <span class="note" style="flex:0 0 120px">${name}</span><span style="flex:1 1 auto;min-width:0">${val}</span></div>`;
    }).join("");
    // Tillfälliga nätverksfel (Home Assistant eller ett moln svarade inte en stund) visas grått - bara riktiga fel rött
    const TRANSIENT = /(ReadTimeout|ConnectTimeout|Timeout|ConnectionError|HTTPError|RemoteDisconnected|ChunkedEncodingError|SSLError|TimeoutError|OSError)$/;
    const allErrs = (h.errors || []), errs = allErrs.filter((e) => !TRANSIENT.test(e)), tmp = allErrs.filter((e) => TRANSIENT.test(e));
    const tmpRow = tmp.length ? `<div style="display:flex;gap:10px;padding:6px 0;border-top:1px solid var(--line)"><span style="flex:0 0 26px">🌐</span>
        <span class="note" style="flex:0 0 120px">Tillfälligt (nätet)</span><span class="note" style="flex:1 1 auto;min-width:0;overflow-wrap:anywhere">${tmp.map(esc).join("<br>")}</span></div>` : "";
    const errRow = tmpRow + `<div style="display:flex;gap:10px;padding:6px 0;border-top:1px solid var(--line)"><span style="flex:0 0 26px">${errs.length ? "⚠️" : "✅"}</span>
        <span class="note" style="flex:0 0 120px">Fel senaste dygnet</span><span style="flex:1 1 auto;min-width:0;overflow-wrap:anywhere${errs.length ? ";color:#c0392b" : ""}">${errs.length ? errs.map(esc).join("<br>") : `<span class="note">inga</span>`}</span></div>`;
    const verRow = h.version ? `<div class="note" style="padding-top:6px">Version ${esc(h.version)}</div>` : "";
    return `<div class="card" style="padding:14px${h.mine ? ";border-color:var(--acc)" : ""}${errs.length ? ";box-shadow:0 0 0 2px #e74c3c55" : ""}">
      <div style="display:flex;justify-content:space-between;gap:10px;align-items:baseline;margin-bottom:6px">
        <div style="font-size:1.05rem;font-weight:800">🏠 ${esc(h.label)}${(h.devices.country || [])[0] ? ` <span class="note" style="font-weight:600">· ${FLAG[(h.devices.country || [])[0].split("@")[0].replace("country:", "")] || ""} ${labelOf((h.devices.country || [])[0])}</span>` : ""}${h.mine ? ` <span class="badge on">ditt hus</span>` : ""}</div>
        <div class="note">sedan ${esc(h.since)}</div></div>
      ${n ? rows : h.ping_only ? `<div class="note" style="padding:8px 0">Äldre version utan telemetri – utrustningen syns när installationen uppdaterat till 1.2.45.</div>` : `<div class="note" style="padding:8px 0">Har installerat men inte valt några enheter än.</div>`}${errRow}${verRow}</div>`;
  };
  // ---- Översikt (2026-11-08, Emil: svårt att få överblick med ett stort kort per hus) ----
  const TRANS = /(ReadTimeout|ConnectTimeout|Timeout|ConnectionError|HTTPError|RemoteDisconnected|ChunkedEncodingError|SSLError|TimeoutError|OSError)$/;
  const realErr = (h) => (h.errors || []).filter((e) => !TRANS.test(e));
  const isNew = (h) => h.since && (Date.now() - Date.parse(h.since)) < 2 * 864e5;   // "ny" = senaste två dygnen
  const ago = (t) => { if (!t) return "–"; const m = Math.round((Date.now() - Date.parse(t)) / 6e4); return m < 60 ? `${m} min` : m < 1440 ? `${Math.round(m / 60)} h` : `${Math.round(m / 1440)} d`; };
  const short = (h) => {
    const dv = h.devices || {}, txt = (k) => labelOf(k).replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
    const parts = [];
    if ((dv.heatpump || [])[0]) parts.push("🌡️ " + txt(dv.heatpump[0]));
    if ((dv.solar || [])[0]) parts.push("☀️");
    if ((dv.battery || [])[0]) parts.push("🔋");
    if ((dv.car || []).length) parts.push("🚗" + ((dv.car || []).length > 1 ? "×" + dv.car.length : ""));
    if ((dv.charger || [])[0]) parts.push("🔌 " + txt(dv.charger[0]).split(" ")[0]);
    if ((dv.spa || [])[0]) parts.push("🛁");
    return parts.join("  ") || (h.ping_only ? "anonym (äldre version)" : "inga enheter valda");
  };
  const withErr = houses.filter((h) => realErr(h).length);
  const tile = (n, t, col) => `<div style="flex:1 1 120px"><div style="font-size:1.9rem;font-weight:800${col ? ";color:" + col : ""}">${n}</div><div class="note">${t}</div></div>`;
  const head = `<div class="card" style="margin-bottom:16px"><div style="font-size:1.1rem;font-weight:700">👥 Installationer</div>
    <div style="display:flex;gap:18px;flex-wrap:wrap;margin-top:10px">${tile(d.active, `aktiva (${d.active_days} dygn)`)}${tile(d.new_last_7d, "nya senaste veckan")}
    ${tile(withErr.length, "med fel just nu", withErr.length ? "#e74c3c" : "var(--acc)")}${tile(`${d.current_versions != null ? d.current_versions : "–"}/${d.active}`, "kör en aktuell version")}</div>
    <div class="note" style="margin-top:8px">Anonymt numrerade i den ordning de kom. Bara drivrutin och märke, aldrig vem eller var. Tillfälliga nätverksfel (Home Assistant eller ett moln svarade inte en stund) räknas inte som fel.</div></div>`;
  const groups = (d.error_groups || []);
  const gRow = (g) => { const t = TRANS.test(g.key); return `<div style="display:flex;gap:10px;align-items:baseline;padding:7px 0;border-top:1px solid var(--line)">
      <span style="flex:0 0 22px">${t ? "🌐" : "⚠️"}</span><span style="flex:1 1 auto;min-width:0;overflow-wrap:anywhere${t ? ";color:var(--mut)" : ";color:#e74c3c;font-weight:600"}">${esc(g.key)}</span>
      <span class="note" style="flex:0 0 auto;white-space:nowrap">${g.houses} hus · ${g.reports} ggr · ${ago(g.last)} sedan</span></div>`; };
  const errCard = groups.length ? `<div class="card" style="margin-bottom:16px"><h2 style="margin:0 0 4px">Fel senaste 48 h</h2>
    <div class="note">Grupperade över alla hus. Rött = programfel att rätta, grått = tillfälliga nätverksfel.</div>
    ${groups.filter((g) => !TRANS.test(g.key)).map(gRow).join("")}
    ${groups.some((g) => TRANS.test(g.key)) ? `<details style="margin-top:6px"><summary class="note" style="cursor:pointer">${groups.filter((g) => TRANS.test(g.key)).length} tillfälliga nätverksfel</summary>${groups.filter((g) => TRANS.test(g.key)).map(gRow).join("")}</details>` : ""}</div>` : "";
  let flt = "alla";
  const draw = () => {
    const list = houses.filter((h) => flt === "alla" || (flt === "fel" && realErr(h).length) || (flt === "gamla" && h.current === false) || (flt === "nya" && isNew(h)));
    const rows = list.map((h) => { const e = realErr(h); return `<details class="card" style="padding:0;margin-bottom:8px${e.length ? ";box-shadow:0 0 0 2px #e74c3c55" : h.mine ? ";border-color:var(--acc)" : ""}">
      <summary style="cursor:pointer;list-style:none;display:flex;gap:12px;align-items:center;flex-wrap:wrap;padding:12px 14px">
        <b style="flex:0 0 auto">${e.length ? "⚠️" : "✅"} ${esc(h.label)}${h.mine ? ' <span class="note">(ditt)</span>' : ""}</b>
        <span style="flex:1 1 200px;min-width:0">${esc(short(h))}</span>
        <span class="note" style="flex:0 0 auto;white-space:nowrap">${h.current === false ? '<span style="color:var(--warn)">äldre version</span>' : "aktuell"} · hörd ${ago(h.last_seen)} sedan${isNew(h) ? ' · <b style="color:var(--acc)">ny</b>' : ""}</span>
        ${e.length ? `<span style="flex:1 1 100%;color:#e74c3c;font-size:.9rem;overflow-wrap:anywhere">${e.map(esc).join(" · ")}</span>` : ""}
      </summary><div style="padding:0 14px 12px">${cardHtml(h)}</div></details>`; }).join("") || `<div class="note">Inga hus i det här urvalet.</div>`;
    main.innerHTML = head + errCard + `<div class="seg" id="instflt" style="margin-bottom:10px;flex-wrap:wrap">${[["alla", `Alla (${houses.length})`], ["fel", `Med fel (${withErr.length})`], ["gamla", `Äldre version (${houses.filter((h) => h.current === false).length})`], ["nya", `Nya 2 dygn (${houses.filter(isNew).length})`]]
      .map(([k, l]) => `<button data-v="${k}" class="${k === flt ? "on" : ""}">${l}</button>`).join("")}</div>` + rows
      + `<details class="card" style="margin-top:12px"><summary style="cursor:pointer;font-weight:700">Totalt per märke</summary><div style="margin-top:10px">${installsCard(d)}</div></details>`;
    main.querySelectorAll("#instflt button").forEach((b) => b.onclick = () => { flt = b.dataset.v; draw(); });
  };
  draw();
}

// Utvecklarens egen räknare: aktiva installationer och deras utrustning (telemetrin, bara märken och drivrutiner).
const FLAG = { SE: "🇸🇪", NO: "🇳🇴", DK: "🇩🇰", FI: "🇫🇮", DE: "🇩🇪", GB: "🇬🇧", NL: "🇳🇱" };   // landet syns i husets rubrik
const INSTALL_CATS = [["heatpump", "🌡️", "Värmepump"], ["spa", "🛁", "Spabad"], ["solar", "☀️", "Solceller / växelriktare"],
  ["battery", "🔋", "Husbatteri"], ["charger", "🔌", "Laddbox"], ["car", "🚗", "Elbil"], ["meter", "📟", "Elmätare"],
  ["price", "💶", "Priskälla"], ["country", "🌍", "Land"], ["size", "📏", "Storlek"], ["indoor", "🏠", "Innegivare"], ["temp", "🌡️", "Temperatur"], ["mode", "⚙️", "Körs som"]];
const DRIVER_NAMES = { thermia_husdata: "Thermia (Husdata)", generic_climate: "climate i HA", nibe_local: "NIBE S (lokalt)",
  myuplink: "myUplink", heishamon: "Panasonic (HeishaMon)", solaredge: "SolarEdge", generic_number: "exportgräns i HA",
  huawei_solar: "Huawei", modbus_register: "Modbus-register", gecko: "Gecko", balboa: "Balboa", switch: "relä/brytare",
  shelly: "Shelly", generic: "generisk", easee: "Easee", tesla: "Tesla", nissan: "Nissan", generic_ev: "generisk elbil",
  ha: "via HA", elprisetjustnu: "elprisetjustnu.se", ha_nordpool: "prissensor i HA", shadow: "skuggläge",
  tou_tariff: "tidstariff", battery_styr: "styr batteriet", battery_samarbete: "läser batteriet", battery_av: "batteri av",
  SE: "Sverige", NO: "Norge", DK: "Danmark", FI: "Finland", DE: "Tyskland", GB: "Storbritannien", NL: "Nederländerna" };
function installsCard(d) {
  if (!d.ok) return `<div class="card" style="margin-bottom:16px">👥 ${esc(d.error || "")}</div>`;
  const label = (k) => { const [drv, brand] = k.split("@"); return brand ? `${esc(brand)} <span class="note">(${esc(DRIVER_NAMES[drv] || drv)})</span>` : esc(DRIVER_NAMES[drv] || drv); };
  const cats = INSTALL_CATS.map(([key, ico, name]) => {
    const items = Object.entries((d.equipment || {})[key] || {});
    const body = items.length ? items.map(([k, n]) => `<div style="display:flex;justify-content:space-between;gap:10px;padding:3px 0"><span>${label(k)}</span><b>${n}</b></div>`).join("")
      : `<div class="note">–</div>`;
    return `<div class="card" style="padding:12px"><div style="font-weight:700;margin-bottom:6px">${ico} ${name}</div>${body}</div>`;
  }).join("");
  return `<div class="card" style="margin-bottom:16px">
      <div style="font-size:1.1rem;font-weight:700">👥 Installationer</div>
      <div style="display:flex;gap:28px;flex-wrap:wrap;margin-top:10px">
        <div><div style="font-size:2rem;font-weight:800">${d.active}</div><div class="note">aktiva (hörda senaste ${d.active_days} dygnen)</div></div>
        <div><div style="font-size:2rem;font-weight:800">${d.total_known}</div><div class="note">totalt sedan start</div></div>
        <div><div style="font-size:2rem;font-weight:800">${d.new_last_7d}</div><div class="note">nya senaste veckan</div></div>
      </div>
      ${d.without_devices ? `<div class="note" style="margin-top:8px">${d.without_devices} har inte valt några enheter än.</div>` : ""}
      ${d.ping_only ? `<div class="note" style="margin-top:4px">${d.ping_only} kör en äldre version utan telemetri och syns med utrustning efter uppdateringen.</div>` : ""}
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,220px),1fr));gap:10px;margin-top:14px">${cats}</div>
      <div class="note" style="margin-top:10px">Antal enheter, från telemetrin: bara drivrutin och märke, aldrig vem eller var. En installation syns med sina enheter när den valt dem i startguiden.</div>
    </div>`;
}

async function loadUpdates(force) {
  const main = document.getElementById("main");
  const d = await api(`api/updates${force ? "?force=1" : ""}`);
  if (!d.ok) { main.innerHTML = `<div class="placeholder">${d.error}</div>`; return; }
  if (d.configured === false) {
    main.innerHTML = `<div class="card">${d.addon
      ? "EnergyWizard uppdateras som tillägg i Home Assistant: Inställningar → Tillägg → EnergyWizard → Uppdatera."
      : "EnergyWizard uppdateras genom att hämta de nya bilderna (docker compose pull && docker compose up -d), eller automatiskt med Watchtower."}</div>`;
    return;
  }
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
      <div class="note" style="margin-top:4px">Skannar ditt Home Assistant efter värmepump, bilar, solceller, batteri, spa och laddare. Kryssa i det som stämmer och tryck <b>Spara och starta</b>.</div>
      <button class="icobtn" id="scanbtn" style="margin-top:10px">Skanna mitt Home Assistant</button>
    </div>
    <div class="card" style="margin-bottom:16px" id="mqttcard" hidden>
      <div style="font-size:1.1rem;font-weight:700">📡 Home Assistant via MQTT</div>
      <div class="note" style="margin-top:4px;line-height:1.5">Med MQTT blir EnergyWizard en riktig enhet i Home Assistant: sensorerna behåller sina namn,
        går att redigera och finns kvar när HA startar om, och du kan slå på/av skuggläget och den automatiska exportstyrningen från HA.
        Använd samma broker som Home Assistant (oftast Mosquitto-tillägget). Tomt = av, sensorerna skickas då som förut.</div>
      <div id="mqttbody" style="margin-top:10px"></div>
    </div>
    <div class="card" style="margin-bottom:16px" id="shadowcard">
      <div class="togglerow" style="align-items:flex-start;gap:14px"><div>
        <div style="font-size:1.1rem;font-weight:700">🕶️ Skuggläge</div>
        <div class="note" style="margin-top:4px;line-height:1.5">Kör EnergyWizard bredvid ditt nuvarande system: allt räknas, planeras och visas som vanligt,
          men <b>ingenting skickas</b> till värmepump, laddbox, batteri, växelriktare eller spabad. Här nedan ser du vad den hade gjort.
          Bra för att prova säkert innan du låter EnergyWizard ta över.</div></div>
        <label class="switch" style="flex:0 0 auto"><input type="checkbox" id="shadowtoggle"><span class="slider"></span></label></div>
      <div id="shadowlist" style="margin-top:10px"></div>
    </div>
    <div class="card" style="margin-bottom:16px" id="signcard" hidden>
      <div style="font-size:1.1rem;font-weight:700">± Effektgivarnas tecken</div>
      <div class="note" style="margin-top:4px">EnergyWizard räknar nätet som <b>+ när du köper</b> och <b>− när du säljer</b>, och batteriet som <b>+ när det laddar</b>. Visar Översikt tvärtom (t.ex. "Köper" när du säljer): vänd tecknet här. Gäller direkt.</div>
      <div id="signbody" style="margin-top:8px"></div>
    </div>
    <div class="card" style="margin-bottom:16px" id="phonecard" hidden>
      <div style="font-size:1.1rem;font-weight:700">📱 Aviseringar till</div>
      <div class="note" style="margin-top:4px">Vilken telefon, notify-tjänst eller vilket skript i Home Assistant som får EnergyWizards aviseringar.</div>
      <div id="phonebody" style="margin-top:10px"></div>
    </div>
    <div class="card" style="margin-bottom:16px" id="notifycard" hidden>
      <div style="font-size:1.1rem;font-weight:700">🔔 Notiser</div>
      <div class="note" style="margin-top:4px">Välj vilka notiser du vill få. Allt går att stänga av.</div>
      <div id="notifybody" style="margin-top:10px"></div>
    </div>
    <div class="card" style="margin-bottom:16px" id="sensorcard" hidden>
      <div style="font-size:1.1rem;font-weight:700">🏠 Givare inne och ute</div>
      <div class="note" style="margin-top:4px">Välj vilka temperaturgivare som visar husets innetemperatur (medianen används när du har tre eller fler) och vilken som sitter ute. Förslagen är markerade ⭐.</div>
      <div id="sensorbody" style="margin-top:10px"></div>
    </div>
    <div class="card" style="margin-bottom:16px" id="pricecard" hidden>
      <div style="font-size:1.1rem;font-weight:700">💶 Elpris och avgifter</div>
      <div class="note" style="margin-top:4px">Gör spotpriset till din verkliga kostnad. Nätavgift, energiskatt och påslag står på elräkningen.</div>
      <div id="pricebody" style="margin-top:10px"></div>
    </div>
    <div class="card" style="margin-bottom:16px" id="batplancard" hidden>
      <div style="font-size:1.1rem;font-weight:700">🔋 Batteriets planering</div>
      <div class="note" style="margin-top:4px">Hur mycket planen litar på prognosen för sol och förbrukning. Säkerhetsgränserna är desamma i alla stilar.</div>
      <div class="seg" id="batstyle" style="margin-top:10px;display:flex;gap:6px;flex-wrap:wrap"></div>
      <div style="display:flex;justify-content:space-between;font-size:.8rem;opacity:.7;margin-top:4px"><span>Sparar mer i batteriet</span><span>Litar mer på prognosen</span></div>
      <div class="note" id="batstyledesc" style="margin-top:8px"></div>
      <label style="display:flex;gap:8px;align-items:flex-start;margin-top:12px"><input type="checkbox" id="batexport">
        <span>Tillåt batteriet att sälja till nätet när planen räknar med en lönsam försäljning.<br><span class="note">Av: batteriet täcker bara husets egen förbrukning. Solelen kan fortfarande säljas.</span></span></label>
    </div>
    <div class="card" style="margin-bottom:16px">
      <div style="font-size:1.1rem;font-weight:700">🌍 Språk / Language</div>
      <div class="note" style="margin-top:4px">Gäller hela installationen och alla enheter som inte valt eget språk.</div>
      <div style="margin-top:10px;display:flex;gap:10px;flex-wrap:wrap;align-items:center"><span id="setlang"></span>
        <a class="icobtn" href="https://github.com/murre87/energywizard/blob/main/TRANSLATING.md" target="_blank" rel="noopener">Hjälp till att översätta</a>
        <button class="icobtn" id="missingbtn" hidden>Ladda ner texter som saknar översättning</button></div>
      <div class="note" style="margin-top:8px">Översättningarna är vanliga textfiler på GitHub. Vem som helst kan rätta en text eller lägga till ett nytt språk.</div>
    </div>
    <div class="card" style="margin-bottom:16px">
      <div style="font-size:1.1rem;font-weight:700">❤️ Sponsra EnergyWizard</div>
      <div class="note" style="margin-top:4px">EnergyWizard är gratis och byggs på fritiden. Ett litet bidrag hjälper till att betala för utvecklingen.</div>
      <div style="margin-top:10px;display:flex;gap:10px;flex-wrap:wrap;align-items:center">
        <a class="icobtn" href="${SPONSOR_URL}" target="_blank" rel="noopener">Sponsra på GitHub</a>
        <label style="display:flex;gap:8px;align-items:center"><input type="checkbox" id="sponsornotice"> Påminn mig en gång i månaden</label></div>
    </div>
    <div class="card" style="margin-bottom:16px" id="hacard" hidden>
      <div style="font-size:1.1rem;font-weight:700">🏠 Home Assistant</div>
      <div class="note" style="margin-top:4px" id="hainfo"></div>
      <button class="icobtn" id="habtn" style="margin-top:10px">Ändra anslutning</button>
    </div>
    <div class="card" style="margin-bottom:16px">
      <div style="font-size:1.1rem;font-weight:700">📡 Sök Modbus-värmepump på nätverket</div>
      <div class="note" style="margin-top:4px">Om din värmepump inte syns i Home Assistant alls (pratar direkt Modbus) kan den här knappen leta upp den på ditt lokala nätverk istället. Kan ta upp till en minut - söker bara, ändrar inget.</div>
      <button class="icobtn" id="scanmodbusbtn" style="margin-top:10px">Sök Modbus-värmepump på nätverket</button>
    </div>
    <div id="modbusScanResults"></div>
    <div id="discoverResults"></div>`;
  document.getElementById("scanbtn").onclick = runDiscovery;
  // #168: senaste skanningen ligger sparad på servern och visas alltid när man kommer tillbaka (även efter att man
  // sparat, och även när Home Assistant-appen startat en ny session)
  try {
    const last = await api("api/discover/last");
    if (last && last.ok && document.getElementById("discoverResults")) {
      await runDiscovery(null, { d: last });
      const r = document.getElementById("discoverResults"), at = new Date((last.scanned_at || 0) * 1000);
      if (r) r.insertAdjacentHTML("afterbegin", `<div class="note" style="margin-bottom:8px"><span>Senaste skanningen</span> ${at.toLocaleString((window.I18N && I18N.lang) || "sv-SE", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}. <span>Kryssa i det som stämmer och tryck</span> <b>Spara och starta</b> – <span>det som är sparat är det EnergyWizard använder. Tryck Skanna för att söka igen.</span></div>`);
    }
  } catch (e) {}
  document.getElementById("scanmodbusbtn").onclick = runModbusScan;
  mountLangSelect("setlang", true);
  mountBatteryPlanSettings();
  mountPriceSettings();
  mountSensorSettings();
  mountSignSettings();
  mountPhoneSetting();
  mountNotifyPrefs();
  mountShadow();
  mountMqtt();
  if (window.I18N && I18N.lang !== "sv") {
    const mb = document.getElementById("missingbtn");
    mb.hidden = false; mb.onclick = () => I18N.downloadMissing();
  }
  api("api/sponsor").then(sp => {
    const cb = document.getElementById("sponsornotice");
    cb.checked = sp.enabled;
    cb.onchange = () => postJSON("api/sponsor/notice", { enabled: cb.checked }).catch(() => { cb.checked = !cb.checked; });
  }).catch(() => {});
  setupStatus().then(st => {
    if (!st || st.supervisor || st.ha_from_env || st.ha_url === undefined) return;
    document.getElementById("hacard").hidden = false;
    document.getElementById("hainfo").textContent = st.ha_ok ? `Kopplat till ${st.ha_url}.` : "Inte kopplat.";
    document.getElementById("habtn").onclick = () => setupHA(3, st.ha_url);
  });
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

// #163/#168: skanningens resultat sparas på servern (api/discover/last) och visas igen när man kommer tillbaka.
// #173: det man valt i guiden (vilka bilar/enheter som är ikryssade, bilarnas namn och batteristorlek) sparas när man
// sparar och fylls i igen när skanningen visas - förut stod guidens förval där (alla ikryssade, gissade namn).
// Nyckeln är enhetens egen entitet/namn, så valen hittar rätt även efter en ny skanning i annan ordning.
const _carKey = (c) => c.soc_entity || c.device_name || "";
function wizardForm() {
  const d = _discovered || {}, f = { cars: {}, chargers: {}, picks: {} };
  (d.cars || []).forEach((c, i) => {
    const on = document.querySelector(`.car-pick[data-i="${i}"]`), id = document.querySelector(`.car-id[data-i="${i}"]`), kwh = document.querySelector(`.car-kwh[data-i="${i}"]`);
    if (on) f.cars[_carKey(c)] = { on: on.checked, id: id ? id.value : "", kwh: kwh ? kwh.value : "" };
  });
  (d.chargers || []).forEach((c, i) => { const cb = document.querySelector(`.charger-pick[data-i="${i}"]`); if (cb) f.chargers[c.device_name || i] = cb.checked; });
  document.querySelectorAll(".pick").forEach((cb) => { f.picks[cb.dataset.cat] = cb.checked; });
  // Elmätarvalen, generisk styrning och direkt anslutning till växelriktare (samma fel som bilarna)
  f.selects = {}; ["pm_main", "pm_export", "pm_second"].forEach((id) => { const e = document.getElementById(id); if (e) f.selects[id] = e.value; });
  f.generic = {}; document.querySelectorAll(".generic-pick").forEach((cb) => { f.generic[cb.dataset.key] = cb.checked; });
  const v = (id) => { const e = document.getElementById(id); return !e ? undefined : e.type === "checkbox" ? e.checked : e.value; };
  f.ftw = { drv: v("ftw_drv"), host: v("ftw_host"), port: v("ftw_port"), unit: v("ftw_unit"), bat: v("ftw_bat"), sol: v("ftw_sol") };
  return f;
}
let _pendingFtw = null;
function applyFtwForm() {
  const f = _pendingFtw, s = document.getElementById("ftw_drv");
  if (!f || !s || !f.drv || ![...s.options].some((o) => o.value === f.drv)) return;
  s.value = f.drv;
  const set = (id, val) => { const e = document.getElementById(id); if (!e || val === undefined) return; if (e.type === "checkbox") e.checked = !!val; else e.value = val; };
  set("ftw_host", f.host); set("ftw_port", f.port); set("ftw_unit", f.unit); set("ftw_bat", f.bat); set("ftw_sol", f.sol);
  _pendingFtw = null;
}
function applyWizardForm(f) {
  if (!f || !_discovered) return;
  (_discovered.cars || []).forEach((c, i) => {
    const s = (f.cars || {})[_carKey(c)]; if (!s) return;
    const on = document.querySelector(`.car-pick[data-i="${i}"]`), id = document.querySelector(`.car-id[data-i="${i}"]`), kwh = document.querySelector(`.car-kwh[data-i="${i}"]`);
    if (on) on.checked = !!s.on; if (id && s.id) id.value = s.id; if (kwh && s.kwh) kwh.value = s.kwh;
  });
  (_discovered.chargers || []).forEach((c, i) => { const v = (f.chargers || {})[c.device_name || i]; const cb = document.querySelector(`.charger-pick[data-i="${i}"]`); if (cb && v != null) cb.checked = !!v; });
  document.querySelectorAll(".pick").forEach((cb) => { const v = (f.picks || {})[cb.dataset.cat]; if (v != null) cb.checked = !!v; });
  Object.entries(f.selects || {}).forEach(([id, val]) => { const e = document.getElementById(id); if (e && [...e.options].some((o) => o.value === val)) e.value = val; });
  document.querySelectorAll(".generic-pick").forEach((cb) => { const v = (f.generic || {})[cb.dataset.key]; if (v != null && cb.checked !== !!v) { cb.checked = !!v; cb.onchange && cb.onchange(); } });
  _pendingFtw = f.ftw || null; applyFtwForm();
}

async function runDiscovery(ev, cached) {
  const results = document.getElementById("discoverResults");
  let d = cached ? cached.d : null;
  if (!d) {
    results.innerHTML = `<div class="placeholder">Skannar... (kan ta en liten stund)</div>`;
    try { d = await api("api/discover", { method: "POST" }); } catch (e) { results.innerHTML = `<div class="placeholder">${e.message}</div>`; return; }
    if (!d.ok) { results.innerHTML = `<div class="placeholder">${d.error}</div>`; return; }
  }
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
      <div class="note" style="margin-top:6px;font-size:.8rem">${fields}</div>${item.note ? `<div class="note" style="margin-top:6px">${esc(item.note)}</div>` : ""}</div>`;
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

  // Enhet utan Home Assistant-integration: Sourcefuls FTW-drivrutin direkt mot enheten (Modbus/HTTP/MQTT)
  html += `<div class="card" style="margin-bottom:16px"><h2>🔌 Batteri eller växelriktare utan Home Assistant-integration</h2>
    <div class="note">Har du t.ex. Pixii, Sungrow, Deye, Sigenergy eller Victron utan integration i Home Assistant kan EnergyWizard läsa den direkt i nätverket med en av Sourcefuls 93 FTW-drivrutiner. Den läses alltid; har drivrutinen styrning kan du låta EnergyWizard styra batteriet (valet nedan).</div>
    <label style="display:flex;flex-direction:column;gap:4px;margin-top:10px"><span class="note">Drivrutin</span><select id="ftw_drv"><option value="">– ingen –</option></select></label>
    <div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:8px">
      <label style="display:flex;flex-direction:column;gap:4px;flex:2 1 160px"><span class="note">IP-adress</span><input id="ftw_host" placeholder="192.168.1.50"></label>
      <label style="display:flex;flex-direction:column;gap:4px;flex:1 1 70px"><span class="note">Port</span><input id="ftw_port" type="number" value="502"></label>
      <label style="display:flex;flex-direction:column;gap:4px;flex:1 1 70px"><span class="note">Enhets-id</span><input id="ftw_unit" type="number" value="1"></label></div>
    <div style="display:flex;gap:14px;margin-top:8px"><label><input type="checkbox" id="ftw_bat"> som husbatteri</label><label><input type="checkbox" id="ftw_sol"> som solceller</label></div>
    <label style="display:flex;gap:8px;align-items:flex-start;margin-top:8px" id="ftw_ctl_row" hidden><input type="checkbox" id="ftw_ctl" style="margin-top:2px">
      <span>Låt EnergyWizard <b>styra</b> batteriet (laddar billigt, laddar ur dyrt). <span class="note">Drivrutinen har styrning men är inte provad på riktig hårdvara – börja i skuggläge.</span></span></label>
    <div class="note" id="ftw_info" style="margin-top:6px"></div></div>`;

  html += `<div class="card" style="margin-bottom:16px"><h2>⚡ Elmätare / Tibber Pulse</h2>
    <div class="note">Krävs för effektvakten, säkringsskyddet och solladdningen. Bäst är en mätare med ström per fas (t.ex. Tibber Pulse); en smartmätare (HAN/P1) med bara effekt fungerar också.</div>
    ${d.power_meter ? `<label style="display:block;margin:8px 0"><input type="checkbox" class="pick" data-cat="Elmätare" checked> Använd ${d.power_meter.driver === "tibber_pulse" ? `Tibber Pulse (${[d.power_meter.entities.import_w ? "köp- och säljeffekt" : "", d.power_meter.entities.current_l1 ? "ström per fas" : ""].filter(Boolean).join(" + ")})` : "effektsensorn " + esc(d.power_meter.entities.power_w)}</label>` : ""}`;
  (d.grid_meters || []).forEach(g => {
    html += `<div class="note" style="margin-top:6px">• ${g.kind === "pulse" ? "Tibber Pulse" : "Smartmätare"}: ${g.power_entity} (${g.maker || "okänt märke"})</div>`;
  });
  if (!(d.grid_meters || []).length) html += `<div class="note" style="margin-top:6px">Ingen hittades.</div>`;
  // Fritt val bland alla effektsensorer i HA (issue #86), plus en valfri mätare för en annan byggnad
  const ps = d.power_sensors || [];
  const opt = (sel0) => ps.map((p) => `<option value="${esc(p.entity)}"${p.entity === sel0 ? " selected" : ""}>${esc(p.name)} (${esc(p.entity)}${p.state != null ? ", " + esc(p.state) + " " + esc(p.unit || "") : ""})</option>`).join("");
  if (ps.length) html += `
    <label style="display:flex;flex-direction:column;gap:4px;margin-top:12px"><span class="note">Elmätare för hela huset (valfri effektsensor, + = köper)</span>
      <select id="pm_main"><option value="">${d.power_meter ? "Förslaget ovan" : "– ingen –"}</option>${opt("")}</select></label>
    <label style="display:flex;flex-direction:column;gap:4px;margin-top:8px"><span class="note">Säljeffekt (valfri – om mätaren har en egen sensor för export, t.ex. Tibber Pulses "effekt produktion"; då räknas sensorn ovan som köp)</span>
      <select id="pm_export"><option value="">– ingen –</option>${opt("")}</select></label>
    <label style="display:flex;flex-direction:column;gap:4px;margin-top:8px"><span class="note">Mätare för en annan byggnad (valfri, t.ex. ett annex - visas, styr inte säkringsskyddet)</span>
      <select id="pm_second"><option value="">– ingen –</option>${opt("")}</select></label>`;
  html += `</div>`;

  html += `<div class="card" style="margin-bottom:16px"><h2>💶 Elpris</h2>
    <div class="note">Varifrån spotpriset hämtas. Utanför Sverige: välj ditt lands prissensor i Home Assistant. Moms och avgifter ställer du in under Elpris och avgifter.</div>
    <div id="discprice" style="margin-top:8px"></div></div>`;

  html += `<button class="icobtn" id="savebtn" style="margin-top:6px;display:none">Spara och starta</button>
    <button class="icobtn" id="genbtn" style="margin-top:6px">Ladda ner house_config.yaml</button>
    <div class="note" id="savemsg" style="margin-top:6px"></div>`;
  results.innerHTML = html;
  mountPriceSource("discprice");
  api("api/ftw-drivers").then((r) => {
    const s = document.getElementById("ftw_drv"); if (!s || !r.ok) return;
    const list = r.drivers.filter((x) => x.capabilities.some((c) => ["battery", "pv", "meter"].includes(c)));
    s.innerHTML += list.map((x) => `<option value="${esc(x.id)}">${esc(x.manufacturer ? x.manufacturer + " – " : "")}${esc(x.name)} (${esc(x.protocol)})</option>`).join("");
    s.onchange = () => { const x = list.find((y) => y.id === s.value); const info = document.getElementById("ftw_info");
      if (!x) { info.textContent = ""; return; }
      document.getElementById("ftw_bat").checked = x.capabilities.includes("battery");
      document.getElementById("ftw_sol").checked = x.capabilities.includes("pv") && !x.capabilities.includes("battery");
      document.getElementById("ftw_port").value = x.protocol === "http" ? 80 : x.protocol === "mqtt" ? 1883 : 502;
      document.getElementById("ftw_ctl_row").hidden = !x.can_control;          // bara drivrutiner med batteristyrning
      info.textContent = `Kan: ${x.capabilities.join(", ")}${x.can_control ? ", styra batteriet" : ""}${x.verification ? " · " + x.verification : ""}`; };
    applyFtwForm();
  }).catch(() => {});
  document.getElementById("genbtn").onclick = () => generateConfig(false);
  document.getElementById("savebtn").onclick = () => generateConfig(true);
  // Spara direkt bara i installationer där install.sh gjort filen skrivbar; annars bara nedladdning.
  fetch("api/house-config-status", { credentials: "same-origin" }).then(r => r.ok ? r.json() : {}).then(st => {
    if (st && st.writable) document.getElementById("savebtn").style.display = "";
  }).catch(() => {});

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
  applyWizardForm(d.form);
}

async function generateConfig(save) {
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
    if (cat === "Elmätare") sel.power_meter = _discovered.power_meter;
  });
  const fd = (document.getElementById("ftw_drv") || {}).value;
  if (fd) sel.ftw = { driver: fd, host: document.getElementById("ftw_host").value.trim(), port: +document.getElementById("ftw_port").value || 502,
    unit_id: +document.getElementById("ftw_unit").value || 1, battery: document.getElementById("ftw_bat").checked, solar: document.getElementById("ftw_sol").checked,
    control: !!(document.getElementById("ftw_ctl") || {}).checked };
  const pmMain = (document.getElementById("pm_main") || {}).value, pmSecond = (document.getElementById("pm_second") || {}).value;
  const pmExport = (document.getElementById("pm_export") || {}).value;
  if (pmMain) sel.power_meter = pmExport ? { driver: "import_export", entities: { import_w: pmMain, export_w: pmExport } } : { driver: "power_w", entities: { power_w: pmMain } };
  if (pmSecond) sel.power_meter = { ...(sel.power_meter || { driver: "power_w", entities: {} }), secondary_power_w: pmSecond };

  if (save) {
    const msg = document.getElementById("savemsg");
    msg.textContent = "Sparar…";
    const rs = await fetch("api/save-house-config", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify(sel) });
    const j = await rs.json().catch(() => ({}));
    msg.textContent = rs.ok ? j.message : ("Kunde inte spara: " + (j.error || rs.status));
    if (rs.ok) postJSON("api/discover/form", wizardForm()).catch(() => {});      // #173: valen visas igen nästa gång
    return;
  }
  const r = await fetch("api/generate-house-config", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify(sel) });
  if (r.ok) postJSON("api/discover/form", wizardForm()).catch(() => {});
  if (!r.ok) { alert("Kunde inte generera filen: " + (await r.json().catch(() => ({}))).error); return; }
  const blob = await r.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = "house_config.yaml"; a.click();
  URL.revokeObjectURL(url);
}

function openPage(id) {
  // #161: en dold flik (utrustning installationen inte har) öppnar Översikt i stället för en tom sida
  if (PAGES.length && id !== "oversikt" && !PAGES.some((p) => p.id === id)) id = "oversikt";
  currentPage = id;
  renderSidebar();
  closeMobileMenu();
  if (id === "oversikt") {
    renderOversikt();
  } else if (id === "varmepump") {
    renderVarmepump();
  } else if (id === "system") {
    renderSystem();
  } else if (id === "installationer") {
    renderInstalls();
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
  } else if (id === "logg") {
    renderLogg();
  } else {
    document.getElementById("main").innerHTML = `<div class="placeholder">"${PAGES.find(p => p.id === id)?.name}" byggs i en senare fas.</div>`;
  }
}

// ---------- Startguiden (första start): lösenord -> Home Assistant -> prylar ----------
async function setupStatus() {
  try { const r = await fetch("api/setup/status", { credentials: "same-origin" }); return r.ok ? r.json() : null; }
  catch (e) { return null; }
}

function showSetup(step, total, title, bodyHtml, btnText, onSubmit) {
  document.getElementById("login").classList.remove("off");
  document.getElementById("shell").classList.remove("on");
  document.getElementById("loginform").style.display = "none";
  const f = document.getElementById("setupform");
  f.style.display = "";
  document.getElementById("setupstep").textContent = `Steg ${step} av ${total}: ${title}`;
  document.getElementById("setupbody").innerHTML = bodyHtml;
  document.getElementById("setuperr").textContent = "";
  document.getElementById("setupok").textContent = "";
  const btn = document.getElementById("setupbtn");
  btn.textContent = btnText;
  btn.disabled = false;
  f.onsubmit = async (e) => {
    e.preventDefault();
    btn.disabled = true;
    document.getElementById("setuperr").textContent = "";
    try { await onSubmit(); } catch (err) { document.getElementById("setuperr").textContent = err.message || String(err); btn.disabled = false; }
  };
  const first = f.querySelector("input"); if (first) first.focus();
}

function hideSetup() {
  document.getElementById("setupform").style.display = "none";
  document.getElementById("loginform").style.display = "";
}

async function postJSON(path, body) {
  const r = await fetch(path, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail || j.error || r.statusText || `Servern svarade med fel ${r.status}`);
  return j;
}

function setupPassword(total) {
  mountLangSelect("setuplang", true);
  showSetup(1, total, "välj lösenord",
    `<div class="note">Lösenordet skyddar webben och mobilappen. Logga in med det sedan (användarnamn behövs inte).</div>
     <input type="password" id="s_pw" placeholder="Lösenord, minst 8 tecken" autocomplete="new-password" required minlength="8">
     <input type="password" id="s_pw2" placeholder="Samma lösenord igen" autocomplete="new-password" required>`,
    "Spara lösenord", async () => {
      const a = document.getElementById("s_pw").value, b = document.getElementById("s_pw2").value;
      if (a !== b) throw new Error("Lösenorden är inte lika.");
      await postJSON("api/setup/password", { password: a });
      boot();
    });
}

function setupHA(total, prev) {
  showSetup(2, total, "koppla Home Assistant",
    `<div class="note">EnergyWizard läser och styr allt via Home Assistant.</div>
     <input type="text" id="s_url" placeholder="Adress, t.ex. 192.168.1.10 eller http://homeassistant.local:8123" value="${esc(prev || "")}" required>
     <input type="password" id="s_tok" placeholder="Token" required>
     <details class="note"><summary>Var hittar jag token?</summary>
       I Home Assistant: klicka på ditt namn längst ner till vänster, välj fliken <b>Säkerhet</b>,
       scrolla längst ner till <b>Långlivade åtkomsttoken</b> och tryck <b>Skapa token</b>. Kopiera den och klistra in här.
     </details>
     <details class="note"><summary>Vad skickas till utvecklaren?</summary>
       <p style="margin:6px 0">En gång per dygn: vilken utrustning du har (drivrutin, märke och modell, t.ex. "NIBE S1255"), var innetemperaturen kommer ifrån, priskälla och land, ungefärliga storlekar (t.ex. batteri 10–15 kWh, huvudsäkring 25 A), inne- och utetemperatur i hela grader och om skuggläget, batteristyrningen eller tidstariffen är på. Vid fel: var i koden felet uppstod och vilken typ, aldrig feltexten. Felen blir automatiskt ärenden på GitHub så att de kan rättas. Aldrig namn, adress, entiteter eller andra mätvärden.</p><p style="margin:6px 0">Telemetrin är alltid påslagen i EnergyWizards byggen och har ingen avstängning. Koden är fri under AGPL-3.0: du får ändra den, även ta bort telemetrin, och sprida den ändrade versionen enligt licensen.</p></details>`,
    "Testa och spara", async () => {
      const j = await postJSON("api/setup/ha", { url: document.getElementById("s_url").value, token: document.getElementById("s_tok").value });
      document.getElementById("setupok").textContent = j.message || "Kopplat!";
      setTimeout(boot, 900);
    });
}

async function boot() {
  const st = await setupStatus();
  const total = st && st.supervisor ? 2 : 3;
  if (st && st.needs_password) { setupPassword(total); return; }
  try {
    const me = await api("api/me");
    if (!me.role) { showLogin(); return; }
    hideSetup();
    PAGES = me.pages;
    moneyCurrency = me.currency || "SEK";
    moneySymbol = me.currency_symbol || "kr";
    if (st && me.role === "owner" && !st.ha_ok && !st.supervisor) { setupHA(total, st.ha_url); return; }
    showShell();
    if (me.role === "owner") showSponsorBanner();
    if (st && me.role === "owner" && !st.devices_chosen) { openPage("installningar"); return; }
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
