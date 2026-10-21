"use strict";
// Loaded first on every app page. A private API answering 401 means there is no
// valid session: return to login and come back here afterwards. One hook covers
// every page script's own fetch wrapper.
const nativeFetch = window.fetch.bind(window);
let leavingForLogin = false;
window.fetch = async (...args) => {
  const response = await nativeFetch(...args);
  if (response.status === 401 && new URL(response.url || location.href).pathname.startsWith("/api/") && !leavingForLogin) {
    leavingForLogin = true;
    location.replace("/login?next=" + encodeURIComponent(location.pathname + location.search + location.hash));
  }
  return response;
};
// The signed-in account, shared by page scripts: {id, email, display_name, role}.
window.fitlogMe = fetch("/api/me", {cache: "no-store"}).then((r) => r.ok ? r.json() : null).catch(() => null);

// Mark the current section in the shared menu (the same markup on every page).
for (const link of document.querySelectorAll(".navigation [data-nav]")) {
  if (link.dataset.nav.split(" ").includes(location.pathname)) { link.classList.add("active"); link.setAttribute("aria-current", "page"); }
}

const today = document.querySelector("#today");
today.textContent = new Intl.DateTimeFormat("ko-KR", {
  month: "long", day: "numeric", weekday: "long"
}).format(new Date());

async function checkHealth() {
  const status = document.querySelector("#server-status");
  try {
    const response = await fetch("/api/health", {
      cache: "no-store", signal: AbortSignal.timeout(5000)
    });
    if (!response.ok) throw new Error("Server unavailable");
    const result = await response.json();
    if (result.status !== "ok") throw new Error("Health check failed");
    status.textContent = "● 서버 연결됨";
    status.className = "status ok";
    // The home footer and settings footer carry this element; other pages skip it.
    const version = document.querySelector("#app-version");
    if (version && result.version) version.textContent = "v" + result.version;
  } catch {
    status.textContent = "서버 연결을 확인해 주세요";
    status.className = "status error";
  }
}
checkHealth();
window.addEventListener("online", checkHealth);
window.addEventListener("offline", () => {
  const status = document.querySelector("#server-status");
  status.textContent = "오프라인 · 저장된 화면";
  status.className = "status error";
});
const pwaNote = document.querySelector("#pwa-note");
if ("serviceWorker" in navigator && window.isSecureContext) {
  navigator.serviceWorker.register("/service-worker.js").catch(() => {
    pwaNote.textContent = "앱 캐시를 준비하지 못했습니다. 온라인으로 계속 사용할 수 있어요.";
  });
} else if (!window.isSecureContext) {
  pwaNote.textContent = "홈 화면 설치와 앱 캐시를 사용하려면 HTTPS로 접속해 주세요.";
}
