"use strict";
// Home: the one next thing to do (a routine's turn, last night's sleep, the protein left …) with a short
// list of the rest, then today's four numbers against their goals and the week. Before the first record
// a checklist takes their place.
const $home = (id) => document.getElementById(id);
const formatNumber = (value) => new Intl.NumberFormat("ko-KR", {maximumFractionDigits:1}).format(value);
const hoursText = (minutes) => Math.floor(minutes / 60) + ":" + String(Math.round(minutes % 60)).padStart(2, "0");
const lengthText = (minutes) => (minutes >= 60 ? Math.floor(minutes / 60) + "시간 " : "") + Math.round(minutes % 60) + "분";
const homeZone = Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Seoul";
const homeToday = new Intl.DateTimeFormat("en-CA", {timeZone: homeZone}).format(new Date());
const ALL_KINDS = ["work", "meal", "body", "sleep"];
// `me` starts as the saved answer, so the home lays out at once; the current one replaces it when it arrives.
const homeState = {data: null, me: window.fitlogCache.get("me"), routines: null, workouts: null, exercises: null};

// ---- 오늘: four numbers, each with a bar to its goal ---------------------------------------------------
function cell(key, value, goal, bar, note) {
  $home("val-" + key).textContent = value;
  $home("goal-" + key).textContent = goal;
  $home("bar-" + key).style.width = Math.max(0, Math.min(100, Math.round(bar * 100))) + "%";
  $home("note-" + key).textContent = note;
}
function showToday(data) {
  const next = nextRoutine();
  cell("work", String(data.completed_sets), data.total_sets > data.completed_sets ? " / " + data.total_sets + "세트" : "세트", data.total_sets ? data.completed_sets / data.total_sets : 0,
    data.workouts_count ? data.workout_titles.slice(0, 2).join(" · ") + (data.volume_kg ? " · " + formatNumber(Math.round(data.volume_kg / 100) / 10) + "t" : "")
      : next ? next.name + " 할 차례" : "오늘은 아직");
  const kcal = data.calories;
  cell("kcal", kcal == null ? "–" : formatNumber(Math.round(kcal)), " / " + formatNumber(data.calorie_goal_kcal), (kcal || 0) / data.calorie_goal_kcal,
    !data.meals_count ? "아직 기록 전" : data.meals_count + "끼 · " + (kcal != null && kcal < data.calorie_goal_kcal ? formatNumber(Math.round(data.calorie_goal_kcal - kcal)) + "kcal 남음" : "목표 도달"));
  const protein = data.protein_grams;
  cell("protein", protein == null ? "–" : formatNumber(Math.round(protein)), " / " + formatNumber(data.protein_goal_grams) + "g", (protein || 0) / data.protein_goal_grams,
    protein == null ? "아직 기록 전" : protein >= data.protein_goal_grams ? "목표 달성" : formatNumber(Math.round(data.protein_goal_grams - protein)) + "g 남음");
  const sleep = data.sleep_minutes;
  cell("sleep", sleep == null ? "–" : hoursText(sleep), " / " + hoursText(data.sleep_goal_minutes), (sleep || 0) / data.sleep_goal_minutes,
    sleep == null ? "어젯밤 기록 전" : sleep >= data.sleep_goal_minutes ? "목표 달성" : lengthText(data.sleep_goal_minutes - sleep) + " 모자람");
  const list = $home("week-days"); list.replaceChildren();
  const names = ["월", "화", "수", "목", "금", "토", "일"];
  data.week.forEach((day, index) => {
    const item = document.createElement("li");
    item.className = [day.workout && "workout", day.date === data.date && "today"].filter(Boolean).join(" ");
    item.textContent = names[index];
    item.setAttribute("aria-label", names[index] + "요일" + (day.workout ? " 운동함" : "") + (day.date === data.date ? ", 오늘" : ""));
    list.append(item);
  });
  $home("week-count").textContent = data.week.filter((day) => day.workout).length;
}

