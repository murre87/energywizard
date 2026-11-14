// EnergyWizard Mobil – fem flikar (Hem, Bil, Hus, Plan, Historik). Bil och Hus får plats utan scroll (fit() gömmer detaljer stegvis);
// Hem, Plan och Historik får scrolla. Poll medan sidan syns.
const $ = (s) => document.querySelector(s), app = $("#app");
const LS = { get: (k, d) => { try { return localStorage.getItem(k) ?? d; } catch { return d; } }, set: (k, v) => { try { localStorage.setItem(k, v); } catch {} } };
let FL = null;                     // "Just nu"-flödet på Hem (api/flow, samma som webbens Översikt)
let PC = null, PCAt = 0, PCNEW = false, PCEL = null, PCH = null;   // planklockan (planclock.js) - samma DOM-nod mellan omritningar så att visaren inte hoppar
let LJ = null, VIEWAS = LS.get("ew_viewas", ""), GR = null, ME = "", ROLE = "owner", EN = null, S = null, H = null, page = LS.get("ew_page", "bil"), busy = false, timer = null, installEvt = null, SCH = null, CLIM = null, schCar = "", HIST = null, SET = null, PL = null, SV = null, HX = null, JR = null, jBack = 1, EC = null, ecAt = 0, TL = null, TLAt = 0;
let svPeriod = LS.get("ew_sv_period", "week"), hxPeriod = LS.get("ew_hx_period", "today"), hxRange = LS.get("ew_hx_range", "24h");
// gamla flikar (före fem-flik-layouten) pekas om så ingen hamnar på en tom sida
page = ({ ljus: "hem", energi: "hem", schema: "plan", grafer: "historik" })[page] || page;
const esc = (x) => String(x ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const buzz = (n = 15) => { try { navigator.vibrate && navigator.vibrate(n); } catch {} };
// haptik: en liten vibration direkt när fingret nuddar en knapp (Android; iPhone saknar vibrations-API i webbläsaren, där ger tryckeffekten i CSS återkopplingen)
document.addEventListener("pointerdown", (e) => { if (e.pointerType !== "mouse" && e.target.closest("button, [data-a], [data-v], .tab, .sw")) buzz(8); }, { passive: true });
const moneyUnit = () => (S && S.currency_symbol) || "kr";
const f1 = (x, d = 1) => (x == null ? "–" : Number(x).toFixed(d).replace(".", window.I18N && I18N.lang === "en" ? "." : ","));
function toast(t, ms = 2600) { const e = $("#toast"); e.textContent = window.I18N ? I18N.tr(t) : t; e.classList.add("show"); clearTimeout(toast.t); toast.t = setTimeout(() => e.classList.remove("show"), ms); }
["gesturestart", "gesturechange", "gestureend"].forEach((n) => document.addEventListener(n, (e) => e.preventDefault()));   // iOS: ingen pinch-zoom
async function api(path, body) {
  const r = await fetch("api/" + path, body !== undefined ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {});
  if (r.status === 401 && path !== "login" && path !== "secure") { showLogin(); throw new Error("Inte inloggad"); }
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail || "Fel " + r.status);
  return j;
}
const ICON = {
  bil: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 17h14M3 13l2-6h14l2 6v4h-2a2 2 0 0 1-4 0H9a2 2 0 0 1-4 0H3z"/><circle cx="7.5" cy="17" r="1.6"/><circle cx="16.5" cy="17" r="1.6"/></svg>',
  hus: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 11l9-8 9 8M5 10v10h14V10M10 20v-6h4v6"/></svg>',
  schema: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="5" width="18" height="16" rx="3"/><path d="M8 3v4M16 3v4M3 10h18"/></svg>',
  ljus: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18h6M10 22h4M12 2a7 7 0 0 0-4 12.7c.6.5 1 1.2 1 2V18h6v-1.3c0-.8.4-1.5 1-2A7 7 0 0 0 12 2z"/></svg>',
  energi: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2L4 14h7l-1 8 9-12h-7z"/></svg>',
  hem: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2L4 14h7l-1 8 9-12h-7z"/></svg>',
  plan: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="5" width="18" height="16" rx="3"/><path d="M8 3v4M16 3v4M3 10h18M8 14h3M8 17h6"/></svg>',
  historik: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 20V11M12 20V5M19 20v-7"/></svg>',
  grafer: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20V4M4 20h16M8 16l4-5 3 3 5-7"/></svg>',
  gear: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/></svg>',
};
function showLogin(msg) {
  clearInterval(timer);
  app.innerHTML = `<form class="login card" id="lf"><div class="brand" style="justify-content:center"><span class="dot"></span>EnergyWizard</div><div class="note">Logga in för att styra hemmet.</div><input id="un" placeholder="Användarnamn (admin = ägare)" autocomplete="username" autocapitalize="none"><input type="password" id="pw" placeholder="Lösenord" autocomplete="current-password" required><button class="big" type="submit">Logga in</button><div class="note" style="color:var(--bad)">${esc(msg || "")}</div></form>`;
  $("#lf").onsubmit = async (e) => { e.preventDefault(); try { await api("login", { user: $("#un").value, password: $("#pw").value }); start(); } catch (er) { showLogin(er.message); } };
}
const ER = () => (ROLE === "owner" && VIEWAS) ? VIEWAS : ROLE;                    // effektiv roll: ägaren kan förhandsgranska Elins vy och gästläget
const CAN = { family: ["theme", "ser", "refreshsoc", "installapp", "tab", "swap", "power", "start", "stop", "auto", "heat_on", "heat_off", "access", "cardata", "lights", "trip", "sch", "schcar", "schtime", "schclock", "clim", "climclock", "rooms", "greet", "log", "health", "settings", "hp", "hr", "bigchart", "bigrange", "planall", "planview", "histview", "solarsheet", "insights", "peaks", "closesheet", "nowsheet"],
              guest: ["theme", "ser", "tab", "health", "settings", "swap", "schcar", "cardata", "rooms", "greet", "log", "report", "hp", "hr", "bigchart", "bigrange", "planall", "planview", "histview", "solarsheet", "insights", "peaks", "closesheet", "nowsheet"] };
const can = (a) => ER() === "owner" || (ROLE === "owner" && a === "viewas") || (CAN[ER()] || []).includes(a);   // ägaren kan alltid byta tillbaka från förhandsvisningen
const TABS = { owner: ["hem", "bil", "hus", "plan", "historik"], family: ["hem", "bil", "plan"], guest: ["hem", "bil", "hus", "plan", "historik"] };
const TABNAME = { hem: "Hem", bil: "Bil", hus: "Hus", plan: "Plan", historik: "Historik" };
const primary = () => LS.get("ew_primary", "");
function chooseCar() {
  app.innerHTML = `<div class="card" style="text-align:center;display:grid;gap:14px;margin-top:10dvh"><h2 style="margin:0">Vilken bil kör du mest?</h2><div class="note">Den visas stor överst. Du kan byta senare.</div>${((S && S.cars) || []).map((c, i) => `<button class="big" data-p="${esc(c.key)}">${esc(c.name)}</button>`).join("")}</div>`;
  app.querySelectorAll("[data-p]").forEach((b) => b.onclick = () => { LS.set("ew_primary", b.dataset.p); start(); });
}
// ---- Bil -------------------------------------------------------------------------------------------------------------------------
function planText(c) {
  const sm = c.plan_all && c.plan_all.summary;      // hela planen: första start → sista slut och batteriet efter planen
  if (sm) return `${sm.day === "idag" ? "" : sm.day + " "}${sm.start} → ${sm.end}${sm.soc0 != null ? ` · ${sm.soc0} → ${sm.soc1} %` : ""}`;
  const g = (c.plan || [])[0]; if (!g) return null;
  return `${g.day === "idag" ? "" : g.day + " "}${g.start} → ${g.end}${g.soc0 != null ? ` · ${g.soc0} → ${g.soc1} %` : ""} · ${f1(g.kw)} kW`;
}
function solarText(c) {
  const s = c.solar || {}, today = new Date().toISOString().slice(0, 10);
  if (s.active) return `Solladdar sedan ${(s.last_start || "").slice(11)} · ${s.amps} A ${s.phases}-fas`;
  if (s.last_start && s.last_start.startsWith(today)) return `Sol idag: ${s.last_start.slice(11)}–${(s.last_end || "").slice(11) || "pågår"}`;
  return "Laddar automatiskt när solen ger överskott";
}
function statusInfo(c) {
  if (!c.home) {
    if (!c.away) return { t: "Inte hemma" }; const a = c.away;
    return { t: (a.dest_home === true ? "På väg hem · " : "") + (a.arrival ? `ankommer ${a.arrival}` : a.arrived ? "framme (parkerad)" : "borta") };         // vi kan inte se adressen bilen navigerar till – bara ankomsttid och kvarvarande km
  }
  if (!c.plugged) return { t: "Kabeln är inte ansluten" };
  if (c.charging) return { t: `Laddar ${f1(c.power_kw)} kW` + (c.eta ? ` · klar kl ${c.eta}` : ""), sun: c.solar && c.solar.active };
  if (c.status === "completed") return { t: "Fulladdad" };
  if (c.mode === "hold") return { t: "Stoppad av dig" };
  const p = planText(c);
  const sw = c.soc != null && c.soc >= 98 ? null : sunWindow(S && S.price);
  return { t: c.mode === "manual" ? "Väntar på start" : (p ? "Planerad: " + p : sw ? `☀ Solladdning väntas ca ${sw.txt}` : "Ingen laddning planerad"), plan: true };
}
function ring(pct, color) { const r = 84, C = 2 * Math.PI * r, v = pct == null ? 0 : pct; return `<svg viewBox="0 0 190 190"><circle cx="95" cy="95" r="${r}" fill="none" stroke="var(--line)" stroke-width="12"/><circle cx="95" cy="95" r="${r}" fill="none" stroke="${color}" stroke-width="12" stroke-linecap="round" stroke-dasharray="${(C * v) / 100} ${C}"/></svg>`; }
function actions(c, big) {
  const can = c.home && c.plugged;
  if (c.charging || c.mode === "manual") return `<button class="${big ? "big stop" : "mini"}" data-a="stop" data-c="${c.key}">${big ? "Stoppa laddning" : "Stoppa"}</button>`;
  return `<button class="${big ? "big" : "mini"}" data-a="start" data-c="${c.key}" ${can ? "" : "disabled"}>${big ? "Ladda nu" : "Ladda"}</button>`;
}
const ageTxt = (h) => (h < 1 ? Math.round(h * 60) + " min" : h < 48 ? Math.round(h) + " h" : Math.round(h / 24) + " dygn");
const staleChip = (c) => (c.age_h != null && c.age_h > 2 ? `<button class="chip warn" data-a="cardata" data-c="${c.key}" title="Bilen har inte skickat nya värden. Öppna för att väcka den och uppdatera.">Data ${ageTxt(c.age_h)} gammal</button>` : "");
const heatChip = (c) => (c.climate_on ? `<span class="chip heat">🔥 Värmen är på${c.inside != null ? " · " + f1(c.inside) + " °" : ""}</span>` : "");
const planPill = (c) => { const sm = c.plan_all && c.plan_all.summary; if (!sm) return null;
  return `<a class="plink pill" data-a="planlist" data-c="${c.key}" role="button" tabindex="0" title="Visa alla laddblock"><span class="pi">⚡</span><b>${sm.day === "idag" ? "" : esc(sm.day) + " "}${sm.start} → ${sm.end}</b>${sm.soc0 != null ? `<em>${sm.soc0} → ${sm.soc1} %</em>` : ""}<span class="pc">›</span></a>`; };
