"use strict";
// Muscle figures: one shared SVG sprite (/static/img/anatomy.svg, Ryan Graves, CC BY 4.0), colored per
// figure with CSS variables (--m-<muscle>) so many thumbnails can reuse the same artwork.
window.FitAnatomy = (() => {
  // The page links the sprite with its content hash (app/pages.py), which also starts the download early.
  const SPRITE = document.getElementById("anatomy-sprite")?.getAttribute("href") || "/static/img/anatomy.svg";
  const VIEW_BOX = {front: "0 0 587 1137", back: "0 0 596 1133"};
  // Preset muscle tags → artwork muscles.
  const TAGS = {
    "대흉근": ["pectoralis_major"], "대흉근 상부": ["pectoralis_major"], "대흉근 하부": ["pectoralis_major"],
    "광배근": ["latissimus_dorsi"], "승모근": ["trapezius_upper", "trapezius_middle", "trapezius_lower"],
    "능형근": ["trapezius_middle"], "척추기립근": [],
    "승모근 상부": ["trapezius_upper"], "승모근 중부": ["trapezius_middle"], "승모근 하부": ["trapezius_lower"],
    "전면 삼각근": ["anterior_deltoid"], "측면 삼각근": ["lateral_deltoid"], "후면 삼각근": ["posterior_deltoid"],
    "이두근": ["biceps_brachii_caput_longum", "biceps_brachii_caput_breve"],
    "삼두근": ["triceps_brachii_caput_longum", "triceps_brachii_caput_laterale", "triceps_brachii_caput_mediale", "anconeus"],
    "전완근": ["brachioradialis", "flexor_digitorum_superficialis", "pronator_quadratus", "extensor_carpi_radialis_longus",
      "palmaris_longus", "flexor_carpi_radialis", "pronator_teres", "extensor_carpi_ulnaris", "extensor_digitorum", "flexor_carpi_ulnaris"],
    "대퇴사두근": ["rectus_femoris", "vastus_lateralis", "vastus_medialis"],
    "햄스트링": ["biceps_femoris", "semitendinosus", "semimembranosus"],
    "둔근": ["gluteus_maximus"], "중둔근": ["gluteus_medius"],
    "내전근": ["adductor_longus", "adductor_magnus", "pectineus", "gracilis"],
    "종아리": ["gastrocnemius"], "복직근": ["rectus_abdominis"], "복사근": ["external_oblique"],
    "코어": ["rectus_abdominis", "external_oblique"],
  };
  // Muscles best seen from the front; a thumbnail of anything else shows the back.
  const FRONT = new Set(["pectoralis_major", "anterior_deltoid", "lateral_deltoid", "biceps_brachii_caput_longum",
    "biceps_brachii_caput_breve", "rectus_abdominis", "external_oblique", "rectus_femoris", "vastus_lateralis",
    "vastus_medialis", "adductor_longus", "pectineus", "gracilis", "brachioradialis", "flexor_digitorum_superficialis"]);
  // Thumbnails crop to the half of the body where the primary muscle is, so the color stays visible.
  const LOWER = new Set(["rectus_femoris", "vastus_lateralis", "vastus_medialis", "biceps_femoris", "semitendinosus",
    "semimembranosus", "gluteus_maximus", "gluteus_medius", "adductor_longus", "adductor_magnus", "pectineus", "gracilis", "gastrocnemius"]);
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
    const [primary = null, ...secondary] = muscles;
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
      const area = main.length && main.every((key) => key === "gastrocnemius") ? "calf"
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
  return {figure, load, TAGS};
})();