// ---- 다음 할 일 -------------------------------------------------------------------------------------
// The routine after the last one done before today (as on the 운동 tab), once the lists are in.
function nextRoutine() {
  const routines = homeState.routines;
  if (!routines?.length || !homeState.workouts) return null;
  const last = homeState.workouts.find((item) => item.workout_date < homeToday && routines.some((routine) => routine.id === item.routine_id));
  if (!last) return routines[0];
  return routines[(routines.findIndex((routine) => routine.id === last.routine_id) + 1) % routines.length];
}
function quick(kind) { return () => window.FitQuick.open(kind, {onSaved: () => window.fitlogOnSync?.()}).catch(() => {}); }
// Things still to do today, most useful first for the hour, and things already done.
function todo(data, tracking) {
  const hour = new Date().getHours(), pending = [], done = [];
  const has = (kind) => tracking.includes(kind);
  if (has("work")) {
    const left = data.total_sets - data.completed_sets;
    if (data.workouts_count && left > 0) pending.push({kind: "work", title: ["", data.workout_titles[0], " 이어서 하기"], detail: data.total_sets + "세트 중 " + data.completed_sets + "세트 했어요",
      label: "이어서 하기", go: "/workouts", line: data.workout_titles[0] + " 이어서 하기 · " + data.completed_sets + "/" + data.total_sets + "세트"});
    else if (data.workouts_count) done.push(data.workout_titles[0] + " 운동 끝 · " + data.completed_sets + "세트");
    else if (hour < 22) {
      const routine = nextRoutine();
      const names = routine && homeState.exercises ? routine.items.map((item) => (homeState.exercises.find((exercise) => exercise.id === item.exercise_id)?.name || "종목") + " " + item.sets).join(" · ") : "";
      pending.push(routine ? {kind: "work", accent: routine.name, title: ["오늘은 ", routine.name, " 할 차례예요"], detail: names, label: routine.name + " 시작", go: "/workouts?start=" + routine.id, line: routine.name + " 할 차례"}
        : {kind: "work", title: ["오늘 ", "운동", "을 시작해 볼까요?"], detail: "종목을 고르면 지난번 무게로 채워져요", label: "운동하러 가기", go: "/workouts", line: "운동 시작하기"});
    }
  }
  if (has("sleep")) {
    if (data.sleep_minutes != null) done.push("수면 " + lengthText(data.sleep_minutes));
    else if (hour < 15) pending.push({kind: "sleep", title: ["어젯밤 ", "수면", "을 기록할까요?"], detail: "평소 잠든 시각으로 채워져요", label: "수면 기록하기", go: quick("sleep"), line: "어젯밤 수면 기록하기"});
  }
  if (has("body")) {
    const today = data.latest_weight && new Intl.DateTimeFormat("en-CA", {timeZone: homeZone}).format(new Date(data.latest_weight.measured_at)) === homeToday;
    if (today) done.push("체중 " + formatNumber(data.latest_weight.weight) + "kg");
    else if (hour < 12) pending.push({kind: "body", title: ["아침 ", "체중", "을 재 볼까요?"], detail: data.latest_weight ? "지난번 " + formatNumber(data.latest_weight.weight) + "kg" : "숫자 하나면 돼요",
      label: "체중 기록하기", go: quick("weight"), line: "아침 체중 재기" + (data.latest_weight ? " · 지난번 " + formatNumber(data.latest_weight.weight) + "kg" : "")});
  }
  if (has("meal")) {
    const left = data.protein_goal_grams - (data.protein_grams || 0);
    if (data.meals_count) done.push(data.meals_count + "끼 · " + formatNumber(Math.round(data.calories || 0)) + "kcal");
    if (data.meals_count && hour >= 14 && left > 5) pending.push({kind: "meal", accent: formatNumber(Math.round(left)) + "g", title: ["단백질 ", formatNumber(Math.round(left)) + "g", " 남았어요"],
      detail: "목표 " + formatNumber(data.protein_goal_grams) + "g 중 " + formatNumber(Math.round(data.protein_grams || 0)) + "g 먹었어요", label: "식사 기록하기", go: quick("meal"), line: "단백질 " + formatNumber(Math.round(left)) + "g 남음"});
    else if (!data.meals_count && hour >= 7) pending.push({kind: "meal", title: ["오늘 ", "첫 끼", "를 기록할까요?"], detail: "이름과 열량만 적으면 돼요", label: "식사 기록하기", go: quick("meal"), line: "첫 끼 기록하기"});
  }
  // The workout leads when it is due; in the afternoon the protein left comes before sleep and weight.
  const order = hour >= 14 ? ["work", "meal", "sleep", "body"] : ["work", "sleep", "body", "meal"];
  pending.sort((a, b) => order.indexOf(a.kind) - order.indexOf(b.kind));
  return {pending, done};
}
function showNext(data, tracking) {
  const {pending, done} = todo(data, tracking);
  const card = $home("next"), first = pending[0];
  // The card holds its place from the start (index.html); new words fade in instead of the page jumping.
  const said = first ? first.title.join("") : done.length ? "done" : "rest";
  if (card.dataset.said !== said) { card.classList.remove("next-in"); void card.offsetWidth; card.classList.add("next-in"); }
  card.dataset.said = said;
  card.hidden = false;
  card.classList.remove("pending"); card.removeAttribute("aria-busy");
  card.dataset.kind = first?.kind || "done";
  const title = $home("next-title"); title.replaceChildren();
  if (first) {
    const [before, strong, after] = first.title;
    const mark = document.createElement("span"); mark.className = "next-accent"; mark.textContent = strong;
    title.append(before, mark, after);
  } else title.textContent = done.length ? "오늘 할 일을 다 했어요" : "오늘은 쉬어 가는 날";
  $home("next-detail").textContent = first?.detail || "";
  const action = $home("next-action");
  action.hidden = !first;
  if (first) { action.textContent = first.label; action.onclick = typeof first.go === "string" ? () => location.assign(first.go) : first.go; }
  const rows = [...pending.slice(1).map((item) => ({text: item.line, go: item.go, kind: item.kind})), ...done.map((text) => ({text, done: true}))].slice(0, 3);
  $home("next-list").replaceChildren(...rows.map((row) => {
    const item = document.createElement("li");
    const box = document.createElement(row.done ? "span" : "button");
    if (!row.done) { box.type = "button"; box.addEventListener("click", typeof row.go === "string" ? () => location.assign(row.go) : row.go); }
    box.className = "next-row" + (row.done ? " done" : " kind-" + row.kind);
    const mark = document.createElement("span"); mark.className = "next-mark"; mark.setAttribute("aria-hidden", "true");
    const text = document.createElement("span"); text.textContent = row.text;
    box.append(mark, text);
    if (row.done) box.setAttribute("aria-label", "끝남: " + row.text);
    item.append(box);
    return item;
  }));
}