const planLink = (c, t) => (c.home && t.startsWith("Planerad") && planPill(c) ? planPill(c) : c.home && c.plugged && (t.startsWith("☀") || t.startsWith("Ingen laddning") || (c.plan_all && c.plan_all.blocks && c.plan_all.blocks.length)) ? `<a class="plink" data-a="planlist" data-c="${c.key}" role="button" tabindex="0">${esc(t)} ›</a>` : esc(t));
function planSheet(key) {
  const c = S.cars.find((x) => x.key === key); if (!c) return;
  sheet(`<h3>Laddplan – ${esc(c.name)}</h3>${planChart(S.price, [c])}${planList(c)}<button class="big" data-v="ok">Stäng</button>`);
  $("#sheet").onclick = (e) => { if (e.target.id === "sheet" || e.target.closest("[data-v]")) closeSheet(); };
}
function planList(c) {
  const pa = c.plan_all; if (!c.home || !pa || !pa.blocks || !pa.blocks.length) return "";
  const mx = Math.max(...pa.blocks.map((b) => b.kwh), 0.1);
  let prevDay = null; const rows = pa.blocks.map((b) => { const showDay = b.day !== prevDay; prevDay = b.day; return `<div class="pb${b.before_morning ? " early" : ""}"><div class="pbt"><b>${b.start}–${b.end}</b><span class="pbd">${showDay ? esc(b.day) : "&nbsp;"}</span></div><div class="pbbar"><i style="width:${Math.max(6, Math.round((b.kwh / mx) * 100))}%"></i></div><div class="pbn">${b.soc0 != null ? `${b.soc0} → ${b.soc1} %` : f1(b.kwh) + " kWh"}<small>${f1(b.kw)} kW</small></div></div>`; }).join("");
  const fl = pa.floor ? `<div class="pfloor ${pa.floor.ok ? "ok" : "warn"}">${pa.floor.ok ? "✓" : "⚠"} ${pa.floor.soc} % kl ${pa.floor.time}${pa.floor.ok ? " (golv 50 %)" : " – under golvet 50 %"}</div>` : "";
  return `<div class="plist"><div class="phead"><b>Laddplan</b><span>${pa.blocks.length} block · ${f1(pa.kwh)} kWh</span></div>${rows}${fl}</div>`;
}
function hero(c) {
  const si = statusInfo(c), color = c.soc == null ? "var(--mut)" : c.soc < 20 ? "var(--bad)" : c.soc < 40 ? "var(--warn)" : "var(--acc)";
  const chips = [`<span class="chip ${c.home ? "ok" : ""}">${c.home ? "Hemma" : "Borta" + (c.away && c.away.car_km_from_home != null ? ` · ${c.away.car_km_from_home} km hemifrån` : "")}</span>`, c.home ? `<span class="chip ${c.plugged ? "ok" : "warn"}">${c.plugged ? "Kabel i" : "Ingen kabel"}</span>` : "", staleChip(c), c.soc_stale ? `<span class="chip warn" title="Bilen svarar inte just nu – visar senast kända värden">Senast kända värde</span>` : "", heatChip(c), c.mode === "manual" ? `<span class="chip warn">${c.charge_now_target ? `Laddar till ${c.charge_now_target} % · ` : "Manuellt "}${c.amps} A${c.phases ? " · " + c.phases + "-fas" : ""}</span>` : "", ...(c.facts || []).slice(0, 2).map((f) => `<span class="chip">${esc(f)}</span>`)].join("");
  return `<section class="card hero${c.climate_on ? " heating" : ""}"><div class="carname">${esc(c.name)} ${ER() === "family" ? "" : `<button class="link" data-a="cardata" data-c="${c.key}">Alla data</button>`}</div><div class="ring">${ring(c.soc, color)}<div class="pct" data-a="refreshsoc" data-c="${c.key}" title="Tryck för att uppdatera"><b>${c.soc == null ? "–" : c.soc}<small style="font-size:.45em">%</small></b><span>batteri</span></div></div>
  <div class="chips">${chips}</div>${c.limit_note ? `<div class="note limnote">${esc(c.limit_note)}</div>` : ""}<div class="stat">${planLink(c, si.t)}${c.away && c.away.km ? ` <span class="note">· ${c.away.km} km kvar</span>` : ""}</div>${c.home && c.plugged ? `<div class="note sunline${c.solar && c.solar.active ? " on" : ""}">${esc(solarText(c))}</div>` : ""}${c.home ? actions(c, true) : ""}
  ${c.guest ? `<div class="chips"><button class="chip ok" data-a="guest" data-c="${c.key}">Gästbil: ${c.guest.kwh} kWh${c.guest.until ? " · klar " + hhmm(c.guest.until) : " · laddar direkt"}</button></div>` : ""}
  <div class="chips crowline">${ER() !== "guest" ? `<button class="mini" data-a="guest" data-c="${c.key}" title="Ladda en bil som inte är din på den här laddboxen">Gästbil</button>` : ""}${c.home ? `<button class="mini${c.climate_on ? " on heat" : ""}" data-a="${c.climate_on ? "heat_off" : "heat_on"}" data-c="${c.key}" title="${c.climate_on ? "Stoppa värme" : "Starta värme"}" aria-label="${c.climate_on ? "Stoppa värme" : "Starta värme"}">${c.climate_on ? "🔥 Värme" : "Värme"}</button>` : ""}${c.home && c.plugged ? `<button class="mini" data-a="power" data-c="${c.key}" title="Välj laddeffekt" aria-label="Välj effekt">Effekt</button>` : ""}${c.home && c.plugged ? `<button class="mini" data-a="trip" data-c="${c.key}">Resplan</button>` : ""}${c.mode !== "auto" ? `<button class="mini" data-a="auto" data-c="${c.key}">Auto</button>` : ""}${c.access ? `<button class="mini${c.access.locked ? "" : " warnb"}" data-a="access" title="Lås och luckor" aria-label="Lås och luckor">${c.access.locked ? "Lås" : "Olåst"}</button>` : ""}</div></section>`;
}
function compact(c) {
  const si = statusInfo(c);
  return `<section class="card${c.climate_on ? " heating" : ""}"><div class="chead"><div class="cname">${esc(c.name)} ${ER() === "family" ? "" : `<button class="link" data-a="cardata" data-c="${c.key}">Alla data</button>`}</div><div class="csoc" data-a="refreshsoc" data-c="${c.key}" title="Tryck för att uppdatera">${c.soc ?? "–"}<small>%</small>${c.age_h != null && c.age_h > 2 ? `<small style="color:var(--warn);display:block;font-size:.62rem;font-weight:500">${ageTxt(c.age_h)} gammal</small>` : ""}</div></div><div class="bar"><i style="width:${c.soc ?? 0}%"></i></div>
  <div class="note compact-note" style="margin-bottom:8px">${esc(si.t)}${c.climate_on ? " · 🔥 värmen är på" : ""}</div>${c.limit_note ? `<div class="note limnote" style="margin-bottom:8px">${esc(c.limit_note)}</div>` : ""}<div class="crow">${c.home ? actions(c, false) : ""}${c.home ? `<button class="mini" data-a="${c.climate_on ? "heat_off" : "heat_on"}" data-c="${c.key}">${c.climate_on ? "Stoppa värme" : "Starta värme"}</button>` : ""}${c.mode !== "auto" ? `<button class="mini" data-a="auto" data-c="${c.key}">Auto</button>` : ""}${c.access ? `<button class="mini" data-a="access">Lås</button>` : ""}</div></section>`;
}
const SUN_MIN_W = 2500;                                   // ca 2,5 kW sol = över 1,4 kW överskott efter husets last (solladdningens startgräns)
function sunWindow(p) {                                   // första sammanhängande soltimmarna från nu: {a, b} index i p.hours, eller null
  const hs = (p && p.hours) || [], nowI = Math.max(0, hs.findIndex((h) => h.now)); let a = -1, b = -1;
  for (let k = nowI; k < hs.length; k++) { if ((hs[k].sun || 0) >= SUN_MIN_W) { if (a < 0) a = k; b = k; } else if (a >= 0) break; }
  return a < 0 ? null : { a, b, txt: `${hs[a].t}–${String((+hs[b].t + 1) % 24).padStart(2, "0")}` };
}
// Laddplan + elpris: prisstaplar över dygnet med en rad per bil som visar när den laddar (samma tidsaxel).
function planChart(p, cars) {
  if (!p || p.now == null) return "";
  const hs = p.hours || [], H = 3600000, t0 = hs.length ? hs[0].ts : 0, span = Math.max(hs.length, 1) * H;
  const mx = Math.max(...hs.map((h) => h.p), 0.1), srt = hs.map((h) => h.p).sort((a, b) => a - b), lowT = srt[Math.floor(srt.length / 3)] ?? 0;
  const segs = (c) => { const out = []; (c.plan_slots || []).forEach((q) => { const l = out[out.length - 1]; if (l && q.t - l.e <= 60000) { l.e = q.t + 900000; l.kw += q.kw; l.n++; } else out.push({ s: q.t, e: q.t + 900000, kw: q.kw, n: 1 }); }); return out; };
  const sunH = hs.map((h) => h.sun || 0), sunMax = Math.max(...sunH, 1), hasSun = sunH.some((v) => v > 0), sw = sunWindow(p);
  const sunTxt = sw ? `☀ sol ca ${sw.txt}` : null;
  const lanes = cars.map((c) => { const g = segs(c).filter((x) => x.e > t0 && x.s < t0 + span), col = cars.indexOf(c) % 2 === 0 ? "var(--acc)" : "var(--acc2)";
    const bars = g.map((x) => `<i style="left:${(Math.max(x.s, t0) - t0) / span * 100}%;width:${(Math.min(x.e, t0 + span) - Math.max(x.s, t0)) / span * 100}%;background:${col}" title="${f1(x.kw / x.n)} kW"></i>`).join("");
    const pa = c.plan_all && c.plan_all.blocks && c.plan_all.blocks.length ? c.plan_all : null;
    const full = c.soc != null && c.soc >= 98;
    const sunBar = (!pa && !full && sw && hs[sw.a] && hs[sw.b]) ? `<i class="predicted" style="left:${(hs[sw.a].ts - t0) / span * 100}%;width:${((hs[sw.b].ts + H - hs[sw.a].ts)) / span * 100}%;background:${col}" title="Väntad solladdning, ej bekräftad ännu"></i>` : "";
    const txt = !c.home ? "inte hemma" : !c.plugged ? "kabeln ej i" : pa ? `${pa.blocks[0].start}–${pa.blocks[pa.blocks.length - 1].end}${pa.summary && pa.summary.soc0 != null ? ` · ${pa.summary.soc0}→${pa.summary.soc1} %` : ""}` : full ? "fulladdad" : sunTxt ? `inget prisschema · solladdning väntas automatiskt ${sunTxt}` : "ingen laddning planerad";
    return `<div class="pc-lane"><span class="pc-name" style="color:${col}">${esc(c.name.split(" ")[0])}</span><div class="pc-track">${bars}${sunBar}</div><button class="pc-txt" data-a="cardata" data-c="${c.key}" title="Tryck för alla data">${esc(txt)}</button></div>`; }).join("");
  const nowAt = hs.length ? (Date.now() - t0) / span * 100 : 0;
  return `<section class="card price pchart"><div class="head"><div><span class="note">Laddplan · elpris nu </span><span class="now">${f1(p.now, 2)} <small>${moneyUnit()}/kWh</small></span></div><span class="chip ${p.level === "billigt" ? "ok" : p.level === "dyrt" ? "bad" : ""}">${esc(p.level || "")}</span></div>
  <div class="pc-plot">${hasSun ? `<div class="pc-bars pc-sun" aria-hidden="true">${hs.map((h, k) => `<span><i style="height:${Math.round(sunH[k] / sunMax * 100)}%"></i></span>`).join("")}</div>` : ""}<div class="pc-bars">${hs.map((h) => `<span class="${h.now ? "now" : h.p <= lowT ? "low" : ""}"><i style="height:${Math.max(10, (h.p / mx) * 100)}%"></i></span>`).join("")}</div>${nowAt >= 0 && nowAt <= 100 ? `<b class="pc-now" style="left:${nowAt}%"></b>` : ""}</div>
  <div class="pc-lanes">${lanes}</div><div class="hrs pc-hrs">${hs.map((h, k) => `<span>${k % 4 === 0 ? h.t : ""}</span>`).join("")}</div>
  <div class="pc-legend"><span><i style="background:var(--line)"></i>elpris</span><span><i style="background:var(--acc)"></i>billig timme</span>${hasSun ? `<span><i style="background:rgba(251,191,36,.5)"></i>sol</span>` : ""}<span>· heldragen linje = bekräftad laddning</span><span>· randig linje = väntad solladdning, ej bekräftad</span></div></section>`;
}
function pageBil() {
  if (!S) return `<div class="note" style="text-align:center;margin-top:20dvh">Laddar…</div>`;
  if (!S.cars.length) return `<div class="page"><section class="card"><div class="note">${S.ok === false ? esc(S.error || (S.health || []).join(" · ")) : "Inga bilar hittades"}</div></section></div>`;
  const p = primary(), main = S.cars.find((c) => c.key === p) || S.cars[0], other = S.cars.find((c) => c !== main), simple = LS.get("ew_simple", "") === "1";
  const carseg = `<div class="seg carseg">${S.cars.map((c) => `<button data-a="swap" data-c="${c.key}" class="${c.key === main.key ? "on" : ""}">${esc(c.name.split(" ")[0])} · ${c.soc ?? "–"} %</button>`).join("")}</div>`;
  const ec = EC && window.EWJournal ? EWJournal.evCostHtml(EC, { compact: true, unit: moneyUnit() }) : "";     // laddat och vad det kostade (ev_cost.py)
  return `<div class="page">${carseg}${hero(main)}${simple ? "" : compact(other)}${planChart(S.price, S.cars)}${ec && !simple ? `<section class="card">${ec}</section>` : ""}</div>`;
}
// ---- Hus -------------------------------------------------------------------------------------------------------------------------
const MODE = { auto: "Auto", on: "Till", off: "Från" };
function seg(kind, cur, opts) { return `<div class="seg">${opts.map(([v, l]) => `<button data-a="home" data-k="${kind}" data-v="${v}" class="${cur === v ? "on" : ""}">${l}</button>`).join("")}</div>`; }
function gridChip(pw) {
  if (pw.net_w == null) return "";
  return pw.net_w < -50 ? `<span class="chip ok">Säljer ${f1(-pw.net_w / 1000)} kW</span>` : `<span class="chip">Köper ${f1(Math.max(0, pw.net_w) / 1000)} kW</span>`;
}
function limitChip(pw) {
  if (pw.solar_limit_pct == null) return "";
  if (pw.solar_limit_pct >= 99.5) return `<span class="chip">SolarEdge: ingen begränsning</span>`;
  return `<span class="chip warn">SolarEdge begränsad till ${Math.round(pw.solar_limit_pct)} %${pw.price_now != null && pw.price_now <= 0 ? " (minuspris)" : ""}</span>`;
}
function pageHus() {
  if (!H) return `<div class="note" style="text-align:center;margin-top:20dvh">Laddar…</div>`;
  const h = H.heat, w = H.water, sp = H.spa, pw = H.power;
  const pct = pw.limit_kw && pw.total_w != null ? Math.min(100, (pw.total_w / 1000 / pw.limit_kw) * 100) : 0;
  return `<div class="page"><div class="grid2">
  <section class="card tile"><h4>Värme inne <button class="link" data-a="rooms" style="padding:0 0 0 6px;font-size:.8rem">alla rum</button></h4><div class="v">${f1(h.inside)}<small> °C</small></div><div class="note">Mål ${f1(h.target)}° · ute ${f1(h.outside, 0)}° · pump ${h.pump_w != null ? Math.round(h.pump_w) : "–"} W</div>${seg("heat", h.mode, [["auto", "Auto"], ["on", "Varm"], ["off", "Sänkt"]])}</section>
  <section class="card tile"><h4>Varmvatten</h4><div class="v">${f1(w.temp, 0)}<small> °C</small></div><div class="note">COP ${f1(h.cop)}${w.until ? ` · Auto om ${hwLeft(w.until)}` : ""}</div>${seg("hotwater", w.mode, [["auto", "Auto"], ["on", "Till"], ["off", "Från"]])}</section>
  <section class="card tile wide"><h4>Spabad</h4><div class="v">${f1(sp.temp)}<small> °C</small></div><div class="note">Mål ${f1(sp.target)}° · ${esc(sp.heater || "")}${sp.error && sp.error !== "None" ? ` · ${esc(sp.error)}` : ""}</div>
    <div class="tilelink"><button class="link" data-a="spaready" style="padding:0;font-size:.82rem">${sp.ready_at ? `Klart ${esc(sp.ready_at)} (${f1(sp.ready_temp)}°) – ändra` : "Ställ in: klart kl…"}</button>${ROLE !== "guest" ? ` · <button class="link" data-a="spabath" style="padding:0;font-size:.82rem">Badtider${(sp.bath_windows || []).some((w) => w.on) ? ` (${(sp.bath_windows || []).filter((w) => w.on).length})` : ""}</button>` : ""}</div><div class="seg"><button data-a="spa" data-k="spa_auto" data-v="1" class="${!sp.force_heat && !sp.eco ? "on" : ""}" title="Följer sitt eget schema, som Home Assistant styr">Auto</button><button data-a="spa" data-k="spa_heat" data-v="${sp.force_heat ? 0 : 1}" class="${sp.force_heat ? "on" : ""}">Värm nu</button><button data-a="spa" data-k="spa_eco" data-v="${sp.eco ? 0 : 1}" class="${sp.eco ? "on" : ""}">Eco</button></div></section>
  <section class="card tile wide"><div style="display:flex;justify-content:space-between;align-items:baseline"><h4>Effekt nu</h4><span class="note">${pw.peak ? `Effektvakt på · gräns ${f1(pw.limit_kw)} kW` : "Effektvakt av"}</span></div><div class="v">${pw.total_w != null ? f1(pw.total_w / 1000) : "–"}<small> kW</small></div>
    <div class="meter" ${pw.peak ? "" : 'style="opacity:.35"'}><i class="${pct > 85 ? "hi" : ""}" style="width:${pw.peak ? pct : 0}%"></i></div><div class="chips" style="justify-content:flex-start">${gridChip(pw)}${limitChip(pw)}<span class="chip">Elbil ${pw.ev_w != null ? f1(pw.ev_w / 1000) : "–"} kW</span><span class="chip ${pw.solar_w > 100 ? "ok" : ""}">Sol ${pw.solar_w != null ? f1(pw.solar_w / 1000) : "–"} kW</span><span class="chip ok">Sparat idag ${f1(pw.saving_today, 1)} ${moneyUnit()}</span></div></section>
  </div></div>`;
}
// ---- levande bilder i energikorten: styrka avgör storlek, glöd och fart ------------------------------------------------------------------
function sunViz(w, ref) {
  const kw = (w || 0) / 1000, p = Math.max(0, Math.min(1, kw / Math.max(3, (ref || 0) / 1000, 6))), dim = kw < 0.05;
  const dur = (26 - 20 * p).toFixed(1), rays = Array.from({ length: 12 }, (_, i) => { const a = i * 30; return `<line x1="50" y1="${(30 - 15 - 7 * p).toFixed(1)}" x2="50" y2="${(30 - 19 - 9 * p).toFixed(1)}" transform="rotate(${a} 50 30)"/>`; }).join("");
  return `<div class="viz sun${dim ? " dim" : ""}" aria-hidden="true"><svg viewBox="0 0 100 60" preserveAspectRatio="xMidYMid meet"><defs><radialGradient id="sg"><stop offset="0" stop-color="#fff3b0"/><stop offset=".6" stop-color="#fbbf24"/><stop offset="1" stop-color="#f97316"/></radialGradient></defs>
    <circle class="glow" cx="50" cy="30" r="${(13 + 17 * p).toFixed(1)}" style="animation-duration:${(3.4 - 1.6 * p).toFixed(1)}s;opacity:${(0.18 + 0.45 * p).toFixed(2)}"/><g class="rays" style="animation-duration:${dur}s;opacity:${(0.35 + 0.65 * p).toFixed(2)}">${rays}</g><circle cx="50" cy="30" r="${(7 + 6 * p).toFixed(1)}" fill="url(#sg)"/></svg></div>`;
}
function gridViz(net) {
  const kw = Math.abs(net || 0) / 1000, p = Math.max(0, Math.min(1, kw / 6)), idle = !net || Math.abs(net) < 50, sell = net < -50, dur = (2.4 - 1.8 * p).toFixed(2), col = sell ? "var(--acc, #22d3a0)" : "var(--warn, #fbbf24)";
  const chev = [0, 1, 2, 3].map((i) => `<path class="ch ${sell ? "l" : "r"}" d="M52 22 L60 30 L52 38" style="animation-duration:${dur}s;animation-delay:${(-i * Number(dur) / 4).toFixed(2)}s;stroke:${col}"/>`).join("");
  return `<div class="viz gridv${idle ? " dim" : ""}" aria-hidden="true"><svg viewBox="0 0 120 60" preserveAspectRatio="xMidYMid meet"><g class="pyl" stroke="currentColor" fill="none" stroke-width="2" stroke-linecap="round"><path d="M12 8 L22 52 M32 8 L22 52 M14 20 H30 M16 32 H28 M10 14 H34"/></g>
    <g class="house" stroke="currentColor" fill="none" stroke-width="2" stroke-linejoin="round"><path d="M92 30 L106 18 L120 30 M95 28 V50 H117 V28"/></g>${idle ? '<path class="idle" d="M44 30 H84" stroke="currentColor" stroke-dasharray="3 5"/>' : chev}</svg></div>`;
}
// ---- Hem (Just nu) --------------------------------------------------------------------------------------------------------------
const SVP = [["today", "Idag"], ["week", "7 d"], ["month", "Månad"]];
function svLine() {                                       // besparingen på en rad – bara ägaren (servern svarar hidden för andra)
  if (!SV || !SV.ok) return "";
  const p = SV.periods[svPeriod] || SV.periods.week, pos = p.saved_kr >= 0;
  return `<section class="card svline"><div><h4>Sparat genom smart tajmning</h4><div class="v" style="color:${pos ? "var(--acc)" : "var(--bad)"}">${p.saved_kr > 0 ? "+" : p.saved_kr < 0 ? "−" : ""}${f1(Math.abs(p.saved_kr), 0)}<small> ${moneyUnit()}${p.pct != null ? ` (${p.pct > 0 ? "+" : ""}${f1(p.pct, 0)} %)` : ""}</small></div></div>
    <div class="seg">${SVP.map(([k, l]) => `<button data-a="svp" data-v="${k}" class="${k === svPeriod ? "on" : ""}">${l}</button>`).join("")}</div></section>`;
}
function planNow() {                                   // vad görs nu och varför (per enhet, ur motorns beslut) + nästa steg i planen
  const now = (EN && EN.now) || [], nxt = PL ? (PL.items || []).find((i) => !i.active) : null;
  if (!now.length && !nxt) return PL ? `<section class="card plannow" data-a="nowsheet"><div class="note">${(PL.headline_parts || [PL.headline]).map(part => `<span>${esc(part)}</span>`).join("")}</div></section>` : "";
  // unslop 2026-11: etikett till vänster, hela meningen till höger (ingen emoji, inget "…")
  const rows = CL()
    ? now.slice(0, 3).map((i) => `<div class="pnrow"><span class="pnl">${esc(i.icon)}</span><span><b>${esc(i.label)}</b><span class="note"> ${esc(i.text)}</span></span></div>`).join("")
    : now.slice(0, 3).map((i) => `<div class="pnrow2"><span class="pnk">${esc(i.label)}</span><span>${esc(i.text)}</span></div>`).join("");
  const later = !nxt ? "" : CL()
    ? `<div class="pnrow"><span class="pnl pnl-t">Sen</span><span><b>${esc(nxt.title.replace(/^[^\p{L}\p{N}]+/u, ""))}</b><span class="note"> ${esc(nxt.when)}</span></span></div>`
    : `<div class="pnrow2"><span class="pnk">Sen</span><span>${esc(nxt.title.replace(/^[^\p{L}\p{N}]+/u, ""))} <span class="note">${esc(nxt.when)}</span></span></div>`;
  return `<section class="card plannow" data-a="nowsheet">${rows}${later}</section>`;
}
async function roomsSheet() {                            // "alla rum": de valda innegivarna, live (api/rooms)
  sheet(`<h3>Rum</h3><div class="note">Laddar…</div>`);
  let d; try { d = await api("rooms"); } catch (e) { sheet(`<h3>Rum</h3><div class="note">${esc(e.message)}</div>`); return; }
  const rows = (d.rows || []).map((r) => `<div class="plrow"><div style="flex:1">${esc(r.name)}</div><b>${f1(r.temp)} °</b></div>`).join("");
  sheet(`<h3>Rum</h3>${rows || `<div class="note">Inga innegivare valda. Välj dem under Inställningar på webben (Givare).</div>`}
    ${d.humidity != null ? `<div class="note" style="margin-top:8px">Luftfuktighet ${d.humidity} %</div>` : ""}<div class="crow"><button class="mini" data-a="closesheet">Stäng</button></div>`);
}
// Gästbil (#131): en bil som inte finns i installationen laddas på den här laddboxen - hur mycket och ev. när klar
const hhmm = (t) => new Date(t).toTimeString().slice(0, 5);
function guestSheet(c) {
  const g = c.guest;
  sheet(`<h3>Gästbil på ${esc(c.name)}s laddbox</h3>
    <div class="note">För en bil som inte är din: ingen laddnivå behövs. Säg hur mycket den ska få, och om den ska vara klar till en viss tid laddas de billigaste timmarna fram till dess. Avslutas av sig själv när kabeln dras ur.</div>
    <div class="seg" style="margin-top:10px">${[5, 10, 20, 30, 50].map((k) => `<button data-gk="${k}" class="${(g ? g.kwh : 20) == k ? "on" : ""}">${k} kWh</button>`).join("")}</div>
    <div class="setrow"><span>Klar till (valfritt)</span><input type="time" id="guntil" value="${g && g.until ? hhmm(g.until) : ""}"></div>
    <div class="crow"><button class="mini" id="gstart">${g ? "Ändra" : "Starta"}</button>${g ? `<button class="mini" id="gstop">Avsluta gästläget</button>` : ""}<button class="mini" data-a="closesheet">Stäng</button></div>`);
  let kwh = g ? g.kwh : 20;
  document.querySelectorAll("[data-gk]").forEach((b) => b.onclick = () => { kwh = +b.dataset.gk; document.querySelectorAll("[data-gk]").forEach((x) => x.classList.toggle("on", x === b)); });
  document.getElementById("gstart").onclick = async () => { try { const r = await api(`car/${c.key}/guest`, { kwh, until: document.getElementById("guntil").value || null }); toast(r.msg); closeSheet(); load(); } catch (e) { toast(e.message); } };
  const st = document.getElementById("gstop"); if (st) st.onclick = async () => { try { const r = await api(`car/${c.key}/guest`, { off: true }); toast(r.msg); closeSheet(); load(); } catch (e) { toast(e.message); } };
}
function nowSheet() {
  const now = (EN && EN.now) || [];
  sheet(`<h3>Vad görs nu – och varför</h3>${now.length ? now.map((i) => `<div class="plrow"><div style="flex:none;font-size:1.2rem">${esc(i.icon)}</div><div><b>${esc(i.label)}</b><div class="note">${esc(i.text)}</div></div></div>`).join("") : '<div class="note">Inget beslut loggat de senaste minuterna.</div>'}
    <div class="crow"><button class="mini" data-a="tab" data-v="plan">Hela planen</button><button class="mini" data-a="closesheet">Stäng</button></div>`);
}
function ljusRow() {
  if (!can("lights") || !LJ || !LJ.configured) return "";       // inga valda lampor -> inga lampknappar (#134)
  return `<div class="ljquick">${LJ.has_windows ? `<button class="mini" data-a="lights" data-v="windows_on">Tänd fönster</button><button class="mini" data-a="lights" data-v="windows_off">Släck fönster</button>` : ""}${LJ.has_up ? `<button class="mini" data-a="lights" data-v="up_on">Tänd uppe</button><button class="mini night" data-a="lights" data-v="goodnight">Godnatt</button>` : ""}</div>`;
}
// ---- Hemskärmens rutor (2026-11-06): fyra kompakta rutor i stället för två stora (sol/nät), så att det man oftast
// vill veta syns direkt: inne och värmepump, nätet, sol eller varmvatten, och batteri eller nästa billiga timme. ----
const MODE_TXT = { CHEAP: "värmer", COMFORT: "normal", EXPENSIVE: "sänkt", SOLAR: "solvärme" };
function nextCheap() {                                      // billigaste hela timmen de närmaste 12 h, ur planens priser
  const sl = (PC && PC.slots) || [], now = Date.now(); let best = null;
  for (let i = 0; i + 3 < sl.length; i++) {
    const t = Date.parse(sl[i].t); if (t < now - 15 * 60e3 || t > now + 12 * 3600e3) continue;
    const ps = sl.slice(i, i + 4).map((x) => x.price); if (ps.some((x) => x == null)) continue;
    const avg = ps.reduce((a, b) => a + b, 0) / 4; if (!best || avg < best.avg) best = { avg, t };
  }
  return best;
}
const qt = (a, label, value, sub, extra = "") => `<section class="card qt" ${a}><h4>${label}</h4><div class="qv">${value}</div><div class="qs">${sub || "&nbsp;"}</div>${extra}</section>`;
function quickGrid(s, g, net, flowShown) {             // flowShown: nät och sol syns redan i "Just nu"
  const h = (EN && EN.house) || {}, b = EN && EN.battery, hh = (t) => new Date(t).toTimeString().slice(0, 5);
  const tiles = [];
  tiles.push(qt('data-a="tab" data-v="hus"', "Inne", h.inside != null ? `${f1(h.inside)}<small>°C</small>` : "–",
    [h.target != null ? `mål ${f1(h.target, 0)}°` : "", h.mode ? (MODE_TXT[h.mode] || h.mode.toLowerCase()) : ""].filter(Boolean).join(" · ")));
  if (!flowShown) tiles.push(qt('data-a="insights"', "Nät", net == null ? "–" : `${net < -50 ? "−" : ""}${f1(Math.abs(net) / 1000)}<small> kW</small>`,
    `${net == null ? "" : net < -50 ? "säljer" : "köper"}${g.price != null ? ` · ${f1(g.price, 2)} ${moneyUnit()}` : ""}`));
  const sunUp = (s.w != null && s.w > 50) || (s.forecast_w != null && s.forecast_w > 100);
  if (flowShown) { /* sol, nät, varmvatten och batteri syns redan i "Just nu" */ }
  else if (sunUp || h.water == null) tiles.push(qt('data-a="solarsheet"', "Sol", s.w != null ? `${f1(s.w / 1000)}<small> kW</small>` : "–", s.today_kwh != null ? `idag ${f1(s.today_kwh, 0)} kWh` : ""));
  else tiles.push(qt('data-a="tab" data-v="hus"', "Varmvatten", `${f1(h.water, 0)}<small>°C</small>`, h.running ? "pumpen går" : "pumpen vilar"));
  if (flowShown) { /* billigaste timmen syns i planen under */ }
  else if (b && b.soc != null) tiles.push(qt('data-a="insights"', "Batteri", `${b.soc}<small> %</small>`, b.w == null ? "" : b.w > 30 ? `laddar ${f1(b.w / 1000)} kW` : b.w < -30 ? `laddar ur ${f1(-b.w / 1000)} kW` : "vilar"));
  else { const c = nextCheap(); tiles.push(qt('data-a="tab" data-v="plan"', "Billigast", c ? `${hh(c.t)}` : "–", c ? `${f1(c.avg, 2)} ${moneyUnit()}/kWh` : "")); }
  if (SV && SV.ok) {                                      // besparingen som ruta; tryck = nästa period (idag → 7 d → månad)
    const ks = SVP.map(([k]) => k), i = Math.max(0, ks.indexOf(svPeriod)), p = SV.periods[svPeriod] || SV.periods.week, nxt = ks[(i + 1) % ks.length];
    const lbl = (SVP.find(([k]) => k === svPeriod) || [, ""])[1];
    tiles.push(qt(`data-a="svp" data-v="${nxt}"`, `Sparat · ${lbl}`, `<span style="color:${p.saved_kr >= 0 ? "var(--acc)" : "var(--bad)"}">${p.saved_kr > 0 ? "+" : p.saved_kr < 0 ? "−" : ""}${f1(Math.abs(p.saved_kr), 0)}</span><small> ${moneyUnit()}</small>`,
      p.pct != null ? `${p.pct > 0 ? "+" : ""}${f1(p.pct, 0)} % billigare` : ""));
  }
  if (EN && EN.today_kwh != null) tiles.push(qt('data-a="tab" data-v="historik"', "Idag", `${f1(EN.today_kwh, 0)}<small> kWh</small>`, "förbrukat hittills"));
  return `<div class="qgrid">${tiles.join("")}</div>`;
}
function carsRow() {                                        // bilarnas laddnivå på en rad (tryck = Bil-fliken)
  const cars = (S && S.cars) || []; if (!cars.length) return "";
  // en bricka per bil: namn, laddnivå och en tunn laddstapel (grön när den laddar)
  return `<div class="carsrow" data-a="tab" data-v="bil">${cars.map((c) => `<div class="card cr${c.charging ? " on" : ""}"><div class="crh"><b>${esc(c.name.split(" ")[0])}</b>
    <span class="crs">${c.soc != null ? c.soc + "<small>%</small>" : "–"}</span></div><div class="crbar"><i style="width:${Math.max(0, Math.min(100, c.soc || 0))}%"></i></div>
    <div class="crn">${c.charging ? `laddar ${f1(c.power_kw)} kW` : !c.home ? "borta" : c.plugged ? "inkopplad" : "hemma"}</div></div>`).join("")}</div>`;
}

