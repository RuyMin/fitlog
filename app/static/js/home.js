"use strict";
const $home = (id) => document.getElementById(id);
async function homeGet(path) {
  const response = await fetch(path, {cache: "no-store", signal: AbortSignal.timeout(10000)});
  if (!response.ok) throw new Error("기록을 불러오지 못했습니다.");
  return response.json();
}
const formatNumber = (value) => new Intl.NumberFormat("ko-KR", {maximumFractionDigits:1}).format(value);
const hoursText = (minutes) => Math.floor(minutes / 60) + ":" + String(Math.round(minutes % 60)).padStart(2, "0");
const homeZone = Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Seoul";
const timeOf = (iso) => new Intl.DateTimeFormat("ko-KR", {hour: "2-digit", minute: "2-digit", hour12: false, timeZone: homeZone}).format(new Date(iso));

// One goal ring: the percentage label, the arc (pathLength is 100) and "value / target".
function ring(name, value, target, valueText, targetText) {
  const percent = value == null ? 0 : Math.round(value / target * 100);
  $home("ring-" + name).setAttribute("stroke-dasharray", Math.min(percent, 100) + " 100");
  $home("pct-" + name).textContent = value == null ? "—" : percent + "%";
  $home("val-" + name).textContent = value == null ? "—" : valueText;
  $home("target-" + name).textContent = targetText;
  return value != null && percent >= 100;
}

function weightTile(data) {
  const latest = data.latest_weight;
  $home("latest-weight").textContent = latest ? formatNumber(latest.weight) : "—";
  const points = data.weights;
  const line = $home("weight-line");
  if (points.length >= 2) {
    const values = points.map((p) => p.weight), low = Math.min(...values), span = Math.max(...values) - low || 1;
    const first = Date.parse(points[0].measured_at), range = Date.parse(points.at(-1).measured_at) - first || 1;
    line.setAttribute("points", points.map((p) => [((Date.parse(p.measured_at) - first) / range * 140).toFixed(1), (24 - (p.weight - low) / span * 20).toFixed(1)].join(",")).join(" "));
    const change = values.at(-1) - values[0];
    $home("weight-note").textContent = Math.abs(change) < 0.05 ? "최근 30일 변화 없음" : "최근 30일 " + (change > 0 ? "+" : "−") + formatNumber(Math.abs(change)) + "kg";
  } else {
    line.setAttribute("points", "");
    $home("weight-note").textContent = latest ? "최근 측정 · " + new Date(latest.measured_at).toLocaleDateString("ko-KR") : "아직 체중 기록이 없어요";
  }
}

function mealTile(data) {
  $home("today-kcal").textContent = data.calories == null ? "—" : formatNumber(Math.round(data.calories));
  const parts = {carb: (data.carbohydrates_grams || 0) * 4, protein: (data.protein_grams || 0) * 4, fat: (data.fat_grams || 0) * 9};
  const total = parts.carb + parts.protein + parts.fat;
  $home("macro-bar").hidden = !total;
  for (const [key, kcal] of Object.entries(parts)) $home("macro-" + key).style.flex = String(kcal);
  const share = (kcal) => Math.round(kcal / total * 100);
  $home("protein-note").textContent = !data.meals_count ? "오늘은 아직 식단 기록이 없어요"
    : total ? data.meals_count + "끼 · 탄 " + share(parts.carb) + " · 단 " + share(parts.protein) + " · 지 " + share(parts.fat) + "%"
    : data.meals_count + "끼 · 영양 정보 없음";
}

function sleepTile(data) {
  $home("today-sleep").replaceChildren();
  if (data.sleep_minutes == null) { $home("today-sleep").textContent = "—"; }
  else {
    const hours = document.createElement("b"); hours.textContent = Math.floor(data.sleep_minutes / 60);
    const minutes = document.createElement("b"); minutes.textContent = data.sleep_minutes % 60;
    $home("today-sleep").append(hours, "시간 ", minutes, "분");
  }
  const start = data.main_sleep_start, end = data.main_sleep_end;
  $home("sleep-bar").hidden = !start;
  if (start) {
    // The bar spans 18:00 the evening before the wake-up day to 12:00 noon.
    const wake = new Date(end), noon = new Date(wake); noon.setHours(12, 0, 0, 0);
    if (wake > noon) noon.setDate(noon.getDate() + 1);
    const origin = noon.getTime() - 18 * 3600000, width = 18 * 3600000;
    const left = Math.max(0, (Date.parse(start) - origin) / width), right = Math.min(1, (wake.getTime() - origin) / width);
    $home("sleep-span").style.left = (left * 100).toFixed(1) + "%";
    $home("sleep-span").style.width = (Math.max(right - left, 0.02) * 100).toFixed(1) + "%";
  }
  $home("sleep-note").textContent = start ? timeOf(start) + " → " + timeOf(end) + (data.sleep_records_count > 1 ? " 외 " + (data.sleep_records_count - 1) + "회" : "") : "오늘 끝난 수면 기록이 없어요";
}

