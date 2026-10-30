const STATS_URL = new URL("data/stats.json", document.currentScript.src);
const ZONES_URL = new URL("data/price_zones.json", document.currentScript.src);
const LANG = document.documentElement.lang === "en" ? "en" : "sv";

const T = {
  sv: {
    err: "Kunde inte läsa siffrorna just nu.",
    savedSince: (since, days) => `Sparat sen ${since} (${days} dagar verklig drift)`,
    total: "totalt",
    breakdown: (timing, solar) => `Varav ${timing} kr prisoptimering + ${solar} kr egenanvänd solel`,
    avg: (v) => `Snitt ${v} kr/år hittills`,
    solarTitle: "☀️ Solel använd i huset",
    solarLine: (kwh, kr) => `${kwh} kWh egenanvänd solel, värd ${kr} kr till rådande elpris`,
    flexLine: (ev, spa, kr) => `Varav ${ev} kWh elbilsladdning + ${spa} kWh spabad specifikt under soleverskott (${kr} kr)`,
    heating: "♨️ Värmestyrning (preheat/coast)",
    heatingLine: (pct, days) => `${pct}% lägre kostnad i backtest, ${days} dagars fönster`,
    heatingNone: "Ingen mätning tillgänglig än",
    earlySeason: "Tidig säsong - väntas växa när vintern kommer",
    monthTitle: "📈 Trend månad för månad",
    monthNote: "Ingen vinterprognos - bara den riktiga trenden hittills. Prisoptimeringen ökar tydligt när elpriserna blir mer volatila på hösten.",
    monthCol: "Månad", timingCol: "Prisoptimering", solarCol: "Solel",
    locale: "sv-SE",
    zoneTitle: "📍 Elpriser per elområde (3 års snitt)",
    zoneNote: (since) => `Verkliga spotpriser sen ${since} - inte en uppskattning. Våra siffror ovan är från vårt eget hus i SE3. Ju större skillnad mellan dygnets billigaste och dyraste timme ("dygnsspridning"), desto mer finns det att vinna på att flytta förbrukningen - prisoptimeringens potential är alltså störst i SE3/SE4, inte i SE1/SE2.`,
    zoneCol: "Område", zoneAvgCol: "Snittpris", zoneRangeCol: "Dygnsspridning (snitt)",
    zoneHome: "(vårt hus)",
  },
  en: {
    err: "Couldn't load the numbers right now.",
    savedSince: (since, days) => `Saved since ${since} (${days} days of real operation)`,
    total: "total",
    breakdown: (timing, solar) => `Of which ${timing} kr price timing + ${solar} kr self-consumed solar`,
    avg: (v) => `Avg. ${v} kr/year so far`,
    solarTitle: "☀️ Solar power used in the house",
    solarLine: (kwh, kr) => `${kwh} kWh of self-consumed solar, worth ${kr} kr at the live price`,
    flexLine: (ev, spa, kr) => `Of which ${ev} kWh EV charging + ${spa} kWh spa heating specifically during solar surplus (${kr} kr)`,
    heating: "♨️ Heat control (preheat/coast)",
    heatingLine: (pct, days) => `${pct}% lower cost in backtest, ${days}-day window`,
    heatingNone: "No measurement available yet",
    earlySeason: "Early season - expected to grow once winter arrives",
    monthTitle: "📈 Month-by-month trend",
    monthNote: "No winter forecast - just the real trend so far. Price timing savings clearly rise as electricity prices get more volatile in autumn.",
    monthCol: "Month", timingCol: "Price timing", solarCol: "Solar",
    locale: "en-SE",
    zoneTitle: "📍 Electricity prices by price zone (3-year average)",
    zoneNote: (since) => `Real spot prices since ${since} - not an estimate. Our numbers above are from our own house in SE3. The bigger the gap between a day's cheapest and most expensive hour ("daily spread"), the more there is to gain from shifting consumption - so price-timing potential is biggest in SE3/SE4, not SE1/SE2.`,
    zoneCol: "Zone", zoneAvgCol: "Average price", zoneRangeCol: "Daily spread (avg)",
    zoneHome: "(our house)",
  },
}[LANG];

