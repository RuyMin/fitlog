"use strict";
// Loaded first on every app page. A private API answering 401 means there is no
// valid session: return to login and come back here afterwards. One hook covers
// every page script's own fetch wrapper.
const nativeFetch = window.fetch.bind(window);
let leavingForLogin = false;

// Speed statistics (app/services/perf.py): how long the phone waited for each API request, with the
// server's own share from the Server-Timing header, and how long each screen took to show its data.
// Only the path shape, status and durations are sent; never what was saved or shown.
const perfQueue = [];
function perfRecord(event) {
  if (perfQueue.length < 300) perfQueue.push({at: new Date().toISOString(), page: location.pathname, ...event});
}
function serverMs(response) {
  const match = /app;dur=([\d.]+)/.exec(response.headers.get("Server-Timing") || "");
  return match ? Number(match[1]) : null;
}
// Moving between screens in a few seconds is normal, and phones do not reliably send anything while a
// page goes away. So: send every 10 s, try a beacon on leaving, and keep what could not be handed over
// in localStorage for the next screen to send.
const PERF_KEY = "fitlog-perf-pending";
function perfFlush(leaving = false) {
  if (!perfQueue.length) return;
  const events = perfQueue.splice(0);
  const body = JSON.stringify(events);
  if (leaving) {
    const sent = navigator.sendBeacon?.("/api/metrics", new Blob([body], {type: "application/json"}));
    if (!sent) { try { localStorage.setItem(PERF_KEY, body); } catch { /* storage unavailable: drop */ } }
    return;
  }
  nativeFetch("/api/metrics", {method: "POST", headers: {"Content-Type": "application/json"}, body, keepalive: true})
    .then((response) => { if (!response.ok && response.status !== 422) perfQueue.unshift(...events.slice(0, 300 - perfQueue.length)); })
    .catch(() => perfQueue.unshift(...events.slice(0, 300 - perfQueue.length)));
}
try {
  const pending = JSON.parse(localStorage.getItem(PERF_KEY) || "[]");
  localStorage.removeItem(PERF_KEY);
  if (Array.isArray(pending)) perfQueue.push(...pending.slice(0, 300));
} catch { /* storage unavailable or damaged: start empty */ }
setInterval(perfFlush, 10000);
// One "page" event per screen: page ready (from cache or network), then the first data shown.
let pageRecorded = false;
function recordPage() {
  if (pageRecorded) return;
  const nav = performance.getEntriesByType("navigation")[0];
  const first = performance.getEntriesByType("resource").filter((entry) => entry.name.includes("/api/") && !entry.name.includes("/api/metrics") && entry.startTime < 3000 && entry.responseEnd > 0);
  if (!nav || !first.length) return;
  pageRecorded = true;
  perfRecord({kind: "page", route: location.pathname, total_ms: Math.round(Math.max(...first.map((entry) => entry.responseEnd))),
    html_ms: Math.round(nav.responseEnd), cached: nav.transferSize === 0});
}
window.addEventListener("load", () => setTimeout(recordPage, 4000));
const leave = () => { recordPage(); perfFlush(true); };
window.addEventListener("pagehide", leave);
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "hidden") leave(); });

// Show-then-refresh: the last copy of a screen's data stays on this phone for the signed-in account, is
// shown at once on the next visit and then replaced by the server's copy. It is health data, so it is
// tied to one account, dropped after CACHE_DAYS, and cleared on logout, on a 401 and when another
// account signs in (the settings page says so).
const CACHE_PREFIX = "fitlog-cache:", CACHE_USER = "fitlog-cache-user", CACHE_DAYS = 7;
const store = (action) => { try { return action(localStorage); } catch { return null; } };
const fresh = (entry) => entry && Date.now() - entry.at < CACHE_DAYS * 86400000;
window.fitlogCache = {
  get(key) {
    return store((storage) => {
      const entry = JSON.parse(storage.getItem(CACHE_PREFIX + key) || "null");
      return fresh(entry) && entry.user === storage.getItem(CACHE_USER) ? entry.data : null;
    });
  },
  set(key, data) {
    window.fitlogMe.then((me) => me && store((storage) => {
      storage.setItem(CACHE_PREFIX + key, JSON.stringify({user: String(me.id), at: Date.now(), data}));
    }));
  },
  clear() {
    store((storage) => Object.keys(storage).filter((key) => key.startsWith(CACHE_PREFIX) || key === CACHE_USER).forEach((key) => storage.removeItem(key)));
  },
};
store((storage) => Object.keys(storage).filter((key) => key.startsWith(CACHE_PREFIX)).forEach((key) => {
  try { if (!fresh(JSON.parse(storage.getItem(key)))) storage.removeItem(key); } catch { storage.removeItem(key); }
}));