// ---- "Just nu" (2026-11-07, Emil: framsidan ska tydligt visa vad som sker just nu, som webbens Översikt) ----
// Källorna till vänster (sol, nät, batteri), huset i mitten, det som drar el till höger. Varje ruta: stor siffra och
// ett statusord. Prickarna rör sig åt det håll elen går. Bara det huset har (live_flow.py).
const FL_TAB = { sol: ["solarsheet"], nat: ["insights"], batteri: ["insights"], varmepump: ["tab", "hus"], varmvatten: ["tab", "hus"], spabad: ["tab", "hus"] };
function flowCard() {                    // delad med webbens Översikt (smartbox/static/liveflow.js) - samma bild och regler
  if (!FL || !FL.ok || !FL.nodes || !window.EWLiveFlow) return "";
  const attrs = (n) => { const t = n.key.startsWith("ev_") ? ["tab", "bil"] : (FL_TAB[n.key] || ["tab", "hus"]); return `data-a="${t[0]}"${t[1] ? ` data-v="${t[1]}"` : ""}`; };
  return `<section class="card flowcard"><div class="flh"><b>Just nu</b><span class="note">${esc(FL.ts || "")}</span></div>${EWLiveFlow.svg(FL, { compact: true, icons: CL(), attrs, hubAttrs: 'data-a="insights"' })}</section>`;
}

