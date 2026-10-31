"use strict";
// Pages show from the cache at once and refresh in the background; assets linked by content hash
// (?v=<12 hex>, app/pages.py) never change at that address, so they come straight from the cache.
// API responses are never cached.
const CACHE = "fitlog-shell-v47";
// Fonts (~950KB) are linked from CSS without a hash and change only when rebuilt, so they live in their own
// cache that survives releases; bump this name when scripts/build_fonts.py output changes.
const FONTS = "fitlog-fonts-v1";
const PAGES = ["/", "/workouts", "/meals", "/body", "/body-metrics", "/sleep", "/statistics", "/settings", "/welcome"];
const OFFLINE = ["/manifest.json", "/static/icons/icon.svg", "/static/icons/icon-192.png", "/static/icons/icon-512.png"];
const HASHED = /^[0-9a-f]{12}$/;

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll([...PAGES, ...OFFLINE])).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(
      keys.filter((key) => (key.startsWith("fitlog-shell-") && key !== CACHE) || (key.startsWith("fitlog-fonts-") && key !== FONTS))
        .map((key) => caches.delete(key))
    )).then(() => self.clients.claim())
  );
});

// Keep only real pages: a redirect (signed out, sent to /login) is not a page to show later.
function keep(cache, key, response) {
  if (response.ok && !response.redirected && response.type === "basic") return cache.put(key, response.clone());
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin || url.pathname.startsWith("/api/") || url.pathname.startsWith("/auth/")) return;

  const fonts = url.pathname.startsWith("/static/fonts/");
  if (fonts || (url.pathname.startsWith("/static/") && HASHED.test(url.searchParams.get("v") || ""))) {
    event.respondWith(caches.open(fonts ? FONTS : CACHE).then(async (cache) => {
      const cached = await cache.match(request);
      if (cached) return cached;
      const response = await fetch(request);
      await keep(cache, request, response);
      return response;
    }));
    return;
  }

  if (PAGES.includes(url.pathname)) {
    // Stale-while-revalidate: show the cached page now, store the server's copy for next time.
    event.respondWith(caches.open(CACHE).then(async (cache) => {
      const cached = await cache.match(url.pathname);
      const network = fetch(request).then(async (response) => { await keep(cache, url.pathname, response); return response; });
      if (cached) { event.waitUntil(network.catch(() => {})); return cached; }
      return network;
    }));
    return;
  }

  if (OFFLINE.includes(url.pathname) || url.pathname.startsWith("/static/")) {
    // Anything else: network first, cache only as an offline fallback.
    event.respondWith(fetch(request).then(async (response) => {
      const cache = await caches.open(CACHE);
      await keep(cache, request, response);
      return response;
    }).catch(async () => (await caches.match(request)) || (await caches.match(request, {ignoreSearch: true})) || Response.error()));
  }
});
