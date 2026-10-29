"use strict";
// Quick record sheets: 체중, 수면 and 식사 in a few taps, filled from the last records. Used by the ＋ sheet on
// the home page and by the weight and sleep pages (to add, edit or delete one record).
// window.FitQuick.open(kind, {record, onSaved}) · window.FitQuick.hints() for the ＋ sheet's tiles.
(() => {
  const MEAL_TYPES = {breakfast: "아침", lunch: "점심", dinner: "저녁", snack: "간식", other: "기타"};
  const TITLES = {weight: "체중", sleep: "수면", meal: "식사"};
  const PATHS = {weight: "/body-metrics", sleep: "/sleep", meal: "/meals"};
  const LABELS = {weight: "체중", body_fat: "체지방률", skeletal_muscle: "골격근량", sleep_start: "잠든 시각", sleep_end: "일어난 시각",
    name: "음식", calories: "열량", protein: "단백질", carbohydrates: "탄수화물", fat: "지방", eaten_at: "식사 시각", measured_at: "측정 시각"};
  const number = (value) => new Intl.NumberFormat("ko-KR", {maximumFractionDigits: 1}).format(value);
  const pad = (value) => String(value).padStart(2, "0");
  const localInput = (date) => new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  const dateInput = (date) => localInput(date).slice(0, 10);
  const clockOf = (date) => pad(date.getHours()) + ":" + pad(date.getMinutes());
  const minutesText = (minutes) => Math.floor(minutes / 60) + "시간 " + (minutes % 60) + "분";

  async function api(path, method = "GET", body) {
    let response;
    try {
      response = await fetch("/api" + path, {method, cache: "no-store", signal: AbortSignal.timeout(15000),
        headers: body ? {"Content-Type": "application/json"} : {}, body: body ? JSON.stringify(body) : undefined});
    } catch { throw new Error("연결이 안 돼요. 인터넷 연결을 확인하고 다시 저장해 주세요."); }
    const data = await response.json();
    if (!response.ok) {
      const detail = data.detail;
      throw new Error(Array.isArray(detail) ? detail.map((item) => (LABELS[item.loc?.at(-1)] ? LABELS[item.loc.at(-1)] + ": " : "") + item.msg.replace(/^Value error, /, "")).join("\n")
        : detail || "저장하지 못했어요.");
    }
    return data;
  }

  // ---- one sheet, rebuilt for each kind -------------------------------------------------------------
  let dialog = null;
  function sheet() {
    if (dialog) return dialog;
    dialog = document.createElement("dialog");
    dialog.className = "quick-sheet";
    dialog.setAttribute("aria-labelledby", "quick-title");
    dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });
    document.body.append(dialog);
    return dialog;
  }
  function toast(text) {
    const box = document.createElement("p");
    box.className = "quick-toast"; box.setAttribute("role", "status"); box.textContent = text;
    document.body.append(box);
    setTimeout(() => box.remove(), 2400);
  }
  const ICON_CLOSE = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"></path></svg>';
  const ICON_CAMERA = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 8h3l2-3h6l2 3h3v11H4z"></path><circle cx="12" cy="13" r="3.5"></circle></svg>';
  function frame(kind, record, inner) {
    const box = sheet();
    box.innerHTML = '<form class="quick-form" novalidate><div class="quick-grip"></div><div class="quick-head"><h2 id="quick-title"></h2><div class="quick-tools"></div>'
      + '<button type="button" class="quick-close" aria-label="닫기">' + ICON_CLOSE + '</button></div>' + inner
      + '<p class="form-error" role="alert"></p><div class="quick-actions">'
      + (record ? '<button type="button" class="quick-delete">삭제</button>' : "") + '<button type="submit" class="quick-save">저장</button></div></form>';
    box.querySelector("h2").textContent = TITLES[kind] + (record ? " 고치기" : "");
    box.querySelector(".quick-close").addEventListener("click", () => box.close());
    return box.querySelector("form");
  }
  // Save (or delete) with the buttons held, the error in the sheet, then close and tell the page.
  function wire(form, kind, record, body, onSaved, done) {
    const run = async (action) => {
      const buttons = [...form.querySelectorAll("button")];
      buttons.forEach((button) => button.disabled = true);
      form.querySelector(".form-error").textContent = "";
      try { await action(); dialog.close(); onSaved?.(); }
      catch (error) { form.querySelector(".form-error").textContent = error.message; }
      finally { buttons.forEach((button) => button.disabled = false); }
    };
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      run(async () => {
        const payload = body();
        await api(PATHS[kind] + (record ? "/" + record.id : ""), record ? "PUT" : "POST", payload);
        toast(done(payload));
      });
    });
    form.querySelector(".quick-delete")?.addEventListener("click", () => {
      if (!confirm("이 기록을 지울까요? 지운 기록은 되돌릴 수 없어요.")) return;
      run(async () => { await api(PATHS[kind] + "/" + record.id, "DELETE"); toast("기록을 지웠어요"); });
    });
  }
  const value = (form, name) => { const text = form.elements[name].value.trim(); return text === "" ? null : Number(text); };

  // ---- 체중 -------------------------------------------------------------------------------------------
  async function weight(record, onSaved) {
    // The measurement before this one (an edit compares with the one before it, not the latest).
    const before = record ? "&to_at=" + encodeURIComponent(record.measured_at) : "";
    const recent = await api("/body-metrics?limit=5" + before).catch(() => []);
    const last = recent.find((item) => item.id !== record?.id && item.weight != null);
    const form = frame("weight", record, '<label class="quick-when"><span class="visually-hidden">측정 시각</span><input type="datetime-local" name="measured_at" required></label>'
      + '<div class="quick-weight"><button type="button" data-step="-0.1" aria-label="0.1kg 줄이기">−</button>'
      + '<label><span class="visually-hidden">체중 kg</span><input type="number" name="weight" step="0.1" min="1" max="1000" inputmode="decimal" class="num"></label><span class="quick-unit">kg</span>'
      + '<button type="button" data-step="0.1" aria-label="0.1kg 늘리기">+</button></div><p class="quick-note" data-note></p>'
      + '<details class="quick-more"><summary>+ 체지방률 · 골격근량도 적기</summary><div class="quick-pair">'
      + '<label>체지방률 %<input type="number" name="body_fat" step="0.1" min="0" max="100" inputmode="decimal"></label>'
      + '<label>골격근량 kg<input type="number" name="skeletal_muscle" step="0.1" min="0" max="1000" inputmode="decimal"></label></div></details>');
    const input = form.elements.weight;
    form.querySelector(".quick-tools").append(form.querySelector(".quick-when"));
    form.elements.measured_at.value = localInput(record ? new Date(record.measured_at) : new Date());
    input.value = record ? record.weight ?? "" : last?.weight ?? "";
    for (const name of ["body_fat", "skeletal_muscle"]) form.elements[name].value = record?.[name] ?? "";
    if (record?.body_fat != null || record?.skeletal_muscle != null) form.querySelector(".quick-more").open = true;
    const note = () => {
      const now = value(form, "weight");
      const diff = last && now != null ? Math.round((now - last.weight) * 10) / 10 : null;
      form.querySelector("[data-note]").textContent = diff == null ? (last ? "" : "처음 기록이에요") : diff === 0 ? "지난번과 같아요"
        : "지난번보다 " + number(Math.abs(diff)) + "kg " + (diff < 0 ? "줄었어요" : "늘었어요");
    };
    form.querySelectorAll("[data-step]").forEach((button) => button.addEventListener("click", () => {
      const now = value(form, "weight") ?? last?.weight ?? 60;
      input.value = (Math.round((now + Number(button.dataset.step)) * 10) / 10).toFixed(1);
      note();
    }));
    input.addEventListener("input", note);
    note();
    wire(form, "weight", record, () => ({measured_at: new Date(form.elements.measured_at.value).toISOString(), weight: value(form, "weight"),
      body_fat: value(form, "body_fat"), skeletal_muscle: value(form, "skeletal_muscle"), memo: record?.memo ?? null}),
      onSaved, (payload) => payload.weight != null ? "체중 " + number(payload.weight) + "kg을 기록했어요" : "체성분을 기록했어요");
    return form;
  }

  // ---- 수면 -------------------------------------------------------------------------------------------
  // Usual bed and wake times from the last week's main sleeps (minutes after noon, so midnight averages well).
  function usual(records) {
    const mains = records.filter((item) => item.sleep_type === "main").slice(0, 7);
    if (!mains.length) return {start: "23:30", end: "07:00"};
    const afterNoon = (value) => { const date = new Date(value); return ((date.getHours() * 60 + date.getMinutes()) - 720 + 1440) % 1440; };
    const round = (minutes) => { const total = (Math.round(minutes / 10) * 10 + 720) % 1440; return pad(Math.floor(total / 60)) + ":" + pad(total % 60); };
    const mean = (key) => mains.reduce((sum, item) => sum + afterNoon(item[key]), 0) / mains.length;
    return {start: round(mean("sleep_start")), end: round(mean("sleep_end"))};
  }
  async function sleep(record, onSaved) {
    const recent = record ? [] : await api("/sleep?limit=14").catch(() => []);
    const form = frame("sleep", record, '<div class="quick-duration"><b class="num" data-length>—</b></div>'
      + '<div class="quick-time"><label><span>잠든 시각</span><input type="time" name="start" required></label>'
      + '<button type="button" data-shift="start:-10">−10분</button><button type="button" data-shift="start:10">+10분</button></div>'
      + '<div class="quick-time"><label><span>일어난 시각</span><input type="time" name="end" required></label>'
      + '<button type="button" data-shift="end:-10">−10분</button><button type="button" data-shift="end:10">+10분</button></div>'
      + '<label class="quick-day">일어난 날<input type="date" name="day" required></label>');
    const kinds = document.createElement("div");
    kinds.className = "quick-segment"; kinds.setAttribute("role", "group"); kinds.setAttribute("aria-label", "수면 종류");
    kinds.innerHTML = '<button type="button" data-kind="main">밤잠</button><button type="button" data-kind="nap">낮잠</button>';
    form.querySelector(".quick-tools").append(kinds);
    let kind = record?.sleep_type || "main";
    const usualTimes = usual(recent);
    const end = record ? new Date(record.sleep_end) : new Date();
    form.elements.day.value = dateInput(end);
    form.elements.start.value = record ? clockOf(new Date(record.sleep_start)) : usualTimes.start;
    form.elements.end.value = record ? clockOf(end) : usualTimes.end;
    // Start belongs to the wake-up day, or the day before when it is later on the clock (went to bed before midnight).
    const times = () => {
      const day = form.elements.day.value, startText = form.elements.start.value, endText = form.elements.end.value;
      if (!day || !startText || !endText) return null;
      const stop = new Date(day + "T" + endText), begin = new Date(day + "T" + startText);
      if (begin >= stop) begin.setDate(begin.getDate() - 1);
      return {begin, stop};
    };
    const show = () => {
      kinds.querySelectorAll("button").forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.kind === kind)));
      const span = times();
      form.querySelector("[data-length]").textContent = span ? minutesText(Math.round((span.stop - span.begin) / 60000)) : "—";
    };
    kinds.addEventListener("click", (event) => {
      const button = event.target.closest("[data-kind]");
      if (!button) return;
      kind = button.dataset.kind;
      if (!record && kind === "nap") { form.elements.start.value = "13:00"; form.elements.end.value = "13:30"; form.elements.day.value = dateInput(new Date()); }
      if (!record && kind === "main") { form.elements.start.value = usualTimes.start; form.elements.end.value = usualTimes.end; }
      show();
    });
    form.querySelectorAll("[data-shift]").forEach((button) => button.addEventListener("click", () => {
      const [name, by] = button.dataset.shift.split(":");
      const [hours, minutes] = (form.elements[name].value || "00:00").split(":").map(Number);
      const total = ((hours * 60 + minutes + Number(by)) % 1440 + 1440) % 1440;
      form.elements[name].value = pad(Math.floor(total / 60)) + ":" + pad(total % 60);
      show();
    }));
    for (const name of ["start", "end", "day"]) form.elements[name].addEventListener("input", show);
    show();
    wire(form, "sleep", record, () => {
      const span = times();
      if (!span) throw new Error("잠든 시각과 일어난 시각을 적어 주세요.");
      return {sleep_start: span.begin.toISOString(), sleep_end: span.stop.toISOString(), sleep_type: kind, memo: record?.memo ?? null};
    }, onSaved, (payload) => minutesText(Math.round((new Date(payload.sleep_end) - new Date(payload.sleep_start)) / 60000)) + " 잔 것을 기록했어요");
    return form;
  }

  // ---- 식사 -------------------------------------------------------------------------------------------
  function mealTypeAt(date) {
    const minutes = date.getHours() * 60 + date.getMinutes();
    return minutes < 630 ? "breakfast" : minutes < 900 ? "lunch" : minutes < 1020 ? "snack" : minutes < 1260 ? "dinner" : "snack";
  }
  // The foods eaten most often lately, each with its latest numbers.
  function favourites(meals) {
    const byName = new Map();
    for (const meal of meals) {
      const key = meal.name.trim();
      const entry = byName.get(key) || {meal, count: 0};
      entry.count++;
      byName.set(key, entry);
    }
    return [...byName.values()].filter((entry) => entry.count > 1 || byName.size <= 6).sort((a, b) => b.count - a.count).slice(0, 6).map((entry) => entry.meal);
  }
  async function meal(record, onSaved) {
    const recent = record ? [] : await api("/meals?limit=100").catch(() => []);
    const form = frame("meal", record, '<div class="quick-food"><label class="quick-name"><span class="visually-hidden">음식 이름</span><input name="name" maxlength="200" placeholder="무엇을 먹었나요" required></label>'
      + '<label class="quick-kcal"><span class="visually-hidden">열량 kcal</span><input type="number" name="calories" min="0" inputmode="numeric" placeholder="—"><span>kcal</span></label></div>'
      + '<div class="quick-favourites" hidden><p>자주 먹은 것 · 누르면 채워져요</p><div class="quick-chips"></div></div>'
      + '<details class="quick-more"><summary>+ 단백질 · 탄수화물 · 지방 · 메모</summary><div class="quick-macros">'
      + '<label>단백질 g<input type="number" name="protein" min="0" inputmode="decimal"></label><label>탄수화물 g<input type="number" name="carbohydrates" min="0" inputmode="decimal"></label>'
      + '<label>지방 g<input type="number" name="fat" min="0" inputmode="decimal"></label></div><label class="quick-memo">메모<input name="memo" maxlength="5000"></label></details>');
    const tools = form.querySelector(".quick-tools");
    const when = document.createElement("label"); when.className = "quick-when";
    when.innerHTML = '<span class="visually-hidden">식사 시각</span><input type="datetime-local" name="eaten_at" required>';
    const type = document.createElement("label"); type.className = "quick-type";
    type.innerHTML = '<span class="visually-hidden">끼니</span><select name="meal_type"></select>';
    for (const [key, label] of Object.entries(MEAL_TYPES)) { const option = document.createElement("option"); option.value = key; option.textContent = label; type.querySelector("select").append(option); }
    tools.append(type, when);
    if (!record && window.fitlogPhotoRecord) {
      const photo = document.createElement("button");
      photo.type = "button"; photo.className = "quick-photo"; photo.innerHTML = ICON_CAMERA;
      photo.setAttribute("aria-label", "사진으로 기록 (AI가 열량을 채워요)");
      photo.addEventListener("click", () => { dialog.close(); window.fitlogPhotoRecord(); });
      tools.append(photo);
    }
    const at = record ? new Date(record.eaten_at) : new Date();
    form.elements.eaten_at.value = localInput(at);
    form.elements.meal_type.value = record?.meal_type || mealTypeAt(at);
    form.elements.eaten_at.addEventListener("change", () => { if (!record) form.elements.meal_type.value = mealTypeAt(new Date(form.elements.eaten_at.value)); });
    for (const name of ["name", "calories", "protein", "carbohydrates", "fat", "memo"]) form.elements[name].value = record?.[name] ?? "";
    if (record && [record.protein, record.carbohydrates, record.fat, record.memo].some((item) => item != null && item !== "")) form.querySelector(".quick-more").open = true;
    const picks = favourites(recent);
    if (picks.length) {
      const box = form.querySelector(".quick-favourites");
      box.hidden = false;
      box.querySelector(".quick-chips").append(...picks.map((item) => {
        const chip = document.createElement("button");
        chip.type = "button";
        const name = document.createElement("span"); name.textContent = item.name;
        const kcal = document.createElement("small"); kcal.className = "num"; kcal.textContent = item.calories != null ? number(item.calories) : "";
        chip.append(name, kcal);
        chip.setAttribute("aria-label", item.name + (item.calories != null ? " " + number(item.calories) + "kcal" : "") + " 채우기");
        chip.addEventListener("click", () => {
          box.querySelectorAll("button").forEach((other) => other.setAttribute("aria-pressed", String(other === chip)));
          for (const field of ["name", "calories", "protein", "carbohydrates", "fat"]) form.elements[field].value = item[field] ?? "";
        });
        return chip;
      }));
    }
    wire(form, "meal", record, () => ({eaten_at: new Date(form.elements.eaten_at.value).toISOString(), meal_type: form.elements.meal_type.value,
      name: form.elements.name.value.trim(), calories: value(form, "calories"), protein: value(form, "protein"), carbohydrates: value(form, "carbohydrates"),
      fat: value(form, "fat"), memo: form.elements.memo.value.trim() || null}),
      onSaved, (payload) => MEAL_TYPES[payload.meal_type] + " ‘" + payload.name + "’을 기록했어요");
    return form;
  }

  const BUILDERS = {weight, sleep, meal};
  async function open(kind, {record = null, onSaved = null} = {}) {
    const form = await BUILDERS[kind](record, onSaved);
    if (!dialog.open) dialog.showModal();
    if (kind === "meal" && !record) form.elements.name.focus();
  }
  // Short lines for the ＋ sheet's tiles: the last weight, last night's sleep, the meal of this hour.
  async function hints() {
    const [weights, sleeps] = await Promise.all([api("/body-metrics?limit=3").catch(() => []), api("/sleep?limit=1").catch(() => [])]);
    const lastWeight = weights.find((item) => item.weight != null);
    const lastSleep = sleeps[0];
    const today = dateInput(new Date());
    return {
      weight: lastWeight ? "지난번 " + number(lastWeight.weight) + "kg" : "첫 기록을 남겨 보세요",
      sleep: lastSleep && dateInput(new Date(lastSleep.sleep_end)) === today ? "어젯밤 " + minutesText(lastSleep.duration_minutes) : "어젯밤 기록 전",
      meal: "지금은 " + MEAL_TYPES[mealTypeAt(new Date())]
    };
  }
  window.FitQuick = {open, hints};
})();
