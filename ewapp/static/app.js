// EnergyWizard Mobil – fyra sidor (Bil, Hus, Schema, Grafer), ingen scrollning: allt får plats i skärmen. Poll medan sidan syns.
const $ = (s) => document.querySelector(s), app = $("#app");
const LS = { get: (k, d) => { try { return localStorage.getItem(k) ?? d; } catch { return d; } }, set: (k, v) => { try { localStorage.setItem(k, v); } catch {} } };
let LJ = null, VIEWAS = LS.get("ew_viewas", ""), GR = null, ME = "", ROLE = "owner", EN = null, S = null, H = null, page = LS.get("ew_page", "bil"), busy = false, timer = null, installEvt = null, SCH = null, schCar = "nissan", HIST = null, SET = null;
const esc = (x) => String(x ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const buzz = (n = 15) => { try { navigator.vibrate && navigator.vibrate(n); } catch {} };
// haptik: en liten vibration direkt när fingret nuddar en knapp (Android; iPhone saknar vibrations-API i webbläsaren, där ger tryckeffekten i CSS återkopplingen)
document.addEventListener("pointerdown", (e) => { if (e.pointerType !== "mouse" && e.target.closest("button, [data-a], [data-v], .tab, .sw")) buzz(8); }, { passive: true });
const f1 = (x, d = 1) => (x == null ? "–" : Number(x).toFixed(d).replace(".", window.I18N && I18N.lang === "en" ? "." : ","));
function toast(t, ms = 2600) { const e = $("#toast"); e.textContent = t; e.classList.add("show"); clearTimeout(toast.t); toast.t = setTimeout(() => e.classList.remove("show"), ms); }
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
  grafer: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20V4M4 20h16M8 16l4-5 3 3 5-7"/></svg>',
  gear: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/></svg>',
};
function showLogin(msg) {
  clearInterval(timer);
  app.innerHTML = `<form class="login card" id="lf"><div class="brand" style="justify-content:center"><span class="dot"></span>EnergyWizard</div><div class="note">Logga in för att styra hemmet.</div><input id="un" placeholder="Användarnamn (tomt = ägare)" autocomplete="username" autocapitalize="none"><input type="password" id="pw" placeholder="Lösenord" autocomplete="current-password" required><button class="big" type="submit">Logga in</button><div class="note" style="color:var(--bad)">${esc(msg || "")}</div></form>`;
  $("#lf").onsubmit = async (e) => { e.preventDefault(); try { await api("login", { user: $("#un").value, password: $("#pw").value }); start(); } catch (er) { showLogin(er.message); } };
}
const ER = () => (ROLE === "owner" && VIEWAS) ? VIEWAS : ROLE;                    // effektiv roll: ägaren kan förhandsgranska Elins vy och gästläget
const CAN = { family: ["theme", "ser", "refreshsoc", "installapp", "tab", "swap", "power", "start", "stop", "auto", "heat_on", "heat_off", "access", "cardata", "lights", "trip", "sch", "schcar", "schtime", "schclock", "rooms", "greet", "log", "health", "settings"],
              guest: ["theme", "ser", "tab", "health", "settings", "swap", "schcar", "cardata", "rooms", "greet", "log", "report"] };