function pageHem() {
  if (!EN) return `<div class="note" style="text-align:center;margin-top:20dvh">Laddar…</div>`;
  const s = EN.solar, g = EN.grid, net = g.net_w;
  const alerts = (EN.alerts || []).map((a) => CL()
    ? `<section class="card" style="border:1.5px solid ${a.level === "info" ? "#38bdf8" : "#ef4444"}"><b>${a.level === "info" ? "ℹ️" : "⚠️"} <span>${esc(a.device)}</span>: <span>${esc(a.title)}</span></b><div style="margin-top:4px">${esc(a.text)}</div><div class="note">${esc(a.hint)}</div></section>`
    : `<section class="card"><b><span class="alertdot ${a.level === "info" ? "info" : ""}"></span><span>${esc(a.device)}</span>: <span>${esc(a.title)}</span></b><div style="margin-top:4px">${esc(a.text)}</div><div class="note">${esc(a.hint)}</div></section>`).join("");
  // Planklockan/Skyline ligger bara under Plan (Emil 2026-11-08: framsidan visar vad som händer just nu)
  return `<div class="page">${alerts}${flowCard()}${planNow()}${quickGrid(s, g, net, !!(FL && FL.ok))}${carsRow()}${ljusRow()}</div>`;
}
async function spaBathSheet() {                           // badtider (smartbox/spa_bath.py) - samma som webben
  if (!H || !H.spa || !H.spa.bath_windows) { try { H = await api("home"); } catch (e) { toast(e.message); return; } }
  const ws = ((H && H.spa && H.spa.bath_windows) || []).map((w) => ({ ...w }));
  const days = ["Mån", "Tis", "Ons", "Tor", "Fre", "Lör", "Sön"];
  const inp = 'style="font-size:16px;padding:4px 6px;border-radius:10px;border:1px solid var(--line);background:var(--card);color:var(--txt);width:7.4em;min-width:0"';
  sheet(`<h3>Badtider</h3><div class="note">När brukar ni bada? Utanför badtiderna får badet svalna till eco-golvet och värms upp i tid före nästa badtid, på de billigaste timmarna. Inga badtider = badet hålls varmt som idag.</div>
    ${ws.map((w, i) => `<div class="setrow"><label style="display:flex;gap:8px;align-items:center;min-width:4.5em"><input type="checkbox" class="bon" data-i="${i}"${w.on ? " checked" : ""}>${days[i]}</label>
      <span style="display:flex;gap:6px;align-items:center"><input type="time" class="bfrom" data-i="${i}" value="${w.from}" ${inp}>–<input type="time" class="bto" data-i="${i}" value="${w.to}" ${inp}></span></div>`).join("")}
    <button class="big" id="bathsave">Spara</button><button class="mini" data-x="no">Avbryt</button>`);
  $("#bathsave").onclick = async () => {
    const q = (c, i) => document.querySelector(`#sheet .${c}[data-i="${i}"]`);
    const windows = ws.map((_, i) => ({ on: q("bon", i).checked, from: q("bfrom", i).value, to: q("bto", i).value }));
    try { const r = await api("spa_bath", { windows }); closeSheet(); toast(r.msg); H = await api("home"); render(); } catch (er) { toast(er.message); }
  };
  const no = document.querySelector('#sheet [data-x="no"]'); if (no) no.onclick = () => closeSheet();
}
function solarSheet() {                                    // exportgränsen (förut på Energi-sidan) – nu ett blad från Hem
  const s = EN.solar, lim = s.limit_pct, limTxt = lim == null ? "offline" : lim >= 99.5 ? "ingen begränsning" : `${Math.round(lim)} %`;
  sheet(`<h3>Solceller – exportbegränsning</h3><div style="display:flex;justify-content:space-between;align-items:baseline"><div style="font-size:1.4rem;font-weight:700">${limTxt}</div><span class="chip ${s.ai_limit ? "warn" : "ok"}">${s.ai_limit ? "AI begränsar nu" : "Auto"}</span></div>
    <div class="note">${s.ai_limit ? "Spotpriset är under gränsen, så AI:n begränsar exporten själv." : "AI:n begränsar exporten själv när spotpriset går under gränsen nedan. Knapparna är bara för manuell överstyrning."}</div>
    <div class="seg">${[100, 75, 50, 25, 0].map((p) => `<button data-a="energy" data-k="limit" data-v="${p}" class="${lim != null && Math.round(lim) === p ? "on" : ""}" ${s.ai_limit || lim == null ? "disabled" : ""}>${p} %</button>`).join("")}</div>
    <div class="setrow" style="border:0"><span class="note">Begränsa export när spotpriset är under</span><div class="step"><button data-a="energy" data-k="floor" data-v="${(s.export_price_floor - 0.05).toFixed(2)}">−</button><span>${f1(s.export_price_floor, 2)}</span><button data-a="energy" data-k="floor" data-v="${(s.export_price_floor + 0.05).toFixed(2)}">+</button></div></div>
    <div class="note">${esc(s.status || "")} · prognos ${s.forecast_w != null ? f1(s.forecast_w / 1000) : "–"} kW · elbilar på solel ${EN.solar_ev_kwh != null ? f1(EN.solar_ev_kwh, 0) : "–"} kWh</div>
    <button class="mini" data-a="closesheet">Stäng</button>`);
}
function insightsSheet() {
  sheet(`<h3>Just nu</h3><div class="insl">${(EN.insights || []).map((x) => `<div class="insr"><span>${x.i}</span><span>${esc(x.t)}</span></div>`).join("") || '<div class="note">Inget särskilt just nu.</div>'}</div>
    <div class="note">Sparat idag ${f1(EN.saving_today, 1)} ${moneyUnit()} · förbrukat ${EN.today_kwh != null ? f1(EN.today_kwh, 0) : "–"} kWh</div>
    <div class="crow"><button class="mini" data-a="report">Veckorapport</button><button class="mini" data-a="aidecisions">Alla AI-beslut</button><button class="mini" data-a="closesheet">Stäng</button></div>`);
}
// ---- Plan ------------------------------------------------------------------------------------------------------------------------
let planView = LS.get("ew_plan_view", "plan");
function planList() {
  if (!PL) return `<div class="note" style="text-align:center">Laddar…</div>`;
  const items = PL.items || [];
  const sd = PL.solar_days, f = (v) => v >= 10 ? v.toFixed(0) : v.toFixed(1).replace(".", ",");
  const sun = sd && sd.today_kwh != null ? `<div class="note">☀️ Sol idag ${f(sd.today_kwh)} kWh${sd.today_left_kwh != null ? ` (${f(sd.today_left_kwh)} kvar)` : ""}${sd.tomorrow_kwh != null ? ` · imorgon ${f(sd.tomorrow_kwh)} kWh` : ""}</div>` : "";
  const clock = window.EWPlanView && PC && PC.slots && PC.slots.length ? `<section class="card pccard"><div id="pcslot"></div></section>` : "";
  return `${clock}<section class="card planlist"><div class="planhead">${(PL.headline_parts || [PL.headline]).map(part => `<span>${esc(part)}</span>`).join("")}</div>${sun}${items.slice(0, 5).map((i) => `<div class="plrow ${i.active ? "on" : ""}"><div class="plw">${i.active ? '<span class="chip ok">Nu</span> ' : ""}${esc(i.when)}</div><div><b>${esc(i.title)}</b><div class="note">${esc(i.detail)}</div></div></div>`).join("")}${items.length > 5 ? `<button class="link" data-a="planall" style="padding:0;font-size:.82rem;text-align:left">+${items.length - 5} till</button>` : ""}<div class="note plnote">${esc(PL.note)}</div></section>`;
}
function pagePlan() {
  const seg = `<div class="seg"><button data-a="planview" data-v="plan" class="${planView === "plan" ? "on" : ""}">Planen</button><button data-a="planview" data-v="schema" class="${planView === "schema" ? "on" : ""}">Laddschema</button></div>`;
  if (planView === "schema") return `<div class="page">${seg}${SCH ? schemaInner() : `<div class="note" style="text-align:center">Laddar…</div>`}</div>`;
  return `<div class="page">${seg}${planList()}</div>`;
}
// ---- Schema ----------------------------------------------------------------------------------------------------------------------
const DAYS = ["Mån", "Tis", "Ons", "Tor", "Fre", "Lör", "Sön"];
function schemaInner() {
  if (!SCH) return "";
  // Vald bil först, sedan bilens schema (2026-11-08: schemat lästes innan schCar fått sitt värde -> JS-fel första gången)
  const _cs = (S && S.cars) || []; if (!_cs.some((c) => c.key === schCar) && _cs.length) schCar = _cs[0].key;
  const s = SCH[schCar];
  if (!s) return `<div class="note" style="text-align:center">Inget laddschema för den här bilen.</div>`;
  const hx = CLIM && CLIM[schCar];
  const heat = hx && hx.has_climate ? `<section class="card" style="margin-top:12px"><h4>Kupévärme</h4>
    <div class="note">Varje dag, varm till klockan när bilen är hemma eller inkopplad.</div>
    <div class="card srow"><b>På</b><button class="sw ${hx.enabled ? "on" : ""}" data-a="clim" data-f="enabled" aria-label="Kupévärme på/av"></button><button class="tm" data-a="climclock" aria-label="Varm kl"><span>${hx.time}</span></button><div class="step"><button data-a="clim" data-f="t-">−</button><span>${hx.temp}°</span><button data-a="clim" data-f="t+">+</button></div></div></section>` : "";
  return `<div class="seg">${_cs.map((c) => `<button data-a="schcar" data-v="${esc(c.key)}" class="${schCar === c.key ? "on" : ""}">${esc(c.name)}</button>`).join("")}</div>
  <div class="note" style="text-align:center">Klar till vald tid och batterinivå. Av = laddar bara enligt pris/Auto.</div>
  <div class="sched">${DAYS.map((d, i) => { const x = s[i]; return `<div class="card srow"><b>${d}</b><button class="sw ${x.enabled ? "on" : ""}" data-a="sch" data-d="${i}" data-f="enabled" aria-label="${d} på/av"></button><button class="tm" data-a="schclock" data-d="${i}" aria-label="${d} klar kl"><span>${x.time}</span></button><div class="step"><button data-a="sch" data-d="${i}" data-f="soc-">−</button><span>${x.soc}%</span><button data-a="sch" data-d="${i}" data-f="soc+">+</button></div></div>`; }).join("")}</div>${heat}`;
}
// ---- Grafer ----------------------------------------------------------------------------------------------------------------------
const hiddenSer = (key) => String(LS.get("ew_hide_" + key, "")).split(",").filter((x) => x !== "").map(Number);
function chart(title, unit, series, labels, colors, names, key) {
  const hid = hiddenSer(key || title), vis = series.map((_, k) => !hid.includes(k));
  const all = series.filter((_, k) => vis[k]).flat().filter((v) => v != null);
  const legend = names ? `<div class="legend">${names.map((nm, k) => `<button class="${vis[k] ? "" : "off"}" data-a="ser" data-v="${key || title}:${k}"><i style="background:${colors[k]}"></i>${nm}</button>`).join("")}</div>` : "";
  if (!all.length) return `<section class="card chart"><div class="ch"><b>${title}</b></div>${legend}<div class="note">${series.some((s) => s.some((v) => v != null)) ? "Alla linjer är dolda – tryck på en förklaring ovan" : "Ingen data"}</div></section>`;
  const mn = Math.min(...all), mx = Math.max(...all), rg = mx - mn || 1, W = 300, Hh = 70, n = labels.length;
  const X = (i) => (n <= 1 ? 0 : (i / (n - 1)) * W), Y = (v) => Hh - 4 - ((v - mn) / rg) * (Hh - 10);
  const paths = series.map((s, k) => { if (!vis[k]) return ""; let d = ""; s.forEach((v, i) => { if (v != null) d += (d ? "L" : "M") + X(i).toFixed(1) + " " + Y(v).toFixed(1); }); return `<path d="${d}" fill="none" stroke="${colors[k]}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke"/>`; }).join("");
  // Skala: tre hjälplinjer med värden (min, mitten, max) så att man ser vad kurvan betyder
  const grid = [0, 0.5, 1].map((q) => { const v = mn + q * rg, y = Y(v); return `<line x1="0" x2="${W}" y1="${y.toFixed(1)}" y2="${y.toFixed(1)}" stroke="currentColor" stroke-opacity=".12" stroke-dasharray="3 4" vector-effect="non-scaling-stroke"/>`; }).join("");
  const ylab = [1, 0.5, 0].map((q) => `<span style="position:absolute;right:2px;top:${(((Hh - 4 - q * (Hh - 10)) / Hh) * 100).toFixed(1)}%;transform:translateY(-50%);font-size:.66rem;opacity:.6">${f1(mn + q * rg, unit === moneyUnit() ? 2 : 1)}</span>`).join("");
  const last = series.map((s, k) => vis[k] ? [...s].reverse().find((v) => v != null) : null);
  return `<section class="card chart"><div class="ch"><b style="color:var(--txt)">${title}</b><span>${last.map((v, k) => v == null ? "" : `<span style="color:${colors[k]}">${f1(v, unit === moneyUnit() ? 2 : 1)}</span>`).filter(Boolean).join(" · ")} ${unit}</span></div>${legend}<div style="position:relative;flex:1;min-height:0"><svg viewBox="0 0 ${W} ${Hh}" preserveAspectRatio="none" style="color:var(--mut);position:absolute;inset:0;width:100%;height:100%">${grid}${paths}</svg>${ylab}</div><div class="ch"><span>${labels[0] ?? ""}:00</span><span>${labels[Math.floor((n - 1) / 2)] ?? ""}:00</span><span>${labels[n - 1] ?? ""}:00</span></div></section>`;
}
// ---- Historik (inspirerat av FTW:s History-vy, egen implementation) ------------------------------------------------------------
let histView = LS.get("ew_hist_view", "energi");
const HC = { grid: "#e11d74", solar: "#d4a72c", battery: "#0e7490", house: "var(--mut)" };
function kwhCell(l, v, c) { return `<div class="kc" style="border-color:${c}"><span>${l}</span><b>${v == null ? "–" : f1(v, v >= 100 ? 0 : 1)}<small> kWh</small></b></div>`; }
function powerSvg(sr) {                                   // nät/sol/hus/batteri runt nollan: uppåt = in i huset, nedåt = ut
  if (!sr || !sr.t.length) return `<div class="note">Ingen data</div>`;
  const ser = [[sr.grid_kw, HC.grid], [sr.solar_kw.map((v) => (v == null ? null : -v)), HC.solar], [sr.house_kw, HC.house]];
  if (sr.battery_kw.some((v) => v != null)) ser.push([sr.battery_kw, HC.battery]);
  const all = ser.flatMap(([s]) => s).filter((v) => v != null), mx = Math.max(0.5, ...all.map(Math.abs)), W = 300, Hh = 100, n = sr.t.length;
  const X = (i) => (n <= 1 ? 0 : (i / (n - 1)) * W), Y = (v) => Hh / 2 - (v / mx) * (Hh / 2 - 4);
  const paths = ser.map(([s, c]) => { let d = ""; s.forEach((v, i) => { if (v != null) d += (d ? "L" : "M") + X(i).toFixed(1) + " " + Y(v).toFixed(1); }); return `<path d="${d}" fill="none" stroke="${c}" stroke-width="1.8" stroke-linejoin="round" vector-effect="non-scaling-stroke"/>`; }).join("");
  const lbl = (x) => sr.range === "24h" ? x.slice(11, 16) : `${x.slice(8, 10)}/${x.slice(5, 7)}`;
  // #371: tryck på grafen -> stor, lättläst version (bigChartSheet)
  return `<div data-a="bigchart" style="cursor:zoom-in"><div class="ch"><span>${f1(mx, 0)} kW in</span><span class="note" style="margin:0">Tryck för större</span></div><svg viewBox="0 0 ${W} ${Hh}" preserveAspectRatio="none"><line x1="0" x2="${W}" y1="${Hh / 2}" y2="${Hh / 2}" stroke="var(--line)" vector-effect="non-scaling-stroke"/>${paths}</svg><div class="ch"><span>${lbl(sr.t[0])}</span><span>${f1(mx, 0)} kW ut</span><span>nu</span></div></div>`;
}
// #371 (Emil 2026-11-13): grafen var svår att läsa. Stor vy med axlar, tider, teckenförklaring, periodval och
// värden där man trycker eller drar med fingret.
function bigPowerSvg(sr) {
  if (!sr || !sr.t.length) return `<div class="note">Ingen data</div>`;
  const ser = [["Nät", sr.grid_kw, HC.grid], ["Sol", sr.solar_kw.map((v) => (v == null ? null : -v)), HC.solar], ["Hus", sr.house_kw, HC.house]];
  if (sr.battery_kw.some((v) => v != null)) ser.push(["Batteri", sr.battery_kw, HC.battery]);
  const all = ser.flatMap(([, s]) => s).filter((v) => v != null), mx = Math.max(0.5, ...all.map(Math.abs));
  const W = 1000, H = 460, L = 54, R = 12, T = 14, B = 34, pw = W - L - R, ph = H - T - B, n = sr.t.length;
  const X = (i) => L + (n <= 1 ? 0 : (i / (n - 1)) * pw), Y = (v) => T + ph / 2 - (v / mx) * (ph / 2);
  const grid = [mx, mx / 2, 0, -mx / 2, -mx].map((v) => `<line x1="${L}" x2="${W - R}" y1="${Y(v).toFixed(1)}" y2="${Y(v).toFixed(1)}" stroke="var(--line)" stroke-width="${v === 0 ? 1.6 : 0.8}" ${v === 0 ? "" : 'stroke-dasharray="4 6"'}/><text x="${L - 6}" y="${(Y(v) + 4).toFixed(1)}" font-size="15" fill="var(--mut)" text-anchor="end">${v > 0 ? "+" : ""}${f1(v, mx >= 5 ? 0 : 1)}</text>`).join("");
  const lbl = (x) => sr.range === "24h" ? x.slice(11, 16) : sr.range === "1y" ? `${x.slice(5, 7)}/${x.slice(2, 4)}` : `${x.slice(8, 10)}/${x.slice(5, 7)}`;
  const ticks = [0, 0.2, 0.4, 0.6, 0.8, 1].map((f) => Math.round(f * (n - 1))).map((i) => `<text x="${X(i).toFixed(1)}" y="${H - 10}" font-size="15" fill="var(--mut)" text-anchor="${i === 0 ? "start" : i === n - 1 ? "end" : "middle"}">${esc(lbl(sr.t[i]))}</text>`).join("");
  const paths = ser.map(([, s, c]) => { let d = ""; s.forEach((v, i) => { if (v != null) d += (d ? "L" : "M") + X(i).toFixed(1) + " " + Y(v).toFixed(1); }); return `<path d="${d}" fill="none" stroke="${c}" stroke-width="2.2" stroke-linejoin="round"/>`; }).join("");
  const legend = ser.map(([nm, , c]) => `<span style="display:inline-flex;align-items:center;gap:6px;margin-right:14px"><span style="width:14px;height:4px;border-radius:2px;background:${c}"></span>${nm}</span>`).join("");
  return `<div class="note" style="margin:0 0 6px">${legend}</div>
    <div class="note" style="margin:0 0 4px">kW · uppåt = in i huset (köpt), nedåt = ut (sålt, solproduktion)</div>
    <div id="bigwrap" style="position:relative;touch-action:none">
      <svg id="bigsvg" viewBox="0 0 ${W} ${H}" style="width:100%;height:auto;display:block">${grid}${ticks}${paths}<line id="bigcur" x1="0" x2="0" y1="${T}" y2="${T + ph}" stroke="var(--txt)" stroke-width="1.2" opacity="0"/></svg>
      <div id="bigtip" class="card" style="position:absolute;top:6px;left:60px;padding:8px 10px;font-size:.85rem;pointer-events:none;display:none;min-width:150px"></div>
    </div>
    <div class="note" style="margin-top:6px">Tryck eller dra över grafen för att se värdena.</div>`;
}
function bigChartSheet() {
  const draw = () => {
    sheet(`<div style="display:flex;justify-content:space-between;align-items:center;gap:8px"><h3 style="margin:0">Effekt</h3><button class="mini" data-a="closesheet">Stäng</button></div>
      <div class="seg" style="margin:8px 0">${[["24h", "24 h"], ["7d", "7 d"], ["30d", "30 d"], ["1y", "1 år"]].map(([k, l]) => `<button data-a="bigrange" data-v="${k}" class="${hxRange === k ? "on" : ""}">${l}</button>`).join("")}</div>
      ${bigPowerSvg(HX && HX.series)}`);
    const p = $("#sheet .panel"); if (p) { p.style.maxWidth = "1100px"; p.style.width = "100%"; p.style.maxHeight = "94dvh"; }
    const sr = HX && HX.series, svg = $("#bigsvg"), tip = $("#bigtip"), cur = $("#bigcur");
    if (!sr || !svg) return;
    const n = sr.t.length, L = 54, pw = 1000 - 54 - 12;
    const kw = (v) => v == null ? "–" : `${f1(Math.abs(v), Math.abs(v) >= 10 ? 0 : 1)} kW`;
    const show = (ev) => {
      const r = svg.getBoundingClientRect(), x = ((ev.clientX - r.left) / r.width) * 1000;
      const i = Math.max(0, Math.min(n - 1, Math.round(((x - L) / pw) * (n - 1))));
      const cx = L + (n <= 1 ? 0 : (i / (n - 1)) * pw);
      cur.setAttribute("x1", cx); cur.setAttribute("x2", cx); cur.setAttribute("opacity", ".6");
      const g = sr.grid_kw[i], when = sr.t[i].slice(0, 16).replace("T", " ");
      tip.innerHTML = `<b>${esc(when)}</b><br>Nät: ${kw(g)} ${g != null ? (g < 0 ? "säljer" : "köper") : ""}<br>Sol: ${kw(sr.solar_kw[i])}<br>Hus: ${kw(sr.house_kw[i])}${sr.battery_kw.some((v) => v != null) ? `<br>Batteri: ${kw(sr.battery_kw[i])} ${sr.battery_kw[i] != null ? (sr.battery_kw[i] < 0 ? "laddar ur" : "laddar") : ""}` : ""}`;
      tip.style.display = "block";
      const left = (cx / 1000) * r.width; tip.style.left = (left > r.width / 2 ? Math.max(0, left - 170) : left + 12) + "px";
    };
    svg.addEventListener("pointerdown", (e) => { svg.setPointerCapture(e.pointerId); show(e); });
    svg.addEventListener("pointermove", (e) => { if (e.buttons || e.pointerType === "mouse") show(e); });
  };
  draw();
  bigChartSheet.redraw = draw;
}
function dayWhen(iso) {
  if (!iso) return "";
  return `${iso.slice(8, 10)}/${iso.slice(5, 7)} ${iso.slice(11, 16)}`;
}
function dayChart(d) {
  if (!d || !d.ok || !(d.hours || []).length) return `<section class="card dayc"><div class="note" style="text-align:center">${d ? "Ingen data" : "Laddar…"}</div></section>`;
  const hours = d.hours, n = hours.length, price = d.price || [], solar = d.solar_kw || [], fut = d.future || [], lanes = d.lanes || [];
  const firstFut = fut.findIndex(Boolean);
  const nowIdx = firstFut < 0 ? n - 1 : Math.max(0, firstFut - 1);
  const ps = price.filter((v) => v != null);
  const pMax = Math.max(0.5, ...ps, 0), pMin = Math.min(0, ...ps);
  const sMax = Math.max(0.5, ...solar.filter((v) => v != null));
  const slot = 18, top = 16, pH = 112, laneH = 26, bot = 22;
  const plotW = n * slot, H = top + pH + 8 + lanes.length * laneH + bot;
  const Yp = (v) => top + 4 + (pH - 12) * (1 - (v - pMin) / (pMax - pMin || 1));
  const y0 = Yp(0);
  let bars = "", path = "", pen = false;
  solar.forEach((v, i) => {
    if (v == null || v <= 0) return;
    const h = (v / sMax) * (pH - 18), x = i * slot + 3;
    bars += `<rect x="${x.toFixed(1)}" y="${(y0 - h).toFixed(1)}" width="${slot - 6}" height="${h.toFixed(1)}" fill="#fbbf24" opacity="${fut[i] ? ".35" : ".78"}"/>`;
  });
  price.forEach((v, i) => {
    if (v == null) { pen = false; return; }
    const y = Yp(v).toFixed(1), x0 = (i * slot).toFixed(1), x1 = ((i + 1) * slot).toFixed(1);
    path += pen ? `V${y}H${x1}` : `M${x0} ${y}H${x1}`;
    pen = true;
  });
  const nx = (firstFut < 0 ? n : firstFut) * slot;
  const scale = [pMax, (pMax + pMin) / 2, pMin].map((v) => `<span class="ps" style="top:${Yp(v).toFixed(1)}px">${f1(v, 1)}</span>`).join("");
  let laneSvg = "", laneLabs = "";
  lanes.forEach((ln, li) => {
    const y = top + pH + 10 + li * laneH;
    laneLabs += `<span class="ln" style="top:${y + 3}px">${esc(ln.label)}</span>`;
    (ln.values || []).forEach((v, i) => {
      if (v == null || v <= 0.02) return;
      const op = ((fut[i] ? 0.12 : 0.2) + v * (fut[i] ? 0.45 : 0.8)).toFixed(2);
      laneSvg += `<rect x="${i * slot + 2}" y="${y + 4}" width="${slot - 4}" height="14" rx="3" fill="${ln.color}" opacity="${op}"${fut[i] ? ` stroke="${ln.color}" stroke-dasharray="2 2" stroke-width="1"` : ""}/>`;
    });
  });
  let labels = "";
  hours.forEach((h, i) => {
    const hr = +h.slice(11, 13);
    if (hr % 6 !== 0 && i !== n - 1) return;
    labels += `<text data-h="${esc(h)}" x="${i * slot + slot / 2}" y="${H - 6}" text-anchor="middle" fill="currentColor" opacity=".6" font-size="10">${String(hr).padStart(2, "0")}</text>`;
  });
  const lastI = price.reduce((a, v, i) => (v != null ? i : a), nowIdx);
  const until = dayWhen(hours[lastI]);
  const nowPrice = price[nowIdx];
  return `<section class="card dayc" data-until="${esc(hours[lastI])}" data-lastprice="${price[lastI] == null ? "" : price[lastI]}"><div class="chead"><div><b>Dygnet</b><div class="note">Vänster om strecket är uppmätt. Höger är planerat, till sista priset från leverantören${until ? ` · ${until}` : ""}.</div></div><div class="nowp">${f1(nowPrice, 2)} <small>${moneyUnit()}</small><div class="note">nu</div></div></div><div class="dayleg"><span><i style="background:#38bdf8"></i>Elpris</span><span><i style="background:#fbbf24"></i>Sol</span><span>Starkare färg = mer</span></div><div class="dayframe"><div class="daylabs" style="height:${H}px">${scale}${laneLabs}</div><div class="dayscroll" data-nowx="${nx}"><svg viewBox="0 0 ${plotW} ${H}" width="${plotW}" height="${H}" role="img" aria-label="Elpris dygnet"><line x1="0" x2="${plotW}" y1="${y0.toFixed(1)}" y2="${y0.toFixed(1)}" stroke="currentColor" stroke-opacity=".15"/>${bars}<path d="${path}" fill="none" stroke="#38bdf8" stroke-width="2"/>${laneSvg}<line data-now x1="${nx}" x2="${nx}" y1="${top}" y2="${H - bot}" stroke="currentColor" stroke-opacity=".7" stroke-dasharray="3 3"/>${labels}</svg></div></div></section>`;
}
function pageHistorik() {
  const seg = `<div class="seg">${[["energi", "Energi"], ["temp", "Temperatur"], ["pris", "Elpris"]].map(([k, l]) => `<button data-a="histview" data-v="${k}" class="${histView === k ? "on" : ""}">${l}</button>`).join("")}</div>`;
  if (histView === "pris") return `<div class="page">${seg}${dayChart(TL)}</div>`;
  if (histView !== "energi") {
    if (!HIST) return `<div class="page">${seg}<div class="note" style="text-align:center">Laddar…</div></div>`;
    const h = HIST, c = chart("Temperatur inne / ute", "°C", [h.indoor, h.outdoor], h.t, ["var(--warn)", "var(--mut)"], ["Inne", "Ute"], "temp");
    return `<div class="page">${seg}<div class="charts one">${c}</div></div>`;
  }
  if (!HX) return `<div class="page">${seg}<div class="note" style="text-align:center">Laddar…</div></div>`;
  const t = HX.totals[hxPeriod], L = HX.latest || {};
  const w = (x) => (x == null ? "–" : Math.abs(x) >= 1000 ? `${f1(x / 1000)} kW` : `${Math.round(x)} W`);
  const cells = t ? [kwhCell("Förbrukat", t.used_kwh, HC.house), t.solar_kwh != null ? kwhCell("Solel", t.solar_kwh, HC.solar) : "", kwhCell("Köpt", t.bought_kwh, HC.grid), kwhCell("Sålt", t.sold_kwh, HC.grid)].join("") : `<div class="note">Ingen mätdata</div>`;
  return `<div class="page">${seg}
  <section class="card hxtot"><div class="seg">${[["today", "Idag"], ["7d", "7 dagar"], ["30d", "30 dagar"]].map(([k, l]) => `<button data-a="hp" data-v="${k}" class="${hxPeriod === k ? "on" : ""}">${l}</button>`).join("")}</div><div class="kgrid">${cells}</div>${t && t.summary ? `<div class="note hxsum">${esc(t.summary)}</div>` : ""}</section>
  <section class="card chart hxchart"><div class="seg">${[["24h", "24 h"], ["7d", "7 d"], ["30d", "30 d"], ["1y", "1 år"]].map(([k, l]) => `<button data-a="hr" data-v="${k}" class="${hxRange === k ? "on" : ""}">${l}</button>`).join("")}</div>${powerSvg(HX.series)}
    <div class="latest"><span style="border-color:${HC.grid}">Nät <b>${L.grid_w == null ? "–" : w(Math.abs(L.grid_w))}</b> ${L.grid_w != null && L.grid_w < -50 ? "säljer" : "köper"}</span><span style="border-color:${HC.solar}">Sol <b>${w(L.solar_w)}</b></span>${L.battery_w != null ? `<span style="border-color:${HC.battery}">Batteri <b>${w(Math.abs(L.battery_w))}</b></span>` : ""}<span style="border-color:${HC.house}">Hus <b>${w(L.house_w)}</b></span></div>
    <button class="link" data-a="peaks" style="padding:0;font-size:.8rem;text-align:left">Effekttoppar denna månad</button></section>
  ${window.EWJournal && JR && JR.ok ? `<section class="card" id="journalcard">${EWJournal.html(JR, { compact: true, back: jBack })}</section>` : ""}</div>`;
}
// ---- ram, render, laddning ----------------------------------------------------------------------------------------------------------
// Version i sidhuvudet: "✓ senaste" bara när det är bekräftat, annars en knapp om en nyare finns (update_check.py)
let UPD = null, updAt = 0;
function verBadge() {
  const u = UPD && UPD.status, v = (u && u.running) || (S && S.version);
  if (u && u.outdated && u.latest) return `<button class="ver" data-a="update" style="color:var(--warn);background:none;border:0;padding:0;font:inherit;cursor:pointer">⬆️ Ny version ${esc(u.latest)} · tryck här</button>`;
  if (!v || v === "dev" || v === "local") return "";
  return `<span class="ver">v${esc(v)}${u && u.latest && !u.outdated ? " ✓ senaste" : ""}</span>`;
}
function updateSheet() {
  const u = (UPD && UPD.status) || {};
  const how = u.kind === "addon" ? "Öppna Home Assistant → <b>Inställningar → Tillägg → EnergyWizard</b> och tryck <b>Uppdatera</b>." : "Hämta den nya bilden (<code>docker compose pull</code> och starta om) eller låt Watchtower göra det.";
  sheet(`<h3>Ny version: ${esc(u.latest || "")}</h3><div class="note" style="margin-bottom:8px">Du kör ${esc(u.running || "en äldre version")}. Nya versioner har rättningar och förbättringar, och fel som redan är rättade försvinner först när du uppdaterat.</div><p>${how}</p><a class="mini" href="${esc(u.changelog || "")}" target="_blank" rel="noopener">Vad är nytt</a>`);
}
// unslop 2026-11: överst priset just nu och hur det ligger (i stället för en slumpad rad)
function priceLine() {
  const g = EN && EN.grid; if (!g || g.price == null) return "";
  const lv = g.level || "", col = lv === "billigt" ? "var(--acc)" : lv === "dyrt" ? "var(--warn)" : "var(--txt)";
  return `<span class="gl gprice"><strong style="color:${col};font-weight:500">${esc(lv ? lv[0].toUpperCase() + lv.slice(1) : "Elpris")} just nu</strong> · ${f1(g.price, 2)} kr/kWh</span>`;
}
const CL = () => LS.get("ew_style", "new") === "classic";   // Inställningar → Appen → Stil: Ny (standard) eller Klassisk (före unslop)
function render() {
  if (page === "bil" && !primary() && S && S.cars.length) return chooseCar();
  const warn = S && S.health && S.health.length;
  if (!TABS[ER()].includes(page)) page = "bil";
  const body = { hem: pageHem, bil: pageBil, hus: pageHus, plan: pagePlan, historik: pageHistorik }[page]();
  const ok = S ? S.ok : true;
  const tabs = TABS[ER()].map((k) => [k, TABNAME[k]]);
  // Scrollar sidan (stor text, tscroll) ska omritningen var 5:e sekund inte kasta en tillbaka till toppen
  const _oldPg = document.querySelector(".page"), _keepScroll = _oldPg && _oldPg.dataset.p === page ? _oldPg.scrollTop : 0;
  const _oldDay = document.querySelector(".dayscroll"), _keepDay = _oldDay ? _oldDay.scrollLeft : null;
  app.innerHTML = `<div class="top"><div class="greet" data-a="greet"><b><span class="dot ${ok ? "" : "off"}"></span>${esc(GR ? (CL() ? GR.hello : GR.hello.replace(/!+$/, "")) : "EnergyWizard")}</b>${CL() ? (GR ? `<span class="gl">${esc([GR.weather, GR.line].filter(Boolean).join(" · "))}</span>` : "") : `${priceLine()}${GR ? `<span class="gl">${esc(GR.weather || "")}</span>` : ""}`}${verBadge()}</div><div class="tools"><button class="icobtn" data-a="theme" aria-label="Byt tema">${themeIcon()}</button>${warn ? `<button class="icobtn warn" data-a="health">⚠ ${S.health.length}</button>` : ""}<button class="icobtn" data-a="settings" aria-label="Inställningar">${ICON.gear}</button></div></div>${ROLE === "owner" && VIEWAS ? `<button class="vastrip" data-a="viewas" data-v="">Visar som ${VIEWAS === "family" ? "familj" : "gäst"} · tryck för att avsluta</button>` : ER() === "guest" ? `<div class="vastrip">Gästläge · bara titta</div>` : ""}${needInstall() && page === "bil" ? `<button class="installbar" data-a="installapp"><b>Installera som app</b><span>${installEvt ? "Ett tryck" : "Så gör du"}</span></button>` : ""}${body}`;
  let tb = $("#tabs"); if (!tb) { tb = document.createElement("nav"); tb.id = "tabs"; tb.className = "tabs"; document.body.insertBefore(tb, $("#toast")); }
  tb.style.setProperty("--ntabs", tabs.length);
  tb.innerHTML = tabs.map(([k, l]) => `<button class="tab ${page === k ? "on" : ""}" data-a="tab" data-v="${k}">${ICON[k]}<span>${l}</span></button>`).join("");
  const pcs = $("#pcslot");
  if (pcs && PC && window.EWPlanView) {
    if (!PCEL) PCEL = document.createElement("div");
    if (PCNEW && (!PCH || PCH.index === 0)) { PCH = EWPlanView.mount(PCEL, PC, { lang: I18N.lang, unit: moneyUnit() }); PCNEW = false; }
    pcs.replaceWith(PCEL);
  }
  const _pg = document.querySelector(".page");
  if (_pg) _pg.dataset.p = page;
  fit();
  if (_pg && _keepScroll) _pg.scrollTop = _keepScroll;
  const _day = document.querySelector(".dayscroll");
  if (_day) _day.scrollLeft = _keepDay == null ? Math.max(0, (+_day.dataset.nowx || 0) - 28) : _keepDay;
}
function overflows(pg) {
  const r = pg.getBoundingClientRect(); if (pg.scrollHeight > pg.clientHeight + 1) return true;
  return [...pg.children].some((k) => k.getBoundingClientRect().bottom > r.bottom + 1 || k.scrollHeight > k.clientHeight + 1) || [...pg.querySelectorAll(".card")].some((k) => k.scrollHeight > k.clientHeight + 1);
}
function fit() {                                           // krymper innehållet steg för steg tills inget sticker ut eller överlappar (stora typsnitt, små skärmar)
  const pg = document.querySelector(".page"); if (!pg) return;
  const st = pg.scrollTop;                                 // omräkningen får inte nollställa scrollen
  pg.classList.remove("t1", "t2", "t3", "t4", "t5", "tscroll");   // t5 också: annars satt den kvar och dolde "Just nu"-raderna
  for (let l = 1; l <= 5 && overflows(pg); l++) pg.classList.add("t" + l);     // t5: hemskärmens extra steg för stor text
  if (overflows(pg)) pg.classList.add("tscroll");          // sista utvägen: scrolla hellre än att kort överlappar eller göms
  if (st) pg.scrollTop = st;
}
window.addEventListener("resize", () => fit());
let APPV = null;
async function checkVersion() {                           // ny version på servern -> ladda om sidan automatiskt (sparar användaren från att hänga kvar på gammal kod)
  try { const r = await fetch("api/version", { cache: "no-store" }); if (!r.ok) return; const v = (await r.json()).v; if (APPV && v !== APPV) { toast("Ny version – laddar om…"); setTimeout(hardReload, 900); } APPV = v; } catch {}
}
async function hardReload() {
  try { if ("serviceWorker" in navigator) { (await navigator.serviceWorker.getRegistrations()).forEach((r) => r.unregister()); } if (window.caches) { (await caches.keys()).forEach((k) => caches.delete(k)); } } catch {}
  location.reload();
}
let doneShortcut = false, grAt = 0;
// #394: "Ladda nu" frågar efter mål - laddningen avslutas av sig själv vid målet, urdragen kabel eller efter 24 h
// #397: varmvatten "Till" med tid - går tillbaka till Auto av sig själv
function hwLeft(until) { const m = Math.max(0, Math.round((until * 1000 - Date.now()) / 60000)); return m >= 60 ? `${Math.floor(m / 60)} h ${m % 60} min` : `${m} min`; }
function hotwaterSheet() {
  const opts = [[30, "30 min"], [60, "1 h"], [120, "2 h"], [240, "4 h"], [360, "6 h"]];
  sheet(`<h3>Varmvatten till</h3><div class="note">Hur länge? Sedan går varmvattnet tillbaka till Auto.</div>
    <div class="cn-tg">${opts.map(([m, l]) => `<button class="mini" data-x="${m}">${l}</button>`).join("")}</div>
    <button class="mini" data-x="0" style="width:100%;margin-top:8px">Tills jag ändrar</button><button class="mini" data-x="no" style="width:100%;margin-top:8px">Avbryt</button>`);
  $("#sheet").onclick = async (e) => { const b = e.target.closest("[data-x]"); if (!b) { if (e.target.id === "sheet") closeSheet(); return; } closeSheet(); if (b.dataset.x === "no") return;
    buzz(); try { const r = await api("home/hotwater", { value: "on", minutes: +b.dataset.x || null }); toast(r.msg); H = await api("home"); render(); } catch (er) { toast(er.message); } };
}
function chargeNowSheet(key) {
  const c = S.cars.find((x) => x.key === key); if (!c) return;
  const soc = c.soc, tg = [40, 60, 80, 100].filter((t) => soc == null || t > soc);
  sheet(`<h3>Ladda ${esc(c.name)} nu?</h3><div class="note">${soc == null ? "Laddnivån är okänd just nu." : `Bilen har ${soc} %.`} Laddar direkt, oavsett schema. Med ett mål slutar laddningen av sig själv och planen tar över.</div>
    ${soc == null ? "" : `<div class="cn-tg">${tg.map((t) => `<button class="mini" data-x="t${t}">Till ${t} %</button>`).join("")}</div>`}
    <button class="${soc == null ? "big" : "mini"}" data-x="ok" style="width:100%;margin-top:8px">Tills jag stoppar</button><button class="mini" data-x="no" style="width:100%;margin-top:8px">Avbryt</button>`);
  $("#sheet").onclick = (e) => { const b = e.target.closest("[data-x]"); if (!b) { if (e.target.id === "sheet") closeSheet(); return; } closeSheet();
    if (b.dataset.x === "ok") act(key, "start"); else if (b.dataset.x[0] === "t") act(key, "start", { target_soc: +b.dataset.x.slice(1) }); };
}

