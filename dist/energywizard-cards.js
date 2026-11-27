/*
 * EnergyWizard-kort för Home Assistant.
 *
 * Läser EN sensor, sensor.energywizard_kort, som EnergyWizard publicerar (smartbox/ha_card_feed.py). Fungerar likadant
 * för HA-tillägget och Docker: kortet når aldrig EnergyWizards egen webb. Inga beroenden, bara webbkomponenter.
 *
 *   type: custom:energywizard-house-card
 *   entity: sensor.energywizard_kort     # valfritt, det här är standard
 *   title: Hemmet                        # valfritt
 *   tab: now                             # now | plan | cars (startflik, valfritt)
 *   language: sv                         # sv | en, annars HA:s språk
 *
 * Sol och batteri: type: custom:energywizard-battery-card
 *   Läser solar (produktion och prognos) och batt (laddnivå, effekt, plan) på samma sensor.
 *
 * Tider visas alltid som 24-timmarsklocka (TT:MM), aldrig AM/PM.
 */
const EW_VERSION = "0.1.0";

const EW_TEXT = {
  sv: { now: "Nu", plan: "Plan", cars: "Bilar", cheap: "billigt", dear: "dyrt", unknown: "okänt", noData: "Ingen data från EnergyWizard än.",
        missing: (e) => `Hittar inte ${e}. Är EnergyWizard uppdaterad och kopplad till Home Assistant?`, stale: "Gammal data", clock: "Klocka", skyline: "Skyline",
        heat: "Värme", water: "Varmvatten", outdoor: "Ute", setpoint: "Börvärde", within: "inom", cheapUntil: (h) => `Billigt till ${h}`, dearUntil: (h) => `Dyrt till ${h}`, thenCheap: "sedan billigt", thenDear: "sedan dyrt", noHeat: "Ingen värmedata än.", noPlan: "Inget planerat pass", plannedAt: "Planerad laddning", battery: "Laddnivå", notCharging: "Laddar inte", modes: { "Auto": "Auto", "Ladda nu": "Ladda nu", "Pausa": "Pausa" }, modeHint: "Auto = AI-schemat styr. Ladda nu laddar tills bilen är full eller kabeln dras ur.",
        perKwh: "kWh", price: "Pris nu", cheapest: "Billigast", dearest: "Dyrast", sun: "Sol", charging: "Laddar", noCars: "Inga elbilar i installationen.",
        why: "Varför", house: "Hemmet", ago: (m) => `${m} min sedan`,
        solarBattery: "Sol och batteri", sunNow: "Sol nu", forecastToday: "Prognos idag", forecastTomorrow: "Imorgon",
        batteryName: "Batteri", powerNow: "Effekt nu", noPlant: "Ingen sol eller batteri i installationen.", noBatPlan: "Ingen plan",
        forecastNote: "Prognosen är resten av dagens och morgondagens plan, inte ett helt dygn.",
        batPlan: { charge: "Laddar", discharge: "Laddar ur", hold: "Sparar", idle: "Vilar", export: "Säljer", auto: "Självförbrukning", standby: "Standby" } },
  en: { now: "Now", plan: "Plan", cars: "Cars", cheap: "cheap", dear: "expensive", unknown: "unknown", noData: "No data from EnergyWizard yet.",
        missing: (e) => `Cannot find ${e}. Is EnergyWizard updated and connected to Home Assistant?`, stale: "Old data", clock: "Clock", skyline: "Skyline",
        heat: "Heating", water: "Hot water", outdoor: "Outdoors", setpoint: "Setpoint", within: "within", cheapUntil: (h) => `Cheap until ${h}`, dearUntil: (h) => `Expensive until ${h}`, thenCheap: "then cheap", thenDear: "then expensive", noHeat: "No heating data yet.", noPlan: "No planned session", plannedAt: "Planned charging", battery: "Charge level", notCharging: "Not charging", modes: { "Auto": "Auto", "Ladda nu": "Charge now", "Pausa": "Pause" }, modeHint: "Auto = the AI plan decides. Charge now charges until the car is full or the cable is unplugged.",
        perKwh: "kWh", price: "Price now", cheapest: "Cheapest", dearest: "Most expensive", sun: "Sun", charging: "Charging", noCars: "No EVs in the installation.",
        why: "Why", house: "House", ago: (m) => `${m} min ago`,
        solarBattery: "Solar and battery", sunNow: "Solar now", forecastToday: "Forecast today", forecastTomorrow: "Tomorrow",
        batteryName: "Battery", powerNow: "Power now", noPlant: "No solar or battery in the installation.", noBatPlan: "No plan",
        forecastNote: "The forecast is the rest of today's and tomorrow's plan, not a full day.",
        batPlan: { charge: "Charging", discharge: "Discharging", hold: "Saving", idle: "Idle", export: "Selling", auto: "Self-consumption", standby: "Standby" } },
};

// Färg per nod. Följer HA:s tema för text och bakgrund, men energifärgerna är desamma i ljust och mörkt.
const EW_COLOR = { sol: "#f5b301", nat: "#8e6bd8", hus: "#7b61ff", varmepump: "#ef5350", varmvatten: "#29a3f5", spabad: "#26c6da", ev: "#ff9f1a", batteri: "#2ec4a6" };
const colorOf = (k) => EW_COLOR[k] || (String(k).startsWith("ev_") ? EW_COLOR.ev : "#9aa0a6");