const can = (a) => ER() === "owner" || (ROLE === "owner" && a === "viewas") || (CAN[ER()] || []).includes(a);   // ägaren kan alltid byta tillbaka från förhandsvisningen
const TABS = { owner: ["bil", "ljus", "hus", "energi", "schema", "grafer"], family: ["bil", "ljus", "schema"], guest: ["bil", "ljus", "hus", "energi", "schema", "grafer"] };
const TABNAME = { bil: "Bil", ljus: "Ljus", hus: "Hus", energi: "Energi", schema: "Schema", grafer: "Grafer" };
const primary = () => LS.get("ew_primary", "");
function chooseCar() {
  app.innerHTML = `<div class="card" style="text-align:center;display:grid;gap:14px;margin-top:10dvh"><h2 style="margin:0">Vilken bil kör du mest?</h2><div class="note">Den visas stor överst. Du kan byta senare.</div><button class="big" data-p="tesla">Tesla</button><button class="big" data-p="nissan" style="background:linear-gradient(135deg,#a5b4fc,#38bdf8)">Nissan</button></div>`;
  app.querySelectorAll("[data-p]").forEach((b) => b.onclick = () => { LS.set("ew_primary", b.dataset.p); start(); });
}
// ---- Bil -------------------------------------------------------------------------------------------------------------------------
function planText(c) {
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
  return { t: c.mode === "manual" ? "Väntar på start" : (p ? "Planerad: " + p : "Ingen laddning planerad") };
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
const planLink = (c, t) => (c.home && c.plan_all && c.plan_all.blocks && c.plan_all.blocks.length ? `<a class="plink" data-a="planlist" data-c="${c.key}" role="button" tabindex="0">${esc(t)} ›</a>` : esc(t));
function planSheet(key) {
  const c = S.cars.find((x) => x.key === key); if (!c) return;
  sheet(`<h3>Laddplan – ${esc(c.name)}</h3>${planList(c)}<button class="big" data-v="ok">Stäng</button>`);
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
  const chips = [`<span class="chip ${c.home ? "ok" : ""}">${c.home ? "Hemma" : "Borta" + (c.away && c.away.car_km_from_home != null ? ` · ${c.away.car_km_from_home} km hemifrån` : "")}</span>`, c.home ? `<span class="chip ${c.plugged ? "ok" : "warn"}">${c.plugged ? "Kabel i" : "Ingen kabel"}</span>` : "", staleChip(c), c.soc_stale ? `<span class="chip warn" title="Bilen svarar inte just nu – visar senast kända värden">Senast kända värde</span>` : "", heatChip(c), c.mode === "manual" ? `<span class="chip warn">Manuellt ${c.amps} A${c.phases ? " · " + c.phases + "-fas" : ""}</span>` : "", ...(c.facts || []).slice(0, 2).map((f) => `<span class="chip">${esc(f)}</span>`)].join("");
  return `<section class="card hero${c.climate_on ? " heating" : ""}"><div class="carname">${esc(c.name)} ${ER() === "family" ? "" : `<button class="link" data-a="cardata" data-c="${c.key}">Alla data</button>`}</div><div class="ring">${ring(c.soc, color)}<div class="pct" data-a="refreshsoc" data-c="${c.key}" title="Tryck för att uppdatera"><b>${c.soc == null ? "–" : c.soc}<small style="font-size:.45em">%</small></b><span>batteri</span></div></div>
  <div class="chips">${chips}</div><div class="stat">${planLink(c, si.t)}${c.away && c.away.km ? ` <span class="note">· ${c.away.km} km kvar</span>` : ""}</div>${c.home && c.plugged ? `<div class="note sunline${c.solar && c.solar.active ? " on" : ""}">${esc(solarText(c))}</div>` : ""}${c.home ? actions(c, true) : ""}
  <div class="chips">${c.home ? `<button class="mini" data-a="${c.climate_on ? "heat_off" : "heat_on"}" data-c="${c.key}">${c.climate_on ? "Stoppa värme" : "Starta värme"}</button>` : ""}${c.home && c.plugged ? `<button class="mini" data-a="power" data-c="${c.key}">Välj effekt</button>` : ""}${c.home && c.plugged ? `<button class="mini" data-a="trip" data-c="${c.key}">Resplan</button>` : ""}${c.mode !== "auto" ? `<button class="mini" data-a="auto" data-c="${c.key}">Auto</button>` : ""}${c.access ? `<button class="mini" data-a="access">${c.access.locked ? "Lås & luckor" : "Olåst · luckor"}</button>` : ""}</div></section>`;
}
function compact(c) {
  const si = statusInfo(c);
  return `<section class="card${c.climate_on ? " heating" : ""}"><div class="chead"><div class="cname">${esc(c.name)} ${ER() === "family" ? "" : `<button class="link" data-a="cardata" data-c="${c.key}">Alla data</button>`}</div><div class="csoc" data-a="refreshsoc" data-c="${c.key}" title="Tryck för att uppdatera">${c.soc ?? "–"}<small>%</small>${c.age_h != null && c.age_h > 2 ? `<small style="color:var(--warn);display:block;font-size:.62rem;font-weight:500">${ageTxt(c.age_h)} gammal</small>` : ""}</div></div><div class="bar"><i style="width:${c.soc ?? 0}%"></i></div>
  <div class="note compact-note" style="margin-bottom:8px">${esc(si.t)}${c.climate_on ? " · 🔥 värmen är på" : ""}</div><div class="crow">${c.home ? actions(c, false) : ""}${c.home ? `<button class="mini" data-a="${c.climate_on ? "heat_off" : "heat_on"}" data-c="${c.key}">${c.climate_on ? "Stoppa värme" : "Starta värme"}</button>` : ""}${c.mode !== "auto" ? `<button class="mini" data-a="auto" data-c="${c.key}">Auto</button>` : ""}${c.access ? `<button class="mini" data-a="access">Lås</button>` : ""}</div></section>`;
}
function priceCard(p) {
  if (!p || p.now == null) return "";
  const hs = p.hours || [], mx = Math.max(...hs.map((h) => h.p), 0.1), srt = hs.map((h) => h.p).sort((a, b) => a - b), lowT = srt[Math.floor(srt.length / 3)] ?? 0;
  return `<section class="card price"><div class="head"><div><span class="note">Elpris nu </span><span class="now">${f1(p.now, 2)} <small>kr/kWh</small></span></div><span class="chip ${p.level === "billigt" ? "ok" : p.level === "dyrt" ? "bad" : ""}">${esc(p.level || "")}</span></div>
  <div class="bars">${hs.map((h) => `<span class="${h.now ? "now" : h.p <= lowT ? "low" : ""}" style="height:${Math.max(10, (h.p / mx) * 100)}%"></span>`).join("")}</div><div class="hrs">${hs.map((h) => `<span>${h.t}</span>`).join("")}</div></section>`;
}
function pageBil() {
  if (!S) return `<div class="note" style="text-align:center;margin-top:20dvh">Laddar…</div>`;
  const p = primary(), main = S.cars.find((c) => c.key === p) || S.cars[0], other = S.cars.find((c) => c !== main), simple = LS.get("ew_simple", "") === "1";
  const carseg = `<div class="seg carseg">${S.cars.map((c) => `<button data-a="swap" data-c="${c.key}" class="${c.key === main.key ? "on" : ""}">${esc(c.name.split(" ")[0])} · ${c.soc ?? "–"} %</button>`).join("")}</div>`;
  return `<div class="page">${carseg}${hero(main)}${simple ? "" : compact(other) + priceCard(S.price)}</div>`;
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
  const h = H.heat, w = H.water, sp = H.spa, m = H.mower, pw = H.power;
  const pct = pw.limit_kw && pw.total_w != null ? Math.min(100, (pw.total_w / 1000 / pw.limit_kw) * 100) : 0;
  const mowerTxt = m.status ? `${esc(m.status)}${m.since ? ` · ${m.since}` : ""}` : "okänd";
  return `<div class="page"><div class="grid2">
  <section class="card tile"><h4>Värme inne <button class="link" data-a="rooms" style="padding:0 0 0 6px;font-size:.8rem">alla rum</button></h4><div class="v">${f1(h.inside)}<small> °C</small></div><div class="note">Mål ${f1(h.target)}° · ute ${f1(h.outside, 0)}° · pump ${h.pump_w != null ? Math.round(h.pump_w) : "–"} W</div>${seg("heat", h.mode, [["auto", "Auto"], ["on", "Varm"], ["off", "Sänkt"]])}</section>
  <section class="card tile"><h4>Varmvatten</h4><div class="v">${f1(w.temp, 0)}<small> °C</small></div><div class="note">COP ${f1(h.cop)}</div>${seg("hotwater", w.mode, [["auto", "Auto"], ["on", "Till"], ["off", "Från"]])}</section>
  <section class="card tile wide"><h4>Spabad</h4><div class="v">${f1(sp.temp)}<small> °C</small></div><div class="note">Mål ${f1(sp.target)}° · ${esc(sp.heater || "")}${sp.error && sp.error !== "None" ? ` · ${esc(sp.error)}` : ""}</div>
    <div class="tilelink"><button class="link" data-a="spaready" style="padding:0;font-size:.82rem">${sp.ready_at ? `Klart ${esc(sp.ready_at)} (${f1(sp.ready_temp)}°) – ändra` : "Ställ in: klart kl…"}</button></div><div class="seg"><button data-a="spa" data-k="spa_auto" data-v="1" class="${!sp.force_heat && !sp.eco ? "on" : ""}" title="Följer sitt eget schema, som Home Assistant styr">Auto</button><button data-a="spa" data-k="spa_heat" data-v="${sp.force_heat ? 0 : 1}" class="${sp.force_heat ? "on" : ""}">Värm nu</button><button data-a="spa" data-k="spa_eco" data-v="${sp.eco ? 0 : 1}" class="${sp.eco ? "on" : ""}">Eco</button></div></section>
  <section class="card tile wide"><div style="display:flex;justify-content:space-between;align-items:baseline"><h4>Effekt nu</h4><span class="note">${pw.peak ? `Effektvakt på · gräns ${f1(pw.limit_kw)} kW` : "Effektvakt av"}</span></div><div class="v">${pw.total_w != null ? f1(pw.total_w / 1000) : "–"}<small> kW</small></div>
    <div class="meter" ${pw.peak ? "" : 'style="opacity:.35"'}><i class="${pct > 85 ? "hi" : ""}" style="width:${pw.peak ? pct : 0}%"></i></div><div class="chips" style="justify-content:flex-start">${gridChip(pw)}${limitChip(pw)}<span class="chip">Elbil ${pw.ev_w != null ? f1(pw.ev_w / 1000) : "–"} kW</span><span class="chip ${pw.solar_w > 100 ? "ok" : ""}">Sol ${pw.solar_w != null ? f1(pw.solar_w / 1000) : "–"} kW</span><span class="chip ok">Sparat idag ${f1(pw.saving_today, 1)} kr</span></div></section>
  </div></div>`;
}
// ---- Ljus ------------------------------------------------------------------------------------------------------------------------
function pageLjus() {
  if (!LJ) return `<div class="note" style="text-align:center;margin-top:20dvh">Laddar…</div>`;
  const w = LJ.windows, u = LJ.up, off = (x) => (x.offline.length ? ` · offline: ${x.offline.map((n) => esc(n.replace("Fönsterlampa - ", ""))).join(", ")}` : "");
  return `<div class="page"><section class="card lj"><h4>Fönsterlampor</h4><div class="note">${w.on} av ${w.total} tända${off(w)}</div><div class="ljrow"><button class="lbig on" data-a="lights" data-v="windows_on">Tänd alla</button><button class="lbig" data-a="lights" data-v="windows_off">Släck alla</button></div></section>
  <section class="card lj"><h4>Uppe (som knappen i sovrummet)</h4><div class="note">Trapp, balkong och Esther · ${u.on} av ${u.total} tända${off(u)}</div><button class="lbig night" data-a="lights" data-v="goodnight">Godnatt – släck uppe</button><button class="mini wideb" data-a="lights" data-v="up_on">Tänd uppe</button></section></div>`;
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
// ---- Energi ----------------------------------------------------------------------------------------------------------------------
function pageEnergi() {
  if (!EN) return `<div class="note" style="text-align:center;margin-top:20dvh">Laddar…</div>`;
  const s = EN.solar, g = EN.grid, lim = s.limit_pct, net = g.net_w;
  const limTxt = lim == null ? "offline" : lim >= 99.5 ? "ingen begränsning" : `${Math.round(lim)} %`;
  return `<div class="page"><div class="grid2">
  <section class="card tile"><h4>Solel</h4>${sunViz(s.w, s.forecast_w)}<div class="v">${s.w != null ? f1(s.w / 1000) : "–"}<small> kW</small></div><div class="note">${esc(s.status || "")} · idag ${f1(s.today_kwh, 0)} kWh · prognos ${s.forecast_w != null ? f1(s.forecast_w / 1000) : "–"} kW</div><div class="note">Elbilar laddade på solel: ${EN.solar_ev_kwh != null ? f1(EN.solar_ev_kwh, 0) : "–"} kWh</div></section>
  <section class="card tile"><h4>Nät</h4>${gridViz(net)}<div class="v" style="font-size:1.45rem">${net == null ? "–" : net < -50 ? `Säljer ${f1(-net / 1000)} kW` : `Köper ${f1(Math.max(0, net) / 1000)} kW`}</div><div class="note">Spotpris nu ${g.price != null ? f1(g.price, 2) : "–"} kr/kWh${g.level ? " · " + esc(g.level) : ""}</div><div class="note">Sparat idag ${f1(EN.saving_today, 1)} kr · förbrukat ${EN.today_kwh != null ? f1(EN.today_kwh, 0) : "–"} kWh</div></section>
  <section class="card tile wide"><h4>SolarEdge – exportbegränsning</h4><div style="display:flex;justify-content:space-between;align-items:baseline"><div class="v" style="font-size:1.45rem">${limTxt}</div><span class="chip ${s.ai_limit ? "warn" : "ok"}">${s.ai_limit ? "AI begränsar nu" : "Auto"}</span></div>
    <div class="tilelink note">${s.ai_limit ? "Spotpriset är under gränsen, så AI:n begränsar exporten själv." : "AI:n sköter detta automatiskt: den begränsar exporten själv när spotpriset går under gränsen nedan. Knapparna är bara till för manuell överstyrning."}</div>
    <div class="seg">${[100, 75, 50, 25, 0].map((p) => `<button data-a="energy" data-k="limit" data-v="${p}" class="${lim != null && Math.round(lim) === p ? "on" : ""}" ${s.ai_limit || lim == null ? "disabled" : ""}>${p} %</button>`).join("")}</div>
    <div class="setrow" style="border:0"><span class="note">Begränsa export när spotpriset är under</span><div class="step"><button data-a="energy" data-k="floor" data-v="${(s.export_price_floor - 0.05).toFixed(2)}">−</button><span>${f1(s.export_price_floor, 2)}</span><button data-a="energy" data-k="floor" data-v="${(s.export_price_floor + 0.05).toFixed(2)}">+</button></div></div></section>
  <section class="card tile"><h4>Effekttoppar denna månad</h4>${EN.peaks.length ? EN.peaks.map((p) => `<div style="display:flex;justify-content:space-between"><b>${f1(p.kw)} kW</b><span class="note">${p.t}</span></div>`).join("") : '<div class="note">Ingen data</div>'}</section>
  <section class="card tile ins"><h4>Just nu <button class="link" data-a="report" style="padding:0 0 0 6px;font-size:.8rem">Veckorapport</button></h4><div class="insl">${(EN.insights || []).map((x) => `<div class="insr"><span>${x.i}</span><span>${esc(x.t)}</span></div>`).join("") || '<div class="note">Inget särskilt just nu.</div>'}</div><button class="link" data-a="aidecisions" style="padding:0;font-size:.8rem;text-align:left">Visa alla AI-beslut</button></section>
  </div></div>`;
}
// ---- Schema ----------------------------------------------------------------------------------------------------------------------
const DAYS = ["Mån", "Tis", "Ons", "Tor", "Fre", "Lör", "Sön"];
function pageSchema() {
  if (!SCH) return `<div class="note" style="text-align:center;margin-top:20dvh">Laddar…</div>`;
  const s = SCH[schCar];
  return `<div class="page"><div class="seg"><button data-a="schcar" data-v="nissan" class="${schCar === "nissan" ? "on" : ""}">Nissan</button><button data-a="schcar" data-v="tesla" class="${schCar === "tesla" ? "on" : ""}">Tesla</button></div>
  <div class="note" style="text-align:center">Klar till vald tid och batterinivå. Av = laddar bara enligt pris/Auto.</div>
  <div class="sched">${DAYS.map((d, i) => { const x = s[i]; return `<div class="card srow"><b>${d}</b><button class="sw ${x.enabled ? "on" : ""}" data-a="sch" data-d="${i}" data-f="enabled" aria-label="${d} på/av"></button><button class="tm" data-a="schclock" data-d="${i}" aria-label="${d} klar kl"><span>${x.time}</span></button><div class="step"><button data-a="sch" data-d="${i}" data-f="soc-">−</button><span>${x.soc}%</span><button data-a="sch" data-d="${i}" data-f="soc+">+</button></div></div>`; }).join("")}</div></div>`;
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
  const paths = series.map((s, k) => { if (!vis[k]) return ""; let d = ""; s.forEach((v, i) => { if (v != null) d += (d ? "L" : "M") + X(i).toFixed(1) + " " + Y(v).toFixed(1); }); return `<path d="${d}" fill="none" stroke="${colors[k]}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`; }).join("");
  const last = series.map((s, k) => vis[k] ? [...s].reverse().find((v) => v != null) : null);
  return `<section class="card chart"><div class="ch"><b style="color:var(--txt)">${title}</b><span>${last.map((v, k) => v == null ? "" : `<span style="color:${colors[k]}">${f1(v, unit === "kr" ? 2 : 1)}</span>`).filter(Boolean).join(" · ")} ${unit}</span></div>${legend}<svg viewBox="0 0 ${W} ${Hh}" preserveAspectRatio="none">${paths}</svg><div class="ch"><span>${labels[0] ?? ""}:00</span><span>min ${f1(mn, 1)} · max ${f1(mx, 1)}</span><span>${labels[n - 1] ?? ""}:00</span></div></section>`;
}
function pageGrafer() {
  if (!HIST) return `<div class="note" style="text-align:center;margin-top:20dvh">Laddar…</div>`;
  const h = HIST;
  return `<div class="page"><div class="charts">${chart("Effekt hus", "kW", [h.total_kw, h.pump_kw, h.spa_kw, h.ev_kw, h.solar_kw], h.t, ["var(--txt)", "#fb923c", "#a78bfa", "var(--acc)", "var(--warn)"], ["Hus totalt", "Värmepump", "Spabad", "Elbilar", "Solproduktion"], "effekt")}${chart("Temperatur inne / ute", "°C", [h.indoor, h.outdoor], h.t, ["var(--warn)", "var(--mut)"], ["Inne", "Ute"], "temp")}${chart("Elpris", "kr", [h.price], h.t, ["var(--acc)"], ["Spotpris kr/kWh"], "pris")}</div></div>`;
}
// ---- ram, render, laddning ----------------------------------------------------------------------------------------------------------
function render() {
  if (page === "bil" && !primary() && S) return chooseCar();
  const warn = S && S.health && S.health.length;
  if (!TABS[ER()].includes(page)) page = "bil";
  const body = { bil: pageBil, ljus: pageLjus, hus: pageHus, energi: pageEnergi, schema: pageSchema, grafer: pageGrafer }[page]();
  const ok = S ? S.ok : true;
  const tabs = TABS[ER()].map((k) => [k, TABNAME[k]]);
  app.innerHTML = `<div class="top"><div class="greet" data-a="greet"><b><span class="dot ${ok ? "" : "off"}"></span>${esc(GR ? GR.hello : "EnergyWizard")}</b>${GR ? `<span class="gl">${esc([GR.weather, GR.line].filter(Boolean).join(" · "))}</span>` : ""}${S && S.version && S.version !== "dev" && S.version !== "local" ? `<span class="ver" title="Du kör senaste versionen">v${esc(S.version)} ✓ senaste</span>` : ""}</div><div class="tools"><button class="icobtn" data-a="theme" aria-label="Byt tema">${themeIcon()}</button>${warn ? `<button class="icobtn warn" data-a="health">⚠ ${S.health.length}</button>` : ""}<button class="icobtn" data-a="settings" aria-label="Inställningar">${ICON.gear}</button></div></div>${ROLE === "owner" && VIEWAS ? `<button class="vastrip" data-a="viewas" data-v="">Visar som ${VIEWAS === "family" ? "Elin" : "gäst"} · tryck för att avsluta</button>` : ER() === "guest" ? `<div class="vastrip">Gästläge · bara titta</div>` : ""}${needInstall() && page === "bil" ? `<button class="installbar" data-a="installapp"><b>Installera som app</b><span>${installEvt ? "Ett tryck" : "Så gör du"}</span></button>` : ""}${body}`;
  let tb = $("#tabs"); if (!tb) { tb = document.createElement("nav"); tb.id = "tabs"; tb.className = "tabs"; document.body.insertBefore(tb, $("#toast")); }
  tb.style.setProperty("--ntabs", tabs.length);
  tb.innerHTML = tabs.map(([k, l]) => `<button class="tab ${page === k ? "on" : ""}" data-a="tab" data-v="${k}">${ICON[k]}<span>${l}</span></button>`).join("");
  fit();
}
function overflows(pg) {
  const r = pg.getBoundingClientRect(); if (pg.scrollHeight > pg.clientHeight + 1) return true;
  return [...pg.children].some((k) => k.getBoundingClientRect().bottom > r.bottom + 1 || k.scrollHeight > k.clientHeight + 1) || [...pg.querySelectorAll(".card")].some((k) => k.scrollHeight > k.clientHeight + 1);
}
function fit() {                                           // krymper innehållet steg för steg tills inget sticker ut eller överlappar (stora typsnitt, små skärmar)
  const pg = document.querySelector(".page"); if (!pg) return;
  pg.classList.remove("t1", "t2", "t3", "t4");
  for (let l = 1; l <= 4 && overflows(pg); l++) pg.classList.add("t" + l);
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
function runShortcut() {                              // genvägar från ikonens långtryck: ./?do=goodnight, windows_on, windows_off, tesla_start, nissan_start
  const q = new URLSearchParams(location.search).get("do"); if (!q) return; history.replaceState(null, "", location.pathname);
  if (["windows_on", "windows_off", "goodnight"].includes(q) && can("lights")) { api("lights", { action: q }).then((r) => toast(r.msg)).catch((e) => toast(e.message)); return; }
  const m = /^(tesla|nissan)_start$/.exec(q); if (m && can("start")) { const nm = m[1] === "tesla" ? "Teslan" : "Nissan"; sheet(`<h3>Ladda ${nm} nu?</h3><div class="note">Startar laddning direkt, oavsett schema.</div><button class="big" data-x="ok">Ja, ladda</button><button class="mini" data-x="no">Avbryt</button>`); $("#sheet").onclick = (e) => { const b = e.target.closest("[data-x]"); if (!b) { if (e.target.id === "sheet") closeSheet(); return; } closeSheet(); if (b.dataset.x === "ok") act(m[1], "start"); }; }
}
async function loadGreeting() { if (Date.now() - grAt < 120000) return; grAt = Date.now(); try { GR = await api("greeting?lang=" + I18N.lang + (ROLE === "owner" && VIEWAS ? "&as=" + VIEWAS : "")); render(); } catch {} }
async function load() {
  try {
    if (page === "bil") S = await api("state"); else if (!S) S = await api("state");
    ROLE = (S && S.role) || ROLE; ME = (S && S.user) || ME; document.body.classList.toggle("guest", ROLE === "guest");
    if (page === "hus") H = await api("home");
    if (page === "energi") EN = await api("energy");
    if (page === "ljus") LJ = await api("lights");
    if (page === "schema" && !SCH) SCH = await api("schedule");
    if (page === "grafer" && !HIST) HIST = await api("history?hours=24");
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
  const draw = () => sheet(`<h3>Välj laddeffekt – ${esc(c.name)}</h3><div class="seg">${[6, 10, 16].map((a) => `<button data-v="a${a}" class="${amps === a ? "on" : ""}">${a} A</button>`).join("")}</div>${c.default_phases === 3 ? `<div class="seg">${[1, 3].map((f) => `<button data-v="p${f}" class="${ph === f ? "on" : ""}">${f}-fas</button>`).join("")}</div>` : `<div class="note">Nissan laddar på 1-fas.</div>`}<div class="note">≈ ${f1((amps * 230 * (c.default_phases === 3 ? ph : 1)) / 1000)} kW</div><button class="big" data-v="go">Starta laddning</button>`);
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
  ${rows.map((r) => `<div class="setrow"><span>${r.valid ? "✓" : "⚠"} ${esc(r.name.replace(/^(Tesla MY|Leaf|Nissan) ?/i, ""))}</span><span class="note" style="text-align:right;${r.valid ? "" : "color:var(--warn)"}">${esc(r.state)} ${esc(r.unit)}${r.why ? ` · ${esc(r.why)}` : ""}</span></div>`).join("")}
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
  sheet(`<h3>Veckorapport (7 dygn)</h3><div class="note">Förbrukning ${f1(t.use, 0)} kWh · sol ${f1(t.sun, 0)} kWh · elbil ${f1(t.ev, 0)} kWh · spotkostnad ca ${f1(t.cost, 0)} kr · snittpris ${f1(t.price, 2)} kr/kWh</div>
  <div class="setrow note"><b style="flex:1">Dag</b><b style="width:56px;text-align:right">Förbr.</b><b style="width:48px;text-align:right">Sol</b><b style="width:48px;text-align:right">Bil</b><b style="width:48px;text-align:right">kr</b></div>
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
function accessSheet() {
  const c = S.cars.find((x) => x.key === "tesla"); if (!c || !c.access) return; const a = c.access;
  sheet(`<h3>Tesla – lås & luckor</h3><div class="note">Bilen är ${a.locked ? "<b>låst</b>" : "<b style='color:var(--warn)'>upplåst</b>"}. Upplåsning och luckor kräver lösenordet (gäller i 10 min).</div><div class="seg"><button data-x="${a.locked ? "unlock" : "lock"}">${a.locked ? "Lås upp" : "Lås"}</button></div><div class="seg"><button data-x="trunk">${a.trunk ? "Stäng baklucka" : "Öppna baklucka"}</button><button data-x="frunk">${a.frunk ? "Stäng framlucka" : "Öppna framlucka"}</button></div>`);
  $("#sheet").onclick = async (e) => { const b = e.target.closest("[data-x]"); if (!b) { if (e.target.id === "sheet") closeSheet(); return; } closeSheet(); await access(b.dataset.x); };
}
async function access(what) {
  if (busy) return; busy = true; buzz(30);
  try { let r; try { r = await api("tesla/access", { what }); } catch (e) { if (e.message !== "secure") throw e; busy = false; return askPassword(what); } toast(r.msg); setTimeout(async () => { try { S = await api("state"); if (!sheetOpen()) render(); } catch {} }, 4000); }
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
async function settingsSheet() {
  if (!SET) { try { SET = await api("settings"); } catch (e) { return toast(e.message); } }
  const v = SET.values, R = SET.rules, off = (k) => k === "power_limit_kw" && !v.peak_shaving_enabled, row = (k, label, unit) => { const r = R[k]; return `<div class="setrow${off(k) ? " dim" : ""}"${off(k) ? ' title="Gäller bara när effektvakten är på"' : ""}><span>${label}${off(k) ? ' <span class="note">(effektvakt av)</span>' : ""}</span>${r[0] === "bool" ? `<button class="sw ${v[k] ? "on" : ""}" data-set="${k}" data-bool="1"></button>` : `<div class="step"><button data-set="${k}" data-d="-${r[3]}" ${off(k) ? "disabled" : ""}>−</button><span>${f1(v[k], r[3] < 1 ? 1 : 0)}${unit}</span><button data-set="${k}" data-d="${r[3]}" ${off(k) ? "disabled" : ""}>+</button></div>`}</div>`; };
  const standalone = window.matchMedia("(display-mode: standalone)").matches || navigator.standalone;
  const owner = ER() === "owner", secs = [...(owner ? [["effekt", "Effekt"], ["notiser", "Notiser"]] : []), ["appen", "Appen"], ["konto", "Konto"]];
  if (!secs.some(([s]) => s === setSec)) setSec = secs[0][0];
  const tabs = `<div class="seg segtabs">${secs.map(([s, l]) => `<button data-s="sec:${s}" class="${setSec === s ? "on" : ""}">${l}</button>`).join("")}</div>`;
  const body = {
    effekt: () => `${row("peak_shaving_enabled", "Effektvakt (peak shaving)")}${row("power_limit_kw", "Effektgräns", " kW")}${row("fuse_size_a", "Huvudsäkring", " A")}${row("temp_cheap", "Värmare vid billig el", "°")}${row("temp_expensive", "Sänkt värme vid dyr el", "°")}${row("spa_normal_temp", "Spabad normal", "°")}`,
    notiser: () => `${row("notify_spa_ready", "Avisera: spabadet klart")}${row("notify_ev_start", "Avisera: elbil startar")}${row("notify_washer_start", "Avisera: tvätt startar")}${row("notify_spa_open", "Avisera: spalocket öppet")}`,
    appen: () => `<div class="seg"><button data-s="tesla" class="${primary() === "tesla" ? "on" : ""}">Huvudbil: Tesla</button><button data-s="nissan" class="${primary() === "nissan" ? "on" : ""}">Huvudbil: Nissan</button></div><div class="seg"><button data-s="glass" class="${LS.get("ew_glass", "1") !== "0" ? "on" : ""}">Glasdesign</button><button data-s="ambient" class="${LS.get("ew_ambient", "1") !== "0" ? "on" : ""}">Dygnsfärger</button></div><div class="seg"><button data-s="simple" class="${LS.get("ew_simple", "") === "1" ? "on" : ""}">Enkel vy (bara huvudbilen)</button>${standalone ? "" : `<button data-s="install">${installEvt ? "Installera appen" : "Lägg till på hemskärmen"}</button>`}</div><div class="seg"><button data-s="reload">Ladda om appen</button></div>`,
    konto: () => `${ROLE === "owner" ? `<div class="seg"><button data-a="viewas" data-v="" class="${!VIEWAS ? "on" : ""}">Jag (admin)</button><button data-a="viewas" data-v="family" class="${VIEWAS === "family" ? "on" : ""}">Visa som Elin</button><button data-a="viewas" data-v="guest" class="${VIEWAS === "guest" ? "on" : ""}">Visa som gäst</button></div>` : ""}${ER() !== "owner" ? `<div class="note">${ER() === "guest" ? "Gästläge: du kan titta på allt men inte ändra." : "Dina inställningar är bara bil, schema och ljus."}</div>` : ""}<button class="mini" data-a="log">Visa familjelogg</button><div class="note" style="text-align:center">Inloggad som ${esc(ME === "owner" ? "ägare" : ME)}</div><div class="seg"><button data-s="logout">Logga ut</button></div>`,
  }[setSec]();
  sheet(`<h3>Inställningar</h3>${tabs}${body}`);
  $("#sheet").onclick = async (e) => {
    if (e.target.id === "sheet") return closeSheet();
    const x = e.target.closest("[data-set]");
    if (x) { const k = x.dataset.set; let val; if (x.dataset.bool) val = !SET.values[k]; else { const r = SET.rules[k]; val = Math.round((SET.values[k] + parseFloat(x.dataset.d)) / r[3]) * r[3]; val = Math.max(r[1], Math.min(r[2], val)); } try { const r = await api("settings", { key: k, value: val }); SET.values[k] = r.value; settingsSheet(); } catch (er) { toast(er.message); } return; }
    const y = e.target.closest("[data-s]"); if (!y) return; const s = y.dataset.s;
    if (s.startsWith("sec:")) { setSec = s.slice(4); settingsSheet(); return; }
    if (s.startsWith("lang:")) { I18N.set(s.slice(5)); return; }
    if (s === "glass" || s === "ambient") { LS.set("ew_" + s, LS.get("ew_" + s, "1") !== "0" ? "0" : "1"); applyLook(); }
    if (s === "tesla" || s === "nissan") LS.set("ew_primary", s); if (s === "simple") LS.set("ew_simple", LS.get("ew_simple", "") === "1" ? "" : "1");
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
document.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-a]"); if (!b || b.disabled) return;
  const a = b.dataset.a, c = b.dataset.c, v = b.dataset.v;
  if (!can(a)) { toast(ER() === "guest" ? "Gästläge – du kan bara titta" : "Det här kan bara administratören ändra"); return; }
  if (a === "tab") { if (v !== page) { try { history.pushState({ page: v }, ""); } catch (e) {} } page = v; LS.set("ew_page", v); render(); return load(); }
  if (a === "planlist") return planSheet(c);
  if (a === "power") return powerSheet(c);
  if (a === "swap") { LS.set("ew_primary", c); return render(); }
  if (a === "settings") return settingsSheet();
  if (a === "health") return healthSheet();
  if (a === "access") return accessSheet();
  if (a === "cardata") return carDataSheet(c);
  if (a === "home") { buzz(); try { const r = await api("home/" + b.dataset.k, { value: v }); toast(r.msg); H = await api("home"); render(); } catch (er) { toast(er.message); } return; }
  if (a === "spa") { buzz(); try { const r = await api("home/" + b.dataset.k, { value: v === "1" }); toast(r.msg); H = await api("home"); render(); } catch (er) { toast(er.message); } return; }
  if (a === "mower") { buzz(); try { const r = await api("home/mower", { value: v }); toast(r.msg); setTimeout(async () => { try { H = await api("home"); render(); } catch {} }, 1500); } catch (er) { toast(er.message); } return; }
  if (a === "energy" && b.dataset.k === "limit" && +v < 100 && !b.dataset.ok) {      // 0–75 % stryper solelen: kräver bekräftelse så att det inte sker av misstag
    sheet(`<h3>Begränsa solelen till ${v} %?</h3><div class="note">Exporten och solproduktionen begränsas tills du väljer 100 % igen. AI:n släpper begränsningen själv bara vid minuspris.</div><button class="big stop" data-x="ok">Ja, begränsa till ${v} %</button><button class="mini" data-x="no">Avbryt</button>`);
    $("#sheet").onclick = (e) => { const x = e.target.closest("[data-x]"); if (e.target.id === "sheet" || (x && x.dataset.x === "no")) return closeSheet(); if (x) { closeSheet(); b.dataset.ok = "1"; b.click(); delete b.dataset.ok; } };
    return;
  }
  if (a === "energy") { buzz(); try { const r = await api("energy/" + b.dataset.k, { value: b.dataset.k === "floor" ? parseFloat(v) : (b.dataset.k === "notify" ? v === "1" : v) }); toast(r.msg); EN = await api("energy"); render(); } catch (er) { toast(er.message); } return; }
  if (a === "rooms") return roomsSheet();
  if (a === "refreshsoc") { buzz(20); toast("Uppdaterar bilens data…", 6000); try { await api(`car/${c}/press`, { button: "refresh" }); } catch (er) { toast("⚠ " + er.message, 5000); return; } [3000, 8000, 20000].forEach((ms) => setTimeout(async () => { try { S = await api("state"); render(); if (ms === 8000) toast("Uppdaterat", 2000); } catch {} }, ms)); return; }
  if (a === "aidecisions") { sheet(`<h3>AI-beslut just nu</h3><div class="note" style="white-space:pre-wrap;max-height:60vh;overflow:auto">${esc(EN.log || EN.decision || "–")}</div>`); return; }
  if (a === "installapp") { installApp(); return; }
  if (a === "theme") { cycleTheme(); return; }
  if (a === "ser") { const [ck, ix] = v.split(":"); const h = hiddenSer(ck), n = +ix; LS.set("ew_hide_" + ck, (h.includes(n) ? h.filter((x) => x !== n) : [...h, n]).join(",")); render(); return; }
  if (a === "schclock") { schClockSheet(+b.dataset.d); return; }
  if (a === "lights") { buzz(25); try { const r = await api("lights", { action: v }); toast(r.msg); LJ = await api("lights"); render(); } catch (er) { toast(er.message); } return; }
  if (a === "viewas") { VIEWAS = v; LS.set("ew_viewas", v); grAt = 0; closeSheet(); loadGreeting(); return; }
  if (a === "trip") return tripSheet(c);
  if (a === "report") return reportSheet();
  if (a === "spaready") return spaReadySheet();
  if (a === "log") return logSheet();
  if (a === "greet" && GR) return sheet(`<h3>${esc(GR.hello)}</h3><div class="note">${esc(GR.weather)}</div><div style="font-size:1.1rem;font-weight:600">${esc(GR.line)}</div>`);
  if (a === "schcar") { schCar = v; return render(); }
  if (a === "sch") { const d = +b.dataset.d, x = SCH[schCar][d], f = b.dataset.f; buzz(8); if (f === "enabled") x.enabled = !x.enabled; else if (f === "soc+") x.soc = Math.min(100, x.soc + 5); else if (f === "soc-") x.soc = Math.max(20, x.soc - 5); render(); return schedSave(schCar, d); }
  if (["start", "stop", "auto", "heat_on", "heat_off"].includes(a)) return act(c, a);
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
window.addEventListener("unhandledrejection", (e) => reportErr("promise: " + (e.reason && e.reason.message || e.reason), ""));
function scaleFix() {                       // Chrome i "Datoranpassad webbplats" ger telefonen en 980 px bred vy: skala upp gränssnittet så det ser ut som på en telefon (inte som en liten kolumn)
  const de = document.documentElement, desk = matchMedia("(pointer: coarse)").matches && innerWidth >= 900;
  if (desk) { const z = innerWidth / 430; de.style.zoom = z; de.style.setProperty("--u", innerHeight / z / 100 + "px"); }
  else { de.style.zoom = ""; de.style.setProperty("--u", (window.visualViewport ? visualViewport.height : innerHeight) / 100 + "px"); }      // mäts i stället för dvh: efter väckning från bakgrunden kan dvh vara fel en stund, och då hamnar menyn utanför skärmen
}
// Utseende: glasdesign (frostat glas) och dygnsfärger (bakgrunden följer morgon/dag/kväll/natt). Båda valfria; ?look=glass,ambient,evening visar en förhandsvisning utan att spara.
const todOf = (h) => (h >= 5 && h < 10 ? "morning" : h >= 10 && h < 16 ? "day" : h >= 16 && h < 21 ? "evening" : "night");
function applyLook() {
  const de = document.documentElement, q = new URLSearchParams(location.search).get("look") || "", pv = q.split(",");
  const glass = pv.includes("glass") || (q === "" && LS.get("ew_glass", "1") !== "0"), amb = pv.includes("ambient") || (q === "" && LS.get("ew_ambient", "1") !== "0");      // båda på som standard; "0" = avstängd av användaren
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
maybeInstallPrompt();
start();
