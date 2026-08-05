const CACHE_NAME = "smartmailer-static-v3";
const STATIC_ASSETS = [
  "/static/styles.css",
  "/static/app.js",
  "/static/favicon.svg",
  "/static/manifest.webmanifest",
];

self.addEventListener("install", event => {
  event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(STATIC_ASSETS)));
  self.skipWaiting();
});

self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys().then(keys => Promise.all(
      keys.filter(key => key !== CACHE_NAME).map(key => caches.delete(key))
    ))
  );
  self.clients.claim();
});

self.addEventListener("fetch", event => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== self.location.origin) return;

  if (url.pathname.startsWith("/static/")) {
    event.respondWith(caches.match(event.request).then(cached => cached || fetch(event.request)));
  }
});