const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const hhmm = (epoch) => { const d = new Date(epoch * 1000); return String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0"); };
const kw = (w) => (Math.abs(w) >= 100 ? (w / 1000).toFixed(1) : "0.0") + " kW";
const fmtPrice = (p, unit) => (p == null ? "–" : p.toFixed(2).replace(".", ",") + " " + unit + "/kWh");

const STYLE = `
:host { display:block; color:var(--primary-text-color, #e1e1e1); }
ha-card { overflow:hidden; --ew-line: var(--divider-color, rgba(127,127,127,.25)); --ew-mut: var(--secondary-text-color, #8a8f98); }
.head { display:flex; align-items:center; gap:10px; padding:14px 16px 4px; }
.bolt { width:22px; height:22px; flex:none; }
.title { font-size:1.05rem; font-weight:600; color:var(--primary-text-color); }
.sub { color:var(--ew-mut); font-size:.85rem; margin-left:2px; }
.spacer { flex:1; }
.chip { font-size:.78rem; padding:3px 10px; border-radius:999px; font-weight:600; background:rgba(127,127,127,.15); color:var(--primary-text-color); white-space:nowrap; }
.chip.cheap { background:rgba(46,196,166,.18); color:#1fa88c; } .chip.dear { background:rgba(239,83,80,.16); color:#e0443f; }
.tabs { display:flex; margin-top:8px; border-bottom:1px solid var(--ew-line); }
.tab { flex:1; text-align:center; padding:10px 4px; font-size:.85rem; cursor:pointer; color:var(--ew-mut); border-bottom:2px solid transparent; user-select:none; background:none; border-top:0; border-left:0; border-right:0; font-family:inherit; }
.tab.on { color:var(--primary-color, #03a9f4); border-bottom-color:var(--primary-color, #03a9f4); font-weight:600; }
.body { padding:8px 12px 14px; }
.msg { padding:18px 16px; color:var(--ew-mut); }
svg { width:100%; height:auto; display:block; }
svg text { font-family: var(--paper-font-body1_-_font-family, system-ui, sans-serif); fill: var(--primary-text-color); }
.m { fill: var(--ew-mut) !important; }
.node-w { font-size:12px; font-weight:700; } .node-l { font-size:10.5px; } .node-d { font-size:9.5px; }
@keyframes ew-flow { to { stroke-dashoffset: -18.2; } }
.flow { stroke-dasharray: 0.1 9; stroke-linecap: round; stroke-width: 4; animation: ew-flow 1.1s linear infinite; fill:none; }
.flow.off { animation:none; stroke-dasharray:none; opacity:.18; stroke-width:2; }
@media (prefers-reduced-motion: reduce) { .flow { animation:none; } }
.why { margin:6px 4px 0; color:var(--ew-mut); font-size:.82rem; line-height:1.35; }
.row { display:flex; align-items:center; gap:10px; padding:10px 6px; border-top:1px solid var(--ew-line); }
.row:first-child { border-top:0; }
.dot { width:10px; height:10px; border-radius:50%; flex:none; background:#9aa0a6; } .dot.on { background:#2ec4a6; box-shadow:0 0 0 4px rgba(46,196,166,.18); }
.row .n { font-weight:600; color:var(--primary-text-color); } .row .d { color:var(--ew-mut); font-size:.85rem; }
.soc { height:6px; border-radius:3px; background:rgba(127,127,127,.2); margin:6px 0 2px; overflow:hidden; } .soc div { height:100%; border-radius:3px; }
.b-l { font-size:11px; font-weight:700; letter-spacing:.2px; } .b-w { font-size:17px; font-weight:700; } .b-u { font-size:10px; font-weight:500; opacity:.7; } .b-s { font-size:9.5px; }
.seg { display:flex; gap:6px; justify-content:flex-end; padding:6px 4px 2px; }
.seg button { font:inherit; font-size:.72rem; letter-spacing:.5px; padding:4px 12px; border-radius:999px; border:1px solid var(--ew-line); background:none; color:var(--ew-mut); cursor:pointer; }
.seg button.on { color:var(--primary-text-color); border-color:var(--primary-text-color); }
.legend { display:flex; gap:14px; flex-wrap:wrap; padding:2px 6px 0; color:var(--ew-mut); font-size:.78rem; }
.legend i { display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:5px; vertical-align:-1px; }
`;

class EnergyWizardHouseCard extends HTMLElement {
  setConfig(config) {
    this._config = { entity: "sensor.energywizard_kort", tab: "now", ...(config || {}) };
    this._tab = this._config.tab;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this._render();
  }
  set hass(hass) {
    this._hass = hass;
    const st = hass && hass.states ? hass.states[this._config.entity] : null;
    const key = st ? st.last_updated + "|" + (st.attributes && st.attributes.ts) : "missing";
    if (key !== this._key) { this._key = key; this._render(); }
  }
  getCardSize() { return 6; }
  static getStubConfig() { return { entity: "sensor.energywizard_kort" }; }

  _t() {
    const lang = (this._config.language || (this._hass && (this._hass.language || (this._hass.locale && this._hass.locale.language))) || "sv").slice(0, 2);
    return EW_TEXT[lang] || EW_TEXT.sv;
  }

  _render() {
    if (!this.shadowRoot || !this._config) return;
    const t = this._t();
    const st = this._hass && this._hass.states ? this._hass.states[this._config.entity] : null;
    let inner;
    if (!this._hass) inner = `<div class="msg">…</div>`;
    else if (!st) inner = `<div class="msg">${esc(t.missing(this._config.entity))}</div>`;
    else inner = this._card(st, t);
    this.shadowRoot.innerHTML = `<style>${STYLE}</style><ha-card>${inner}</ha-card>`;
    this.shadowRoot.querySelectorAll(".tab").forEach((b) => b.addEventListener("click", () => { this._tab = b.dataset.tab; this._render(); }));
    this.shadowRoot.querySelectorAll("[data-view]").forEach((b) => b.addEventListener("click", () => { this._view = b.dataset.view; this._render(); }));
  }

  _card(st, t) {
    const a = st.attributes || {};
    const unit = a.unit || "kr";
    const p = a.price || {};
    const cls = p.mode === "C" ? "cheap" : p.mode === "E" ? "dear" : "";
    const label = p.mode === "C" ? t.cheap : p.mode === "E" ? t.dear : t.unknown;
    const age = a.ts ? Math.round((Date.now() - new Date(a.ts).getTime()) / 60000) : 0;
    const stale = age > 10 ? `<div class="msg" style="padding:6px 16px 0;color:#e0443f">${esc(t.stale)}: ${esc(t.ago(age))}</div>` : "";
    const tabs = ["now", "plan", "cars"].map((k) => `<button class="tab ${this._tab === k ? "on" : ""}" data-tab="${k}">${t[k]}</button>`).join("");
    const body = this._tab === "plan" ? this._plan(a, t, unit) : this._tab === "cars" ? this._cars(a, t) : this._now(a, t);
    return `<div class="head">
        <svg class="bolt" viewBox="0 0 24 24"><path fill="#f5b301" d="M13 2 4 14h6l-1 8 9-12h-6z"/></svg>
        <span class="title">${esc(this._config.title || "EnergyWizard")}</span><span class="spacer"></span>
        <span class="chip ${cls}">${esc(fmtPrice(p.now, unit))} · ${esc(label)}</span></div>${stale}
      <div class="tabs">${tabs}</div><div class="body">${body}</div>`;
  }

  // "Nu" i appens stil (Just nu): källor till vänster, hemmet i mitten, laster som rutor till höger. Mjuka kurvor, och
  // prickarna på dem rör sig dit elen går. Rutorna har namn, värde och status.
  _now(a, t) {
    const nodes = (a.flow || []).filter((n) => n && n.k);
    if (!nodes.length) return `<div class="msg">${esc(t.noData)}</div>`;
    const W = 360, BOXW = 136, BOXH = 66, GAP = 8, LX = 4, RX = W - BOXW - 4, cx = W / 2 - 6;
    const hub = nodes.find((n) => n.r === "hub") || { k: "hus", l: t.house, i: "🏠", w: null, on: true };
    const sun = nodes.find((n) => n.k === "sol"), grid = nodes.find((n) => n.r === "grid");
    const loads = nodes.filter((n) => n.r === "load" || (n.k !== "sol" && n.r !== "grid" && n.r !== "hub"));
    const colH = Math.max(loads.length, 2) * (BOXH + GAP) - GAP, H = colH + 8, hubY = H / 2;
    const left = [sun, grid].filter(Boolean);
    const leftPos = {}; left.forEach((n, i) => { leftPos[n.k] = (H / (left.length + 1)) * (i + 1) - BOXH / 2; });
    const boxText = (n) => {
      // Tre rader: namn, värde, status. Statusen utan watt-siffran (den står redan som värde) och kortad.
      let status = String(n.d || "").replace(/\d+(\.\d+)?\s?k?W\b\s*·?\s*/gi, "").replace(/^[\s·]+|[\s·]+$/g, "");
      if (status.length > 24) status = status.slice(0, 23) + "…";
      const name = String(n.l || ""), nm = name.length > 18 ? name.slice(0, 17) + "…" : name;
      return `<text class="b-l" x="10" y="18" fill="${colorOf(n.k)}">${esc(nm)}</text>
        <text class="b-w" x="10" y="42">${n.w == null ? "–" : (Math.abs(n.w) >= 1000 ? (n.w / 1000).toFixed(1) + '<tspan class="b-u"> kW</tspan>' : Math.round(n.w) + '<tspan class="b-u"> W</tspan>')}</text>
        <text class="b-s m" x="10" y="58">${esc(status)}</text>`;
    };
    const box = (n, x, y) => `<g transform="translate(${x},${y})"><rect width="${BOXW}" height="${BOXH}" rx="12" fill="${colorOf(n.k)}" fill-opacity="${n.on ? ".14" : ".05"}"
        stroke="${colorOf(n.k)}" stroke-width="${n.on ? 2 : 1}" stroke-opacity="${n.on ? 1 : .35}"/>${boxText(n)}</g>`;
    const curve = (x1, y1, x2, y2, on, color) => { const mx = (x1 + x2) / 2;
      return `<path class="flow ${on ? "" : "off"}" stroke="${color}" d="M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}"/>`; };
    const hubBox = 62, hx = cx - hubBox / 2 + 6;
    let lines = "", boxes = "";
    left.forEach((n) => {
      const y = leftPos[n.k], selling = n.r === "grid" && /säljer|sell|export/i.test(n.d || "");
      lines += selling ? curve(hx, hubY, LX + BOXW, y + BOXH / 2, n.on, colorOf(n.k)) : curve(LX + BOXW, y + BOXH / 2, hx, hubY, n.on, colorOf(n.k));
      boxes += box(n, LX, y);
    });
    loads.forEach((n, i) => {
      const y = i * (BOXH + GAP) + (colH - loads.length * (BOXH + GAP) + GAP) / 2;
      lines += curve(hx + hubBox, hubY, RX, y + BOXH / 2, n.on, colorOf(n.k));
      boxes += box(n, RX, y);
    });
    const hubKw = hub.w == null ? "" : (Math.abs(hub.w) >= 1000 ? (hub.w / 1000).toFixed(1) + " kW" : Math.round(hub.w) + " W");
    boxes += `<g transform="translate(${hx},${hubY - hubBox / 2})"><rect width="${hubBox}" height="${hubBox}" rx="16" fill="${colorOf("hus")}" fill-opacity=".14" stroke="${colorOf("hus")}" stroke-width="2"/>
      <path d="M${hubBox / 2 - 15},${hubBox / 2 + 1} L${hubBox / 2},${hubBox / 2 - 14} L${hubBox / 2 + 15},${hubBox / 2 + 1} M${hubBox / 2 - 10},${hubBox / 2 - 3} V${hubBox / 2 + 13} H${hubBox / 2 + 10} V${hubBox / 2 - 3}" fill="none" stroke="${colorOf("hus")}" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/></g>
      <text class="b-w" x="${hx + hubBox / 2}" y="${hubY + hubBox / 2 + 18}" text-anchor="middle" font-size="13">${esc(hubKw)}</text>`;
    const reasons = Object.values(a.why || {}).filter(Boolean);
    const why = reasons.length ? `<div class="why"><b>${esc(t.why)}:</b> ${esc([...new Set(reasons)][0])}</div>` : "";
    return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Energiflöde">${lines}${boxes}</svg>${why}`;
  }

  // Planlockan i appens stil: ett streck per kvart runt en urtavla, längden efter priset. Bilen som laddar får egen färg,
  // solprognosen en mjuk krans utanför. I mitten klockan nu, priset och läget.
  _clock(a, t, unit) {
    const slots = (a.slots || []).filter((s) => s && s[1] != null);
    if (!slots.length) return `<div class="msg">${esc(t.noData)}</div>`;
    const C = 200, R0 = 118, R1 = 154, now = Math.floor(Date.now() / 1000);
    const first = Math.max(slots.findIndex((s, i) => s[0] + 900 > now || i === slots.length - 1), 0);
    const rows = slots.slice(first, first + 96);
    const prices = rows.map((r) => r[1]), lo = Math.min(...prices), hi = Math.max(...prices), span = Math.max(hi - lo, 1e-6);
    const sunMax = Math.max(1, ...rows.map((r) => r[4] || 0));
    const ang = (epoch) => { const d = new Date(epoch * 1000); return ((d.getHours() + d.getMinutes() / 60) / 24) * 2 * Math.PI - Math.PI / 2; };
    const pt = (an, r) => [C + r * Math.cos(an), C + r * Math.sin(an)], f1 = (n) => n.toFixed(1);
    let svg = `<svg viewBox="0 0 400 400" role="img" aria-label="Plan">`;
    const runs = []; let cur = [];
    rows.forEach((r) => { const w = r[4] || 0; if (w > sunMax * 0.04) cur.push([ang(r[0]), 3 + 15 * (w / sunMax)]); else if (cur.length) { runs.push(cur); cur = []; } });
    if (cur.length) runs.push(cur);
    runs.forEach((run) => { if (run.length < 2) return;
      const outer = run.map(([an, h]) => pt(an, R1 + 8 + h)), inner = run.slice().reverse().map(([an]) => pt(an, R1 + 7));
      svg += `<path d="M${outer.map((p) => p.map(f1).join(" ")).join(" L")} L${inner.map((p) => p.map(f1).join(" ")).join(" L")} Z" fill="#facc15" opacity=".16"/>`
        + `<path d="M${outer.map((p) => p.map(f1).join(" ")).join(" L")}" fill="none" stroke="#facc15" stroke-width="1" stroke-dasharray="1.5 3" opacity=".85"/>`; });
    svg += `<circle cx="${C}" cy="${C}" r="${R0 - 20}" fill="none" stroke="currentColor" stroke-opacity=".07"/>`;
    rows.forEach((r) => {
      const an = ang(r[0]), len = 5 + (R1 - R0 - 5) * ((r[1] - lo) / span), [x1, y1] = pt(an, R0), [x2, y2] = pt(an, R0 + len), ev = r[5] > 0.05;
      const col = ev ? "#a78bfa" : r[3] === "C" ? "#3fb68b" : r[3] === "E" ? "#e0675e" : "currentColor";
      svg += `<line x1="${f1(x1)}" y1="${f1(y1)}" x2="${f1(x2)}" y2="${f1(y2)}" stroke="${col}" stroke-width="${ev ? 2.8 : 2.1}" stroke-linecap="round" opacity="${ev ? 1 : .55}"/>`; });
    for (let h = 0; h < 24; h++) { const an = (h / 24) * 2 * Math.PI - Math.PI / 2;
      if (h % 6 === 0) { const [x, y] = pt(an, R0 - 14); svg += `<text class="m" x="${f1(x)}" y="${f1(y + 3.4)}" text-anchor="middle" font-size="10" letter-spacing="1.5">${String(h).padStart(2, "0")}</text>`; }
      else { const [x, y] = pt(an, R0 - 12); svg += `<circle cx="${f1(x)}" cy="${f1(y)}" r="1" fill="currentColor" opacity=".3"/>`; } }
    const aN = ang(rows[0][0]), [hx, hy] = pt(aN, R1 + 4), [ix, iy] = pt(aN, R0 - 24);
    svg += `<line x1="${f1(ix)}" y1="${f1(iy)}" x2="${f1(hx)}" y2="${f1(hy)}" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/><circle cx="${f1(hx)}" cy="${f1(hy)}" r="4" fill="currentColor"/>`;
    const mode = a.price && a.price.mode, label = mode === "C" ? t.cheap : mode === "E" ? t.dear : t.unknown;
    const d0 = new Date(), clock = String(d0.getHours()).padStart(2, "0") + ":" + String(d0.getMinutes()).padStart(2, "0");
    svg += `<text class="m" x="${C}" y="${C - 34}" text-anchor="middle" font-size="11" letter-spacing="2">${esc(t.now.toUpperCase())}</text>
      <text x="${C}" y="${C + 14}" text-anchor="middle" font-size="46" font-weight="300">${clock}</text>
      <text class="m" x="${C}" y="${C + 38}" text-anchor="middle" font-size="12" letter-spacing="1.2">${esc((a.price && a.price.now != null ? a.price.now.toFixed(2).replace(".", ",") : "–") + " " + unit.toUpperCase() + "/KWH")}</text>
      <text x="${C}" y="${C + 58}" text-anchor="middle" font-size="12" font-weight="600" letter-spacing="1.2" fill="${mode === "C" ? "#3fb68b" : mode === "E" ? "#e0675e" : "currentColor"}">${esc(label.toUpperCase())}</text></svg>`;
    const cheap = rows.reduce((m, r) => (r[1] < m[1] ? r : m), rows[0]), dear = rows.reduce((m, r) => (r[1] > m[1] ? r : m), rows[0]);
    const legend = `<div class="legend"><span><i style="background:#3fb68b"></i>${esc(t.cheap)}</span><span><i style="background:#e0675e"></i>${esc(t.dear)}</span>`
      + `${rows.some((r) => r[5] > 0.05) ? `<span><i style="background:#a78bfa"></i>${esc(t.charging)}</span>` : ""}${sunMax > 50 ? `<span><i style="background:#facc15"></i>${esc(t.sun)}</span>` : ""}</div>`;
    return `${svg}${legend}<div class="why">${esc(t.cheapest)}: <b>${esc(hhmm(cheap[0]))}</b> ${esc(fmtPrice(cheap[1], unit))} · ${esc(t.dearest)}: <b>${esc(hhmm(dear[0]))}</b> ${esc(fmtPrice(dear[1], unit))}</div>`;
  }

  _plan(a, t, unit) {
    const v = this._view || "clock";
    const toggle = `<div class="seg"><button data-view="clock" class="${v === "clock" ? "on" : ""}">${esc(t.clock)}</button><button data-view="sky" class="${v === "sky" ? "on" : ""}">${esc(t.skyline)}</button></div>`;
    return toggle + (v === "sky" ? this._skyline(a, t, unit) : this._clock(a, t, unit));
  }

  // Priset kvart för kvart, med planen: grönt = billigt, rött = dyrt, gult = sol, orange = bilen laddar.
  _skyline(a, t, unit) {
    const slots = (a.slots || []).filter((s) => s && s[1] != null);
    if (!slots.length) return `<div class="msg">${esc(t.noData)}</div>`;
    const W = 360, H = 200, L = 30, R = 6, T = 10, B = 24, w = W - L - R, h = H - T - B;
    const now = Math.floor(Date.now() / 1000);
    const first = slots.findIndex((s, i) => s[0] + 900 > now || i === slots.length - 1);
    const rows = slots.slice(Math.max(first, 0), Math.max(first, 0) + 96);
    const max = Math.max(...rows.map((r) => r[1]), 0.5) * 1.08, bw = w / rows.length;
    const y = (v) => T + h - (Math.max(v, 0) / max) * h;
    const sunMax = Math.max(...rows.map((r) => r[4] || 0), 1);
    let bars = "", sun = "", ev = "", lab = "";
    rows.forEach((r, i) => {
      const x = L + i * bw, c = r[3] === "C" ? "#2ec4a6" : r[3] === "E" ? "#ef5350" : "#9aa0a6";
      bars += `<rect x="${x.toFixed(1)}" y="${y(r[1]).toFixed(1)}" width="${Math.max(bw - 0.6, 0.6).toFixed(1)}" height="${(T + h - y(r[1])).toFixed(1)}" fill="${c}" fill-opacity=".85"/>`;
      if (r[5] > 0) ev += `<rect x="${x.toFixed(1)}" y="${T + h + 3}" width="${Math.max(bw - 0.6, 0.6).toFixed(1)}" height="4" fill="#ff9f1a"/>`;
    });
    if (sunMax > 50) {
      const pts = rows.map((r, i) => `${(L + (i + 0.5) * bw).toFixed(1)},${(T + h - ((r[4] || 0) / sunMax) * h * 0.55).toFixed(1)}`);
      sun = `<polyline points="${pts.join(" ")}" fill="none" stroke="#f5b301" stroke-width="2" stroke-linejoin="round"/>`;
    }
    const top = max / 1.08, step = [0.25, 0.5, 1, 2, 5, 10].find((x) => top / x <= 4) || 10;
    const ticks = []; for (let v = 0; v <= top + 1e-6; v += step) ticks.push(v);
    ticks.forEach((v) => { lab += `<line x1="${L}" x2="${W - R}" y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}" stroke="currentColor" stroke-opacity=".12"/><text class="m" x="${L - 4}" y="${(y(v) + 3).toFixed(1)}" text-anchor="end" font-size="9">${Number.isInteger(v) ? v : v.toFixed(2).replace(/0$/, "")}</text>`; });
    rows.forEach((r, i) => { const m = new Date(r[0] * 1000).getMinutes(), hr = new Date(r[0] * 1000).getHours(); if (m === 0 && hr % 6 === 0) lab += `<text class="m" x="${(L + i * bw).toFixed(1)}" y="${H - 8}" text-anchor="middle" font-size="9">${String(hr).padStart(2, "0")}:00</text>`; });
    const cheap = rows.reduce((m, r) => (r[1] < m[1] ? r : m), rows[0]), dear = rows.reduce((m, r) => (r[1] > m[1] ? r : m), rows[0]);
    return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Elpris och plan">${lab}${bars}${sun}${ev}
        <line x1="${L}" x2="${L}" y1="${T}" y2="${T + h}" stroke="var(--primary-text-color)" stroke-width="2"/></svg>
      <div class="legend"><span><i style="background:#2ec4a6"></i>${esc(t.cheap)}</span><span><i style="background:#ef5350"></i>${esc(t.dear)}</span>
        <span><i style="background:#f5b301"></i>${esc(t.sun)}</span><span><i style="background:#ff9f1a"></i>${esc(t.charging)}</span></div>
      <div class="why">${esc(t.cheapest)}: <b>${esc(hhmm(cheap[0]))}</b> ${esc(fmtPrice(cheap[1], unit))} · ${esc(t.dearest)}: <b>${esc(hhmm(dear[0]))}</b> ${esc(fmtPrice(dear[1], unit))}</div>`;
  }

  _cars(a, t) {
    const cars = (a.flow || []).filter((n) => n && String(n.k).startsWith("ev_"));
    if (!cars.length) return `<div class="msg">${esc(t.noCars)}</div>`;
    return cars.map((c) => { const m = /(\d{1,3})\s?%/.exec(c.d || ""), soc = m ? Math.min(100, +m[1]) : null;
      const bar = soc == null ? "" : `<div class="soc"><div style="width:${soc}%;background:${c.on ? "#2ec4a6" : "#9aa0a6"}"></div></div>`;
      return `<div class="row"><span class="dot ${c.on ? "on" : ""}"></span><div style="flex:1;min-width:0">
        <div class="n">${esc(c.i || "🚗")} ${esc(c.l)}</div><div class="d">${esc(c.d || "")}</div>${bar}
        ${a.why && a.why[c.k] ? `<div class="d" style="margin-top:2px">${esc(a.why[c.k])}</div>` : ""}</div>
        <div class="n">${c.w == null ? "" : esc(kw(c.w))}</div></div>`; }).join("");
  }
}


