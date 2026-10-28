"use strict";
// 관리자 화면: shown to admins only (the APIs check too), and the shared AI key.
(() => {
  const $ = (id) => document.getElementById(id);
  window.fitlogMe.then((me) => {
    const admin = Boolean(me && me.role === "admin");
    $("admin-content").hidden = !admin;
    $("admin-denied").hidden = admin;
  });

  const AI_ERRORS = {
    invalid_key: "키가 올바르지 않습니다. 복사한 키를 다시 확인해 주세요.",
    key_forbidden: "이 키에는 사용 권한이 없습니다. Anthropic 콘솔에서 키를 확인해 주세요.",
    model_unavailable: "이 키로는 앱이 쓰는 모델을 사용할 수 없습니다.",
    request_rejected: "Anthropic이 요청을 거절했습니다. 콘솔에서 결제·크레딧 상태를 확인해 주세요.",
    rate_limited: "잠시 후 다시 시도해 주세요.",
    server_not_configured: "서버의 AI 설정(FITLOG_SECRET_KEY)이 아직 되어 있지 않습니다.",
    unreachable: "Anthropic에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.",
  };
  async function aiStatus() {
    try {
      const r = await fetch("/api/assistant/status", {cache: "no-store", signal: AbortSignal.timeout(10000)});
      if (!r.ok) throw new Error();
      const s = await r.json();
      $("ai-key-hint").textContent = !s.key_configured ? "아직 등록되지 않음" : (s.key_hint || "등록됨") + " · 오늘 1인당 " + s.daily_limit + "회 · 모델 " + s.model;
      $("ai-key-delete").hidden = !s.key_configured;
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
    if (!confirm("공용 API 키를 삭제할까요? 삭제하면 모든 사용자가 문장으로 기록하기를 쓸 수 없습니다.")) return;
    const r = await fetch("/api/assistant/key", {method: "DELETE", cache: "no-store", signal: AbortSignal.timeout(10000)});
    $("ai-message").textContent = r.ok ? "키를 삭제했습니다." : "키를 삭제하지 못했습니다.";
    await aiStatus();
  });
  aiStatus();
})();
