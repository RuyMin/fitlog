"use strict";
// Meals by day: intake against goals, the day's meals, and the last 7 days of calories.
const $ = (id) => document.getElementById(id);
const ESTIMATE_NOTE = "열량·영양소 AI 추정"; // written into memo by the AI assistant (app/services/assistant.py)
const mealTypes = {breakfast: "아침", lunch: "점심", dinner: "저녁", snack: "간식", other: "기타"};
const weekdays = ["일", "월", "화", "수", "목", "금", "토"];
const number = (value) => new Intl.NumberFormat("ko-KR", {maximumFractionDigits: 1}).format(value);
const pad = (value) => String(value).padStart(2, "0");
const keyOf = (date) => date.getFullYear() + "-" + pad(date.getMonth() + 1) + "-" + pad(date.getDate());
const dateOf = (key) => { const [y, m, d] = key.split("-").map(Number); return new Date(y, m - 1, d); };
const shift = (key, days) => { const date = dateOf(key); date.setDate(date.getDate() + days); return keyOf(date); };
const todayKey = () => keyOf(new Date());
const zone = Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Seoul";
const state = {day: todayKey(), meals: [], goals: null, editing: null, saving: false, request: 0};

function element(tag, text, className) {
  const item = document.createElement(tag);
  if (text != null) item.textContent = text;
  if (className) item.className = className;
  return item;
}
function notice(text, error = false) { $("notice").textContent = text; $("notice").className = error ? "error" : ""; }
async function api(path, method = "GET", body) {
  let response;
  try {
    response = await fetch("/api" + path, {method, cache: "no-store", signal: AbortSignal.timeout(15000),
      headers: body ? {"Content-Type": "application/json"} : {}, body: body ? JSON.stringify(body) : undefined});
  } catch {
    throw new Error("서버에 연결하지 못했습니다. 저장 중이었다면 새로고침으로 반영 여부를 확인한 뒤 다시 시도하세요.");
  }
  const data = await response.json();
  if (!response.ok) {
    const labels = {eaten_at: "식사 시각", meal_type: "식사 구분", name: "음식·식사 이름", calories: "열량", protein: "단백질", carbohydrates: "탄수화물", fat: "지방", memo: "메모"};
    const detail = data.detail;
    throw new Error(Array.isArray(detail) ? detail.map((item) => (labels[item.loc.at(-1)] ? labels[item.loc.at(-1)] + ": " : "") + item.msg).join("\n") : detail || "요청에 실패했습니다.");
  }
  return data;
}

// Every meal from 6 days before the chosen day through its end, paging past the API's 100 limit.
// Today's week is kept on this phone (app.js show-then-refresh) and shown read-only until the
// server's copy arrives, so an edit is never made on an old copy.
async function loadWeek() {
  const request = ++state.request;
  const key = state.day === todayKey() ? "meals:" + state.day : null, cached = key && window.fitlogCache.get(key);
  if (cached && !state.meals.length) { state.meals = cached; render(); $("meal-list").inert = true; }
  const from = dateOf(shift(state.day, -6)), to = dateOf(shift(state.day, 1));
  const meals = [];
  for (let offset = 0; ; offset += 100) {
    const page = await api("/meals?" + new URLSearchParams({from_at: from.toISOString(), to_at: to.toISOString(), limit: 100, offset}));
    meals.push(...page);
    if (page.length < 100) break;
  }
  if (request !== state.request) return;
  state.meals = meals.map((meal) => ({...meal, day: keyOf(new Date(meal.eaten_at))}));
  if (key) window.fitlogCache.set(key, state.meals);
  $("meal-list").inert = false;
  render();
}

function sum(meals, key) {
  const known = meals.filter((meal) => meal[key] != null);
  return known.length ? known.reduce((total, meal) => total + meal[key], 0) : null;
}
const estimated = (meal) => (meal.memo || "").includes(ESTIMATE_NOTE);

function renderDay() {
  const date = dateOf(state.day), isToday = state.day === todayKey();
  $("day-label").textContent = (date.getMonth() + 1) + "월 " + date.getDate() + "일 (" + weekdays[date.getDay()] + ")" + (isToday ? " · 오늘" : "");
  $("day-input").value = state.day;
  $("day-input").max = todayKey();
  $("day-next").disabled = state.day >= todayKey();
}

