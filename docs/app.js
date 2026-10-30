const STATS_URL = new URL("data/stats.json", document.currentScript.src);
const LANG = document.documentElement.lang === "en" ? "en" : "sv";

const T = {
  sv: {
    err: "Kunde inte läsa siffrorna just nu.",
    savedSince: (since, days) => `Sparat sen ${since} (${days} dagar verklig drift)`,
    total: "totalt",
    kwh: (kwh) => `${kwh} kWh köpt el, styrd efter elpris i stället för fast`,
    avg: (v) => `Snitt ${v} kr/år hittills`,
    heating: "♨️ Värmestyrning (preheat/coast)",
    heatingLine: (pct, days) => `${pct}% lägre kostnad i backtest, ${days} dagars fönster`,
    heatingNone: "Ingen mätning tillgänglig än",
    earlySeason: "Tidig säsong - väntas växa när vintern kommer",
    locale: "sv-SE",
  },
  en: {
    err: "Couldn't load the numbers right now.",
    savedSince: (since, days) => `Saved since ${since} (${days} days of real operation)`,
    total: "total",
    kwh: (kwh) => `${kwh} kWh of electricity bought, priced-controlled instead of flat`,
    avg: (v) => `Avg. ${v} kr/year so far`,
    heating: "♨️ Heat control (preheat/coast)",
    heatingLine: (pct, days) => `${pct}% lower cost in backtest, ${days}-day window`,
    heatingNone: "No measurement available yet",
    earlySeason: "Early season - expected to grow once winter arrives",
    locale: "en-SE",
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
}

function render(d) {
  const since = d.since ? new Date(d.since).toLocaleDateString(T.locale) : "–";
  const el = document.getElementById("stats");
  el.innerHTML = `
    <div class="card">
      <div class="note">${T.savedSince(since, d.days_covered)}</div>
      <div class="stat">${d.total_saved_kr.toFixed(0)} kr <small>${T.total}</small></div>
      <div class="note">${T.kwh(d.total_kwh_bought.toFixed(0))}</div>
      <span class="tag">${T.avg(d.saved_kr_per_year_avg.toFixed(0))}</span>
    </div>
    <div class="card">
      <h3>${T.heating}</h3>
      <div class="note">${d.heating ? T.heatingLine(d.heating.saving_pct.toFixed(0), d.heating.days_used) : T.heatingNone}</div>
      ${d.heating && d.heating.early_season ? `<span class="tag warn">${T.earlySeason}</span>` : ""}
    </div>`;
}

loadStats();
