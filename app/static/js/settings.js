"use strict";
(() => {
  const $ = (id) => document.getElementById(id);
  const node = (tag, value) => { const n = document.createElement(tag); if (value != null) n.textContent = value; return n; };
  let busy = false;
  async function api(path, post = false) {
    const r = await fetch("/api/sync/" + path, {method: post ? "POST" : "GET", cache: "no-store", headers: post ? {"Content-Type": "application/json"} : {}, body: post ? "{}" : undefined, signal: AbortSignal.timeout(post ? 180000 : 10000)});
    const data = await r.json();
    if (!r.ok) throw new Error(typeof data.detail === "string" ? data.detail : "요청을 처리하지 못했습니다.");
    return data;
  }
  function result(data) {
    const container = $("sync-results"); container.replaceChildren();
    if (!data) return;
    const names = {workouts: "운동", workout_sets: "세트", meals: "식단", body_metrics: "신체", sleep: "수면"};
    for (const [key, label] of Object.entries(names)) {
      const n = data[key]; if (n) container.append(node("p", `${label}: ${n.inserted}건 추가 · ${n.updated}건 수정 · ${n.skipped}건 유지`));
    }
  }
  async function status() {
    try {
      const data = await api("status");
      const labels = {not_configured:"Not configured · 설정 필요", not_verified:"설정됨 · 연결 확인 전", connected:"Connected · 마지막 동기화 성공", different_spreadsheet:"다른 Spreadsheet · 기존 ID 확인 필요"};
      $("sync-connection").textContent = data.running ? "동기화 중" : labels[data.connection_status];
      $("sync-sheet").textContent = data.spreadsheet_title || data.spreadsheet_id || "미설정";
      $("sync-last").textContent = data.last_sync_at ? new Date(data.last_sync_at).toLocaleString("ko-KR") + (data.last_sync_status === "ok" ? " · 성공" : " · 실패") : "아직 없음";
      $("sync-help").textContent = !data.configured ? "서비스 계정 JSON 파일과 Spreadsheet ID를 설정해 주세요. README의 Google Sheets 연결 절차를 따라주세요." : data.last_sync_error || "한글 통합기록 7개 탭 또는 영어 표준 시트 5개를 자동 인식합니다. 지금 동기화를 눌러 기록을 가져오세요.";
      $("sync-now").disabled = busy || data.running || !data.configured || data.connection_status === "different_spreadsheet";
      result(data.last_result);
    } catch { $("sync-connection").textContent = "서버 연결 실패"; $("sync-now").disabled = true; }
  }
  $("sync-now").addEventListener("click", async () => {
    if (busy) return; busy = true; $("sync-now").disabled = true;
    $("sync-message").textContent = "동기화 중…"; $("sync-results").replaceChildren();
    try { const data = await api("google", true); result(data); $("sync-message").textContent = "동기화 완료"; }
    catch (error) { $("sync-message").textContent = error.name === "TimeoutError" ? "응답 대기 시간이 지났습니다. 상태 새로고침으로 결과를 확인해 주세요." : error.message === "Failed to fetch" ? "서버에 연결하지 못했습니다. 연결 후 상태를 새로고침해 주세요." : error.message; }
    finally { busy = false; await status(); }
  });
  $("sync-refresh").addEventListener("click", status);

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
      const toggle = $("consent-ai-toggle"), active = Boolean(data.ai_transfer && data.ai_transfer.active);
      toggle.textContent = active ? "AI 외부 전송 동의 철회" : "고지를 확인했고 AI 외부 전송에 동의";
      toggle.dataset.active = active ? "1" : "";
      toggle.hidden = false;
    } catch { $("consent-ai").textContent = "동의 내역을 확인하지 못했습니다."; }
  }
  $("consent-ai-toggle").addEventListener("click", async () => {
    const toggle = $("consent-ai-toggle"), active = toggle.dataset.active === "1";
    if (!active && !confirm("위 'AI 외부 전송 고지'를 확인했고 동의합니까? 동의 후에도 언제든 철회할 수 있습니다.")) return;
    toggle.disabled = true;
    try {
      const r = await fetch("/api/me/consents/ai_transfer", {method: active ? "DELETE" : "POST", cache: "no-store", signal: AbortSignal.timeout(10000)});
      if (!r.ok) throw new Error();
      $("account-message").textContent = active ? "AI 외부 전송 동의를 철회했습니다." : "AI 외부 전송에 동의했습니다.";
      await consents(await window.fitlogMe);
      aiStatus();
    } catch { $("account-message").textContent = "동의 상태를 바꾸지 못했습니다. 다시 시도해 주세요."; }
    finally { toggle.disabled = false; }
  });
  $("logout").addEventListener("click", async () => {
    $("logout").disabled = true;
    try { await fetch("/auth/logout", {method: "POST", cache: "no-store", signal: AbortSignal.timeout(10000)}); } catch { /* the session cookie is cleared on the next successful request */ }
    location.replace("/login");
  });

  const AI_ERRORS = {
    invalid_key: "키가 올바르지 않습니다. 복사한 키를 다시 확인해 주세요.",
    key_forbidden: "이 키에는 사용 권한이 없습니다. Anthropic 콘솔에서 키를 확인해 주세요.",
    model_unavailable: "이 키로는 앱이 쓰는 모델을 사용할 수 없습니다.",
    request_rejected: "Anthropic이 요청을 거절했습니다. 콘솔에서 결제·크레딧 상태를 확인해 주세요.",
    rate_limited: "잠시 후 다시 시도해 주세요.",
    server_not_configured: "관리자가 서버의 AI 설정(FITLOG_SECRET_KEY)을 아직 하지 않았습니다.",
    unreachable: "Anthropic에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.",
  };
  async function aiStatus() {
    try {
      const r = await fetch("/api/assistant/status", {cache: "no-store", signal: AbortSignal.timeout(10000)});
      if (!r.ok) throw new Error();
      const s = await r.json();
      $("ai-key-hint").textContent = s.key_hint || "없음";
      $("ai-consent").textContent = s.consent ? "동의함" : "동의 필요 (위 계정 카드에서 동의)";
      $("ai-usage").textContent = `${s.used_today} / ${s.daily_limit}회 (모델 ${s.model})`;
      $("ai-key-delete").hidden = !s.key_hint;
      $("ai-key-save").disabled = !s.server_ready;
      if (!s.server_ready) $("ai-message").textContent = AI_ERRORS.server_not_configured;
    } catch { $("ai-key-hint").textContent = "상태를 확인하지 못했습니다."; }
  }
  $("ai-key-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    $("ai-key-save").disabled = true; $("ai-message").textContent = "키를 확인하는 중…";
    try {
      const r = await fetch("/api/assistant/key", {method: "PUT", cache: "no-store", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({api_key: $("ai-key").value.trim()}), signal: AbortSignal.timeout(60000)});
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail && data.detail.code ? AI_ERRORS[data.detail.code] || "키를 저장하지 못했습니다." : "sk-ant-로 시작하는 키를 입력해 주세요.");
      $("ai-key").value = ""; $("ai-message").textContent = "키를 확인했고 저장했습니다.";
    } catch (error) { $("ai-message").textContent = error.message; }
    finally { await aiStatus(); }
  });
  $("ai-key-delete").addEventListener("click", async () => {
    if (!confirm("등록한 API 키를 삭제할까요? 삭제하면 문장으로 기록하기를 쓸 수 없습니다.")) return;
    const r = await fetch("/api/assistant/key", {method: "DELETE", cache: "no-store", signal: AbortSignal.timeout(10000)});
    $("ai-message").textContent = r.ok ? "키를 삭제했습니다." : "키를 삭제하지 못했습니다.";
    await aiStatus();
  });
  aiStatus();

  window.fitlogMe.then((me) => {
    if (!me) return;
    $("account-email").textContent = me.display_name ? `${me.display_name} (${me.email})` : me.email;
    $("account-role").textContent = me.role === "admin" ? "관리자" : "멤버";
    consents(me);
    // The service account and Spreadsheet are server-wide, so only the admin syncs.
    if (me.role === "admin") { $("sync-card").hidden = false; status(); }
  });
})();
