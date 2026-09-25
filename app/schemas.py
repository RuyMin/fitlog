from datetime import date, datetime, timezone
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, PlainSerializer, model_validator

UTCDateTime = Annotated[datetime, PlainSerializer(
    lambda value: value.replace(tzinfo=timezone.utc).isoformat(), return_type=str
)]
Name = Annotated[str, Field(min_length=1, max_length=200)]
ShortText = Annotated[str, Field(max_length=100)]
Memo = Annotated[str, Field(max_length=5000)]


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    app: Literal["FitLog"] = "FitLog"


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


class ExerciseInput(InputModel):
    name: Name
    category: ShortText | None = None
    body_part: ShortText | None = None


class ExerciseResponse(ExerciseInput):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: UTCDateTime


class WorkoutInput(InputModel):
    workout_date: date
    title: Name
    body_part: ShortText | None = None
    started_at: AwareDatetime | None = None
    ended_at: AwareDatetime | None = None
    memo: Memo | None = None

    @model_validator(mode="after")
    def validate_times(self) -> Self:
        if self.ended_at is not None and (
            self.started_at is None or self.ended_at < self.started_at
        ):
            raise ValueError("종료 시각은 시작 시각 이후여야 합니다.")
        return self


class SetInput(InputModel):
    exercise_id: Annotated[int, Field(gt=0, strict=True)]
    set_number: Annotated[int, Field(gt=0, le=10000, strict=True)]
    weight: Annotated[float, Field(ge=0, le=10000)] | None = None
    reps: Annotated[int, Field(ge=0, le=100000, strict=True)] | None = None
    completed: bool = False
    memo: Memo | None = None


class SetResponse(SetInput):
    model_config = ConfigDict(from_attributes=True)
    id: int
    workout_id: int
    exercise: ExerciseResponse
    rpe: float | None = None
    rir: float | None = None


class WorkoutResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    workout_date: date
    title: str
    body_part: str | None
    started_at: UTCDateTime | None
    ended_at: UTCDateTime | None
    memo: str | None
    created_at: UTCDateTime
    updated_at: UTCDateTime
    sets: list[SetResponse]


class DeleteResponse(BaseModel):
    status: Literal["deleted"] = "deleted"


MealType = Literal["breakfast", "lunch", "dinner", "snack", "other"]
Nutrition = Annotated[float, Field(ge=0, le=100000)]


class MealInput(InputModel):
    eaten_at: AwareDatetime
    meal_type: MealType = "other"
    name: Name
    calories: Nutrition | None = None
    protein: Nutrition | None = None
    carbohydrates: Nutrition | None = None
    fat: Nutrition | None = None
    memo: Memo | None = None


class MealResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    eaten_at: UTCDateTime
    meal_type: str
    name: str
    calories: float | None
    protein: float | None
    carbohydrates: float | None
    fat: float | None
    memo: str | None
    image_path: str | None
    image_url: str | None = None
    created_at: UTCDateTime


class BodyMetricInput(InputModel):
    measured_at: AwareDatetime
    weight: Annotated[float, Field(gt=0, le=1000)] | None = None
    body_fat: Annotated[float, Field(ge=0, le=100)] | None = None
    skeletal_muscle: Annotated[float, Field(ge=0, le=1000)] | None = None
    memo: Memo | None = None

    @model_validator(mode="after")
    def require_measurement(self) -> Self:
        if self.weight is None and self.body_fat is None and self.skeletal_muscle is None:
            raise ValueError("체중·체지방률·골격근량 중 하나 이상을 입력해 주세요.")
        return self


class BodyMetricResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    measured_at: UTCDateTime
    weight: float | None
    body_fat: float | None
    skeletal_muscle: float | None
    memo: str | None


class SleepInput(InputModel):
    sleep_start: AwareDatetime
    sleep_end: AwareDatetime
    sleep_type: Literal["main", "nap"] = "main"
    memo: Memo | None = None

    @model_validator(mode="after")
    def validate_duration(self) -> Self:
        duration = self.sleep_end.astimezone(timezone.utc) - self.sleep_start.astimezone(timezone.utc)
        if duration.total_seconds() < 60:
            raise ValueError("종료는 시작보다 최소 1분 이후여야 합니다.")
        return self


class SleepResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    sleep_start: UTCDateTime
    sleep_end: UTCDateTime
    duration_minutes: int
    sleep_type: str
    memo: str | None


class DashboardResponse(BaseModel):
    date: date
    timezone: str
    workouts_count: int
    total_sets: int
    completed_sets: int
    latest_weight: BodyMetricResponse | None
    meals_count: int
    protein_known_count: int
    protein_grams: float | None
    protein_goal_grams: float
    sleep_records_count: int
    sleep_minutes: int | None
