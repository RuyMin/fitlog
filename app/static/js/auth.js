"use strict";
const AUTH_ERRORS = {
  not_configured: "로그인이 아직 설정되지 않았습니다. 관리자에게 문의해 주세요.",
  invalid_invite: "초대 링크가 만료되었거나 이미 사용되었습니다. 관리자에게 새 링크를 요청해 주세요.",
  consent_required: "필수 항목에 동의해야 가입할 수 있습니다.",
  state: "로그인 요청이 만료되었거나 다른 브라우저에서 열렸습니다. 처음부터 다시 시도해 주세요.",
  cancelled: "Google 로그인이 취소되었습니다.",
  google: "Google 계정을 확인하지 못했습니다. 잠시 후 다시 시도해 주세요.",
  not_invited: "초대받은 계정이 아닙니다. 관리자에게 초대 링크를 요청해 주세요.",
  disabled: "사용이 중지된 계정입니다. 관리자에게 문의해 주세요.",
  rate_limited: "요청이 너무 많습니다. 1분 후 다시 시도해 주세요.",
};

function showAuthError(code) {
  const target = document.getElementById("auth-error");
  if (!target || !code) return;
  target.textContent = AUTH_ERRORS[code] || "로그인하지 못했습니다. 다시 시도해 주세요.";
  target.hidden = false;
}

showAuthError(new URLSearchParams(location.search).get("error"));

const inviteToken = document.getElementById("invite-token");
if (inviteToken) {
  const match = location.pathname.match(/^\/invite\/([A-Za-z0-9_-]{20,100})$/);
  if (match) inviteToken.value = match[1];
  else showAuthError("invalid_invite");
}
