"use strict";
// 설정: a list of rows (with a short current value each) that open one panel at a time by #hash, plus the
// account, consent and AI details those panels show.
(() => {
  const $ = (id) => document.getElementById(id);

  const when = (value) => new Date(value).toLocaleString("ko-KR");
  function consentText(entry, isAdmin) {
    if (!entry) return isAdmin ? "운영자 계정 · 해당 없음" : "기록 없음";
    if (entry.withdrawn_at) return "철회함 · " + when(entry.withdrawn_at);
    return entry.active ? "동의함 · " + when(entry.granted_at) : `이전 고지(${entry.version})에 동의함 · 다시 확인 필요`;
  }
  async function consents(me) {
    try {
      const r = await fetch("/api/me/consents", {cache: "no-store", signal: AbortSignal.timeout(10000)});
      if (!r.ok) throw new Error();
      const data = await r.json();
      $("consent-service").textContent = consentText(data.service, me.role === "admin");
      $("consent-ai").textContent = data.ai_transfer ? consentText(data.ai_transfer, false) : "동의하지 않음";
      $("row-account").textContent = "AI 외부 전송 " + (data.ai_transfer?.active ? "동의함" : "동의 안 함");
      const toggle = $("consent-ai-toggle"), active = Boolean(data.ai_transfer && data.ai_transfer.active);
      toggle.textContent = active ? "AI 외부 전송 동의 철회" : "고지를 확인했고 AI 외부 전송에 동의";
      toggle.dataset.active = active ? "1" : "";
      toggle.hidden = false;
    } catch { $("consent-ai").textContent = "동의 내역을 확인하지 못했어요."; }
  }
  $("consent-ai-toggle").addEventListener("click", async () => {
    const toggle = $("consent-ai-toggle"), active = toggle.dataset.active === "1";
    if (!active && !confirm("위 'AI 외부 전송 고지'를 확인했고 동의합니까? 동의 후에도 언제든 철회할 수 있습니다.")) return;
    toggle.disabled = true;
    try {
      const r = await fetch("/api/me/consents/ai_transfer", {method: active ? "DELETE" : "POST", cache: "no-store", signal: AbortSignal.timeout(10000)});
      if (!r.ok) throw new Error();
      $("account-message").textContent = active ? "AI 외부 전송 동의를 철회했어요." : "AI 외부 전송에 동의했어요.";
      await consents(await window.fitlogMe);
      aiStatus();
    } catch { $("account-message").textContent = "동의 상태를 바꾸지 못했어요. 다시 시도해 주세요."; }
    finally { toggle.disabled = false; }
  });
  $("logout").addEventListener("click", async () => {
    $("logout").disabled = true;
    window.fitlogCache.clear();
    try { await fetch("/auth/logout", {method: "POST", cache: "no-store", signal: AbortSignal.timeout(10000)}); } catch { /* the session cookie is cleared on the next successful request */ }
    location.replace("/login");
  });

  async function aiStatus() {
    try {
      const r = await fetch("/api/assistant/status", {cache: "no-store", signal: AbortSignal.timeout(10000)});
      if (!r.ok) throw new Error();
      const s = await r.json();
      $("ai-key-hint").textContent = !s.key_configured ? "아직 등록되지 않음" : s.key_hint || "등록됨";
      $("ai-consent").textContent = s.consent ? "동의함" : "동의 필요 (위 계정 카드에서 동의)";
      $("ai-usage").textContent = `${s.used_today} / ${s.daily_limit}회 (모델 ${s.model})`;
      $("row-ai").textContent = !s.key_configured ? "공용 키 등록 전" : !s.consent ? "AI 외부 전송 동의가 필요해요" : "오늘 " + s.used_today + "/" + s.daily_limit + "회 사용";
      if (!s.server_ready) $("ai-message").textContent = "관리자가 AI 기능을 아직 설정하지 않았어요.";
    } catch { $("ai-key-hint").textContent = "상태를 확인하지 못했어요."; }
  }
  aiStatus();

  window.fitlogMe.then((me) => {
    if (!me) return;
    $("account-email").textContent = me.display_name ? `${me.display_name} (${me.email})` : me.email;
    $("account-role").textContent = me.role === "admin" ? "관리자" : "멤버";
    $("admin-entry").hidden = me.role !== "admin";
    $("profile-email").textContent = me.display_name || me.email;
    $("profile-role").textContent = "Google 계정 · " + (me.role === "admin" ? "관리자" : "멤버");
    $("profile-initial").textContent = (me.display_name || me.email || "·").trim().charAt(0).toUpperCase();
    const KINDS = {work: "운동", meal: "식단", body: "체중", sleep: "수면"};
    $("row-tracking").textContent = (me.tracking || Object.keys(KINDS)).map((kind) => KINDS[kind]).filter(Boolean).join(" · ");
    consents(me);
  });
  fetch("/api/me/goals", {cache: "no-store"}).then((r) => r.ok ? r.json() : null).then((data) => {
    if (!data) return;
    const g = data.goals, n = (value) => new Intl.NumberFormat("ko-KR").format(Math.round(value));
    $("row-goals").textContent = n(g.calorie_kcal) + "kcal · 단백질 " + n(g.protein_g) + "g · 수면 " + Math.round(g.sleep_minutes / 6) / 10 + "시간";
  }).catch(() => { $("row-goals").textContent = "열량 · 단백질 · 수면"; });
  $("logout-row").addEventListener("click", () => $("logout").click());

  // One screen at a time: the list, or the panel the #hash names (old links like #excel-heading still work).
  const ALIASES = {"excel-heading": "excel", "goals-heading": "goals", "ai-card": "ai", "account-heading": "account"};
  function route() {
    const key = ALIASES[location.hash.slice(1)] || location.hash.slice(1);
    const panel = key && document.querySelector('.set-panel[data-panel="' + key + '"]');
    $("settings-home").hidden = Boolean(panel);
    for (const item of document.querySelectorAll(".set-panel")) item.hidden = item !== panel;
    window.scrollTo(0, 0);
  }
  for (const back of document.querySelectorAll(".set-back")) back.addEventListener("click", (event) => {
    event.preventDefault();
    if (history.state?.settingsPanel) history.back(); else { history.replaceState(null, "", location.pathname); route(); }
  });
  // Rows push a history entry, so the phone's back button returns to the list.
  for (const link of document.querySelectorAll('#settings-home a[href^="#"]')) link.addEventListener("click", (event) => {
    event.preventDefault();
    history.pushState({settingsPanel: true}, "", link.getAttribute("href"));
    route();
  });
  window.addEventListener("popstate", route);
  window.addEventListener("hashchange", route);
  route();
})();
