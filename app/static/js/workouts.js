"use strict";
// Workouts: this week's summary, today's session with inline set tables, past sessions,
// the preset picker (search + body part / equipment tags) and an exercise sheet with the muscle figure.
const $ = (selector) => document.querySelector(selector);
const state = {variants: {}, workouts: [], offset: 0, exercises: [], presets: [], catalog: null, current: null, route: 0,
  editWorkout: null, editExercise: null, picker: {workout: null, part: "전체", gear: "전체", picked: new Map()}};
const pageSize = 20;
const SVG_CHEVRON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 6l6 6-6 6"></path></svg>';
const SVG_CHECK = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12l5 5 9-10"></path></svg>';
const SVG_PLUS = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"></path></svg>';
const number = (value) => new Intl.NumberFormat("ko-KR", {maximumFractionDigits: 1}).format(value);

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
    const error = new Error(Array.isArray(detail) ? detail.map((item) => item.msg).join("\n") : detail || "요청에 실패했습니다.");
    error.status = response.status;
    throw error;
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
function fill(form, data) {
  form.reset();
  form.querySelector(".form-error").textContent = "";
  for (const [key, value] of Object.entries(data)) {
    const field = form.elements.namedItem(key);
    if (field) field.value = value ?? "";
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
  if (control) control.disabled = true;
  try { await action(); }
  catch (error) { notice(error.message, true); }
  finally { if (control) control.disabled = false; }
}

// ---- reference data ------------------------------------------------------------------------------
async function loadExercises() {
  const exercises = [];
  for (let offset = 0; ; offset += 100) {
    const page = await api("/exercises?limit=100&offset=" + offset);
    exercises.push(...page);
    if (page.length < 100) break;
  }
  state.exercises = exercises;
}
async function loadCatalog() {
  if (!state.catalog) { state.catalog = await api("/exercise-presets"); state.presets = state.catalog.presets; }
}
const presetOf = (exercise) => exercise?.preset_id ? state.presets.find((preset) => preset.id === exercise.preset_id) : null;
function thumb(muscles, label) {
  const box = node("span", null, "ex-thumb");
  if (muscles?.length) box.append(FitAnatomy.figure(muscles, {view: "auto"}));
  else box.append(node("span", (label || "?").slice(0, 1), "ex-initial"));
  return box;
}
function describe(exercise) {
  const preset = presetOf(exercise);
  return [preset?.body_part || exercise.body_part, preset?.equipment || exercise.category].filter(Boolean).join(" · ") || "부위·장비 미지정";
}
// ---- set fields by tracking type -----------------------------------------------------------------
// Each preset says how it is recorded (app/data/exercise_presets.json "tracking"); custom exercises use weight × reps.
const CARDIO_FIELDS = ["duration_seconds", "distance_m", "speed_kmh", "incline_pct", "level", "calories", "heart_rate"];
const FIELDS = {
  weight: {key: "weight", label: "kg", mode: "decimal"},
  reps: {key: "reps", label: "회", mode: "numeric"},
  count: {key: "reps", label: "횟수", mode: "numeric"},
  seconds: {key: "duration_seconds", label: "초", mode: "numeric"},
  time: {key: "duration_seconds", label: "시간", mode: "time"},
  speed: {key: "speed_kmh", label: "km/h", mode: "decimal"},
  incline: {key: "incline_pct", label: "경사%", mode: "decimal"},
  distance: {key: "distance_m", label: "km", mode: "km"},
  level: {key: "level", label: "레벨", mode: "decimal"},
};
const TRACKING = {
  weight_reps: {fields: ["weight", "reps"]},
  reps: {fields: ["weight", "reps"], weightLabel: "+kg"},
  hold: {fields: ["seconds"]},
  weight_time: {fields: ["weight", "seconds"]},
  treadmill: {fields: ["time", "speed", "incline"], cardio: true},
  distance: {fields: ["distance", "time"], cardio: true},
  cardio_machine: {fields: ["time", "level", "distance"], cardio: true},
  rope: {fields: ["time", "count"], cardio: true},
};
const trackingOf = (exercise) => TRACKING[presetOf(exercise)?.tracking] ? presetOf(exercise).tracking : "weight_reps";
function clock(seconds) {
  if (seconds == null) return "";
  const h = Math.floor(seconds / 3600), m = Math.floor(seconds % 3600 / 60), s = Math.round(seconds % 60);
  return (h ? h + ":" + String(m).padStart(2, "0") : m) + ":" + String(s).padStart(2, "0");
}
// "30" is minutes, "30:15" minutes:seconds, "1:05:00" hours:minutes:seconds.
function parseClock(text) {
  const parts = text.trim().split(":");
  if (!text.trim() || parts.some((part) => !/^\d+$/.test(part)) || parts.length > 3) return text.trim() ? NaN : null;
  const [a, b, c] = parts.map(Number);
  return parts.length === 1 ? a * 60 : parts.length === 2 ? a * 60 + b : a * 3600 + b * 60 + c;
}
function fieldValue(field, set) {
  const value = set[field.key];
  if (value == null) return "";
  return field.mode === "time" ? clock(value) : field.mode === "km" ? String(Number((value / 1000).toFixed(3))) : String(value);
}
function readField(field, text) {
  if (field.mode === "time") return parseClock(text);
  if (text.trim() === "") return null;
  const value = Number(text);
  if (!Number.isFinite(value)) return NaN;
  return field.mode === "km" ? Math.round(value * 1000) : field.mode === "numeric" ? Math.round(value) : value;
}
// Distance of a cardio row: as entered, or speed × time on a treadmill.
const rowDistance = (set) => set.distance_m ?? (set.speed_kmh != null && set.duration_seconds != null ? set.speed_kmh * set.duration_seconds / 3.6 : null);
function cardioSummary(sets) {
  const seconds = sets.reduce((sum, set) => sum + (set.duration_seconds || 0), 0);
  const metres = sets.reduce((sum, set) => sum + (rowDistance(set) || 0), 0);
  const count = sets.reduce((sum, set) => sum + (set.reps || 0), 0);
  const parts = [];
  if (seconds) parts.push(clock(seconds));
  if (metres) parts.push(number(metres / 1000) + "km");
  if (seconds && metres >= 100) { const pace = seconds / (metres / 1000); parts.push(Math.floor(pace / 60) + "'" + String(Math.round(pace % 60)).padStart(2, "0") + "\"/km"); }
  if (count) parts.push(number(count) + "회");
  return parts.join(" · ");
}
function setText(set, tracking = "weight_reps") {
  const config = TRACKING[tracking];
  if (config.cardio) return cardioSummary([set]) || "—";
  return config.fields.map((name) => {
    const field = FIELDS[name], value = set[field.key];
    if (value == null) return "—";
    return name === "weight" ? number(value) + "kg" : name === "seconds" ? value + "초" : String(value);
  }).join(" × ");
}
// Sets of an exercise in the most recent other workout we have loaded.
function previousSets(exerciseId, workout) {
  const earlier = state.workouts.filter((item) => item.id !== workout.id && (item.workout_date < workout.workout_date || (item.workout_date === workout.workout_date && item.id < workout.id)));
  for (const item of earlier) {
    const sets = item.sets.filter((set) => set.exercise_id === exerciseId).sort((a, b) => a.set_number - b.set_number);
    if (sets.length) return sets;
  }
  return [];
}
const userExercise = (exercise) => state.exercises.find((item) => item.id === exercise.id) || exercise;

// ---- session editor ------------------------------------------------------------------------------
function setPayload(set, changes = {}) {
  const payload = {exercise_id: set.exercise_id, set_number: set.set_number, weight: set.weight, reps: set.reps, completed: set.completed, memo: set.memo, variant: set.variant ?? null};
  for (const key of CARDIO_FIELDS) payload[key] = set[key] ?? null;
  return {...payload, ...changes};
}
async function refreshWorkout(workout) {
  const fresh = await api("/workouts/" + workout.id);
  Object.assign(workout, fresh);
  const index = state.workouts.findIndex((item) => item.id === fresh.id);
  if (index >= 0) state.workouts[index] = fresh;
  renderCurrent();
}
function renderCurrent() {
  if (state.current) renderSession(state.current, $("#workout-detail"), true);
  const today = state.workouts.find((item) => item.workout_date === localDate());
  if (!location.hash.slice(1)) renderToday(today);
}
function fieldInput(workout, set, field, prev, label) {
  const input = node("input");
  input.type = field.mode === "time" ? "text" : "number";
  if (field.mode === "time") { input.inputMode = "numeric"; input.placeholder = prev ? fieldValue(field, prev) || "분:초" : "분:초"; input.pattern = "[0-9:]*"; }
  else { input.min = field.key === "incline_pct" ? "-30" : "0"; input.step = field.mode === "numeric" ? "1" : "any"; input.inputMode = field.mode === "numeric" ? "numeric" : "decimal"; input.placeholder = prev ? fieldValue(field, prev) : ""; }
  input.value = fieldValue(field, set);
  input.setAttribute("aria-label", set.exercise.name + " " + set.set_number + " " + label);
  input.addEventListener("change", () => mutate(input, async () => {
    const value = readField(field, input.value);
    if (Number.isNaN(value)) { input.value = fieldValue(field, set); throw new Error(label + " 값을 확인해 주세요." + (field.mode === "time" ? " 예: 30 (분), 30:15, 1:05:00" : "")); }
    await api("/workouts/" + workout.id + "/sets/" + set.id, "PUT", setPayload(set, {[field.key]: value}));
    set[field.key] = value;
    if (TRACKING[trackingOf(userExercise(set.exercise))].cardio) await refreshWorkout(workout);
  }));
  const cell = node("span", null, "set-cell"); cell.append(input);
  return cell;
}
function setRow(workout, set, prev, tracking, variant = null) {
  const config = TRACKING[tracking];
  const row = node("div", null, "set-line" + (set.completed ? " done" : ""));
  row.setAttribute("role", "row");
  row.append(node("span", String(set.set_number), "set-no"));
  if (!config.cardio) {
    const cell = node("span", null, "set-prev");
    if (variant) cell.append(node("b", variant.label, "set-variant"));
    cell.append(node("span", prev ? setText(prev, tracking).replace(/kg/g, "").replace(/ × /g, "×") : "—"));
    row.append(cell);
  }
  for (const name of config.fields) {
    const field = FIELDS[name];
    row.append(fieldInput(workout, set, field, prev, name === "weight" && config.weightLabel ? "추가 중량" : field.label));
  }
  const done = node("button", null, "set-done"); done.type = "button";
  done.innerHTML = SVG_CHECK;
  done.setAttribute("aria-pressed", String(set.completed));
  done.setAttribute("aria-label", set.exercise.name + " " + set.set_number + (config.cardio ? "구간 " : "세트 ") + (set.completed ? "완료 취소" : "완료"));
  done.addEventListener("click", () => mutate(done, async () => {
    // Completing an empty row adopts the previous session's numbers, like most workout loggers.
    const changes = {completed: !set.completed};
    const keys = [...new Set(config.fields.map((name) => FIELDS[name].key))];
    if (!set.completed && prev && keys.every((key) => set[key] == null)) for (const key of keys) changes[key] = prev[key] ?? null;
    await api("/workouts/" + workout.id + "/sets/" + set.id, "PUT", setPayload(set, changes));
    await refreshWorkout(workout);
  }));
  const remove = node("button", "×", "set-remove"); remove.type = "button";
  remove.setAttribute("aria-label", set.exercise.name + " " + set.set_number + (config.cardio ? "구간" : "세트") + " 삭제");
  remove.addEventListener("click", () => mutate(remove, async () => {
    await api("/workouts/" + workout.id + "/sets/" + set.id, "DELETE");
    await refreshWorkout(workout);
  }));
  row.append(done, remove);
  // Strength rows: number, previous, fields, done, remove. Cardio rows have no "previous" column.
  row.style.gridTemplateColumns = (config.cardio ? "28px " : "28px minmax(0,1fr) ") + "repeat(" + config.fields.length + ",minmax(0," + (config.cardio ? "1fr" : "64px") + ")) 40px 24px";
  return row;
}
// Session-level calories and average heart rate live on the first row of a cardio exercise.
function extrasRow(workout, first) {
  const box = node("div", null, "cardio-extras");
  for (const [key, label] of [["calories", "소모 kcal"], ["heart_rate", "평균 심박"]]) {
    const wrap = node("label", null, "extra-field");
    wrap.append(node("span", label));
    const input = node("input"); input.type = "number"; input.min = key === "heart_rate" ? "20" : "0"; input.step = "1"; input.inputMode = "numeric";
    input.value = first[key] ?? ""; input.placeholder = "선택";
    input.addEventListener("change", () => mutate(input, async () => {
      const value = input.value === "" ? null : Math.round(Number(input.value));
      await api("/workouts/" + workout.id + "/sets/" + first.id, "PUT", setPayload(first, {[key]: value}));
      first[key] = value;
    }));
    wrap.append(input); box.append(wrap);
  }
  return box;
}
// ---- grip / foot position / stance (preset "variants", optional per set) -------------------------------
const variantOf = (preset, id) => preset?.variants?.find((item) => item.id === id) || null;
// The variant picked for new sets of this exercise in this workout: the last choice, else the last set's.
function pickedVariant(workout, exerciseId, sets) {
  const key = workout.id + ":" + exerciseId;
  return key in state.variants ? state.variants[key] : sets.at(-1)?.variant ?? null;
}
function variantChips(workout, exercise, preset, sets, picked) {
  const box = node("div", null, "variant-box");
  const groups = node("div", null, "variant-groups");
  for (const group of [...new Set(preset.variants.map((item) => item.group))]) {
    const column = node("div", null, "variant-group");
    const row = node("div", null, "chips");
    for (const item of preset.variants.filter((variant) => variant.group === group)) {
      const on = item.id === picked;
      const chip = button(item.label, (control) => mutate(control, async () => {
        // Picking applies to new sets and to this exercise's sets not done yet; done sets keep theirs.
        const next = on ? null : item.id;
        state.variants[workout.id + ":" + exercise.id] = next;
        for (const set of sets.filter((set) => !set.completed && (set.variant ?? null) !== next)) {
          await api("/workouts/" + workout.id + "/sets/" + set.id, "PUT", setPayload(set, {variant: next}));
        }
        await refreshWorkout(workout);
      }), "chip" + (on ? " on" : ""));
      chip.setAttribute("aria-pressed", String(on));
      chip.setAttribute("aria-label", exercise.name + " " + group + " " + item.label);
      row.append(chip);
    }
    column.append(row, node("span", group, "variant-group-label"));
    groups.append(column);
  }
  const chosen = variantOf(preset, picked);
  box.append(groups, node("p", chosen ? chosen.detail + " · " + chosen.note : "선택 안 함 · 기구의 기본 자극 부위로 표시해요", "variant-note"));
  return box;
}

function exerciseBlock(workout, sets) {
  const exercise = userExercise(sets[0].exercise);
  const preset = presetOf(exercise);
  const tracking = trackingOf(exercise), config = TRACKING[tracking];
  const prev = previousSets(exercise.id, workout);
  const picked = preset?.variants ? pickedVariant(workout, exercise.id, sets) : null;
  const block = node("article", null, "ex-block" + (config.cardio ? " cardio" : ""));
  const title = button("", () => openInfo(exercise), "ex-title");
  title.append(thumb(variantOf(preset, picked)?.muscles || preset?.muscles, exercise.name));
  const text = node("span", null, "ex-text");
  const last = prev.length ? (config.cardio ? " · 지난번 " + (cardioSummary(prev) || "기록 있음") : " · 지난번 " + setText(prev[0], tracking) + " × " + prev.length) : "";
  text.append(node("strong", exercise.name), node("span", describe(exercise) + last));
  title.append(text);
  title.insertAdjacentHTML("beforeend", SVG_CHEVRON);
  block.append(title);
  if (preset?.variants) block.append(variantChips(workout, exercise, preset, sets, picked));
  const table = node("div", null, "set-table"); table.setAttribute("role", "table");
  table.setAttribute("aria-label", exercise.name + (config.cardio ? " 구간" : " 세트"));
  const header = node("div", null, "set-line set-header"); header.setAttribute("role", "row");
  const labels = [config.cardio ? "구간" : "세트", ...(config.cardio ? [] : ["이전"]),
    ...config.fields.map((name) => name === "weight" && config.weightLabel ? config.weightLabel : FIELDS[name].label), "완료", ""];
  for (const label of labels) header.append(node("span", label));
  header.style.gridTemplateColumns = (config.cardio ? "28px " : "28px minmax(0,1fr) ") + "repeat(" + config.fields.length + ",minmax(0," + (config.cardio ? "1fr" : "64px") + ")) 40px 24px";
  table.append(header);
  sets.forEach((set, index) => {
    const same = prev.filter((item) => (item.variant ?? null) === (set.variant ?? null));
    table.append(setRow(workout, set, (same.length ? same : prev)[same.length ? Math.min(index, same.length - 1) : index], tracking, variantOf(preset, set.variant)));
  });
  block.append(table);
  if (config.cardio) {
    const summary = cardioSummary(sets);
    if (summary) block.append(node("p", (sets.length > 1 ? "합계 " : "") + summary, "cardio-summary"));
    block.append(extrasRow(workout, sets[0]));
  }
  const actions = node("div", null, "ex-actions");
  actions.append(button(config.cardio ? "+ 구간 추가" : "+ 세트 추가", (control) => mutate(control, async () => {
    const lastSet = sets.at(-1);
    const copy = Object.fromEntries(config.fields.map((name) => [FIELDS[name].key, lastSet[FIELDS[name].key] ?? null]));
    await api("/workouts/" + workout.id + "/sets", "POST", {...setPayload(lastSet, {}), ...Object.fromEntries(CARDIO_FIELDS.map((key) => [key, null])), ...copy,
      set_number: Math.max(...sets.map((set) => set.set_number)) + 1, completed: false, memo: null, variant: picked});
    await refreshWorkout(workout);
  }), "dashed"), button("종목 빼기", (control) => {
    if (!confirm(exercise.name + "의 " + (config.cardio ? "기록" : "세트 " + sets.length + "개") + "를 이 운동에서 지울까요?")) return;
    mutate(control, async () => {
      for (const set of sets) await api("/workouts/" + workout.id + "/sets/" + set.id, "DELETE");
      await refreshWorkout(workout);
    });
  }, "link-button danger"));
  block.append(actions);
  return block;
}
function renderSession(workout, root, detail = false) {
  root.replaceChildren();
  const head = node("div", null, "session-head");
  const titles = node("div");
  const running = workout.started_at && !workout.ended_at && workout.workout_date === localDate();
  const status = running ? "● 진행 중 · " + Math.max(1, Math.round((Date.now() - new Date(workout.started_at)) / 60000)) + "분"
    : workout.workout_date + (workout.body_part ? " · " + workout.body_part : "");
  titles.append(node("p", status, running ? "session-status running" : "session-status"), node("h2", workout.title));
  head.append(titles);
  const tools = node("div", null, "session-tools");
  if (running) tools.append(button("운동 끝내기", (control) => mutate(control, async () => {
    await api("/workouts/" + workout.id, "PUT", {workout_date: workout.workout_date, title: workout.title, body_part: workout.body_part,
      memo: workout.memo, started_at: workout.started_at, ended_at: new Date().toISOString()});
    await refreshWorkout(workout); notice("운동을 마쳤습니다. 수고했어요!");
  })));
  tools.append(button("수정", () => openWorkout(workout)));
  if (detail) tools.append(button("삭제", (control) => {
    if (!confirm("이 운동과 모든 세트를 삭제할까요?")) return;
    mutate(control, async () => { await api("/workouts/" + workout.id, "DELETE"); notice("운동을 삭제했습니다."); location.hash = ""; });
  }, "danger"));
  head.append(tools);
  root.append(head);
  if (workout.memo) root.append(node("p", workout.memo, "memo"));
  const groups = new Map();
  for (const set of [...workout.sets].sort((a, b) => a.id - b.id)) {
    if (!groups.has(set.exercise_id)) groups.set(set.exercise_id, []);
    groups.get(set.exercise_id).push(set);
  }
  for (const sets of groups.values()) root.append(exerciseBlock(workout, sets.sort((a, b) => a.set_number - b.set_number)));
  if (!groups.size) root.append(node("p", "아직 운동이 없어요. 아래에서 운동을 추가해 보세요.", "empty-state"));
  const add = button("", () => openPicker(workout), "primary add-exercise");
  add.innerHTML = SVG_PLUS + "<span>운동 추가</span>";
  root.append(add);
}
function renderToday(today) {
  const root = $("#today-card");
  if (today) { renderSession(today, root); return; }
  root.replaceChildren();
  const start = node("div", null, "start-card");
  start.append(node("h2", "오늘 운동을 시작해 볼까요?"), node("p", "운동을 추가하면 세트를 바로 기록할 수 있어요. 지난 운동의 ‘다시 하기’로 같은 구성을 불러올 수도 있어요.", "muted"));
  const go = button("", (control) => mutate(control, async () => {
    const workout = await api("/workouts", "POST", {workout_date: localDate(), title: "오늘 운동", started_at: new Date().toISOString()});
    state.workouts.unshift(workout); renderToday(workout); openPicker(workout);
  }), "primary add-exercise");
  go.innerHTML = SVG_PLUS + "<span>오늘 운동 시작</span>";
  start.append(go);
  root.append(start);
}

// ---- list ---------------------------------------------------------------------------------------
function pastItem(workout) {
  const item = node("div", null, "past-item");
  const link = node("a", null, "past-link"); link.href = "/workouts#" + workout.id;
  const date = node("span", null, "past-date");
  date.append(node("span", Number(workout.workout_date.slice(5, 7)) + "월"), node("b", String(Number(workout.workout_date.slice(8)))));
  const names = [...new Set(workout.sets.map((set) => set.exercise.name))];
  const text = node("span", null, "past-text");
  text.append(node("strong", workout.title), node("span", (names.slice(0, 3).join(" · ") || "세트 없음") + (names.length > 3 ? " 외" : "") + " · " + workout.sets.length + "세트"));
  link.append(date, text);
  item.append(link);
  if (workout.sets.length) item.append(button("다시 하기", (control) => mutate(control, () => repeat(workout)), "small"));
  return item;
}
// Copy a past session's exercises and numbers into today's workout as unfinished sets.
async function repeat(source) {
  let today = state.workouts.find((item) => item.workout_date === localDate());
  if (!today) {
    today = await api("/workouts", "POST", {workout_date: localDate(), title: source.title, body_part: source.body_part, started_at: new Date().toISOString()});
    state.workouts.unshift(today);
  }
  const used = new Map();
  for (const set of today.sets) used.set(set.exercise_id, Math.max(used.get(set.exercise_id) || 0, set.set_number));
  for (const set of [...source.sets].sort((a, b) => a.id - b.id)) {
    const next = (used.get(set.exercise_id) || 0) + 1; used.set(set.exercise_id, next);
    // Plans copy over; outcomes (calories, heart rate) do not.
    await api("/workouts/" + today.id + "/sets", "POST", setPayload(set, {set_number: next, completed: false, memo: null, calories: null, heart_rate: null}));
  }
  notice("‘" + source.title + "’ 구성을 오늘 운동에 불러왔어요.");
  if (location.hash) location.hash = ""; else await showRoute();
  window.scrollTo({top: 0, behavior: "smooth"});
}
function renderWeek() {
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const monday = new Date(today); monday.setDate(today.getDate() - (today.getDay() + 6) % 7);
  const days = Array.from({length: 7}, (_, i) => { const d = new Date(monday); d.setDate(monday.getDate() + i); return localDate(d); });
  const week = state.workouts.filter((item) => item.workout_date >= days[0] && item.workout_date <= days[6]);
  const done = week.flatMap((item) => item.sets.filter((set) => set.completed));
  const volume = done.filter((set) => !TRACKING[trackingOf(userExercise(set.exercise))].cardio).reduce((sum, set) => sum + (set.weight || 0) * (set.reps || 0), 0);
  $("#week-count").textContent = week.length;
  $("#week-sets").textContent = done.filter((set) => !TRACKING[trackingOf(userExercise(set.exercise))].cardio).length;
  $("#week-volume").textContent = volume >= 1000 ? number(volume / 1000) + " t" : number(volume) + " kg";
  const cardio = done.filter((set) => TRACKING[trackingOf(userExercise(set.exercise))].cardio);
  const minutes = Math.round(cardio.reduce((sum, set) => sum + (set.duration_seconds || 0), 0) / 60);
  const metres = cardio.reduce((sum, set) => sum + (rowDistance(set) || 0), 0);
  $("#week-cardio").textContent = minutes || metres ? "유산소 " + [minutes && minutes + "분", metres && number(metres / 1000) + "km"].filter(Boolean).join(" · ") : "";
  const bars = $("#week-bars"); bars.replaceChildren();
  ["월", "화", "수", "목", "금", "토", "일"].forEach((name, i) => {
    const trained = week.some((item) => item.workout_date === days[i]);
    const item = node("li", null, (trained ? "on" : "") + (days[i] === localDate() ? " today" : ""));
    item.setAttribute("aria-label", name + "요일 " + (trained ? "운동함" : "운동 안 함"));
    item.append(node("span", name)); bars.append(item);
  });
}
async function loadList(append = false) {
  const route = state.route;
  const items = await api("/workouts?" + new URLSearchParams({limit: pageSize, offset: append ? state.offset : 0}));
  if (route !== state.route) return;
  state.workouts = append ? [...state.workouts, ...items] : items;
  state.offset = state.workouts.length;
  const past = state.workouts.filter((item) => item.workout_date !== localDate());
  $("#workout-list").replaceChildren(...past.map(pastItem));
  if (!past.length) $("#workout-list").append(node("p", "지난 운동 기록이 아직 없어요.", "empty-state"));
  $("#load-more").hidden = items.length < pageSize;
  renderWeek();
  renderToday(state.workouts.find((item) => item.workout_date === localDate()));
}
async function showRoute() {
  const route = ++state.route;
  const hash = location.hash.slice(1);
  state.current = null;
  $("#list-view").hidden = Boolean(hash);
  $("#detail-view").hidden = !hash;
  try {
    await Promise.all([loadCatalog(), loadExercises()]);
    if (!hash) { await loadList(); return; }
    $("#workout-detail").replaceChildren(node("p", "기록을 불러오는 중…", "empty-state"));
    if (!/^\d+$/.test(hash)) throw new Error("잘못된 운동 주소입니다.");
    if (!state.workouts.length) state.workouts = await api("/workouts?limit=" + pageSize);
    const workout = await api("/workouts/" + hash);
    if (route !== state.route) return;
    state.current = workout; renderSession(workout, $("#workout-detail"), true);
  } catch (error) {
    if (route !== state.route) return;
    notice(error.message, true);
    (hash ? $("#workout-detail") : $("#workout-list")).replaceChildren(node("p", "기록을 불러오지 못했습니다. 연결을 확인하고 새로고침해 주세요.", "empty-state"));
  }
}

// ---- picker -------------------------------------------------------------------------------------
const squash = (text) => text.replace(/\s+/g, "").toLowerCase();
function candidates() {
  const custom = state.exercises.filter((exercise) => !exercise.preset_id).map((exercise) => ({
    key: "e" + exercise.id, exercise, name: exercise.name, names: [exercise.name], part: exercise.body_part, gear: exercise.category,
    tags: [exercise.body_part, exercise.category].filter(Boolean), muscles: [], meta: describe(exercise) + " · 내 종목"}));
  const presets = state.presets.map((preset) => ({
    key: "p" + preset.id, preset, exercise: state.exercises.find((exercise) => exercise.preset_id === preset.id) || null,
    name: preset.name, names: [preset.name, preset.name_en, ...preset.aliases], part: preset.body_part, gear: preset.equipment,
    tags: preset.tags, muscles: preset.muscles,
    meta: [preset.body_part, preset.equipment, {compound: "복합", isolation: "고립", cardio: "유산소"}[preset.kind]].join(" · ")
      + (preset.variants ? " · 그립·자세 " + preset.variants.length + "종" : preset.aliases.length ? " · " + preset.aliases[0] : "")}));
  return [...custom, ...presets];
}
function renderPicker() {
  const picker = state.picker;
  const query = squash($("#picker-query").value);
  const chips = (root, values, current, pick) => {
    root.replaceChildren(...values.map((value) => {
      const chip = button(value, () => { pick(value); renderPicker(); }, "chip" + (value === current ? " on" : ""));
      chip.setAttribute("aria-pressed", String(value === current));
      return chip;
    }));
  };
  chips($("#picker-parts"), ["전체", ...state.catalog.parts], picker.part, (value) => picker.part = value);
  chips($("#picker-gear"), ["전체", "맨몸", "기구", ...state.catalog.equipment.filter((gear) => gear !== "맨몸")], picker.gear, (value) => picker.gear = value);
  const hits = candidates().filter((item) => (picker.part === "전체" || item.part === picker.part)
    && (picker.gear === "전체" || item.gear === picker.gear || item.tags.includes(picker.gear))
    && (!query || item.names.some((name) => squash(name).includes(query))));
  // Exercises the user already has come first, then name order.
  hits.sort((a, b) => Number(!a.exercise) - Number(!b.exercise) || a.name.localeCompare(b.name, "ko"));
  $("#picker-count").textContent = [query && "‘" + $("#picker-query").value.trim() + "’", picker.part !== "전체" && picker.part, picker.gear !== "전체" && picker.gear].filter(Boolean).join(" · ") + (query || picker.part !== "전체" || picker.gear !== "전체" ? " " : "") + hits.length + "개";
  const results = $("#picker-results");
  results.replaceChildren(...hits.slice(0, 80).map((item) => {
    const row = node("div", null, "pick-row" + (picker.picked.has(item.key) ? " on" : ""));
    const info = button("", () => openInfo(item.exercise || {name: item.name, preset_id: item.preset?.id}, item), "pick-info");
    info.setAttribute("aria-label", item.name + " 자세히");
    info.append(thumb(item.muscles, item.name));
    const text = node("span", null, "ex-text");
    text.append(node("strong", item.name), node("span", item.meta));
    info.append(text);
    const toggle = node("button", null, "pick-toggle"); toggle.type = "button";
    const on = picker.picked.has(item.key);
    toggle.innerHTML = on ? SVG_CHECK : SVG_PLUS;
    toggle.setAttribute("aria-pressed", String(on));
    toggle.setAttribute("aria-label", item.name + (on ? " 선택 해제" : " 선택"));
    toggle.addEventListener("click", () => { if (on) picker.picked.delete(item.key); else picker.picked.set(item.key, item); renderPicker(); });
    row.append(info, toggle);
    return row;
  }));
  if (!hits.length) results.append(node("p", "조건에 맞는 운동이 없어요.", "empty-state"));
  const typed = $("#picker-query").value.trim();
  const exact = candidates().some((item) => item.names.some((name) => squash(name) === query));
  $("#picker-custom").hidden = !typed || exact;
  $("#picker-custom").textContent = "‘" + typed + "’ 내 종목으로 만들기" + (picker.part !== "전체" ? " · " + picker.part : "") + (!["전체", "기구"].includes(picker.gear) ? " · " + picker.gear : "");
  $("#picker-selected").textContent = picker.picked.size + "개 선택";
  $("#picker-add").disabled = !picker.picked.size;
}
async function openPicker(workout) {
  try {
    await Promise.all([loadCatalog(), loadExercises()]);
    Object.assign(state.picker, {workout, picked: new Map()});
    $("#picker-query").value = "";
    renderPicker();
    $("#picker-dialog").showModal();
  } catch (error) { notice(error.message, true); }
}
// The user's exercise for a picked item: the linked one, one with the same name, or a new one.
async function ensureExercise(item) {
  if (item.exercise) return item.exercise;
  const same = state.exercises.find((exercise) => exercise.name === item.name);
  if (same) return same;
  const body = item.preset ? {name: item.preset.name, body_part: item.preset.body_part, category: item.preset.equipment, preset_id: item.preset.id}
    : {name: item.name, body_part: item.part || null, category: item.gear || null};
  const created = await api("/exercises", "POST", body);
  state.exercises.push(created);
  return created;
}
async function addPicked(items) {
  const workout = state.picker.workout;
  for (const item of items) {
    const exercise = await ensureExercise(item);
    const sets = workout.sets.filter((set) => set.exercise_id === exercise.id);
    const created = await api("/workouts/" + workout.id + "/sets", "POST", {exercise_id: exercise.id,
      set_number: Math.max(0, ...sets.map((set) => set.set_number)) + 1, weight: null, reps: null, completed: false, memo: null});
    workout.sets.push(created);
  }
  $("#picker-dialog").close();
  await refreshWorkout(workout);
  notice(items.length + "개 운동을 추가했어요. 세트 표에 중량과 횟수를 적어 주세요.");
}

// ---- exercise sheet -----------------------------------------------------------------------------
function showTab(muscle) {
  $("#tab-muscle").setAttribute("aria-selected", String(muscle));
  $("#tab-motion").setAttribute("aria-selected", String(!muscle));
  $("#info-muscle").hidden = !muscle; $("#info-motion").hidden = muscle;
}
function openInfo(exercise, item = null) {
  const preset = item?.preset || presetOf(exercise);
  $("#info-title").textContent = exercise.name || preset?.name;
  $("#info-sub").textContent = preset ? [preset.name_en, ...preset.aliases].join(" · ") : "내 종목 · 프리셋과 연결되지 않아 근육 그림이 없어요";
  const tracking = TRACKING[preset?.tracking] ? preset.tracking : "weight_reps";
  $("#info-tracking").textContent = "기록 방식 · " + (state.catalog?.tracking?.[tracking] || "중량 × 횟수");
  const tags = $("#info-tags"); tags.replaceChildren();
  for (const tag of preset ? preset.tags : [exercise.body_part, exercise.category].filter(Boolean)) tags.append(node("span", tag, "tag"));
  $("#info-muscle").replaceChildren(preset ? FitAnatomy.figure(preset.muscles) : node("p", "근육 정보가 없어요.", "empty-state"));
  // Variants: switch the figure between the default and each grip / foot position / stance.
  const variants = $("#info-variants"); variants.replaceChildren(); variants.hidden = !preset?.variants;
  if (preset?.variants) {
    const note = node("p", "기본 · 그립을 고르지 않았을 때의 자극 부위", "variant-note");
    const show = (item, chip) => {
      $("#info-muscle").replaceChildren(FitAnatomy.figure(item ? item.muscles : preset.muscles));
      note.textContent = item ? item.label + " · " + item.detail + " · " + item.note : "기본 · 그립을 고르지 않았을 때의 자극 부위";
      variants.querySelectorAll(".chip").forEach((other) => { other.classList.toggle("on", other === chip); other.setAttribute("aria-pressed", String(other === chip)); });
    };
    const row = node("div", null, "chips");
    const base = button("기본", (chip) => show(null, chip), "chip on"); base.setAttribute("aria-pressed", "true");
    row.append(base);
    for (const item of preset.variants) { const chip = button(item.label, (control) => show(item, control), "chip"); chip.setAttribute("aria-pressed", "false"); row.append(chip); }
    variants.append(row, note);
  }
  showTab(true);
  const records = $("#info-records"); records.replaceChildren();
  const sets = exercise.id ? state.workouts.flatMap((workout) => workout.sets.filter((set) => set.exercise_id === exercise.id && set.completed).map((set) => ({...set, date: workout.workout_date}))) : [];
  records.append(node("h3", "내 기록"));
  if (!sets.length) records.append(node("p", "최근 기록이 없어요.", "muted"));
  else {
    const latestDate = sets.reduce((a, b) => b.date > a.date ? b : a).date;
    let cells;
    if (TRACKING[tracking].cardio) {
      // Cardio: per-day sessions (all intervals of a day together).
      const days = [...sets.reduce((map, set) => map.set(set.date, [...(map.get(set.date) || []), set]), new Map()).values()];
      const total = (day, f) => day.reduce((sum, set) => sum + (f(set) || 0), 0);
      const far = days.reduce((a, b) => total(b, rowDistance) > total(a, rowDistance) ? b : a);
      const long = days.reduce((a, b) => total(b, (s) => s.duration_seconds) > total(a, (s) => s.duration_seconds) ? b : a);
      cells = [["최장 거리", total(far, rowDistance) ? number(total(far, rowDistance) / 1000) + "km" : "—"],
        ["최장 시간", total(long, (s) => s.duration_seconds) ? clock(total(long, (s) => s.duration_seconds)) : "—"],
        ["최근", cardioSummary(sets.filter((set) => set.date === latestDate)) || "—"]];
    } else if (tracking === "hold") {
      const best = sets.reduce((a, b) => (b.duration_seconds ?? -1) > (a.duration_seconds ?? -1) ? b : a);
      cells = [["최장 시간", best.duration_seconds != null ? best.duration_seconds + "초" : "—"], ["최근", setText(sets.find((set) => set.date === latestDate), tracking)], ["완료 세트", sets.length + "세트"]];
    } else {
      const best = sets.reduce((a, b) => (b.weight ?? -1) > (a.weight ?? -1) ? b : a);
      cells = [["최고 중량", setText(best, tracking)], ["최근", setText(sets.find((set) => set.date === latestDate), tracking)], ["완료 세트", sets.length + "세트"]];
    }
    const grid = node("div", null, "record-grid");
    for (const [label, value] of cells) {
      const cell = node("p"); cell.append(node("span", label), node("strong", value)); grid.append(cell);
    }
    records.append(grid, node("p", "최근 불러온 운동 " + state.workouts.length + "회 기준", "hint"));
  }
  $("#info-dialog").showModal();
}

// ---- workout & exercise forms ---------------------------------------------------------------------
function openWorkout(workout = null) {
  state.editWorkout = workout?.id ?? null;
  $("#workout-form-title").textContent = workout ? "운동 수정" : "새 운동 기록";
  fill($("#workout-form"), workout ? {...workout, started_at: localTime(workout.started_at), ended_at: localTime(workout.ended_at)} : {workout_date: localDate()});
  $("#workout-dialog").showModal();
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
    item.append(node("h3", exercise.name), node("p", describe(exercise) + (exercise.preset_id ? " · 프리셋 연결됨" : ""), "muted"));
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
$("#workout-form").addEventListener("submit", (event) => {
  event.preventDefault(); const form = event.currentTarget;
  submitForm(form, async () => {
    const body = {workout_date: form.elements.workout_date.value, title: form.elements.title.value,
      body_part: textValue(form, "body_part"), memo: textValue(form, "memo"),
      started_at: form.elements.started_at.value ? new Date(form.elements.started_at.value).toISOString() : null,
      ended_at: form.elements.ended_at.value ? new Date(form.elements.ended_at.value).toISOString() : null};
    await api("/workouts" + (state.editWorkout ? "/" + state.editWorkout : ""), state.editWorkout ? "PUT" : "POST", body);
    $("#workout-dialog").close(); notice("운동을 저장했습니다."); await showRoute();
  });
});
$("#exercise-form").addEventListener("submit", (event) => {
  event.preventDefault(); const form = event.currentTarget;
  submitForm(form, async () => {
    const current = state.exercises.find((exercise) => exercise.id === state.editExercise);
    await api("/exercises" + (state.editExercise ? "/" + state.editExercise : ""), state.editExercise ? "PUT" : "POST", {
      name: form.elements.name.value, category: textValue(form, "category"), body_part: textValue(form, "body_part"), preset_id: current?.preset_id ?? null
    });
    resetExercise(); await loadExercises(); renderExercises();
  });
});
$("#picker-query").addEventListener("input", renderPicker);
$("#picker-add").addEventListener("click", (event) => mutate(event.currentTarget, () => addPicked([...state.picker.picked.values()])));
$("#picker-custom").addEventListener("click", (event) => mutate(event.currentTarget, async () => {
  const picker = state.picker;
  await addPicked([{key: "new", name: $("#picker-query").value.trim(), part: picker.part === "전체" ? null : picker.part,
    gear: ["전체", "기구"].includes(picker.gear) ? null : picker.gear}]);
}));
$("#tab-muscle").addEventListener("click", () => showTab(true));
$("#tab-motion").addEventListener("click", () => showTab(false));
document.querySelectorAll("[data-close]").forEach((control) => control.addEventListener("click", () => control.closest("dialog").close()));
document.querySelectorAll("dialog").forEach((dialog) => dialog.addEventListener("cancel", (event) => {
  if (dialog.querySelector('[data-busy="true"]')) event.preventDefault();
}));
$("#exercise-dialog").addEventListener("close", () => showRoute());
$("#manage-exercises").addEventListener("click", async () => {
  try { await loadExercises(); resetExercise(); renderExercises(); $("#exercise-dialog").showModal(); }
  catch (error) { notice(error.message, true); }
});
$("#reset-exercise").addEventListener("click", resetExercise);
$("#load-more").addEventListener("click", (event) => mutate(event.currentTarget, () => loadList(true)));
window.addEventListener("hashchange", showRoute);
FitAnatomy.load().catch(() => {});
showRoute();
