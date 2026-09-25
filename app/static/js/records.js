"use strict";
const $ = (selector) => document.querySelector(selector);
const mealTypes = {breakfast: "아침", lunch: "점심", dinner: "저녁", snack: "간식", other: "기타"};
const sleepTypes = {main: "주 수면", nap: "낮잠"};
const configs = {
  "/meals": {
    title: "식단 기록", description: "먹은 것부터 간단히. 영양 정보는 아는 만큼만 남겨요.",
    hint: "영양 정보가 없으면 비워두세요. 0은 실제 0으로 저장합니다. 사진 첨부는 추후 지원합니다.",
    dateHint: "식사 시각 기준 · 현재 기기 시간대", timeField: "eaten_at",
    fields: [
      {name:"eaten_at", label:"식사 시각", type:"datetime-local", required:true},
      {name:"meal_type", label:"식사 구분", type:"select", options:mealTypes, required:true},
      {name:"name", label:"음식·식사 이름", type:"text", required:true, maxLength:200, placeholder:"예: 닭가슴살 샐러드"},
      {name:"calories", label:"열량 (kcal)", type:"number", min:0, max:100000},
      {name:"protein", label:"단백질 (g)", type:"number", min:0, max:100000},
      {name:"carbohydrates", label:"탄수화물 (g)", type:"number", min:0, max:100000},
      {name:"fat", label:"지방 (g)", type:"number", min:0, max:100000}
    ]
  },
  "/body-metrics": {
    title:"체중·신체 기록", description:"작은 변화를 기록해 나의 흐름을 살펴보세요.",
    hint:"체중·체지방률·골격근량 중 하나 이상 입력하세요. 시각은 현재 기기 시간대입니다.",
    dateHint:"측정 시각 기준 · 현재 기기 시간대", timeField:"measured_at",
    fields:[
      {name:"measured_at", label:"측정 시각", type:"datetime-local", required:true},
      {name:"weight", label:"체중 (kg)", type:"number", min:0.01, max:1000},
      {name:"body_fat", label:"체지방률 (%)", type:"number", min:0, max:100},
      {name:"skeletal_muscle", label:"골격근량 (kg)", type:"number", min:0, max:1000}
    ]
  },
  "/sleep": {
    title:"수면 기록", description:"밤의 휴식부터 짧은 낮잠까지, 나의 회복을 기록해요.",
    hint:"날짜를 포함해 시작·종료를 입력하세요. 분할 수면은 각각 기록하며 시간은 겹칠 수 없습니다.",
    dateHint:"수면 종료 시각 기준 · 날짜를 넘긴 수면은 종료한 날에 표시합니다.", timeField:"sleep_end",
    fields:[
      {name:"sleep_start", label:"잠든 시각", type:"datetime-local", required:true},
      {name:"sleep_end", label:"일어난 시각", type:"datetime-local", required:true},
      {name:"sleep_type", label:"수면 구분", type:"select", options:sleepTypes, required:true}
    ]
  }
};
const config = configs[location.pathname];
const state = {items:[], editId:null, offset:0, request:0, saving:false};
const pageSize = 20;
function element(tag, text, className) {
  const item = document.createElement(tag);
  if (text != null) item.textContent = text;
  if (className) item.className = className;
  return item;
}
function notice(text, error = false) { $("#notice").textContent = text; $("#notice").className = error ? "error" : ""; }
function localInput(value = new Date()) {
  const date = value instanceof Date ? value : new Date(value);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0,16);
}
function formatDate(value) { return new Date(value).toLocaleString("ko-KR", {year:"numeric",month:"long",day:"numeric",hour:"2-digit",minute:"2-digit"}); }
function duration(minutes) { return Math.floor(minutes / 60) + "시간 " + (minutes % 60) + "분"; }
function display(value, unit) { return value == null ? "미입력" : new Intl.NumberFormat("ko-KR", {maximumFractionDigits:2}).format(value) + " " + unit; }
async function api(path, method = "GET", body) {
  let response;
  try {
    response = await fetch("/api" + path, {
      method, cache:"no-store", signal:AbortSignal.timeout(15000),
      headers:body ? {"Content-Type":"application/json"} : {},
      body:body ? JSON.stringify(body) : undefined
    });
  } catch {
    throw new Error("서버에 연결하지 못했습니다. 저장 중이었다면 새로고침으로 반영 여부를 확인한 뒤 다시 시도하세요.");
  }
  const data = await response.json();
  if (!response.ok) {
    const labels = Object.fromEntries(config.fields.map((field) => [field.name, field.label]));
    const detail = data.detail;
    throw new Error(Array.isArray(detail) ? detail.map((item) => {
      const key = item.loc.at(-1);
      return (labels[key] ? labels[key] + ": " : "") + item.msg;
    }).join("\n") : detail || "요청에 실패했습니다.");
  }
  return data;
}
function createFields() {
  for (const field of config.fields) {
    const label = element("label", field.label + (field.required ? " *" : ""));
    const input = element(field.type === "select" ? "select" : "input");
    input.name = field.name;
    if (field.type === "select") {
      for (const [value, title] of Object.entries(field.options)) {
        const option = element("option", title); option.value = value; input.append(option);
      }
    } else {
      input.type = field.type;
      if (field.type === "number") { input.step = "any"; input.inputMode = "decimal"; }
      for (const attribute of ["min","max","maxLength","placeholder"]) if (field[attribute] != null) input[attribute] = field[attribute];
    }
    input.required = Boolean(field.required);
    label.append(input); $("#form-fields").append(label);
  }
}
function openForm(record = null) {
  state.editId = record?.id ?? null;
  const form = $("#record-form"); form.reset();
  form.querySelector(".form-error").textContent = "";
  $("#form-title").textContent = config.title + (record ? " 수정" : " 추가");
  for (const field of config.fields) {
    const input = form.elements.namedItem(field.name);
    if (record) input.value = field.type === "datetime-local" ? localInput(record[field.name]) : record[field.name] ?? "";
    else if (field.type === "datetime-local") input.value = field.name === "sleep_start" ? "" : localInput();
  }
  if (!record && form.elements.meal_type) form.elements.meal_type.value = "other";
  form.elements.memo.value = record?.memo ?? "";
  updateDuration(); $("#record-dialog").showModal();
}
function updateDuration() {
  if (location.pathname !== "/sleep") return;
  const form = $("#record-form");
  const start = form.elements.sleep_start.value, end = form.elements.sleep_end.value;
  const minutes = Math.floor((new Date(end) - new Date(start)) / 60000);
  $("#sleep-duration").textContent = start && end ? (minutes >= 1 ? "수면 시간 · " + duration(minutes) : "종료는 시작보다 최소 1분 이후여야 합니다.") : "시작·종료 시각을 입력하면 수면 시간이 계산됩니다.";
}
function metric(root, label, value) {
  const item = element("p", label); item.append(element("strong", value)); root.append(item);
}
function recordCard(record) {
  const card = element("article", null, "card record-card");
  card.append(element("p", formatDate(record[config.timeField]), "date"));
  const heading = element("div", null, "record-heading");
  const values = element("div", null, "record-values");
  if (location.pathname === "/meals") {
    heading.append(element("h2", record.name), element("span", mealTypes[record.meal_type] || record.meal_type, "record-kind"));
    metric(values, "열량", display(record.calories,"kcal"));
    metric(values, "단백질", display(record.protein,"g"));
    metric(values, "탄수화물", display(record.carbohydrates,"g"));
    metric(values, "지방", display(record.fat,"g"));
  } else if (location.pathname === "/body-metrics") {
    heading.append(element("h2", "신체 측정"));
    metric(values,"체중",display(record.weight,"kg"));
    metric(values,"체지방률",display(record.body_fat,"%"));
    metric(values,"골격근량",display(record.skeletal_muscle,"kg"));
  } else {
    heading.append(element("h2", duration(record.duration_minutes)), element("span",sleepTypes[record.sleep_type] || record.sleep_type,"record-kind"));
    values.className = "sleep-times";
    values.append(element("p", "잠든 시각 · " + formatDate(record.sleep_start)), element("p", "일어난 시각 · " + formatDate(record.sleep_end)));
  }
  card.append(heading, values);
  if (record.memo) card.append(element("p",record.memo,"memo"));
  const actions = element("div", null, "row-actions");
  const edit = element("button","수정"); edit.type = "button"; edit.addEventListener("click", () => openForm(record));
  const remove = element("button","삭제","danger"); remove.type = "button";
  remove.addEventListener("click", async () => {
    if (!confirm("이 기록을 삭제할까요? 삭제 후 되돌릴 수 없습니다.")) return;
    remove.disabled = true; edit.disabled = true;
    try { await api(location.pathname + "/" + record.id, "DELETE"); notice("기록을 삭제했습니다."); await loadRecords(); }
    catch (error) { notice(error.message,true); }
    finally { remove.disabled = false; edit.disabled = false; }
  });
  actions.append(edit, remove); card.append(actions); return card;
}
async function loadRecords(append = false) {
  const request = ++state.request;
  const params = new URLSearchParams({limit:pageSize, offset:append ? state.offset : 0});
  const form = $("#filter-form");
  const from = form.elements.date_from.value, to = form.elements.date_to.value;
  try {
    if (from && to && from > to) throw new Error("시작 날짜는 종료 날짜 이전이어야 합니다.");
    if (from) params.set("from_at", new Date(from + "T00:00:00").toISOString());
    if (to) { const end = new Date(to + "T00:00:00"); end.setDate(end.getDate() + 1); params.set("to_at", end.toISOString()); }
    const records = await api(location.pathname + "?" + params);
    if (request !== state.request) return;
    state.items = append ? [...state.items,...records] : records;
    state.offset = state.items.length;
    $("#record-list").replaceChildren(...state.items.map(recordCard));
    if (!state.items.length) $("#record-list").append(element("p", "기록이 없습니다. ‘+ 기록 추가’로 첫 기록을 남겨보세요.", "empty-state"));
    $("#load-more").hidden = records.length < pageSize;
  } catch (error) {
    if (request !== state.request) return;
    notice(error.message,true);
    if (!append) { $("#record-list").replaceChildren(element("p","기록을 불러오지 못했습니다. 조건과 연결을 확인하고 새로고침해 주세요.","empty-state")); $("#load-more").hidden = true; }
  }
}
$("#record-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.saving) return;
  state.saving = true;
  const form = event.currentTarget, errorBox = form.querySelector(".form-error");
  errorBox.textContent = "";
  const controls = [...$("#record-dialog").querySelectorAll("button")];
  controls.forEach((control) => control.disabled = true);
  try {
    const body = {memo:form.elements.memo.value.trim() || null};
    for (const field of config.fields) {
      const value = form.elements.namedItem(field.name).value;
      body[field.name] = field.type === "datetime-local" ? new Date(value).toISOString() : field.type === "number" ? (value === "" ? null : Number(value)) : value.trim();
    }
    if (location.pathname === "/body-metrics" && [body.weight,body.body_fat,body.skeletal_muscle].every((value) => value == null)) throw new Error("체중·체지방률·골격근량 중 하나 이상을 입력해 주세요.");
    await api(location.pathname + (state.editId ? "/" + state.editId : ""), state.editId ? "PUT" : "POST", body);
    $("#record-dialog").close(); notice("기록을 저장했습니다."); await loadRecords();
  } catch (error) { errorBox.textContent = error.message; }
  finally { state.saving = false; controls.forEach((control) => control.disabled = false); }
});
document.title = "FitLog · " + config.title;
$("#page-title").textContent = config.title;
$("#page-description").textContent = config.description;
$("#filter-hint").textContent = config.dateHint;
$("#form-hint").textContent = config.hint;
document.querySelector('.record-tabs a[href="' + location.pathname + '"]').setAttribute("aria-current","page");
if (location.pathname === "/meals") { $("#meal-nav").classList.add("active"); $("#meal-nav").setAttribute("aria-current","page"); }
createFields();
$("#record-form").addEventListener("input", updateDuration);
$("#new-record").addEventListener("click", () => openForm());
$("#cancel-record").addEventListener("click", () => $("#record-dialog").close());
$("#record-dialog").addEventListener("cancel", (event) => { if (state.saving) event.preventDefault(); });
$("#refresh").addEventListener("click", () => { notice(""); loadRecords(); });
$("#filter-form").addEventListener("submit", (event) => { event.preventDefault(); notice(""); loadRecords(); });
$("#clear-filter").addEventListener("click", () => { $("#filter-form").reset(); notice(""); loadRecords(); });
$("#load-more").addEventListener("click", async (event) => { event.currentTarget.disabled = true; const control = event.currentTarget; try { await loadRecords(true); } finally { control.disabled = false; } });
loadRecords();
