"use strict";
// Workouts, in two tabs. 오늘: start by picking exercises (or repeat a recent routine), then log with only the
// current exercise open, a rest timer after each set and a summary to finish. 기록: a folding calendar over the
// month's sessions, each opening to its exercises. Also the preset picker and an exercise sheet with the muscle figure.
const $ = (selector) => document.querySelector(selector);
const state = {variants: {}, workouts: [], exercises: [], presets: [], catalog: null, current: null, route: 0,
  editWorkout: null, picker: {workout: null, mode: null, part: "전체", gear: "전체", picked: new Map()},
  calendar: {month: null, day: null, picked: false, months: new Map(), stale: false, expanded: false},
  focus: null, rest: {timer: null, until: 0}, finish: null, routines: [], routineEdit: null};
const DEFAULT_TITLE = "오늘 운동";
const REST_SECONDS = 90;
const pageSize = 20;
const SVG_CHEVRON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 6l6 6-6 6"></path></svg>';
const SVG_CHECK = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12l5 5 9-10"></path></svg>';
const SVG_PLUS = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"></path></svg>';
const SVG_DOWN = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 9l6 6 6-6"></path></svg>';
const SVG_PLAY = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 4.5v15l12-7.5z"></path></svg>';
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
  } catch { throw new Error("연결이 안 돼요. 저장 중이었다면 새로고침해서 저장됐는지 확인한 뒤 다시 시도해 주세요."); }
  const data = await response.json();
  if (!response.ok) {
    const detail = data.detail;
    const error = new Error(Array.isArray(detail) ? detail.map((item) => item.msg).join("\n") : detail || "처리하지 못했어요. 다시 시도해 주세요.");
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
  window.fitlogCache.set("exercises", exercises);
}
// The catalog is linked by its version (preloaded by the page), so after the first visit it comes from the
// phone's cache until an admin changes the list.
async function loadCatalog() {
  if (state.catalog) return;
  const href = document.getElementById("preset-catalog")?.getAttribute("href");
  const response = href ? await fetch(href, {credentials: "same-origin"}).catch(() => null) : null;
  state.catalog = response?.ok ? await response.json() : await api("/exercise-presets");
  state.presets = state.catalog.presets;
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
  return [preset?.body_part || exercise.body_part, preset?.equipment || exercise.category].filter(Boolean).join(" · ");
}
// A workout started from 오늘 is saved as "오늘 운동"; until it is renamed it shows the body parts it worked.
function partsOf(workout) {
  const parts = [];
  for (const set of [...workout.sets].sort((a, b) => a.id - b.id)) {
    const exercise = userExercise(set.exercise);
    const part = presetOf(exercise)?.body_part || exercise.body_part;
    if (part && !parts.includes(part)) parts.push(part);
  }
  return parts;
}
function titleOf(workout) {
  if (workout.title !== DEFAULT_TITLE) return workout.title;
  const parts = partsOf(workout);
  return parts.length ? parts.slice(0, 2).join(" · ") + (parts.length > 2 ? " 외" : "") : DEFAULT_TITLE;
}
// ---- set fields by tracking type -----------------------------------------------------------------
// Each preset says how it is recorded (its "tracking"); custom exercises use weight × reps.
const CARDIO_FIELDS = ["duration_seconds", "distance_m", "speed_kmh", "incline_pct", "level", "calories", "heart_rate",
  "max_heart_rate", "cadence", "max_cadence", "steps", "elevation_gain_m", "best_pace_seconds"];
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
// short: the label on the exercise editor's chips (the catalog's own labels are longer).
const TRACKING = {
  weight_reps: {fields: ["weight", "reps"], short: "무게 × 횟수"},
  reps: {fields: ["weight", "reps"], weightLabel: "+kg", short: "횟수"},
  hold: {fields: ["seconds"], short: "버티기 시간"},
  weight_time: {fields: ["weight", "seconds"], short: "무게 × 시간"},
  treadmill: {fields: ["time", "speed", "incline"], cardio: true, short: "트레드밀"},
  distance: {fields: ["distance", "time"], cardio: true, short: "거리 · 시간"},
  run: {fields: ["distance", "time"], cardio: true, details: true, short: "달리기 · 걷기"},
  cardio_machine: {fields: ["time", "level", "distance"], cardio: true, short: "유산소 머신"},
  rope: {fields: ["time", "count"], cardio: true, short: "줄넘기"},
};
// A preset decides how its exercise is recorded; a user's own exercise says so itself (default weight × reps).
const trackingOf = (exercise) => [presetOf(exercise)?.tracking, exercise?.tracking].find((tracking) => TRACKING[tracking]) || "weight_reps";
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
const paceText = (seconds) => Math.floor(seconds / 60) + "'" + String(Math.round(seconds % 60)).padStart(2, "0") + "\"/km";
const rowDistance = (set) => set.distance_m ?? (set.speed_kmh != null && set.duration_seconds != null ? set.speed_kmh * set.duration_seconds / 3.6 : null);
function cardioSummary(sets) {
  const seconds = sets.reduce((sum, set) => sum + (set.duration_seconds || 0), 0);
  const metres = sets.reduce((sum, set) => sum + (rowDistance(set) || 0), 0);
  const count = sets.reduce((sum, set) => sum + (set.reps || 0), 0);
  const parts = [];
  if (seconds) parts.push(clock(seconds));
  if (metres) parts.push(number(metres / 1000) + "km");
  if (seconds && metres >= 100) parts.push(paceText(seconds / (metres / 1000)));
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
  applyWorkout(workout, await api("/workouts/" + workout.id));
}
// Use a workout the server returned (after creating sets) in place of the shown one.
function applyWorkout(workout, fresh) {
  Object.assign(workout, fresh);
  const index = state.workouts.findIndex((item) => item.id === fresh.id);
  if (index >= 0) state.workouts[index] = workout;
  renderCurrent();
}
// Edits show at once and save in the background, one request per action. Saves for a workout run in
// order so a quick second tap never lands before the first; a failed save reloads the server's copy.
const queues = new Map();
function save(workout, request) {
  const run = (queues.get(workout.id) || Promise.resolve()).then(request);
  queues.set(workout.id, run.catch(() => {}));
  return run.catch(async (error) => {
    notice(error.message + " 저장된 기록으로 되돌렸어요.", true);
    await refreshWorkout(workout).catch(() => {});
  });
}
function instant(workout, change, request) {
  change();
  renderCurrent();
  return save(workout, request);
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
  input.addEventListener("change", () => {
    const value = readField(field, input.value);
    if (Number.isNaN(value)) {
      input.value = fieldValue(field, set);
      notice(label + " 값을 확인해 주세요." + (field.mode === "time" ? " 예: 30 (분), 30:15, 1:05:00" : ""), true);
      return;
    }
    set[field.key] = value;
    // Cardio rows feed the summary line, so redraw; strength rows already show what was typed.
    if (TRACKING[trackingOf(userExercise(set.exercise))].cardio) renderCurrent();
    save(workout, () => api("/workouts/" + workout.id + "/sets/" + set.id, "PUT", setPayload(set)));
  });
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
  done.addEventListener("click", () => {
    // Completing an empty row adopts the previous session's numbers, like most workout loggers.
    const changes = {completed: !set.completed};
    const keys = [...new Set(config.fields.map((name) => FIELDS[name].key))];
    if (!set.completed && prev && keys.every((key) => set[key] == null)) for (const key of keys) changes[key] = prev[key] ?? null;
    instant(workout, () => { Object.assign(set, changes); if (set.completed && workout === todayWorkout()) afterSet(workout, set, config); },
      () => api("/workouts/" + workout.id + "/sets/" + set.id, "PUT", setPayload(set)));
  });
  const remove = node("button", "×", "set-remove"); remove.type = "button";
  remove.setAttribute("aria-label", set.exercise.name + " " + set.set_number + (config.cardio ? "구간" : "세트") + " 삭제");
  remove.addEventListener("click", () => instant(workout,
    () => { workout.sets = workout.sets.filter((item) => item.id !== set.id); },
    () => api("/workouts/" + workout.id + "/sets/" + set.id, "DELETE")));
  row.append(done, remove);
  // Strength rows: number, previous, fields, done, remove. Cardio rows have no "previous" column.
  row.style.gridTemplateColumns = (config.cardio ? "28px " : "28px minmax(0,1fr) ") + "repeat(" + config.fields.length + ",minmax(0," + (config.cardio ? "1fr" : "64px") + ")) 40px 24px";
  return row;
}
// Session-level values live on the first row of a cardio exercise: calories and average heart rate, and for
// runs and walks the rest of what a watch shows (max heart rate, cadence, steps, climb, best pace).
const EXTRAS = [["calories", "소모 kcal"], ["heart_rate", "평균 심박"]];
const RUN_EXTRAS = [["calories", "소모 kcal"], ["steps", "걸음"], ["heart_rate", "평균 심박"], ["max_heart_rate", "최대 심박"],
  ["cadence", "평균 케이던스"], ["max_cadence", "최대 케이던스"], ["best_pace_seconds", "최고 페이스", "pace"], ["elevation_gain_m", "누적 상승 m"]];
