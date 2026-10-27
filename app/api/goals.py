"""내 목표: per-user daily goals for the home rings, the meals screen and the sleep chart."""
from dataclasses import asdict
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser
from app.database import get_session
from app.models import GoalProfile
from app.schemas import DeleteResponse, GoalEstimate, GoalProfileInput, GoalsResponse, GoalValues
from app.services import goals

router = APIRouter(prefix="/api/me", tags=["goals"])
DB = Annotated[Session, Depends(get_session)]
FIELDS = list(GoalProfileInput.model_fields)


def describe(db: Session, user_id: int, profile: GoalProfile | None, saved: bool) -> GoalsResponse:
    latest = goals.latest_weight(db, user_id)
    weight = latest.weight if latest else None
    shown = profile or GoalProfile(mode="auto", activity="light", aim="maintain")
    found = goals.estimate(shown, weight, date.today())
    return GoalsResponse(
        saved=saved,
        profile=GoalProfileInput.model_construct(**{name: getattr(shown, name) for name in FIELDS}),
        weight=weight, weight_measured_at=latest.measured_at if latest else None,
        estimate=GoalEstimate(**asdict(found)) if found else None,
        missing=goals.missing_details(shown, weight),
        goals=GoalValues(**asdict(goals.resolve(profile, weight, date.today()))),
        defaults=GoalValues(**asdict(goals.default_goals())),
    )


@router.get("/goals", response_model=GoalsResponse)
def get_goals(db: DB, user: CurrentUser) -> GoalsResponse:
    profile = goals.get_profile(db, user.id)
    return describe(db, user.id, profile, profile is not None)


@router.put("/goals", response_model=GoalsResponse)
def save_goals(data: GoalProfileInput, db: DB, user: CurrentUser) -> GoalsResponse:
    return describe(db, user.id, goals.save_profile(db, user.id, data.model_dump()), True)


# The form's live result: the same answer as saving, without saving.
@router.post("/goals/preview", response_model=GoalsResponse)
def preview_goals(data: GoalProfileInput, db: DB, user: CurrentUser) -> GoalsResponse:
    return describe(db, user.id, GoalProfile(user_id=user.id, **data.model_dump()), False)


@router.delete("/goals", response_model=DeleteResponse)
def delete_goals(db: DB, user: CurrentUser) -> DeleteResponse:
    goals.delete_profile(db, user.id)
    return DeleteResponse()
