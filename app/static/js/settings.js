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
      $("sync-help").textContent = !data.configured ? "서비스 계정 JSON 파일과 Spreadsheet ID를 설정해 주세요. README의 Google Sheets 연결 절차를 따라주세요." : data.last_sync_error || "공유 권한과 시트 형식을 확인한 후 지금 동기화를 누르세요.";
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
  async function showArchive(id) {
    const view = $("archive-view"); view.textContent = "자료를 불러오는 중…";
    try {
      const data = await api("archives/" + id); view.replaceChildren(node("h3", data.filename));
      for (const [name, rows] of Object.entries(data.sheets)) {
        const detail = node("details"), scroll = node("div"), table = node("table"); scroll.className = "archive-scroll";
        detail.append(node("summary", name + " · " + rows.length + "개 비어 있지 않은 행"));
        for (const entry of rows) {
          const tr = node("tr"); tr.append(node("th", entry.row + "행"));
          for (const cell of entry.values) tr.append(node("td", cell == null ? "" : String(cell)));
          table.append(tr);
        }
        scroll.append(table); detail.append(scroll); view.append(detail);
      }
    } catch { view.textContent = "원본 자료를 불러오지 못했습니다."; }
  }
  async function archives() {
    try {
      const data = await api("archives"); const list = $("archive-list"); list.replaceChildren();
      if (!data.length) { list.textContent = "아직 이관한 원본 자료가 없습니다."; return; }
      for (const item of data) {
        const box = node("div"); box.className = "archive-entry"; box.append(node("h3", item.filename));
        const r = item.report; box.append(node("p", r.summary || "원본 보존됨"));
        const notes = node("details"); notes.append(node("summary", "이관 기준과 보존 항목"));
        for (const warning of r.notes || []) notes.append(node("p", warning));
        box.append(notes);
        const button = node("button", "전체 원본 내용 보기"); button.addEventListener("click", () => showArchive(item.id)); box.append(button);
        const link = node("a", "원본 Excel 다운로드"); link.href = "/api/sync/archives/" + item.id + "/download"; box.append(link); list.append(box);
      }
    } catch { $("archive-list").textContent = "원본 자료 목록을 불러오지 못했습니다."; }
  }
  window.addEventListener("fitlog-imported", archives);
  status(); archives();
})();