const LIMITS = {heart_rate: [20, 250], max_heart_rate: [20, 250], cadence: [0, 300], max_cadence: [0, 300], best_pace_seconds: [60, 3600]};
function extrasRow(workout, first, config) {
  const box = node("div", null, "cardio-extras" + (config.details ? " run-extras" : ""));
  for (const [key, label, mode] of config.details ? RUN_EXTRAS : EXTRAS) {
    const wrap = node("label", null, "extra-field");
    wrap.append(node("span", label));
    const input = node("input");
    if (mode === "pace") { input.type = "text"; input.inputMode = "numeric"; input.pattern = "[0-9:]*"; input.placeholder = "분:초"; input.value = first[key] != null ? clock(first[key]) : ""; }
    else { input.type = "number"; input.min = String(LIMITS[key]?.[0] ?? 0); input.step = key === "elevation_gain_m" ? "any" : "1"; input.inputMode = key === "elevation_gain_m" ? "decimal" : "numeric"; input.placeholder = "선택"; input.value = first[key] ?? ""; }
    input.addEventListener("change", () => {
      const value = mode === "pace" ? parseClock(input.value) : input.value === "" ? null : key === "elevation_gain_m" ? Number(input.value) : Math.round(Number(input.value));
      const [low, high] = LIMITS[key] || [0, Infinity];
      if (value != null && (!Number.isFinite(value) || value < low || value > high)) {
        input.value = first[key] == null ? "" : mode === "pace" ? clock(first[key]) : first[key];
        notice(label + " 값을 확인해 주세요." + (mode === "pace" ? " 1km당 분:초로 적어요. 예: 4:31" : ""), true);
        return;
      }
      first[key] = value;
      save(workout, () => api("/workouts/" + workout.id + "/sets/" + first.id, "PUT", setPayload(first)));
    });
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
      const chip = button(item.label, () => {
        // Picking applies to new sets and to this exercise's sets not done yet; done sets keep theirs.
        const next = on ? null : item.id;
        instant(workout, () => {
          state.variants[workout.id + ":" + exercise.id] = next;
          for (const set of sets) if (!set.completed) set.variant = next;
        }, () => api("/workouts/" + workout.id + "/exercises/" + exercise.id + "/variant", "PUT", {variant: next}));
      }, "chip" + (on ? " on" : ""));
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

// A folded exercise (today's session shows only the one in progress): name, a short summary and how many
// sets are done; tapping it opens it.
function foldedBlock(exercise, sets, config) {
  const block = node("article", null, "ex-block folded");
  const done = sets.filter((set) => set.completed).length;
  const toggle = button("", () => { state.focus = exercise.id; renderCurrent(); }, "ex-title");
  toggle.setAttribute("aria-expanded", "false");
  toggle.append(thumb(presetOf(exercise)?.muscles || exercise.muscles, exercise.name));
  const weights = [...new Set(sets.map((set) => set.weight).filter((value) => value != null))].map(number);
  const text = node("span", null, "ex-text");
  text.append(node("strong", exercise.name), node("span", config.cardio ? cardioSummary(sets) || "기록 전"
    : (weights.length ? weights.join("/") + "kg · " : "") + sets.length + "세트"));
  toggle.append(text, node("span", done === sets.length ? "완료" : done + "/" + sets.length, "ex-count num" + (done === sets.length ? " complete" : "")));
  block.append(toggle);
  return block;
}
function exerciseBlock(workout, sets, folded = false) {
  const exercise = userExercise(sets[0].exercise);
  const preset = presetOf(exercise);
  const tracking = trackingOf(exercise), config = TRACKING[tracking];
  if (folded) return foldedBlock(exercise, sets, config);
  const prev = previousSets(exercise.id, workout);
  const picked = preset?.variants ? pickedVariant(workout, exercise.id, sets) : null;
  const block = node("article", null, "ex-block" + (config.cardio ? " cardio" : ""));
  const title = button("", () => openInfo(exercise), "ex-title");
  title.append(thumb(variantOf(preset, picked)?.muscles || preset?.muscles || exercise.muscles, exercise.name));
  const text = node("span", null, "ex-text");
  const last = prev.length ? (config.cardio ? "지난번 " + (cardioSummary(prev) || "기록 있음") : "지난번 " + setText(prev[0], tracking) + " × " + prev.length) : "";
  text.append(node("strong", exercise.name), node("span", [describe(exercise), last].filter(Boolean).join(" · ")));
  title.append(text);
  if (workout === todayWorkout()) {
    const done = sets.filter((set) => set.completed).length;
    title.append(node("span", done + "/" + sets.length, "ex-count num"));
  }
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
    const seconds = sets.reduce((sum, set) => sum + (set.duration_seconds || 0), 0), metres = sets.reduce((sum, set) => sum + (rowDistance(set) || 0), 0);
    const speed = config.details && seconds && metres >= 100 ? " · " + number(metres / seconds * 3.6) + "km/h" : "";
    if (summary) block.append(node("p", (sets.length > 1 ? "합계 " : "") + summary + speed, "cardio-summary"));
    block.append(extrasRow(workout, sets[0], config));
  }
  const actions = node("div", null, "ex-actions");
  actions.append(button(config.cardio ? "+ 구간 추가" : "+ 세트 추가", (control) => mutate(control, async () => {
    const lastSet = sets.at(-1);
    const copy = Object.fromEntries(config.fields.map((name) => [FIELDS[name].key, lastSet[FIELDS[name].key] ?? null]));
    const created = await save(workout, () => api("/workouts/" + workout.id + "/sets", "POST", {...setPayload(lastSet, {}),
      ...Object.fromEntries(CARDIO_FIELDS.map((key) => [key, null])), ...copy,
      set_number: Math.max(...sets.map((set) => set.set_number)) + 1, completed: false, memo: null, variant: picked}));
    if (created?.id) { workout.sets.push(created); renderCurrent(); }
  }), "dashed"), button("종목 빼기", () => {
    if (!confirm(exercise.name + "의 " + (config.cardio ? "기록" : "세트 " + sets.length + "개") + "를 이 운동에서 지울까요?")) return;
    instant(workout, () => { workout.sets = workout.sets.filter((item) => item.exercise_id !== exercise.id); },
      () => api("/workouts/" + workout.id + "/exercises/" + exercise.id, "DELETE"));
  }, "link-button danger"));
  block.append(actions);
  return block;
}
const todayWorkout = () => state.workouts.find((item) => item.workout_date === localDate()) || null;
function exerciseGroups(workout) {
  const groups = new Map();
  for (const set of [...workout.sets].sort((a, b) => a.id - b.id)) {
    if (!groups.has(set.exercise_id)) groups.set(set.exercise_id, []);
    groups.get(set.exercise_id).push(set);
  }
  for (const sets of groups.values()) sets.sort((a, b) => a.set_number - b.set_number);
  return groups;
}
// The exercise open in today's session: the one last opened, else the first with a set still to do.
function focusOf(groups) {
  if (groups.has(state.focus)) return state.focus;
  const ids = [...groups.keys()];
  return ids.find((id) => groups.get(id).some((set) => !set.completed)) ?? ids.at(-1) ?? null;
}
const minutesSince = (value) => Math.max(1, Math.round((Date.now() - new Date(value)) / 60000));
// Today's session (focus: one exercise open, the rest folded) or a past one opened from 기록 (all open).
function renderSession(workout, root, detail = false) {
  root.replaceChildren();
  const focus = !detail && workout === todayWorkout();
  const head = node("div", null, "session-head");
  const titles = node("div");
  const open = !workout.ended_at && workout.workout_date === localDate();
  const status = open ? (workout.started_at ? "● 진행 중 · " + minutesSince(workout.started_at) + "분" : "● 진행 중")
    : (workout.workout_date === localDate() ? "오늘 · 끝냄" : workout.workout_date) + (workout.body_part ? " · " + workout.body_part : "");
  titles.append(node("p", status, open ? "session-status running" : "session-status"), node("h2", titleOf(workout)));
  head.append(titles);
  const tools = node("div", null, "session-tools");
  if (open && workout.sets.length) tools.append(button("끝내기", () => openFinish(workout), "finish-button"));
  if (!open || detail) tools.append(button("수정", () => openWorkout(workout)));
  if (detail) tools.append(button("삭제", (control) => {
    if (!confirm("이 운동과 모든 세트를 삭제할까요?")) return;
    mutate(control, async () => { await api("/workouts/" + workout.id, "DELETE"); notice("운동을 삭제했어요."); location.hash = ""; });
  }, "danger"));
  head.append(tools);
  root.append(head);
  const groups = exerciseGroups(workout);
  if (focus && workout.sets.length) {
    const done = workout.sets.filter((set) => set.completed).length;
    const progress = node("div", null, "session-progress");
    const bar = node("span", null, "progress-track"), fill = node("span", null, "progress-fill");
    fill.style.width = Math.round(done / workout.sets.length * 100) + "%";
    bar.append(fill);
    progress.append(bar, node("span", done + "/" + workout.sets.length, "num"));
    progress.setAttribute("aria-label", "세트 " + workout.sets.length + "개 중 " + done + "개 완료");
    root.append(progress);
  }
  if (workout.memo) root.append(node("p", workout.memo, "memo"));
  const opened = focus ? focusOf(groups) : null;
  for (const [id, sets] of groups) root.append(exerciseBlock(workout, sets, focus && id !== opened));
  if (!groups.size) root.append(node("p", "아직 종목이 없어요. 아래에서 종목을 추가해 보세요.", "empty-state"));
  const add = button("", () => openPicker(workout), focus ? "dashed add-more" : "primary add-exercise");
  add.innerHTML = SVG_PLUS + "<span>종목 추가</span>";
  root.append(add);
}
// Monday-to-Sunday count of sessions, for the start card.
function weekCount() {
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const monday = new Date(today); monday.setDate(today.getDate() - (today.getDay() + 6) % 7);
  return state.workouts.filter((item) => item.workout_date >= localDate(monday)).length;
}
function whenText(workout) {
  const days = Math.round((new Date(localDate() + "T12:00:00") - new Date(workout.workout_date + "T12:00:00")) / 86400000);
  const date = new Date(workout.workout_date + "T12:00:00");
  return days === 1 ? "어제" : days < 7 ? days + "일 전" : (date.getMonth() + 1) + "월 " + date.getDate() + "일";
}
// The last few distinct sessions before today, to start again with their numbers.
function recentRoutines() {
  const seen = new Set(), routines = [];
  for (const workout of state.workouts) {
    const title = titleOf(workout);
    if (workout.workout_date >= localDate() || !workout.sets.length || seen.has(title)) continue;
    seen.add(title); routines.push(workout);
    if (routines.length === 3) break;
  }
  return routines;
}
function renderToday(today) {
  const root = $("#today-card");
  if (today) { root.className = "session-card focus"; renderSession(today, root); return; }
  stopRest();
  root.className = "today-start";
  const start = node("section", null, "start-card");
  const now = new Date();
  start.append(node("p", (now.getMonth() + 1) + "월 " + now.getDate() + "일 · 이번 주 " + weekCount() + "회", "start-sub"));
  const next = nextRoutine();
  if (next) {
    // With routines: the next one in the rotation, ready to start; the others one tap away.
    const title = node("h2");
    title.append("오늘은 ", node("em", next.name), " 할 차례예요");
    start.append(title, node("p", routineSummary(next), "start-plan"));
    const go = button("", (control) => mutate(control, () => startRoutine(next)), "primary start-button");
    go.innerHTML = SVG_PLAY;
    go.append(node("span", next.name + " 시작"));
    start.append(go);
    const others = state.routines.filter((item) => item !== next);
    const row = node("div", null, "start-others");
    for (const routine of others) row.append(button(routine.name, (control) => mutate(control, () => startRoutine(routine)), "chip"));
    row.append(button("직접 고르기", (control) => mutate(control, () => openPicker(null, "start")), "chip ghost"));
    start.append(row);
  } else {
    start.append(node("h2", "오늘은 무엇을 할까요?"));
    const go = button("", (control) => mutate(control, () => openPicker(null, "start")), "primary start-button");
    go.innerHTML = SVG_PLAY + "<span>종목 골라서 시작</span>";
    start.append(go, button("자주 하는 구성을 루틴으로 저장해 두면 순서대로 알려 드려요 ›", () => openRoutines(), "link-button start-hint"));
  }
  const parts = [start];
  const routines = recentRoutines();
  if (routines.length) {
    const box = node("section", null, "routines");
    const heading = node("div", null, "routines-head");
    heading.append(node("h2", "최근 운동 다시 하기"), node("span", "지난번 무게로 채워져요"));
    box.append(heading);
    for (const workout of routines) {
      const row = node("div", null, "routine");
      const names = [...new Set(workout.sets.map((set) => set.exercise.name))];
      const text = node("span", null, "routine-text");
      const minutes = workout.started_at && workout.ended_at ? " · " + Math.round((new Date(workout.ended_at) - new Date(workout.started_at)) / 60000) + "분" : "";
      text.append(node("strong", titleOf(workout)), node("span", names.slice(0, 3).join(" · ") + (names.length > 3 ? " 외 " + (names.length - 3) : "")),
        node("small", whenText(workout) + " · " + workout.sets.length + "세트" + minutes));
      const again = button("시작", (control) => mutate(control, () => repeat(workout)), "routine-start");
      again.setAttribute("aria-label", titleOf(workout) + " 다시 시작");
      row.append(text, again);
      box.append(row);
    }
    parts.push(box);
  }
  root.replaceChildren(...parts);
}

// ---- list ---------------------------------------------------------------------------------------
// One line per exercise of a past session: its heaviest done set and how many sets (cardio: its totals).
function exerciseLines(workout) {
  return [...exerciseGroups(workout).values()].map((sets) => {
    const exercise = userExercise(sets[0].exercise), tracking = trackingOf(exercise);
    const done = sets.filter((set) => set.completed);
    const shown = done.length ? done : sets;
    if (TRACKING[tracking].cardio) return [exercise.name, cardioSummary(shown) || "기록 없음"];
    const best = shown.reduce((a, b) => (b.weight ?? -1) > (a.weight ?? -1) ? b : a);
    return [exercise.name, setText(best, tracking) + " · " + shown.length + "세트"];
  });
}
// A past session folds to a line (date, name, what it held) and opens to its exercises.
function pastItem(workout) {
  const item = node("details", null, "past-item");
  const summary = node("summary", null, "past-summary");
  const date = new Date(workout.workout_date + "T12:00:00");
  const day = node("span", null, "past-date");
  day.append(node("small", WEEKDAYS[date.getDay()]), node("b", String(date.getDate()), "num"));
  const names = [...new Set(workout.sets.map((set) => set.exercise.name))];
  // Strength work counts sets; a run or other cardio shows its distance, time and pace instead.
  const cardio = workout.sets.filter((set) => TRACKING[trackingOf(userExercise(set.exercise))].cardio);
  const strength = workout.sets.length - cardio.length;
  const amount = [strength && strength + "세트", cardioSummary(cardio)].filter(Boolean).join(" · ");
  const text = node("span", null, "past-text");
  text.append(node("strong", titleOf(workout)), node("span", (names.slice(0, 2).join(" · ") || "세트 없음") + (names.length > 2 ? " 외 " + (names.length - 2) : "") + (amount ? " · " + amount : "")));
  summary.append(day, text);
  summary.insertAdjacentHTML("beforeend", SVG_DOWN);
  const body = node("div", null, "past-body");
  for (const [name, value] of exerciseLines(workout)) {
    const line = node("p", null, "past-line");
    line.append(node("span", name), node("span", value, "num"));
    body.append(line);
  }
  const actions = node("div", null, "past-actions");
  if (workout.sets.length && workout.workout_date !== localDate()) actions.append(button("오늘 다시 하기", (control) => mutate(control, () => repeat(workout)), "primary"));
  const edit = node("a", "수정", "past-edit"); edit.href = "/workouts#" + workout.id;
  actions.append(edit);
  body.append(actions);
  item.append(summary, body);
  return item;
}
// Plans copy over; outcomes (calories, heart rate) do not.
const OUTCOMES = {calories: null, heart_rate: null, max_heart_rate: null, cadence: null, max_cadence: null, steps: null, elevation_gain_m: null, best_pace_seconds: null};
// Copy a past session's exercises and numbers into today's workout as unfinished sets.
async function repeat(source) {
  let today = todayWorkout();
  if (!today) {
    today = await api("/workouts", "POST", {workout_date: localDate(), title: titleOf(source), body_part: source.body_part, started_at: new Date().toISOString()});
    state.workouts.unshift(today);
  }
  const used = new Map();
  for (const set of today.sets) used.set(set.exercise_id, Math.max(used.get(set.exercise_id) || 0, set.set_number));
  const copies = [...source.sets].sort((a, b) => a.id - b.id).map((set) => {
    const next = (used.get(set.exercise_id) || 0) + 1; used.set(set.exercise_id, next);
    return setPayload(set, {set_number: next, completed: false, memo: null, ...OUTCOMES});
  });
  Object.assign(today, await api("/workouts/" + today.id + "/sets/batch", "POST", copies));
  notice("‘" + titleOf(source) + "’ 구성을 불러왔어요. 지난번 무게로 채웠어요.");
  showView("today");
  if (location.hash) location.hash = ""; else { renderCurrent(); renderCalendar(); }
  window.scrollTo({top: 0, behavior: "smooth"});
}
// ---- routines -------------------------------------------------------------------------------------
async function loadRoutines() {
  state.routines = await api("/routines");
  window.fitlogCache.set("routines", state.routines);
}
const exerciseById = (id) => state.exercises.find((item) => item.id === id);
// The routine after the last one done before today, in list order; the first when none was done yet.
function nextRoutine() {
  const routines = state.routines;
  if (!routines.length) return null;
  const last = state.workouts.find((item) => item.workout_date < localDate() && routines.some((routine) => routine.id === item.routine_id));
  if (!last) return routines[0];
  return routines[(routines.findIndex((routine) => routine.id === last.routine_id) + 1) % routines.length];
}
function routineSummary(routine) {
  return routine.items.map((item) => (exerciseById(item.exercise_id)?.name || "종목") + " " + item.sets).join(" · ");
}
// Today's workout from a routine: each exercise with its set count, filled from its last session.
async function startRoutine(routine) {
  if (!state.exercises.length) await loadExercises();
  let today = todayWorkout();
  if (!today) {
    today = await api("/workouts", "POST", {workout_date: localDate(), title: routine.name, routine_id: routine.id, started_at: new Date().toISOString()});
    state.workouts.unshift(today);
  }
  const additions = [];
  for (const item of routine.items) {
    const prev = previousSets(item.exercise_id, today);
    const taken = Math.max(0, ...today.sets.filter((set) => set.exercise_id === item.exercise_id).map((set) => set.set_number));
    for (let index = 0; index < item.sets; index++) {
      const source = prev[index] || prev.at(-1);
      additions.push(source ? setPayload(source, {set_number: taken + index + 1, completed: false, memo: null, ...OUTCOMES})
        : {exercise_id: item.exercise_id, set_number: taken + index + 1, weight: null, reps: null, completed: false, memo: null});
    }
  }
  state.focus = routine.items[0]?.exercise_id ?? null;
  Object.assign(today, await api("/workouts/" + today.id + "/sets/batch", "POST", additions));
  notice("‘" + routine.name + "’ 루틴을 시작했어요. 지난번 무게로 채웠어요.");
  showView("today");
  renderCurrent(); renderCalendar();
  window.scrollTo({top: 0, behavior: "smooth"});
}
async function openRoutines() {
  try {
    $("#menu-dialog").close();
    await Promise.all([loadExercises(), loadRoutines()]);
    renderRoutines();
    $("#routine-dialog").showModal();
  } catch (error) { notice(error.message, true); }
}
function renderRoutines() {
  const list = $("#routine-list");
  $("#routine-message").textContent = "";
  if (!state.routines.length) { list.replaceChildren(node("p", "아직 루틴이 없어요. 운동을 끝낼 때 '이 구성을 루틴으로 저장'으로도 만들 수 있어요.", "empty-state")); return; }
  list.replaceChildren(...state.routines.map((routine, index) => {
    const row = node("div", null, "routine-row");
    const open = button("", () => openRoutineEditor(routine), "routine-open");
    open.append(node("strong", (index + 1) + ". " + routine.name), node("span", routineSummary(routine)));
    const move = (by) => mutate(null, async () => {
      const ids = state.routines.map((item) => item.id);
      [ids[index], ids[index + by]] = [ids[index + by], ids[index]];
      state.routines = await api("/routines/order", "PUT", {ids});
      renderRoutines(); renderCurrent();
    });
    const up = button("↑", () => move(-1), "routine-move"); up.disabled = index === 0; up.setAttribute("aria-label", routine.name + " 위로");
    const down = button("↓", () => move(1), "routine-move"); down.disabled = index === state.routines.length - 1; down.setAttribute("aria-label", routine.name + " 아래로");
    row.append(open, up, down);
    return row;
  }));
}
function openRoutineEditor(routine = null) {
  state.routineEdit = {id: routine?.id ?? null, items: routine ? routine.items.map((item) => ({...item})) : []};
  const form = $("#routine-form");
  fill(form, {name: routine?.name || ""});
  $("#routine-editor-title").textContent = routine ? "루틴 고치기" : "새 루틴";
  $("#routine-delete").hidden = !routine;
  renderRoutineEditor();
  $("#routine-editor").showModal();
}
function renderRoutineEditor() {
  const edit = state.routineEdit, box = $("#routine-items");
  if (!edit.items.length) { box.replaceChildren(node("p", "아래 '+ 종목 넣기'로 종목을 골라 주세요.", "empty-state")); return; }
  box.replaceChildren(...edit.items.map((item, index) => {
    const row = node("div", null, "routine-item");
    row.append(node("span", exerciseById(item.exercise_id)?.name || "종목", "routine-item-name"));
    const step = (by) => { item.sets = Math.min(20, Math.max(1, item.sets + by)); renderRoutineEditor(); };
    const less = button("−", () => step(-1), "step"); less.setAttribute("aria-label", "세트 줄이기");
    const more = button("+", () => step(1), "step"); more.setAttribute("aria-label", "세트 늘리기");
    const up = button("↑", () => { [edit.items[index - 1], edit.items[index]] = [edit.items[index], edit.items[index - 1]]; renderRoutineEditor(); }, "step");
    up.disabled = index === 0; up.setAttribute("aria-label", "위로");
    const remove = button("×", () => { edit.items.splice(index, 1); renderRoutineEditor(); }, "step remove"); remove.setAttribute("aria-label", "빼기");
    row.append(less, node("span", item.sets + "세트", "routine-sets num"), more, up, remove);
    return row;
  }));
}
// A finished session's done sets as a routine: its exercises in order, each with how many sets were done.
function routineFrom(workout, name) {
  const items = [...exerciseGroups(workout).values()].map((sets) => ({exercise_id: sets[0].exercise_id, sets: Math.min(20, sets.filter((set) => set.completed).length)}))
    .filter((item) => item.sets > 0);
  return {name: name.slice(0, 100), items};
}

function showList(items) {
  state.workouts = items;
  renderToday(todayWorkout());
  renderCalendar();
}
// 오늘 / 기록 tabs; the choice lasts while the app is open.
function showView(view) {
  const history = view === "history";
  $("#today-view").hidden = history; $("#history-view").hidden = !history;
  $("#tab-today").setAttribute("aria-selected", String(!history)); $("#tab-history").setAttribute("aria-selected", String(history));
  try { sessionStorage.setItem("workouts:view", view); } catch {}
}

// ---- calendar -----------------------------------------------------------------------------------
// A month grid (folded to the two weeks around the picked day) and the picked day's sessions below it.
const WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"];
const monthOf = (day) => day.slice(0, 7);
function shiftMonth(month, by) {
  const [year, index] = month.split("-").map(Number);
  return localDate(new Date(year, index - 1 + by, 1)).slice(0, 7);
}
// The month's sessions as fetched, with the recent list's copies (edited on this page) taking their place.
function monthWorkouts(month) {
  const byId = new Map((state.calendar.months.get(month) || []).map((item) => [item.id, item]));
  for (const item of state.workouts) if (monthOf(item.workout_date) === month) byId.set(item.id, item);
  return [...byId.values()].sort((a, b) => b.workout_date.localeCompare(a.workout_date) || b.id - a.id);
}
function renderCalendar() {
  const calendar = state.calendar, today = localDate();
  calendar.month ??= monthOf(today);
  const month = calendar.month, items = monthWorkouts(month);
  // Until a day is tapped (calendar.picked): today when there was a session today, else the month's latest session day.
  if (!calendar.picked || monthOf(calendar.day || "") !== month) {
    calendar.picked = false;
    calendar.day = items.find((item) => item.workout_date <= today)?.workout_date || (month === monthOf(today) ? today : month + "-01");
  }
  const [year, index] = month.split("-").map(Number);
  $("#cal-title").textContent = (year === Number(today.slice(0, 4)) ? "" : year + "년 ") + index + "월";
  $("#cal-next").disabled = month >= monthOf(today);
  const sets = items.reduce((sum, item) => sum + item.sets.filter((set) => set.completed).length, 0);
  $("#cal-stats").textContent = (items.length ? items.length + "회 · " + sets + "세트 · " : "") + "통계 ›";
  const counts = items.reduce((map, item) => map.set(item.workout_date, (map.get(item.workout_date) || 0) + 1), new Map());
  const first = new Date(year, index - 1, 1), length = new Date(year, index, 0).getDate();
  const cells = Array.from({length: (first.getDay() + 6) % 7}, () => node("span", null, "cal-blank"));
  for (let date = 1; date <= length; date++) {
    const day = month + "-" + String(date).padStart(2, "0"), count = counts.get(day) || 0;
    const cell = button(String(date), () => { calendar.day = day; calendar.picked = true; renderCalendar(); },
      "cal-date" + (count ? " on" : "") + (day === today ? " today" : "") + (day > today ? " future" : ""));
    cell.setAttribute("aria-pressed", String(day === calendar.day));
    cell.setAttribute("aria-label", index + "월 " + date + "일" + (day === today ? " 오늘" : "") + (count ? ", 운동 " + count + "회" : ""));
    cells.push(cell);
  }
  // Folded: the week of the picked day (else today, else the month's last week) and the one before it.
  const anchor = calendar.day || (month === monthOf(today) ? today : month + "-" + String(length).padStart(2, "0"));
  const row = Math.floor((cells.length - length + Number(anchor.slice(8)) - 1) / 7);
  const shown = calendar.expanded ? cells : cells.slice(Math.max(0, row - 1) * 7, (row + 1) * 7);
  $("#cal-grid").replaceChildren(...shown);
  $("#cal-expand").textContent = calendar.expanded ? "달력 접기" : "달력 펼치기";
  $("#cal-expand").setAttribute("aria-expanded", String(calendar.expanded));
  const picked = items.filter((item) => item.workout_date === calendar.day);
  const panel = $("#cal-day");
  const date = new Date(calendar.day + "T12:00:00");
  const head = node("p", null, "cal-day-head");
  head.append(node("strong", (date.getMonth() + 1) + "월 " + date.getDate() + "일 " + WEEKDAYS[date.getDay()] + "요일"),
    node("span", picked.length ? "운동 " + picked.length + "회" : ""));
  panel.replaceChildren(head);
  if (picked.length) {
    const list = node("div", null, "past-list"); list.append(...picked.map(pastItem)); panel.append(list);
    if (picked.length === 1) list.firstChild.open = true;
  }
  else panel.append(node("p", calendar.day > today ? "아직 오지 않은 날이에요." : !state.calendar.months.has(month) ? "기록을 불러오는 중…" : "이 날은 운동 기록이 없어요.", "empty-state"));
  // A saved copy is read-only (다시 하기 writes) until the month's current copy is in.
  panel.inert = calendar.stale;
}
// This month comes through app.js (fitlogShow, filled by the bulk sync); others show this phone's
// copy, then fetch.
async function loadMonth(month) {
  const show = (items, stale) => {
    state.calendar.months.set(month, items);
    if (state.calendar.month !== month) return;
    state.calendar.stale = stale;
    renderCalendar();
  };
  if (month === monthOf(localDate())) { await window.fitlogShow(window.fitlogData.calendar, show); return; }
  const key = "workouts:month:" + month, cached = window.fitlogCache.get(key);
  if (cached) show(cached, true);
  const items = [];
  for (let offset = 0; ; offset += 100) {
    const page = await api("/workouts?" + new URLSearchParams({date_from: month + "-01", date_to: localDate(new Date(Number(month.slice(0, 4)), Number(month.slice(5)), 0)), limit: 100, offset}));
    items.push(...page);
    if (page.length < 100) break;
  }
  window.fitlogCache.set(key, items);
  show(items, false);
}
function moveMonth(by) {
  state.calendar.month = shiftMonth(state.calendar.month, by);
  state.calendar.day = null; state.calendar.stale = false;
  renderCalendar();
  loadMonth(state.calendar.month).catch((error) => notice(error.message, true));
}
async function showRoute() {
  const route = ++state.route;
  const hash = location.hash.slice(1);
  state.current = null;
  $("#list-view").hidden = Boolean(hash);
  $("#detail-view").hidden = !hash;
  let showedCache = false;
  try {
    // The list and exercises come through app.js (fitlogShow): the saved copy at once, read-only until
    // the current one is in (an edit made on an old copy could be overwritten by it), and a request
    // only when the bulk sync has no current copy. Each set carries its exercise, so the list does not
    // wait for /exercises (the picker does).
    const exercises = window.fitlogShow(window.fitlogData.exercises, (items) => { state.exercises = items; });
    exercises.catch(() => {});
    await loadCatalog(); // a static file from the phone's cache after the first visit
    if (route !== state.route) return;
    if (!hash) {
      state.calendar.month ??= monthOf(localDate());
      loadMonth(state.calendar.month).catch((error) => { if (route === state.route) notice(error.message, true); });
      // Routines: this phone's copy at once, then the server's (they only change the start card).
      state.routines = window.fitlogCache.get("routines") || state.routines;
      loadRoutines().then(() => {
        if (route !== state.route) return;
        // /workouts?start=<routine id> (the home's 다음 할 일) starts that routine once, unless today already has a session.
        const start = Number(new URLSearchParams(location.search).get("start"));
        if (start) {
          history.replaceState(null, "", location.pathname);
          const routine = state.routines.find((item) => item.id === start);
          if (routine && !todayWorkout()) { mutate(null, () => startRoutine(routine)); return; }
        }
        if (!todayWorkout()) renderToday(null);
      }).catch(() => {});
      await window.fitlogShow(window.fitlogData.workouts, (items, stale) => {
        if (route !== state.route) return;
        showList(items);
        $("#list-view").inert = stale;
        if (stale) showedCache = true;
      });
      return;
    }
    await exercises;
    $("#workout-detail").replaceChildren(node("p", "기록을 불러오는 중…", "empty-state"));
    if (!/^\d+$/.test(hash)) throw new Error("잘못된 운동 주소입니다.");
    if (!state.workouts.length) state.workouts = await api("/workouts?limit=" + pageSize);
    const workout = await api("/workouts/" + hash);
    if (route !== state.route) return;
    state.current = workout; renderSession(workout, $("#workout-detail"), true);
  } catch (error) {
    if (route !== state.route) return;
    $("#list-view").inert = false;
    notice(error.message, true);
    if (showedCache) return; // keep the saved copy on screen rather than an empty error
    (hash ? $("#workout-detail") : $("#workout-list")).replaceChildren(node("p", "기록을 불러오지 못했어요. 연결을 확인하고 새로고침해 주세요.", "empty-state"));
  }
}

// ---- picker -------------------------------------------------------------------------------------
const squash = (text) => text.replace(/\s+/g, "").toLowerCase();
function candidates() {
  const custom = state.exercises.filter((exercise) => !exercise.preset_id).map((exercise) => ({
    key: "e" + exercise.id, exercise, name: exercise.name, names: [exercise.name], part: exercise.body_part, gear: exercise.category,
    tags: [exercise.body_part, exercise.category].filter(Boolean), muscles: exercise.muscles || [], meta: describe(exercise) + " · 내 종목"}));
  // A preset the admin hid stays only for people who already use it.
  const presets = state.presets.filter((preset) => !preset.hidden || state.exercises.some((exercise) => exercise.preset_id === preset.id)).map((preset) => ({
    key: "p" + preset.id, preset, exercise: state.exercises.find((exercise) => exercise.preset_id === preset.id) || null,
    name: preset.name, names: [preset.name, preset.name_en, ...preset.aliases], part: preset.body_part, gear: preset.equipment,
    tags: preset.tags, muscles: preset.muscles,
    meta: [preset.body_part, preset.equipment, {compound: "복합", isolation: "고립", cardio: "유산소"}[preset.kind]].join(" · ")
      + (preset.variants ? " · 그립·자세 " + preset.variants.length + "종" : preset.aliases.length ? " · " + preset.aliases[0] : "")}));
  return [...custom, ...presets];
}
function renderPicker() {
  const picker = state.picker, browse = !picker.workout && !picker.mode; // browse: look exercises up without adding them
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
    row.append(info);
    if (!browse) row.append(toggle);
    return row;
  }));
  if (!hits.length) results.append(node("p", "조건에 맞는 운동이 없어요.", "empty-state"));
  const typed = $("#picker-query").value.trim();
  const exact = candidates().some((item) => item.names.some((name) => squash(name) === query));
  $("#picker-custom").hidden = browse || !typed || exact;
  $("#picker-custom").textContent = "‘" + typed + "’ 내 종목으로 만들기" + (picker.part !== "전체" ? " · " + picker.part : "") + (!["전체", "기구"].includes(picker.gear) ? " · " + picker.gear : "");
  $("#picker-selected").textContent = picker.picked.size + "개 선택";
  $("#picker-add").disabled = !picker.picked.size;
  $("#picker-add").textContent = picker.mode === "start" ? (picker.picked.size ? picker.picked.size + "개로 시작" : "종목을 골라 주세요")
    : picker.mode === "routine" ? "루틴에 넣기" : "종목 추가";
}
// workout: add to it. mode "start": today's workout is made when the picked exercises are added; "routine": they
// go into the routine being edited. Neither: just browse.
async function openPicker(workout = null, mode = null) {
  try {
    await Promise.all([loadCatalog(), loadExercises()]);
    Object.assign(state.picker, {workout, mode, picked: new Map()});
    $("#picker-title").textContent = mode === "start" ? "종목 고르기" : mode === "routine" ? "루틴에 넣을 종목" : workout ? "종목 추가" : "종목 둘러보기";
    $("#picker-foot").hidden = !workout && !mode;
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
// Each picked exercise comes with the sets of its last session (numbers filled, not done), else one empty set.
async function addPicked(items) {
  let workout = state.picker.workout;
  const additions = [];
  // New exercises are created side by side; then one request adds all the sets.
  const exercises = await Promise.all(items.map(ensureExercise));
  if (state.picker.mode === "routine") {
    const edit = state.routineEdit;
    for (const exercise of exercises) {
      if (edit.items.some((item) => item.exercise_id === exercise.id)) continue;
      edit.items.push({exercise_id: exercise.id, sets: previousSets(exercise.id, {id: 0, workout_date: "9999-12-31"}).length || 3});
    }
    $("#picker-dialog").close();
    renderRoutineEditor();
    return;
  }
  if (!workout) {
    workout = await api("/workouts", "POST", {workout_date: localDate(), title: DEFAULT_TITLE, started_at: new Date().toISOString()});
    state.workouts.unshift(workout);
  }
  let filled = 0;
  for (const exercise of exercises) {
    const sets = workout.sets.filter((set) => set.exercise_id === exercise.id);
    const next = Math.max(0, ...sets.map((set) => set.set_number)) + 1;
    const prev = previousSets(exercise.id, workout);
    if (prev.length) filled++;
    if (prev.length) additions.push(...prev.map((set, index) => setPayload(set, {set_number: next + index, completed: false, memo: null, ...OUTCOMES})));
    else additions.push({exercise_id: exercise.id, set_number: next, weight: null, reps: null, completed: false, memo: null});
  }
  if (!workout.sets.length) state.focus = exercises[0].id;
  applyWorkout(workout, await api("/workouts/" + workout.id + "/sets/batch", "POST", additions));
  $("#picker-dialog").close();
  if (workout === todayWorkout()) showView("today");
  notice(items.length + "개 종목을 추가했어요." + (filled ? " 지난번 무게와 횟수로 채웠어요." : ""));
}

// ---- during a session: rest timer, next exercise, finish ---------------------------------------------
// After a set is ticked: rest, and when the exercise is done, open the next one with sets left.
function afterSet(workout, set, config) {
  const groups = exerciseGroups(workout), sets = groups.get(set.exercise_id) || [];
  const left = sets.find((item) => !item.completed);
  if (!left) {
    const ids = [...groups.keys()], at = ids.indexOf(set.exercise_id);
    const next = [...ids.slice(at + 1), ...ids.slice(0, at)].find((id) => groups.get(id).some((item) => !item.completed));
    if (next != null) state.focus = next;
  }
  if (config.cardio) return;
  const nextSet = left || [...groups.values()].flat().find((item) => !item.completed);
  startRest(nextSet ? "다음 " + nextSet.exercise.name + " " + nextSet.set_number + "세트" : "마지막 세트까지 끝났어요");
}
function startRest(label) {
  state.rest.until = Date.now() + REST_SECONDS * 1000;
  $("#rest-label").textContent = "휴식 · " + label;
  clearInterval(state.rest.timer);
  state.rest.timer = setInterval(tickRest, 500);
  tickRest();
  $("#rest-bar").hidden = false;
}
function tickRest() {
  const left = Math.ceil((state.rest.until - Date.now()) / 1000);
  if (left <= 0) { stopRest(); navigator.vibrate?.(300); return; }
  $("#rest-clock").textContent = clock(left);
}
function stopRest() { clearInterval(state.rest.timer); state.rest.timer = null; $("#rest-bar").hidden = true; }

// The finish sheet: what was done, what improved, a name, a memo, and whether to drop sets left unticked.
function bestWeights(exerciseId, sets) { return Math.max(0, ...sets.filter((set) => set.exercise_id === exerciseId && set.completed).map((set) => set.weight || 0)); }
function openFinish(workout) {
  state.finish = workout;
  const done = workout.sets.filter((set) => set.completed), left = workout.sets.length - done.length;
  const strength = done.filter((set) => !TRACKING[trackingOf(userExercise(set.exercise))].cardio);
  const volume = strength.reduce((sum, set) => sum + (set.weight || 0) * (set.reps || 0), 0);
  const start = workout.started_at ? new Date(workout.started_at) : null;
  const stats = [["세트", String(done.length)], ["볼륨", volume >= 1000 ? number(volume / 1000) + "t" : number(volume) + "kg"],
    ["시간", start ? minutesSince(start) + "분" : "—"]];
  $("#finish-stats").replaceChildren(...stats.map(([label, value]) => { const cell = node("p"); cell.append(node("span", label), node("strong", value, "num")); return cell; }));
  $("#finish-time").textContent = workout.workout_date.slice(5).replace("-", "월 ").replace(/^0/, "") + "일" + (start ? " · " + start.toTimeString().slice(0, 5) + " 시작" : "");
  // Heaviest weight per exercise against every earlier session loaded on this page.
  const earlier = state.workouts.filter((item) => item.id !== workout.id && item.workout_date <= workout.workout_date).flatMap((item) => item.sets);
  const better = [...new Set(strength.map((set) => set.exercise_id))].map((id) => {
    const now = bestWeights(id, workout.sets), before = bestWeights(id, earlier);
    return {name: strength.find((set) => set.exercise_id === id).exercise.name, now, before};
  }).filter((item) => item.before > 0 && item.now > item.before).slice(0, 3);
  $("#finish-best").hidden = !better.length;
  $("#finish-best-list").replaceChildren(...better.map((item) => {
    const line = node("p", null, "best-line");
    line.append(node("strong", item.name + " " + number(item.now) + "kg"), node("span", "최고 무게 · 지난 기록 " + number(item.before) + "kg"));
    return line;
  }));
  const form = $("#finish-form");
  fill(form, {title: titleOf(workout), memo: workout.memo});
  form.elements.drop.checked = true;
  $("#finish-drop-row").hidden = !left || !done.length;
  $("#finish-drop-text").textContent = "체크하지 않은 세트 " + left + "개는 지우기";
  form.elements.save_routine.checked = false;
  $("#finish-save-row").hidden = workout.routine_id != null || !done.length;
  $("#finish-dialog").showModal();
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
  const own = preset ? null : exercise.muscles || [];
  $("#info-sub").textContent = preset ? [preset.name_en, ...preset.aliases].join(" · ") : own.length ? "내 종목" : "내 종목 · 근육을 고르지 않아 근육 그림이 없어요";
  const tracking = [preset?.tracking, exercise.tracking].find((value) => TRACKING[value]) || "weight_reps";
  $("#info-tracking").textContent = "기록 방식 · " + (state.catalog?.tracking?.[tracking] || "중량 × 횟수");
  const tags = $("#info-tags"); tags.replaceChildren();
  for (const tag of preset ? preset.tags : [exercise.body_part, ...own, exercise.category].filter(Boolean)) tags.append(node("span", tag, "tag"));
  $("#info-muscle").replaceChildren(preset ? FitAnatomy.figure(preset.muscles)
    : own.length ? FitAnatomy.figure(own) : node("p", "근육 정보가 없어요. 내 종목 관리에서 근육을 고를 수 있어요.", "empty-state"));
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
// ---- my exercises: a searchable list; tapping one (or "+ 새 종목") opens the editor ------------------------
function renderExercises() {
  const list = $("#exercise-list"), query = squash($("#exercise-query").value);
  const shown = state.exercises.filter((exercise) => !query || squash(exercise.name).includes(query));
  list.replaceChildren(...shown.map((exercise) => {
    const preset = presetOf(exercise);
    const item = button("", () => openExerciseEditor(exercise), "exercise-row");
    const text = node("span", null, "ex-text");
    const muscles = preset?.muscles || exercise.muscles;
    text.append(node("strong", exercise.name), node("span", describe(exercise) + (preset ? " · 기본 종목 연결" : muscles?.length ? "" : " · 근육 없음")));
    item.append(thumb(muscles, exercise.name), text);
    item.insertAdjacentHTML("beforeend", SVG_CHEVRON);
    return item;
  }));
  if (!shown.length) list.append(node("p", query ? "맞는 종목이 없어요." : "등록된 종목이 없어요.", "empty-state"));
}
// The editor: name for every exercise; equipment, recording type, muscles (on the figure) and body part
// for the user's own ones. A preset-linked exercise shows the preset's figure instead.
const editor = {exercise: null, gear: null, tracking: "weight_reps", part: null, partPicked: false, muscles: null};
function editorChips(id, values, current, pick) {
  $(id).replaceChildren(...values.map(([value, label]) => {
    const chip = button(label, () => { pick(value === current ? null : value); }, "chip" + (value === current ? " on" : ""));
    chip.setAttribute("aria-pressed", String(value === current));
    return chip;
  }));
}
function renderEditorChoices() {
  const catalog = state.catalog;
  editorChips("#exercise-gear", catalog.equipment.map((gear) => [gear, gear]), editor.gear, (value) => { editor.gear = value; renderEditorChoices(); });
  editorChips("#exercise-tracking", Object.keys(catalog.tracking).filter((value) => TRACKING[value]).map((value) => [value, TRACKING[value].short]), editor.tracking,
    (value) => { editor.tracking = value || "weight_reps"; renderEditorChoices(); });
  editorChips("#exercise-part", catalog.parts.map((part) => [part, part]), editor.part, (value) => { editor.part = value; editor.partPicked = true; renderEditorChoices(); });
  $("#exercise-part-note").textContent = editor.partPicked ? "" : "· 주 근육에서 자동으로 정해요";
}
function openExerciseEditor(exercise = null, muscles = exercise?.muscles) {
  const preset = presetOf(exercise), form = $("#exercise-form");
  fill(form, {name: exercise?.name || ""});
  Object.assign(editor, {exercise, gear: exercise?.category || null, tracking: exercise?.tracking || "weight_reps",
    part: exercise?.body_part || null, partPicked: Boolean(exercise?.body_part)});
  $("#exercise-form-title").textContent = exercise ? "종목 수정" : "새 종목";
  $("#exercise-own").hidden = Boolean(preset);
  $("#exercise-linked").hidden = $("#exercise-linked-figure").hidden = !preset;
  $("#exercise-delete").hidden = !exercise;
  if (preset) {
    $("#exercise-linked").textContent = "기본 종목 '" + preset.name + "'과 연결돼 있어요. 근육·장비·기록 방식은 기본 종목을 따라요. 이름만 바꿀 수 있어요.";
    $("#exercise-linked-figure").replaceChildren(FitAnatomy.figure(preset.muscles));
  } else {
    editor.muscles = FitAnatomy.picker(muscles || [], {names: state.catalog.muscles, onChange: (picked) => {
      if (!editor.partPicked) { editor.part = FitAnatomy.partOf(picked); renderEditorChoices(); }
    }});
    $("#exercise-muscles").replaceChildren(editor.muscles.root);
    if (!editor.partPicked && muscles?.length) editor.part = FitAnatomy.partOf(muscles);
    renderEditorChoices();
  }
  $("#exercise-editor").showModal();
}
// Exercises from old records that repeat a built-in one, often with the grip in the name ("랫풀다운 페러럴그립").
async function renderCleanup() {
  const items = await api("/exercise-cleanup");
  $("#cleanup").hidden = !items.length;
  const list = $("#cleanup-list"); list.replaceChildren();
  const merge = (item) => api("/exercises/" + item.exercise_id + "/merge", "POST", {preset_id: item.preset_id, variant: item.variant});
  // Errors go in the dialog: the page notice sits behind it.
  const run = (control, action) => mutate(control, () => action().catch((error) => { $("#cleanup-message").textContent = error.message; }));
  const after = async (text) => { await loadExercises(); renderExercises(); await renderCleanup(); $("#cleanup-message").textContent = text; };
  for (const item of items) {
    const row = node("div", null, "cleanup-item");
    const text = node("p");
    text.append(node("strong", item.name), node("span", "→ " + item.preset_name + (item.variant_label ? " · " + item.variant_label : "") + " · 기록 " + item.sets + "세트", "muted"));
    row.append(text, button("합치기", (control) => run(control, async () => {
      const result = await merge(item);
      await after(item.name + "의 " + result.moved + "세트를 " + item.preset_name + "(으)로 옮겼어요.");
    }), "small"));
    list.append(row);
  }
  $("#cleanup-all").onclick = (event) => run(event.currentTarget, async () => {
    if (!confirm(items.length + "개 종목을 기본 종목으로 합칠까요? 기록은 그대로 옮겨지고, 겹치는 종목은 지워져요.")) return;
    let moved = 0;
    for (const item of items) moved += (await merge(item)).moved;
    await after(items.length + "개 종목을 합쳤어요. 옮긴 기록 " + moved + "세트.");
  });
}
// My own exercises with nothing to draw, with muscles suggested from the closest built-in one.
async function renderMuscleFix() {
  const items = await api("/exercise-muscles");
  $("#muscle-fix").hidden = !items.length;
  const list = $("#muscle-fix-list"); list.replaceChildren();
  const save = (item, muscles) => {
    const exercise = state.exercises.find((entry) => entry.id === item.exercise_id);
    return api("/exercises/" + item.exercise_id, "PUT", {name: exercise.name, category: exercise.category, body_part: exercise.body_part || FitAnatomy.partOf(muscles),
      preset_id: null, muscles, tracking: exercise.tracking});
  };
  const run = (control, action) => mutate(control, () => action().catch((error) => { $("#muscle-fix-message").textContent = error.message; }));
  const after = async (text) => { await loadExercises(); renderExercises(); await renderMuscleFix(); $("#muscle-fix-message").textContent = text; };
  for (const item of items) {
    const row = node("div", null, "cleanup-item");
    const text = node("p");
    text.append(node("strong", item.name), node("span", (item.like ? "추천: " + item.muscles.join(", ") + " · 비슷한 종목 " + item.like : "비슷한 기본 종목이 없어요") + " · 기록 " + item.sets + "세트", "muted"));
    row.append(text);
    if (item.like) row.append(button("추천대로", (control) => run(control, async () => {
      await save(item, item.muscles); await after(item.name + "에 근육 정보를 넣었어요.");
    }), "small"));
    row.append(button("고르기", () => openExerciseEditor(state.exercises.find((entry) => entry.id === item.exercise_id), item.muscles), "small"));
    list.append(row);
  }
  const suggested = items.filter((item) => item.like);
  $("#muscle-fix-all").hidden = !suggested.length;
  $("#muscle-fix-all").onclick = (event) => run(event.currentTarget, async () => {
    if (!confirm(suggested.length + "개 종목에 추천 근육을 넣을까요? 나중에 '수정'에서 바꿀 수 있어요.")) return;
    for (const item of suggested) await save(item, item.muscles);
    await after(suggested.length + "개 종목에 근육 정보를 넣었어요.");
  });
}
$("#workout-form").addEventListener("submit", (event) => {
  event.preventDefault(); const form = event.currentTarget;
  submitForm(form, async () => {
    const body = {workout_date: form.elements.workout_date.value, title: form.elements.title.value,
      body_part: textValue(form, "body_part"), memo: textValue(form, "memo"),
      started_at: form.elements.started_at.value ? new Date(form.elements.started_at.value).toISOString() : null,
      ended_at: form.elements.ended_at.value ? new Date(form.elements.ended_at.value).toISOString() : null};
    await api("/workouts" + (state.editWorkout ? "/" + state.editWorkout : ""), state.editWorkout ? "PUT" : "POST", body);
    $("#workout-dialog").close(); notice("운동을 저장했어요."); await showRoute();
  });
});
$("#exercise-form").addEventListener("submit", (event) => {
  event.preventDefault(); const form = event.currentTarget;
  submitForm(form, async () => {
    const current = editor.exercise;
    if (!form.elements.name.value.trim()) throw new Error("종목명을 적어 주세요.");
    const body = current?.preset_id
      ? {name: form.elements.name.value, category: current.category, body_part: current.body_part, preset_id: current.preset_id}
      : {name: form.elements.name.value, category: editor.gear, body_part: editor.part, preset_id: null,
        muscles: editor.muscles.get(), tracking: editor.tracking === "weight_reps" ? null : editor.tracking};
    await api("/exercises" + (current ? "/" + current.id : ""), current ? "PUT" : "POST", body);
    $("#exercise-editor").close();
    await loadExercises(); renderExercises(); renderMuscleFix().catch(() => {});
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
  $("#menu-dialog").close();
  try { await loadExercises(); $("#exercise-query").value = ""; renderExercises(); $("#cleanup-message").textContent = ""; $("#muscle-fix-message").textContent = ""; $("#exercise-dialog").showModal();
    renderCleanup().catch((error) => notice(error.message, true)); renderMuscleFix().catch((error) => notice(error.message, true)); }
  catch (error) { notice(error.message, true); }
});
$("#exercise-new").addEventListener("click", () => openExerciseEditor());
$("#exercise-query").addEventListener("input", renderExercises);
$("#exercise-delete").addEventListener("click", () => submitForm($("#exercise-form"), async () => {
  const exercise = editor.exercise;
  if (!confirm(exercise.name + " 종목을 삭제할까요?")) return;
  await api("/exercises/" + exercise.id, "DELETE");
  $("#exercise-editor").close();
  await loadExercises(); renderExercises(); renderMuscleFix().catch(() => {}); renderCleanup().catch(() => {});
}));
$("#browse-exercises").addEventListener("click", () => { $("#menu-dialog").close(); openPicker(); });
$("#menu-button").addEventListener("click", () => $("#menu-dialog").showModal());
$("#manage-routines").addEventListener("click", () => openRoutines());
$("#routine-new").addEventListener("click", () => openRoutineEditor());
$("#routine-add").addEventListener("click", () => openPicker(null, "routine"));
$("#routine-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const form = event.currentTarget, edit = state.routineEdit;
  submitForm(form, async () => {
    if (!edit.items.length) throw new Error("종목을 하나 이상 넣어 주세요.");
    const saved = await api("/routines" + (edit.id ? "/" + edit.id : ""), edit.id ? "PUT" : "POST", {name: form.elements.name.value.trim(), items: edit.items});
    const index = state.routines.findIndex((item) => item.id === saved.id);
    if (index >= 0) state.routines[index] = saved; else state.routines.push(saved);
    $("#routine-editor").close();
    renderRoutines(); renderCurrent();
  });
});
$("#routine-delete").addEventListener("click", () => submitForm($("#routine-form"), async () => {
  const edit = state.routineEdit;
  if (!confirm("이 루틴을 삭제할까요? 지난 운동 기록은 그대로 남아요.")) return;
  await api("/routines/" + edit.id, "DELETE");
  state.routines = state.routines.filter((item) => item.id !== edit.id);
  $("#routine-editor").close();
  renderRoutines(); renderCurrent();
}));
$("#tab-today").addEventListener("click", () => showView("today"));
$("#tab-history").addEventListener("click", () => showView("history"));
$("#cal-expand").addEventListener("click", () => { state.calendar.expanded = !state.calendar.expanded; renderCalendar(); });
$("#rest-more").addEventListener("click", () => { state.rest.until += 30000; tickRest(); });
$("#rest-skip").addEventListener("click", stopRest);
$("#finish-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const form = event.currentTarget, workout = state.finish;
  submitForm(form, async () => {
    // Pending set saves land first, so a set ticked just before finishing is not dropped.
    await (queues.get(workout.id) || Promise.resolve());
    if (form.elements.drop.checked && !$("#finish-drop-row").hidden) {
      for (const set of workout.sets.filter((item) => !item.completed)) await api("/workouts/" + workout.id + "/sets/" + set.id, "DELETE");
      workout.sets = workout.sets.filter((item) => item.completed);
    }
    const body = {workout_date: workout.workout_date, title: form.elements.title.value.trim(), body_part: workout.body_part,
      memo: textValue(form, "memo"), started_at: workout.started_at, ended_at: new Date().toISOString()};
    if (form.elements.save_routine.checked && !$("#finish-save-row").hidden) {
      const routine = await api("/routines", "POST", routineFrom(workout, body.title));
      state.routines.push(routine);
      body.routine_id = routine.id;
    }
    await api("/workouts/" + workout.id, "PUT", body);
    Object.assign(workout, body);
    $("#finish-dialog").close();
    stopRest(); state.focus = null;
    notice("운동을 저장했어요. 수고했어요!");
    renderCurrent(); renderCalendar();
  });
});
$("#cal-prev").addEventListener("click", () => moveMonth(-1));
$("#cal-next").addEventListener("click", () => moveMonth(1));
window.addEventListener("hashchange", showRoute);
try { showView(sessionStorage.getItem("workouts:view") === "history" ? "history" : "today"); } catch { showView("today"); }
window.fitlogOnSync = showRoute;
FitAnatomy.load().catch(() => {});
showRoute();
