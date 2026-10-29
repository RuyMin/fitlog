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
// A copy is "current" when it was fetched after CACHE_EPOCH: the last time the app was opened or
// brought back (bulk sync below) and the last successful save, whichever is later.
const CACHE_PREFIX = "fitlog-cache:", CACHE_USER = "fitlog-cache-user", CACHE_EPOCH = "fitlog-cache-epoch", CACHE_DAYS = 7;
const store = (action) => { try { return action(localStorage); } catch { return null; } };
const fresh = (entry) => entry && Date.now() - entry.at < CACHE_DAYS * 86400000;
const entryOf = (storage, key) => {
  const entry = JSON.parse(storage.getItem(CACHE_PREFIX + key) || "null");
  return fresh(entry) && entry.user === storage.getItem(CACHE_USER) ? entry : null;
};
window.fitlogCache = {
  get(key) { return store((storage) => entryOf(storage, key)?.data ?? null); },
  current(key) { return Boolean(store((storage) => (entryOf(storage, key)?.at ?? -1) >= Number(storage.getItem(CACHE_EPOCH) || 0))); },
  // `at` is when the request started, so an answer that raced a save is not taken as current.
  set(key, data, at = Date.now()) {
    return window.fitlogMe.then((me) => me && store((storage) => {
      storage.setItem(CACHE_PREFIX + key, JSON.stringify({user: String(me.id), at, data}));
    }));
  },
  outdate() { store((storage) => storage.setItem(CACHE_EPOCH, String(Date.now()))); },
  clear() {
    store((storage) => Object.keys(storage).filter((key) => key.startsWith(CACHE_PREFIX) || key === CACHE_USER || key === CACHE_EPOCH)
      .forEach((key) => storage.removeItem(key)));
  },
};
store((storage) => Object.keys(storage).filter((key) => key.startsWith(CACHE_PREFIX)).forEach((key) => {
  try { if (!fresh(JSON.parse(storage.getItem(key)))) storage.removeItem(key); } catch { storage.removeItem(key); }
}));

// Corner indicator: the server pill in the top bar says "불러오는 중" / "저장 중" while an API request has
// been waiting longer than BUSY_DELAY (quick answers do not make it flicker), then shows the
// connection state again.
const BUSY_DELAY = 300;
const inFlight = {reads: 0, writes: 0, shown: false, timer: 0};
let serverState = null; // {text, className} once known; the page's own "서버 확인 중" until then
function paintStatus() {
  const status = document.querySelector("#server-status");
  if (!status) return;
  if (inFlight.shown) { status.textContent = inFlight.writes ? "저장 중" : "불러오는 중"; status.className = "status loading"; }
  else if (serverState) { status.textContent = serverState.text; status.className = serverState.className; }
}
function busyStart(write) {
  inFlight[write ? "writes" : "reads"]++;
  if (inFlight.shown) paintStatus();
  else if (!inFlight.timer) inFlight.timer = setTimeout(() => { inFlight.timer = 0; if (inFlight.reads + inFlight.writes) { inFlight.shown = true; paintStatus(); } }, BUSY_DELAY);
}
function busyEnd(write) {
  inFlight[write ? "writes" : "reads"]--;
  if (inFlight.reads + inFlight.writes) { if (inFlight.shown) paintStatus(); return; }
  clearTimeout(inFlight.timer); inFlight.timer = 0;
  if (inFlight.shown) { inFlight.shown = false; paintStatus(); }
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
  // A save can change what any tab shows (a set moves the home summary too), so every saved copy is
  // fetched again the next time its tab opens.
  // A preview (내 목표's live result) computes without saving.
  if (measured && write && response.ok && !target.pathname.endsWith("/preview")) window.fitlogCache.outdate();
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
  // The last answer too, so a page can lay itself out (home: which kinds to show) before this one arrives.
  window.fitlogCache.set("me", me);
}));

