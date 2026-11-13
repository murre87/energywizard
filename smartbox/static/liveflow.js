/* liveflow.js - "Just nu": vad som ger och drar el, delad av webben (Översikt) och mobilappen (Hem).
 *
 * 2026-11-07 (Emil: appen och webben ska göra samma sak på samma sätt): förut ritades flödet en gång i varje
 * gränssnitt, med olika siffror och ord. Nu samma kod och samma regler i båda, bara storleken skiljer:
 *   - källorna (sol, nät, batteri) till vänster, huset i mitten, det som drar el till höger
 *   - varje ruta: namn, en stor siffra och ett statusord ("köper", "producerar", "laddar ur", "går" ...)
 *   - prickarna rör sig åt det håll elen går (in mot huset från källorna, ut från huset till förbrukarna)
 *   - värmepumpens w i datan är värmeeffekten (el × COP), inte vad den drar, så pump, varmvatten och spa visar
 *     temperaturen ur detaljen i stället för watt
 *
 * Data: api/flow (smartbox/live_flow.py). Användning:
 *   EWLiveFlow.svg(data, { compact: true|false, attrs: (node) => 'data-...', hubAttrs: 'data-...' })
 */
(function () {
  "use strict";
  const COL = { sol: "#fbbf24", nat: "#38bdf8", natut: "#22d3a0", batteri: "#2dd4bf", varmepump: "#fb923c", varmvatten: "#60a5fa", spabad: "#a78bfa", ev: "#22d3a0" };
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const f1 = (v) => (Math.round(v * 10) / 10).toFixed(1).replace(".", ",");

  function status(n) {
    const w = n.w || 0;
    if (n.key === "nat") return w < -50 ? "säljer" : w > 50 ? "köper" : "i balans";
    if (n.key === "sol") return w > 50 ? "producerar" : "vilar";
    if (n.key === "batteri") return w < -30 ? "laddar ur" : w > 30 ? "laddar" : "vilar";
    if (n.key.startsWith("ev_")) return n.active ? "laddar" : (n.detail || "").replace(/\s*·.*$/, "").toLowerCase() || "laddar inte";
    const parts = (n.detail || "").split("·").map((x) => x.trim()).filter(Boolean);
    if (parts.length > 1) return parts[0].toLowerCase();
    return n.active ? (n.key === "varmvatten" ? "värms" : "går") : "";
  }
  const showsPower = (n, isLeft) => isLeft || n.key.startsWith("ev_");
  const color = (n) => n.key === "nat" ? ((n.w || 0) < -50 ? COL.natut : COL.nat) : n.key.startsWith("ev_") ? COL.ev : (COL[n.key] || "#94a3b8");
  const inward = (n) => n.role === "source" || (n.role === "grid" && (n.w || 0) > 50) || (n.role === "battery" && (n.w || 0) < -30);

  function svg(d, opts) {
    opts = opts || {};
    if (!d || !d.nodes) return "";
    const c = !!opts.compact;
    // Geometri: appen (smal, läsbar text i mobilen) eller webben (bred)
    const G = c ? { W: 360, row: 42, minH: 160, LW: 116, LH: 50, RW: 116, RH: 36, hub: 38, fs: { lab: 12, big: 17, st: 10.5, rlab: 11, rbig: 13, rst: 10, unit: 11, hub: 12.5 }, maxRight: 5 }
                : { W: 960, row: 76, minH: 330, LW: 190, LH: 72, RW: 190, RH: 62, hub: 64, fs: { lab: 14, big: 22, st: 13, rlab: 14, rbig: 16, rst: 12.5, unit: 13, hub: 15 }, maxRight: 8 };
    const nodes = d.nodes.filter((n) => n.key !== "hus"), house = d.nodes.find((n) => n.key === "hus");
    const left = nodes.filter((n) => ["source", "grid", "battery"].includes(n.role)), right = nodes.filter((n) => n.role === "load").slice(0, G.maxRight);
    const rows = Math.max(left.length, right.length, 3), H = Math.max(G.minH, rows * G.row + 6), hub = { x: G.W / 2, y: H / 2 };
    const place = (arr, x, h) => arr.map((n, i) => ({ ...n, x, h, y: arr.length === 1 ? H / 2 : h / 2 + 4 + i * ((H - h - 8) / (arr.length - 1)) }));
    const all = [...place(left, 4, G.LH), ...place(right, G.W - G.RW - 4, G.RH)];
    const motion = !(window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches);
    const kw = (w) => w == null ? "–" : Math.abs(w) >= 1000 ? `${f1(Math.abs(w) / 1000)}<tspan font-size="${G.fs.unit}" font-weight="500"> kW</tspan>`
      : `${Math.round(Math.abs(w))}<tspan font-size="${G.fs.unit}" font-weight="500"> W</tspan>`;
    const pre = c ? "flc" : "flw";
    let paths = "", dots = "", cards = "";
    all.forEach((n, i) => {
      const isL = n.x < hub.x, w = isL ? G.LW : G.RW, sx = isL ? n.x + w : n.x, ex = isL ? hub.x - G.hub : hub.x + G.hub, col = color(n), id = `${pre}${i}`;
      paths += `<path id="${id}" d="M${sx} ${n.y.toFixed(1)} C${(sx + ex) / 2} ${n.y.toFixed(1)} ${(sx + ex) / 2} ${hub.y} ${ex} ${hub.y}" fill="none" stroke="${col}" stroke-width="${n.active ? (c ? 2 : 2.5) : 1.2}" stroke-dasharray="${n.active ? "0" : "2 5"}" opacity="${n.active ? .6 : .25}"/>`;
      if (n.active && motion) {
        const k = Math.abs(n.w || 1000) / 1000, dur = Math.max(0.8, 3.2 - k * 0.35).toFixed(2), cnt = k > 3 ? 3 : 2;
        for (let j = 0; j < cnt; j++) dots += `<circle r="${((c ? 2.6 : 3.5) + Math.min(2, k / 2)).toFixed(1)}" fill="${col}"><animateMotion dur="${dur}s" begin="${(-j * dur / cnt).toFixed(2)}s" repeatCount="indefinite" keyPoints="${inward(n) ? "0;1" : "1;0"}" keyTimes="0;1" calcMode="linear"><mpath href="#${id}"/></animateMotion></circle>`;
      }
      const big = showsPower(n, isL) ? kw(n.w) : esc((n.detail || "").split("·").pop().trim().replace(/^inne\s*/i, ""));
      const st = esc(status(n)).slice(0, c ? 14 : 22), at = opts.attrs ? opts.attrs(n) : "";
      const p = c ? 10 : 14;
      cards += `<g ${at} transform="translate(${n.x},${(n.y - n.h / 2).toFixed(1)})" style="cursor:pointer">
        <rect width="${w}" height="${n.h}" rx="${c ? 12 : 16}" fill="var(--card2, var(--card))" stroke="${n.active ? col : "var(--line)"}" stroke-width="${n.active ? 1.6 : 1}"/>`
        + (isL ? `<text x="${p}" y="${c ? 19 : 26}" font-size="${G.fs.lab}" fill="${col}" font-weight="700">${opts.icons === false ? "" : esc(n.icon) + " "}${esc(n.label)}</text>
        <text x="${p}" y="${c ? 41 : 55}" font-size="${G.fs.big}" font-weight="800" fill="var(--txt)">${kw(n.w)}</text>
        <text x="${w - p + 2}" y="${c ? 19 : 55}" font-size="${G.fs.st}" fill="var(--mut)" text-anchor="end">${st}</text>`
        : `<text x="${p - 1}" y="${c ? 15 : 24}" font-size="${G.fs.rlab}" fill="${n.active ? col : "var(--mut)"}" font-weight="700">${opts.icons === false ? "" : esc(n.icon) + " "}${esc(c ? n.label.split(" ")[0] : n.label)}</text>
        <text x="${p - 1}" y="${c ? 30 : 47}" font-size="${G.fs.rbig}" font-weight="700" fill="var(--txt)">${big}</text>
        <text x="${w - p + 3}" y="${c ? 30 : 47}" font-size="${G.fs.rst}" fill="var(--mut)" text-anchor="end">${st}</text>`) + `</g>`;
    });
    const hk = house && house.w != null ? f1(house.w / 1000) : "–", s = G.hub * 2;
    const hubSvg = `<g ${opts.hubAttrs || ""} style="cursor:pointer" transform="translate(${hub.x - G.hub},${hub.y - G.hub})"><rect width="${s}" height="${s}" rx="${c ? 18 : 26}" fill="var(--card2, var(--card))" stroke="var(--acc)" stroke-width="${c ? 1.6 : 2}"/>
      <path d="M${s * .32} ${s * .47} L${s / 2} ${s * .31} L${s * .68} ${s * .47} V${s * .68} H${s * .32} Z" fill="none" stroke="var(--acc)" stroke-width="${c ? 2 : 2.5}" stroke-linejoin="round"/>
      <text x="${s / 2}" y="${s * .9}" text-anchor="middle" font-size="${G.fs.hub}" font-weight="800" fill="var(--txt)">${hk} kW</text></g>`;
    return `<svg viewBox="0 0 ${G.W} ${H}" style="width:100%;height:auto;display:block${c ? "" : `;max-width:${G.W * 1.1}px;margin:0 auto`}" role="img" aria-label="Elen just nu">${paths}${dots}${hubSvg}${cards}</svg>`;
  }
  window.EWLiveFlow = { svg, status };
})();
