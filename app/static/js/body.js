"use strict";
// 몸: two cards, each the latest value with a small trend (weight with muscle and fat; last night's sleep with
// the week), a line into the workout statistics, and quick ＋ buttons. Tapping a card opens its full page.
(() => {
  const $ = (id) => document.getElementById(id);
  const WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"];
  const SVG = "http://www.w3.org/2000/svg";
  const one = (value) => new Intl.NumberFormat("ko-KR", {minimumFractionDigits: 1, maximumFractionDigits: 1}).format(value);
  const signed = (value, unit = "") => (value > 0 ? "+" : value < 0 ? "−" : "") + one(Math.abs(value)) + unit;
  const length = (minutes) => Math.floor(minutes / 60) + "시간 " + (minutes % 60) + "분";
  const dayKey = (value) => { const date = new Date(value); return date.getFullYear() + "-" + (date.getMonth() + 1) + "-" + date.getDate(); };
  const state = {sleepGoal: null, body: null};
  function svg(tag, attrs) { const item = document.createElementNS(SVG, tag); for (const [key, value] of Object.entries(attrs)) item.setAttribute(key, value); return item; }

  // Weight: the latest value, its change over the 3 months, a line, and the latest muscle and fat.
  function renderWeight(records) {
    const weights = records.filter((item) => item.weight != null);
    const last = weights.at(-1);
    $("weight-now").textContent = last ? one(last.weight) : "–";
    const unit = document.createElement("small"); unit.textContent = "kg";
    if (last) $("weight-now").append(unit);
    const change = weights.length > 1 ? Math.round((last.weight - weights[0].weight) * 10) / 10 : null;
    $("weight-change").textContent = change == null ? (last ? "" : "아직 기록이 없어요") : "3개월 " + signed(change, "kg");
    $("weight-change").className = "num" + (change < 0 ? " good" : change > 0 ? " bad" : "");
    $("weight-when").textContent = last ? when(last.measured_at) + " ›" : "기록하기 ›";
    const box = $("weight-spark"); box.replaceChildren();
    box.append(svg("line", {x1: 0, y1: 4, x2: 180, y2: 4, class: "spark-grid"}), svg("line", {x1: 0, y1: 52, x2: 180, y2: 52, class: "spark-grid"}));
    if (weights.length > 1) {
      const values = weights.map((item) => item.weight), low = Math.min(...values), high = Math.max(...values), pad = (high - low) * 0.15 || 0.5;
      const start = new Date(weights[0].measured_at), span = (new Date(last.measured_at) - start) || 1;
      const point = (item) => [(new Date(item.measured_at) - start) / span * 176 + 2, 52 - (item.weight - (low - pad)) / ((high + pad) - (low - pad)) * 48];
      box.append(svg("polyline", {points: weights.map((item) => point(item).map((n) => n.toFixed(1)).join(",")).join(" "), class: "spark-line"}));
      const [x, y] = point(last); box.append(svg("circle", {cx: x, cy: y, r: 3.5, class: "spark-dot"}));
      box.setAttribute("aria-label", "최근 3개월 체중 " + one(values[0]) + "kg에서 " + one(last.weight) + "kg");
    }
    for (const [key, id, betterDown] of [["skeletal_muscle", "muscle", false], ["body_fat", "fat", true]]) {
      const series = records.filter((item) => item[key] != null);
      const latest = series.at(-1);
      $(id + "-now").textContent = latest ? one(latest[key]) : "–";
      const moved = series.length > 1 ? Math.round((latest[key] - series[0][key]) * 10) / 10 : null;
      $(id + "-change").textContent = moved == null || moved === 0 ? "" : signed(moved);
      $(id + "-change").className = "num" + (moved == null || moved === 0 ? "" : (moved < 0) === betterDown ? " good" : " bad");
    }
  }
  function when(value) {
    const date = new Date(value), today = new Date();
    const time = (date.getHours() < 12 ? "오전 " : "오후 ") + ((date.getHours() % 12) || 12) + ":" + String(date.getMinutes()).padStart(2, "0");
    if (dayKey(date) === dayKey(today)) return "오늘 " + time;
    return (date.getMonth() + 1) + "월 " + date.getDate() + "일";
  }

  // Sleep: last night, the week as bars with the goal line, and how far last night was from the goal.
  function renderSleep(records) {
    const days = Array.from({length: 7}, (_, i) => { const day = new Date(); day.setHours(0, 0, 0, 0); day.setDate(day.getDate() - 6 + i); return day; });
    const totals = days.map((day) => records.filter((item) => dayKey(item.sleep_end) === dayKey(day)).reduce((sum, item) => sum + item.duration_minutes, 0));
    const known = totals.filter(Boolean);
    $("sleep-average").textContent = (known.length ? "7일 평균 " + length(Math.round(known.reduce((a, b) => a + b, 0) / known.length)) : "최근 7일 기록 없음") + " ›";
    const last = totals[6];
    $("sleep-last").textContent = last ? length(last) : "기록 전";
    const goal = state.sleepGoal;
    const note = $("sleep-goal-note");
    note.textContent = last && goal ? (last >= goal ? "목표를 채웠어요" : "목표보다 " + length(goal - last).replace(/^0시간 /, "") + " 적어요") : "";
    note.className = last && goal ? (last >= goal ? "good" : "bad") : "";
    const top = Math.max(600, goal || 0, ...totals);
    const bars = $("sleep-bars");
    bars.replaceChildren(...days.map((day, index) => {
      const bar = document.createElement("span");
      bar.className = "body-bar" + (index === 6 ? " today" : "");
      bar.style.height = Math.max(3, Math.round(totals[index] / top * 100)) + "%";
      bar.title = WEEKDAYS[day.getDay()] + " " + (totals[index] ? length(totals[index]) : "기록 없음");
      return bar;
    }));
    if (goal) { const line = document.createElement("span"); line.className = "body-goal"; line.style.bottom = Math.round(goal / top * 100) + "%"; bars.append(line); }
  }

  // This month's sessions and volume against the same days of last month.
  async function renderStats() {
    const today = new Date(), day = (date) => date.getFullYear() + "-" + String(date.getMonth() + 1).padStart(2, "0") + "-" + String(date.getDate()).padStart(2, "0");
    const start = new Date(today.getFullYear(), today.getMonth(), 1);
    const before = new Date(today.getFullYear(), today.getMonth() - 1, 1);
    const beforeEnd = new Date(today.getFullYear(), today.getMonth() - 1, Math.min(today.getDate(), new Date(today.getFullYear(), today.getMonth(), 0).getDate()));
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    const get = (from, to) => fetch("/api/statistics?" + new URLSearchParams({date_from: day(from), date_to: day(to), timezone: zone}), {cache: "no-store"}).then((response) => response.ok ? response.json() : null);
    const [now, then] = await Promise.all([get(start, today), get(before, beforeEnd)]);
    if (!now) { $("stats-line").textContent = "기간별 운동 횟수와 볼륨"; return; }
    const line = $("stats-line"); line.replaceChildren("이번 달 " + now.summary.workouts_count + "회");
    const a = now.summary.volume_kg_reps, b = then?.summary.volume_kg_reps;
    if (a && b) {
      const percent = Math.round((a - b) / b * 100);
      const strong = document.createElement("b"); strong.textContent = Math.abs(percent) + "% " + (percent >= 0 ? "↑" : "↓");
      strong.className = percent >= 0 ? "good" : "bad";
      line.append(" · 볼륨 지난달보다 ", strong);
    }
  }

  function show(data) { state.body = data; renderWeight(data.records); renderSleep(data.sleep); }
  async function load() {
    try {
      await window.fitlogShow(window.fitlogData.body, show);
      $("notice").textContent = "";
    } catch (error) { $("notice").textContent = error.message; }
    renderStats().catch(() => {});
  }
  // The sleep goal only adds the line and the note, so the records do not wait for it.
  function loadAll() {
    load();
    window.fitlogShow(window.fitlogData.dashboard, (data) => {
      state.sleepGoal = data.sleep_goal_minutes;
      if (state.body) renderSleep(state.body.sleep);
    }).catch(() => {});
  }
  // After a quick record the bulk copy is stale: drop it and load again.
  document.querySelectorAll(".body-actions [data-quick]").forEach((button) => button.addEventListener("click", () => {
    window.FitQuick.open(button.dataset.quick, {onSaved: () => { window.fitlogCache.outdate(); loadAll(); }}).catch(() => {});
  }));
  window.fitlogOnSync = loadAll;
  loadAll();
})();