// In a block: page scripts share the global scope and declare names such as `zone` themselves.
{
  // Each tab's main data, in the shape its page renders, under the key its saved copy uses.
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Seoul";
  const dayKey = (date) => date.getFullYear() + "-" + String(date.getMonth() + 1).padStart(2, "0") + "-" + String(date.getDate()).padStart(2, "0");
  async function getJSON(path) {
    const response = await fetch(path, {cache: "no-store", signal: AbortSignal.timeout(15000)});
    if (!response.ok) throw new Error("기록을 불러오지 못했습니다. 연결을 확인하고 새로고침해 주세요.");
    return response.json();
  }
  async function paged(path, params = {}) { // every row, past the API's 100-per-page limit
    const items = [];
    for (let offset = 0; ; offset += 100) {
      const page = await getJSON(path + "?" + new URLSearchParams({...params, limit: 100, offset}));
      items.push(...page);
      if (page.length < 100) return items;
    }
  }
  const midnight = (daysFromToday) => { const date = new Date(); date.setHours(0, 0, 0, 0); date.setDate(date.getDate() + daysFromToday); return date; };
  const today = dayKey(new Date());
  window.fitlogData = {
    dashboard: {key: "dashboard:" + zone + ":" + today, load: () => getJSON("/api/dashboard?timezone=" + encodeURIComponent(zone))},
    recent: {key: "workouts:recent", load: () => getJSON("/api/workouts?limit=3")},
    workouts: {key: "workouts:list", load: () => getJSON("/api/workouts?limit=20&offset=0")},
    // The workout calendar's current month (운동 tab); other months load when the user moves to them.
    calendar: {key: "workouts:month:" + today.slice(0, 7), load: () => {
      const start = new Date(); start.setDate(1);
      const end = new Date(start.getFullYear(), start.getMonth() + 1, 0);
      return paged("/api/workouts", {date_from: dayKey(start), date_to: dayKey(end)});
    }},
    exercises: {key: "exercises", load: () => paged("/api/exercises")},
    // Meals: the 7 days ending today, each tagged with its local day.
    meals: {key: "meals:" + today, load: async () => (await paged("/api/meals", {from_at: midnight(-6).toISOString(), to_at: midnight(1).toISOString()}))
      .map((meal) => ({...meal, day: dayKey(new Date(meal.eaten_at))}))},
    // 몸·추이 at its default 3 months, plus the last 7 nights of sleep; both oldest first.
    body: {key: "body:90:" + today, load: async () => {
      const to = new Date(), from = new Date(to); from.setDate(from.getDate() - 90);
      const [records, sleep] = await Promise.all([paged("/api/body-metrics", {from_at: from.toISOString(), to_at: to.toISOString()}),
        paged("/api/sleep", {from_at: midnight(-6).toISOString(), to_at: to.toISOString()})]);
      return {records: records.reverse(), sleep: sleep.reverse()};
    }},
  };

  // Bulk sync: when the app is opened, every tab's data is fetched at once behind a dim layer, so moving between
  // tabs afterwards needs no waiting. Brought back after AWAY_MS in another app, it first asks the server whether
  // records changed elsewhere (another device, a new day) and syncs only then; its own edits never count. Each page
  // renders through fitlogShow and re-renders on window.fitlogOnSync.
  const AWAY_MS = 5000, DIM_DELAY = 150, SYNC_LIMIT = 12000;
  let syncing = Promise.resolve();
  function dim(on) {
    clearTimeout(dim.timer);
    if (!on) { document.getElementById("sync-dim")?.remove(); document.body.removeAttribute("aria-busy"); return; }
    dim.timer = setTimeout(() => {
      if (document.getElementById("sync-dim")) return;
      const layer = document.createElement("div"); layer.id = "sync-dim"; layer.className = "sync-dim";
      const label = document.createElement("span"); label.className = "sync-pill"; label.setAttribute("role", "status");
      label.textContent = "최신 기록을 불러오는 중";
      layer.append(label); document.body.append(layer); document.body.setAttribute("aria-busy", "true");
    }, DIM_DELAY);
  }
  function syncAll() {
    window.fitlogCache.outdate();
    const started = Date.now();
    dim(true);
    const work = Promise.allSettled(Object.values(window.fitlogData).map(async (dataset) => window.fitlogCache.set(dataset.key, await dataset.load(), started)));
    // A stuck request must not leave the app dimmed; tabs then fetch what is still missing themselves.
    syncing = Promise.race([work, new Promise((resolve) => setTimeout(resolve, SYNC_LIMIT))]).finally(() => dim(false));
    return syncing;
  }
  // One tab's data: the saved copy at once (stale = true: the page keeps it read-only), then the current
  // copy, from the bulk sync when it has one, otherwise fetched now.
  window.fitlogShow = async (dataset, show) => {
    const saved = window.fitlogCache.get(dataset.key);
    if (saved) show(saved, true);
    await syncing;
    if (window.fitlogCache.current(dataset.key)) { show(window.fitlogCache.get(dataset.key), false); return; }
    const started = Date.now();
    const data = await dataset.load();
    await window.fitlogCache.set(dataset.key, data, started);
    show(data, false);
  };
  // Asking also marks this phone as up to date (app/services/freshness.py). An error answer (say, signed out)
  // counts as changed, so the sync shows it; no connection at all leaves the saved copy as it is.
  const changedElsewhere = async () => {
    const response = await fetch("/api/me/changed", {cache: "no-store", signal: AbortSignal.timeout(5000)});
    return !response.ok || (await response.json()).changed !== false;
  };
  try {
    if (!sessionStorage.getItem("fitlog-opened")) {
      sessionStorage.setItem("fitlog-opened", "1");
      changedElsewhere().catch(() => {});
      syncAll();
    }
  } catch { /* no session storage: tabs load their own data */ }
  let hiddenAt = 0;
  const resync = () => syncAll().then(() => window.fitlogOnSync?.());
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") { hiddenAt = Date.now(); return; }
    if (hiddenAt && Date.now() - hiddenAt >= AWAY_MS && !leavingForLogin) {
      if (dayKey(new Date()) !== today) resync();
      else changedElsewhere().then((changed) => { if (changed) resync(); }, () => {});
    }
    hiddenAt = 0;
  });
}

// Mark the current section in the shared menu (the same markup on every page).
for (const link of document.querySelectorAll(".navigation [data-nav]")) {
  if (link.dataset.nav.split(" ").includes(location.pathname)) { link.classList.add("active"); link.setAttribute("aria-current", "page"); }
}

const today = document.querySelector("#today");
if (today) today.textContent = new Intl.DateTimeFormat("ko-KR", {
  month: "long", day: "numeric", weekday: "long"
}).format(new Date());

function showServer(ok, version) {
  serverState = ok ? {text: "", className: "status ok"} : {text: "연결이 안 돼요", className: "status error"};
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
  serverState = {text: "인터넷 연결 없음", className: "status error"};
  paintStatus();
});
if ("serviceWorker" in navigator && window.isSecureContext) {
  // A failed registration only costs the offline copy; the app keeps working online, so nothing is shown.
  navigator.serviceWorker.register("/service-worker.js").catch(() => {});
}
