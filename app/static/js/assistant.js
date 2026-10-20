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
    no_key: "설정에서 본인 Anthropic API 키를 먼저 등록해 주세요.",
    no_consent: "설정에서 'AI 외부 전송'에 동의해야 사용할 수 있어요.",
    key_unreadable: "저장된 키를 읽을 수 없습니다. 설정에서 키를 다시 등록해 주세요.",
    invalid_key: "API 키가 올바르지 않습니다. 설정에서 키를 확인해 주세요.",
    key_forbidden: "이 API 키로는 사용할 수 없습니다. Anthropic 콘솔에서 키 권한을 확인해 주세요.",
    model_unavailable: "이 키로 사용할 수 없는 모델입니다. 관리자에게 문의해 주세요.",
    request_rejected: "Anthropic이 요청을 거절했습니다. 콘솔에서 크레딧·결제 상태를 확인해 주세요.",
    rate_limited: "Anthropic 사용량 한도에 걸렸습니다. 잠시 후 다시 시도해 주세요.",
    daily_limit: "오늘 사용할 수 있는 횟수를 모두 썼습니다. 내일 다시 이용해 주세요.",
    refused: "이 내용으로는 초안을 만들 수 없습니다. 표현을 바꿔 다시 시도해 주세요.",
    too_long: "내용이 너무 길어요. 나눠서 입력해 주세요.",
    server_not_configured: "관리자가 AI 기능을 아직 설정하지 않았습니다.",
    unreachable: "AI 서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.",
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

  function message(text, error = false) { $("assistant-message").textContent = text; $("assistant-message").className = "assistant-message" + (error ? " error" : ""); }
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

  async function loadStatus() {
    try {
      const r = await fetch("/api/assistant/status", {cache: "no-store", signal: AbortSignal.timeout(10000)});
      if (!r.ok) return;
      const s = await r.json();
      const setup = !s.server_ready ? ERRORS.server_not_configured : !s.key_hint ? ERRORS.no_key : !s.consent ? ERRORS.no_consent : "";
      $("assistant-setup").hidden = !setup;
      $("assistant-setup").replaceChildren(node("span", setup + " "));
      if (setup && s.server_ready) { const link = node("a", "설정으로 이동 →"); link.href = "/settings"; $("assistant-setup").append(link); }
      $("assistant-form").hidden = Boolean(setup);
      $("assistant-usage").textContent = `오늘 ${s.used_today}/${s.daily_limit}회 사용`;
    } catch { /* the rest of the home page still works without the assistant */ }
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
            reps: get("reps").value === "" ? null : Number(get("reps").value), completed: get("completed").checked};
        });
      }
      body[kind].push(data);
    }
    return body;
  }

  $("assistant-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = $("assistant-submit");
    button.disabled = true; message("초안을 만드는 중이에요… (최대 1분)");
    try {
      const r = await fetch("/api/assistant/draft", {method: "POST", cache: "no-store", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({text: $("assistant-text").value, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Seoul"}),
        signal: AbortSignal.timeout(120000)});
      const data = await r.json();
      if (!r.ok) throw new Error(errorText(data, "초안을 만들지 못했습니다."));
      render(data);
    } catch (error) { message(error.name === "TimeoutError" ? "응답이 늦어 중단했습니다. 다시 시도해 주세요." : error.message, true); }
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
      $("assistant-drafts").replaceChildren(); drafts = []; $("assistant-save-row").hidden = true; $("assistant-text").value = "";
      message(`저장 완료 · ${parts.join(" · ")}${data.sets ? ` (세트 ${data.sets}개)` : ""}`);
      if (typeof loadSummary === "function") loadSummary();
      if (typeof loadRecent === "function") loadRecent();
    } catch (error) { message(error.message, true); }
    finally { button.disabled = false; }
  });

  $("assistant-discard").addEventListener("click", () => {
    $("assistant-drafts").replaceChildren(); drafts = []; $("assistant-save-row").hidden = true; message("");
  });

  loadStatus();
})();
