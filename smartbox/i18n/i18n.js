// EnergyWizard: språkstöd för webben och mobilappen.
//
// Gränssnitten skrivs på svenska. När ett annat språk är valt översätts texten i webbläsaren
// efter att den ritats, med ordlistan i i18n/<språk>.json ({"svensk text": "översättning"}).
// Siffror i texten byts mot # i nyckeln, så "Laddar 3,7 kW" hittar "Laddar # kW". Saknas en
// översättning visas svenskan, och texten sparas i en lista som kan laddas ner i inställningarna
// (I18N.missing()) - så blir det lätt att hjälpa till att översätta. Se TRANSLATING.md.
(function () {
  const here = (document.currentScript && document.currentScript.src) || "";
  const BASE = here ? here.replace(/i18n\.js(\?.*)?$/, "") : "i18n/";
  const LS_KEY = "ew_lang";
  const localPref = () => { try { return localStorage.getItem(LS_KEY) || ""; } catch (e) { return ""; } };

  let lang = localPref() || "sv";
  let dict = {};
  let languages = { sv: "Svenska", en: "English" };
  let serverDefault = "sv";
  const missingSet = new Set();

  const NUM = /\d+(?:[.,]\d+)?/g;
  const LEAD = /^[\s\p{Extended_Pictographic}\p{S}\p{P}️‍]+/u;
  const TRAIL = /[\s:.…!?,;)\]]+$/u;
  const LOOKS_SV = /[åäöÅÄÖ]|\b(och|inte|för|att|är|på|till|med|eller|när|kvar|idag|imorgon|ladda\w*|batteri\w*|elpris\w*|timm\w*|värme\w*|spara\w*)\b/i;

  // Meningar med namn eller fri text i, som inte går att slå upp ord för ord.
  const RULES = [
    [/^Använd effektsensorn (.+)$/, (m) => "Use power sensor " + m[1]],
    [/^Smartmätare: (.+)$/, (m) => "Smart meter: " + m[1].replace("okänt märke", "unknown brand")],
    [/^hittades \((.+)\)$/, (m) => "found (" + m[1].replace("okänt märke", "unknown brand") + ")"],
    [/^(Effekt|Dagsenergi|Kabel|Klimat): (.+)$/, (m) => ({ Effekt: "Power", Dagsenergi: "Today's energy", Kabel: "Cable", Klimat: "Climate" })[m[1]] + ": " + m[2]],
    [/^Laddningen av (.+) har startat med (.+) kW$/, (m) => "Charging " + m[1] + " started at " + m[2] + " kW"],
    [/^Laddningen av (.+) har avslutats$/, (m) => "Charging " + m[1] + " has finished"],
    [/^(.+) svarar inte$/, (m) => m[1] + " is not responding"],
    [/^God (morgon|natt|kväll), (.+)!$/, (m) => ({ morgon: "Good morning", natt: "Good night", "kväll": "Good evening" })[m[1]] + ", " + m[2] + "!"],
    [/^Hej, (.+)!$/, (m) => "Hello, " + m[1] + "!"],
    [/^Inloggad som (.+)$/, (m) => "Logged in as " + (m[1] === "ägare" ? "owner" : m[1])],
    [/^Visar som (.+)$/, (m) => "Viewing as " + (m[1] === "gäst" ? "guest" : m[1])],
    [/^Kopplat till (.+)\.$/, (m) => "Connected to " + m[1] + "."],
    [/^Kontakt med Home Assistant på (.+)\.$/, (m) => "Connected to Home Assistant at " + m[1] + "."],
    [/^Fick inget svar från (.+)\. Stämmer adressen, och når servern Home Assistant\?$/, (m) => "No answer from " + m[1] + ". Is the address right, and can the server reach Home Assistant?"],
    [/^Oväntat svar från (.+) \((\d+)\)\. Är det rätt adress till Home Assistant\?$/, (m) => "Unexpected answer from " + m[1] + " (" + m[2] + "). Is it the right address for Home Assistant?"],
    [/^Kunde inte prata krypterat med (.+)\. Prova http:\/\/ i stället\.$/, (m) => "Could not talk encrypted with " + m[1] + ". Try http:// instead."],
    [/^(.+) har varit onåbar i över (\d+) minuter$/, (m) => m[1] + " has been unreachable for over " + m[2] + " minutes"],
    [/^(.+) är fulladdad$/, (m) => m[1] + " is fully charged"],
    [/^(.+): kabeln lossnade$/, (m) => m[1] + ": the cable was unplugged"],
    [/^(.+) har saknat värde i över (\d+) minuter$/, (m) => m[1] + " has had no value for over " + m[2] + " minutes"],
    [/^Första telefonen i Home Assistant \((.+)\)?$/, (m) => "First phone in Home Assistant (" + m[1] + ")"],
    [/^till ((?:notify\.|script\.|mobile_app_)\S+)$/, (m) => "to " + m[1]],
    [/^Härnäst (.+?): (.+) laddar$/, (m) => "Next " + m[1] + ": " + m[2] + " charging"],
    [/^Just nu: (.+)\. Härnäst (.+?): (.+) laddar$/, (m) => "Right now: " + (tr(m[1]) || m[1]).toLowerCase() + ". Next " + m[2] + ": " + m[3] + " charging"],
    [/^förinställning (.+)$/, (m) => "preset " + m[1]],
    [/^Växelriktaren svarar inte \(FTW-drivrutinen (.+)$/, (m) => "The inverter doesn't answer (FTW driver " + m[1]],
    [/^GPS: (.+) närmar sig hemmet! \(Avstånd: (.+?) km(\)?)$/, (m) => "GPS: " + m[1] + " is approaching home! (Distance: " + m[2] + " km" + m[3]],
    [/^Hittade befintligt framtida schema för (.+)$/, (m) => "Found an existing future schedule for " + m[1]],
    [/^(\S+(?: \S+){0,2}) frånkopplad$/, (m) => m[1] + " disconnected"],
    [/^Senast kända batterinivåer inlästa: (.+)$/, (m) => "Last known battery levels loaded: " + m[1]],
    [/^Sätter (.+)$/, (m) => "Setting " + m[1]],
    [/^Prio (\d+) \(BATTERISKYDD\): (.+) måste ladda (\d+) min i sträck för att skydda kontaktorerna$/, (m) => "Prio " + m[1] + " (BATTERY PROTECTION): " + m[2] + " must charge " + m[3] + " min in a row to protect the contactors"],
    [/^Tvingar fram (\d+)A$/, (m) => "Forcing " + m[1] + "A"],
    [/^Klimat: (\S+) satt till (\S+) \((.+?)°C(\)?)$/, (m) => "Climate: " + m[1] + " set to " + m[2] + " (" + m[3] + "°C" + m[4]],
    [/^Notis → ([^:]+): (.+)$/, (m) => "Notification → " + m[1] + ": " + m[2]],
    [/^(\S+(?: \S+){0,2}) laddar$/, (m) => m[1] + " charging"],              // bilnamn (högst tre ord)
  ];

  function fill(text, nums) {
    let i = 0;
    return text.replace(/#/g, () => {
      const n = nums[i++];
      if (n == null) return "#";
      return lang === "sv" ? n : n.replace(/(\d),(\d)/, "$1.$2");
    });
  }

  // Named values complement numeric #: translators can reorder names, currencies and addresses.
  // Only catalog-declared, anchored templates are matched; captured values remain unchanged.
  const templateCache = new WeakMap();
  function namedLookup(core) {
    let templates = templateCache.get(dict);
    if (!templates) {
      templates = [];
      const token = /\{([a-z][a-z0-9_]*)\}/gi;
      const escape = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      for (const [key, value] of Object.entries(dict)) {
        if (typeof value !== "string" || !value || key.startsWith("_")) continue;
        const parts = [...key.matchAll(token)];
        if (!parts.length || parts.length > 8 || key.replace(token, "").trim().length < 4) continue;
        const names = parts.map((p) => p[1]);
        const targetNames = [...value.matchAll(token)].map((p) => p[1]);
        if ([...new Set(names)].sort().join("|") !== [...new Set(targetNames)].sort().join("|")) continue;
        let pattern = "^", at = 0;
        for (const p of parts) { pattern += escape(key.slice(at, p.index)) + "(.+?)"; at = p.index + p[0].length; }
        templates.push([new RegExp(pattern + escape(key.slice(at)) + "$", "u"), names, value, key.replace(token, "").length]);
      }
      // Mest fast text först: en specifik mall går före en allmän som också matchar (stabil sortering, samma som i18n_py)
      templates.sort((a, b) => b[3] - a[3]);
      templateCache.set(dict, templates);
    }
    if (core.length > 1000) return null;
    for (const [rx, names, value] of templates) {
      const m = core.match(rx); if (!m) continue;
      const params = Object.create(null); let valid = true;
      names.forEach((name, i) => { if (params[name] !== undefined && params[name] !== m[i + 1]) valid = false; params[name] = m[i + 1]; });
      if (valid) return value.replace(/\{([a-z][a-z0-9_]*)\}/gi, (_, name) => params[name]);
    }
    return null;
  }

  function lookup(core) {
    if (dict[core] !== undefined && dict[core] !== "") return dict[core];
    const nums = core.match(NUM) || [], key = core.replace(NUM, "#");
    if (dict[key] !== undefined && dict[key] !== "") return fill(dict[key], nums);
    const named = namedLookup(core);
    if (named !== null) return named;
    for (const [re, fn] of RULES) { const m = core.match(re); if (m && lang === "en") return fn(m); }
    return null;
  }

  function tr(s) {
    if (!s || lang === "sv") return s;
    const lead = (s.match(LEAD) || [""])[0];
    let rest = s.slice(lead.length);
    const trail = (rest.match(TRAIL) || [""])[0];
    const core = rest.slice(0, rest.length - trail.length);
    if (!core) return s;
    // hela texten först (med skiljetecknen), sedan kärnan utan dem
    let r = lookup(rest.trim());
    if (r !== null) return lead + r + (rest.match(/\s*$/) || [""])[0];
    r = lookup(core);
    if (r !== null) return lead + r + trail;
    // en avslutande parentes som hör till texten ("Gråzon (1.39 kr).") ska följa med vid uppslaget (samma som i18n_py)
    const need = (core.match(/\(/g) || []).length - (core.match(/\)/g) || []).length;
    if (need > 0 && (trail.match(/\)/g) || []).length >= need) {
      let cut = 0;
      for (let i = 0; i < need; i++) cut = trail.indexOf(")", cut) + 1;
      r = lookup(core + trail.slice(0, cut).replace(/ /g, ""));
      if (r !== null) return lead + r + trail.slice(cut);
    }
    // flera meningar eller delar: översätt var för sig
    for (const sep of [/(?<=[.!?]) (?=[A-ZÅÄÖ])/, / · /, / – /, / - /]) {
      const parts = core.split(sep);
      if (parts.length > 1) {
        const joiner = core.match(sep) ? core.match(sep)[0] || " " : " ";
        const out = parts.map((p) => tr(p));
        if (out.some((x, i) => x !== parts[i])) return lead + out.join(joiner) + trail;
      }
    }
    if (LOOKS_SV.test(core) && core.length < 400) missingSet.add(core.replace(NUM, "#"));
    return s;
  }

  const SKIP = new Set(["SCRIPT", "STYLE", "TEXTAREA", "CODE", "PRE"]);
  const ATTRS = ["title", "aria-label", "placeholder"];
  const done = new WeakMap();

  function node(n) {
    if (n.nodeType === 3) {
      const p = n.parentElement;
      if (!p || SKIP.has(p.tagName) || p.closest("[data-noi18n]")) return;
      const t = n.textContent;
      if (!/\p{L}{2}/u.test(t) || done.get(n) === t) return;
      const e = tr(t);
      done.set(n, e);
      if (e !== t) n.textContent = e;
      return;
    }
    if (n.nodeType !== 1 || SKIP.has(n.tagName) || n.hasAttribute("data-noi18n")) return;
    for (const a of ATTRS) {
      const v = n.getAttribute(a);
      if (v) { const e = tr(v); if (e !== v) n.setAttribute(a, e); }
    }
    for (let c = n.firstChild; c; c = c.nextSibling) node(c);
  }

  const CFG = { childList: true, subtree: true, characterData: true };
  let obs = null, pend = false;
  const queue = new Set();
  function flush() {
    pend = false;
    const q = [...queue]; queue.clear();
    obs.disconnect();
    q.forEach((n) => { if (n.isConnected) node(n.nodeType === 3 ? n : n); });
    obs.observe(document.body, CFG);
  }
  function start() {
    document.documentElement.lang = lang;
    if (lang === "sv") return;
    document.title = tr(document.title);
    node(document.body);
    obs = new MutationObserver((ms) => {
      for (const m of ms) { if (m.type === "characterData") queue.add(m.target); else m.addedNodes.forEach((x) => queue.add(x)); }
      if (!pend) { pend = true; requestAnimationFrame(flush); }
    });
    obs.observe(document.body, CFG);
  }

  const ready = fetch(BASE + "config", { credentials: "same-origin" })
    .then((r) => (r.ok ? r.json() : {}))
    .catch(() => ({}))
    .then((c) => {
      if (c.languages) languages = c.languages;
      if (c.default) serverDefault = c.default;
      if (!localPref()) lang = serverDefault;
      // Inget språk valt i installationen eller på enheten: webbläsarens språk (svenska om den är svensk, annars engelska)
      if (!localPref() && c.chosen === false) {
        const nav = String((navigator.languages && navigator.languages[0]) || navigator.language || "sv").toLowerCase();
        lang = nav.startsWith("sv") ? "sv" : (languages[nav.slice(0, 2)] ? nav.slice(0, 2) : "en");
      }
      if (!languages[lang]) lang = "sv";
      if (lang === "sv") return;
      return fetch(BASE + lang + ".json").then((r) => (r.ok ? r.json() : {})).then((d) => { dict = d || {}; }).catch(() => {});
    })
    .then(() => { if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start(); });

  window.I18N = {
    get lang() { return lang; },
    get languages() { return languages; },
    ready,
    pref: localPref,
    tr,
    /** Byter språk på den här enheten och laddar om. */
    set(p) { try { p && p !== "auto" ? localStorage.setItem(LS_KEY, p) : localStorage.removeItem(LS_KEY); } catch (e) { /* privat läge */ } location.reload(); },
    /** Väljare för språk (<select>), färdig att stoppa in i en sida. */
    selectHtml(id) {
      const opts = Object.entries(languages).map(([k, v]) => `<option value="${k}"${k === lang ? " selected" : ""}>${v}</option>`).join("");
      return `<select id="${id || "langsel"}" data-noi18n aria-label="Language / Språk">${opts}</select>`;
    },
    num: (s) => (lang === "sv" ? s : String(s).replace(/(\d),(\d)/g, "$1.$2")),
    /** Texter som visats utan översättning (för den som vill hjälpa till). */
    missing() { return [...missingSet].sort(); },
    downloadMissing() {
      const out = {}; this.missing().forEach((k) => { out[k] = ""; });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([JSON.stringify(out, null, 2)], { type: "application/json" }));
      a.download = `saknas-${lang}.json`; a.click();
    },
    TRANSLATE_URL: "https://github.com/murre87/energywizard/blob/main/TRANSLATING.md",
  };
})();

