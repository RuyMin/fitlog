"use strict";
// First run and 설정 › 홈에 보일 기록: which record kinds the home summary shows (PUT /api/me/tracking).
(() => {
  const $ = (id) => document.getElementById(id);
  const kinds = [...document.querySelectorAll(".kind")];
  const start = $("welcome-start");
  const message = $("welcome-message");
  let answered = false; // an account that already chose comes here only to change it

  function paint() {
    const count = kinds.filter((button) => button.getAttribute("aria-pressed") === "true").length;
    start.disabled = !count;
    start.textContent = !count ? "하나 이상 골라 주세요" : answered ? count + "개 저장하기" : count + "개로 시작하기";
  }
  function pick(list) {
    for (const button of kinds) button.setAttribute("aria-pressed", String(list.includes(button.dataset.kind)));
    paint();
  }
  for (const button of kinds) {
    button.addEventListener("click", () => {
      button.setAttribute("aria-pressed", String(button.getAttribute("aria-pressed") !== "true"));
      paint();
    });
  }

  async function save(list) {
    message.textContent = "";
    start.disabled = true;
    try {
      const response = await fetch("/api/me/tracking", {method: "PUT", headers: {"Content-Type": "application/json"}, body: JSON.stringify({tracking: list})});
      if (!response.ok) throw new Error();
      location.replace("/");
    } catch {
      message.textContent = "저장하지 못했어요. 연결을 확인하고 다시 눌러 주세요.";
      paint();
    }
  }
  start.addEventListener("click", () => save(kinds.filter((button) => button.getAttribute("aria-pressed") === "true").map((button) => button.dataset.kind)));
  // Skipping the first run shows everything, so the home does not send the user back here.
  $("welcome-skip").addEventListener("click", (event) => {
    if (answered) return;
    event.preventDefault();
    save(kinds.map((button) => button.dataset.kind));
  });

  pick(["work", "meal"]);
  window.fitlogMe.then((me) => {
    if (!me?.tracking) return;
    answered = true;
    $("welcome-skip").textContent = "닫기";
    pick(me.tracking);
  });
})();
