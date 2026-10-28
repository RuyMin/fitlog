"use strict";
// 관리자 화면 › 기본 종목: the exercise list every user picks from. Add, edit, hide or show, and undo changes.
(() => {
  const $ = (id) => document.getElementById(id);
  const node = (tag, text, className) => { const n = document.createElement(tag); if (text != null) n.textContent = text; if (className) n.className = className; return n; };
  const form = $("preset-form");
  // The open form's choices: chips for the lists, the figure for muscles (FitAnatomy.picker).
  const state = {presets: [], options: null, editing: null, choice: {}, partPicked: false, muscles: null};
  const normalize = (text) => text.replace(/\s+/g, "").toLowerCase();

  async function call(method, path = "", body) {
    const response = await fetch("/api/admin/presets" + path, {method, cache: "no-store", signal: AbortSignal.timeout(15000),
      headers: body ? {"Content-Type": "application/json"} : {}, body: body ? JSON.stringify(body) : undefined});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = data.detail;
      throw new Error(Array.isArray(detail) ? "입력값을 확인해 주세요. (" + detail.map((item) => item.loc.at(-1)).join(", ") + ")" : detail || "저장하지 못했습니다.");
    }
    return data;
  }
  function message(text) { $("preset-message").textContent = text; }
  async function load() {
    const data = await call("GET");
    state.presets = data.presets; state.options = data.options;
    render();
  }

  function render() {
    const query = normalize($("preset-query").value), filter = $("preset-filter").value;
    const shown = state.presets.filter((preset) => {
      if (filter === "changed" && !(preset.edited && !preset.added)) return false;
      if (filter === "added" && !preset.added) return false;
      if (filter === "hidden" && !preset.hidden) return false;
      return !query || [preset.name, preset.name_en || "", ...preset.aliases].some((name) => normalize(name).includes(query));
    });
    const hidden = state.presets.filter((preset) => preset.hidden).length;
    $("preset-count").textContent = "전체 " + state.presets.length + "개" + (hidden ? " · 숨김 " + hidden + "개" : "")
      + (shown.length !== state.presets.length ? " · 표시 " + shown.length + "개" : "");
    const list = $("preset-list"); list.replaceChildren();
    if (!shown.length) list.append(node("p", "맞는 종목이 없어요.", "hint"));
    for (const preset of shown) list.append(row(preset));
  }
  function row(preset) {
    const item = node("div", null, "preset-item" + (preset.hidden ? " is-hidden" : ""));
    const text = node("div", null, "preset-text");
    const title = node("p", null, "preset-title");
    title.append(node("strong", preset.name));
    if (preset.added) title.append(node("b", "추가함", "preset-badge added"));
    else if (preset.edited) title.append(node("b", "바꿈", "preset-badge edited"));
    if (preset.hidden) title.append(node("b", "숨김", "preset-badge hidden"));
    text.append(title, node("span", [preset.body_part, preset.equipment, state.options.tracking[preset.tracking]].join(" · ")));
    const actions = node("div", null, "preset-actions");
    const action = (label, run, className) => {
      const control = node("button", label, className); control.type = "button";
      control.setAttribute("aria-label", preset.name + " " + label);
      control.addEventListener("click", async () => {
        control.disabled = true; message("");
        try { await run(); } catch (error) { message(error.message); } finally { control.disabled = false; }
      });
      actions.append(control);
    };
    action("수정", async () => open(preset));
    action(preset.hidden ? "보이기" : "숨기기", async () => {
      if (!preset.hidden && !confirm(preset.name + "을(를) 운동 추가 목록에서 숨길까요? 이미 쓰고 있는 사용자의 기록은 그대로예요.")) return;
      await call("PUT", "/" + preset.id + "/hidden", {hidden: !preset.hidden});
      message(preset.name + (preset.hidden ? "을(를) 다시 보이게 했어요." : "을(를) 숨겼어요."));
      await load();
    });
    if (preset.added) action("삭제", async () => {
      if (!confirm(preset.name + "을(를) 삭제할까요?")) return;
      await call("DELETE", "/" + preset.id);
      message(preset.name + "을(를) 삭제했어요."); await load();
    }, "danger");
    else if (preset.edited || preset.hidden) action("원래대로", async () => {
      if (!confirm(preset.name + "의 변경을 모두 되돌릴까요? 앱에 들어 있던 원래 내용으로 돌아가요.")) return;
      const result = await call("DELETE", "/" + preset.id);
      message("원래 내용(" + result.preset.name + ")으로 되돌렸어요."); await load();
    });
    item.append(text, actions);
    return item;
  }

  function chips(id, entries, key, after) {
    $(id).replaceChildren(...entries.map(([value, label]) => {
      const on = state.choice[key] === value;
      const chip = node("button", label, "chip" + (on ? " on" : "")); chip.type = "button";
      chip.setAttribute("aria-pressed", String(on));
      chip.addEventListener("click", () => { state.choice[key] = value; if (after) after(); renderChoices(); });
      return chip;
    }));
  }
  function renderChoices() {
    const o = state.options;
    chips("preset-equipment", o.equipment.map((gear) => [gear, gear]), "equipment");
    chips("preset-kind", Object.entries(o.kinds), "kind");
    chips("preset-tracking", Object.entries(o.tracking), "tracking");
    chips("preset-part", o.parts.map((part) => [part, part]), "body_part", () => { state.partPicked = true; });
    $("preset-part-note").textContent = state.partPicked ? "" : "· 주 근육에서 자동으로 정해요";
  }
  function open(preset = null) {
    const o = state.options;
    state.editing = preset;
    $("preset-form-title").textContent = preset ? "종목 수정" : "새 종목";
    form.elements.name.value = preset?.name || "";
    form.elements.name_en.value = preset?.name_en || "";
    form.elements.aliases.value = (preset?.aliases || []).join(", ");
    state.choice = {equipment: preset?.equipment || o.equipment[0], kind: preset?.kind || "compound",
      tracking: preset?.tracking || "weight_reps", body_part: preset?.body_part || o.parts[0]};
    state.partPicked = Boolean(preset);
    state.muscles = FitAnatomy.picker(preset?.muscles || [], {names: o.muscles, onChange: (picked) => {
      const part = FitAnatomy.partOf(picked);
      if (!state.partPicked && part) { state.choice.body_part = part; renderChoices(); }
    }});
    $("preset-muscles").replaceChildren(state.muscles.root);
    renderChoices();
    $("preset-variants").textContent = preset?.variants?.length
      ? "그립·자세 선택 " + preset.variants.length + "가지(" + preset.variants.map((variant) => variant.label).join(", ") + ")는 그대로 유지돼요." : "";
    form.querySelector(".form-error").textContent = "";
    $("preset-dialog").showModal();
    form.elements.name.focus();
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const save = $("preset-save"); save.disabled = true;
    const error = form.querySelector(".form-error"); error.textContent = "";
    const body = {name: form.elements.name.value.trim(), name_en: form.elements.name_en.value.trim(),
      aliases: form.elements.aliases.value.split(/[,，]/).map((alias) => alias.trim()).filter(Boolean),
      ...state.choice, muscles: state.muscles.get()};
    try {
      if (!body.name) throw new Error("이름을 적어 주세요.");
      if (!body.muscles.length) throw new Error("주로 쓰는 근육을 하나 이상 골라 주세요.");
      const editing = state.editing;
      const saved = await call(editing ? "PUT" : "POST", editing ? "/" + editing.id : "", body);
      $("preset-dialog").close();
      message(editing ? saved.name + "을(를) 저장했어요. 모든 사용자에게 바로 반영돼요." : saved.name + "을(를) 추가했어요. 이제 모든 사용자가 고를 수 있어요.");
      await load();
    } catch (failure) { error.textContent = failure.message; }
    finally { save.disabled = false; }
  });
  $("preset-new").addEventListener("click", () => open());
  $("preset-query").addEventListener("input", render);
  $("preset-filter").addEventListener("change", render);
  document.querySelectorAll("#preset-dialog [data-close]").forEach((control) => control.addEventListener("click", () => $("preset-dialog").close()));

  window.fitlogMe.then((me) => {
    if (!me || me.role !== "admin") return;
    load().catch((error) => message(error.message));
  });
})();
