"use strict";
// 몸·추이: latest body composition within the chosen period, trend lines, and the last 7 nights of sleep.
const $ = (id) => document.getElementById(id);
const SVG = "http://www.w3.org/2000/svg";
const number = (value, digits = 1) => new Intl.NumberFormat("ko-KR", {maximumFractionDigits: digits}).format(value);
const pad = (value) => String(value).padStart(2, "0");
const keyOf = (date) => date.getFullYear() + "-" + pad(date.getMonth() + 1) + "-" + pad(date.getDate());
const shortDate = (value) => { const date = new Date(value); return (date.getMonth() + 1) + "/" + date.getDate(); };
const zone = Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Seoul";
const metrics = [
  {key: "weight", label: "체중", unit: "kg"},
  {key: "skeletal_muscle", label: "골격근량", unit: "kg"},
  {key: "body_fat", label: "체지방률", unit: "%"},
];
const state = {days: 90, request: 0, sleepGoal: null, sleep: null};

function element(tag, text, className) {
  const item = document.createElement(tag);
  if (text != null) item.textContent = text;
  if (className) item.className = className;
  return item;
}
function svg(tag, attributes) {
  const item = document.createElementNS(SVG, tag);
  for (const [name, value] of Object.entries(attributes)) item.setAttribute(name, value);
  return item;
}
function notice(text) { $("notice").textContent = text; }
async function api(path) {
  const response = await fetch("/api" + path, {cache: "no-store", signal: AbortSignal.timeout(15000)});
  if (!response.ok) throw new Error("기록을 불러오지 못했습니다. 연결을 확인하고 새로고침해 주세요.");
  return response.json();
}
// Every record in [from, to), paging past the API's 100 limit; oldest first.
async function all(path, from, to) {
  const items = [];
  for (let offset = 0; ; offset += 100) {
    const page = await api(path + "?" + new URLSearchParams({from_at: from.toISOString(), to_at: to.toISOString(), limit: 100, offset}));
    items.push(...page);
    if (page.length < 100) return items.reverse();
  }
}

function changeText(change, unit) {
  if (change == null) return "";
  if (Math.abs(change) < 0.05) return "변화 없음";
  return (change > 0 ? "+" : "−") + number(Math.abs(change)) + unit;
}

function renderComposition(records) {
  const rows = $("composition-rows"); rows.replaceChildren();
  const latest = records.at(-1);
  $("measured-at").textContent = latest ? new Date(latest.measured_at).toLocaleString("ko-KR", {month: "long", day: "numeric", hour: "2-digit", minute: "2-digit"}) + " 측정" : "";
  for (const metric of metrics) {
    const series = records.filter((record) => record[metric.key] != null);
    if (!series.length) continue;
    const values = series.map((record) => record[metric.key]);
    const current = values.at(-1), low = Math.min(...values), high = Math.max(...values);
    const row = element("div", null, "composition-row");
    const head = element("p", null, "composition-head");
    const value = element("span", null, "composition-value");
    value.append(element("strong", number(current)), " " + metric.unit);
    const change = values.length > 1 ? current - values.at(-2) : null;
    if (change != null) value.append(" ", element("b", changeText(change, metric.unit), "composition-change"));
    head.append(element("span", metric.label), value);
    const track = element("span", null, "range-track");
    const fill = element("span", null, "range-fill");
    fill.style.width = (high > low ? 6 + (current - low) / (high - low) * 94 : 100).toFixed(1) + "%";
    track.append(fill);
    track.setAttribute("role", "img");
    track.setAttribute("aria-label", `${metric.label} ${number(current)}${metric.unit}, 기간 최저 ${number(low)} 최고 ${number(high)}`);
    const scale = element("p", null, "range-scale");
    scale.append(element("span", "최저 " + number(low)), element("span", series.length + "회 측정"), element("span", "최고 " + number(high)));
    row.append(head, track, scale);
    rows.append(row);
  }
  if (!rows.children.length) rows.append(element("p", "이 기간에는 체중·신체 측정 기록이 없어요.", "empty-state"));
}

function trendChart(metric, series, from, to) {
  const card = element("figure", null, "trend");
  const values = series.map((record) => record[metric.key]);
  const caption = element("figcaption");
  const summary = element("span", null, "trend-summary");
  summary.append(number(values[0]) + " → ", element("strong", number(values.at(-1))));
  caption.append(element("b", metric.label + " " + metric.unit), summary);
  const width = 320, height = 90, low = Math.min(...values), high = Math.max(...values);
  const spread = high - low || Math.max(Math.abs(high) * 0.02, 1);
  const x = (record) => ((new Date(record.measured_at) - from) / (to - from) * (width - 8) + 4).toFixed(1);
  const base = high > low ? low : low - spread / 2; // a flat series sits mid-height
  const y = (value) => (height - 8 - (value - base) / spread * (height - 16)).toFixed(1);
  const chart = svg("svg", {viewBox: `0 0 ${width} ${height}`, preserveAspectRatio: "none", class: "trend-svg", role: "img",
    "aria-label": `${metric.label} ${shortDate(series[0].measured_at)} ${number(values[0])}${metric.unit}에서 ${shortDate(series.at(-1).measured_at)} ${number(values.at(-1))}${metric.unit}`});
  for (const line of [8, height / 2, height - 8]) chart.append(svg("line", {x1: 0, x2: width, y1: line, y2: line, class: "trend-grid"}));
  if (series.length > 1) chart.append(svg("polyline", {points: series.map((record) => x(record) + "," + y(record[metric.key])).join(" "), class: "trend-line"}));
  const last = series.at(-1);
  chart.append(svg("circle", {cx: x(last), cy: y(last[metric.key]), r: 4, class: "trend-dot"}));
  card.append(caption, chart);
  return card;
}

