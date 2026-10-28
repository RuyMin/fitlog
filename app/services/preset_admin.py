"""Admin changes to the built-in exercise list: add, edit, hide or show, and undo.

Every change is a PresetOverride row laid over the shipped list (see exercise_presets). Users' own
exercises and records never change here; a preset only says how a linked exercise is shown and recorded.
"""
import json
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Exercise, PresetOverride, utc_now
from app.services import exercise_presets
from app.services.persistence import RecordConflict, RecordInvalid, RecordNotFound, commit

EDITABLE = ("name", "name_en", "aliases", "body_part", "equipment", "muscles", "kind", "tracking")
KINDS = {"compound": "복합", "isolation": "고립", "cardio": "유산소"}


def options() -> dict:
    """What a preset may be set to: the shipped list's parts, equipment, tracking types and muscles."""
    base = exercise_presets.base()
    # Every muscle the anatomy figure knows from the shipped list, grip variants included.
    muscles = sorted({muscle for preset in base["presets"]
                      for muscle in [*preset["muscles"], *(m for variant in preset.get("variants", []) for m in variant.get("muscles", []))]})
    return {"parts": base["parts"], "equipment": base["equipment"], "tracking": base["tracking"], "kinds": KINDS, "muscles": muscles}


def definition(values: dict) -> dict:
    """The stored fields for a preset, checked against the options, with the search tags filled in."""
    allowed = options()
    data = {key: values[key] for key in EDITABLE}
    data["name"] = data["name"].strip()
    data["name_en"] = (data["name_en"] or "").strip()
    data["aliases"] = list(dict.fromkeys(alias.strip() for alias in data["aliases"] if alias.strip() and alias.strip() != data["name"]))
    if data["body_part"] not in allowed["parts"]:
        raise RecordInvalid("운동 부위를 목록에서 골라 주세요.")
    if data["equipment"] not in allowed["equipment"]:
        raise RecordInvalid("장비를 목록에서 골라 주세요.")
    if data["kind"] not in KINDS or data["tracking"] not in allowed["tracking"]:
        raise RecordInvalid("운동 종류와 기록 방식을 목록에서 골라 주세요.")
    unknown = [muscle for muscle in data["muscles"] if muscle not in allowed["muscles"]]
    if unknown or not data["muscles"]:
        raise RecordInvalid("주로 쓰는 근육을 목록에서 하나 이상 골라 주세요.")
    data["muscles"] = list(dict.fromkeys(data["muscles"]))
    data["tags"] = list(dict.fromkeys([data["body_part"], *data["muscles"], data["equipment"],
                                       *(["기구"] if data["equipment"] != "맨몸" else []), *([KINDS[data["kind"]]] if data["kind"] != "cardio" else [])]))
    return data


def check_names(data: dict, preset_id: str | None) -> None:
    """Names must stay unique across the visible list, or imports could not tell presets apart."""
    mine = {exercise_presets.normalize(name) for name in [data["name"], data["name_en"], *data["aliases"]] if name}
    for preset in exercise_presets.visible():
        if preset["id"] == preset_id:
            continue
        theirs = {exercise_presets.normalize(name) for name in [preset["name"], preset.get("name_en", ""), *preset["aliases"]] if name}
        clash = mine & theirs
        if clash:
            raise RecordConflict(f"'{preset['name']}'과(와) 이름이 겹칩니다. 이름이나 다른 이름(별칭)을 바꿔 주세요.")


def save(session: Session, admin_id: int, values: dict, preset_id: str | None = None) -> dict:
    """Add a preset (no `preset_id`) or change one, built-in or added. Returns it as users now see it."""
    if preset_id is not None and exercise_presets.find(preset_id) is None:
        raise RecordNotFound("기본 종목을 찾을 수 없습니다.")
    data = definition(values)
    check_names(data, preset_id)
    preset_id = preset_id or "admin_" + secrets.token_hex(4)
    row = session.get(PresetOverride, preset_id) or PresetOverride(preset_id=preset_id, hidden=False)
    row.data = json.dumps(data, ensure_ascii=False)
    row.updated_by, row.updated_at = admin_id, utc_now()
    session.add(row)
    commit(session)
    return exercise_presets.find(preset_id)


def set_hidden(session: Session, admin_id: int, preset_id: str, hidden: bool) -> dict:
    preset = exercise_presets.find(preset_id)
    if preset is None:
        raise RecordNotFound("기본 종목을 찾을 수 없습니다.")
    if not hidden:
        check_names({key: preset.get(key, "") for key in ("name", "name_en")} | {"aliases": preset["aliases"]}, preset_id)
    row = session.get(PresetOverride, preset_id) or PresetOverride(preset_id=preset_id, data=None)
    row.hidden = hidden
    row.updated_by, row.updated_at = admin_id, utc_now()
    session.add(row)
    commit(session)
    return exercise_presets.find(preset_id)


def remove(session: Session, preset_id: str) -> str:
    """Undo the admin's changes to a built-in preset ("reset"), or delete a preset an admin added when no
    one's exercise uses it ("deleted")."""
    row = session.get(PresetOverride, preset_id)
    builtin = any(preset["id"] == preset_id for preset in exercise_presets.base()["presets"])
    if row is None:
        raise RecordNotFound("되돌리거나 지울 변경이 없습니다.")
    if not builtin and session.scalar(select(Exercise.id).where(Exercise.preset_id == preset_id).limit(1)):
        raise RecordConflict("이 종목을 쓰는 사용자가 있어 지울 수 없습니다. 대신 숨겨 주세요.")
    if builtin and row.data is None and not row.hidden:
        raise RecordNotFound("되돌릴 변경이 없습니다.")
    session.delete(row)
    commit(session)
    return "reset" if builtin else "deleted"
