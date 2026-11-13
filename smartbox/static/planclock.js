/* planclock.js - EnergyWizards dragbara planklocka (webben och mobilappen).
 *
 * En 24-timmarsurtavla: en stapel per kvart, längden efter priset och färgen efter vad som händer då
 * (batteriet laddar/laddar ur, en bil laddar, annars prisnivån). Solprognosen ligger som en mjuk gul krans utanför.
 * Visaren pulserar på "nu" och går att dra (mus, finger, piltangenter) till valfri kvart de närmaste 24 timmarna -
 * mitten visar då klockslag, pris och vad batteri och bilar gör just då. Släpp och tryck "Nu" för att gå tillbaka.
 *
 * Data: GET api/planclock (smartbox/plan_clock.py). Användning:
 *   EWPlanClock.mount(element, data, { unit: "kr", lang: "sv" })
 * Ingen beroende kod - bara SVG och pekarhändelser.
 */
(function () {
  "use strict";
  const COL = { discharge: "#f59e0b", export: "#d946ef", charge: "#2dd4bf", hold: "#64748b", idle: "#475569", car: ["#a78bfa", "#f472b6", "#60a5fa", "#34d399"],
                cheap: "#3fb68b", mid: "#7c8aa0", dear: "#e0675e", sun: "#facc15" };
  const T = {
    sv: { next12: "Hela planen · totalpris", now: "Nu", today: "Idag", tomorrow: "Imorgon", until: "till", discharge: "Laddar ur", export: "Laddar ur · säljer", charge: "Laddar", hold: "Sparas",
          idle: "Vilar", auto: "Självförbrukning", balance: "Balansering", charges: "laddar", sun: "Sol", nothing: "Inget planerat",
          heat: { CHEAP: "Värmer på huset", EXPENSIVE: "Värmen sänkt" }, drag: "Dra visaren för att se planen",
          legend: ["Laddar ur", "Laddar", "Bil", "Solprognos"], legExport: "Laddar ur · säljer", cheap: "Billigt", dear: "Dyrt" },
    en: { next12: "Whole plan · total price", now: "Now", today: "Today", tomorrow: "Tomorrow", until: "until", discharge: "Discharging", export: "Discharging · selling", charge: "Charging", hold: "Holding",
          idle: "Idle", auto: "Self-consumption", balance: "Balancing", charges: "charges", sun: "Sun", nothing: "Nothing planned",
          heat: { CHEAP: "Pre-heating", EXPENSIVE: "Heat lowered" }, drag: "Drag the hand to explore the plan",
          legend: ["Discharging", "Charging", "Car", "Sun forecast"], legExport: "Discharging · selling", cheap: "Cheap", dear: "Expensive" },
  };
  // Additional languages use the same catalog as the rest of the interface.
  function labels(lang) {
    if (T[lang]) return T[lang];
    const tr = (s) => window.I18N ? window.I18N.tr(s) : s;
    const src = { ...T.sv, until: "fram till", charge: "Laddning pågår", legend: ["Laddar ur", "Laddning pågår", "Bil", "Solprognos"] };
    return Object.fromEntries(Object.entries(src).map(([k, v]) => [k, Array.isArray(v) ? v.map(tr) :
      v && typeof v === "object" ? Object.fromEntries(Object.entries(v).map(([key, text]) => [key, tr(text)])) : tr(v)]));
  }
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  let styled = false;
  function style() {
    if (styled) return;
    styled = true;
    const css = document.createElement("style");
    css.textContent = `
.ewpc{position:relative;max-width:400px;margin:0 auto;user-select:none;-webkit-user-select:none;touch-action:none;container-type:inline-size}
.ewpc svg{width:100%;height:auto;display:block;overflow:visible}
.ewpc .ewpc-mid{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;pointer-events:none;text-align:center;padding:0 29%}
.ewpc .ewpc-day{font-size:clamp(.55rem,2.4cqw,.66rem);letter-spacing:.22em;text-transform:uppercase;opacity:.5;min-height:1.1em}
.ewpc .ewpc-time{font-size:clamp(1.9rem,13cqw,3.3rem);font-weight:300;letter-spacing:-.02em;font-variant-numeric:tabular-nums;line-height:1.02;margin:2px 0}
.ewpc .ewpc-price{font-size:clamp(.58rem,2.6cqw,.72rem);letter-spacing:.12em;text-transform:uppercase;opacity:.65;font-variant-numeric:tabular-nums}
.ewpc .ewpc-act{font-size:clamp(.54rem,2.4cqw,.66rem);letter-spacing:.1em;text-transform:uppercase;margin-top:6px;line-height:1.5;font-weight:600}
.ewpc .ewpc-now{position:absolute;left:0;top:0;border:1px solid currentColor;background:transparent;color:inherit;border-radius:999px;padding:3px 11px;font:inherit;font-size:.66rem;letter-spacing:.14em;text-transform:uppercase;opacity:.7;cursor:pointer}
.ewpc .ewpc-now[hidden]{display:none}
.ewpc .ewpc-pulse{transform-box:fill-box;transform-origin:center;animation:ewpcPulse 2s ease-out infinite}
@keyframes ewpcPulse{0%{opacity:.6;transform:scale(1)}100%{opacity:0;transform:scale(3.4)}}
@media (prefers-reduced-motion:reduce){.ewpc .ewpc-pulse{animation:none;opacity:0}}
.ewpc .ewpc-hand{cursor:grab}.ewpc.drag .ewpc-hand{cursor:grabbing}
.ewpc-strip{max-width:520px;margin:14px auto 0;font-variant-numeric:tabular-nums;user-select:none;-webkit-user-select:none}
.ewpc-strip .h{display:flex;justify-content:space-between;font-size:.62rem;letter-spacing:.16em;text-transform:uppercase;opacity:.6;margin-bottom:6px}
.ewpc-strip .h b{opacity:1;font-weight:700;letter-spacing:.06em}
.ewpc-strip svg{width:100%;height:auto;display:block;cursor:pointer;touch-action:pan-y}
.ewpc-legend{display:flex;flex-wrap:wrap;gap:4px 14px;justify-content:center;font-size:.6rem;letter-spacing:.12em;text-transform:uppercase;opacity:.65;margin-top:10px}
.ewpc-legend i{display:inline-block;width:12px;height:3px;border-radius:2px;margin-right:6px;vertical-align:2px}`;
    document.head.appendChild(css);
  }

  function mount(el, data, opts) {
    style();
    opts = opts || {};
    const L = labels(opts.lang), unit = opts.unit || "kr";
    const slots = (data && data.slots) || [];
    if (!slots.length) { el.innerHTML = ""; return null; }
    const cars = (data.cars || []).map((c, k) => ({ id: c.id, name: c.name || c.id, col: COL.car[k % COL.car.length] }));
    const carCol = (id) => (cars.find((c) => c.id === id) || { col: COL.car[0] }).col;
    const carName = (id) => (cars.find((c) => c.id === id) || { name: id }).name;
    const C = 200, R0 = 132, R1 = 158;                 // kvartsstreckens inner- och maxradie
    const prices = slots.map((s) => s.price).filter((v) => v != null);
    const lo = Math.min(...prices), hi = Math.max(...prices), span = Math.max(hi - lo, 1e-6);
    const sunMax = Math.max(1, ...slots.map((s) => s.sun_w || 0));
    const t0 = new Date(slots[0].t);
    const angOf = (d) => ((d.getHours() + d.getMinutes() / 60) / 24) * 2 * Math.PI - Math.PI / 2;
    const pt = (a, r) => [C + r * Math.cos(a), C + r * Math.sin(a)];
    const f1 = (n) => n.toFixed(1);
    const level = (p) => (p - lo) / span;
    const act = (s) => (s.bat === "discharge" || s.bat === "export" || s.bat === "charge") ? s.bat
      : (Object.keys(s.ev || {}).find((k) => (s.ev[k] || 0) > 0.05) ? "car" : null);
    const slotCol = (s) => {
      const a = act(s);
      if (a === "car") return carCol(Object.keys(s.ev).find((k) => (s.ev[k] || 0) > 0.05));
      return a ? COL[a] : "currentColor";
    };
    let svg = `<svg viewBox="0 0 400 400" role="slider" tabindex="0" aria-label="${esc(L.drag)}" aria-valuemin="0" aria-valuemax="${slots.length - 1}">
      <defs><radialGradient id="ewpcSun" cx="50%" cy="50%" r="50%"><stop offset="78%" stop-color="${COL.sun}" stop-opacity="0"/><stop offset="100%" stop-color="${COL.sun}" stop-opacity=".55"/></radialGradient></defs>`;
    // Solprognosen: en mjuk krans utanför strecken, bredare där solen ger mer
    const runs = [];
    let cur = [];
    slots.forEach((s) => {
      const w = s.sun_w || 0;
      if (w > sunMax * 0.04) cur.push([angOf(new Date(s.t)), 3 + 15 * (w / sunMax)]);
      else if (cur.length) { runs.push(cur); cur = []; }
    });
    if (cur.length) runs.push(cur);
    runs.forEach((run) => {
      if (run.length < 2) return;
      const outer = run.map(([a, h]) => pt(a, R1 + 8 + h)), inner = run.slice().reverse().map(([a]) => pt(a, R1 + 7));
      svg += `<path d="M${outer.map((p) => p.map(f1).join(" ")).join(" L")} L${inner.map((p) => p.map(f1).join(" ")).join(" L")} Z" fill="${COL.sun}" opacity=".16"/>`;
      svg += `<path d="M${outer.map((p) => p.map(f1).join(" ")).join(" L")}" fill="none" stroke="${COL.sun}" stroke-width="1" stroke-dasharray="1.5 3" opacity=".85"/>`;
    });
    svg += `<circle cx="${C}" cy="${C}" r="104" fill="none" stroke="currentColor" stroke-opacity=".07"/>`;
    // Ett tunt streck per kvart: längden efter priset, färg när något händer (batteri, bil), annars dämpat
    slots.forEach((s, i) => {
      const a = angOf(new Date(s.t)), len = s.price == null ? 4 : 5 + (R1 - R0 - 5) * level(s.price);
      const [x1, y1] = pt(a, R0), [x2, y2] = pt(a, R0 + len), on = !!act(s);
      svg += `<line data-i="${i}" x1="${f1(x1)}" y1="${f1(y1)}" x2="${f1(x2)}" y2="${f1(y2)}" stroke="${slotCol(s)}" stroke-width="${on ? 2.6 : 2}" stroke-linecap="round" opacity="${on ? 1 : 0.28}"/>`;
    });
    // Timmarna: siffror var sjätte timme, prickar däremellan
    for (let h = 0; h < 24; h++) {
      const a = (h / 24) * 2 * Math.PI - Math.PI / 2;
      if (h % 6 === 0) { const [x, y] = pt(a, R0 - 16); svg += `<text x="${f1(x)}" y="${f1(y + 3.4)}" text-anchor="middle" font-size="10" letter-spacing="1.5" fill="currentColor" opacity=".55">${String(h).padStart(2, "0")}</text>`; }
      else { const [x, y] = pt(a, R0 - 14); svg += `<circle cx="${f1(x)}" cy="${f1(y)}" r="1" fill="currentColor" opacity=".3"/>`; }
    }
    // "Nu" pulserar på kransen; visaren är tunn och går att dra
    const aNow = angOf(t0), [nx, ny] = pt(aNow, R1 + 4);
    svg += `<circle cx="${f1(nx)}" cy="${f1(ny)}" r="3.5" fill="currentColor" class="ewpc-pulse"/><circle cx="${f1(nx)}" cy="${f1(ny)}" r="2.5" fill="currentColor"/>`;
    svg += `<g class="ewpc-hand"><line class="ewpc-hl" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/><circle class="ewpc-hk" r="7" fill="none" stroke="currentColor" stroke-width="1.6"/><circle class="ewpc-hd" r="1.8" fill="currentColor"/></g>`;
    svg += `</svg>`;
    // Hela planen (2026-11-07: förut bara 12 h, så man nådde inte resten genom att dra i remsan): åtgärderna som tunna
    // band, priset som staplar. Tryck eller dra i remsan för att flytta visaren dit.
    const N = slots.length, W = 480, BH = 46;
    const sh = slots.slice(0, N), bw = W / N;
    let strip = `<svg viewBox="0 0 ${W} ${BH + 30}" class="ewpc-sv">`;
    let k = 0;
    while (k < N) {                                         // band: sammanhängande pass med samma åtgärd
      const a = act(sh[k]);
      let j = k;
      while (j + 1 < N && act(sh[j + 1]) === a && (a !== "car" || slotCol(sh[j + 1]) === slotCol(sh[k]))) j++;
      if (a) strip += `<rect x="${f1(k * bw + 1)}" y="2" width="${f1((j - k + 1) * bw - 2)}" height="4" rx="2" fill="${slotCol(sh[k])}"/>`;
      k = j + 1;
    }
    sh.forEach((s, i) => {
      const h = s.price == null ? 2 : 4 + (BH - 8) * level(s.price), on = !!act(s);
      strip += `<rect data-i="${i}" x="${f1(i * bw + 0.8)}" y="${f1(12 + BH - h)}" width="${f1(bw - 1.6)}" height="${f1(h)}" rx="1" fill="${on ? slotCol(s) : "currentColor"}" opacity="${on ? 0.9 : i === 0 ? 0.55 : 0.22}"/>`;
    });
    for (let i = 0; i < N; i += (N > 64 ? 16 : 12)) {
      const d = new Date(sh[i].t);
      strip += `<text x="${f1(i * bw + 1)}" y="${BH + 26}" font-size="10" letter-spacing="1" fill="currentColor" opacity=".5">${i === 0 ? esc(L.now.toUpperCase()) : String(d.getHours()).padStart(2, "0")}</text>`;
    }
    strip += `<rect class="ewpc-sel" y="10" width="${f1(bw)}" height="${BH + 4}" fill="none" stroke="currentColor" stroke-width="1" rx="2"/></svg>`;
    const legend = [].concat(data.has_battery ? [[COL.charge, L.legend[1]], [COL.discharge, L.legend[0]]] : [])
      .concat(slots.some((s) => s.bat === "export") ? [[COL.export, L.legExport]] : [])
      .concat(cars.filter((c) => slots.some((s) => (s.ev || {})[c.id] > 0.05)).map((c) => [c.col, c.name]))
      .concat(slots.some((s) => s.sun_w) ? [[COL.sun, L.legend[3]]] : []);
    el.innerHTML = `<div class="ewpc">${svg}<div class="ewpc-mid"><div class="ewpc-day"></div><div class="ewpc-time"></div><div class="ewpc-price"></div><div class="ewpc-act"></div></div>
      <button class="ewpc-now" type="button" hidden>${esc(L.now)}</button></div>
      <div class="ewpc-strip"><div class="h"><span>${esc(L.next12)}</span><b class="ewpc-pnow"></b></div>${strip}</div>
      <div class="ewpc-legend">${legend.map(([c, t]) => `<span><i style="background:${c}"></i>${esc(t)}</span>`).join("")}</div>`;
    const root = el.querySelector(".ewpc"), svgEl = root.querySelector("svg"), hl = root.querySelector(".ewpc-hl"), hk = root.querySelector(".ewpc-hk");
    const mid = { day: root.querySelector(".ewpc-day"), time: root.querySelector(".ewpc-time"), price: root.querySelector(".ewpc-price"), act: root.querySelector(".ewpc-act") };
    const nowBtn = root.querySelector(".ewpc-now"), hd = root.querySelector(".ewpc-hd");
    const stripEl = el.querySelector(".ewpc-sv"), sel = el.querySelector(".ewpc-sel");
    const pnow = el.querySelector(".ewpc-pnow");
    let idx = 0;
    const fmtPrice = (p) => (p == null ? "–" : unit === "öre" ? `${Math.round(p * 100)} öre/kWh` : `${p.toFixed(2).replace(".", opts.lang === "en" ? "." : ",")} ${unit}/kWh`);
    function show(i, fromUser) {
      i = Math.max(0, Math.min(slots.length - 1, i));
      if (i === idx && fromUser) return;
      idx = i;
      const s = slots[i], d = new Date(s.t), a = angOf(d);
      const [x1, y1] = pt(a, 108), [x2, y2] = pt(a, R1 + 4);         // visaren börjar utanför texten i mitten
      hl.setAttribute("x1", f1(x1)); hl.setAttribute("y1", f1(y1)); hl.setAttribute("x2", f1(x2)); hl.setAttribute("y2", f1(y2));
      hk.setAttribute("cx", f1(x2)); hk.setAttribute("cy", f1(y2));
      hd.setAttribute("cx", f1(x2)); hd.setAttribute("cy", f1(y2));
      if (sel) { sel.style.display = i < N ? "" : "none"; sel.setAttribute("x", f1(Math.min(i, N - 1) * bw)); }
      svgEl.setAttribute("aria-valuenow", i);
      const sameDay = d.toDateString() === t0.toDateString();
      mid.day.textContent = i === 0 ? L.now : sameDay ? L.today : L.tomorrow;
      mid.time.textContent = (i === 0 ? new Date() : d).toTimeString().slice(0, 5);
      mid.price.textContent = fmtPrice(s.price);
      const acts = [];
      if (s.bat && T.sv[s.bat] !== undefined) {
        let j = i; while (j + 1 < slots.length && slots[j + 1].bat === s.bat && !!slots[j + 1].bat_balance === !!s.bat_balance) j++;      // passets slut
        const end = new Date(new Date(slots[j].t).getTime() + 15 * 60e3);
        let t = (L[s.bat] || s.bat) + ` ${L.until} ${end.toTimeString().slice(0, 5)}`;
        if (s.bat_balance) t = L.balance + " · " + t;
        if (s.bat_kw != null && (s.bat === "charge" || s.bat === "discharge" || s.bat === "export")) t += ` · ${Math.abs(s.bat_kw).toFixed(1)} kW`;
        if (s.soc != null) t += ` · ${s.soc} %`;
        acts.push(`<span style="color:${s.bat === "discharge" ? COL.discharge : s.bat === "export" ? COL.export : s.bat === "charge" ? COL.charge : "inherit"}">${esc(t)}</span>`);
      }
      Object.entries(s.ev || {}).filter(([, kw]) => kw > 0.05).forEach(([car, kw]) =>
        acts.push(`<span style="color:${carCol(car)}">${esc(carName(car))} ${esc(L.charges)} · ${kw.toFixed(1)} kW</span>`));
      if (s.heat && L.heat[s.heat]) acts.push(`<span style="opacity:.8">${esc(L.heat[s.heat])}</span>`);
      if (s.sun_w > 50) acts.push(`<span style="color:${COL.sun}">☀ ${(s.sun_w / 1000).toFixed(1)} kW</span>`);
      mid.act.innerHTML = acts.length ? acts.join("<br>") : `<span style="opacity:.55">${esc(L.nothing)}</span>`;
      nowBtn.hidden = i === 0;
      if (fromUser && navigator.vibrate && i % 4 === 0) { try { navigator.vibrate(4); } catch (e) { /* inte alla webbläsare */ } }
    }
    function idxFromPoint(ev) {
      const r = svgEl.getBoundingClientRect(), x = (ev.clientX - r.left) / r.width * 400 - C, y = (ev.clientY - r.top) / r.height * 400 - C;
      let a = Math.atan2(y, x) + Math.PI / 2;
      if (a < 0) a += 2 * Math.PI;
      const hours = a / (2 * Math.PI) * 24;                       // klockslag 0-24
      const startH = t0.getHours() + t0.getMinutes() / 60;
      let ahead = hours - startH;
      if (ahead < 0) ahead += 24;
      return Math.round(ahead * 4);
    }
    // När sidan runt omkring scrollar (appen med stor text, touch-action: pan-y) väntar ett finger på pekskärm tills det
    // syns om det är en scroll eller en vridning: tar webbläsaren rörelsen som scroll (pointercancel) återställs visaren,
    // ett tryck utan rörelse väljer tiden som förut (2026-11-06: klockan vreds av misstag när man scrollade).
    let dragging = false, pending = false, downIdx = 0;
    const panAllowed = () => /pan/.test(getComputedStyle(svgEl).touchAction || "");
    svgEl.addEventListener("pointerdown", (ev) => {
      dragging = true; downIdx = idx; root.classList.add("drag");
      if (ev.pointerType === "touch" && panAllowed()) { pending = true; return; }
      pending = false; svgEl.setPointerCapture(ev.pointerId); show(idxFromPoint(ev), true); ev.preventDefault();
    });
    svgEl.addEventListener("pointermove", (ev) => {
      if (!dragging) return;
      if (pending) { pending = false; try { svgEl.setPointerCapture(ev.pointerId); } catch (e) { /* redan släppt */ } }
      show(idxFromPoint(ev), true);
    });
    const stop = () => { dragging = false; pending = false; root.classList.remove("drag"); };
    svgEl.addEventListener("pointerup", (ev) => { if (pending) show(idxFromPoint(ev), true); stop(); });
    svgEl.addEventListener("pointercancel", () => { if (dragging) show(downIdx, true); stop(); });
    svgEl.addEventListener("keydown", (ev) => {
      const step = { ArrowRight: 1, ArrowUp: 1, ArrowLeft: -1, ArrowDown: -1, PageUp: 4, PageDown: -4 }[ev.key];
      if (step) { show(idx + step, true); ev.preventDefault(); } else if (ev.key === "Home") { show(0, true); ev.preventDefault(); }
    });
    nowBtn.addEventListener("click", () => show(0, true));
    if (stripEl) {                                        // tryck/dra i remsan flyttar visaren till den kvarten
      const pick = (ev) => { const r = stripEl.getBoundingClientRect(); show(Math.floor((ev.clientX - r.left) / r.width * N), true); };
      let sDrag = false;
      stripEl.addEventListener("pointerdown", (ev) => { sDrag = true; try { stripEl.setPointerCapture(ev.pointerId); } catch (e) { /* äldre webbläsare */ } pick(ev); });
      stripEl.addEventListener("pointermove", (ev) => { if (sDrag || ev.buttons) pick(ev); });
      const sStop = () => { sDrag = false; };
      stripEl.addEventListener("pointerup", sStop); stripEl.addEventListener("pointercancel", sStop);
    }
    if (pnow && slots[0].price != null) pnow.textContent = fmtPrice(slots[0].price) + " " + L.now.toLowerCase();
    show(0, false);
    return { show, get index() { return idx; } };
  }
  window.EWPlanClock = { mount };
})();