// Corner indicator: the server pill in the top bar says "불러오는 중" / "저장 중" while an API request has
// been waiting longer than BUSY_DELAY (quick answers do not make it flicker), then shows the
// connection state again.
const BUSY_DELAY = 300;
const busy = {reads: 0, writes: 0, shown: false, timer: 0};
let serverState = null; // {text, className} once known; the page's own "서버 확인 중" until then
function paintStatus() {
  const status = document.querySelector("#server-status");
  if (!status) return;
  if (busy.shown) { status.textContent = busy.writes ? "저장 중" : "불러오는 중"; status.className = "status loading"; }
  else if (serverState) { status.textContent = serverState.text; status.className = serverState.className; }
}
function busyStart(write) {
  busy[write ? "writes" : "reads"]++;
  if (busy.shown) paintStatus();
  else if (!busy.timer) busy.timer = setTimeout(() => { busy.timer = 0; if (busy.reads + busy.writes) { busy.shown = true; paintStatus(); } }, BUSY_DELAY);
}
function busyEnd(write) {
  busy[write ? "writes" : "reads"]--;
  if (busy.reads + busy.writes) { if (busy.shown) paintStatus(); return; }
  clearTimeout(busy.timer); busy.timer = 0;
  if (busy.shown) { busy.shown = false; paintStatus(); }
}

window.fetch = async (...args) => {
  const started = performance.now();
  const target = new URL(args[0] instanceof Request ? args[0].url : String(args[0]), location.href);
  const method = (args[1]?.method || (args[0] instanceof Request ? args[0].method : "GET")).toUpperCase();
  const measured = target.origin === location.origin && target.pathname.startsWith("/api/") && target.pathname !== "/api/metrics";
  const write = method !== "GET";
  let response;
  if (measured) busyStart(write);
  try {
    response = await nativeFetch(...args);
  } catch (error) {
    if (measured) perfRecord({kind: "client", route: target.pathname, method, status: 0, total_ms: Math.round(performance.now() - started)});
    throw error;
  } finally {
    if (measured) busyEnd(write);
  }
  if (measured) perfRecord({kind: "client", route: target.pathname, method, status: response.status,
    total_ms: Math.round(performance.now() - started), server_ms: serverMs(response)});
  if (response.status === 401 && new URL(response.url || location.href).pathname.startsWith("/api/") && !leavingForLogin) {
    leavingForLogin = true;
    window.fitlogCache.clear();
    location.replace("/login?next=" + encodeURIComponent(location.pathname + location.search + location.hash));
  }
  return response;
};
// The signed-in account, shared by page scripts: {id, email, display_name, role}.
window.fitlogMe = fetch("/api/me", {cache: "no-store"}).then((r) => r.ok ? r.json() : null).catch(() => null);
window.fitlogMe.then((me) => me && store((storage) => {
  if (storage.getItem(CACHE_USER) !== String(me.id)) { window.fitlogCache.clear(); storage.setItem(CACHE_USER, String(me.id)); }
}));

// Mark the current section in the shared menu (the same markup on every page).
for (const link of document.querySelectorAll(".navigation [data-nav]")) {
  if (link.dataset.nav.split(" ").includes(location.pathname)) { link.classList.add("active"); link.setAttribute("aria-current", "page"); }
}

const today = document.querySelector("#today");
today.textContent = new Intl.DateTimeFormat("ko-KR", {
  month: "long", day: "numeric", weekday: "long"
}).format(new Date());

function showServer(ok, version) {
  serverState = ok ? {text: "● 서버 연결됨", className: "status ok"} : {text: "서버 연결을 확인해 주세요", className: "status error"};
  paintStatus();
  // The home footer and settings footer carry this element; other pages skip it.
  const label = document.querySelector("#app-version");
  if (label && version) label.textContent = "v" + version;
}
// Every page already asks for /api/me; its answer doubles as the connection check, so pages make one
// round trip fewer. /api/health is used only when the phone comes back online.
window.fitlogMe.then((me) => showServer(Boolean(me), me?.version));
async function checkHealth() {
  try {
    const response = await fetch("/api/health", {
      cache: "no-store", signal: AbortSignal.timeout(5000)
    });
    if (!response.ok) throw new Error("Server unavailable");
    const result = await response.json();
    if (result.status !== "ok") throw new Error("Health check failed");
    showServer(true, result.version);
  } catch {
    showServer(false);
  }
}
window.addEventListener("online", checkHealth);
window.addEventListener("offline", () => {
  serverState = {text: "오프라인 · 저장된 화면", className: "status error"};
  paintStatus();
});
const pwaNote = document.querySelector("#pwa-note");
if ("serviceWorker" in navigator && window.isSecureContext) {
  navigator.serviceWorker.register("/service-worker.js").catch(() => {
    pwaNote.textContent = "앱 캐시를 준비하지 못했습니다. 온라인으로 계속 사용할 수 있어요.";
  });
} else if (!window.isSecureContext) {
  pwaNote.textContent = "홈 화면 설치와 앱 캐시를 사용하려면 HTTPS로 접속해 주세요.";
}