// Gemensam bas för korten: läser sensorn, ritar om vid ny data och visar tydliga fel i stället för ett tomt kort.
class EnergyWizardBase extends HTMLElement {
  setConfig(config) {
    this._config = { entity: "sensor.energywizard_kort", ...(config || {}) };
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this._render();
  }
  set hass(hass) {
    this._hass = hass;
    const st = hass && hass.states ? hass.states[this._config.entity] : null;
    const key = st ? st.last_updated + "|" + (st.attributes && st.attributes.ts) : "missing";
    if (key !== this._key) { this._key = key; this._render(); }
  }
  getCardSize() { return 5; }
  _t() {
    const lang = (this._config.language || (this._hass && (this._hass.language || (this._hass.locale && this._hass.locale.language))) || "sv").slice(0, 2);
    return EW_TEXT[lang] || EW_TEXT.sv;
  }
  _render() {
    if (!this.shadowRoot || !this._config) return;
    const t = this._t(), st = this._hass && this._hass.states ? this._hass.states[this._config.entity] : null;
    let inner;
    if (!this._hass) inner = `<div class="msg">…</div>`;
    else if (!st) inner = `<div class="msg">${esc(t.missing(this._config.entity))}</div>`;
    else {
      const a = st.attributes || {}, p = a.price || {}, unit = a.unit || "kr";
      const cls = p.mode === "C" ? "cheap" : p.mode === "E" ? "dear" : "";
      const label = p.mode === "C" ? t.cheap : p.mode === "E" ? t.dear : t.unknown;
      const age = a.ts ? Math.round((Date.now() - new Date(a.ts).getTime()) / 60000) : 0;
      const stale = age > 10 ? `<div class="msg" style="padding:6px 16px 0;color:#e0443f">${esc(t.stale)}: ${esc(t.ago(age))}</div>` : "";
      inner = `<div class="head"><svg class="bolt" viewBox="0 0 24 24"><path fill="#f5b301" d="M13 2 4 14h6l-1 8 9-12h-6z"/></svg>
        <span class="title">${esc(this._config.title || this._title(t))}</span><span class="spacer"></span>
        <span class="chip ${cls}">${esc(fmtPrice(p.now, unit))} · ${esc(label)}</span></div>${stale}<div class="body">${this._body(a, t, unit)}</div>`;
    }
    this.shadowRoot.innerHTML = `<style>${STYLE}</style><ha-card>${inner}</ha-card>`;
    // Knappar som styr EnergyWizard går via en väljare (select) i HA; kortet anropar bara HA:s tjänst.
    this.shadowRoot.querySelectorAll("button[data-select]").forEach((b) => b.addEventListener("click", () => {
      if (!this._hass || b.classList.contains("on")) return;
      b.disabled = true; b.style.opacity = ".5";                    // väntar tills sensorn visar nya läget
      this._hass.callService("select", "select_option", { entity_id: b.dataset.select, option: b.dataset.option });
    }));
  }
}

