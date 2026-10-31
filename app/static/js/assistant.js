"use strict";
// Free text -> AI drafts -> the person edits and confirms -> one save. Nothing is stored before "저장".
(() => {
  const $ = (id) => document.getElementById(id);
  const node = (tag, text, className) => {
    const n = document.createElement(tag);
    if (text != null) n.textContent = text;
    if (className) n.className = className;
    return n;
  };
  const ERRORS = {
    no_key: "아직 AI 기록을 쓸 수 없어요. 관리자가 준비하면 바로 쓸 수 있어요.",
    no_key_admin: "AI 기록을 쓰려면 먼저 준비가 필요해요.",
    no_consent: "AI 기록을 쓰려면 먼저 동의가 필요해요.",
    key_unreadable: "지금은 AI 기록을 쓸 수 없어요. 관리자에게 알려 주세요.",
    invalid_key: "지금은 AI 기록을 쓸 수 없어요. 관리자에게 알려 주세요.",
    key_forbidden: "지금은 AI 기록을 쓸 수 없어요. 관리자에게 알려 주세요.",
    model_unavailable: "지금은 AI 기록을 쓸 수 없어요. 관리자에게 알려 주세요.",
    request_rejected: "지금은 AI 기록을 쓸 수 없어요. 관리자에게 알려 주세요.",
    rate_limited: "지금 AI가 바빠요. 잠시 후 다시 해 주세요.",
    daily_limit: "오늘 AI 기록을 다 썼어요. 내일 다시 쓸 수 있어요.",
    refused: "이 내용으로는 기록을 만들지 못했어요. 조금 다르게 적어 보세요.",
    too_long: "내용이 너무 길어요. 나눠서 적어 주세요.",
    server_not_configured: "아직 AI 기록을 쓸 수 없어요.",
    unreachable: "AI에 연결하지 못했어요. 잠시 후 다시 해 주세요.",
  };
  const MEAL_TYPES = [["breakfast", "아침"], ["lunch", "점심"], ["dinner", "저녁"], ["snack", "간식"], ["other", "기타"]];
  const KINDS = {
    meals: {label: "식단", fields: [
      ["eaten_at", "식사 시각", "datetime"], ["meal_type", "구분", MEAL_TYPES], ["name", "음식", "text"],
      ["calories", "열량(kcal)", "number"], ["protein", "단백질(g)", "number"], ["carbohydrates", "탄수화물(g)", "number"],
      ["fat", "지방(g)", "number"], ["memo", "메모", "text"]]},
    body_metrics: {label: "체중·신체", fields: [
      ["measured_at", "측정 시각", "datetime"], ["weight", "체중(kg)", "number"], ["body_fat", "체지방률(%)", "number"],
      ["skeletal_muscle", "골격근량(kg)", "number"], ["memo", "메모", "text"]]},
    sleep: {label: "수면", fields: [
      ["sleep_start", "잠든 시각", "datetime"], ["sleep_end", "일어난 시각", "datetime"],
      ["sleep_type", "구분", [["main", "밤잠"], ["nap", "낮잠"]]], ["memo", "메모", "text"]]},
    workouts: {label: "운동", fields: [
      ["workout_date", "운동일", "date"], ["title", "제목", "text"], ["body_part", "부위", "text"], ["memo", "메모", "text"]]},
  };
  let drafts = [];
  let photos = [];  // [{media_type, data, preview}] - sent with the next draft, never stored
  const MAX_PHOTOS = 3, MAX_EDGE = 1568;

  async function decode(file) {
    try { return await createImageBitmap(file, {imageOrientation: "from-image"}); } catch { /* fall back below */ }
    const url = await new Promise((resolve, reject) => { const r = new FileReader(); r.onload = () => resolve(r.result); r.onerror = reject; r.readAsDataURL(file); });
    return await new Promise((resolve, reject) => { const img = new Image(); img.onload = () => resolve(img); img.onerror = reject; img.src = url; });
  }
  // Re-encoding through a canvas shrinks the upload and drops EXIF (including location).
  async function compress(file) {
    const source = await decode(file);
    const scale = Math.min(1, MAX_EDGE / Math.max(source.width, source.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(source.width * scale); canvas.height = Math.round(source.height * scale);
    canvas.getContext("2d").drawImage(source, 0, 0, canvas.width, canvas.height);
    const url = canvas.toDataURL("image/jpeg", 0.85);
    return {media_type: "image/jpeg", data: url.slice(url.indexOf(",") + 1), preview: url};
  }
  function renderPhotos() {
    const list = $("assistant-photo-list"); list.replaceChildren();
    photos.forEach((photo, index) => {
      const item = node("div", null, "assistant-photo"), img = node("img"), remove = node("button", "✕");
      img.src = photo.preview; img.alt = `첨부 사진 ${index + 1}`;
      remove.type = "button"; remove.setAttribute("aria-label", `사진 ${index + 1} 빼기`);
      remove.addEventListener("click", () => { photos.splice(index, 1); renderPhotos(); });
      item.append(img, remove); list.append(item);
    });
  }
  $("assistant-photo-input").addEventListener("change", async (event) => {
    const files = [...event.target.files]; event.target.value = "";
    const room = MAX_PHOTOS - photos.length;
    if (files.length > room) message(`사진은 최대 ${MAX_PHOTOS}장까지 올릴 수 있어요.`, true);
    for (const file of files.slice(0, Math.max(room, 0))) {
      try { photos.push(await compress(file)); } catch { message("이 사진은 읽을 수 없어요. JPG나 PNG로 다시 시도해 주세요.", true); }
    }
    renderPhotos();
  });
  function clearPhotos() { photos = []; renderPhotos(); }

  function message(text, error = false) {
    $("assistant-message").textContent = text; $("assistant-message").className = "assistant-message" + (error ? " error" : "");
    // The save button sits below the drafts in a scrolling sheet; bring the error into view.
    if (error && text) $("assistant-message").scrollIntoView({block: "nearest", behavior: "smooth"});
  }
  function errorText(data, fallback) {
    const detail = data && data.detail;
    if (detail && detail.code) return ERRORS[detail.code] || fallback;
    if (Array.isArray(detail)) return detail.map((d) => {
      const [, kind, index, ...rest] = d.loc;
      return (KINDS[kind] ? `${KINDS[kind].label} ${Number(index) + 1}` : "") + (rest.length ? ` · ${rest.join(".")}` : "") + ": " + d.msg;
    }).join("\n");
    return typeof detail === "string" ? detail : fallback;
  }
  function localInput(iso) {
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return "";
    return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  }

  // The record sheet is AI first; its direct-record list appears only when the AI can't be used right now.
  // A failed draft keeps it open too (say, the AI account is out of credit), until a draft works again.
  let draftFailed = false;
  const direct = (show) => { const list = document.getElementById("direct-record"); if (list) list.hidden = !(show || draftFailed); };
  async function loadStatus() {
    try {
      const r = await fetch("/api/assistant/status", {cache: "no-store", signal: AbortSignal.timeout(10000)});
      if (!r.ok) { direct(true); return; }
      const s = await r.json();
      const noKey = s.can_manage_key ? ERRORS.no_key_admin : ERRORS.no_key;
      const setup = !s.server_ready ? ERRORS.server_not_configured : !s.key_configured ? noKey : !s.consent ? ERRORS.no_consent : "";
      $("assistant-setup").hidden = !setup;
      $("assistant-setup").replaceChildren(node("span", setup + " "));
      // Members can fix consent in settings; only an admin can fix a missing key.
      if (setup && s.server_ready && (s.key_configured || s.can_manage_key)) {
        const link = node("a", s.key_configured ? "동의하러 가기 →" : "AI 키 등록하러 가기 →");
        link.href = s.key_configured ? "/settings#account" : "/admin"; $("assistant-setup").append(link);
      }
      $("assistant-form").hidden = Boolean(setup);
      $("assistant-usage").textContent = `오늘 ${s.used_today}/${s.daily_limit}회 사용`;
      direct(Boolean(setup) || s.used_today >= s.daily_limit);
    } catch { direct(true); /* the rest of the home page still works without the assistant */ }
  }

  function field(kind, data, [name, label, type]) {
    const id = `ad-${drafts.length}-${kind}-${name}`;
    const wrap = node("div", null, type === "datetime" ? "assistant-wide" : null), title = node("label", label);
    title.htmlFor = id;
    let input;
    if (Array.isArray(type)) {
      input = node("select");
      for (const [value, text] of type) { const o = node("option", text); o.value = value; input.append(o); }
      input.value = data[name] ?? type[0][0];
    } else {
      input = node("input");
      input.type = type === "datetime" ? "datetime-local" : type;
      if (type === "number") input.step = "any";
      input.value = type === "datetime" ? localInput(data[name]) : data[name] ?? "";
    }
    input.id = id; input.dataset.name = name; input.dataset.type = Array.isArray(type) ? "select" : type;
    wrap.append(title, input);
    return wrap;
  }

  // The table edits these; everything else a drafted set carries is kept as it is and saved with it.
  const EDITED = ["exercise", "set_number", "weight", "reps", "completed"];
  const SHOWN = [["left_reps", "왼쪽", (v) => v + "회 (회 칸은 오른쪽)"], ["memo", "메모", String],
    ["duration_seconds", "시간", (s) => Math.floor(s / 60) + "분" + (s % 60 ? " " + s % 60 + "초" : "")],
    ["distance_m", "거리", (m) => (m / 1000).toFixed(2).replace(/\.?0+$/, "") + "km"], ["speed_kmh", "속도", (v) => v + "km/h"],
    ["incline_pct", "경사", (v) => v + "%"], ["level", "레벨", (v) => String(v)], ["calories", "소모", (v) => v + "kcal"],
    ["heart_rate", "심박", (v) => v + "bpm"]];

  function setRow(set) {
    const tr = node("tr");
    const cell = (type, value, name) => {
      const input = node("input"); input.type = type; input.dataset.name = name;
      if (type === "checkbox") input.checked = value !== false; else { input.value = value ?? ""; if (type === "number") input.step = "any"; }
      input.setAttribute("aria-label", {exercise: "종목", set_number: "세트", weight: "중량(kg)", reps: "횟수", completed: "완료"}[name]);
      const td = node("td"); td.append(input); return td;
    };
    const remove = node("button", "빼기"); remove.type = "button"; remove.addEventListener("click", () => tr.remove());
    const td = node("td"); td.append(remove);
    tr.append(cell("text", set.exercise, "exercise"), cell("number", set.set_number, "set_number"), cell("number", set.weight, "weight"),
      cell("number", set.reps, "reps"), cell("checkbox", set.completed, "completed"), td);
    // One-side, note, cardio and timed values are kept as they are (edit them later on the workouts screen); the
    // common ones are shown as a summary.
    const extra = Object.fromEntries(Object.entries(set).filter(([key, v]) => !EDITED.includes(key) && v != null));
    tr.dataset.extra = JSON.stringify(extra);
    const summary = SHOWN.filter(([key]) => extra[key] != null).map(([key, label, format]) => label + " " + format(extra[key])).join(" · ");
    if (summary) tr.firstChild.append(node("small", summary, "assistant-extra"));
    return tr;
  }

  function render(result) {
    drafts = [];
    const box = $("assistant-drafts"); box.replaceChildren();
    for (const [kind, spec] of Object.entries(KINDS)) {
      for (const [index, item] of (result[kind] || []).entries()) {
        const card = node("article", null, "assistant-draft");
        const include = node("input"); include.type = "checkbox"; include.checked = item.errors.length === 0;
        include.setAttribute("aria-label", `${spec.label} ${index + 1} 저장에 포함`);
        include.addEventListener("change", () => card.classList.toggle("excluded", !include.checked));
        card.classList.toggle("excluded", !include.checked);
        const head = node("div", null, "assistant-draft-head"); head.append(include, node("span", `${spec.label} ${index + 1}`));
        if (item.estimated) head.append(node("span", "영양 정보 AI 추정 · 확인 후 수정하세요", "assistant-badge"));
        const fields = node("div", null, "assistant-fields");
        for (const f of spec.fields) fields.append(field(kind, item.data, f));
        card.append(head, fields);
        if (kind === "workouts") {
          const table = node("table", null, "assistant-sets"), head2 = node("tr");
          for (const h of ["종목", "세트", "kg", "회", "완료", ""]) head2.append(node("th", h));
          table.append(head2);
          for (const set of item.data.sets || []) table.append(setRow(set));
          card.append(table);
        }
        if (item.errors.length) {
          const list = node("ul", null, "assistant-errors");
          for (const e of item.errors) list.append(node("li", e));
          card.append(list);
        }
        box.append(card);
        drafts.push({kind, card, include});
      }
    }
    if (result.unparsed && result.unparsed.length) {
      const note = node("div", null, "assistant-unparsed"), list = node("ul");
      note.append(node("strong", "기록으로 바꾸지 못한 내용"));
      for (const u of result.unparsed) list.append(node("li", u));
      note.append(list); box.append(note);
    }
    $("assistant-save-row").hidden = drafts.length === 0;
    message(drafts.length ? "초안을 확인하고 고칠 부분을 수정한 뒤 저장하세요. 저장 전에는 아무것도 기록되지 않습니다." : "기록으로 바꿀 내용을 찾지 못했어요. 조금 더 구체적으로 적어 주세요.");
  }

  function value(input) {
    const raw = input.value.trim();
    if (input.dataset.type === "datetime") return raw ? new Date(raw).toISOString() : null;
    if (input.dataset.type === "number") return raw === "" ? null : Number(raw);
    return raw === "" ? null : raw;
  }

  function collect() {
    const body = {meals: [], body_metrics: [], sleep: [], workouts: []};
    for (const {kind, card, include} of drafts) {
      if (!include.checked) continue;
      const data = {};
      for (const input of card.querySelectorAll(".assistant-fields [data-name]")) data[input.dataset.name] = value(input);
      if (kind === "workouts") {
        data.sets = [...card.querySelectorAll(".assistant-sets tr")].slice(1).map((tr) => {
          const get = (name) => tr.querySelector(`[data-name="${name}"]`);
          return {exercise: get("exercise").value.trim(), set_number: Number(get("set_number").value), weight: value(get("weight")),
            reps: get("reps").value === "" ? null : Number(get("reps").value), completed: get("completed").checked,
            ...JSON.parse(tr.dataset.extra || "{}")};
        });
      }
      body[kind].push(data);
    }
    return body;
  }

  $("assistant-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!$("assistant-text").value.trim() && !photos.length) { message("문장이나 사진을 하나 이상 입력해 주세요.", true); return; }
    const button = $("assistant-submit");
    button.disabled = true; message(photos.length ? "사진과 내용을 보고 초안을 만드는 중이에요… (최대 1분)" : "초안을 만드는 중이에요… (최대 1분)");
    try {
      const r = await fetch("/api/assistant/draft", {method: "POST", cache: "no-store", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({text: $("assistant-text").value, images: photos.map(({media_type, data}) => ({media_type, data})),
          timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Seoul"}),
        signal: AbortSignal.timeout(120000)});
      const data = await r.json();
      if (!r.ok) throw new Error(errorText(data, "초안을 만들지 못했어요."));
      draftFailed = false;
      render(data);
    } catch (error) {
      draftFailed = true;
      // No connection (TypeError) or a non-JSON answer (SyntaxError) gets plain words, not the browser's.
      const text = error.name === "TimeoutError" ? "AI 응답이 늦어 멈췄어요. 잠시 후 다시 해 주세요."
        : error instanceof TypeError || error instanceof SyntaxError ? ERRORS.unreachable : error.message;
      message(text + " 아래에서 직접 기록할 수도 있어요.", true);
    }
    finally { button.disabled = false; loadStatus(); }
  });

  $("assistant-save").addEventListener("click", async () => {
    const button = $("assistant-save");
    button.disabled = true; message("저장하는 중…");
    try {
      const r = await fetch("/api/assistant/commit", {method: "POST", cache: "no-store", headers: {"Content-Type": "application/json"},
        body: JSON.stringify(collect()), signal: AbortSignal.timeout(20000)});
      const data = await r.json();
      if (!r.ok) throw new Error(errorText(data, "저장하지 못했습니다."));
      const parts = [["meals", "식단"], ["body_metrics", "체중·신체"], ["sleep", "수면"], ["workouts", "운동"]].filter(([k]) => data[k]).map(([k, l]) => `${l} ${data[k]}건`);
      $("assistant-drafts").replaceChildren(); drafts = []; $("assistant-save-row").hidden = true; $("assistant-text").value = ""; clearPhotos();
      message(`저장 완료 · ${parts.join(" · ")}${data.sets ? ` (세트 ${data.sets}개)` : ""}`);
      if (typeof loadSummary === "function") loadSummary();
      if (typeof loadRecent === "function") loadRecent();
    } catch (error) { message(error.message, true); }
    finally { button.disabled = false; }
  });

  $("assistant-discard").addEventListener("click", () => {
    $("assistant-drafts").replaceChildren(); drafts = []; $("assistant-save-row").hidden = true; message(""); clearPhotos();
  });

  loadStatus();
})();
