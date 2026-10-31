"use strict";
// 수면: the last seven nights at a glance, then every sleep newest first (more as you go). Tapping one
// opens it to edit or delete; ＋ 기록 adds one with the usual times filled in (quick.js).
(() => {
  const $ = (selector) => document.querySelector(selector);
  const WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"];
  const PAGE = 30;
  const state = {items: [], offset: 0, request: 0};
  const pad = (value) => String(value).padStart(2, "0");
  const clock = (value) => { const date = new Date(value); return date.getHours() + ":" + pad(date.getMinutes()); };
  const length = (minutes) => Math.floor(minutes / 60) + "시간 " + pad(minutes % 60) + "분";
  function node(tag, text, className) { const item = document.createElement(tag); if (text != null) item.textContent = text; if (className) item.className = className; return item; }
  function notice(text, error = false) { $("#notice").textContent = text; $("#notice").className = error ? "error" : ""; }

  async function load(append = false) {
    const request = ++state.request;
    try {
      const response = await fetch("/api/sleep?" + new URLSearchParams({limit: PAGE, offset: append ? state.offset : 0}), {cache: "no-store"});
      if (!response.ok) throw new Error();
      const page = await response.json();
      if (request !== state.request) return;
      state.items = append ? [...state.items, ...page] : page;
      state.offset = state.items.length;
      $("#load-more").hidden = page.length < PAGE;
      notice("");
      render();
    } catch { if (request === state.request) notice("기록을 불러오지 못했어요. 연결을 확인하고 새로고침해 주세요.", true); }
  }
  function summary() {
    // Main sleep per wake-up day over the last seven days, today last.
    const days = Array.from({length: 7}, (_, i) => { const day = new Date(); day.setHours(0, 0, 0, 0); day.setDate(day.getDate() - 6 + i); return day; });
    const totals = days.map((day) => state.items.filter((item) => { const end = new Date(item.sleep_end); end.setHours(0, 0, 0, 0); return end.getTime() === day.getTime(); })
      .reduce((sum, item) => sum + item.duration_minutes, 0));
    const known = totals.filter(Boolean);
    const box = node("div", null, "sleep-week");
    const head = node("p", null, "sleep-week-head");
    head.append(node("span", "최근 7일 평균"), node("strong", known.length ? length(Math.round(known.reduce((a, b) => a + b, 0) / known.length)) : "–", "num"));
    const bars = node("div", null, "sleep-bars");
    const top = Math.max(600, ...totals); // a 10-hour scale, so 5 and 8 hours look different
    days.forEach((day, index) => {
      const bar = node("span", null, "sleep-bar" + (index === 6 ? " today" : ""));
      const fill = node("i"); fill.style.height = Math.round(totals[index] / top * 100) + "%";
      bar.append(fill, node("small", index === 6 ? "오늘" : WEEKDAYS[day.getDay()]));
      bar.setAttribute("aria-label", (day.getMonth() + 1) + "월 " + day.getDate() + "일 " + (totals[index] ? length(totals[index]) : "기록 없음"));
      bars.append(bar);
    });
    box.append(head, bars);
    return box;
  }
  function render() {
    $("#sleep-summary").replaceChildren(summary());
    const rows = [];
    let month = null;
    for (const item of state.items) {
      const end = new Date(item.sleep_end), key = end.getFullYear() + "-" + end.getMonth();
      if (key !== month) { month = key; rows.push(node("p", (end.getMonth() + 1) + "월", "bm-month")); }
      const row = node("button", null, "sleep-row");
      row.type = "button";
      row.append(node("span", end.getDate() + " " + WEEKDAYS[end.getDay()], "bm-date"), node("span", clock(item.sleep_start) + " → " + clock(item.sleep_end), "num sleep-times"));
      const amount = node("strong", length(item.duration_minutes), "num");
      if (item.sleep_type === "nap") amount.prepend(node("small", "낮잠", "sleep-nap"));
      row.append(amount);
      row.setAttribute("aria-label", (end.getMonth() + 1) + "월 " + end.getDate() + "일 " + (item.sleep_type === "nap" ? "낮잠 " : "") + length(item.duration_minutes) + ", 고치기");
      row.addEventListener("click", () => window.FitQuick.open("sleep", {record: item, onSaved: () => load()}).catch(() => {}));
      rows.push(row);
    }
    if (!state.items.length) rows.push(node("p", "아직 수면 기록이 없어요. ‘+ 기록’으로 남겨 보세요.", "empty-state"));
    $("#sleep-rows").replaceChildren(...rows);
  }
  $("#rec-add").addEventListener("click", () => window.FitQuick.open("sleep", {onSaved: () => load()}).catch(() => {}));
  $("#load-more").addEventListener("click", () => load(true));
  window.fitlogOnSync = () => load();
  load();
})();
