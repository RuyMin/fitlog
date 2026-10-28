from datetime import date, datetime, timezone
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, PlainSerializer, model_validator

from app.config import APP_VERSION
from app.services import exercise_presets

UTCDateTime = Annotated[datetime, PlainSerializer(
    lambda value: value.replace(tzinfo=timezone.utc).isoformat(), return_type=str
)]
Name = Annotated[str, Field(min_length=1, max_length=200)]
ShortText = Annotated[str, Field(max_length=100)]
Memo = Annotated[str, Field(max_length=5000)]


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    app: Literal["FitLog"] = "FitLog"
    version: str = APP_VERSION


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


class ExerciseInput(InputModel):
    name: Name
    category: ShortText | None = None
    body_part: ShortText | None = None
    preset_id: Annotated[str, Field(max_length=64)] | None = None

    @model_validator(mode="after")
    def known_preset(self) -> Self:
        if self.preset_id is not None and self.preset_id not in exercise_presets.ids():
            raise ValueError("알 수 없는 운동 프리셋입니다.")
        return self


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
    duration_seconds: Annotated[int, Field(ge=0, le=86400, strict=True)] | None = None
    distance_m: Annotated[float, Field(ge=0, le=1_000_000)] | None = None
    speed_kmh: Annotated[float, Field(ge=0, le=100)] | None = None
    incline_pct: Annotated[float, Field(ge=-30, le=60)] | None = None
    level: Annotated[float, Field(ge=0, le=100)] | None = None
    calories: Annotated[float, Field(ge=0, le=20000)] | None = None
    heart_rate: Annotated[int, Field(ge=20, le=250, strict=True)] | None = None
    max_heart_rate: Annotated[int, Field(ge=20, le=250, strict=True)] | None = None
    cadence: Annotated[int, Field(ge=0, le=300, strict=True)] | None = None
    max_cadence: Annotated[int, Field(ge=0, le=300, strict=True)] | None = None
    steps: Annotated[int, Field(ge=0, le=1_000_000, strict=True)] | None = None
    elevation_gain_m: Annotated[float, Field(ge=0, le=10_000)] | None = None
    best_pace_seconds: Annotated[int, Field(ge=60, le=3600, strict=True)] | None = None
    variant: Annotated[str, Field(min_length=1, max_length=40)] | None = None


class MergeInput(InputModel):
    preset_id: Annotated[str, Field(min_length=1, max_length=64)]
    variant: Annotated[str, Field(min_length=1, max_length=40)] | None = None


class VariantInput(InputModel):
    variant: Annotated[str, Field(min_length=1, max_length=40)] | None = None


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


class WeekDay(BaseModel):
    date: date
    workout: bool
    logged: bool


class WeightPoint(BaseModel):
    measured_at: UTCDateTime
    weight: float


class GoalProfileInput(InputModel):
    """내 목표: `auto` computes calories and macros from the body details and the latest weight; `manual` uses
    the four numbers. Sleep is set by hand in both (None: the default)."""
    mode: Literal["auto", "manual"] = "auto"
    sex: Literal["male", "female"] | None = None
    birth_year: Annotated[int, Field(strict=True)] | None = None
    height_cm: Annotated[float, Field(ge=100, le=250)] | None = None
    activity: Literal["sedentary", "light", "moderate", "active", "very_active"] = "light"
    aim: Literal["lose", "maintain", "gain"] = "maintain"
    calorie_kcal: Annotated[float, Field(ge=800, le=6000)] | None = None
    protein_g: Annotated[float, Field(ge=10, le=400)] | None = None
    carbohydrate_g: Annotated[float, Field(ge=0, le=1000)] | None = None
    fat_g: Annotated[float, Field(ge=0, le=400)] | None = None
    sleep_minutes: Annotated[int, Field(ge=180, le=720, strict=True)] | None = None

    @model_validator(mode="after")
    def complete(self) -> Self:
        if self.birth_year is not None and not 15 <= date.today().year - self.birth_year <= 100:
            raise ValueError("출생연도를 확인해 주세요. 만 15세~100세 기준으로 계산합니다.")
        if self.mode == "manual" and None in (self.calorie_kcal, self.protein_g, self.carbohydrate_g, self.fat_g):
            raise ValueError("직접 입력에서는 열량·단백질·탄수화물·지방을 모두 적어 주세요.")
        return self


class GoalValues(BaseModel):
    calorie_kcal: float
    protein_g: float
    carbohydrate_g: float
    fat_g: float
    sleep_minutes: float
    source: Literal["default", "auto", "manual"]


class GoalEstimate(BaseModel):
    age: int
    weight: float
    bmr: float
    activity_factor: float
    adjustment_kcal: float
    protein_g_per_kg: float
    calorie_kcal: float
    protein_g: float
    carbohydrate_g: float
    fat_g: float


class GoalsResponse(BaseModel):
    saved: bool
    profile: GoalProfileInput
    weight: float | None
    weight_measured_at: UTCDateTime | None
    estimate: GoalEstimate | None
    missing: list[str]
    goals: GoalValues
    defaults: GoalValues


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
    volume_kg: float | None
    workout_titles: list[str]
    calories: float | None
    carbohydrates_grams: float | None
    fat_grams: float | None
    calorie_goal_kcal: float
    carbohydrate_goal_grams: float
    fat_goal_grams: float
    sleep_goal_minutes: float
    goal_source: Literal["default", "auto", "manual"]
    main_sleep_start: UTCDateTime | None
    main_sleep_end: UTCDateTime | None
    week: list[WeekDay]
    weights: list[WeightPoint]
