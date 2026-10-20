"""Schema v3; all timestamp values follow the UTC-naive storage convention.

Explicit DDL for upgrades lives in app/migrations.py; tests keep the two equal.
"""
from datetime import date, datetime, timezone

from sqlalchemy import (
    LargeBinary, Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey, ForeignKeyConstraint, Index, Integer,
    String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    """Identity is the Google `sub`; only the owner row may wait unbound (see migrations v3)."""
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("length(trim(email)) > 0", name="ck_user_email"),
        CheckConstraint("role IN ('admin', 'member')", name="ck_user_role"),
        CheckConstraint("status IN ('active', 'disabled')", name="ck_user_status"),
        CheckConstraint("google_sub IS NOT NULL OR role = 'admin'", name="ck_user_identity"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    google_sub: Mapped[str | None] = mapped_column(String(255), unique=True)
    email: Mapped[str] = mapped_column(String(320))
    display_name: Mapped[str | None] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(10), default="member", server_default="member")
    status: Mapped[str] = mapped_column(String(10), default="active", server_default="active")
    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)


class AuthSession(Base):
    """Server-side login session. The cookie holds the token; only its SHA-256 is stored."""
    __tablename__ = "auth_sessions"
    __table_args__ = (CheckConstraint("expires_at > created_at", name="ck_session_expiry"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    last_seen_at: Mapped[datetime] = mapped_column(default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime)


class Invite(Base):
    """One-time link that lets a new Google account join. Only the token hash is stored."""
    __tablename__ = "invites"
    __table_args__ = (
        CheckConstraint("expires_at > created_at", name="ck_invite_expiry"),
        CheckConstraint("(used_at IS NULL) = (used_by IS NULL)", name="ck_invite_use"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    note: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[datetime | None] = mapped_column(DateTime)
    used_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class OAuthAttempt(Base):
    """Single-use Google login attempt (state, PKCE verifier, nonce); expires in minutes."""
    __tablename__ = "oauth_attempts"

    state_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    code_verifier: Mapped[str] = mapped_column(String(128))
    nonce: Mapped[str] = mapped_column(String(64))
    invite_id: Mapped[int | None] = mapped_column(ForeignKey("invites.id", ondelete="CASCADE"))
    next_path: Mapped[str | None] = mapped_column(String(200))
    consent_service: Mapped[bool] = mapped_column(Boolean(create_constraint=True), default=False)
    consent_ai: Mapped[bool] = mapped_column(Boolean(create_constraint=True), default=False)
    created_at: Mapped[datetime] = mapped_column(default=utc_now)


class Consent(Base):
    """What a user agreed to, which notice version, and when; withdrawal keeps the row."""
    __tablename__ = "consents"
    __table_args__ = (
        CheckConstraint("kind IN ('service', 'ai_transfer')", name="ck_consent_kind"),
        CheckConstraint("withdrawn_at IS NULL OR withdrawn_at >= granted_at", name="ck_consent_withdrawn"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    version: Mapped[str] = mapped_column(String(20))
    granted_at: Mapped[datetime] = mapped_column(default=utc_now)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime)


class AiCredential(Base):
    """The operator's shared Anthropic API key (one row, saved by an admin), encrypted with the server secret; never returned."""
    __tablename__ = "ai_credentials"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    hint: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(default=utc_now)


class AiUsage(Base):
    """Assistant requests per user per UTC day, counted before each call."""
    __tablename__ = "ai_usage"
    __table_args__ = (CheckConstraint("count >= 0", name="ck_ai_usage_count"),)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)


class Owned:
    """Every user-owned row. Services filter on it and answer 404 for other owners."""
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


def source_index(table: str) -> Index:
    return Index(f"uq_{table}_source_external", "user_id", "source", "external_id", unique=True)


class SyncFields:
    external_id: Mapped[str | None] = mapped_column(String(200))
    source: Mapped[str] = mapped_column(String(30), default="local", server_default="local")
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime)


class Workout(Owned, SyncFields, Base):
    __tablename__ = "workouts"
    __table_args__ = (
        CheckConstraint("length(trim(title)) > 0", name="ck_workout_title"),
        CheckConstraint("ended_at IS NULL OR (started_at IS NOT NULL AND ended_at >= started_at)", name="ck_workout_time"),
        UniqueConstraint("id", "user_id", name="uq_workout_owner"),
        Index("ix_workouts_user_date", "user_id", "workout_date"),
        source_index("workouts"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workout_date: Mapped[date] = mapped_column(Date)
    title: Mapped[str] = mapped_column(String(200))
    body_part: Mapped[str | None] = mapped_column(String(100))
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime)
    memo: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now, onupdate=utc_now)
    # Joined on id only: services set user_id and the composite FK enforces it.
    sets: Mapped[list["WorkoutSet"]] = relationship(
        back_populates="workout", cascade="all, delete-orphan", passive_deletes=True,
        primaryjoin="Workout.id == foreign(WorkoutSet.workout_id)",
        order_by="WorkoutSet.exercise_id, WorkoutSet.set_number, WorkoutSet.id"
    )


class Exercise(Owned, Base):
    __tablename__ = "exercises"
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="ck_exercise_name"),
        UniqueConstraint("user_id", "name", name="uq_exercise_user_name"),
        UniqueConstraint("id", "user_id", name="uq_exercise_owner"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str | None] = mapped_column(String(100))
    body_part: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(default=utc_now)


class WorkoutSet(Owned, SyncFields, Base):
    __tablename__ = "workout_sets"
    __table_args__ = (
        UniqueConstraint("workout_id", "exercise_id", "set_number", name="uq_set_number"),
        CheckConstraint("set_number > 0", name="ck_set_number"),
        CheckConstraint("weight IS NULL OR weight >= 0", name="ck_set_weight"),
        CheckConstraint("reps IS NULL OR reps >= 0", name="ck_set_reps"),
        # A set may only reference the same owner's workout and exercise.
        ForeignKeyConstraint(["workout_id", "user_id"], ["workouts.id", "workouts.user_id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["exercise_id", "user_id"], ["exercises.id", "exercises.user_id"], ondelete="RESTRICT"),
        source_index("workout_sets"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workout_id: Mapped[int] = mapped_column(index=True)
    exercise_id: Mapped[int] = mapped_column(index=True)
    set_number: Mapped[int] = mapped_column(Integer)
    weight: Mapped[float | None] = mapped_column(Float)
    reps: Mapped[int | None] = mapped_column(Integer)
    completed: Mapped[bool] = mapped_column(Boolean(create_constraint=True), default=False)
    memo: Mapped[str | None] = mapped_column(Text)
    workout: Mapped[Workout] = relationship(back_populates="sets", primaryjoin="Workout.id == foreign(WorkoutSet.workout_id)")
    exercise: Mapped[Exercise] = relationship(primaryjoin="Exercise.id == foreign(WorkoutSet.exercise_id)")
    rpe: Mapped[float | None] = mapped_column(Float)
    rir: Mapped[float | None] = mapped_column(Float)


class Meal(Owned, SyncFields, Base):
    __tablename__ = "meals"
    __table_args__ = tuple(
        CheckConstraint(f"{field} IS NULL OR {field} >= 0", name=f"ck_meal_{field}")
        for field in ("calories", "protein", "carbohydrates", "fat")
    ) + (
        CheckConstraint("length(trim(name)) > 0", name="ck_meal_name"),
        Index("ix_meals_user_eaten_at", "user_id", "eaten_at"),
        source_index("meals"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    eaten_at: Mapped[datetime] = mapped_column(DateTime)
    meal_type: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(200))
    calories: Mapped[float | None] = mapped_column(Float)
    protein: Mapped[float | None] = mapped_column(Float)
    carbohydrates: Mapped[float | None] = mapped_column(Float)
    fat: Mapped[float | None] = mapped_column(Float)
    memo: Mapped[str | None] = mapped_column(Text)
    image_path: Mapped[str | None] = mapped_column(String(500))
    image_url: Mapped[str | None] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(default=utc_now)


class BodyMetric(Owned, SyncFields, Base):
    __tablename__ = "body_metrics"
    __table_args__ = (
        CheckConstraint("weight IS NULL OR weight > 0", name="ck_body_weight"),
        CheckConstraint("body_fat IS NULL OR body_fat BETWEEN 0 AND 100", name="ck_body_fat"),
        CheckConstraint("skeletal_muscle IS NULL OR skeletal_muscle >= 0", name="ck_body_muscle"),
        CheckConstraint("weight IS NOT NULL OR body_fat IS NOT NULL OR skeletal_muscle IS NOT NULL", name="ck_body_value"),
        Index("ix_body_metrics_user_measured_at", "user_id", "measured_at"),
        source_index("body_metrics"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    measured_at: Mapped[datetime] = mapped_column(DateTime)
    weight: Mapped[float | None] = mapped_column(Float)
    body_fat: Mapped[float | None] = mapped_column(Float)
    skeletal_muscle: Mapped[float | None] = mapped_column(Float)
    memo: Mapped[str | None] = mapped_column(Text)


class SleepRecord(Owned, SyncFields, Base):
    __tablename__ = "sleep_records"
    __table_args__ = (
        CheckConstraint("sleep_end > sleep_start", name="ck_sleep_time"),
        CheckConstraint("duration_minutes >= 0", name="ck_sleep_duration"),
        CheckConstraint("sleep_type IN ('main', 'nap')", name="ck_sleep_type"),
        Index("ix_sleep_records_user_start", "user_id", "sleep_start"),
        Index("ix_sleep_records_user_end", "user_id", "sleep_end"),
        source_index("sleep_records"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sleep_start: Mapped[datetime] = mapped_column(DateTime)
    sleep_end: Mapped[datetime] = mapped_column(DateTime)
    duration_minutes: Mapped[int] = mapped_column(Integer)
    sleep_type: Mapped[str] = mapped_column(String(20), default="main")
    memo: Mapped[str | None] = mapped_column(Text)


class SyncState(Owned, Base):
    __tablename__ = "sync_state"
    __table_args__ = (UniqueConstraint("user_id", name="uq_sync_state_user"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    spreadsheet_id: Mapped[str | None] = mapped_column(String(200))
    spreadsheet_title: Mapped[str | None] = mapped_column(String(300))
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_sync_status: Mapped[str | None] = mapped_column(String(30))
    last_sync_error: Mapped[str | None] = mapped_column(Text)
    last_result: Mapped[str | None] = mapped_column(Text)


class ImportArchive(Owned, Base):
    """Immutable source workbook plus all cell values; never served as static files."""
    __tablename__ = "import_archives"
    __table_args__ = (UniqueConstraint("user_id", "sha256", name="uq_archive_user_sha256"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64))
    filename: Mapped[str] = mapped_column(String(255))
    original: Mapped[bytes] = mapped_column(LargeBinary)
    payload: Mapped[str] = mapped_column(Text)
    report: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utc_now)


class ExcelPreview(Owned, Base):
    """Expiring draft; applied previews retain the exact before/after audit trail."""
    __tablename__ = "excel_previews"
    __table_args__ = (Index("ix_excel_previews_user_created", "user_id", "created_at"),)
    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload: Mapped[str] = mapped_column(Text)
    original: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    result: Mapped[str | None] = mapped_column(Text)
