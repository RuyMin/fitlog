"""Schema v10; all timestamp values follow the UTC-naive storage convention.

Explicit DDL for upgrades lives in app/migrations.py; tests keep the two equal.
"""
from datetime import date, datetime, timezone

from sqlalchemy import (
    LargeBinary, Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey, ForeignKeyConstraint, Index, Integer,
    JSON, String, Text, UniqueConstraint,
)
from sqlalchemy import text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


TRACKING_KINDS = ("work", "meal", "body", "sleep")


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
    # What the home summary shows, comma-separated from TRACKING_KINDS; None until the first-run screen is answered.
    tracking: Mapped[str | None] = mapped_column(String(40))


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


class GoalProfile(Base):
    """A user's daily goals (schema v8). `auto` computes calories and macros from the body details here and
    the latest recorded weight; `manual` uses the four numbers here. Sleep is always set by hand (NULL:
    the server default). Deleting the row returns the user to the server defaults."""
    __tablename__ = "goal_profiles"
    __table_args__ = (
        CheckConstraint("mode IN ('auto', 'manual')", name="ck_goal_mode"),
        CheckConstraint("sex IS NULL OR sex IN ('male', 'female')", name="ck_goal_sex"),
        CheckConstraint("birth_year IS NULL OR birth_year BETWEEN 1900 AND 2100", name="ck_goal_birth_year"),
        CheckConstraint("height_cm IS NULL OR height_cm BETWEEN 100 AND 250", name="ck_goal_height"),
        CheckConstraint("activity IN ('sedentary', 'light', 'moderate', 'active', 'very_active')", name="ck_goal_activity"),
        CheckConstraint("aim IN ('lose', 'maintain', 'gain')", name="ck_goal_aim"),
        CheckConstraint("calorie_kcal IS NULL OR calorie_kcal BETWEEN 800 AND 6000", name="ck_goal_calories"),
        CheckConstraint("protein_g IS NULL OR protein_g BETWEEN 10 AND 400", name="ck_goal_protein"),
        CheckConstraint("carbohydrate_g IS NULL OR carbohydrate_g BETWEEN 0 AND 1000", name="ck_goal_carbohydrate"),
        CheckConstraint("fat_g IS NULL OR fat_g BETWEEN 0 AND 400", name="ck_goal_fat"),
        CheckConstraint("mode = 'auto' OR (calorie_kcal IS NOT NULL AND protein_g IS NOT NULL AND carbohydrate_g IS NOT NULL AND fat_g IS NOT NULL)", name="ck_goal_manual"),
        CheckConstraint("sleep_minutes IS NULL OR sleep_minutes BETWEEN 180 AND 720", name="ck_goal_sleep"),
    )

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    mode: Mapped[str] = mapped_column(String(10), default="auto")
    sex: Mapped[str | None] = mapped_column(String(10))
    birth_year: Mapped[int | None] = mapped_column(Integer)
    height_cm: Mapped[float | None] = mapped_column(Float)
    activity: Mapped[str] = mapped_column(String(20), default="light")
    aim: Mapped[str] = mapped_column(String(10), default="maintain")
    calorie_kcal: Mapped[float | None] = mapped_column(Float)
    protein_g: Mapped[float | None] = mapped_column(Float)
    carbohydrate_g: Mapped[float | None] = mapped_column(Float)
    fat_g: Mapped[float | None] = mapped_column(Float)
    sleep_minutes: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now, onupdate=utc_now)


class PresetOverride(Base):
    """An admin's change to the built-in exercise list (schema v10). For a built-in preset `data` holds the
    edited fields (null keeps the original) and `hidden` takes it off the picker; a preset an admin added
    has its whole definition in `data`. The shipped file stays the base, so later releases still add to it."""
    __tablename__ = "preset_overrides"
    __table_args__ = (CheckConstraint("length(trim(preset_id)) > 0", name="ck_preset_override_id"),)

    preset_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    data: Mapped[str | None] = mapped_column(Text)
    hidden: Mapped[bool] = mapped_column(Boolean(create_constraint=True), default=False)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(default=utc_now, onupdate=utc_now)


