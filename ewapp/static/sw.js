// Minimal service worker: gör appen installerbar och visar skalet offline; data hämtas alltid färsk från nätet.
const SHELL = "ew-shell-v54", FILES = ["./", "style.css", "app.js", "i18n.js", "icons/icon-192.png"];
self.addEventListener("install", (e) => { e.waitUntil(caches.open(SHELL).then((c) => c.addAll(FILES)).then(() => self.skipWaiting())); });
self.addEventListener("activate", (e) => { e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== SHELL).map((k) => caches.delete(k)))).then(() => self.clients.claim())); });
self.addEventListener("fetch", (e) => {
  const u = new URL(e.request.url);
  if (e.request.method !== "GET" || u.pathname.includes("/api/")) return;
  e.respondWith(fetch(e.request).then((r) => { const cp = r.clone(); caches.open(SHELL).then((c) => c.put(e.request, cp)); return r; }).catch(() => caches.match(e.request)));
});