async function loadStats() {
  try {
    const r = await fetch(STATS_URL, { cache: "no-store" });
    const d = await r.json();
    render(d);
  } catch (e) {
    document.getElementById("stats").innerHTML = `<div class="card"><div class="note">${T.err}</div></div>`;
  }
  const zonesEl = document.getElementById("zones");
  if (zonesEl) {
    try {
      const r = await fetch(ZONES_URL, { cache: "no-store" });
      renderZones(await r.json());
    } catch (e) {
      zonesEl.innerHTML = "";
    }
  }
}

function renderZones(z) {
  const el = document.getElementById("zones");
  const rows = Object.entries(z.zones).map(([name, v]) =>
    `<tr><td>${name}${name === "SE3" ? ` <span class="tag">${T.zoneHome}</span>` : ""}</td><td>${v.avg_sek_per_kwh.toFixed(2)} kr</td><td>${v.avg_daily_range_sek_per_kwh.toFixed(2)} kr</td></tr>`
  ).join("");
  el.innerHTML = `
    <div class="card" style="grid-column:1/-1">
      <h3>${T.zoneTitle}</h3>
      <div class="note">${T.zoneNote(new Date(z.since).toLocaleDateString(T.locale))}</div>
      <table class="monthtable">
        <thead><tr><th>${T.zoneCol}</th><th>${T.zoneAvgCol}</th><th>${T.zoneRangeCol}</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}

function render(d) {
  const since = d.since ? new Date(d.since).toLocaleDateString(T.locale) : "–";
  const el = document.getElementById("stats");
  el.innerHTML = `
    <div class="card">
      <div class="note">${T.savedSince(since, d.days_covered)}</div>
      <div class="stat">${d.total_saved_kr.toFixed(0)} kr <small>${T.total}</small></div>
      <div class="note">${T.breakdown(d.price_timing_saved_kr.toFixed(0), d.solar ? d.solar.value_kr.toFixed(0) : "0")}</div>
      <span class="tag">${T.avg(d.saved_kr_per_year_avg.toFixed(0))}</span>
    </div>
    ${d.solar ? `
    <div class="card">
      <h3>${T.solarTitle}</h3>
      <div class="note">${T.solarLine(d.solar.kwh.toFixed(0), d.solar.value_kr.toFixed(0))}</div>
      ${d.solar_flexible_load ? `<div class="note" style="margin-top:6px">${T.flexLine(d.solar_flexible_load.ev_kwh.toFixed(0), d.solar_flexible_load.spa_kwh.toFixed(0), d.solar_flexible_load.value_kr.toFixed(0))}</div>` : ""}
    </div>` : ""}
    <div class="card">
      <h3>${T.heating}</h3>
      <div class="note">${d.heating ? T.heatingLine(d.heating.saving_pct.toFixed(0), d.heating.days_used) : T.heatingNone}</div>
      ${d.heating && d.heating.early_season ? `<span class="tag warn">${T.earlySeason}</span>` : ""}
    </div>
    ${d.monthly && d.monthly.length ? `
    <div class="card" style="grid-column:1/-1">
      <h3>${T.monthTitle}</h3>
      <div class="note">${T.monthNote}</div>
      <table class="monthtable">
        <thead><tr><th>${T.monthCol}</th><th>${T.timingCol}</th><th>${T.solarCol}</th></tr></thead>
        <tbody>${d.monthly.map(m => `<tr><td>${m.month}</td><td>${m.timing_kr.toFixed(0)} kr</td><td>${m.solar_kr.toFixed(0)} kr</td></tr>`).join("")}</tbody>
      </table>
    </div>` : ""}`;
}

loadStats();
