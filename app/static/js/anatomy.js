"use strict";
// Muscle figures: one shared SVG sprite (/static/img/anatomy.svg, Ryan Graves, CC BY 4.0), colored per
// figure with CSS variables (--m-<muscle>) so many thumbnails can reuse the same artwork.
window.FitAnatomy = (() => {
  // The page links the sprite with its content hash (app/pages.py), which also starts the download early.
  const SPRITE = document.getElementById("anatomy-sprite")?.getAttribute("href") || "/static/img/anatomy.svg";
  const VIEW_BOX = {front: "0 0 587 1137", back: "0 0 596 1133"};
  // Preset muscle tags → artwork muscles.
  const FLEXORS = ["flexor_digitorum_superficialis", "pronator_quadratus", "palmaris_longus", "flexor_carpi_radialis", "pronator_teres", "flexor_carpi_ulnaris"];
  const EXTENSORS = ["extensor_carpi_radialis_longus", "extensor_carpi_ulnaris", "extensor_digitorum"];
  const TAGS = {
    "대흉근": ["pectoralis_upper", "pectoralis_lower"], "대흉근 상부": ["pectoralis_upper"], "대흉근 하부": ["pectoralis_lower"],
    "광배근": ["latissimus_dorsi"], "승모근": ["trapezius_upper", "trapezius_middle", "trapezius_lower"],
    "능형근": ["rhomboids"], "척추기립근": ["erector_spinae"], "전거근": ["serratus_anterior"], "극하근": ["infraspinatus"], "목": ["sternocleidomastoid"],
    "승모근 상부": ["trapezius_upper"], "승모근 중부": ["trapezius_middle"], "승모근 하부": ["trapezius_lower"],
    "전면 삼각근": ["anterior_deltoid"], "측면 삼각근": ["lateral_deltoid"], "후면 삼각근": ["posterior_deltoid"],
    "이두근": ["biceps_brachii_caput_longum", "biceps_brachii_caput_breve"],
    "이두근 장두": ["biceps_brachii_caput_longum"], "이두근 단두": ["biceps_brachii_caput_breve"], "상완근": ["brachialis"],
    "삼두근": ["triceps_brachii_caput_longum", "triceps_brachii_caput_laterale", "triceps_brachii_caput_mediale", "anconeus"],
    "삼두근 장두": ["triceps_brachii_caput_longum"], "삼두근 외측두": ["triceps_brachii_caput_laterale"],
    "삼두근 내측두": ["triceps_brachii_caput_mediale", "anconeus"],
    "전완근": ["brachioradialis", ...FLEXORS, ...EXTENSORS], "상완요골근": ["brachioradialis"],
    "전완 굴곡근": FLEXORS, "전완 신전근": EXTENSORS,
    "대퇴사두근": ["rectus_femoris", "vastus_lateralis", "vastus_medialis"],
    "대퇴직근": ["rectus_femoris"], "외측광근": ["vastus_lateralis"], "내측광근": ["vastus_medialis"],
    "햄스트링": ["biceps_femoris", "semitendinosus", "semimembranosus"],
    "햄스트링 바깥쪽": ["biceps_femoris"], "햄스트링 안쪽": ["semitendinosus", "semimembranosus"],
    "둔근": ["gluteus_maximus"], "중둔근": ["gluteus_medius"],
    "내전근": ["adductor_longus", "adductor_magnus", "pectineus", "gracilis"],
    "종아리": ["gastrocnemius", "soleus"], "비복근": ["gastrocnemius"], "가자미근": ["soleus"], "전경골근": ["tibialis_anterior"],
    "복직근": ["rectus_abdominis"], "복사근": ["external_oblique"],
    "코어": ["rectus_abdominis", "external_oblique"],
  };
  // Muscles best seen from the front; a thumbnail of anything else shows the back.
  const FRONT = new Set(["pectoralis_upper", "pectoralis_lower", "anterior_deltoid", "lateral_deltoid", "biceps_brachii_caput_longum",
    "biceps_brachii_caput_breve", "rectus_abdominis", "external_oblique", "rectus_femoris", "vastus_lateralis",
    "vastus_medialis", "adductor_longus", "pectineus", "gracilis", "brachioradialis", "flexor_digitorum_superficialis",
    "tibialis_anterior", "sternocleidomastoid", "serratus_anterior", "brachialis"]);
  // Thumbnails crop to the half of the body where the primary muscle is, so the color stays visible.
  const LOWER = new Set(["rectus_femoris", "vastus_lateralis", "vastus_medialis", "biceps_femoris", "semitendinosus",
    "semimembranosus", "gluteus_maximus", "gluteus_medius", "adductor_longus", "adductor_magnus", "pectineus", "gracilis",
    "gastrocnemius", "tibialis_anterior", "soleus"]);
  const CALF = new Set(["gastrocnemius", "tibialis_anterior", "soleus"]);
  const CROP = {upper: "93 90 400 400", lower: "113 480 360 360", calf: "143 720 300 300"};
  const PRIMARY = "#e8772e", SECONDARY = "#f5c394";
  let loading = null;

  // Insert the sprite once per page; <use href="#anatomy-front"> then refers to it.
  function load() {
    loading ??= fetch(SPRITE).then((r) => r.ok ? r.text() : Promise.reject(new Error("anatomy"))).then((text) => {
      const sprite = new DOMParser().parseFromString(text, "image/svg+xml").documentElement;
      const holder = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      holder.setAttribute("aria-hidden", "true");
      holder.setAttribute("width", "0"); holder.setAttribute("height", "0");
      holder.classList.add("anatomy-sprite");
      for (const symbol of sprite.querySelectorAll("symbol")) holder.append(document.importNode(symbol, true));
      document.body.prepend(holder);
    });
    return loading;
  }
  const keys = (muscles) => muscles.flatMap((muscle) => TAGS[muscle] || []);

  // muscles: the preset's muscle tags, first one primary. view: "both" | "auto" (one side, for thumbnails).
  function figure(muscles, {view = "both", captions = view === "both"} = {}) {
    load().catch(() => {});
    // Some tags have no artwork (심폐): the first one that does is drawn as primary.
    const [primary = null, ...secondary] = muscles.filter((muscle) => TAGS[muscle]?.length);
    const root = document.createElement("div");
    root.className = "anatomy";
    root.setAttribute("role", "img");
    root.setAttribute("aria-label", muscles.length ? "사용 근육: " + muscles.join(", ") : "근육 정보 없음");
    for (const key of keys(secondary)) root.style.setProperty("--m-" + key, SECONDARY);
    const main = keys(primary ? [primary] : []);
    for (const key of main) root.style.setProperty("--m-" + key, PRIMARY);
    const sides = view === "both" ? ["front", "back"] : [main.some((key) => FRONT.has(key)) || !main.length ? "front" : "back"];
    for (const side of sides) {
      const item = document.createElement("figure");
      const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      const area = main.length && main.every((key) => CALF.has(key)) ? "calf"
        : main.length && main.every((key) => LOWER.has(key)) ? "lower" : "upper";
      svg.setAttribute("viewBox", view === "both" ? VIEW_BOX[side] : CROP[area]);
      svg.setAttribute("aria-hidden", "true");
      const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
      use.setAttribute("href", "#anatomy-" + side);
      // Native size, so a cropped viewBox selects a region instead of rescaling the whole figure.
      const [, , width, height] = VIEW_BOX[side].split(" ");
      use.setAttribute("width", width); use.setAttribute("height", height);
      svg.append(use); item.append(svg);
      if (captions) { const caption = document.createElement("figcaption"); caption.textContent = side === "front" ? "앞" : "뒤"; item.append(caption); }
      root.append(item);
    }
    return root;
  }

  // Tapping the figure picks these by default; "세부 부위" mode picks the finer tags (삼두근 장두, 비복근 …).
  const BROAD = ["대흉근 상부", "대흉근 하부", "광배근", "승모근", "능형근", "척추기립근", "전거근", "극하근", "목",
    "전면 삼각근", "측면 삼각근", "후면 삼각근", "이두근", "상완근", "삼두근", "전완근", "복직근", "복사근",
    "대퇴사두근", "햄스트링", "둔근", "중둔근", "내전근", "종아리", "전경골근"];
  const PARTS = {"가슴": ["대흉근", "전거근"], "등": ["광배근", "승모근", "능형근", "척추기립근"],
    "어깨": ["삼각근", "극하근", "목"], "팔": ["이두근", "상완근", "삼두근", "전완", "상완요골근"],
    "코어": ["복직근", "복사근", "코어"], "하체": ["대퇴", "외측광근", "내측광근", "햄스트링", "둔근", "내전근", "종아리", "비복근", "가자미근", "전경골근"]};
  // The body part an exercise belongs to, from its main muscle (null for 심폐 or nothing picked).
  const partOf = (muscles) => {
    const main = muscles.find((muscle) => TAGS[muscle]?.length);
    return main ? Object.keys(PARTS).find((part) => PARTS[part].some((word) => main.includes(word))) || null : null;
  };

  // An editable figure: tap a muscle to add or remove it; the first one is the main muscle. `muscles` is
  // the starting list; onChange gets the new list after every change. Also offers the list as text
  // (make main, remove) and a menu for muscles too small to tap.
  function picker(muscles, {onChange = () => {}, names = Object.keys(TAGS)} = {}) {
    const picked = [...muscles];
    // Open on the side where the main muscle shows.
    const main = TAGS[picked.find((muscle) => TAGS[muscle]?.length)] || [];
    let side = !main.length || main.some((key) => FRONT.has(key)) ? "front" : "back", detail = picked.some((muscle) => TAGS[muscle] && !BROAD.includes(muscle) && muscle !== "대흉근");
    const root = document.createElement("div"); root.className = "muscle-picker";
    const make = (tag, className, text) => { const n = document.createElement(tag); if (className) n.className = className; if (text != null) n.textContent = text; return n; };
    const segment = make("div", "mp-sides");
    const sides = ["front", "back"].map((value) => {
      const control = make("button", null, value === "front" ? "앞" : "뒤"); control.type = "button";
      control.addEventListener("click", () => { side = value; draw(); });
      segment.append(control); return [value, control];
    });
    const map = make("div", "anatomy mp-map"), tip = make("p", "mp-tip"); tip.setAttribute("aria-live", "polite");
    const fine = make("label", "mp-detail"), box = document.createElement("input"); box.type = "checkbox";
    box.addEventListener("change", () => { detail = box.checked; draw(); });
    fine.append(box, " 세부 부위로 고르기 (삼두근 장두, 대흉근 상부 …)");
    const menu = make("select", "mp-menu"); menu.setAttribute("aria-label", "목록에서 근육 추가");
    menu.addEventListener("change", () => { if (menu.value) toggleTag(menu.value); menu.value = ""; });
    const list = make("div", "mp-list");
    root.append(segment, map, tip, fine, menu, list);

    function changed(text) { tip.textContent = text; onChange([...picked]); draw(); }
    function toggleTag(tag) {
      const at = picked.indexOf(tag);
      if (at >= 0) picked.splice(at, 1); else picked.push(tag);
      changed((at >= 0 ? "뺐어요: " : picked.length === 1 ? "주 근육: " : "더했어요: ") + tag);
    }
    // A tap on a muscle already covered by a picked tag removes that tag; otherwise adds the smallest tag for it.
    function tapKey(key) {
      const covering = picked.find((tag) => TAGS[tag]?.includes(key));
      if (covering) return toggleTag(covering);
      const pool = detail ? names.filter((name) => TAGS[name]) : BROAD;
      const tag = pool.filter((name) => TAGS[name].includes(key)).sort((a, b) => TAGS[a].length - TAGS[b].length)[0];
      if (tag) toggleTag(tag);
    }
    function draw() {
      for (const [value, control] of sides) control.setAttribute("aria-pressed", String(value === side));
      box.checked = detail;
      map.removeAttribute("style");
      picked.forEach((tag, i) => { for (const key of TAGS[tag] || []) if (i === 0 || !map.style.getPropertyValue("--m-" + key)) map.style.setProperty("--m-" + key, i === 0 ? PRIMARY : SECONDARY); });
      for (const key of TAGS[picked[0]] || []) map.style.setProperty("--m-" + key, PRIMARY);
      load().then(() => {
        const symbol = document.getElementById("anatomy-" + side);
        const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        svg.setAttribute("viewBox", side === "front" ? "60 60 467 1000" : "60 60 476 1000");
        // A copy of the artwork (not <use>), so a tap reports which muscle it hit. Ids get a prefix so the
        // chest clip paths do not clash with the sprite's.
        const id = "mp" + Math.random().toString(36).slice(2, 8);
        svg.innerHTML = symbol.innerHTML.replace(/id="pec-/g, `id="${id}-pec-`).replace(/url\(#pec-/g, `url(#${id}-pec-`);
        svg.setAttribute("aria-hidden", "true");
        svg.addEventListener("click", (event) => {
          const shape = event.target.closest('path[class^="m-"]');
          if (shape) tapKey(shape.getAttribute("class").slice(2));
        });
        map.replaceChildren(svg);
      }).catch(() => map.replaceChildren(make("p", "hint", "근육 그림을 불러오지 못했어요. 아래 목록에서 골라 주세요.")));
      menu.replaceChildren(new Option("목록에서 근육 추가…", ""), ...names.filter((name) => TAGS[name] && !picked.includes(name)).map((name) => new Option(name, name)));
      list.replaceChildren(...picked.map((tag, i) => {
        const row = make("div", "mp-row");
        const dot = make("i", "mp-dot"); dot.style.background = i === 0 ? PRIMARY : SECONDARY;
        const label = make("span", null, tag + " "); label.append(make("small", null, i === 0 ? "주 근육" : "보조"));
        row.append(dot, label);
        if (i > 0) {
          const main = make("button", "mp-main", "주 근육으로"); main.type = "button";
          main.addEventListener("click", () => { picked.splice(i, 1); picked.unshift(tag); changed("주 근육: " + tag); });
          row.append(main);
        }
        const drop = make("button", "mp-drop", "×"); drop.type = "button"; drop.setAttribute("aria-label", tag + " 빼기");
        drop.addEventListener("click", () => toggleTag(tag));
        row.append(drop);
        return row;
      }));
      if (!picked.length) list.append(make("p", "hint", "그림에서 근육을 눌러 고르세요. 처음 고른 근육이 주 근육이 돼요."));
    }
    draw();
    return {root, get: () => [...picked]};
  }
  return {figure, picker, partOf, load, TAGS};
})();
