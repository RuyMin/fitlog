"""Admin page › 기본 종목: change the built-in exercise list every user picks from."""
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import Field
from sqlalchemy.orm import Session

from app.api.deps import AdminUser
from app.database import get_session
from app.schemas import InputModel
from app.services import exercise_presets, preset_admin

router = APIRouter(prefix="/api/admin/presets", tags=["exercise presets (admin)"])
DB = Annotated[Session, Depends(get_session)]
Label = Annotated[str, Field(min_length=1, max_length=100)]


class PresetInput(InputModel):
    name: Label
    name_en: Annotated[str, Field(max_length=100)] = ""
    aliases: Annotated[list[Label], Field(max_length=20)] = []
    body_part: Label
    equipment: Label
    muscles: Annotated[list[Label], Field(min_length=1, max_length=12)]
    kind: Literal["compound", "isolation", "cardio"]
    tracking: Annotated[str, Field(min_length=1, max_length=40)]


class HiddenInput(InputModel):
    hidden: bool


@router.get("")
def list_presets(admin: AdminUser) -> dict:
    """Every preset, hidden ones included, and the choices a preset can take."""
    return {"presets": exercise_presets.catalog()["presets"], "options": preset_admin.options()}


@router.post("", status_code=201)
def add(data: PresetInput, db: DB, admin: AdminUser) -> dict:
    return preset_admin.save(db, admin.id, data.model_dump())


@router.put("/{preset_id}")
def change(preset_id: str, data: PresetInput, db: DB, admin: AdminUser) -> dict:
    return preset_admin.save(db, admin.id, data.model_dump(), preset_id)


@router.put("/{preset_id}/hidden")
def hide(preset_id: str, data: HiddenInput, db: DB, admin: AdminUser) -> dict:
    return preset_admin.set_hidden(db, admin.id, preset_id, data.hidden)


@router.delete("/{preset_id}")
def undo(preset_id: str, db: DB, admin: AdminUser) -> dict:
    """A built-in preset goes back to the shipped version; an added one is deleted."""
    return {"result": preset_admin.remove(db, preset_id), "preset": exercise_presets.find(preset_id)}