function weekStrip(data) {
  const list = $home("week-days"); list.replaceChildren();
  const names = ["월", "화", "수", "목", "금", "토", "일"];
  data.week.forEach((day, index) => {
    const item = document.createElement("li");
    item.className = [day.workout && "workout", day.logged && "logged", day.date === data.date && "today"].filter(Boolean).join(" ");
    const label = (day.workout ? "운동함" : day.logged ? "기록함" : day.date > data.date ? "" : "기록 없음");
    item.setAttribute("aria-label", names[index] + "요일 " + Number(day.date.slice(8)) + "일" + (label ? ", " + label : "") + (day.date === data.date ? ", 오늘" : ""));
    const number = document.createElement("b"); number.textContent = Number(day.date.slice(8)); number.setAttribute("aria-hidden", "true");
    const name = document.createElement("span"); name.textContent = names[index]; name.setAttribute("aria-hidden", "true");
    item.append(name, number); list.append(item);
  });
  $home("week-note").textContent = "운동 " + data.week.filter((d) => d.workout).length + "일 · 기록 " + data.week.filter((d) => d.logged).length + "일";
}

const homeToday = new Intl.DateTimeFormat("en-CA", {timeZone: homeZone}).format(new Date());

function showSummary(data) {
  const met = [
    ring("protein", data.protein_grams, data.protein_goal_grams, formatNumber(data.protein_grams), formatNumber(data.protein_goal_grams) + "g"),
    ring("kcal", data.calories, data.calorie_goal_kcal, formatNumber(Math.round(data.calories)), formatNumber(data.calorie_goal_kcal)),
    ring("sleep", data.sleep_minutes, data.sleep_goal_minutes, hoursText(data.sleep_minutes), hoursText(data.sleep_goal_minutes)),
  ].filter(Boolean).length;
  $home("goals-note").textContent = "3개 중 " + met + "개 달성";
  $home("today-sets").textContent = data.total_sets;
  $home("today-workouts").textContent = !data.workouts_count ? "오늘은 아직 운동 기록이 없어요"
    : data.workout_titles.slice(0, 2).join(" · ") + (data.volume_kg ? " · 볼륨 " + formatNumber(Math.round(data.volume_kg)) + "kg" : "");
  weightTile(data); mealTile(data); sleepTile(data); weekStrip(data);
}
// Yesterday's copy would show yesterday as today, so a cached summary is used only on its own day.
async function loadSummary() {
  const key = "dashboard:" + homeZone, cached = window.fitlogCache.get(key);
  if (cached?.date === homeToday) showSummary(cached);
  try {
    const data = await homeGet("/api/dashboard?timezone=" + encodeURIComponent(homeZone));
    window.fitlogCache.set(key, data);
    showSummary(data);
  } catch {
    if (cached?.date === homeToday) return;
    $home("goals-note").textContent = "연결 후 새로고침해 주세요";
    for (const id of ["today-workouts", "weight-note", "protein-note", "sleep-note"]) $home(id).textContent = "연결 후 새로고침해 주세요";
  }
}

function showRecent(recent) {
  const target = $home("recent-workouts");
  target.replaceChildren();
  if (!recent.length) {
    const empty = document.createElement("p"); empty.className = "empty";
    empty.textContent = "아직 운동 기록이 없습니다. 첫 운동을 남겨보세요."; target.append(empty);
  }
  for (const workout of recent) {
    const link = document.createElement("a"); link.href = "/workouts#" + workout.id;
    link.className = "recent-item" + (workout.workout_date === homeToday ? " is-today" : "");
    const date = document.createElement("span"); date.className = "recent-date";
    const day = document.createElement("b"); day.textContent = Number(workout.workout_date.slice(8));
    date.append(Number(workout.workout_date.slice(5, 7)) + "월", day);
    const text = document.createElement("span"); text.className = "recent-text";
    const title = document.createElement("strong"); title.textContent = workout.title;
    const names = [...new Set(workout.sets.map((set) => set.exercise.name))];
    const detail = document.createElement("span");
    detail.textContent = [names.slice(0, 3).join(" · ") + (names.length > 3 ? " 외" : ""), workout.sets.length + "세트"].filter(Boolean).join(" · ");
    text.append(title, detail);
    link.append(date, text);
    link.insertAdjacentHTML("beforeend", '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 6l6 6-6 6"></path></svg>');
    target.append(link);
  }
}
async function loadRecent() {
  const cached = window.fitlogCache.get("workouts:recent");
  if (cached) showRecent(cached);
  try {
    const recent = await homeGet("/api/workouts?limit=3");
    window.fitlogCache.set("workouts:recent", recent);
    showRecent(recent);
  } catch { if (!cached) $home("recent-workouts").textContent = "운동 기록을 불러오지 못했습니다. 연결 후 새로고침해 주세요."; }
}

// The record sheet opens from the ＋ menu item (/#record), the quick-record bar and the photo button.
const sheet = $home("record-sheet");
function openSheet() { if (!sheet.open) sheet.showModal(); }
sheet.addEventListener("close", () => { if (location.hash === "#record") history.replaceState(null, "", location.pathname + location.search); });
sheet.addEventListener("click", (event) => { if (event.target === sheet) sheet.close(); });
$home("sheet-close").addEventListener("click", () => sheet.close());
$home("quick-photo").addEventListener("click", () => { openSheet(); if (!$home("assistant-form").hidden) $home("assistant-photo-input").click(); });
window.addEventListener("hashchange", () => { if (location.hash === "#record") openSheet(); });
if (location.hash === "#record") openSheet();

loadSummary();
loadRecent();
