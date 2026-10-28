"use strict";
// 내 목표 (settings): auto (body details + latest weight) or manual calorie and macro goals, plus sleep.
(() => {
  const $ = (id) => document.getElementById(id);
  const form = $("goals-form");
  const number = (value) => new Intl.NumberFormat("ko-KR", {maximumFractionDigits: 1}).format(value);
  const hours = (minutes) => Math.floor(minutes / 60) + "시간" + (minutes % 60 ? " " + minutes % 60 + "분" : "");
  const SOURCE = {default: "기본 목표", auto: "자동 계산", manual: "직접 입력"};
  const AIM = {lose: "감량", maintain: "유지", gain: "증가"};
  const MISSING = {sex: "성별", birth_year: "출생연도", height: "키", weight: "체중"};
  const MANUAL = ["calorie_kcal", "protein_g", "carbohydrate_g", "fat_g"];
  let state = null, preview = 0, timer = 0;

  const year = new Date().getFullYear();
  form.elements.birth_year.min = year - 100;
  form.elements.birth_year.max = year - 15;

  async function call(method, path = "", body) {
    const response = await fetch("/api/me/goals" + path, {method, cache: "no-store", signal: AbortSignal.timeout(15000),
      headers: body ? {"Content-Type": "application/json"} : {}, body: body ? JSON.stringify(body) : undefined});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = data.detail;
      throw new Error(Array.isArray(detail) ? detail.map((item) => item.msg.replace(/^Value error, /, "")).join("\n") : detail || "목표를 저장하지 못했습니다.");
    }
    return data;
  }
  function element(tag, text, className) {
    const item = document.createElement(tag);
    if (text != null) item.textContent = text;
    if (className) item.className = className;
    return item;
  }
  const mode = () => form.elements.mode.value;
  function payload() {
    const value = (name) => form.elements[name].value.trim();
    const numeric = (name) => value(name) === "" ? null : Number(value(name));
    const body = {mode: mode(), sex: value("sex") || null, birth_year: numeric("birth_year"), height_cm: numeric("height_cm"),
      activity: value("activity"), aim: value("aim"), sleep_minutes: numeric("sleep_minutes")};
    for (const name of MANUAL) body[name] = numeric(name);
    return body;
  }

  // The goals in effect now, with where they come from.
  function showNow(goals) {
    const box = $("goal-now"); box.replaceChildren();
    const head = element("p", null, "goal-now-head");
    head.append(element("span", "지금 적용 중", "goal-now-label"), element("b", SOURCE[goals.source], "goal-badge goal-" + goals.source));
    const values = element("p", null, "goal-now-values");
    values.append(element("strong", number(goals.calorie_kcal) + " kcal"),
      element("span", "단백질 " + number(goals.protein_g) + "g · 탄수화물 " + number(goals.carbohydrate_g) + "g · 지방 " + number(goals.fat_g) + "g · 수면 " + hours(goals.sleep_minutes)));
    box.append(head, values);
  }
  function showWeight(data) {
    const weight = $("goal-weight"); weight.replaceChildren();
    if (data.weight == null) {
      const link = element("a", "기록이 없어요 · 체중 기록하기 ›"); link.href = "/body-metrics#new";
      weight.append(link);
      return;
    }
    const at = new Date(data.weight_measured_at);
    weight.append(number(data.weight) + "kg", element("small", " " + (at.getMonth() + 1) + "/" + at.getDate() + " 기록"));
  }
  // The auto result: the numbers and how they were reached, or what is still missing.
  function showResult(data) {
    const box = $("goal-result"); box.replaceChildren();
    const found = data.estimate;
    if (!found) {
      // A missing weight is recorded on 몸·추이, the rest is typed here; the age range is the last reason.
      const typed = data.missing.filter((name) => name !== "weight").map((name) => MISSING[name]).join("·");
      const object = (word) => word + ((word.charCodeAt(word.length - 1) - 0xAC00) % 28 ? "을" : "를");
      const needs = [typed && object(typed) + " 입력하고", data.missing.includes("weight") && "체중을 한 번 기록하면"].filter(Boolean).join(" ")
        .replace(/입력하고$/, "입력하면") || "출생연도를 확인하면";
      box.append(element("p", needs + " 바로 계산돼요. 그전까지는 기본 목표(" + number(data.defaults.calorie_kcal) + "kcal · 단백질 " + number(data.defaults.protein_g) + "g)를 씁니다.", "goal-missing"));
      return;
    }
    const top = element("p", null, "goal-result-top");
    top.append(element("span", "계산 결과"), element("strong", number(found.calorie_kcal) + " kcal"));
    const macros = element("p", "단백질 " + number(found.protein_g) + "g · 탄수화물 " + number(found.carbohydrate_g) + "g · 지방 " + number(found.fat_g) + "g", "goal-result-macros");
    const maintain = Math.round(found.bmr * found.activity_factor);
    const steps = element("ul", null, "goal-steps");
    steps.append(
      element("li", "기초대사량 " + number(found.bmr) + "kcal (만 " + found.age + "세 기준) × 활동량 " + found.activity_factor + " = 유지 열량 약 " + number(maintain) + "kcal"),
      element("li", found.adjustment_kcal ? AIM[form.elements.aim.value] + " " + (found.adjustment_kcal > 0 ? "+" : "−") + number(Math.abs(found.adjustment_kcal)) + "kcal" + (maintain + found.adjustment_kcal < found.bmr ? " (기초대사량 아래로는 내리지 않음)" : "") + " → " + number(found.calorie_kcal) + "kcal" : "유지 열량을 10kcal 단위로 → " + number(found.calorie_kcal) + "kcal"),
      element("li", "단백질은 체중 1kg당 " + found.protein_g_per_kg + "g(" + AIM[form.elements.aim.value] + " 목표 기준), 지방은 열량의 25%, 나머지를 탄수화물로 나눴어요."));
    box.append(top, macros, steps);
  }
  function manualCheck() {
    const [kcal, protein, carbohydrate, fat] = MANUAL.map((name) => Number(form.elements[name].value) || 0);
    const sum = protein * 4 + carbohydrate * 4 + fat * 9;
    $("manual-check").textContent = protein || carbohydrate || fat
      ? "세 영양소를 열량으로 바꾸면 약 " + number(Math.round(sum)) + "kcal" + (kcal ? " (하루 열량과 " + (sum >= kcal ? "+" : "−") + number(Math.abs(Math.round(sum - kcal))) + "kcal 차이)" : "") + "예요. 꼭 맞출 필요는 없어요."
      : "";
  }
  function showMode() {
    $("goal-auto").hidden = mode() !== "auto";
    $("goal-manual").hidden = mode() !== "manual";
    // Manual starts from the goals in effect, so only the numbers to change need typing.
    if (mode() === "manual" && state && MANUAL.every((name) => !form.elements[name].value)) {
      const goals = state.goals;
      [goals.calorie_kcal, goals.protein_g, goals.carbohydrate_g, goals.fat_g].forEach((value, index) => form.elements[MANUAL[index]].value = Math.round(value));
      manualCheck();
    }
  }
  function fill(data) {
    state = data;
    const profile = data.profile;
    for (const name of ["sex", "birth_year", "height_cm", "activity", "aim", ...MANUAL]) form.elements[name].value = profile[name] ?? "";
    form.elements.sleep_minutes.value = profile.sleep_minutes ?? "";
    for (const radio of form.elements.mode) radio.checked = radio.value === profile.mode;
    $("goals-delete").hidden = !data.saved;
    showNow(data.goals); showWeight(data); showResult(data); showMode(); manualCheck();
  }
  // Recalculate as the user types (nothing is saved until 목표 저장).
  function recalculate() {
    clearTimeout(timer);
    form.querySelector(".form-error").textContent = "";
    timer = setTimeout(async () => {
      const request = ++preview;
      try {
        const data = await call("POST", "/preview", payload());
        if (request === preview) showResult(data);
      } catch (error) { if (request === preview) form.querySelector(".form-error").textContent = error.message; }
    }, 300);
  }

  const sleep = form.elements.sleep_minutes;
  sleep.append(new Option("기본 (7시간)", ""));
  for (let minutes = 300; minutes <= 600; minutes += 30) sleep.append(new Option(hours(minutes), String(minutes)));

  form.addEventListener("change", (event) => {
    if (event.target.name === "mode") showMode();
    else if (MANUAL.includes(event.target.name)) manualCheck();
  });
  form.addEventListener("input", (event) => {
    if (["sex", "birth_year", "height_cm", "activity", "aim"].includes(event.target.name)) recalculate();
    if (MANUAL.includes(event.target.name)) manualCheck();
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const save = $("goals-save");
    save.disabled = true; form.querySelector(".form-error").textContent = ""; $("goals-message").textContent = "";
    try {
      fill(await call("PUT", "", payload()));
      $("goals-message").textContent = "목표를 저장했어요. 홈과 식단 화면에 바로 반영됩니다.";
    } catch (error) { form.querySelector(".form-error").textContent = error.message; }
    finally { save.disabled = false; }
  });
  $("goals-delete").addEventListener("click", async () => {
    if (!confirm("입력한 성별·출생연도·키와 직접 정한 목표를 지울까요? 기본 목표로 돌아갑니다. (체중 기록은 지우지 않아요.)")) return;
    $("goals-delete").disabled = true;
    try {
      await call("DELETE");
      fill(await call("GET"));
      for (const name of MANUAL) form.elements[name].value = "";
      $("goals-message").textContent = "목표 정보를 지웠어요. 기본 목표를 씁니다.";
    } catch (error) { form.querySelector(".form-error").textContent = error.message; }
    finally { $("goals-delete").disabled = false; }
  });

  call("GET").then(fill).catch((error) => { $("goal-now").textContent = "목표를 불러오지 못했습니다. " + error.message; });
})();
