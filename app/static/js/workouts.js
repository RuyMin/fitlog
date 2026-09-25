"use strict";
const $ = (selector) => document.querySelector(selector);
const state = {workouts: [], current: null, exercises: [], offset: 0, editWorkout: null, editSet: null, editExercise: null, route: 0};
const pageSize = 20;
function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text != null) element.textContent = text;
  if (className) element.className = className;
  return element;
}
function button(text, action, className) {
  const element = node("button", text, className);
  element.type = "button";
  element.addEventListener("click", () => action(element));
  return element;
}
function notice(text, error = false) { $("#notice").textContent = text; $("#notice").className = error ? "error" : ""; }
async function api(path, method = "GET", body) {
  let response;
  try {
    response = await fetch("/api" + path, {
      method, cache: "no-store", headers: body ? {"Content-Type": "application/json"} : {},
      body: body ? JSON.stringify(body) : undefined, signal: AbortSignal.timeout(15000)
    });
  } catch { throw new Error("서버에 연결하지 못했습니다. 저장 요청 중이었다면 새로고침으로 반영 여부를 확인한 뒤 다시 시도하세요."); }
  const data = await response.json();
  if (!response.ok) {
    const detail = data.detail;
    throw new Error(Array.isArray(detail) ? detail.map((item) => item.loc.slice(1).join(".") + ": " + item.msg).join("\n") : detail || "요청에 실패했습니다.");
  }
  return data;
}
function localDate(value = new Date()) {
  return new Date(value.getTime() - value.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}
function localTime(value) {
  if (!value) return "";
  const date = new Date(value);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}
function textValue(form, key) { return form.elements[key].value.trim() || null; }
function numberValue(form, key) { const value = form.elements[key].value; return value === "" ? null : Number(value); }
function fill(form, data) {
  form.reset();
  form.querySelector(".form-error").textContent = "";
  for (const [key, value] of Object.entries(data)) {
    const field = form.elements.namedItem(key);
    if (!field) continue;
    if (field.type === "checkbox") field.checked = Boolean(value);
    else field.value = value ?? "";
  }
}
async function submitForm(form, action) {
  if (form.dataset.busy) return;
  form.dataset.busy = "true";
  const buttons = [...form.closest("dialog").querySelectorAll("button")];
  buttons.forEach((item) => item.disabled = true);
  form.querySelector(".form-error").textContent = "";
  try { await action(); }
  catch (error) { form.querySelector(".form-error").textContent = error.message; }
  finally { delete form.dataset.busy; buttons.forEach((item) => item.disabled = false); }
}
async function mutate(control, action) {
  control.disabled = true;
  try { await action(); }
  catch (error) { notice(error.message, true); }
  finally { control.disabled = false; }
}
function workoutLink(workout) {
  const link = node("a", null, "card workout-link");
  link.href = "/workouts#" + workout.id;
  link.append(node("p", workout.workout_date, "date"), node("h2", workout.title, "workout-title"));
  link.append(node("p", (workout.body_part || "부위 미지정") + " · " + workout.sets.length + "세트 · 완료 " + workout.sets.filter((s) => s.completed).length, "workout-meta"));
  return link;
}
async function loadList(append = false) {
  const route = state.route;
  const params = new URLSearchParams({limit: pageSize, offset: append ? state.offset : 0});
  const form = $("#filter-form");
  for (const key of ["date_from", "date_to"]) if (form.elements[key].value) params.set(key, form.elements[key].value);
  const items = await api("/workouts?" + params);
  if (route !== state.route) return;
  state.workouts = append ? [...state.workouts, ...items] : items;
  state.offset = state.workouts.length;
  const list = $("#workout-list");
  list.replaceChildren(...state.workouts.map(workoutLink));
  if (!state.workouts.length) list.append(node("p", "운동 기록이 없습니다. ‘+ 운동 기록’으로 첫 운동을 남겨보세요.", "empty-state"));
  $("#load-more").hidden = items.length < pageSize;
}
async function loadExercises() {
  const exercises = [];
  for (let offset = 0; ; offset += 100) {
    const page = await api("/exercises?limit=100&offset=" + offset);
    exercises.push(...page);
    if (page.length < 100) break;
  }
  state.exercises = exercises;
}
function setPayload(set) {
  return {exercise_id: set.exercise_id, set_number: set.set_number, weight: set.weight, reps: set.reps, completed: set.completed, memo: set.memo};
}
function renderDetail(workout) {
  const root = $("#workout-detail");
  const header = node("div", null, "detail-header");
  header.append(node("p", workout.workout_date, "date"), node("h2", workout.title, "workout-title"));
  header.append(node("p", (workout.body_part || "부위 미지정") + " · 총 " + workout.sets.length + "세트 · 완료 " + workout.sets.filter((s) => s.completed).length, "workout-meta"));
  if (workout.started_at || workout.ended_at) header.append(node("p", (workout.started_at ? new Date(workout.started_at).toLocaleString("ko-KR") : "—") + " ~ " + (workout.ended_at ? new Date(workout.ended_at).toLocaleString("ko-KR") : "진행 중"), "workout-meta"));
  if (workout.memo) header.append(node("p", workout.memo, "memo"));
  const actions = node("div", null, "row-actions");
  actions.append(button("+ 세트 추가", () => openSet(), "primary"), button("운동 수정", () => openWorkout(workout)), button("운동 삭제", (control) => {
    if (!confirm("이 운동과 모든 세트를 삭제할까요?")) return;
    mutate(control, async () => { await api("/workouts/" + workout.id, "DELETE"); notice("운동을 삭제했습니다."); location.hash = ""; });
  }, "danger"));
  header.append(actions);
  root.replaceChildren(header);
  const groups = new Map();
  for (const set of workout.sets) {
    if (!groups.has(set.exercise_id)) groups.set(set.exercise_id, []);
    groups.get(set.exercise_id).push(set);
  }
  if (!groups.size) root.append(node("p", "아직 세트가 없습니다. 종목을 등록하고 세트를 추가하세요.", "empty-state"));
  for (const sets of groups.values()) {
    const group = node("article", null, "card exercise-group");
    group.append(node("h3", sets[0].exercise.name));
    for (const set of sets.sort((a, b) => a.set_number - b.set_number)) {
      const row = node("div", null, "set-row" + (set.completed ? " done" : ""));
      const heading = node("div", null, "set-heading");
      heading.append(node("span", set.set_number + "세트 · " + (set.completed ? "완료" : "미완료"), "set-number"), node("strong", (set.weight ?? "—") + " kg × " + (set.reps ?? "—") + "회"));
      row.append(heading);
      if (set.rpe != null || set.rir != null) row.append(node("p", "RPE " + (set.rpe ?? "—") + " · RIR " + (set.rir ?? "—"), "memo"));
      if (set.memo) row.append(node("p", set.memo, "memo"));
      const controls = node("div", null, "row-actions");
      const toggle = button(set.completed ? "완료 취소" : "완료 표시", (control) => mutate(control, async () => {
        await api("/workouts/" + workout.id + "/sets/" + set.id, "PUT", {...setPayload(set), completed: !set.completed});
        await showRoute();
      }));
      toggle.setAttribute("aria-pressed", String(set.completed));
      toggle.setAttribute("aria-label", set.exercise.name + " " + set.set_number + "세트 " + (set.completed ? "완료 취소" : "완료 표시"));
      controls.append(toggle, button("수정", () => openSet(set)), button("삭제", (control) => {
        if (!confirm(set.set_number + "세트를 삭제할까요?")) return;
        mutate(control, async () => { await api("/workouts/" + workout.id + "/sets/" + set.id, "DELETE"); await showRoute(); notice("세트를 삭제했습니다."); });
      }, "danger"));
      row.append(controls); group.append(row);
    }
    root.append(group);
  }
}
async function showRoute() {
  const route = ++state.route;
  const hash = location.hash.slice(1);
  state.current = null;
  $("#list-view").hidden = Boolean(hash);
  $("#detail-view").hidden = !hash;
  try {
    if (!hash) { await loadList(); return; }
    $("#workout-detail").replaceChildren(node("p", "기록을 불러오는 중…", "empty-state"));
    if (!/^\d+$/.test(hash)) throw new Error("잘못된 운동 주소입니다.");
    const workout = await api("/workouts/" + hash);
    if (route !== state.route) return;
    state.current = workout; renderDetail(workout);
  } catch (error) {
    if (route !== state.route) return;
    notice(error.message, true);
    const target = hash ? $("#workout-detail") : $("#workout-list");
    target.replaceChildren(node("p", "기록을 불러오지 못했습니다. 연결을 확인하고 새로고침해 주세요.", "empty-state"));
  }
}
function openWorkout(workout = null) {
  state.editWorkout = workout?.id ?? null;
  $("#workout-form-title").textContent = workout ? "운동 수정" : "새 운동 기록";
  fill($("#workout-form"), workout ? {...workout, started_at: localTime(workout.started_at), ended_at: localTime(workout.ended_at)} : {workout_date: localDate()});
  $("#workout-dialog").showModal();
}
async function openSet(set = null) {
  try {
    const workoutId = state.current?.id;
    await loadExercises();
    if (!state.current || state.current.id !== workoutId) return;
    if (!state.exercises.length) { notice("종목을 먼저 등록해 주세요."); await openExercises(); return; }
    state.editSet = set?.id ?? null;
    const form = $("#set-form");
    const options = state.exercises.map((exercise) => { const option = node("option", exercise.name); option.value = exercise.id; return option; });
    form.elements.exercise_id.replaceChildren(...options);
    $("#set-form-title").textContent = set ? "세트 수정" : "세트 추가";
    fill(form, set || {exercise_id: state.exercises[0].id, set_number: 1, completed: false});
    if (!set) nextSetNumber();
    $("#set-dialog").showModal();
  } catch (error) { notice(error.message, true); }
}
function nextSetNumber() {
  if (state.editSet || !state.current) return;
  const exerciseId = Number($("#set-form").elements.exercise_id.value);
  const sets = state.current.sets.filter((set) => set.exercise_id === exerciseId);
  $("#set-form").elements.set_number.value = Math.max(0, ...sets.map((set) => set.set_number)) + 1;
}
function resetExercise() {
  state.editExercise = null; fill($("#exercise-form"), {});
  $("#exercise-form-title").textContent = "새 종목";
}
function renderExercises() {
  const list = $("#exercise-list"); list.replaceChildren();
  if (!state.exercises.length) list.append(node("p", "등록된 종목이 없습니다.", "empty-state"));
  for (const exercise of state.exercises) {
    const item = node("div", null, "exercise-item");
    item.append(node("h3", exercise.name), node("p", [exercise.category, exercise.body_part].filter(Boolean).join(" · ") || "분류·부위 미지정", "muted"));
    const actions = node("div", null, "row-actions");
    actions.append(button("수정", () => {
      state.editExercise = exercise.id; fill($("#exercise-form"), exercise);
      $("#exercise-form-title").textContent = "종목 수정";
      $("#exercise-form").elements.name.focus();
    }), button("삭제", async (control) => {
      if (!confirm(exercise.name + " 종목을 삭제할까요?")) return;
      control.disabled = true;
      try { await api("/exercises/" + exercise.id, "DELETE"); resetExercise(); await loadExercises(); renderExercises(); }
      catch (error) { $("#exercise-form .form-error").textContent = error.message; }
      finally { control.disabled = false; }
    }, "danger"));
    item.append(actions); list.append(item);
  }
}
async function openExercises() {
  try { await loadExercises(); resetExercise(); renderExercises(); $("#exercise-dialog").showModal(); }
  catch (error) { notice(error.message, true); }
}
$("#workout-form").addEventListener("submit", (event) => {
  event.preventDefault(); const form = event.currentTarget;
  submitForm(form, async () => {
    const body = {workout_date: form.elements.workout_date.value, title: form.elements.title.value,
      body_part: textValue(form, "body_part"), memo: textValue(form, "memo"),
      started_at: form.elements.started_at.value ? new Date(form.elements.started_at.value).toISOString() : null,
      ended_at: form.elements.ended_at.value ? new Date(form.elements.ended_at.value).toISOString() : null};
    const workout = await api("/workouts" + (state.editWorkout ? "/" + state.editWorkout : ""), state.editWorkout ? "PUT" : "POST", body);
    $("#workout-dialog").close(); notice("운동을 저장했습니다.");
    if (location.hash === "#" + workout.id) await showRoute(); else location.hash = workout.id;
  });
});
$("#set-form").addEventListener("submit", (event) => {
  event.preventDefault(); const form = event.currentTarget;
  submitForm(form, async () => {
    const workoutId = state.current.id;
    await api("/workouts/" + workoutId + "/sets" + (state.editSet ? "/" + state.editSet : ""), state.editSet ? "PUT" : "POST", {
      exercise_id: Number(form.elements.exercise_id.value), set_number: Number(form.elements.set_number.value),
      weight: numberValue(form, "weight"), reps: numberValue(form, "reps"), completed: form.elements.completed.checked, memo: textValue(form, "memo")
    });
    $("#set-dialog").close(); notice("세트를 저장했습니다."); await showRoute();
  });
});
$("#exercise-form").addEventListener("submit", (event) => {
  event.preventDefault(); const form = event.currentTarget;
  submitForm(form, async () => {
    await api("/exercises" + (state.editExercise ? "/" + state.editExercise : ""), state.editExercise ? "PUT" : "POST", {
      name: form.elements.name.value, category: textValue(form, "category"), body_part: textValue(form, "body_part")
    });
    resetExercise(); await loadExercises(); renderExercises();
  });
});
document.querySelectorAll("[data-close]").forEach((control) => control.addEventListener("click", () => control.closest("dialog").close()));
document.querySelectorAll("dialog").forEach((dialog) => dialog.addEventListener("cancel", (event) => {
  if (dialog.querySelector('[data-busy="true"]')) event.preventDefault();
}));
$("#exercise-dialog").addEventListener("close", () => showRoute());
$("#new-workout").addEventListener("click", () => openWorkout());
$("#manage-exercises").addEventListener("click", openExercises);
$("#reset-exercise").addEventListener("click", resetExercise);
$("#set-form").elements.exercise_id.addEventListener("change", nextSetNumber);
$("#refresh").addEventListener("click", () => { notice(""); showRoute(); });
$("#load-more").addEventListener("click", (event) => mutate(event.currentTarget, () => loadList(true)));
$("#filter-form").addEventListener("submit", (event) => { event.preventDefault(); notice(""); showRoute(); });
$("#clear-filter").addEventListener("click", () => { $("#filter-form").reset(); notice(""); showRoute(); });
window.addEventListener("hashchange", showRoute);
showRoute();