// Ett pass-streck per kvart över kommande dygn: pris som staplar, planerade pass som fält, "nu" som linje.
function priceStrip(slots, wins, unit, t, H = 120) {
  const rows = slots.filter((s) => s && s[1] != null), now = Math.floor(Date.now() / 1000);
  if (!rows.length) return "";
  const first = Math.max(rows.findIndex((s, i) => s[0] + 900 > now || i === rows.length - 1), 0), r = rows.slice(first, first + 96);
  const W = 360, L = 26, Rr = 6, T = 8, B = 20, w = W - L - Rr, h = H - T - B, max = Math.max(...r.map((x) => x[1]), 0.5) * 1.08, bw = w / r.length;
  const y = (v) => T + h - (Math.max(v, 0) / max) * h, t0 = r[0][0], t1 = r[r.length - 1][0] + 900, xOf = (e) => L + ((e - t0) / (t1 - t0)) * w;
  let g = "";
  (wins || []).forEach(([a, b]) => { if (b > t0 && a < t1) g += `<rect x="${xOf(Math.max(a, t0)).toFixed(1)}" y="${T}" width="${(xOf(Math.min(b, t1)) - xOf(Math.max(a, t0))).toFixed(1)}" height="${h}" fill="#a78bfa" fill-opacity=".28"/>`; });
  r.forEach((x, i) => { const c = x[3] === "C" ? "#3fb68b" : x[3] === "E" ? "#e0675e" : "#9aa0a6";
    g += `<rect x="${(L + i * bw).toFixed(1)}" y="${y(x[1]).toFixed(1)}" width="${Math.max(bw - 0.6, 0.6).toFixed(1)}" height="${(T + h - y(x[1])).toFixed(1)}" fill="${c}" fill-opacity=".8"/>`; });
  const top = max / 1.08, step = [0.25, 0.5, 1, 2, 5, 10].find((q) => top / q <= 3) || 10;
  for (let v = 0; v <= top + 1e-6; v += step) g += `<line x1="${L}" x2="${W - Rr}" y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}" stroke="currentColor" stroke-opacity=".1"/><text class="m" x="${L - 4}" y="${(y(v) + 3).toFixed(1)}" text-anchor="end" font-size="9">${Number.isInteger(v) ? v : v.toFixed(2).replace(/0$/, "")}</text>`;
  r.forEach((x, i) => { const d = new Date(x[0] * 1000); if (d.getMinutes() === 0 && d.getHours() % 6 === 0) g += `<text class="m" x="${(L + i * bw).toFixed(1)}" y="${H - 6}" text-anchor="middle" font-size="9">${String(d.getHours()).padStart(2, "0")}:00</text>`; });
  g += `<line x1="${L}" x2="${L}" y1="${T}" y2="${T + h}" stroke="var(--primary-text-color)" stroke-width="2"/>`;
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Elpris">${g}</svg>`;
}

