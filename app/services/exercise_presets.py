"""Built-in exercise presets (app/data/exercise_presets.json): names, aliases and body-part/equipment/muscle tags.

The file is read-only reference data shared by every user. A user's own Exercise row links to a
preset through `preset_id`; the preset never changes what the user has stored.
"""
import json
import re
from functools import cache
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "data" / "exercise_presets.json"


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
