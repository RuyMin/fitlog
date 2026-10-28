"use strict";
// 체중 · 체성분: weight, skeletal muscle and body fat as three small charts over one period, and a table of
// the measurements below. Tapping a row marks its day on the charts and opens it to edit or delete.
(() => {
  const $ = (selector) => document.querySelector(selector);
  const METRICS = [
    {key: "weight", label: "체중", unit: "kg", color: "var(--body-ink)", betterDown: true},
    {key: "skeletal_muscle", label: "골격근", unit: "kg", color: "var(--accent)", betterDown: false},
    {key: "body_fat", label: "체지방", unit: "%", color: "var(--meal)", betterDown: true}
  ];
  const WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"];
  const state = {days: 90, records: [], picked: null};
  const number = (value) => new Intl.NumberFormat("ko-KR", {minimumFractionDigits: 1, maximumFractionDigits: 1}).format(value);
  const SVG = "http://www.w3.org/2000/svg";
  function svg(tag, attrs) { const item = document.createElementNS(SVG, tag); for (const [key, value] of Object.entries(attrs)) item.setAttribute(key, value); return item; }
  function node(tag, text, className) { const item = document.createElement(tag); if (text != null) item.textContent = text; if (className) item.className = className; return item; }
  function notice(text, error = false) { $("#notice").textContent = text; $("#notice").className = error ? "error" : ""; }

  async function load() {
    const since = new Date(); since.setHours(0, 0, 0, 0); since.setDate(since.getDate() - state.days);
    const records = [];
    try {
      for (let offset = 0; ; offset += 100) {
        const response = await fetch("/api/body-metrics?" + new URLSearchParams({from_at: since.toISOString(), limit: 100, offset}), {cache: "no-store"});
        if (!response.ok) throw new Error();
        const page = await response.json();
        records.push(...page);
        if (page.length < 100) break;
      }
    } catch { notice("기록을 불러오지 못했어요. 연결을 확인하고 새로고침해 주세요.", true); return; }
    notice("");
    state.records = records.sort((a, b) => new Date(b.measured_at) - new Date(a.measured_at));
    if (!state.records.some((item) => item.id === state.picked)) state.picked = null;
    render();
  }

  // One small chart: grid, the line through the measured points, min/max at the right, the picked day's line.
  function chart(metric, start, end) {
    const points = state.records.filter((item) => item[metric.key] != null).map((item) => ({at: new Date(item.measured_at), value: item[metric.key], id: item.id})).reverse();
    const row = node("div", null, "bm-chart");
    const side = node("div", null, "bm-side");
    side.append(node("span", metric.label, "bm-label"));
    const width = 226, top = 4, bottom = 60, span = end - start;
    const box = svg("svg", {viewBox: "0 0 260 64", role: "img"});
    for (const y of [top, bottom]) box.append(svg("line", {x1: 0, y1: y, x2: width, y2: y, class: "bm-grid"}));
    box.append(svg("line", {x1: 0, y1: 32, x2: width, y2: 32, class: "bm-grid bm-grid-mid"}));
    for (let i = 0; i <= 3; i++) box.append(svg("line", {x1: width * i / 3, y1: top, x2: width * i / 3, y2: bottom, class: "bm-grid bm-grid-mid"}));
    if (!points.length) {
      side.append(node("strong", "–", "bm-value"));
      box.setAttribute("aria-label", metric.label + " 기록 없음");
      const empty = svg("text", {x: width / 2, y: 36, "text-anchor": "middle", class: "bm-empty"}); empty.textContent = "이 기간에 기록이 없어요";
      box.append(empty);
      row.append(side, box);
      return row;
    }
    const values = points.map((point) => point.value);
    const low = Math.min(...values), high = Math.max(...values), pad = (high - low) * 0.15 || 0.5;
    const xOf = (at) => Math.max(0, Math.min(width, (at - start) / span * width));
    const yOf = (value) => bottom - (value - (low - pad)) / ((high + pad) - (low - pad)) * (bottom - top);
    const picked = state.records.find((item) => item.id === state.picked);
    if (picked) box.append(svg("line", {x1: xOf(new Date(picked.measured_at)), y1: 1, x2: xOf(new Date(picked.measured_at)), y2: 63, class: "bm-mark"}));
    // Colours are CSS variables, so they go in style (presentation attributes do not read var()).
    const line = svg("polyline", {points: points.map((point) => xOf(point.at).toFixed(1) + "," + yOf(point.value).toFixed(1)).join(" "), class: "bm-line"});
    line.style.stroke = metric.color;
    box.append(line);
    points.forEach((point, index) => {
      const dot = svg("circle", {cx: xOf(point.at), cy: yOf(point.value), r: index === points.length - 1 || point.id === state.picked ? 4 : 2.2});
      dot.style.fill = metric.color;
      box.append(dot);
    });
    for (const [y, value] of [[10, high], [63, low]]) { const label = svg("text", {x: 232, y, class: "bm-axis-label"}); label.textContent = number(value); box.append(label); }
    const first = values[0], last = values.at(-1), diff = Math.round((last - first) * 10) / 10;
    box.setAttribute("aria-label", metric.label + " " + number(first) + metric.unit + "에서 " + number(last) + metric.unit);
    const value = node("strong", number(last), "bm-value num"); value.append(node("small", metric.unit));
    const change = node("span", (diff > 0 ? "+" : diff < 0 ? "−" : "") + number(Math.abs(diff)) + metric.unit, "bm-change num");
    if (diff !== 0) change.classList.add((diff < 0) === metric.betterDown ? "good" : "bad");
    side.append(value, change);
    row.append(side, box);
    return row;
  }

  function render() {
    const end = new Date(), start = new Date(end); start.setDate(end.getDate() - state.days);
    const charts = METRICS.map((metric) => chart(metric, start, end));
    const axis = node("div", null, "bm-axis");
    for (let i = 0; i <= 3; i++) {
      const at = new Date(start.getTime() + (end - start) * i / 3);
      axis.append(node("span", i === 3 ? "오늘" : (at.getMonth() + 1) + "/" + at.getDate()));
    }
    $("#bm-charts").replaceChildren(...charts, axis);
    const rows = [];
    let month = null;
    for (const record of state.records) {
      const at = new Date(record.measured_at);
      const key = at.getFullYear() + "-" + at.getMonth();
      if (key !== month) { month = key; rows.push(node("p", (at.getMonth() + 1) + "월", "bm-month")); }
      const row = node("button", null, "bm-row" + (record.id === state.picked ? " picked" : ""));
      row.type = "button";
      row.append(node("span", at.getDate() + " " + WEEKDAYS[at.getDay()], "bm-date"));
      for (const metric of METRICS) {
        const cell = node("span", record[metric.key] == null ? "–" : number(record[metric.key]), "num bm-" + metric.key + (record[metric.key] == null ? " empty" : ""));
        row.append(cell);
      }
      row.setAttribute("aria-label", (at.getMonth() + 1) + "월 " + at.getDate() + "일 " + METRICS.filter((metric) => record[metric.key] != null).map((metric) => metric.label + " " + number(record[metric.key]) + metric.unit).join(", ") + ", 고치기");
      row.addEventListener("click", () => {
        state.picked = record.id;
        render();
        window.FitQuick.open("weight", {record, onSaved: load}).catch(() => {});
      });
      rows.push(row);
    }
    if (!state.records.length) rows.push(node("p", "이 기간에는 기록이 없어요. ‘+ 기록’으로 남겨 보세요.", "empty-state"));
    $("#bm-rows").replaceChildren(...rows);
  }

  document.querySelectorAll(".rec-periods button").forEach((button) => button.addEventListener("click", () => {
    state.days = Number(button.dataset.days);
    document.querySelectorAll(".rec-periods button").forEach((other) => other.setAttribute("aria-pressed", String(other === button)));
    load();
  }));
  $("#rec-add").addEventListener("click", () => window.FitQuick.open("weight", {onSaved: load}).catch(() => {}));
  window.fitlogOnSync = load;
  load();
})();