// Värme: termostatratt (inomhus, bandet mellan golv och tak) och dygnets billiga/dyra pass. Läser bara; styrning sker i EnergyWizard.
class EnergyWizardHeatCard extends EnergyWizardBase {
  static getStubConfig() { return { entity: "sensor.energywizard_kort" }; }
  _title(t) { return t.heat; }
  _body(a, t, unit) {
    const h = a.heat;
    if (!h || h.indoor == null) return `<div class="msg">${esc(t.noHeat)}</div>`;
    const lo = Math.min(15, (h.floor == null ? 15 : h.floor) - 2), hi = Math.max(25, (h.max == null ? 25 : h.max) + 2);
    const A0 = 135, SW = 270, cx = 150, cy = 140, R = 104;
    const ang = (v) => A0 + SW * ((Math.min(Math.max(v, lo), hi) - lo) / (hi - lo));
    const xy = (deg, r) => [cx + r * Math.cos((deg * Math.PI) / 180), cy + r * Math.sin((deg * Math.PI) / 180)];
    const arc = (v0, v1, r) => { const [x0, y0] = xy(ang(v0), r), [x1, y1] = xy(ang(v1), r), big = ang(v1) - ang(v0) > 180 ? 1 : 0;
      return `M${x0.toFixed(1)},${y0.toFixed(1)} A${r},${r} 0 ${big} 1 ${x1.toFixed(1)},${y1.toFixed(1)}`; };
    const f1 = (n) => (n == null ? "–" : n.toFixed(1).replace(".", ","));
    const hasBand = h.floor != null && h.max != null && h.max > h.floor;
    const [kx, ky] = xy(ang(h.indoor), R);
    const col = h.mode === "C" ? "#3fb68b" : h.mode === "E" ? "#ef5350" : "#ff9f1a";
    let g = `<path d="${arc(lo, hi, R)}" fill="none" stroke="currentColor" stroke-opacity=".12" stroke-width="16" stroke-linecap="round"/>`;
    if (hasBand) g += `<path d="${arc(h.floor, h.max, R)}" fill="none" stroke="#3fb68b" stroke-opacity=".28" stroke-width="16"/>`;
    g += `<path d="${arc(lo, Math.max(h.indoor, lo + 0.01), R)}" fill="none" stroke="${col}" stroke-width="8" stroke-linecap="round"/>`
      + `<circle cx="${kx.toFixed(1)}" cy="${ky.toFixed(1)}" r="9" fill="var(--card-background-color, #1c1c1c)" stroke="var(--primary-text-color)" stroke-width="3"/>`;
    if (h.setpoint != null) { const [sx, sy] = xy(ang(h.setpoint), R + 14); g += `<circle cx="${sx.toFixed(1)}" cy="${sy.toFixed(1)}" r="3" fill="var(--primary-text-color)" opacity=".6"/>`; }
    g += `<text x="${cx}" y="${cy + 12}" text-anchor="middle" font-size="46" font-weight="300">${f1(h.indoor)}°</text>`
      + `<text class="m" x="${cx}" y="${cy + 38}" text-anchor="middle" font-size="12">${hasBand ? esc(t.within) + " " + f1(h.floor) + "–" + f1(h.max) + " °C" : ""}</text>`;
    const dial = `<svg viewBox="0 0 300 250" role="img" aria-label="${esc(t.heat)}">${g}</svg>`;
    const facts = [h.outdoor != null ? `${esc(t.outdoor)} ${f1(h.outdoor)} °C` : "", h.setpoint != null ? `${esc(t.setpoint)} ${f1(h.setpoint)} °C` : "",
      h.cop ? `COP ${f1(h.cop)}` : ""].filter(Boolean).join(" · ");
    const water = h.water != null ? `<div class="row"><span class="dot ${h.water >= (h.water_set || 99) - 3 ? "on" : ""}"></span><div style="flex:1"><div class="n">💧 ${esc(t.water)}</div></div><div class="n">${h.water} °C${h.water_set ? ` <span class="d">/ ${h.water_set}</span>` : ""}</div></div>` : "";
    // Kommande pass: var läget byter
    const now = Math.floor(Date.now() / 1000), rows = (a.slots || []).filter((s) => s && s[3]);
    const cur = rows.find((s) => s[0] + 900 > now) || rows[0];
    let nextTxt = "";
    if (cur) { const sw = rows.find((s) => s[0] > cur[0] && s[3] !== cur[3]);
      if (sw) nextTxt = (cur[3] === "E" ? t.dearUntil : t.cheapUntil)(hhmm(sw[0])) + ", " + (cur[3] === "E" ? t.thenCheap : t.thenDear); }
    const strip = priceStrip(a.slots || [], [], unit, t, 110);
    return `${dial}<div class="why" style="text-align:center">${facts}</div>${water}${strip}${nextTxt ? `<div class="why">${esc(nextTxt)}</div>` : ""}`;
  }
}

