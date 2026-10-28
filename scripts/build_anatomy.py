"""Build app/static/img/anatomy.svg and app/static/css/anatomy.css from Ryan Graves' anatomy SVGs.

Source: the "advanced" male front/back SVGs bundled in muscle_mapper
(https://github.com/suryamolly/muscle_mapper, lib/src/assets/advanced), by Ryan Graves,
CC BY 4.0 (https://www.figma.com/community/file/1320468164820924031).
Changes: element ids removed, colors replaced by CSS classes so muscles can be highlighted.

Usage: python scripts/build_anatomy.py <dir with front.svg and back.svg>
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BODY_GROUPS = {"non_muscle", "face", "head", "hands", None}
BODY_KEYS = {"underlayer", "hand", "palm", "wrist"}
# Muscle keys the app can highlight (see app/static/js/anatomy.js for the tag mapping).
KEYS = {"pectoralis_upper", "pectoralis_lower", "latissimus_dorsi", "trapezius_upper", "trapezius_middle", "trapezius_lower",
        "anterior_deltoid", "lateral_deltoid", "posterior_deltoid", "biceps_brachii_caput_longum",
        "biceps_brachii_caput_breve", "triceps_brachii_caput_longum", "triceps_brachii_caput_laterale",
        "triceps_brachii_caput_mediale", "anconeus", "brachioradialis", "flexor_digitorum_superficialis",
        "pronator_quadratus", "extensor_carpi_radialis_longus", "palmaris_longus", "flexor_carpi_radialis",
        "pronator_teres", "extensor_carpi_ulnaris", "extensor_digitorum", "flexor_carpi_ulnaris", "rectus_femoris",
        "vastus_lateralis", "vastus_medialis", "biceps_femoris", "semitendinosus", "semimembranosus",
        "gluteus_maximus", "gluteus_medius", "adductor_longus", "adductor_magnus", "pectineus", "gracilis",
        "gastrocnemius", "rectus_abdominis", "external_oblique", "infraspinatus", "tibialis_anterior", "sternocleidomastoid",
        "serratus_anterior", "brachialis", "soleus", "rhomboids", "erector_spinae"}
# The artwork draws pectoralis major as one shape; two clipped copies split it at this height (front view)
# into the upper (clavicular) and lower (sternal) parts that incline and decline work hit.
PEC_SPLIT = 240
# Muscles the artwork lacks, drawn for FitLog (right half; a mirrored copy makes the left). They sit on top of
# the original shapes, roughly where the muscle shows under the skin.
DRAWN = {
    "anatomy-front": {
        "serratus_anterior": "M397 304 C386 308 371 316 361 327 C373 330 387 326 395 321 Z M395 327 C383 332 369 342 361 353 "
                             "C374 353 386 347 392 342 Z M392 349 C381 355 369 365 363 376 C375 375 384 368 389 364 Z "
                             "M389 370 C381 376 373 386 368 395 C377 393 384 387 387 383 Z",
        "brachialis": "M454 328 C466 338 475 360 473 393 C466 396 458 391 451 381 C451 360 451 344 454 328 Z",
        "soleus": "M352 900 C351 950 352 990 350 1030 L343 1032 C343 990 342 950 345 905 Z",
    },
    "anatomy-back": {
        "rhomboids": "M302 205 C316 212 331 221 343 230 C346 254 348 277 351 299 C335 289 317 280 302 272 Z",
        "erector_spinae": "M302 298 C318 300 327 332 327 380 C327 422 322 455 311 478 L302 478 Z",
        "soleus": "M336 905 C334 955 344 1000 360 1022 C376 1000 400 955 400 905 C392 942 382 966 368 978 "
                  "C354 966 344 942 336 905 Z",
    },
}


def convert(path: Path, symbol: str) -> tuple[str, set[str]]:
    text = path.read_text(encoding="utf-8")
    view_box = re.search(r'viewBox="([^"]+)"', text).group(1)
    inner = text[text.index(">", text.index("<svg")) + 1:text.rindex("</svg>")]
    found, group, parts, last = set(), [], [], 0
    for m in re.finditer(r"<(/?)(g|path)\b([^>]*?)(/?)>", inner):
        parts.append(inner[last:m.start()]); last = m.end()
        close, tag, attrs, _ = m.groups()
        if close:
            if tag == "g":
                group.pop()
            parts.append(f"</{tag}>")
            continue
        ident = re.search(r'\bid="([^"]+)"', attrs)
        attrs = re.sub(r'\s*\bid="[^"]*"', "", attrs)
        if tag == "g":
            group.append(ident.group(1) if ident else (group[-1] if group else None))
            parts.append(f"<g{attrs}>")
            continue
        key = re.sub(r"(_\d+)?(_[lr])?$", "", ident.group(1)) if ident else ""
        if not re.search(r'\bfill="(?!none)[^"]*"', attrs):
            css = "a-none"  # outline helpers under the root's fill="none"
        elif key in KEYS:
            css = "m-" + key
            found.add(key)
        elif (group[0] if group else None) in BODY_GROUPS or key in BODY_KEYS:
            css = "a-body"
        else:
            css = "a-rest"
        attrs = re.sub(r'\s*\bfill="[^"]*"', "", attrs)
        attrs = re.sub(r'\bstroke="[^"]*"', 'stroke="#FFFFFF"', attrs)
        attrs = re.sub(r"\s+", " ", attrs).strip()
        if key == "pectoralis_major":
            for part in ("upper", "lower"):
                parts.append(f'<path class="m-pectoralis_{part}" clip-path="url(#pec-{part})" {attrs}></path>')
                found.add("pectoralis_" + part)
            continue
        parts.append(f'<path class="{css}" {attrs}></path>')
    width = view_box.split()[2]
    for key, d in DRAWN.get(symbol, {}).items():
        for mirror in ("", f' transform="translate({width},0) scale(-1,1)"'):
            parts.append(f'\n<path class="m-{key}" d="{d}"{mirror} stroke="#FFFFFF" stroke-linejoin="round"></path>')
        found.add(key)
    parts.append(inner[last:])
    body = re.sub(r"\n\s*\n", "\n", "".join(parts)).strip()
    if "pectoralis_upper" in found:
        body = (f'<clipPath id="pec-upper"><rect x="0" y="0" width="{width}" height="{PEC_SPLIT}"></rect></clipPath>'
                f'<clipPath id="pec-lower"><rect x="0" y="{PEC_SPLIT}" width="{width}" height="1000"></rect></clipPath>\n' + body)
    return f'<symbol id="{symbol}" viewBox="{view_box}">\n{body}\n</symbol>', found


def main(source: Path) -> None:
    front, front_keys = convert(source / "front.svg", "anatomy-front")
    back, back_keys = convert(source / "back.svg", "anatomy-back")
    missing = KEYS - front_keys - back_keys
    if missing:
        raise SystemExit(f"keys not found in artwork: {sorted(missing)}")
    notice = ("<!-- Anatomy artwork by Ryan Graves, CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/), "
              "https://www.figma.com/community/file/1320468164820924031 . Modified for FitLog: ids removed, "
              "colors moved to CSS classes. Generated by scripts/build_anatomy.py. -->")
    svg = f'<svg xmlns="http://www.w3.org/2000/svg">\n{notice}\n{front}\n{back}\n</svg>\n'
    (ROOT / "app/static/img").mkdir(parents=True, exist_ok=True)
    (ROOT / "app/static/img/anatomy.svg").write_text(svg, encoding="utf-8", newline="\n")
    rules = "\n".join(f".m-{key}{{fill:var(--m-{key},var(--a-rest))}}" for key in sorted(KEYS))
    css = ("/* Generated by scripts/build_anatomy.py. Muscle colors come from --m-<key> set on each figure. */\n"
           ".anatomy{--a-body:#ecefe9;--a-rest:#d3d9d0;display:flex;align-items:flex-end;gap:12px}\n"
           ".anatomy figure{flex:1;min-width:0;margin:0;display:flex;flex-direction:column;align-items:center;gap:2px}\n"
           ".anatomy svg{display:block;width:100%;height:auto}\n"
           ".anatomy figcaption{font-size:11px;color:var(--muted)}\n"
           ".a-body{fill:var(--a-body)}.a-rest{fill:var(--a-rest)}.a-none{fill:none}\n"
           "@media(prefers-color-scheme:dark){.anatomy{--a-body:#2b3a31;--a-rest:#40524a}}\n" + rules + "\n")
    (ROOT / "app/static/css/anatomy.css").write_text(css, encoding="utf-8", newline="\n")
    print("front", len(front_keys), "back", len(back_keys), "svg KB", len(svg) // 1024)
    print("FRONT_KEYS", sorted(front_keys))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