function renderTrends(records, from, to) {
  const charts = $("trend-charts"); charts.replaceChildren();
  for (const metric of metrics) {
    const series = records.filter((record) => record[metric.key] != null);
    if (series.length) charts.append(trendChart(metric, series, from, to));
  }
  if (!charts.children.length) charts.append(element("p", "추이를 그릴 측정 기록이 없어요.", "empty-state"));
  const ticks = element("p", null, "trend-axis");
  ticks.append(element("span", shortDate(from)), element("span", "오늘"));
  if (charts.querySelector("figure")) charts.append(ticks);
}

function renderSleep(records) {
  const bars = $("sleep-bars");
  bars.querySelectorAll(".sleep-day").forEach((bar) => bar.remove());
  const today = new Date(), days = [];
  for (let back = 6; back >= 0; back--) { const day = new Date(today); day.setDate(today.getDate() - back); days.push(keyOf(day)); }
  const totals = days.map((day) => records.filter((record) => keyOf(new Date(record.sleep_end)) === day).reduce((sum, record) => sum + record.duration_minutes, 0));
  const goal = state.sleepGoal || 0, scale = Math.max(goal * 1.25, ...totals, 60);
  $("sleep-goal-line").hidden = !goal;
  if (goal) $("sleep-goal-line").style.bottom = "calc((100% - 22px) * " + (goal / scale).toFixed(3) + " + 22px)";
  const names = ["일", "월", "화", "수", "목", "금", "토"];
  days.forEach((day, index) => {
    const bar = element("div", null, "sleep-day" + (index === 6 ? " is-today" : ""));
    const minutes = totals[index];
    bar.setAttribute("role", "img");
    bar.setAttribute("aria-label", `${day.slice(5).replace("-", "월 ")}일 ${minutes ? Math.floor(minutes / 60) + "시간 " + minutes % 60 + "분" : "기록 없음"}`);
    const column = element("span", null, "sleep-column");
    const fill = element("span", null, "sleep-fill");
    fill.style.height = (minutes / scale * 100).toFixed(1) + "%";
    column.append(fill);
    const date = new Date(day + "T12:00:00");
    bar.append(column, element("span", index === 6 ? "오늘" : names[date.getDay()], "sleep-label"));
    bars.append(bar);
  });
  const nights = totals.filter(Boolean);
  const average = nights.length ? Math.round(nights.reduce((a, b) => a + b, 0) / nights.length) : null;
  $("sleep-note").textContent = [average != null && "7일 평균 " + Math.floor(average / 60) + "시간 " + average % 60 + "분", goal && "점선 목표 " + Math.floor(goal / 60) + "시간" + (goal % 60 ? " " + goal % 60 + "분" : "")].filter(Boolean).join(" · ");
}

async function load() {
  const request = ++state.request;
  const to = new Date(), from = new Date(to);
  from.setDate(from.getDate() - state.days);
  const sleepFrom = new Date(to); sleepFrom.setHours(0, 0, 0, 0); sleepFrom.setDate(sleepFrom.getDate() - 6);
  const show = ({records, sleep}) => {
    state.sleep = sleep;
    $("trend-title").textContent = {30: "1개월", 90: "3개월", 365: "1년"}[state.days] + " 변화";
    $("trend-range").textContent = shortDate(from) + " ~ 오늘";
    renderComposition(records); renderTrends(records, from, to); renderSleep(sleep);
  };
  // Show what this phone saved last time for this period (app.js show-then-refresh), then the server's copy.
  const key = "body:" + state.days + ":" + keyOf(to), cached = window.fitlogCache.get(key);
  if (cached) show(cached);
  try {
    const [records, sleep] = await Promise.all([all("/body-metrics", from, to), all("/sleep", sleepFrom, to)]);
    if (request !== state.request) return;
    notice("");
    window.fitlogCache.set(key, {records, sleep});
    show({records, sleep});
  } catch (error) { if (request === state.request) notice(error.message); }
}

for (const button of document.querySelectorAll(".period button")) {
  button.addEventListener("click", () => {
    state.days = Number(button.dataset.days);
    for (const other of document.querySelectorAll(".period button")) other.setAttribute("aria-pressed", String(other === button));
    load();
  });
}
// The sleep goal only adds the dotted line, so the records do not wait for it.
state.sleepGoal = window.fitlogCache.get("dashboard:" + zone)?.sleep_goal_minutes ?? null;
load();
api("/dashboard?timezone=" + encodeURIComponent(zone)).then((data) => {
  window.fitlogCache.set("dashboard:" + zone, data);
  state.sleepGoal = data.sleep_goal_minutes;
  if (state.sleep) renderSleep(state.sleep);
}).catch(() => {});