// Bil: per bil laddnivå, status och planerade pass över elpriset. config.car = bilens id (valfritt, annars alla bilar).
class EnergyWizardCarCard extends EnergyWizardBase {
  static getStubConfig() { return { entity: "sensor.energywizard_kort" }; }
  _title(t) { return t.cars; }
  _body(a, t, unit) {
    let cars = a.cars || [];
    if (this._config.car) cars = cars.filter((c) => c.id === this._config.car);
    if (!cars.length) return `<div class="msg">${esc(t.noCars)}</div>`;
    return cars.map((c) => {
      const soc = c.soc, status = c.on ? `${esc(t.charging)} ${c.w ? esc(kw(c.w)) : ""}` : esc(t.notCharging);
      const bar = soc == null ? "" : `<div class="soc"><div style="width:${soc}%;background:${c.on ? "#2ec4a6" : "#9aa0a6"}"></div></div>`;
      const wins = (c.win || []).map(([x, y, k]) => `${hhmm(x)}–${hhmm(y)} · ${k.toFixed(1).replace(".", ",")} kW`);
      const planned = wins.length ? `<div class="why"><b>${esc(t.plannedAt)}:</b> ${esc(wins.slice(0, 3).join("  ·  "))}${wins.length > 3 ? " …" : ""}</div>` : `<div class="why">${esc(t.noPlan)}</div>`;
      const reason = a.why && a.why["ev_" + c.id] ? `<div class="why">${esc(a.why["ev_" + c.id])}</div>` : "";
      const sel = this._hass && this._hass.states ? this._hass.states[`select.energywizard_ev_${c.id}_mode`] : null;
      const ctl = sel && sel.attributes && Array.isArray(sel.attributes.options) && this._config.controls !== false
        ? `<div class="seg" style="justify-content:flex-start;padding:8px 0 2px">${sel.attributes.options.map((o) => `<button class="${o === sel.state ? "on" : ""}" data-select="select.energywizard_ev_${esc(c.id)}_mode" data-option="${esc(o)}">${esc((t.modes && t.modes[o]) || o)}</button>`).join("")}</div>
           ${cars.indexOf(c) === 0 ? `<div class="why" style="margin-top:2px">${esc(t.modeHint)}</div>` : ""}` : "";
      return `<div style="padding:6px 4px 14px"><div class="row" style="border:0;padding:4px 0"><span class="dot ${c.on ? "on" : ""}"></span>
          <div style="flex:1;min-width:0"><div class="n">🚗 ${esc(c.name || c.id)}</div><div class="d">${status}</div></div>
          <div class="n" style="font-size:1.6rem;font-weight:300">${soc == null ? "–" : soc + " %"}</div></div>${bar}
        ${ctl}${priceStrip(a.slots || [], c.win, unit, t, 110)}${planned}${reason}</div>`;
    }).join("");
  }
}

