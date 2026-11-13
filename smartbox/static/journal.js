/* journal.js - "Höll vi planen?", delad av webben (Historik) och mobilappen (Historik).
 *
 * Data: api/control-journal?back=0|1 (smartbox/control_journal.py): per enhet hur stor del av minuterna den gjorde det
 * EnergyWizard beställde, och när den inte gjorde det. Samma kod i båda gränssnitten, bara storleken skiljer.
 *   EWJournal.html(data, { compact: true|false, back: 0|1 })
 * Knapparna Idag/Igår har data-jback="0|1"; gränssnittet hämtar om och ritar.
 */
(function () {
  "use strict";
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const LOC = () => (window.I18N && I18N.lang && I18N.lang !== "sv" ? (I18N.lang === "en" ? "en-GB" : I18N.lang) : "sv-SE");
  const hm = (iso) => new Date(iso).toLocaleTimeString(LOC(), { hour: "2-digit", minute: "2-digit", timeZone: "Europe/Stockholm" });
  const dur = (m) => m >= 60 ? `${Math.floor(m / 60)} h${m % 60 ? ` ${m % 60} min` : ""}` : `${m} min`;
  const col = (p) => p == null ? "var(--mut)" : p >= 95 ? "var(--acc, #22d3a0)" : p >= 80 ? "#fbbf24" : "#ef4444";

  function html(d, opts) {
    opts = opts || {};
    const c = !!opts.compact, back = opts.back == null ? 1 : opts.back;
    const seg = `<div class="seg" style="margin:6px 0 10px">${[[0, "Idag"], [1, "Igår"]].map(([k, l]) => `<button data-jback="${k}" class="${back === k ? "on" : ""}">${l}</button>`).join("")}</div>`;
    const devs = (d && d.devices) || [];
    let body;
    if (!devs.length) {
      body = `<div class="note">Inget att visa ${back ? "för igår" : "än idag"}. Journalen fylls varje minut när EnergyWizard styr (inte i skuggläge).</div>`;
    } else {
      body = devs.map((x) => {
        const p = x.pct, h = (x.minutes / 60);
        const head = `<div style="display:flex;justify-content:space-between;align-items:baseline;gap:8px">
          <b>${esc(x.device)}</b><span style="font-weight:800;font-size:${c ? 1.05 : 1.2}rem;color:${col(p)}">${p == null ? "–" : p + " %"}</span></div>
          <div style="height:6px;border-radius:3px;background:var(--line);margin:4px 0 2px;overflow:hidden"><div style="height:100%;width:${p || 0}%;background:${col(p)}"></div></div>
          <div class="note" style="margin:0"><span>Gjorde som planen ${h >= 1 ? `${h.toFixed(h < 10 ? 1 : 0).replace(".", ",")} h` : `${x.minutes} min`} kontrollerat</span>${x.deviation_minutes ? `, <span>avvek ${dur(x.deviation_minutes)}</span>` : ""}</div>`;
        const list = (x.deviations || []).map((v) => `<div style="display:flex;gap:10px;padding:4px 0;border-top:1px solid var(--line)">
          <span style="white-space:nowrap;color:var(--mut)">${hm(v.start)}–${hm(v.end)}</span>
          <span>${esc(v.note || "Avvek")}${v.ordered ? ` <span style="color:var(--mut)">(beställt ${esc(v.ordered)}, blev ${esc(v.actual)})</span>` : ""}</span></div>`).join("");
        return `<div style="padding:8px 0">${list ? `<details><summary style="list-style:none;cursor:pointer">${head}</summary><div style="margin-top:6px;font-size:${c ? .85 : .9}rem">${list}</div></details>` : head}</div>`;
      }).join("");
    }
    const title = c ? `<b>Höll vi planen?</b>` : `<h2>✅ Höll vi planen?</h2>`;
    return `${title}<div class="note" style="margin:2px 0 0">Det EnergyWizard beställde jämfört med vad enheterna gjorde, minut för minut. Tryck på en enhet för att se när den avvek.</div>${seg}${body}`;
  }
  // Aviseringshistorik (api/notify-log, smartbox/notify_log.py): vad som skickades, till vem och hur det gick
  const SCOL = { sent: "var(--acc, #22d3a0)", failed: "#ef4444", muted: "var(--mut)", none: "#fbbf24" };
  function notifyHtml(d, opts) {
    opts = opts || {};
    const c = !!opts.compact, rows = (d && d.rows) || [];
    const title = c ? `<b>Skickade aviseringar</b>` : `<h2>📨 Skickade aviseringar</h2>`;
    const intro = `<div class="note" style="margin:2px 0 6px">Senaste 7 dygnen. "Skickad" betyder att Home Assistant tog emot den och skickade den vidare till telefonen.</div>`;
    if (!rows.length) return `${title}${intro}<div class="note">Inga aviseringar än.</div>`;
    const day = (iso) => new Date(iso).toLocaleString(LOC(), { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Stockholm" });
    return `${title}${intro}` + rows.slice(0, c ? 40 : 100).map((r) => `<details style="padding:6px 0;border-top:1px solid var(--line)">
      <summary style="list-style:none;cursor:pointer;display:flex;gap:8px;align-items:baseline;justify-content:space-between">
        <span style="min-width:0;overflow-wrap:anywhere"><span style="color:var(--mut);font-size:.85em">${esc(day(r.ts))}</span><br><b>${esc(r.title)}</b></span>
        <span style="white-space:nowrap;font-size:.85em;font-weight:700;color:${SCOL[r.status] || "var(--mut)"}">${esc(r.status_text)}</span></summary>
      <div style="font-size:.9em;margin-top:4px;overflow-wrap:anywhere">${esc(r.message)}</div>
      <div class="note" style="margin:2px 0 0">${[r.category, r.recipient ? "till " + r.recipient : "", r.src === "appen" ? "från appen" : "", r.detail].filter(Boolean).map((x) => `<span>${esc(x)}</span>`).join(" · ")}</div></details>`).join("");
  }
  // Elbilsladdningens energi och kostnad (api/ev-cost, smartbox/ev_cost.py)
  function evCostHtml(d, opts) {
    opts = opts || {};
    const c = !!opts.compact, P = (d && d.periods) || {};
    if (!P.today) return "";
    const n1 = (x) => (Math.round(x * 10) / 10).toFixed(x >= 100 ? 0 : 1).replace(".", ",");
    const cell = (k, l) => { const p = P[k]; return `<div style="flex:1;min-width:0">
      <div class="note" style="margin:0">${l}${p.partial ? ` <span title="Loggen har luckor, siffran är för låg">· delvis</span>` : ""}</div>
      <div style="font-weight:800;font-size:${c ? 1.05 : 1.25}rem">${p.kr} ${esc(opts.unit || "kr")}</div>
      <div class="note" style="margin:0">${n1(p.kwh)} kWh${p.solar_kwh >= 0.5 ? `, ${n1(p.solar_kwh)} från solen` : ""}</div></div>`; };
    const title = c ? `<b>Laddat</b>` : `<h2>🔌 Laddat och vad det kostade</h2>`;
    return `${title}<div style="display:flex;gap:10px;margin-top:6px">${cell("today", "Idag")}${cell("week", "Veckan")}${cell("month", "Månaden")}</div>
      <div class="note" style="margin-top:6px">Från nätet till full köpkostnad, från solen till vad den annars hade sålts för. Alla bilar tillsammans.</div>`;
  }
  window.EWJournal = { html, notifyHtml, evCostHtml };
})();
