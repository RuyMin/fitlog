"use strict";
// 운동 통계: answer first. A period tab (주·월·3개월·1년) loads at once with the period before it, for a one-line
// summary and the change of each number; then sets over time, sets per body part (with a body part left
// alone lately) and each exercise's best weight. Exact dates and unticked sets live in the filter sheet.
(() => {
  const $ = (id) => document.getElementById(id);
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"];
  const BEFORE = {week: "지난주", month: "지난달", quarter: "직전 3개월", year: "직전 1년", custom: "직전 같은 기간"};
  const state = {period: "month", custom: null, incomplete: false, request: 0};
  try { Object.assign(state, JSON.parse(sessionStorage.getItem("statistics:view") || "{}")); } catch {}
  const number = (value, digits = 0) => new Intl.NumberFormat("ko-KR", {maximumFractionDigits: digits}).format(value);
  const day = (date) => date.getFullYear() + "-" + String(date.getMonth() + 1).padStart(2, "0") + "-" + String(date.getDate()).padStart(2, "0");
  const parse = (text) => { const [y, m, d] = text.split("-").map(Number); return new Date(y, m - 1, d); };
  const addDays = (date, days) => { const next = new Date(date); next.setDate(next.getDate() + days); return next; };
  const between = (a, b) => Math.round((b - a) / 86400000);
  function node(tag, text, className) { const item = document.createElement(tag); if (text != null) item.textContent = text; if (className) item.className = className; return item; }
  const volumeText = (value) => value >= 1000 ? number(value / 1000, 1) + "t" : number(value) + "kg";
  // Korean particles follow the last syllable: 과/와, 을/를.
  const batchim = (word) => { const code = word.charCodeAt(word.length - 1) - 0xac00; return code >= 0 && code < 11172 && code % 28 !== 0; };
  const particle = (word, withFinal, withoutFinal) => word + (batchim(word) ? withFinal : withoutFinal);

  // The period shown and the one just before it, the same length (a month: the same days of last month).
  function ranges() {
    const today = new Date(); today.setHours(0, 0, 0, 0);
    if (state.custom) {
      const from = parse(state.custom.from), to = parse(state.custom.to), length = between(from, to) + 1;
      return {from, to, before: [addDays(from, -length), addDays(from, -1)]};
    }
    if (state.period === "week") {
      const monday = addDays(today, -((today.getDay() + 6) % 7));
      return {from: monday, to: today, before: [addDays(monday, -7), addDays(today, -7)]};
    }
    if (state.period === "month") {
      const first = new Date(today.getFullYear(), today.getMonth(), 1);
      const lastFirst = new Date(today.getFullYear(), today.getMonth() - 1, 1);
      const lastEnd = new Date(today.getFullYear(), today.getMonth() - 1, Math.min(today.getDate(), new Date(today.getFullYear(), today.getMonth(), 0).getDate()));
      return {from: first, to: today, before: [lastFirst, lastEnd]};
    }
    const length = state.period === "quarter" ? 90 : 365;
    const from = addDays(today, -(length - 1));
    return {from, to: today, before: [addDays(from, -length), addDays(from, -1)]};
  }
  async function get(from, to) {
    const response = await fetch("/api/statistics?" + new URLSearchParams({date_from: day(from), date_to: day(to), timezone: zone, completed_only: String(!state.incomplete)}), {cache: "no-store"});
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "통계를 불러오지 못했어요.");
    return data;
  }

  async function load() {
    const request = ++state.request;
    try { sessionStorage.setItem("statistics:view", JSON.stringify({period: state.period, custom: state.custom, incomplete: state.incomplete})); } catch {}
    document.querySelectorAll(".stats-periods button").forEach((button) => button.setAttribute("aria-selected", String(!state.custom && button.dataset.period === state.period)));
    $("filter-dot").hidden = !state.custom && !state.incomplete;
    const range = ranges();
    $("range-label").textContent = (range.from.getMonth() + 1) + "월 " + range.from.getDate() + "일 ~ " + (day(range.to) === day(new Date()) ? "오늘" : (range.to.getMonth() + 1) + "월 " + range.to.getDate() + "일")
      + (state.incomplete ? " · 체크 안 한 세트 포함" : "");
    try {
      const [now, before] = await Promise.all([get(range.from, range.to), get(...range.before).catch(() => null)]);
      if (request !== state.request) return;
      $("notice").textContent = "";
      render(now, before, range);
    } catch (error) { if (request === state.request) { $("notice").textContent = error.message; $("notice").className = "error"; } }
  }

  function render(now, before, range) {
    const kind = state.custom ? "custom" : state.period;
    const a = now.summary, b = before?.summary;
    // One line: the biggest lift gain over 3 months or a year, else volume against the period before, else counts.
    const gains = now.exercises.filter((item) => item.max_weight != null && item.first_max_weight != null && item.max_weight > item.first_max_weight)
      .sort((x, y) => (y.max_weight - y.first_max_weight) - (x.max_weight - x.first_max_weight));
    const title = $("headline"); title.replaceChildren();
    const accent = (text, down = false) => node("span", text, "stats-accent" + (down ? " down" : ""));
    if (!a.workouts_count) title.append("이 기간에는 운동 기록이 없어요");
    else if ((kind === "quarter" || kind === "year") && gains.length) {
      const top = gains[0];
      title.append(kind === "year" ? "1년 동안" : "석 달 동안", document.createElement("br"), accent(top.name + " " + number(top.max_weight - top.first_max_weight, 1) + "kg 늘었어요"));
    } else if (a.volume_kg_reps && b?.volume_kg_reps) {
      const percent = Math.round((a.volume_kg_reps - b.volume_kg_reps) / b.volume_kg_reps * 100);
      title.append(BEFORE[kind] + "보다", document.createElement("br"), accent("볼륨이 " + Math.abs(percent) + "% " + (percent >= 0 ? "늘었어요" : "줄었어요"), percent < 0));
    } else if (b && a.workouts_count !== b.workouts_count) {
      const diff = a.workouts_count - b.workouts_count;
      title.append(BEFORE[kind] + "보다", document.createElement("br"), accent("운동을 " + Math.abs(diff) + "번 " + (diff > 0 ? "더 했어요" : "덜 했어요"), diff < 0));
    } else title.append("이 기간에", document.createElement("br"), accent(a.workouts_count + "번 운동했어요"));
    const delta = (x, y, percent) => y == null || x == null ? "" : percent ? (y ? (x >= y ? "+" : "−") + Math.abs(Math.round((x - y) / y * 100)) + "%" : "") : (x >= y ? "+" : "−") + number(Math.abs(x - y));
    const kpis = [["운동", a.workouts_count + "회", delta(a.workouts_count, b?.workouts_count)], ["세트", number(a.sets_count), delta(a.sets_count, b?.sets_count)],
      ["볼륨", a.volume_kg_reps ? volumeText(a.volume_kg_reps) : "–", delta(a.volume_kg_reps, b?.volume_kg_reps, true)]];
    $("kpis").replaceChildren(...kpis.map(([label, value, change]) => {
      const box = node("div", null, "stats-kpi");
      box.append(node("span", label), node("strong", value, "num"), node("small", change, "num" + (change.startsWith("−") ? " down" : "")));
      return box;
    }));
    $("kpi-note").textContent = b ? particle(BEFORE[kind] + (kind === "month" ? " 같은 날까지" : ""), "과", "와") + " 비교" : "";
    renderBars(now, range);
    renderParts(now, range);
    renderLifts(now);
  }

  // Sets over time: by day up to two weeks, by week up to about a month and a half, by month beyond.
  function renderBars(now, range) {
    const length = between(range.from, range.to) + 1;
    let groups;
    if (length <= 14) {
      groups = now.daily.map((item) => [WEEKDAYS[parse(item.date).getDay()], item.sets_count]);
      $("bars-title").textContent = "요일별 세트";
    } else if (length <= 45) {
      groups = now.weekly.map((item, index) => [(index + 1) + "주", item.sets_count]);
      $("bars-title").textContent = "주별 세트";
    } else {
      const months = new Map();
      for (const item of now.daily) { const key = item.date.slice(0, 7); months.set(key, (months.get(key) || 0) + item.sets_count); }
      groups = [...months].map(([key, sets]) => [Number(key.slice(5)) + "월", sets]);
      $("bars-title").textContent = "월별 세트";
    }
    const top = Math.max(1, ...groups.map((group) => group[1]));
    $("bars").replaceChildren(...groups.map(([label, sets], index) => {
      const column = node("div", null, "stats-bar" + (index === groups.length - 1 ? " last" : ""));
      const bar = node("i"); bar.style.height = Math.max(3, Math.round(sets / top * 84)) + "px";
      column.append(node("span", sets ? number(sets) : "", "num"), bar, node("small", label));
      column.setAttribute("aria-label", label + " " + sets + "세트");
      return column;
    }));
  }

  // Sets per body part, and the part trained in this period but not in the last two weeks.
  function renderParts(now, range) {
    const parts = new Map();
    for (const item of now.exercises) {
      const part = item.body_part || "기타";
      const entry = parts.get(part) || {sets: 0, last: null, names: []};
      entry.sets += item.sets_count;
      entry.names.push([item.name, item.sets_count]);
      const last = item.daily_volume.at(-1)?.date;
      if (last && (!entry.last || last > entry.last)) entry.last = last;
      parts.set(part, entry);
    }
    const rows = [...parts].sort((x, y) => y[1].sets - x[1].sets);
    const top = Math.max(1, ...rows.map(([, entry]) => entry.sets));
    $("parts").replaceChildren(...rows.map(([part, entry]) => {
      const row = node("div", null, "stats-part");
      const track = node("span", null, "stats-track"), fill = node("i");
      fill.style.width = Math.round(entry.sets / top * 100) + "%";
      if (entry.sets < top * 0.2) fill.className = "low";
      track.append(fill);
      row.append(node("span", part), track, node("span", number(entry.sets), "num"));
      return row;
    }));
    if (!rows.length) $("parts").append(node("p", "이 기간에는 세트가 없어요.", "empty-state"));
    const cutoff = day(addDays(new Date(), -14));
    const left = between(range.from, range.to) >= 27 ? rows.filter(([part, entry]) => part !== "기타" && part !== "유산소" && entry.last && entry.last < cutoff)
      .sort((x, y) => x[1].last.localeCompare(y[1].last))[0] : null;
    const link = $("neglect");
    link.hidden = !left;
    if (left) {
      const [part, entry] = left;
      const weeks = Math.floor(between(parse(entry.last), new Date()) / 7);
      const text = node("span", null, "stats-neglect-text");
      const strong = node("b", part);
      text.append(strong, particle(part, "을", "를").slice(part.length) + " " + weeks + "주째 안 했어요", document.createElement("br"),
        node("small", entry.names.sort((x, y) => y[1] - x[1]).slice(0, 2).map((name) => name[0]).join(" · ")));
      link.replaceChildren(text, node("span", "운동하러 가기", "stats-neglect-go"));
    }
  }

  // Best weight per exercise, most trained first, with how far it moved since the period's first session.
  function renderLifts(now) {
    const lifts = now.exercises.filter((item) => item.max_weight != null && item.max_weight > 0).sort((x, y) => y.sets_count - x.sets_count).slice(0, 8);
    $("lifts").replaceChildren(...lifts.map((item) => {
      const row = node("div", null, "stats-lift");
      const best = node("span", number(item.max_weight, 1), "num"); best.append(node("small", " kg"));
      const moved = item.first_max_weight == null ? null : Math.round((item.max_weight - item.first_max_weight) * 10) / 10;
      row.append(node("span", item.name, "stats-lift-name"), best, node("span", moved ? "+" + number(moved, 1) : "–", "num" + (moved ? " up" : "")));
      return row;
    }));
    if (!lifts.length) $("lifts").append(node("p", "무게를 적은 세트가 없어요.", "empty-state"));
  }

  document.querySelectorAll(".stats-periods button").forEach((button) => button.addEventListener("click", () => {
    state.period = button.dataset.period; state.custom = null; load();
  }));
  document.querySelectorAll(".stats-help-button").forEach((button) => button.addEventListener("click", () => {
    const help = $(button.getAttribute("aria-controls")), open = help.hidden;
    help.hidden = !open; button.setAttribute("aria-expanded", String(open));
  }));
  const dialog = $("filter-dialog"), form = $("filter-form");
  $("filter-open").addEventListener("click", () => {
    const range = ranges();
    form.elements.date_from.value = state.custom ? state.custom.from : day(range.from);
    form.elements.date_to.value = state.custom ? state.custom.to : day(range.to);
    form.elements.include_incomplete.checked = state.incomplete;
    form.querySelector(".form-error").textContent = "";
    dialog.showModal();
  });
  dialog.querySelector("[data-close]").addEventListener("click", () => dialog.close());
  dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const from = form.elements.date_from.value, to = form.elements.date_to.value, range = ranges();
    const changed = from && to && (from !== day(range.from) || to !== day(range.to) || state.custom);
    if (changed) {
      if (from > to) { form.querySelector(".form-error").textContent = "시작이 끝보다 늦어요."; return; }
      if (between(parse(from), parse(to)) >= 366) { form.querySelector(".form-error").textContent = "최대 1년까지 볼 수 있어요."; return; }
      state.custom = {from, to};
    }
    state.incomplete = form.elements.include_incomplete.checked;
    dialog.close();
    load();
  });
  $("filter-reset").addEventListener("click", () => { state.custom = null; state.incomplete = false; dialog.close(); load(); });
  window.fitlogOnSync = load;
  load();
})();
