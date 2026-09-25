"""Transport-neutral row contracts shared by Sheets and local CSV import."""
from typing import Annotated
from pydantic import AwareDatetime, Field, HttpUrl, model_validator, field_validator
from app.schemas import InputModel, WorkoutInput, MealInput, BodyMetricInput, SleepInput, Memo, Name


class Identity(InputModel):
    external_id: Annotated[str, Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_.:-]+$")]
    updated_at: AwareDatetime

    @field_validator("*", mode="before")
    @classmethod
    def explicit_timestamps(cls, value, info):
        import re
        if value is None:
            return value
        if info.field_name in {"updated_at", "started_at", "ended_at", "eaten_at", "measured_at", "sleep_start", "sleep_end"}:
            if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", value):
                raise ValueError("ISO timestamp with explicit timezone required")
        if info.field_name == "workout_date" and (not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)):
            raise ValueError("ISO date required")
        if info.field_name in {"weight", "reps", "set_number", "rpe", "rir", "calories", "protein", "carbohydrates", "fat", "body_fat", "skeletal_muscle", "duration_minutes"} and isinstance(value, bool):
            raise ValueError("boolean is not a number")
        return value


class WorkoutRow(WorkoutInput, Identity):
    pass


class SetRow(Identity):
    workout_external_id: Annotated[str, Field(min_length=1, max_length=200)]
    exercise: Name
    set_number: Annotated[int, Field(gt=0, le=10000)]
    weight: Annotated[float, Field(ge=0, le=10000)] | None = None
    reps: Annotated[int, Field(ge=0, le=100000)] | None = None
    completed: bool
    rpe: Annotated[float, Field(ge=0, le=10)] | None = None
    rir: Annotated[float, Field(ge=0, le=100)] | None = None
    memo: Memo | None = None


class MealRow(MealInput, Identity):
    image_url: HttpUrl | None = None


class BodyRow(BodyMetricInput, Identity):
    pass


class SleepRow(SleepInput, Identity):
    duration_minutes: Annotated[int, Field(ge=1)] | None = None

    @model_validator(mode="after")
    def duration_matches(self):
        from datetime import timezone
        duration = int((self.sleep_end.astimezone(timezone.utc) - self.sleep_start.astimezone(timezone.utc)).total_seconds() // 60)
        if self.duration_minutes is not None and self.duration_minutes != duration:
            raise ValueError("duration_minutes must match start/end")
        self.duration_minutes = duration
        return self


ROW_TYPES = {"workouts": WorkoutRow, "workout_sets": SetRow, "meals": MealRow, "body_metrics": BodyRow, "sleep": SleepRow}
COLUMNS = {
    "workouts": "external_id workout_date title body_part started_at ended_at memo updated_at".split(),
    "workout_sets": "external_id workout_external_id exercise set_number weight reps completed rpe rir memo updated_at".split(),
    "meals": "external_id eaten_at meal_type name calories protein carbohydrates fat memo image_url updated_at".split(),
    "body_metrics": "external_id measured_at weight body_fat skeletal_muscle memo updated_at".split(),
    "sleep": "external_id sleep_start sleep_end duration_minutes sleep_type memo updated_at".split(),
}
