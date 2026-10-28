"use strict";
// Workouts: this week's summary, today's session with inline set tables, a month calendar of past sessions,
// the preset picker (search + body part / equipment tags) and an exercise sheet with the muscle figure.
const $ = (selector) => document.querySelector(selector);
const state = {variants: {}, workouts: [], exercises: [], presets: [], catalog: null, current: null, route: 0,
  editWorkout: null, editExercise: null, picker: {workout: null, part: "전체", gear: "전체", picked: new Map()},
  calendar: {month: null, day: null, months: new Map(), stale: false}};
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
  window.fitlogCache.set("exercises", exercises);
}
// The catalog is a static file linked by content hash (preloaded by the page), so after the first visit
// it comes from the phone's cache instead of a server round trip.
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
  return [preset?.body_part || exercise.body_part, preset?.equipment || exercise.category].filter(Boolean).join(" · ") || "부위·장비 미지정";
}
// ---- set fields by tracking type -----------------------------------------------------------------
// Each preset says how it is recorded (app/static/data/exercise_presets.json "tracking"); custom exercises use weight × reps.
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
const TRACKING = {
  weight_reps: {fields: ["weight", "reps"]},
  reps: {fields: ["weight", "reps"], weightLabel: "+kg"},
  hold: {fields: ["seconds"]},
  weight_time: {fields: ["weight", "seconds"]},
  treadmill: {fields: ["time", "speed", "incline"], cardio: true},
  distance: {fields: ["distance", "time"], cardio: true},
  run: {fields: ["distance", "time"], cardio: true, details: true},
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
    notice(error.message + " 서버의 기록으로 되돌렸어요.", true);
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
    instant(workout, () => Object.assign(set, changes), () => api("/workouts/" + workout.id + "/sets/" + set.id, "PUT", setPayload(set)));
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
  if (running) tools.append(button("운동 끝내기", () => {
    notice("운동을 마쳤습니다. 수고했어요!");
    instant(workout, () => { workout.ended_at = new Date().toISOString(); },
      () => api("/workouts/" + workout.id, "PUT", {workout_date: workout.workout_date, title: workout.title, body_part: workout.body_part,
        memo: workout.memo, started_at: workout.started_at, ended_at: workout.ended_at}));
  }));
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
  const names = [...new Set(workout.sets.map((set) => set.exercise.name))];
  // Strength work counts sets; a run or other cardio shows its distance, time and pace instead.
  const cardio = workout.sets.filter((set) => TRACKING[trackingOf(userExercise(set.exercise))].cardio);
  const strength = workout.sets.length - cardio.length;
  const amount = [strength && strength + "세트", cardioSummary(cardio)].filter(Boolean).join(" · ");
  const text = node("span", null, "past-text");
  text.append(node("strong", workout.title), node("span", (names.slice(0, 3).join(" · ") || "세트 없음") + (names.length > 3 ? " 외" : "") + (amount ? " · " + amount : "")));
  link.append(text);
  link.insertAdjacentHTML("beforeend", SVG_CHEVRON);
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
  const copies = [...source.sets].sort((a, b) => a.id - b.id).map((set) => {
    const next = (used.get(set.exercise_id) || 0) + 1; used.set(set.exercise_id, next);
    // Plans copy over; outcomes (calories, heart rate) do not.
    return setPayload(set, {set_number: next, completed: false, memo: null, calories: null, heart_rate: null,
      max_heart_rate: null, cadence: null, max_cadence: null, steps: null, elevation_gain_m: null, best_pace_seconds: null});
  });
  Object.assign(today, await api("/workouts/" + today.id + "/sets/batch", "POST", copies));
  notice("‘" + source.title + "’ 구성을 오늘 운동에 불러왔어요.");
  if (location.hash) location.hash = ""; else { renderWeek(); renderCurrent(); renderCalendar(); }
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
function showList(items) {
  state.workouts = items;
  renderWeek();
  renderToday(state.workouts.find((item) => item.workout_date === localDate()));
  renderCalendar();
}

// ---- calendar -----------------------------------------------------------------------------------
// A month grid with a dot on each day with a workout; tapping a day lists that day's sessions below.
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
  // Until a day is picked, show the latest session before today (today's is the card above).
  if (!calendar.day || monthOf(calendar.day) !== month) {
    calendar.day = items.find((item) => item.workout_date < today)?.workout_date || (month === monthOf(today) ? today : month + "-01");
  }
  const [year, index] = month.split("-").map(Number);
  $("#cal-title").textContent = year + "년 " + index + "월";
  $("#cal-next").disabled = month >= monthOf(today);
  const counts = items.reduce((map, item) => map.set(item.workout_date, (map.get(item.workout_date) || 0) + 1), new Map());
  const first = new Date(year, index - 1, 1), length = new Date(year, index, 0).getDate();
  const cells = Array.from({length: (first.getDay() + 6) % 7}, () => node("span", null, "cal-blank"));
  for (let date = 1; date <= length; date++) {
    const day = month + "-" + String(date).padStart(2, "0"), count = counts.get(day) || 0;
    const cell = button(String(date), () => { calendar.day = day; renderCalendar(); },
      "cal-date" + (count ? " on" : "") + (day === today ? " today" : "") + (day > today ? " future" : ""));
    cell.setAttribute("aria-pressed", String(day === calendar.day));
    cell.setAttribute("aria-label", index + "월 " + date + "일" + (day === today ? " 오늘" : "") + (count ? ", 운동 " + count + "회" : ""));
    cells.push(cell);
  }
  $("#cal-grid").replaceChildren(...cells);
  const picked = items.filter((item) => item.workout_date === calendar.day);
  const date = new Date(calendar.day + "T12:00:00");
  const panel = $("#cal-day");
  const head = node("p", null, "cal-day-head");
  head.append(node("strong", (date.getMonth() + 1) + "월 " + date.getDate() + "일 " + WEEKDAYS[date.getDay()] + "요일"),
    node("span", picked.length ? "운동 " + picked.length + "회" : ""));
  panel.replaceChildren(head);
  if (picked.length) { const list = node("div", null, "past-list"); list.append(...picked.map(pastItem)); panel.append(list); }
  else panel.append(node("p", calendar.day > today ? "아직 오지 않은 날이에요." : state.calendar.months.has(month) ? "이 날은 운동 기록이 없어요." : "기록을 불러오는 중…", "empty-state"));
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
  const picker = state.picker, browse = !picker.workout; // browse: look exercises up without adding them
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
}
async function openPicker(workout = null) {
  try {
    await Promise.all([loadCatalog(), loadExercises()]);
    Object.assign(state.picker, {workout, picked: new Map()});
    $("#picker-title").textContent = workout ? "운동 추가" : "운동 종목";
    $("#picker-foot").hidden = !workout;
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
  const additions = [];
  // New exercises are created side by side; then one request adds all the sets.
  const exercises = await Promise.all(items.map(ensureExercise));
  for (const exercise of exercises) {
    const sets = workout.sets.filter((set) => set.exercise_id === exercise.id);
    additions.push({exercise_id: exercise.id, set_number: Math.max(0, ...sets.map((set) => set.set_number)) + 1,
      weight: null, reps: null, completed: false, memo: null});
  }
  applyWorkout(workout, await api("/workouts/" + workout.id + "/sets/batch", "POST", additions));
  $("#picker-dialog").close();
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
$("#browse-exercises").addEventListener("click", () => openPicker());
$("#cal-prev").addEventListener("click", () => moveMonth(-1));
$("#cal-next").addEventListener("click", () => moveMonth(1));
window.addEventListener("hashchange", showRoute);
window.fitlogOnSync = showRoute;
FitAnatomy.load().catch(() => {});
showRoute();
