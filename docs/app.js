async function loadStats() {
  try {
    const r = await fetch("data/stats.json", { cache: "no-store" });
    const d = await r.json();
    render(d);
  } catch (e) {
    document.getElementById("stats").innerHTML = `<div class="card"><div class="note">Kunde inte läsa siffrorna just nu.</div></div>`;
  }
}

function render(d) {
  const since = d.since ? new Date(d.since).toLocaleDateString("sv-SE") : "–";
  const el = document.getElementById("stats");
  el.innerHTML = `
    <div class="card">
      <div class="note">Sparat sen ${since} (${d.days_covered} dagar verklig drift)</div>
      <div class="stat">${d.total_saved_kr.toFixed(0)} kr <small>totalt</small></div>
      <div class="note">${d.total_kwh_bought.toFixed(0)} kWh köpt el, styrd efter elpris i stället för fast</div>
      <span class="tag">Snitt ${d.saved_kr_per_year_avg.toFixed(0)} kr/år hittills</span>
    </div>
    <div class="card">
      <h3>♨️ Värmestyrning (preheat/coast)</h3>
      <div class="note">${d.heating ? `${d.heating.saving_pct.toFixed(0)}% lägre kostnad i backtest, ${d.heating.days_used} dagars fönster` : "Ingen mätning tillgänglig än"}</div>
      ${d.heating && d.heating.early_season ? `<span class="tag warn">Tidig säsong - väntas växa när vintern kommer</span>` : ""}
    </div>`;
}

loadStats();