function renderIntake(meals) {
  const goals = state.goals;
  const kcal = sum(meals, "calories");
  $("kcal-eaten").textContent = kcal == null ? "—" : number(Math.round(kcal));
  if (goals) {
    $("kcal-goal").textContent = number(goals.calorie_goal_kcal);
    $("kcal-arc").setAttribute("stroke-dasharray", Math.min(100, (kcal || 0) / goals.calorie_goal_kcal * 100).toFixed(1) + " 100");
    const left = goals.calorie_goal_kcal - (kcal || 0);
    $("remaining-label").textContent = left >= 0 ? "남은 열량" : "목표보다 더 먹은 열량";
    $("kcal-remaining").textContent = number(Math.round(Math.abs(left)));
  }
  for (const [name, key, goal] of [["protein", "protein", "protein_goal_grams"], ["carb", "carbohydrates", "carbohydrate_goal_grams"], ["fat", "fat", "fat_goal_grams"]]) {
    const grams = sum(meals, key);
    $(name + "-eaten").textContent = grams == null ? "—" : number(Math.round(grams));
    if (goals) {
      $(name + "-goal").textContent = number(goals[goal]);
      $(name + "-fill").style.width = Math.min(100, (grams || 0) / goals[goal] * 100).toFixed(1) + "%";
    }
  }
  const guesses = meals.filter(estimated).length;
  $("estimate-note").hidden = !guesses;
  $("estimate-note").textContent = guesses + "끼는 AI 추정 포함";
  const unknown = meals.filter((meal) => meal.calories == null).length;
  $("unknown-note").hidden = !unknown;
  $("unknown-note").textContent = "열량을 입력하지 않은 " + unknown + "건은 합계에서 빠졌어요.";
}

function mealItem(meal) {
  const item = element("button", null, "meal-item" + (estimated(meal) ? " is-estimated" : ""));
  item.type = "button";
  item.setAttribute("aria-label", mealTypes[meal.meal_type] + " " + meal.name + " 수정");
  const when = element("span", null, "meal-when");
  when.append(element("b", mealTypes[meal.meal_type] || meal.meal_type), element("span", new Date(meal.eaten_at).toLocaleTimeString("ko-KR", {hour: "2-digit", minute: "2-digit", hour12: false})));
  const text = element("span", null, "meal-text");
  const macros = [["단", meal.protein], ["탄", meal.carbohydrates], ["지", meal.fat]].filter(([, value]) => value != null).map(([label, value]) => label + " " + number(value) + "g");
  text.append(element("b", meal.name), element("span", macros.length ? macros.join(" · ") : "영양 정보 없음"));
  const kcal = element("span", null, "meal-kcal");
  kcal.append(meal.calories == null ? "—" : number(Math.round(meal.calories)), element("small", " kcal"));
  const row = element("span", null, "meal-row");
  row.append(when, text, kcal);
  item.append(row);
  const memo = (meal.memo || "").replace(" · " + ESTIMATE_NOTE, "").replace(ESTIMATE_NOTE, "").trim();
  if (estimated(meal)) item.append(element("span", "AI 추정 · 실제와 다르면 눌러서 고쳐 주세요" + (memo ? " · " + memo : ""), "meal-estimate"));
  else if (memo) item.append(element("span", memo, "meal-memo"));
  item.addEventListener("click", () => openForm(meal));
  return item;
}

function renderWeek() {
  const bars = $("kcal-bars");
  bars.querySelectorAll("button").forEach((bar) => bar.remove());
  const days = Array.from({length: 7}, (_, index) => shift(state.day, index - 6));
  const totals = days.map((day) => sum(state.meals.filter((meal) => meal.day === day), "calories") || 0);
  const goal = state.goals ? state.goals.calorie_goal_kcal : 0;
  const scale = Math.max(goal * 1.15, ...totals, 1);
  $("kcal-goal-line").hidden = !goal;
  // Bars fill the area above the 22px day labels (16px line + 6px gap).
  if (goal) $("kcal-goal-line").style.bottom = "calc((100% - 22px) * " + (goal / scale).toFixed(3) + " + 22px)";
  days.forEach((day, index) => {
    const date = dateOf(day);
    const bar = element("button", null, "kcal-bar" + (day === state.day ? " selected" : ""));
    bar.type = "button";
    bar.setAttribute("aria-label", (date.getMonth() + 1) + "월 " + date.getDate() + "일 " + number(Math.round(totals[index])) + "kcal");
    if (day === state.day) bar.setAttribute("aria-current", "date");
    const fill = element("span", null, "kcal-fill");
    fill.style.height = (totals[index] / scale * 100).toFixed(1) + "%";
    bar.append(element("span", null, "kcal-column"), element("span", day === todayKey() ? "오늘" : weekdays[date.getDay()], "kcal-day"));
    bar.firstChild.append(fill);
    bar.addEventListener("click", () => setDay(day));
    bars.append(bar);
  });
  const logged = totals.filter((total) => total > 0);
  $("week-kcal-note").textContent = [logged.length && "평균 " + number(Math.round(logged.reduce((a, b) => a + b, 0) / logged.length)) + "kcal", goal && "점선 목표 " + number(goal)].filter(Boolean).join(" · ");
}

