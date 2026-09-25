"""Initial schema; all timestamp values follow the UTC-naive storage convention."""
from datetime import date, datetime, timezone

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Workout(Base):
    __tablename__ = "workouts"
    __table_args__ = (
        CheckConstraint("length(trim(title)) > 0", name="ck_workout_title"),
        CheckConstraint("ended_at IS NULL OR (started_at IS NOT NULL AND ended_at >= started_at)", name="ck_workout_time"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workout_date: Mapped[date] = mapped_column(Date, index=True)
    title: Mapped[str] = mapped_column(String(200))
    body_part: Mapped[str | None] = mapped_column(String(100))
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime)
    memo: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now, onupdate=utc_now)
    sets: Mapped[list["WorkoutSet"]] = relationship(
        back_populates="workout", cascade="all, delete-orphan", passive_deletes=True
    )


class Exercise(Base):
    __tablename__ = "exercises"
    __table_args__ = (CheckConstraint("length(trim(name)) > 0", name="ck_exercise_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    category: Mapped[str | None] = mapped_column(String(100))
    body_part: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(default=utc_now)


class WorkoutSet(Base):
    __tablename__ = "workout_sets"
    __table_args__ = (
        UniqueConstraint("workout_id", "exercise_id", "set_number", name="uq_set_number"),
        CheckConstraint("set_number > 0", name="ck_set_number"),
        CheckConstraint("weight IS NULL OR weight >= 0", name="ck_set_weight"),
        CheckConstraint("reps IS NULL OR reps >= 0", name="ck_set_reps"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workout_id: Mapped[int] = mapped_column(ForeignKey("workouts.id", ondelete="CASCADE"), index=True)
    exercise_id: Mapped[int] = mapped_column(ForeignKey("exercises.id", ondelete="RESTRICT"), index=True)
    set_number: Mapped[int] = mapped_column(Integer)
    weight: Mapped[float | None] = mapped_column(Float)
    reps: Mapped[int | None] = mapped_column(Integer)
    completed: Mapped[bool] = mapped_column(Boolean(create_constraint=True), default=False)
    memo: Mapped[str | None] = mapped_column(Text)
    workout: Mapped[Workout] = relationship(back_populates="sets")
    # RPE, RIR, duration and distance will be added via a schema migration.


class Meal(Base):
    __tablename__ = "meals"
    __table_args__ = tuple(
        CheckConstraint(f"{field} IS NULL OR {field} >= 0", name=f"ck_meal_{field}")
        for field in ("calories", "protein", "carbohydrates", "fat")
    ) + (CheckConstraint("length(trim(name)) > 0", name="ck_meal_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    eaten_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    meal_type: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(200))
    calories: Mapped[float | None] = mapped_column(Float)
    protein: Mapped[float | None] = mapped_column(Float)
    carbohydrates: Mapped[float | None] = mapped_column(Float)
    fat: Mapped[float | None] = mapped_column(Float)
    memo: Mapped[str | None] = mapped_column(Text)
    image_path: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(default=utc_now)


class BodyMetric(Base):
    __tablename__ = "body_metrics"
    __table_args__ = (
        CheckConstraint("weight IS NULL OR weight > 0", name="ck_body_weight"),
        CheckConstraint("body_fat IS NULL OR body_fat BETWEEN 0 AND 100", name="ck_body_fat"),
        CheckConstraint("skeletal_muscle IS NULL OR skeletal_muscle >= 0", name="ck_body_muscle"),
        CheckConstraint("weight IS NOT NULL OR body_fat IS NOT NULL OR skeletal_muscle IS NOT NULL", name="ck_body_value"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    measured_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    weight: Mapped[float | None] = mapped_column(Float)
    body_fat: Mapped[float | None] = mapped_column(Float)
    skeletal_muscle: Mapped[float | None] = mapped_column(Float)
    memo: Mapped[str | None] = mapped_column(Text)


class SleepRecord(Base):
    __tablename__ = "sleep_records"
    __table_args__ = (
        CheckConstraint("sleep_end > sleep_start", name="ck_sleep_time"),
        CheckConstraint("duration_minutes >= 0", name="ck_sleep_duration"),
        CheckConstraint("sleep_type IN ('main', 'nap')", name="ck_sleep_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sleep_start: Mapped[datetime] = mapped_column(DateTime, index=True)
    sleep_end: Mapped[datetime] = mapped_column(DateTime)
    duration_minutes: Mapped[int] = mapped_column(Integer)
    sleep_type: Mapped[str] = mapped_column(String(20), default="main")
    memo: Mapped[str | None] = mapped_column(Text)
