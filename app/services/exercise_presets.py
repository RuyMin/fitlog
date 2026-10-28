"""Built-in exercise presets (app/static/data/exercise_presets.json): names, aliases and body-part/equipment/muscle tags.

The file is read-only reference data shared by every user. It lives under /static/ so the workout page
can link it by content hash and phones keep it until it changes (the API route stays for older pages). A user's own Exercise row links to a
preset through `preset_id`; the preset never changes what the user has stored.
"""
import json
import re
from functools import cache
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "static" / "data" / "exercise_presets.json"


@cache
def catalog() -> dict:
    return json.loads(PATH.read_text(encoding="utf-8"))


@cache
def ids() -> frozenset[str]:
    return frozenset(preset["id"] for preset in catalog()["presets"])


def variant_ids(preset_id: str | None) -> frozenset[str]:
    """Grip / foot-position / stance options a preset offers; none for custom exercises."""
    preset = next((p for p in catalog()["presets"] if p["id"] == preset_id), None) if preset_id else None
    return frozenset(item["id"] for item in (preset or {}).get("variants", []))


def normalize(name: str) -> str:
    return re.sub(r"\s+", "", name).lower()


def match_name(name: str) -> str | None:
    """The preset whose name or alias equals `name` (ignoring spaces and case), when exactly one does."""
    key = normalize(name)
    hits = {preset["id"] for preset in catalog()["presets"]
            if key in {normalize(preset["name"]), normalize(preset["name_en"]), *map(normalize, preset["aliases"])}}
    return next(iter(hits)) if len(hits) == 1 else None


# Old records often name the grip inside the exercise ("랫풀다운 페러럴그립"). Common spellings, then the
# words that only say "grip"/"bar", are folded so the rest can be compared with a variant's label.
SPELLINGS = {"페러럴": "패러럴", "패럴렐": "패러럴", "페럴렐": "패러럴", "파라렐": "패러럴", "parallel": "패러럴",
             "브이바": "v바", "디핸들": "d핸들", "언더핸드": "언더", "미듐": "미디엄", "와이드그립": "와이드"}


def fold(text: str) -> str:
    text = re.sub(r"[\s()\[\]·,./_-]+", "", text).lower()
    for wrong, right in SPELLINGS.items():
        text = text.replace(wrong, right)
    return text


def grip_key(text: str) -> str:
    return re.sub(r"(그립|grip|바|bar)$", "", fold(text).replace("그립", ""))


def split_variant(name: str) -> tuple[str, str | None] | None:
    """The preset (and grip/stance variant) an exercise name stands for: "랫풀다운 페러럴그립" →
    ("lat_pulldown", "parallel"), "랫 풀다운" → ("lat_pulldown", None). None when unsure."""
    text = fold(name)
    best = None
    for preset in catalog()["presets"]:
        for key in {fold(preset["name"]), fold(preset["name_en"]), *map(fold, preset["aliases"])}:
            if not key or not (text.startswith(key) or text.endswith(key)):
                continue
            rest = text[len(key):] if text.startswith(key) else text[:-len(key)]
            if rest:
                hits = [v["id"] for v in preset.get("variants", []) if grip_key(v["label"]) == grip_key(rest)]
                if len(hits) != 1:
                    continue
                found = (len(key), preset["id"], hits[0])
            else:
                found = (len(key), preset["id"], None)
            if best is None or found[0] > best[0]:
                best = found
            elif found[0] == best[0] and found[1:] != best[1:]:
                best = (best[0], None, None)  # two presets fit equally well: leave it to the person
    return (best[1], best[2]) if best and best[1] else None
