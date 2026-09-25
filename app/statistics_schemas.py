"""Public statistics response contracts, independent of chart rendering."""
from datetime import date

from pydantic import BaseModel

from app.schemas import UTCDateTime


class StatisticsSummary(BaseModel):
    workouts_count: int
    sets_count: int
    known_volume_sets: int
    volume_kg_reps: float | None
    weight_change_kg: float | None
    weight_days: int
    average_sleep_minutes: float | None
    sleep_days: int


class DailyStatistics(BaseModel):
    date: date
    workouts_count: int = 0
    sets_count: int = 0
    known_volume_sets: int = 0
    volume_kg_reps: float | None = None
    weight: float | None = None
    weight_measured_at: UTCDateTime | None = None
    sleep_minutes: int | None = None
    sleep_records_count: int = 0


class WeeklyStatistics(BaseModel):
    week_start: date
    period_start: date
    period_end: date
    workouts_count: int = 0
    sets_count: int = 0


class ExerciseVolumePoint(BaseModel):
    date: date
    sets_count: int = 0
    known_volume_sets: int = 0
    volume_kg_reps: float | None = None


class ExerciseStatistics(BaseModel):
    exercise_id: int
    name: str
    sets_count: int
    known_volume_sets: int
    max_weight: float | None
    volume_kg_reps: float | None
    daily_volume: list[ExerciseVolumePoint]


class StatisticsResponse(BaseModel):
    date_from: date
    date_to: date
    timezone: str
    completed_only: bool
    summary: StatisticsSummary
    daily: list[DailyStatistics]
    weekly: list[WeeklyStatistics]
    exercises: list[ExerciseStatistics]