class PerfEvent(Base):
    """Request timing for the operator's speed statistics (schema v7). Kept 14 days.

    Only technical facts: when, which route template (ids as {id}), status and durations.
    No record contents, query values or request bodies.
    """
    __tablename__ = "perf_events"
    __table_args__ = (
        CheckConstraint("source IN ('server', 'client', 'page')", name="ck_perf_source"),
        CheckConstraint("total_ms >= 0", name="ck_perf_total"),
        Index("ix_perf_events_at", "at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # server: one API request as the app handled it; client: the same request as the phone waited for it;
    # page: opening a screen (html_ms = page ready, total_ms = first data shown).
    source: Mapped[str] = mapped_column(String(10))
    page: Mapped[str | None] = mapped_column(String(60))
    route: Mapped[str] = mapped_column(String(160))
    method: Mapped[str | None] = mapped_column(String(8))
    status: Mapped[int | None] = mapped_column(Integer)
    total_ms: Mapped[float] = mapped_column(Float)
    server_ms: Mapped[float | None] = mapped_column(Float)
    html_ms: Mapped[float | None] = mapped_column(Float)
    cached: Mapped[bool | None] = mapped_column(Boolean(create_constraint=True))
    bytes: Mapped[int | None] = mapped_column(Integer)


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
    # The routine this session was started from (schema v15), so the next one in the rotation can be offered.
    routine_id: Mapped[int | None] = mapped_column(Integer)
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
        # One exercise per built-in preset for each user; custom exercises have no preset.
        Index("uq_exercise_user_preset", "user_id", "preset_id", unique=True, sqlite_where=text("preset_id IS NOT NULL")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str | None] = mapped_column(String(100))
    body_part: Mapped[str | None] = mapped_column(String(100))
    preset_id: Mapped[str | None] = mapped_column(String(64))
    # Muscles the user picked for an exercise not linked to a preset (schema v11); a preset brings its own.
    muscles: Mapped[list[str] | None] = mapped_column(JSON)
    # How an exercise without a preset is recorded (schema v13; the list's tracking ids). None: weight × reps.
    tracking: Mapped[str | None] = mapped_column(String(20))
    # Recorded one side at a time, left and right reps apart (schema v16). None: as the preset says (its "side").
    one_side: Mapped[bool | None] = mapped_column(Boolean(create_constraint=False))
    created_at: Mapped[datetime] = mapped_column(default=utc_now)


class Routine(Owned, Base):
    """A saved session plan (schema v15): exercises in order with how many sets each. Routines rotate in
    `position` order; the workouts page offers the one after the last routine done."""
    __tablename__ = "routines"
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="ck_routine_name"),
        Index("ix_routines_user", "user_id", "position"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    position: Mapped[int] = mapped_column(Integer, default=0)
    # [{"exercise_id": 3, "sets": 4}, …]; exercises are the user's own (checked when saved).
    items: Mapped[list[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(default=utc_now, onupdate=utc_now)


class WorkoutSet(Owned, SyncFields, Base):
    __tablename__ = "workout_sets"
    __table_args__ = (
        UniqueConstraint("workout_id", "exercise_id", "set_number", name="uq_set_number"),
        CheckConstraint("set_number > 0", name="ck_set_number"),
        CheckConstraint("weight IS NULL OR weight >= 0", name="ck_set_weight"),
        CheckConstraint("reps IS NULL OR reps >= 0", name="ck_set_reps"),
        # One-side exercises (schema v16): `reps` is the right side, this the left.
        CheckConstraint("left_reps IS NULL OR left_reps >= 0", name="ck_set_left_reps"),
        # Cardio and timed sets (schema v5); which ones a row uses depends on the exercise.
        CheckConstraint("duration_seconds IS NULL OR duration_seconds >= 0", name="ck_set_duration"),
        CheckConstraint("distance_m IS NULL OR distance_m >= 0", name="ck_set_distance"),
        CheckConstraint("speed_kmh IS NULL OR speed_kmh >= 0", name="ck_set_speed"),
        CheckConstraint("incline_pct IS NULL OR incline_pct BETWEEN -30 AND 60", name="ck_set_incline"),
        CheckConstraint("level IS NULL OR level >= 0", name="ck_set_level"),
        CheckConstraint("calories IS NULL OR calories >= 0", name="ck_set_calories"),
        CheckConstraint("heart_rate IS NULL OR heart_rate BETWEEN 20 AND 250", name="ck_set_heart_rate"),
        # Running details from a watch (schema v9).
        CheckConstraint("max_heart_rate IS NULL OR max_heart_rate BETWEEN 20 AND 250", name="ck_set_max_heart_rate"),
        CheckConstraint("cadence IS NULL OR cadence BETWEEN 0 AND 300", name="ck_set_cadence"),
        CheckConstraint("max_cadence IS NULL OR max_cadence BETWEEN 0 AND 300", name="ck_set_max_cadence"),
        CheckConstraint("steps IS NULL OR steps >= 0", name="ck_set_steps"),
        CheckConstraint("elevation_gain_m IS NULL OR elevation_gain_m >= 0", name="ck_set_elevation_gain"),
        CheckConstraint("best_pace_seconds IS NULL OR best_pace_seconds > 0", name="ck_set_best_pace"),
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
    left_reps: Mapped[int | None] = mapped_column(Integer)
    completed: Mapped[bool] = mapped_column(Boolean(create_constraint=True), default=False)
    memo: Mapped[str | None] = mapped_column(Text)
    workout: Mapped[Workout] = relationship(back_populates="sets", primaryjoin="Workout.id == foreign(WorkoutSet.workout_id)")
    exercise: Mapped[Exercise] = relationship(primaryjoin="Exercise.id == foreign(WorkoutSet.exercise_id)")
    rpe: Mapped[float | None] = mapped_column(Float)
    rir: Mapped[float | None] = mapped_column(Float)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    distance_m: Mapped[float | None] = mapped_column(Float)
    speed_kmh: Mapped[float | None] = mapped_column(Float)
    incline_pct: Mapped[float | None] = mapped_column(Float)
    level: Mapped[float | None] = mapped_column(Float)
    calories: Mapped[float | None] = mapped_column(Float)
    heart_rate: Mapped[int | None] = mapped_column(Integer)
    max_heart_rate: Mapped[int | None] = mapped_column(Integer)
    cadence: Mapped[int | None] = mapped_column(Integer)  # average steps per minute
    max_cadence: Mapped[int | None] = mapped_column(Integer)
    steps: Mapped[int | None] = mapped_column(Integer)
    elevation_gain_m: Mapped[float | None] = mapped_column(Float)
    best_pace_seconds: Mapped[int | None] = mapped_column(Integer)  # fastest pace, seconds per km
    # Grip, foot position or stance from the exercise's preset (schema v6); empty means the default.
    variant: Mapped[str | None] = mapped_column(String(40))


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