function runShortcut() {                              // genvägar från ikonens långtryck: ./?do=goodnight, windows_on, windows_off, <bil>_start
  const q = new URLSearchParams(location.search).get("do"); if (!q) return; history.replaceState(null, "", location.pathname);
  if (["windows_on", "windows_off", "goodnight"].includes(q) && can("lights")) { api("lights", { action: q }).then((r) => toast(r.msg)).catch((e) => toast(e.message)); return; }
  const m = /^(.+)_start$/.exec(q); if (m && S && S.cars.some((c) => c.key === m[1]) && can("start")) chargeNowSheet(m[1]);
}
async function loadGreeting() { if (Date.now() - grAt < 120000) return; grAt = Date.now(); try { GR = await api("greeting?lang=" + I18N.lang + (ROLE === "owner" && VIEWAS ? "&as=" + VIEWAS : "")); render(); } catch {} }
async function loadClock() {           // planklockan på Hem och Plan - högst en gång i minuten
  if (Date.now() - PCAt < 60000) return;
  const pc = await api("planclock").catch(() => null);
  if (pc) { PC = pc; PCAt = Date.now(); PCNEW = true; }
}
async function load() {
  try {
    if (page === "bil") S = await api("state"); else if (!S) S = await api("state");
    ROLE = (S && S.role) || ROLE; ME = (S && S.user) || ME; document.body.classList.toggle("guest", ROLE === "guest");
    if (page === "hus") H = await api("home");
    if (page === "hem") { if (!S || Date.now() - (S._t || 0) > 30000) { S = await api("state").catch(() => S); if (S) S._t = Date.now(); }
      [EN, PL, SV, FL] = await Promise.all([api("energy"), api("plan").catch(() => PL), ER() === "owner" ? api("savings").catch(() => null) : null, api("flow").catch(() => FL)]); if (!LJ && can("lights")) LJ = await api("lights").catch(() => null); await loadClock(); }
    if (Date.now() - updAt > 3600000) { updAt = Date.now(); api("update-status").then((d) => { UPD = d; render(); }).catch(() => {}); }
    if (page === "bil" && Date.now() - ecAt > 300000) { ecAt = Date.now(); api("ev-cost").then((d) => { EC = d; if (page === "bil") render(); }).catch(() => {}); }
    if (page === "plan") { PL = await api("plan").catch(() => PL); if (!SCH) SCH = await api("schedule"); if (!CLIM) CLIM = await api("schedule/climate").catch(() => CLIM); await loadClock(); }
    if (page === "historik") {
      if (histView === "energi") { HX = await api("energyhistory?range=" + hxRange); JR = await api("control-journal?back=" + jBack).catch(() => JR); }
      else if (histView === "pris") { if (!TL || Date.now() - TLAt > 60000) { TL = await api("timeline").catch(() => TL); if (TL) TLAt = Date.now(); } }
      else if (!HIST) HIST = await api("history?hours=24");
      if (!EN) EN = await api("energy").catch(() => null);
    }
    if (!(sheetOpen())) render();
    checkVersion(); loadGreeting(); openStream();
    if (!doneShortcut) { doneShortcut = true; runShortcut(); }
  } catch (e) { if (!S && !H) showLogin(); }
}
const sheetOpen = () => !$("#sheet").hidden;
function sheet(html) { const s = $("#sheet"); const wasOpen = !s.hidden; s.innerHTML = `<div class="panel">${html}</div>`; s.hidden = false; if (wasOpen) return; try { history.pushState({ s: 1, page }, ""); } catch (e) {} /* omritning av ett öppet blad behåller dess klickhanterare (annars dör knapparna efter första trycket) */ s.onclick = (e) => { if (e.target === s) closeSheet(); }; }
function hideSheet() { $("#sheet").hidden = true; render(); }
function closeSheet() { if (history.state && history.state.s) history.back(); else hideSheet(); }           // bakåtknappen stänger bladet; stängknappen gör samma sak (ingen kvarglömd historikpost)
window.addEventListener("popstate", (e) => {                                                                // bakåt på telefonen: stäng blad eller gå till förra fliken, lämna inte appen
  if (!$("#sheet").hidden) { hideSheet(); return; }
  const st = e.state; if (st && st.page && st.page !== page && !st.s) { page = st.page; LS.set("ew_page", page); render(); load(); }
});
function powerSheet(key) {
  const c = S.cars.find((x) => x.key === key); let amps = c.amps || 16, ph = c.phases || c.default_phases;
  const draw = () => sheet(`<h3>Välj laddeffekt – ${esc(c.name)}</h3><div class="seg">${[6, 10, 16].map((a) => `<button data-v="a${a}" class="${amps === a ? "on" : ""}">${a} A</button>`).join("")}</div>${c.default_phases === 3 ? `<div class="seg">${[1, 3].map((f) => `<button data-v="p${f}" class="${ph === f ? "on" : ""}">${f}-fas</button>`).join("")}</div>` : `<div class="note">${esc(c.name)} laddar på 1-fas.</div>`}<div class="note">≈ ${f1((amps * 230 * (c.default_phases === 3 ? ph : 1)) / 1000)} kW</div><button class="big" data-v="go">Starta laddning</button>`);
  draw();
  $("#sheet").onclick = async (e) => { const b = e.target.closest("[data-v]"); if (!b) { if (e.target.id === "sheet") closeSheet(); return; } const v = b.dataset.v; if (v[0] === "a") { amps = +v.slice(1); draw(); } else if (v[0] === "p") { ph = +v.slice(1); draw(); } else if (v === "go") { closeSheet(); await act(key, "set", { amps, phases: c.default_phases === 3 ? ph : 1 }); } };
}
async function act(car, kind, extra) {
  if (busy) { toast("Vänta, förra kommandot skickas…"); return; } busy = true; buzz();
  toast("Skickar…", 8000);
  try { const r = await api(`car/${car}/action`, { kind, ...(extra || {}) }); toast((r.ok === false ? "⚠ " : "✓ ") + (r.msg || "Klart"), 5000); S = await api("state"); render(); if (["set", "start", "max", "auto", "stop"].includes(kind)) [6000, 16000].forEach((ms) => setTimeout(async () => { try { S = await api("state"); render(); } catch {} }, ms)); } catch (e) { toast("⚠ " + e.message, 5000); } finally { busy = false; }
}
let cdGroup = "", cdPage = 0;
async function carDataSheet(key, first = true) {
  if (first) { cdGroup = ""; cdPage = 0; }
  let d; try { d = await api(`car/${key}/entities`); } catch (e) { return toast(e.message); }
  const car = S.cars.find((x) => x.key === key), grp = {}; d.rows.forEach((r) => (grp[r.group] = grp[r.group] || []).push(r));
  const names = Object.keys(grp); if (!grp[cdGroup]) cdGroup = names[0];
  const BTN = { flash: "Blinka", horn: "Tuta", wake: "Väck bilen", refresh: "Uppdatera data", start_charge: "Starta laddning (bilen)" };
  const rowsAll = grp[cdGroup] || [];
  const draw = (per) => {
    const pages = Math.max(1, Math.ceil(rowsAll.length / per)); cdPage = Math.min(cdPage, pages - 1);
    const rows = rowsAll.slice(cdPage * per, cdPage * per + per);
    sheet(`<h3>${esc(car.name)} – all data</h3><div class="note">${d.valid} av ${d.total} entiteter har giltigt värde. ✓ = validerad, ⚠ = otillgänglig eller gammal.</div>
  <div class="seg" style="grid-auto-flow:row;grid-template-columns:1fr 1fr">${d.buttons.map((b) => `<button data-p="${b}">${BTN[b] || b}</button>`).join("")}</div>
  <div class="chips">${names.map((g) => `<button class="chip ${g === cdGroup ? "on" : ""}" data-g="${esc(g)}" style="padding:4px 10px;font-size:.78rem">${esc(g)}</button>`).join("")}</div>
  ${rows.map((r) => `<div class="setrow"><span>${r.valid ? "✓" : "⚠"} ${esc(r.name.replace(new RegExp("^(" + car.name.split(" ").map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|") + ")( |$)+", "i"), ""))}</span><span class="note" style="text-align:right;${r.valid ? "" : "color:var(--warn)"}">${esc(r.state)} ${esc(r.unit)}${r.why ? ` · ${esc(r.why)}` : ""}</span></div>`).join("")}
  ${pages > 1 ? `<div class="seg"><button data-pg="-1" ${cdPage === 0 ? "disabled" : ""}>‹</button><button disabled>${cdPage + 1} / ${pages}</button><button data-pg="1" ${cdPage >= pages - 1 ? "disabled" : ""}>›</button></div>` : ""}`);
  };
  fitSheet(draw, sheetRows(360, 52));
  $("#sheet").onclick = async (e) => { if (e.target.id === "sheet") return closeSheet();
    const g = e.target.closest("[data-g]"); if (g) { cdGroup = g.dataset.g; cdPage = 0; carDataSheet(key, false); return; }
    const pg = e.target.closest("[data-pg]"); if (pg) { cdPage += +pg.dataset.pg; carDataSheet(key, false); return; }
    const b = e.target.closest("[data-p]"); if (!b) return; if (ROLE === "guest") return toast("Gästläge – du kan bara titta"); buzz(); try { const r = await api(`car/${key}/press`, { button: b.dataset.p }); toast(r.msg); } catch (er) { toast(er.message); } };
}
let logPage = 0;
function fitSheet(draw, per0) {                         // ritar om med färre rader tills rutan får plats utan scroll
  let per = per0;
  for (let i = 0; i < 10; i++) { draw(per); const p = document.querySelector("#sheet .panel"); if (!p || p.scrollHeight <= p.clientHeight + 1 || per <= 1) break; per--; }
}
const sheetRows = (reserve, rowH) => Math.max(3, Math.floor((innerHeight * 0.94 - reserve) / rowH));          // hur många rader som får plats utan scroll
async function logSheet(first = true) {
  if (first) logPage = 0;
  let d; try { d = await api("log"); } catch (e) { return toast(e.message); }
  const draw = (per) => {
    const pages = Math.max(1, Math.ceil(d.rows.length / per)); logPage = Math.min(logPage, pages - 1);
    const rows = d.rows.slice(logPage * per, logPage * per + per);
    sheet(`<h3>Familjelogg</h3>${rows.map((r) => `<div class="setrow"><span><b>${esc(r.who)}</b> ${esc(r.txt)}</span><span class="note">${esc(r.t)}</span></div>`).join("") || '<div class="note">Inget loggat än.</div>'}${pages > 1 ? `<div class="seg"><button data-pg="-1" ${logPage === 0 ? "disabled" : ""}>‹</button><button disabled>${logPage + 1} / ${pages}</button><button data-pg="1" ${logPage >= pages - 1 ? "disabled" : ""}>›</button></div>` : ""}`);
  };
  fitSheet(draw, sheetRows(190, 78));
  $("#sheet").onclick = (e) => { if (e.target.id === "sheet") return closeSheet(); const b = e.target.closest("[data-pg]"); if (b) { logPage += +b.dataset.pg; logSheet(false); } };
}
async function reportSheet() {
  let d; try { d = await api("report"); } catch (e) { return toast(e.message); } const t = d.total;
  sheet(`<h3>Veckorapport (7 dygn)</h3><div class="note">Förbrukning ${f1(t.use, 0)} kWh · sol ${f1(t.sun, 0)} kWh · elbil ${f1(t.ev, 0)} kWh · spotkostnad ca ${f1(t.cost, 0)} ${moneyUnit()} · snittpris ${f1(t.price, 2)} ${moneyUnit()}/kWh</div>
  <div class="setrow note"><b style="flex:1">Dag</b><b style="width:56px;text-align:right">Förbr.</b><b style="width:48px;text-align:right">Sol</b><b style="width:48px;text-align:right">Bil</b><b style="width:48px;text-align:right">${esc(moneyUnit())}</b></div>
  ${d.days.map((x) => `<div class="setrow"><span style="flex:1">${esc(x.d)}</span><span style="width:56px;text-align:right">${f1(x.use, 0)}</span><span style="width:48px;text-align:right">${f1(x.sun, 0)}</span><span style="width:48px;text-align:right">${f1(x.ev, 0)}</span><span style="width:48px;text-align:right">${f1(x.cost, 0)}</span></div>`).join("")}<div class="note">kWh per dygn. Kostnaden är spotpris utan nätavgifter.</div>`);
}
function spaReadySheet() {
  const sp = H && H.spa || {}; let temp = sp.ready_temp || 38; const dflt = new Date(Date.now() + 86400000); dflt.setHours(18, 0, 0, 0); let when = new Date(dflt.getTime() - dflt.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  const draw = () => sheet(`<h3>Spabadet klart till…</h3><div class="note">${sp.ready_at ? `Nu satt: ${esc(sp.ready_at)} – ${f1(sp.ready_temp)}°` : "Ingen tid satt just nu."}</div><div class="setrow"><span>Klart</span><input id="sw" type="datetime-local" value="${when}" style="font-size:16px;padding:6px 8px;border-radius:10px;border:1px solid var(--line);background:var(--card);color:var(--txt)"></div>
  <div class="setrow"><span>Temperatur</span><div class="step"><button data-v="t-">−</button><span>${f1(temp)}°</span><button data-v="t+">+</button></div></div><div class="seg"><button data-v="go">Spara</button><button data-v="off">Stäng av tidsstyrning</button></div>`);
  draw();
  $("#sheet").onclick = async (e) => { const b = e.target.closest("[data-v]"); if (!b) { if (e.target.id === "sheet") closeSheet(); return; } const v = b.dataset.v; const w = $("#sw"); if (w) when = w.value || when;
    if (v === "t+") { temp = Math.min(40, temp + 0.5); draw(); } else if (v === "t-") { temp = Math.max(20, temp - 0.5); draw(); }
    else if (v === "go" || v === "off") { try { const r = await api("home/spa_ready", v === "off" ? { off: true } : { when, temp }); closeSheet(); toast(r.msg); H = await api("home"); render(); } catch (er) { toast(er.message); } } };
}
let ACCESS_CAR = null;
function accessSheet(key) {
  const c = S.cars.find((x) => x.key === key) || S.cars.find((x) => x.access); if (!c || !c.access) return; const a = c.access; ACCESS_CAR = c.key;
  sheet(`<h3>${esc(c.name)} – lås & luckor</h3><div class="note">Bilen är ${a.locked ? "<b>låst</b>" : "<b style='color:var(--warn)'>upplåst</b>"}. Upplåsning och luckor kräver lösenordet (gäller i 10 min).</div><div class="seg"><button data-x="${a.locked ? "unlock" : "lock"}">${a.locked ? "Lås upp" : "Lås"}</button></div>${a.has_trunk || a.has_frunk ? `<div class="seg">${a.has_trunk ? `<button data-x="trunk">${a.trunk ? "Stäng baklucka" : "Öppna baklucka"}</button>` : ""}${a.has_frunk ? `<button data-x="frunk">${a.frunk ? "Stäng framlucka" : "Öppna framlucka"}</button>` : ""}</div>` : ""}`);
  $("#sheet").onclick = async (e) => { const b = e.target.closest("[data-x]"); if (!b) { if (e.target.id === "sheet") closeSheet(); return; } closeSheet(); await access(b.dataset.x); };
}
async function access(what) {
  if (busy) return; busy = true; buzz(30);
  try { let r; try { r = await api(`car/${ACCESS_CAR}/access`, { what }); } catch (e) { if (e.message !== "secure") throw e; busy = false; return askPassword(what); } toast(r.msg); setTimeout(async () => { try { S = await api("state"); if (!sheetOpen()) render(); } catch {} }, 4000); }
  catch (e) { toast(e.message); } finally { busy = false; }
}
function askPassword(what) {
  sheet(`<h3>Bekräfta med lösenord</h3><div class="note">För din säkerhet krävs lösenordet för att låsa upp bilen eller öppna luckor.</div><input id="pw2" type="password" autocomplete="current-password" placeholder="Lösenord" style="font-size:16px;padding:15px;border-radius:16px;border:1px solid var(--line);background:var(--card);color:var(--txt);text-align:center"><button class="big" data-x="ok">Bekräfta</button>`);
  $("#sheet").onclick = async (e) => { const b = e.target.closest("[data-x]"); if (!b) { if (e.target.id === "sheet") closeSheet(); return; } try { await api("secure", { password: $("#pw2").value }); closeSheet(); await access(what); } catch (er) { toast(er.message); } };
}
function themeMode() { try { const t = localStorage.getItem("ew_theme"); return t === "light" || t === "dark" ? t : "auto"; } catch { return "auto"; } }
function themeIcon() {
  const m = themeMode(), S = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">';
  return m === "light" ? S + '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>'
    : m === "dark" ? S + '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>'
    : S + '<circle cx="12" cy="12" r="9"/><path d="M12 3a9 9 0 0 0 0 18z" fill="currentColor"/></svg>';
}
function cycleTheme() {
  const n = { auto: "light", light: "dark", dark: "auto" }[themeMode()];
  try { n === "auto" ? localStorage.removeItem("ew_theme") : localStorage.setItem("ew_theme", n); } catch {}
  if (n === "auto") document.documentElement.removeAttribute("data-theme"); else document.documentElement.setAttribute("data-theme", n);
  const dark = n === "dark" || (n === "auto" && !matchMedia("(prefers-color-scheme: light)").matches);
  const tc = document.querySelector('meta[name="theme-color"]'); if (tc) tc.content = dark ? "#0b1220" : "#f2f5fa";
  toast(n === "auto" ? "Tema: följer telefonen" : n === "light" ? "Tema: ljust" : "Tema: mörkt");
  render();
}
let setSec = "effekt";
let NP = null;                                 // notiskategorierna (smartbox/notify_prefs.py)
let NL = null;                                 // skickade aviseringar (smartbox/notify_log.py)
let LG = null, LGL = "";                        // loggen (smartbox/ew_journal.py)
async function settingsSheet() {
  if (!SET) { try { SET = await api("settings"); } catch (e) { return toast(e.message); } }
  if (!NP && ER() === "owner") { try { NP = (await api("notify-prefs")).categories; } catch (e) { NP = null; } }
  if (setSec === "notiser" && NL === null && ER() === "owner") { NL = undefined; api("notify-log?days=7").then((d) => { NL = d; settingsSheet(); }).catch(() => { NL = { rows: [] }; settingsSheet(); }); }
  if (setSec === "logg" && LG === null && ER() === "owner") { LG = undefined; api("journal?hours=6&lvl=" + LGL).then((d) => { LG = d.rows || []; settingsSheet(); }).catch(() => { LG = []; settingsSheet(); }); }
  const v = SET.values, R = SET.rules, off = (k) => k === "power_limit_kw" && !v.peak_shaving_enabled, row = (k, label, unit) => { const r = R[k]; return `<div class="setrow${off(k) ? " dim" : ""}"${off(k) ? ' title="Gäller bara när effektvakten är på"' : ""}><span>${label}${off(k) ? ' <span class="note">(effektvakt av)</span>' : ""}</span>${r[0] === "bool" ? `<button class="sw ${v[k] ? "on" : ""}" data-set="${k}" data-bool="1"></button>` : `<div class="step"><button data-set="${k}" data-d="-${r[3]}" ${off(k) ? "disabled" : ""}>−</button><span>${f1(v[k], r[3] < 1 ? 1 : 0)}${unit}</span><button data-set="${k}" data-d="${r[3]}" ${off(k) ? "disabled" : ""}>+</button></div>`}</div>`; };
  const standalone = window.matchMedia("(display-mode: standalone)").matches || navigator.standalone;
  const owner = ER() === "owner", secs = [...(owner ? [["effekt", "Effekt"], ["notiser", "Notiser"], ["logg", "Logg"]] : []), ["appen", "Appen"], ["konto", "Konto"]];
  if (!secs.some(([s]) => s === setSec)) setSec = secs[0][0];
  const tabs = `<div class="seg segtabs">${secs.map(([s, l]) => `<button data-s="sec:${s}" class="${setSec === s ? "on" : ""}">${l}</button>`).join("")}</div>`;
  const body = {
    effekt: () => `${row("peak_shaving_enabled", "Effektvakt (peak shaving)")}${row("power_limit_kw", "Effektgräns", " kW")}${row("fuse_size_a", "Huvudsäkring", " A")}${row("temp_cheap", "Värmare vid billig el", "°")}${row("temp_expensive", "Sänkt värme vid dyr el", "°")}${row("spa_normal_temp", "Spabad normal", "°")}${row("spa_low_temp", "Spabad eco-golv", "°")}` +
      `<div class="setrow"><span>Spabadets badtider<div class="note">När ni brukar bada - utanför dem får badet svalna till eco-golvet</div></span><button class="mini" data-a="spabath">Ställ in</button></div>` +
      `<div class="setrow"><span>Elpriser inkl. moms${v.nordpool_vat_enabled == null ? ' <span class="note">(nuvarande läge okänt)</span>' : ""}</span><button class="sw${v.nordpool_vat_enabled ? " on" : ""}" data-set="nordpool_vat_enabled" data-bool="1">${v.nordpool_vat_enabled == null ? "?" : ""}</button></div>` +
      `<div class="note">Styr Home Assistants egen Nord Pool-integration direkt (radera+återskapa, ingen enkel "ändra ett fält"-knapp finns i HA) - priserna växlar om efter några sekunder. Kan inte visa nuvarande läge förrän du växlat minst en gång härifrån.</div>`,
    notiser: () => (NP ? NP.map((c) => `<div class="setrow"><span>${esc(c.label)}<div class="note">${esc(c.desc)}</div></span><button class="sw${c.on ? " on" : ""}" data-s="np:${esc(c.key)}" aria-label="${esc(c.label)}"></button></div>`).join("") : `<div class="note">Laddar…</div>`)
      + `<div class="note" style="margin-top:10px">Fler val inom kategorierna:</div>${row("notify_spa_ready", "Avisera: spabadet klart")}${row("notify_ev_start", "Avisera: elbil startar")}${row("notify_washer_start", "Avisera: tvätt startar")}${row("notify_spa_open", "Avisera: spalocket öppet")}`
      + (NL && window.EWJournal ? `<div style="margin-top:14px">${EWJournal.notifyHtml(NL, { compact: true })}</div>` : `<div class="note" style="margin-top:14px">Hämtar skickade aviseringar…</div>`),
    logg: () => `<div class="seg">${[["", "Allt"], ["fel", "Fel"], ["varning", "Varningar"], ["notis", "Notiser"]].map(([v, t]) => `<button data-s="lg:${v}" class="${LGL === v ? "on" : ""}">${t}</button>`).join("")}</div>
      <div class="note">Allt EnergyWizard läst in, bestämt, skickat och fått för fel de senaste 6 timmarna. <a href="api/journal/download?days=2">Ladda ner 2 dygn</a> (att bifoga i en issue).</div>
      ${LG ? (LG.length ? LG.map((r) => `<div class="plrow" style="display:block;font-size:.8rem"><span class="note">${esc(new Date(r.ts).toLocaleTimeString("sv-SE"))} · ${esc(r.lvl)} · ${esc(r.src)}</span><div style="white-space:pre-wrap;overflow-wrap:anywhere">${esc(r.msg)}</div></div>`).join("") : `<div class="note">Inget i loggen.</div>`) : `<div class="note">Laddar…</div>`}`,
    appen: () => `<div class="note" style="margin-top:2px">Stil</div><div class="seg"><button data-s="style:new" class="${CL() ? "" : "on"}">Ny (standard)</button><button data-s="style:classic" class="${CL() ? "on" : ""}">Klassisk</button></div><div class="seg">${((S && S.cars) || []).map((c) => `<button data-s="car:${esc(c.key)}" class="${primary() === c.key ? "on" : ""}">Huvudbil: ${esc(c.name)}</button>`).join("")}</div><div class="seg"><button data-s="glass" class="${LS.get("ew_glass", CL() ? "1" : "0") === "1" ? "on" : ""}">Glasdesign</button><button data-s="ambient" class="${LS.get("ew_ambient", CL() ? "1" : "0") === "1" ? "on" : ""}">Dygnsfärger</button></div><div class="seg"><button data-s="simple" class="${LS.get("ew_simple", "") === "1" ? "on" : ""}">Enkel vy (bara huvudbilen)</button>${standalone ? "" : `<button data-s="install">${installEvt ? "Installera appen" : "Lägg till på hemskärmen"}</button>`}</div><div class="seg"><button data-s="reload">Ladda om appen</button></div>
      <div class="note" style="margin-top:6px">Språk / Language</div><div class="seg" data-noi18n>${Object.entries(I18N.languages).map(([k, v]) => `<button data-s="lang:${k}" class="${I18N.lang === k ? "on" : ""}">${esc(v)}</button>`).join("")}</div>
      <div class="seg"><a class="mini" href="${I18N.TRANSLATE_URL}" target="_blank" rel="noopener">Hjälp till att översätta</a><a class="mini" href="${SPONSOR_URL}" target="_blank" rel="noopener">❤️ Sponsra EnergyWizard</a></div>
      ${ER() === "owner" ? `<div class="seg"><button data-s="sponsornotice" class="${SPONSOR && SPONSOR.enabled ? "on" : ""}">Påminn mig en gång i månaden</button></div>` : ""}`,
    konto: () => `${ROLE === "owner" ? `<div class="seg"><button data-a="viewas" data-v="" class="${!VIEWAS ? "on" : ""}">Jag (admin)</button><button data-a="viewas" data-v="family" class="${VIEWAS === "family" ? "on" : ""}">Visa som familj</button><button data-a="viewas" data-v="guest" class="${VIEWAS === "guest" ? "on" : ""}">Visa som gäst</button></div>` : ""}${ER() !== "owner" ? `<div class="note">${ER() === "guest" ? "Gästläge: du kan titta på allt men inte ändra." : "Dina inställningar är bara bil, schema och ljus."}</div>` : ""}<button class="mini" data-a="log">Visa familjelogg</button><div class="note" style="text-align:center">Inloggad som ${esc(ME === "owner" ? "ägare" : ME)}</div><div class="seg"><button data-s="logout">Logga ut</button></div>`,
  }[setSec]();
  sheet(`<h3>Inställningar</h3>${tabs}${body}`);
  $("#sheet").onclick = async (e) => {
    if (e.target.id === "sheet") return closeSheet();
    const x = e.target.closest("[data-set]");
    if (x) { const k = x.dataset.set; let val; if (x.dataset.bool) val = !SET.values[k]; else { const r = SET.rules[k]; val = Math.round((SET.values[k] + parseFloat(x.dataset.d)) / r[3]) * r[3]; val = Math.max(r[1], Math.min(r[2], val)); } try { const r = await api("settings", { key: k, value: val }); SET.values[k] = r.value; settingsSheet(); } catch (er) { toast(er.message); } return; }
    const y = e.target.closest("[data-s]"); if (!y) return; const s = y.dataset.s;
    if (s.startsWith("sec:")) { setSec = s.slice(4); if (setSec === "notiser") NL = null; settingsSheet(); return; }
    if (s.startsWith("lg:")) { LGL = s.slice(3); LG = null; settingsSheet(); return; }
    if (s.startsWith("np:")) { const k = s.slice(3), c = (NP || []).find((x) => x.key === k); if (!c) return; try { NP = (await api("notify-prefs", { on: { [k]: !c.on } })).categories; } catch (er) { toast(er.message); } settingsSheet(); return; }
    if (s.startsWith("lang:")) { const l = s.slice(5); if (ER() === "owner") { try { await api("setup/language", { language: l }); } catch {} } I18N.set(l); return; }
    if (s === "sponsornotice") { try { const r = await api("sponsor/notice", { enabled: !(SPONSOR && SPONSOR.enabled) }); SPONSOR = { ...(SPONSOR || {}), enabled: r.enabled }; } catch (er) { toast(er.message); } settingsSheet(); return; }
    if (s.startsWith("style:")) { LS.set("ew_style", s.slice(6)); applyLook(); render(); settingsSheet(); return; }
    if (s === "glass" || s === "ambient") { LS.set("ew_" + s, LS.get("ew_" + s, CL() ? "1" : "0") === "1" ? "0" : "1"); applyLook(); }
    if (s.startsWith("car:")) LS.set("ew_primary", s.slice(4)); if (s === "simple") LS.set("ew_simple", LS.get("ew_simple", "") === "1" ? "" : "1");
    if (s === "install") { installApp(); return; }
    if (s === "reload") { hardReload(); return; }
    if (s === "logout") { try { await api("logout", {}); } catch {} hardReload(); return; } closeSheet();
  };
}
function healthSheet() { sheet(`<h3>Varningar</h3>${S.health.map((h) => `<div class="setrow"><span>${esc(h)}</span></div>`).join("")}`); }
const pad2 = (n) => String(n).padStart(2, "0");
function clockHTML(h, m) { return `<div class="clock"><div class="cg"><button data-v="h+">+</button><b>${pad2(h)}</b><button data-v="h-">−</button></div><b class="cc">:</b><div class="cg"><button data-v="m+">+</button><b>${pad2(m)}</b><button data-v="m-">−</button></div></div>`; }
function clockStep(v, h, m) { if (v === "h+") h = (h + 1) % 24; else if (v === "h-") h = (h + 23) % 24; else if (v === "m+") m = (m + 15) % 60; else if (v === "m-") m = (m + 45) % 60; return [h, m]; }
function schClockSheet(d) {
  let [h, m] = SCH[schCar][d].time.split(":").map(Number);
  const draw = () => sheet(`<h3>${DAYS[d]} – klar kl</h3>${clockHTML(h, m)}<button class="big" data-v="ok">Klar</button>`);
  draw();
  $("#sheet").onclick = (e) => { const b = e.target.closest("[data-v]"); if (!b) { if (e.target.id === "sheet") closeSheet(); return; } const v = b.dataset.v;
    if (v === "ok") { SCH[schCar][d].time = `${pad2(h)}:${pad2(m)}`; closeSheet(); schedSave(schCar, d); } else { [h, m] = clockStep(v, h, m); draw(); } };
}
async function schedSave(car, day) { const x = SCH[car][day]; try { await api("schedule", { car, day, enabled: x.enabled, time: x.time, soc: x.soc }); toast("Sparat"); } catch (e) { toast(e.message); } }
function climClockSheet() {
  const x = CLIM && CLIM[schCar]; if (!x) return;
  let [h, m] = String(x.time).split(":").map(Number);
  const draw = () => sheet(`<h3>Kupévärme – varm kl</h3>${clockHTML(h, m)}<button class="big" data-v="ok">Klar</button>`);
  draw();
  $("#sheet").onclick = (e) => { const b = e.target.closest("[data-v]"); if (!b) { if (e.target.id === "sheet") closeSheet(); return; } const v = b.dataset.v;
    if (v === "ok") { x.time = `${pad2(h)}:${pad2(m)}`; closeSheet(); render(); climSave(); } else { [h, m] = clockStep(v, h, m); draw(); } };
}
async function climSave() {
  const x = CLIM && CLIM[schCar]; if (!x) return;
  try { await api("schedule/climate", { car: schCar, enabled: x.enabled, time: x.time, temp: x.temp }); toast("Sparat"); }
  catch (e) { toast(e.message); }
}
document.addEventListener("click", async (e) => {
  const jb = e.target.closest("[data-jback]");             // Höll vi planen? Idag/Igår (journal.js) - bara att titta, alla roller
  if (jb) { jBack = +jb.dataset.jback; JR = await api("control-journal?back=" + jBack).catch(() => JR); return render(); }
  const b = e.target.closest("[data-a]"); if (!b || b.disabled) return;
  const a = b.dataset.a, c = b.dataset.c, v = b.dataset.v;
  if (!can(a)) { toast(ER() === "guest" ? "Gästläge – du kan bara titta" : "Det här kan bara administratören ändra"); return; }
  if (a === "tab") { if (!$("#sheet").hidden) $("#sheet").hidden = true; if (v !== page) { try { history.pushState({ page: v }, ""); } catch (e) {} } page = v; LS.set("ew_page", v); render(); return load(); }
  if (a === "planlist") return planSheet(c);
  if (a === "power") return powerSheet(c);
  if (a === "swap") { LS.set("ew_primary", c); return render(); }
  if (a === "update") return updateSheet();
  if (a === "settings") { NL = null; return settingsSheet(); }
  if (a === "health") return healthSheet();
  if (a === "access") return accessSheet(c);
  if (a === "cardata") return carDataSheet(c);
  if (a === "home" && b.dataset.k === "hotwater" && v === "on") return hotwaterSheet();     // #397: välj hur länge
  if (a === "home") { buzz(); try { const r = await api("home/" + b.dataset.k, { value: v }); toast(r.msg); H = await api("home"); render(); } catch (er) { toast(er.message); } return; }
  if (a === "spabath") { spaBathSheet(); return; }
  if (a === "spa") { buzz(); try { const r = await api("home/" + b.dataset.k, { value: v === "1" }); toast(r.msg); H = await api("home"); render(); } catch (er) { toast(er.message); } return; }
  if (a === "energy" && b.dataset.k === "limit" && +v < 100 && !b.dataset.ok) {      // 0–75 % stryper solelen: kräver bekräftelse så att det inte sker av misstag
    sheet(`<h3>Begränsa solelen till ${v} %?</h3><div class="note">Exporten och solproduktionen begränsas tills du väljer 100 % igen. AI:n släpper begränsningen själv bara vid minuspris.</div><button class="big stop" data-x="ok">Ja, begränsa till ${v} %</button><button class="mini" data-x="no">Avbryt</button>`);
    $("#sheet").onclick = (e) => { const x = e.target.closest("[data-x]"); if (e.target.id === "sheet" || (x && x.dataset.x === "no")) return closeSheet(); if (x) { closeSheet(); b.dataset.ok = "1"; b.click(); delete b.dataset.ok; } };
    return;
  }
  if (a === "energy") { buzz(); try { const r = await api("energy/" + b.dataset.k, { value: b.dataset.k === "floor" ? parseFloat(v) : (b.dataset.k === "notify" ? v === "1" : v) }); toast(r.msg); EN = await api("energy"); render(); } catch (er) { toast(er.message); } return; }
  if (a === "rooms") return roomsSheet();
  if (a === "guest") { const gc = ((S && S.cars) || []).find((x) => x.key === c); if (gc) guestSheet(gc); return; }
  if (a === "refreshsoc") { buzz(20); toast("Uppdaterar bilens data…", 6000); try { await api(`car/${c}/press`, { button: "refresh" }); } catch (er) { toast("⚠ " + er.message, 5000); return; } [3000, 8000, 20000].forEach((ms) => setTimeout(async () => { try { S = await api("state"); render(); if (ms === 8000) toast("Uppdaterat", 2000); } catch {} }, ms)); return; }
  if (a === "aidecisions") { sheet(`<h3>AI-beslut just nu</h3><div class="note" style="white-space:pre-wrap;max-height:60vh;overflow:auto">${esc(EN.log || EN.decision || "–")}</div>`); return; }
  if (a === "installapp") { installApp(); return; }
  if (a === "theme") { cycleTheme(); return; }
  if (a === "ser") { const [ck, ix] = v.split(":"); const h = hiddenSer(ck), n = +ix; LS.set("ew_hide_" + ck, (h.includes(n) ? h.filter((x) => x !== n) : [...h, n]).join(",")); render(); return; }
  if (a === "schclock") { schClockSheet(+b.dataset.d); return; }
  if (a === "climclock") { climClockSheet(); return; }
  if (a === "clim") { const x = CLIM && CLIM[schCar]; if (!x) return; const f = b.dataset.f; buzz(8); if (f === "enabled") x.enabled = !x.enabled; else if (f === "t+") x.temp = Math.min(28, Math.round((Number(x.temp) + 1) * 10) / 10); else if (f === "t-") x.temp = Math.max(15, Math.round((Number(x.temp) - 1) * 10) / 10); render(); return climSave(); }
  if (a === "lights") { buzz(25); try { const r = await api("lights", { action: v }); toast(r.msg); LJ = await api("lights"); render(); } catch (er) { toast(er.message); } return; }
  if (a === "viewas") { VIEWAS = v; LS.set("ew_viewas", v); grAt = 0; closeSheet(); loadGreeting(); return; }
  if (a === "trip") return tripSheet(c);
  if (a === "report") return reportSheet();
  if (a === "closesheet") return closeSheet();
  if (a === "nowsheet") return nowSheet();
  if (a === "solarsheet") { if (EN) solarSheet(); return; }
  if (a === "insights") { if (EN) insightsSheet(); return; }
  if (a === "svp") { svPeriod = v; LS.set("ew_sv_period", v); return render(); }
  if (a === "planview") { planView = v; LS.set("ew_plan_view", v); render(); return load(); }
  if (a === "planall") { sheet(`<h3>Planen framåt</h3>${(PL.items || []).map((i) => `<div class="plrow"><div class="plw">${esc(i.when)}</div><div><b>${esc(i.title)}</b><div class="note">${esc(i.detail)}</div></div></div>`).join("")}<button class="mini" data-a="closesheet">Stäng</button>`); return; }
  if (a === "histview") { histView = v; LS.set("ew_hist_view", v); render(); return load(); }
  if (a === "hp") { hxPeriod = v; LS.set("ew_hx_period", v); return render(); }
  if (a === "bigchart") return bigChartSheet();
  if (a === "bigrange") { hxRange = v; LS.set("ew_hx_range", v); try { HX = await api("energyhistory?range=" + v); } catch (er) { toast(er.message); } if (bigChartSheet.redraw) bigChartSheet.redraw(); return; }
  if (a === "hr") { hxRange = v; LS.set("ew_hx_range", v); try { HX = await api("energyhistory?range=" + v); } catch (er) { toast(er.message); } return render(); }
  if (a === "peaks") { sheet(`<h3>Effekttoppar denna månad</h3>${EN && EN.peaks.length ? EN.peaks.map((p) => `<div style="display:flex;justify-content:space-between"><b>${f1(p.kw)} kW</b><span class="note">${p.t}</span></div>`).join("") : '<div class="note">Ingen data</div>'}<button class="mini" data-a="closesheet">Stäng</button>`); return; }
  if (a === "spaready") return spaReadySheet();
  if (a === "log") return logSheet();
  if (a === "greet" && GR) return sheet(`<h3>${esc(GR.hello)}</h3><div class="note">${esc(GR.weather)}</div><div style="font-size:1.1rem;font-weight:600">${esc(GR.line)}</div>`);
  if (a === "schcar") { schCar = v; return render(); }
  if (a === "sch") { const d = +b.dataset.d, x = SCH[schCar][d], f = b.dataset.f; buzz(8); if (f === "enabled") x.enabled = !x.enabled; else if (f === "soc+") x.soc = Math.min(100, x.soc + 5); else if (f === "soc-") x.soc = Math.max(20, x.soc - 5); render(); return schedSave(schCar, d); }
  if (a === "start") return chargeNowSheet(c);
  if (["stop", "auto", "heat_on", "heat_off"].includes(a)) return act(c, a);
});
document.addEventListener("change", (e) => { const t = e.target.closest('[data-a="schtime"]'); if (t && !can("schtime")) { toast("Gästläge – du kan bara titta"); render(); return; } if (t) { const d = +t.dataset.d; SCH[schCar][d].time = t.value || "07:00"; schedSave(schCar, d); } });
window.addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); installEvt = e; if (typeof render === "function" && S) render(); });
window.addEventListener("appinstalled", () => { LS.set("ew_installed", "1"); installEvt = null; toast("Appen är installerad"); if (S) render(); });
const isStandalone = () => window.matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
const needInstall = () => !isStandalone() && LS.get("ew_installed", "") !== "1";
function installApp() {
  if (installEvt) { installEvt.prompt(); installEvt.userChoice.then((r) => { if (r.outcome === "accepted") { LS.set("ew_installed", "1"); } render(); }).catch(() => {}); return; }
  const ios = /iphone|ipad|ipod/i.test(navigator.userAgent);
  sheet(`<h3>Installera som app</h3><div class="note" style="line-height:1.5">${ios ? "Tryck på Dela-knappen i Safari och välj Lägg till på hemskärmen." : "Öppna Chrome-menyn (tre prickar) och välj Installera app eller Lägg till på startskärmen."}<br>Då startar den som en riktig app, utan adressfält, med genvägar på ikonen.</div><button class="big" data-v="ok">Klart</button>`);
  $("#sheet").onclick = (e) => { if (e.target.closest("[data-v]") || e.target.id === "sheet") closeSheet(); };
}
document.addEventListener("visibilitychange", () => { if (!document.hidden) load(); });
if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js", { scope: "./" }).catch(() => {});
let ES = null, esAt = 0, esLive = false, esTimer = null;
function openStream() {                                   // servern pushar "något ändrades": appen hämtar direkt. Reservpolling (långsammare) finns om strömmen faller.
  if (!window.EventSource || ES) return;
  try {
    ES = new EventSource("api/stream");
    ES.onmessage = () => { esLive = true; if (document.hidden) return; clearTimeout(esTimer); esTimer = setTimeout(() => { if (!busy) load(); }, 150); };
    ES.onerror = () => { esLive = false; if (ES && ES.readyState === 2) ES = null; };      // stängd (t.ex. 401 före inloggning): öppnas på nytt vid nästa lyckade hämtning
  } catch { ES = null; }
}
document.addEventListener("visibilitychange", () => { if (!document.hidden) load(); });
function start() {
  clearInterval(timer); load(); openStream();
  timer = setInterval(() => { if (!document.hidden && (!esLive || Date.now() - esAt > 30000)) { esAt = Date.now(); load(); } }, page === "hus" ? 8000 : 5000);       // med levande ström: bara en lugn kontrollhämtning var 30:e s
}
let errN = 0, errT = 0;
function reportErr(m, s) { const now = Date.now(); if (now - errT > 60000) { errT = now; errN = 0; } if (++errN > 3) return; try { fetch("api/clienterr", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ m: String(m), s: String(s || ""), ua: navigator.userAgent }) }); } catch {} }
window.addEventListener("error", (e) => reportErr(e.message, (e.filename || "").split("/").pop() + ":" + e.lineno));
// Med var felet uppstod (första raderna i förloppet) - 2026-11-06 kom "reading '0'" utan plats och gick inte att spåra
window.addEventListener("unhandledrejection", (e) => reportErr("promise: " + (e.reason && e.reason.message || e.reason),
  e.reason && e.reason.stack ? String(e.reason.stack).split("\n").slice(1, 4).join(" | ").replace(/https?:\/\/[^ )]*\//g, "") : ""));
function scaleFix() {                       // Chrome i "Datoranpassad webbplats" ger telefonen en 980 px bred vy: skala upp gränssnittet så det ser ut som på en telefon (inte som en liten kolumn)
  const de = document.documentElement, desk = matchMedia("(pointer: coarse)").matches && innerWidth >= 900;
  if (desk) { const z = innerWidth / 430; de.style.zoom = z; de.style.setProperty("--u", innerHeight / z / 100 + "px"); }
  else { de.style.zoom = ""; de.style.setProperty("--u", (window.visualViewport ? visualViewport.height : innerHeight) / 100 + "px"); }      // mäts i stället för dvh: efter väckning från bakgrunden kan dvh vara fel en stund, och då hamnar menyn utanför skärmen
}
// Utseende: glasdesign (frostat glas) och dygnsfärger (bakgrunden följer morgon/dag/kväll/natt). Båda valfria; ?look=glass,ambient,evening visar en förhandsvisning utan att spara.
const todOf = (h) => (h >= 5 && h < 10 ? "morning" : h >= 10 && h < 16 ? "day" : h >= 16 && h < 21 ? "evening" : "night");
function applyLook() {
  const de = document.documentElement, q = new URLSearchParams(location.search).get("look") || "", pv = q.split(",");
  const dflt = CL() ? "1" : "0";        // klassisk stil: glas och dygnsfärger på som förut; ny stil: av tills man slår på dem
  CL() ? de.setAttribute("data-classic", "1") : de.removeAttribute("data-classic");
  const glass = pv.includes("glass") || (q === "" && LS.get("ew_glass", dflt) === "1"), amb = pv.includes("ambient") || (q === "" && LS.get("ew_ambient", dflt) === "1");      // båda på som standard; "0" = avstängd av användaren
  glass ? de.setAttribute("data-glass", "1") : de.removeAttribute("data-glass");
  if (amb) { de.setAttribute("data-ambient", "1"); de.setAttribute("data-tod", ["morning", "day", "evening", "night"].find((t) => pv.includes(t)) || todOf(new Date().getHours())); } else { de.removeAttribute("data-ambient"); de.removeAttribute("data-tod"); }
}
applyLook(); setInterval(applyLook, 600000);
const resync = () => { scaleFix(); fit(); };
scaleFix(); window.addEventListener("resize", resync);
if (window.visualViewport) visualViewport.addEventListener("resize", resync);
["pageshow", "focus", "orientationchange"].forEach((n) => window.addEventListener(n, () => { resync(); [120, 500, 1500].forEach((ms) => setTimeout(resync, ms)); }));      // webbläsaren rapporterar rätt höjd först strax efter återgången
document.addEventListener("visibilitychange", () => { if (!document.hidden) { resync(); [120, 500, 1500].forEach((ms) => setTimeout(resync, ms)); } });
try { history.replaceState({ page }, ""); } catch (e) {}

// ---- installationsruta: vid varje öppning tills appen är installerad; kryss uppe till höger hoppar över den (den här gången) ---------------------------------
let _instShown = false, _instHelp = false;
function drawInstallPrompt() {
  let o = document.getElementById("instp"); if (!o) { o = document.createElement("div"); o.id = "instp"; document.body.appendChild(o); }
  const ios = /iphone|ipad|ipod/i.test(navigator.userAgent);
  o.innerHTML = `<div class="instbox" role="dialog" aria-modal="true" aria-label="Installera appen"><button class="instx" aria-label="Stäng">×</button><img src="icons/icon-192.png" alt="" class="insti"><h3>Installera appen</h3><p>Få EnergyWizard på hemskärmen: snabbare start, notiser och alltid senaste versionen.</p>${_instHelp ? `<div class="note" style="line-height:1.5">${ios ? "Tryck på Dela-knappen i Safari och välj Lägg till på hemskärmen." : "Öppna Chrome-menyn (tre prickar) och välj Installera app eller Lägg till på startskärmen."}</div>` : ""}<button class="btn instgo">Installera appen</button></div>`;
  o.querySelector(".instx").onclick = () => o.remove();
  o.querySelector(".instgo").onclick = async () => {
    if (installEvt) { try { installEvt.prompt(); const r = await installEvt.userChoice; if (r.outcome === "accepted") { LS.set("ew_installed", "1"); o.remove(); } } catch (e) {} installEvt = null; }
    else { _instHelp = true; drawInstallPrompt(); }
  };
}
function maybeInstallPrompt() {
  if (_instShown || isStandalone() || LS.get("ew_installed", "") === "1") return;
  _instShown = true;
  // Not on top of the login form: wait until signed in.
  const later = () => { if (isStandalone() || LS.get("ew_installed", "") === "1") return; if (document.getElementById("lf")) { setTimeout(later, 3000); return; } drawInstallPrompt(); };
  setTimeout(later, 1500);
}
window.addEventListener("beforeinstallprompt", () => { if (document.getElementById("instp")) setTimeout(drawInstallPrompt, 0); });
// ---- sponsring: länk i inställningarna + en vänlig ruta en gång i månaden till ägaren (kan stängas av) ----------------------------
const SPONSOR_URL = "https://github.com/sponsors/murre87";
let SPONSOR = null;
// Engångsruta om det nya utseendet (Emil 2026-11-13): den som använt appen före 1.2.73 får veta vad som ändrats och
// hur man byter tillbaka. Nya användare har inte sett det gamla och får ingen ruta. Texterna översätts (i18n).
function maybeStyleNotice() {
  if (LS.get("ew_style_notice", "") === "1") return;
  if (document.getElementById("lf")) { setTimeout(maybeStyleNotice, 4000); return; }      // vänta tills man loggat in
  const before = LS.get("ew_installed", "") || LS.get("ew_page", "") || LS.get("ew_theme", "") || LS.get("ew_primary", "");
  if (!before || LS.get("ew_style", "")) { LS.set("ew_style_notice", "1"); return; }      // ny användare, eller har redan valt stil
  const o = document.createElement("div"); o.id = "stylenote";
  o.innerHTML = `<div class="instbox" role="dialog" aria-modal="true" aria-labelledby="stylenote-h">
    <h3 id="stylenote-h">Appen har fått ett nytt utseende</h3>
    <p>Lugnare och lättare att läsa: färg bara där den betyder något, priset just nu överst och inga emoji i flödet. Allt finns kvar på samma ställe.</p>
    <p class="note">Vill du hellre ha det gamla utseendet: Inställningar → Appen → Stil → Klassisk. Du kan byta när du vill.</p>
    <button class="btn instgo" data-v="keep">Behåll det nya</button>
    <button class="mini" data-v="classic" style="width:100%;margin-top:8px">Byt till klassisk</button></div>`;
  document.body.appendChild(o);
  o.addEventListener("click", (e) => {
    const b = e.target.closest("[data-v]"); if (!b) return;
    if (b.dataset.v === "classic") { LS.set("ew_style", "classic"); applyLook(); render(); toast("Klassisk stil – ändra under Inställningar → Appen → Stil"); }
    LS.set("ew_style_notice", "1"); o.remove();
  });
}
setTimeout(maybeStyleNotice, 1500);
async function maybeSponsor() {
  if (document.getElementById("lf") || document.getElementById("instp") || document.getElementById("stylenote")) { setTimeout(maybeSponsor, 5000); return; }
  try { const r = await fetch("api/sponsor?lang=" + I18N.lang); if (!r.ok) return; SPONSOR = await r.json(); } catch (e) { return; }
  if (!SPONSOR.show) return;
  const o = document.createElement("div"); o.id = "sponsp"; document.body.appendChild(o);
  o.innerHTML = `<div class="instbox" role="dialog" aria-modal="true" data-noi18n><button class="instx" aria-label="×">×</button><div style="font-size:2rem">❤️</div><h3>${esc(SPONSOR.title)}</h3><p>${esc(SPONSOR.text)}</p><a class="instgo" href="${esc(SPONSOR.url)}" target="_blank" rel="noopener" style="display:block;text-align:center;text-decoration:none">${esc(SPONSOR.button)}</a></div>`;
  const close = () => { o.remove(); fetch("api/sponsor/dismiss", { method: "POST" }).catch(() => {}); };
  o.querySelector(".instx").onclick = close;
  o.querySelector(".instgo").addEventListener("click", close);
}
setTimeout(maybeSponsor, 6000);
maybeInstallPrompt();
start();
