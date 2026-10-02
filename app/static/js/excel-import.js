"use strict";
(() => {
  const $ = id => document.getElementById(id);
  const node = (tag, text) => {const n=document.createElement(tag);if(text!=null)n.textContent=text;return n;};
  const labels={new:"신규",updated:"변경",identical:"동일",conflict:"확인 필요"};
  const fields={title:"제목",workout_date:"운동일",body_part:"부위",started_at:"시작",ended_at:"종료",memo:"메모",exercise:"종목",set_number:"세트 번호",weight:"중량/체중",reps:"횟수",completed:"완료 여부",rpe:"RPE",rir:"RIR",eaten_at:"식사 시각",meal_type:"식사 구분",name:"이름",calories:"열량",protein:"단백질",carbohydrates:"탄수화물",fat:"지방",image_url:"사진 URL",measured_at:"측정 시각",body_fat:"체지방률",skeletal_muscle:"골격근량"};
  function display(value){
    if(value==null)return "미기록";
    if(typeof value==="boolean")return value?"완료":"미완료";
    if(typeof value==="string"&&/^\d{4}-\d{2}-\d{2}T/.test(value))return new Date(value).toLocaleString("ko-KR",{timeZone:"Asia/Seoul"})+" (한국 시간)";
    return String(value);
  }
  function title(entry){const v=entry.incoming;if(entry.kind==="meals")return display(v.eaten_at)+" · "+v.name;if(entry.kind==="body_metrics")return display(v.measured_at);return entry.title;}
  let draft=null,busy=false,visible=100,chosen=new Set();
  const message=text=>{$("excel-message").textContent=text;};
  async function request(path, options={}) {
    const r=await fetch("/api/sync/excel"+path,{cache:"no-store",signal:AbortSignal.timeout(60000),...options});
    const data=await r.json();
    if(!r.ok)throw new Error(typeof data.detail==="string"?data.detail:"입력 값을 확인해 주세요.");
    return data;
  }
  function setBusy(value){busy=value;for(const id of ["excel-file","excel-compare","excel-save","excel-cancel","excel-select-all","excel-select-none"])$(id).disabled=value;$("excel-entries").querySelectorAll("input").forEach(n=>n.disabled=value);}
  function showError(error){message(error.name==="TimeoutError"?"응답 대기 시간이 지났습니다. 저장을 요청했다면 같은 저장 버튼으로 결과를 확인할 수 있습니다.":error.message==="Failed to fetch"?"서버에 연결하지 못했습니다. 연결을 확인해 주세요.":error.message);}
  function summary(){ $("excel-selection").textContent=`${chosen.size}개 선택 · 선택하지 않은 기록은 유지합니다.`;$("excel-save").textContent=chosen.size?`선택한 ${chosen.size}개 기록 저장`:"원본 파일만 보관"; }
  function changeSelection(entry,checked){
    if(checked){chosen.add(entry.key);if(entry.parent!=null){const parent=draft.entries.find(e=>e.key===entry.parent);if(parent&&parent.status==="new")chosen.add(parent.key);}}
    else{chosen.delete(entry.key);if(entry.kind==="workouts"&&entry.status==="new")draft.entries.filter(e=>e.parent===entry.key).forEach(e=>chosen.delete(e.key));}
    render();
    const input=$("excel-entries").querySelector(`input[data-key="${entry.key}"]`); if(input)input.focus({preventScroll:true});
  }
  function comparison(entry){
    const wrap=node("div");wrap.className="excel-values";
    const keys=entry.status==="updated"?entry.changes:Object.keys(entry.incoming);
    for(const key of keys){
      const value=entry.incoming[key];if(value==null&&entry.status!=="updated")continue;
      const block=node("div");block.append(node("strong",fields[key]||key));
      if(entry.before)block.append(node("p","기존: "+display(entry.before[key])));
      block.append(node("p","파일: "+display(value)));wrap.append(block);
    }
    return wrap;
  }
  function render(){
    if(!draft)return;
    const filter=$("excel-filter").value;
    const entries=draft.entries.filter(e=>filter==="all"||filter==="changes"&&e.status!=="identical"||filter===e.status);
    const box=$("excel-entries");const opened=new Set([...box.querySelectorAll("details.excel-entry[open]")].map(n=>n.dataset.key));box.replaceChildren();
    if(!entries.length)box.append(node("p","해당 항목이 없습니다."));
    for(const entry of entries.slice(0,visible)){
      const detail=node("details");detail.className="excel-entry";detail.dataset.key=entry.key;detail.open=opened.has(entry.key);
      const heading=node("summary",`${labels[entry.status]} · ${entry.label} · ${title(entry)}`);detail.append(heading);
      if(["new","updated"].includes(entry.status)){
        const label=node("label"),input=node("input");input.type="checkbox";input.checked=chosen.has(entry.key);input.disabled=busy;input.dataset.key=entry.key;input.addEventListener("change",()=>changeSelection(entry,input.checked));
        label.append(input,document.createTextNode(" 이 기록 저장"));detail.append(label);
      }
      detail.append(node("p",entry.reason),comparison(entry));
      if(entry.candidates?.length){const candidates=node("details");candidates.append(node("summary","기존 후보 확인"));for(const c of entry.candidates){const pre=node("pre",JSON.stringify(c.values,null,2));candidates.append(node("p","기존 ID "+c.id),pre);}detail.append(candidates);}
      box.append(detail);
    }
    $("excel-more").hidden=entries.length<=visible;
    summary();
  }
  async function discard(){if(draft){const token=draft.token;draft=null;chosen.clear();$("excel-review").hidden=true;try{await request("/"+token,{method:"DELETE"});}catch{ /* Server also expires unused previews. */ }}}
  $("excel-file").addEventListener("change",()=>{discard();message("");});
  $("excel-upload").addEventListener("submit",async event=>{
    event.preventDefault();if(busy)return;const file=$("excel-file").files[0];if(!file)return;
    if(!file.name.toLowerCase().endsWith(".xlsx")||file.size>5*1024*1024){message("5MB 이하의 .xlsx 파일을 선택해 주세요.");return;}
    setBusy(true);await discard();message("원본과 현재 기록을 비교하는 중…");
    try{
      draft=await request("/preview?filename="+encodeURIComponent(file.name),{method:"POST",headers:{"Content-Type":"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},body:file});chosen.clear();visible=100;
      $("excel-counts").textContent=Object.entries(labels).map(([k,v])=>`${v} ${draft.counts[k]||0}개`).join(" · ");
      $("excel-review").hidden=false;render();message("비교 완료. 저장할 항목을 확인하고 선택해 주세요.");
    }catch(error){showError(error);}finally{setBusy(false);}
  });
  $("excel-filter").addEventListener("change",()=>{visible=100;render();});
  $("excel-more").addEventListener("click",()=>{visible+=100;render();});
  $("excel-select-all").addEventListener("click",()=>{draft.entries.filter(e=>["new","updated"].includes(e.status)).forEach(e=>chosen.add(e.key));render();});
  $("excel-select-none").addEventListener("click",()=>{chosen.clear();render();});
  $("excel-cancel").addEventListener("click",async()=>{if(busy)return;await discard();message("비교를 취소했습니다. 기록은 변경하지 않았습니다.");});
  $("excel-save").addEventListener("click",async()=>{
    if(busy||!draft)return;setBusy(true);message("선택한 기록을 저장하는 중…");
    try{
      const result=await request("/"+draft.token+"/commit",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({selected:[...chosen]})});
      message(`저장 완료 · ${result.inserted}개 추가 · ${result.updated}개 수정 · ${result.skipped}개 유지. 원본 파일을 보관했습니다.`);
      draft=null;chosen.clear();$("excel-review").hidden=true;await history();window.dispatchEvent(new Event("fitlog-imported"));
    }catch(error){showError(error);}finally{setBusy(false);}
  });
  async function history(){
    try{const rows=await request("/history");const box=$("excel-history-list");box.replaceChildren();if(!rows.length)box.append(node("p","아직 Excel 비교 저장 이력이 없습니다."));
      for(const row of rows){const d=node("details");d.append(node("summary",`${new Date(row.saved_at).toLocaleString("ko-KR")} · ${row.filename} · 추가 ${row.result.inserted} / 수정 ${row.result.updated}`));
        for(const entry of row.changes){d.append(node("h3",title(entry)),comparison(entry));}box.append(d);}
    }catch{$("excel-history-list").textContent="저장 이력을 불러오지 못했습니다.";}
  }
  history();
})();