// What the account records (설정 › 홈에 보일 기록) and, until the first record, the 첫 기록 남기기 checklist.
const homeStart = (() => {
  let data;
  window.fitlogMe.then((answer) => {
    homeState.me = answer;
    // A new account answers 무엇을 기록할까요? first; one that already has records never sees it.
    if (answer?.needs_setup) { location.replace("/welcome"); return; }
    paint();
  });
  function step(id, done) {
    $home(id).classList.toggle("done", done);
    return done;
  }
  function paint() {
    const me = homeState.me;
    if (!me || !data) return;
    const tracking = me.tracking || ALL_KINDS;
    for (const element of document.querySelectorAll(".home [data-kind]:not(#next)")) element.hidden = !tracking.includes(element.dataset.kind);
    // Before the first record the numbers and the week are all empty: the checklist takes their place.
    const first = !data.has_records;
    $home("first-day").hidden = $home("first-form").hidden = !first;
    $home("quick-record").hidden = $home("today-card").hidden = first;
    $home("home-title").textContent = first ? "반가워요" : "오늘";
    if (first) { $home("next").hidden = true; return; }  // the checklist takes its place
    showNext(data, tracking);
    $home("step-record-title").textContent = tracking.includes("work") ? "오늘 한 운동 적기" : "오늘 첫 기록 적기";
    const done = [step("step-pick", Boolean(me.tracking)), step("step-record", false), step("step-goal", data.goal_source !== "default")];
    $home("first-day-count").textContent = done.filter(Boolean).length + "/3";
  }
  // The sentence goes to the record sheet's AI box, which turns it into drafts to check and save.
  const text = $home("first-text");
  $home("step-record-link").addEventListener("click", (event) => { event.preventDefault(); text.focus(); });
  for (const chip of document.querySelectorAll(".first-chips button")) {
    chip.addEventListener("click", () => { text.value = chip.textContent; text.focus(); });
  }
  $home("first-form").addEventListener("submit", (event) => {
    event.preventDefault();
    $home("assistant-text").value = text.value.trim();
    openSheet();
  });
  return {show(summary) { data = summary; paint(); }};
})();