function render() {
  const meals = state.meals.filter((meal) => meal.day === state.day).sort((a, b) => a.eaten_at.localeCompare(b.eaten_at));
  renderDay(); renderIntake(meals); renderWeek();
  $("meal-list").replaceChildren(...meals.map(mealItem));
  if (!meals.length) $("meal-list").append(element("p", "이날은 아직 식단 기록이 없어요.", "empty-state"));
}

function setDay(day) {
  state.day = day > todayKey() ? todayKey() : day;
  history.replaceState(null, "", state.day === todayKey() ? location.pathname : "?date=" + state.day);
  notice(""); renderDay();
  loadWeek().catch((error) => notice(error.message, true));
}

function localInput(date) { return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16); }
function openForm(meal = null) {
  state.editing = meal;
  const form = $("meal-form"); form.reset();
  form.querySelector(".form-error").textContent = "";
  $("form-title").textContent = meal ? "식단 수정" : "식단 추가";
  $("delete-meal").hidden = !meal;
  if (meal) {
    form.elements.eaten_at.value = localInput(new Date(meal.eaten_at));
    for (const name of ["meal_type", "name", "calories", "protein", "carbohydrates", "fat", "memo"]) form.elements[name].value = meal[name] ?? "";
  } else {
    const when = state.day === todayKey() ? new Date() : dateOf(state.day);
    if (state.day !== todayKey()) when.setHours(12, 0, 0, 0);
    form.elements.eaten_at.value = localInput(when);
    const hour = when.getHours();
    form.elements.meal_type.value = hour < 10 ? "breakfast" : hour < 15 ? "lunch" : hour < 21 ? "dinner" : "snack";
  }
  $("meal-dialog").showModal();
}
function busy(value) { state.saving = value; $("meal-dialog").querySelectorAll("button").forEach((button) => button.disabled = value); }

$("meal-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.saving) return;
  const form = event.currentTarget;
  form.querySelector(".form-error").textContent = "";
  busy(true);
  try {
    const body = {eaten_at: new Date(form.elements.eaten_at.value).toISOString(), meal_type: form.elements.meal_type.value,
      name: form.elements.name.value.trim(), memo: form.elements.memo.value.trim() || null};
    for (const name of ["calories", "protein", "carbohydrates", "fat"]) body[name] = form.elements[name].value === "" ? null : Number(form.elements[name].value);
    await api("/meals" + (state.editing ? "/" + state.editing.id : ""), state.editing ? "PUT" : "POST", body);
    $("meal-dialog").close(); notice("식단을 저장했습니다.");
    const saved = keyOf(new Date(body.eaten_at));
    if (saved !== state.day) setDay(saved); else await loadWeek();
  } catch (error) { form.querySelector(".form-error").textContent = error.message; }
  finally { busy(false); }
});
$("delete-meal").addEventListener("click", async () => {
  if (!state.editing || !confirm("이 식단 기록을 삭제할까요? 삭제 후 되돌릴 수 없습니다.")) return;
  busy(true);
  try { await api("/meals/" + state.editing.id, "DELETE"); $("meal-dialog").close(); notice("식단을 삭제했습니다."); await loadWeek(); }
  catch (error) { $("meal-form").querySelector(".form-error").textContent = error.message; }
  finally { busy(false); }
});
$("cancel-meal").addEventListener("click", () => $("meal-dialog").close());
$("meal-dialog").addEventListener("cancel", (event) => { if (state.saving) event.preventDefault(); });
$("new-meal").addEventListener("click", () => openForm());
$("day-prev").addEventListener("click", () => setDay(shift(state.day, -1)));
$("day-next").addEventListener("click", () => setDay(shift(state.day, 1)));
$("day-input").addEventListener("change", (event) => { if (event.target.value) setDay(event.target.value); });

const requested = new URLSearchParams(location.search).get("date");
if (requested && /^\d{4}-\d{2}-\d{2}$/.test(requested)) state.day = requested > todayKey() ? todayKey() : requested;
renderDay();
state.goals = window.fitlogCache.get("dashboard:" + zone);
api("/dashboard?timezone=" + encodeURIComponent(zone)).then((data) => { state.goals = data; window.fitlogCache.set("dashboard:" + zone, data); render(); }).catch(() => {});
loadWeek().catch((error) => {
  notice(error.message, true);
  if ($("meal-list").inert) { $("meal-list").inert = false; return; } // keep the saved copy on screen
  $("meal-list").replaceChildren(element("p", "식단을 불러오지 못했습니다. 연결을 확인하고 새로고침해 주세요.", "empty-state"));
});