// Sol och batteri: produktion nu, prognos idag/imorgon, laddnivå och om planen laddar, sparar, laddar ur eller säljer (#558).
class EnergyWizardBatteryCard extends EnergyWizardBase {
  static getStubConfig() { return { entity: "sensor.energywizard_kort" }; }
  _title(t) { return t.solarBattery; }
  _body(a, t) {
    const sun = a.solar, bat = a.batt;
    if (!sun && !bat) return `<div class="msg">${esc(t.noPlant)}</div>`;
    const f1 = (n) => (n == null ? "–" : Number(n).toFixed(1).replace(".", ","));
    const planTxt = (b) => {
      if (b.plan && t.batPlan && t.batPlan[b.plan]) return t.batPlan[b.plan];
      if (b.w > 30) return t.batPlan.charge;
      if (b.w < -30) return t.batPlan.discharge;
      if (b.w == null) return t.noBatPlan;
      return t.batPlan.idle;
    };
    let html = "";
    if (sun) {
      const on = sun.w > 50;
      html += `<div class="row"><span class="dot ${on ? "on" : ""}"></span><div style="flex:1"><div class="n">☀️ ${esc(t.sunNow)}</div>
        <div class="d">${esc(t.forecastToday)} ${f1(sun.today_kwh)} kWh · ${esc(t.forecastTomorrow)} ${f1(sun.tomorrow_kwh)} kWh</div></div>
        <div class="n">${sun.w == null ? "–" : esc(kw(sun.w))}</div></div>`;
    }
    if (bat) {
      const soc = bat.soc;
      const bar = soc == null ? "" : `<div class="soc"><div style="width:${Math.max(0, Math.min(100, soc))}%;background:#2ec4a6"></div></div>`;
      const extra = bat.plan_kw == null || Math.abs(bat.plan_kw) < 0.05 ? "" : ` · ${f1(Math.abs(bat.plan_kw))} kW`;
      const moving = bat.w != null && Math.abs(bat.w) > 30;
      html += `<div class="row" style="align-items:flex-start"><span class="dot ${moving ? "on" : ""}"></span>
        <div style="flex:1;min-width:0"><div class="n">🔋 ${esc(t.batteryName)}</div><div class="d">${esc(planTxt(bat))}${extra}</div>${bar}</div>
        <div class="n" style="font-size:1.6rem;font-weight:300">${soc == null ? "–" : soc + " %"}</div></div>`;
      if (bat.w != null) html += `<div class="why">${esc(t.powerNow)} ${esc(kw(bat.w))}</div>`;
    }
    return html + `<div class="why">${esc(t.forecastNote)}</div>`;
  }
}

