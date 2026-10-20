"""Request and response shapes for the natural-language record assistant."""
from typing import Annotated

from pydantic import BaseModel, Field

from app.schemas import BodyMetricInput, InputModel, MealInput, Name, SleepInput, WorkoutInput


class KeyInput(InputModel):
    api_key: Annotated[str, Field(min_length=20, max_length=300, pattern=r"^sk-ant-\S+$")]


class DraftRequest(InputModel):
    text: Annotated[str, Field(min_length=1, max_length=4000)]
    timezone: Annotated[str, Field(max_length=64)] = "Asia/Seoul"


class SetDraft(InputModel):
    exercise: Name
    set_number: Annotated[int, Field(gt=0, le=10000)]
    weight: Annotated[float, Field(ge=0, le=10000)] | None = None
    reps: Annotated[int, Field(ge=0, le=100000)] | None = None
    completed: bool = True


class WorkoutDraft(WorkoutInput):
    sets: Annotated[list[SetDraft], Field(max_length=300)] = []


class CommitRequest(InputModel):
    """What the person confirmed after editing the drafts; validated like any manual entry."""
    meals: Annotated[list[MealInput], Field(max_length=50)] = []
    body_metrics: Annotated[list[BodyMetricInput], Field(max_length=50)] = []
    sleep: Annotated[list[SleepInput], Field(max_length=50)] = []
    workouts: Annotated[list[WorkoutDraft], Field(max_length=20)] = []


class StatusResponse(BaseModel):
    server_ready: bool
    consent: bool
    key_configured: bool
    key_hint: str | None
    can_manage_key: bool
    model: str
    daily_limit: int
    used_today: int
