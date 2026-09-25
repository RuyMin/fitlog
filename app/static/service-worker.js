"use strict";
const CACHE = "fitlog-shell-v5";
const ASSETS = [
  "/settings", "/static/css/settings.css", "/static/js/settings.js",
  "/statistics", "/static/css/statistics.css", "/static/js/statistics.js", "/static/js/charts.js",
  "/meals", "/body-metrics", "/sleep", "/static/css/records.css", "/static/js/records.js",
  "/workouts", "/static/css/workouts.css", "/static/js/workouts.js", "/static/js/home.js",
  "/", "/static/css/app.css", "/static/js/app.js", "/manifest.json",
  "/static/icons/icon.svg", "/static/icons/icon-192.png", "/static/icons/icon-512.png"
];
self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(ASSETS)));
});
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(
      keys.filter((key) => key.startsWith("fitlog-shell-") && key !== CACHE)
        .map((key) => caches.delete(key))
    )).then(() => self.clients.claim())
  );
});
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  // Never cache health or future personal API responses.
  if (event.request.method !== "GET" || url.origin !== self.location.origin ||
      url.pathname.startsWith("/api/") || !ASSETS.includes(url.pathname)) return;
  // Network first prevents stale UI; cache is only an offline fallback.
  event.respondWith(fetch(event.request).then((response) => {
    if (response.ok) {
      const copy = response.clone();
      event.waitUntil(caches.open(CACHE).then((cache) => cache.put(event.request, copy)));
    }
    return response;
  }).catch(async () => {
    const cached = await caches.match(event.request, {ignoreSearch: true});
    return cached || Response.error();
  }));
});
