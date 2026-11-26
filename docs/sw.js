/* Service worker: offline use and installation.
 * Network first: when online, the newest version from GitHub is always shown (and saved);
 * the saved copy is used only when offline. */
const CACHE = "watchlist-v4";
const FILES = ["./", "index.html", "style.css", "app.js", "manifest.webmanifest", "vendor/plotly-basic.min.js",
  "data/watchlist.json", "data/glossary.json", "data/cpi.json", "data/bear_markets.json", "data/screener.json",
  "icons/icon.svg", "icons/icon-192.png", "icons/icon-512.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(FILES)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;
  e.respondWith(
    // "no-cache": ask GitHub whether the file changed, instead of using the browser's copy
    fetch(e.request.url, { cache: "no-cache" }).then((res) => {
      if (res.ok) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(e.request, copy)); }
      return res;
    }).catch(() => caches.match(e.request, { ignoreSearch: true }).then((hit) => hit || caches.match("./")))
  );
});
