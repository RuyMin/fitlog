"""Request and response shapes for the natural-language record assistant."""
import base64
import binascii
from typing import Annotated, Literal, Self

from pydantic import BaseModel, Field, model_validator

from app.schemas import BodyMetricInput, InputModel, MealInput, Name, SleepInput, WorkoutInput


class KeyInput(InputModel):
    api_key: Annotated[str, Field(min_length=20, max_length=300, pattern=r"^sk-ant-\S+$")]


MAX_IMAGE_BYTES = 5 * 1024 * 1024  # Anthropic's per-image limit
SIGNATURES = {"image/jpeg": (b"\xff\xd8\xff",), "image/png": (b"\x89PNG\r\n\x1a\n",), "image/webp": (b"RIFF",)}


class ImageInput(InputModel):
    """A photo for drafting only: sent to the model, never stored."""
    media_type: Literal["image/jpeg", "image/png", "image/webp"]
    data: Annotated[str, Field(min_length=16, max_length=7_200_000)]

    @model_validator(mode="after")
    def check_bytes(self) -> Self:
        try:
            raw = base64.b64decode(self.data, validate=True)
        except (binascii.Error, ValueError):
            raise ValueError("사진 데이터를 읽을 수 없습니다.") from None
        if len(raw) > MAX_IMAGE_BYTES:
            raise ValueError("사진은 5MB 이하여야 합니다.")
        if not raw.startswith(SIGNATURES[self.media_type]) or (self.media_type == "image/webp" and raw[8:12] != b"WEBP"):
            raise ValueError("사진 형식이 올바르지 않습니다.")
        return self


class DraftRequest(InputModel):
    text: Annotated[str, Field(max_length=4000)] = ""
    images: Annotated[list[ImageInput], Field(max_length=3)] = []
    timezone: Annotated[str, Field(max_length=64)] = "Asia/Seoul"

    @model_validator(mode="after")
    def require_content(self) -> Self:
        if not self.text and not self.images:
            raise ValueError("문장이나 사진을 하나 이상 입력해 주세요.")
        return self


class SetDraft(InputModel):
    exercise: Name
    set_number: Annotated[int, Field(gt=0, le=10000)]
    weight: Annotated[float, Field(ge=0, le=10000)] | None = None
    reps: Annotated[int, Field(ge=0, le=100000)] | None = None
    completed: bool = True
    duration_seconds: Annotated[int, Field(ge=0, le=86400)] | None = None
    distance_m: Annotated[float, Field(ge=0, le=1_000_000)] | None = None
    speed_kmh: Annotated[float, Field(ge=0, le=100)] | None = None
    incline_pct: Annotated[float, Field(ge=-30, le=60)] | None = None
    level: Annotated[float, Field(ge=0, le=100)] | None = None
    calories: Annotated[float, Field(ge=0, le=20000)] | None = None
    heart_rate: Annotated[int, Field(ge=20, le=250)] | None = None
    max_heart_rate: Annotated[int, Field(ge=20, le=250)] | None = None
    cadence: Annotated[int, Field(ge=0, le=300)] | None = None
    max_cadence: Annotated[int, Field(ge=0, le=300)] | None = None
    steps: Annotated[int, Field(ge=0, le=1_000_000)] | None = None
    elevation_gain_m: Annotated[float, Field(ge=0, le=10_000)] | None = None
    best_pace_seconds: Annotated[int, Field(ge=60, le=3600)] | None = None


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
