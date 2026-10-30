// EnergyWizard Webdashboard - Fas A: inloggning + sidomeny-skal + en testgraf (bevisar
// ECharts-pipen). Ingen sida har riktigt innehåll än, bara "oversikt" med testgrafen.
let PAGES = [];
let currentPage = null;

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

function openPage(id) {
  currentPage = id;
  renderSidebar();
  const main = document.getElementById("main");
  if (id === "oversikt") {
    main.innerHTML = `<div class="grid">
      <div class="card"><h2>Testgraf (ECharts)</h2><div class="note">Bevisar att diagram-pipen fungerar - riktiga sidor byggs i Fas B.</div><div id="testchart" style="height:280px;margin-top:10px"></div></div>
    </div>`;
    api("/api/testgraf").then(d => {
      const chart = echarts.init(document.getElementById("testchart"), null, { renderer: "svg" });
      chart.setOption({
        grid: { left: 40, right: 16, top: 16, bottom: 28 },
        xAxis: { type: "category", data: d.hours, axisLine: { lineStyle: { color: "#93a0b8" } } },
        yAxis: { type: "value", axisLine: { lineStyle: { color: "#93a0b8" } }, splitLine: { lineStyle: { color: "rgba(255,255,255,.08)" } } },
        series: [{ type: "line", data: d.values, smooth: true, lineStyle: { color: "#22d3a0", width: 2 }, areaStyle: { color: "rgba(34,211,160,.15)" }, symbol: "none" }],
      });
      new ResizeObserver(() => chart.resize()).observe(document.getElementById("testchart"));
    });
  } else {
    main.innerHTML = `<div class="placeholder">"${PAGES.find(p => p.id === id)?.name}" byggs i en senare fas.</div>`;
  }
}

async function boot() {
  try {
    const me = await api("/api/me");
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
    await api("/api/login", { method: "POST", body: JSON.stringify({ user: document.getElementById("user").value, password: document.getElementById("pw").value }) });
    boot();
  } catch (e) { err.textContent = e.message || "Fel användarnamn eller lösenord"; }
};

document.getElementById("logoutbtn").onclick = async () => { await api("/api/logout", { method: "POST" }); showLogin(); };

boot();
