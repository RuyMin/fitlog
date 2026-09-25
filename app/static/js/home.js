"use strict";
async function homeGet(path) {
  const response = await fetch(path, {cache: "no-store", signal: AbortSignal.timeout(10000)});
  if (!response.ok) throw new Error("기록을 불러오지 못했습니다.");
  return response.json();
}
const formatNumber = (value) => new Intl.NumberFormat("ko-KR", {maximumFractionDigits:1}).format(value);
async function loadSummary() {
  try {
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Seoul";
    const data = await homeGet("/api/dashboard?timezone=" + encodeURIComponent(zone));
    document.querySelector("#today-sets").textContent = data.total_sets;
    document.querySelector("#today-workouts").textContent = data.workouts_count ? "오늘 " + data.workouts_count + "회 · 완료 " + data.completed_sets + "세트" : "오늘은 아직 운동 기록이 없어요";
    document.querySelector("#latest-weight").textContent = data.latest_weight ? formatNumber(data.latest_weight.weight) : "—";
    document.querySelector("#weight-note").textContent = data.latest_weight ? "최근 측정 · " + new Date(data.latest_weight.measured_at).toLocaleDateString("ko-KR") : "아직 체중 기록이 없어요";
    document.querySelector("#today-protein").textContent = data.protein_grams == null ? "—" : formatNumber(data.protein_grams);
    document.querySelector("#protein-goal").textContent = "목표 " + formatNumber(data.protein_goal_grams) + " g";
    document.querySelector("#protein-note").textContent = !data.meals_count ? "오늘은 아직 식단 기록이 없어요" : data.protein_known_count < data.meals_count ? "입력된 값 합계 · 미입력 " + (data.meals_count - data.protein_known_count) + "건" : "오늘 식단 " + data.meals_count + "건 합계";
    document.querySelector("#today-sleep").textContent = data.sleep_minutes == null ? "—" : Math.floor(data.sleep_minutes / 60) + "시간 " + (data.sleep_minutes % 60) + "분";
    document.querySelector("#sleep-note").textContent = data.sleep_records_count ? "오늘 종료된 수면 " + data.sleep_records_count + "회 합계" : "오늘 종료된 수면 기록이 없어요";
  } catch {
    for (const id of ["today-workouts","weight-note","protein-note","sleep-note"]) document.getElementById(id).textContent = "연결 후 새로고침해 주세요";
  }
}
async function loadRecent() {
  const target = document.querySelector("#recent-workouts");
  try {
    const recent = await homeGet("/api/workouts?limit=3");
    target.replaceChildren();
    if (!recent.length) {
      const empty = document.createElement("p"); empty.className = "empty";
      empty.textContent = "아직 운동 기록이 없습니다. 첫 운동을 남겨보세요."; target.append(empty);
    }
    for (const workout of recent) {
      const link = document.createElement("a"); link.href = "/workouts#" + workout.id;
      link.style.cssText = "display:block;padding:14px 0;border-bottom:1px solid var(--line);overflow-wrap:anywhere";
      link.textContent = workout.workout_date + " · " + workout.title + " · " + workout.sets.length + "세트"; target.append(link);
    }
  } catch { target.textContent = "운동 기록을 불러오지 못했습니다. 연결 후 새로고침해 주세요."; }
}
loadSummary();
loadRecent();
