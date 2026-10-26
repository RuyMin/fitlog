"use strict";
// Settings › 속도 통계 (admins only): /api/admin/perf summarised as small tables.
(() => {
  const $ = (id) => document.getElementById(id);
  const node = (tag, text, className) => { const n = document.createElement(tag); if (text != null) n.textContent = text; if (className) n.className = className; return n; };
  const LABELS = {
    "GET /api/dashboard": "홈 요약", "GET /api/workouts": "운동 목록", "GET /api/workouts/{id}": "운동 1건",
    "GET /api/workouts/{workout_id}": "운동 1건", "POST /api/workouts": "운동 만들기", "PUT /api/workouts/{workout_id}": "운동 수정",
    "PUT /api/workouts/{workout_id}/sets/{set_id}": "세트 저장 (완료·값 입력)", "POST /api/workouts/{workout_id}/sets": "세트 추가",
    "DELETE /api/workouts/{workout_id}/sets/{set_id}": "세트 삭제", "POST /api/workouts/{workout_id}/sets/batch": "세트 여러 개 추가",
    "PUT /api/workouts/{workout_id}/exercises/{exercise_id}/variant": "그립 선택", "DELETE /api/workouts/{workout_id}/exercises/{exercise_id}": "종목 빼기",
    "GET /api/exercises": "내 종목", "GET /api/exercise-presets": "운동 프리셋", "GET /api/me": "계정 정보", "GET /api/health": "서버 상태",
    "GET /api/assistant/status": "AI 상태", "POST /api/assistant/draft": "AI 초안", "POST /api/assistant/commit": "AI 저장",
    "GET /api/meals": "식단 목록", "GET /api/body-metrics": "체중·신체 목록", "GET /api/sleep": "수면 목록", "GET /api/statistics": "통계",
  };
  const PAGES = {"/": "홈", "/workouts": "운동", "/meals": "식단", "/body": "몸·추이", "/body-metrics": "체중·신체", "/sleep": "수면", "/statistics": "통계", "/settings": "설정"};
  const ms = (value) => value == null ? "—" : value >= 1000 ? (value / 1000).toFixed(2) + "초" : Math.round(value) + "ms";
  const pair = (stat) => stat && stat.count ? ms(stat.p50) + " / " + ms(stat.p90) : "—";

  function table(root, head, rows) {
    const grid = node("table");
    const tr = node("tr"); for (const h of head) tr.append(node("th", h)); grid.append(tr);
    for (const row of rows) { const line = node("tr"); for (const cell of row) line.append(node("td", String(cell))); grid.append(line); }
    root.replaceChildren(rows.length ? grid : node("p", "아직 기록이 없어요. 앱을 쓰면 30초 안에 모입니다.", "hint"));
  }
  async function load(days) {
    $("perf-message").textContent = "불러오는 중…";
    try {
      const response = await fetch("/api/admin/perf?days=" + days, {cache: "no-store"});
      if (!response.ok) throw new Error("통계를 불러오지 못했습니다.");
      const data = await response.json();
      const overall = $("perf-overall"); overall.replaceChildren();
      for (const [label, stat] of [["휴대폰 체감 (요청 1건)", data.overall.client], ["서버 처리", data.overall.server]]) {
        const box = node("p"); box.append(node("span", label), node("strong", pair(stat)), node("small", (stat.count || 0) + "건"));
        overall.append(box);
      }
      table($("perf-pages"), ["화면", "열린 횟수", "페이지 표시", "데이터까지", "캐시 사용"],
        data.pages.map((p) => [PAGES[p.page] || p.page, p.data.count, pair(p.html), pair(p.data), Math.round(p.cached_share * 100) + "%"]));
      table($("perf-routes"), ["요청", "횟수", "체감", "서버", "네트워크", "실패"],
        data.routes.map((r) => [LABELS[r.method + " " + r.route] || r.method + " " + r.route, r.client.count || r.server.count,
          pair(r.client), pair(r.server), r.network_p50 == null ? "—" : ms(r.network_p50), r.errors]));
      table($("perf-users"), ["계정", "휴대폰 기록", "서버 기록", "화면 열기"], data.users.map((u) => [u.email, u.client, u.server, u.page]));
      $("perf-message").textContent = "최근 " + days + "일 · 보통 / 느릴 때(상위 10%)";
    } catch (error) { $("perf-message").textContent = error.message; }
  }
  window.fitlogMe.then((me) => {
    if (!me || me.role !== "admin") return;
    $("perf-card").hidden = false;
    for (const button of document.querySelectorAll(".perf-days button")) {
      button.addEventListener("click", () => {
        document.querySelectorAll(".perf-days button").forEach((other) => other.setAttribute("aria-pressed", String(other === button)));
        load(Number(button.dataset.days));
      });
    }
    load(1);
  });
})();