if (!customElements.get("energywizard-house-card")) customElements.define("energywizard-house-card", EnergyWizardHouseCard);
if (!customElements.get("energywizard-heat-card")) customElements.define("energywizard-heat-card", EnergyWizardHeatCard);
if (!customElements.get("energywizard-car-card")) customElements.define("energywizard-car-card", EnergyWizardCarCard);
if (!customElements.get("energywizard-battery-card")) customElements.define("energywizard-battery-card", EnergyWizardBatteryCard);
window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === "energywizard-house-card")) {
  window.customCards.push({ type: "energywizard-house-card", name: "EnergyWizard: Hemmet", preview: true,
    description: "Energiflöde, elpris med plan och bilar. Läser sensor.energywizard_kort." });
}
console.info(`%c EnergyWizard %c ${EW_VERSION} `, "background:#f5b301;color:#000;font-weight:700;border-radius:3px 0 0 3px", "background:#333;color:#fff;border-radius:0 3px 3px 0");

for (const [type, name, description] of [
  ["energywizard-heat-card", "EnergyWizard: Värme", "Termostatratt med inomhustemperatur och band, varmvatten och dygnets billiga och dyra pass."],
  ["energywizard-car-card", "EnergyWizard: Bil", "Laddnivå, status och planerade laddpass över elpriset, per bil."],
  ["energywizard-battery-card", "EnergyWizard: Sol och batteri", "Solproduktion nu och prognos, batteriets laddnivå och om planen laddar, sparar eller laddar ur."]]) {
  if (!window.customCards.some((c) => c.type === type)) window.customCards.push({ type, name, preview: true, description });
}
