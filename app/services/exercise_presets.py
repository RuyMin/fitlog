"""Built-in exercise presets: names, aliases and body-part/equipment/muscle tags.

The base list ships as app/static/data/exercise_presets.json. Admins change it from the admin page: their
edits, hidden presets and added presets live in `preset_overrides` and are laid over the base here, so
every user sees the same list and later releases can still add to the file. A user's own Exercise row
links to a preset through `preset_id`; the preset never changes what the user has stored. A hidden
preset stays in the catalog (marked `hidden`) so exercises already linked to it keep working; it only
leaves the picker and name matching.
"""
import copy
import hashlib
import json
import re
from functools import cache
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "static" / "data" / "exercise_presets.json"
_merged: dict = {}


@cache
def base() -> dict:
    """The shipped list, without admin changes."""
    return json.loads(PATH.read_text(encoding="utf-8"))


def overlay(base_catalog: dict, rows: list) -> dict:
    """`base_catalog` with the admin's rows (PresetOverride-like: preset_id, data, hidden) laid over it."""
    result = copy.deepcopy(base_catalog)
    changes = {row.preset_id: row for row in rows}
    presets = []
    for preset in result["presets"]:
        row = changes.pop(preset["id"], None)
        if row is not None:
            if row.data:
                preset.update(json.loads(row.data))
                preset["edited"] = True
            if row.hidden:
                preset["hidden"] = True
        presets.append(preset)
    for row in sorted(changes.values(), key=lambda item: item.preset_id):
        if row.data:
            presets.append({"id": row.preset_id, **json.loads(row.data), "added": True, **({"hidden": True} if row.hidden else {})})
    result["presets"] = presets
    return result


def catalog() -> dict:
    """The list every user sees: the base with the admin's changes. Rebuilt only when those change."""
    from sqlalchemy import func, select
    from sqlalchemy.exc import OperationalError
    from app.database import SessionLocal
    from app.models import PresetOverride
    try:
        with SessionLocal() as session:
            stamp = tuple(session.execute(select(func.count(), func.max(PresetOverride.updated_at))).one())
            if _merged.get("stamp") != stamp:
                rows = list(session.scalars(select(PresetOverride)))
                _merged.update(stamp=stamp, catalog=overlay(base(), rows))
    except OperationalError:
        return base()  # before the table exists (a migration in progress)
    return _merged["catalog"]


def version() -> str:
    """Short hash of the catalog, so pages can link it and phones keep it until it changes."""
    data = catalog()
    if _merged.get("hashed") is not data:
        _merged.update(hashed=data, version=hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:12])
    return _merged["version"]


def visible() -> list[dict]:
    return [preset for preset in catalog()["presets"] if not preset.get("hidden")]


def find(preset_id: str | None) -> dict | None:
    return next((p for p in catalog()["presets"] if p["id"] == preset_id), None) if preset_id else None


def ids() -> frozenset[str]:
    return frozenset(preset["id"] for preset in catalog()["presets"])


def variant_ids(preset_id: str | None) -> frozenset[str]:
    """Grip / foot-position / stance options a preset offers; none for custom exercises."""
    return frozenset(item["id"] for item in (find(preset_id) or {}).get("variants", []))


def normalize(name: str) -> str:
    return re.sub(r"\s+", "", name).lower()


def match_name(name: str) -> str | None:
    """The preset whose name or alias equals `name` (ignoring spaces and case), when exactly one does."""
    key = normalize(name)
    hits = {preset["id"] for preset in visible()
            if key in {normalize(preset["name"]), normalize(preset["name_en"]), *map(normalize, preset["aliases"])}}
    return next(iter(hits)) if len(hits) == 1 else None


# Old records often name the grip inside the exercise ("랫풀다운 페러럴그립"). Common spellings, then the
# words that only say "grip"/"bar", are folded so the rest can be compared with a variant's label.
SPELLINGS = {"페러럴": "패러럴", "패럴렐": "패러럴", "페럴렐": "패러럴", "페러렐": "패러럴", "파라렐": "패러럴", "parallel": "패러럴",
             "브이바": "v바", "디핸들": "d핸들", "언더핸드": "언더", "미듐": "미디엄", "와이드그립": "와이드",
             "팩덱": "펙덱", "이지바벨": "ez바", "이지바": "ez바"}
# "원암 해머컬" is the 해머 컬 done one arm at a time: the same exercise for the list.
ONE_ARM = re.compile(r"^(원암|싱글암|한팔|한손)")
# Words that turn a movement into a different one: a name with one never takes muscles from a preset without it.
OPPOSITES = ("리버스",)


def fold(text: str) -> str:
    text = re.sub(r"[\s()\[\]·,./_-]+", "", text).lower()
    for wrong, right in SPELLINGS.items():
        text = text.replace(wrong, right)
    return text


def grip_key(text: str) -> str:
    return re.sub(r"(그립|grip|바|bar)$", "", fold(text).replace("그립", ""))


def split_variant(name: str) -> tuple[str, str | None] | None:
    """The preset (and grip/stance variant) an exercise name stands for: "랫풀다운 페러럴그립" →
    ("lat_pulldown", "parallel"), "랫 풀다운" → ("lat_pulldown", None). "원암" in front and the preset's own
    equipment in front ("덤벨 해머컬") are ignored. None when unsure."""
    text = ONE_ARM.sub("", fold(name))
    best = None
    for preset in visible():
        names = {fold(preset["name"]), fold(preset["name_en"]), *map(fold, preset["aliases"])} - {""}
        gear = fold(preset["equipment"])
        for key in names | {gear + key for key in names if not key.startswith(gear)}:
            if not (text.startswith(key) or text.endswith(key)):
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


def muscle_names() -> list[str]:
    """Every muscle the shipped list names, grip variants included: what a preset or a user's own exercise
    may be tagged with."""
    return sorted({muscle for preset in base()["presets"]
                   for muscle in [*preset["muscles"], *(m for variant in preset.get("variants", []) for m in variant.get("muscles", []))]})


def similar(name: str) -> dict | None:
    """The visible preset whose name or alias is the longest part of `name` ("해머 스트렝스 인클라인 프레스" →
    인클라인 프레스), to suggest its muscles for a user's own exercise. None when nothing fits or two fit equally."""
    text = fold(name)
    best, length = None, 1
    for preset in visible():
        for key in {fold(preset["name"]), fold(preset["name_en"]), *map(fold, preset["aliases"])}:
            if len(key) < length or key not in text:
                continue
            # "덤벨 리버스 플라이" works the back, not the chest like 덤벨 플라이.
            if any(word in text and word not in key for word in OPPOSITES):
                continue
            if len(key) > length:
                best, length = preset, len(key)
            elif best is not None and best["muscles"] != preset["muscles"]:
                best = None
    return best