function showSummary(data) {
  homeState.data = data;
  showToday(data);
  homeStart.show(data);
}
// Data comes through app.js (fitlogShow): the saved copy first, then the current one.
async function loadSummary() {
  let shown = false;
  try {
    await window.fitlogShow(window.fitlogData.dashboard, (data) => { showSummary(data); shown = true; });
  } catch {
    if (shown) return;
    $home("next").classList.remove("pending"); $home("next").removeAttribute("aria-busy");
    $home("next-title").textContent = "연결 후 새로고침해 주세요";
  }
}
// Routines, recent sessions and exercise names only shape the next-thing card, so they load beside it.
async function loadLists() {
  const routines = fetch("/api/routines", {cache: "no-store"}).then((response) => response.ok ? response.json() : []).catch(() => []);
  await Promise.all([
    window.fitlogShow(window.fitlogData.workouts, (items) => { homeState.workouts = items; }).catch(() => {}),
    window.fitlogShow(window.fitlogData.exercises, (items) => { homeState.exercises = items; }).catch(() => {}),
    routines.then((items) => { homeState.routines = items; })
  ]);
  if (homeState.data) showSummary(homeState.data);
}

// The record sheet opens from the ＋ menu item (/#record), the quick-record bar and the photo button.
const sheet = $home("record-sheet");
function openSheet() {
  if (!sheet.open) sheet.showModal();
  window.FitQuick?.hints().then((hints) => {
    for (const [kind, text] of Object.entries(hints)) { const line = sheet.querySelector('[data-hint="' + kind + '"]'); if (line) line.textContent = text; }
  }).catch(() => {});
}
// Meal, weight and sleep open a quick sheet in place; saving refreshes today's numbers.
sheet.querySelectorAll("[data-quick]").forEach((tile) => tile.addEventListener("click", () => {
  sheet.close();
  window.FitQuick.open(tile.dataset.quick, {onSaved: () => window.fitlogOnSync?.()}).catch(() => {});
}));
// The meal sheet's camera button hands over to the AI photo flow here.
window.fitlogPhotoRecord = () => { openSheet(); if (!$home("assistant-form").hidden) $home("assistant-photo-input").click(); };
sheet.addEventListener("close", () => { if (location.hash === "#record") history.replaceState(null, "", location.pathname + location.search); });
sheet.addEventListener("click", (event) => { if (event.target === sheet) sheet.close(); });
$home("sheet-close").addEventListener("click", () => sheet.close());
$home("quick-photo").addEventListener("click", () => window.fitlogPhotoRecord());
window.addEventListener("hashchange", () => { if (location.hash === "#record") openSheet(); });
if (location.hash === "#record") openSheet();

window.fitlogOnSync = () => { loadSummary(); loadLists(); };
loadSummary();
loadLists();
