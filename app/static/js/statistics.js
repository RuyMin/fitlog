import {renderChart} from "/static/js/charts.js";
const $ = (selector) => document.querySelector(selector);
const number = (value) => new Intl.NumberFormat("ko-KR", {maximumFractionDigits:1}).format(value);
const duration = (value) => { const minutes = Math.round(value); return Math.floor(minutes / 60) + "시간 " + minutes % 60 + "분"; };
const zone = Intl.DateTimeFormat().resolvedOptions().timeZone || "Asia/Seoul";
let current = null, request = 0, controller = null, cleanups = [], volumeCleanup = null;
function node(tag, text, className) { const item=document.createElement(tag); if(text != null)item.textContent=text; if(className)item.className=className; return item; }
function localDate(value) { return new Date(value.getTime()-value.getTimezoneOffset()*60000).toISOString().slice(0,10); }
function preset(days) {
  const end=new Date(), start=new Date(); start.setDate(end.getDate()-days+1);
  $("#statistics-filter").elements.date_from.value=localDate(start);
  $("#statistics-filter").elements.date_to.value=localDate(end);
  document.querySelectorAll("[data-days]").forEach((button)=>button.setAttribute("aria-pressed",String(Number(button.dataset.days)===days)));
}
function tableForExercises(items) {
  const target=$("#exercise-table"); target.replaceChildren();
  if(!items.length){target.append(node("p","선택한 조건의 세트가 없습니다.","empty-state"));return;}
  const scroll=node("div",null,"table-scroll"), table=node("table"), head=node("thead"), row=node("tr");
  table.append(node("caption","중량 내림차순 · 볼륨은 중량·횟수가 모두 있는 세트만 합산"));
  for(const title of ["종목","최고 중량","세트","볼륨 (kg·회)","미입력 세트"]){const th=node("th",title);th.scope="col";row.append(th);}
  head.append(row);table.append(head);
  const body=node("tbody");
  for(const item of items){
    const tr=node("tr");
    tr.append(node("td",item.name),node("td",item.max_weight == null ? "—" : number(item.max_weight)+" kg","number"),node("td",number(item.sets_count),"number"),node("td",item.volume_kg_reps == null ? "—" : number(item.volume_kg_reps),"number"),node("td",number(item.sets_count-item.known_volume_sets),"number"));
    body.append(tr);
  }
  table.append(body);scroll.append(table);target.append(scroll);
}
function renderVolume() {
  if(volumeCleanup)volumeCleanup();
  const id=$("#exercise-select").value;
  const exercise=current.exercises.find((item)=>String(item.exercise_id)===id);
  const source=exercise ? new Map(exercise.daily_volume.map((point)=>[point.date,point])) : null;
  const points=current.daily.map((point)=>{
    const volume=source ? source.get(point.date) : point;
    return {date:point.date,value:volume?.volume_kg_reps ?? null,missingLabel:volume?.sets_count ? "중량·횟수 미입력" : "기록 없음"};
  });
  const total=exercise?.sets_count ?? current.summary.sets_count;
  const known=exercise?.known_volume_sets ?? current.summary.known_volume_sets;
  $("#exercise-volume-note").textContent="일별 중량 × 횟수 합계 · 계산 가능 "+known+"/"+total+"세트 · 기록 없는 날은 비워둡니다.";
  volumeCleanup=renderChart($("#volume-chart"),{title:(exercise?.name || "전체 종목")+" 볼륨",points,unit:"kg·회",format:number});
}
function render(data) {
  cleanups.forEach((cleanup)=>cleanup());cleanups=[];
  current=data;
  $("#statistics-results").hidden=false;
  $("#period-label").textContent=data.date_from+" ~ "+data.date_to+" · "+data.timezone+" · "+(data.completed_only ? "완료 세트만" : "미완료 세트 포함");
  const summary=data.summary;
  $("#workout-count").textContent=number(summary.workouts_count);
  $("#set-count").textContent=number(summary.sets_count);
  $("#sets-note").textContent=data.completed_only ? "완료한 세트" : "완료·미완료 전체 세트";
  $("#total-volume").textContent=summary.volume_kg_reps == null ? "—" : number(summary.volume_kg_reps);
  $("#volume-note").textContent="미입력으로 제외 "+number(summary.sets_count-summary.known_volume_sets)+"세트";
  $("#sleep-average").textContent=summary.average_sleep_minutes == null ? "—" : duration(summary.average_sleep_minutes);
  $("#sleep-average-note").textContent="수면 기록이 있는 "+summary.sleep_days+"일 평균";
  $("#weight-change").textContent=summary.weight_change_kg == null ? "변화를 비교하려면 서로 다른 날짜의 체중이 2개 이상 필요합니다." : "기간 첫 기록 대비 "+(summary.weight_change_kg>0?"+":"")+number(summary.weight_change_kg)+" kg · 측정 "+summary.weight_days+"일";
  cleanups.push(renderChart($("#weekly-chart"),{title:"주간 세트 수",points:data.weekly.map((week)=>({date:week.week_start,label:week.period_start+" ~ "+week.period_end,value:week.sets_count})),kind:"bar",unit:"세트",format:number,integer:true}));
  cleanups.push(renderChart($("#weight-chart"),{title:"체중 변화",points:data.daily.map((point)=>({date:point.date,value:point.weight})),unit:"kg",format:number,zeroBaseline:false}));
  cleanups.push(renderChart($("#sleep-chart"),{title:"수면 시간 변화",points:data.daily.map((point)=>({date:point.date,value:point.sleep_minutes == null ? null : point.sleep_minutes/60})),kind:"bar",unit:"시간",format:(hours)=>number(hours)}));
  const selected=$("#exercise-select").value;
  const all=node("option","전체 종목");all.value="all";
  $("#exercise-select").replaceChildren(all,...data.exercises.map((exercise)=>{const option=node("option",exercise.name);option.value=exercise.exercise_id;return option;}));
  $("#exercise-select").value=data.exercises.some((exercise)=>String(exercise.exercise_id)===selected)?selected:"all";
  renderVolume();tableForExercises(data.exercises);
}
async function load() {
  const form=$("#statistics-filter");
  if(!form.reportValidity())return;
  const token=++request;
  if(controller)controller.abort();controller=new AbortController();
  const activeController=controller;
  const timeout=setTimeout(()=>activeController.abort(),15000);
  $("#statistics-status").className="";
  $("#statistics-status").textContent="기록을 계산하고 있어요…";
  $("#statistics-results").hidden=true;
  const query=new URLSearchParams({date_from:form.elements.date_from.value,date_to:form.elements.date_to.value,timezone:zone,completed_only:String(!form.elements.include_incomplete.checked)});
  try {
    const response=await fetch("/api/statistics?"+query,{cache:"no-store",signal:controller.signal});
    const data=await response.json();
    if(token!==request)return;
    if(!response.ok)throw new Error(typeof data.detail==="string"?data.detail:"조회 조건을 확인해 주세요.");
    render(data);$("#statistics-status").textContent="조회가 완료됐습니다.";
  } catch(error) {
    if(token!==request)return;
    $("#statistics-status").className="error";
    $("#statistics-status").textContent=error.name==="AbortError"?"조회 시간이 초과됐습니다. 다시 조회해 주세요.":error.name==="TypeError"?"통계를 불러오지 못했습니다. 연결을 확인하고 다시 조회해 주세요.":error.message;
  } finally { clearTimeout(timeout); }
}
$("#statistics-filter").addEventListener("submit",(event)=>{event.preventDefault();load();});
$("#statistics-filter").addEventListener("input",(event)=>{if(event.target.type==="date")document.querySelectorAll("[data-days]").forEach((button)=>button.setAttribute("aria-pressed","false"));});
document.querySelectorAll("[data-days]").forEach((button)=>button.addEventListener("click",()=>{preset(Number(button.dataset.days));load();}));
$("#exercise-select").addEventListener("change",renderVolume);
window.addEventListener("pagehide",()=>{cleanups.forEach((cleanup)=>cleanup());if(volumeCleanup)volumeCleanup();controller?.abort();});
preset(30);load();
