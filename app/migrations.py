"""Explicit, ordered SQLite migrations. Back up before upgrading an existing DB.

Each step upgrades exactly one version in one transaction and records
PRAGMA user_version inside that transaction. A brand-new database skips the
steps: create_all builds the current schema and finish_migration stamps it.
"""
import os
import re
import sqlite3
from collections.abc import Callable
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import Connection, Engine

SCHEMA_VERSION = 4
TABLES = ("workouts", "workout_sets", "meals", "body_metrics", "sleep_records")


def migrate(engine: Engine, path: Path) -> None:
    with engine.connect() as c:
        version = c.exec_driver_sql("PRAGMA user_version").scalar_one()
        old = c.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table' AND name='workouts'").first()
    if version > SCHEMA_VERSION:
        raise RuntimeError("Database schema is newer than this application")
    if version == SCHEMA_VERSION or not old:
        return
    backup(path, SCHEMA_VERSION)
    # Version 1 never existed: pre-sync databases report 0 and start at step 2.
    for target in range(max(version, 1) + 1, SCHEMA_VERSION + 1):
        STEPS[target](engine)


def backup(path: Path, target: int) -> Path:
    directory = path.parent / "backups"
    directory.mkdir(exist_ok=True)
    file = directory / (f"before-v{target}-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f") + ".db")
    with closing(sqlite3.connect(path)) as source, closing(sqlite3.connect(file)) as dest:
        source.backup(dest)
        if dest.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("Backup integrity check failed; migration cancelled")
    return file


def migrate_v2(engine: Engine) -> None:
    """Additive sync columns and per-source external IDs."""
    with engine.connect() as c:
        c.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            for table in TABLES:
                cols = {r[1] for r in c.exec_driver_sql(f"PRAGMA table_info({table})")}
                if not cols:
                    continue
                additions = {"external_id": "VARCHAR(200)", "source": "VARCHAR(30) NOT NULL DEFAULT 'local'", "source_updated_at": "DATETIME"}
                if table == "workout_sets":
                    additions.update(rpe="FLOAT", rir="FLOAT")
                if table == "meals":
                    additions["image_url"] = "VARCHAR(2000)"
                for name, sql_type in additions.items():
                    if name not in cols:
                        c.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}")
                c.exec_driver_sql(f"CREATE UNIQUE INDEX IF NOT EXISTS uq_{table}_source_external ON {table}(source, external_id)")
            c.exec_driver_sql("PRAGMA user_version=2")
            c.commit()
        except Exception:
            c.rollback()
            raise


# v3 rebuilds every user-owned table with a NOT NULL owner, so SQLite needs the
# create-copy-drop-rename procedure. Order is parent before child: workout_sets
# references the rebuilt workouts/exercises through composite (id, user_id) keys,
# which lets the database itself reject a set attached to another user's data.
V3_USERS = """
CREATE TABLE users (
	id INTEGER NOT NULL,
	google_sub VARCHAR(255),
	email VARCHAR(320) NOT NULL,
	display_name VARCHAR(100),
	role VARCHAR(10) DEFAULT 'member' NOT NULL,
	status VARCHAR(10) DEFAULT 'active' NOT NULL,
	created_at DATETIME NOT NULL,
	last_login_at DATETIME,
	PRIMARY KEY (id),
	CONSTRAINT ck_user_email CHECK (length(trim(email)) > 0),
	CONSTRAINT ck_user_role CHECK (role IN ('admin', 'member')),
	CONSTRAINT ck_user_status CHECK (status IN ('active', 'disabled')),
	CONSTRAINT ck_user_identity CHECK (google_sub IS NOT NULL OR role = 'admin'),
	UNIQUE (google_sub)
)"""

V3_TABLES: dict[str, tuple[str, tuple[str, ...]]] = {
    "exercises": ("""
CREATE TABLE exercises__v3 (
	id INTEGER NOT NULL,
	user_id INTEGER NOT NULL,
	name VARCHAR(200) NOT NULL,
	category VARCHAR(100),
	body_part VARCHAR(100),
	created_at DATETIME NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT ck_exercise_name CHECK (length(trim(name)) > 0),
	CONSTRAINT uq_exercise_user_name UNIQUE (user_id, name),
	CONSTRAINT uq_exercise_owner UNIQUE (id, user_id),
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE RESTRICT
)""", ()),
    "workouts": ("""
CREATE TABLE workouts__v3 (
	id INTEGER NOT NULL,
	user_id INTEGER NOT NULL,
	workout_date DATE NOT NULL,
	title VARCHAR(200) NOT NULL,
	body_part VARCHAR(100),
	started_at DATETIME,
	ended_at DATETIME,
	memo TEXT,
	created_at DATETIME NOT NULL,
	updated_at DATETIME NOT NULL,
	external_id VARCHAR(200),
	source VARCHAR(30) DEFAULT 'local' NOT NULL,
	source_updated_at DATETIME,
	PRIMARY KEY (id),
	CONSTRAINT ck_workout_title CHECK (length(trim(title)) > 0),
	CONSTRAINT ck_workout_time CHECK (ended_at IS NULL OR (started_at IS NOT NULL AND ended_at >= started_at)),
	CONSTRAINT uq_workout_owner UNIQUE (id, user_id),
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE RESTRICT
)""", (
        "CREATE INDEX ix_workouts_user_date ON workouts (user_id, workout_date)",
        "CREATE UNIQUE INDEX uq_workouts_source_external ON workouts (user_id, source, external_id)",
    )),
    "workout_sets": ("""
CREATE TABLE workout_sets__v3 (
	id INTEGER NOT NULL,
	user_id INTEGER NOT NULL,
	workout_id INTEGER NOT NULL,
	exercise_id INTEGER NOT NULL,
	set_number INTEGER NOT NULL,
	weight FLOAT,
	reps INTEGER,
	completed BOOLEAN NOT NULL,
	memo TEXT,
	rpe FLOAT,
	rir FLOAT,
	external_id VARCHAR(200),
	source VARCHAR(30) DEFAULT 'local' NOT NULL,
	source_updated_at DATETIME,
	PRIMARY KEY (id),
	CONSTRAINT uq_set_number UNIQUE (workout_id, exercise_id, set_number),
	CONSTRAINT ck_set_number CHECK (set_number > 0),
	CONSTRAINT ck_set_weight CHECK (weight IS NULL OR weight >= 0),
	CONSTRAINT ck_set_reps CHECK (reps IS NULL OR reps >= 0),
	CHECK (completed IN (0, 1)),
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE RESTRICT,
	FOREIGN KEY(workout_id, user_id) REFERENCES workouts (id, user_id) ON DELETE CASCADE,
	FOREIGN KEY(exercise_id, user_id) REFERENCES exercises (id, user_id) ON DELETE RESTRICT
)""", (
        "CREATE INDEX ix_workout_sets_workout_id ON workout_sets (workout_id)",
        "CREATE INDEX ix_workout_sets_exercise_id ON workout_sets (exercise_id)",
        "CREATE UNIQUE INDEX uq_workout_sets_source_external ON workout_sets (user_id, source, external_id)",
    )),
    "meals": ("""
CREATE TABLE meals__v3 (
	id INTEGER NOT NULL,
	user_id INTEGER NOT NULL,
	eaten_at DATETIME NOT NULL,
	meal_type VARCHAR(50) NOT NULL,
	name VARCHAR(200) NOT NULL,
	calories FLOAT,
	protein FLOAT,
	carbohydrates FLOAT,
	fat FLOAT,
	memo TEXT,
	image_path VARCHAR(500),
	image_url VARCHAR(2000),
	created_at DATETIME NOT NULL,
	external_id VARCHAR(200),
	source VARCHAR(30) DEFAULT 'local' NOT NULL,
	source_updated_at DATETIME,
	PRIMARY KEY (id),
	CONSTRAINT ck_meal_calories CHECK (calories IS NULL OR calories >= 0),
	CONSTRAINT ck_meal_protein CHECK (protein IS NULL OR protein >= 0),
	CONSTRAINT ck_meal_carbohydrates CHECK (carbohydrates IS NULL OR carbohydrates >= 0),
	CONSTRAINT ck_meal_fat CHECK (fat IS NULL OR fat >= 0),
	CONSTRAINT ck_meal_name CHECK (length(trim(name)) > 0),
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE RESTRICT
)""", (
        "CREATE INDEX ix_meals_user_eaten_at ON meals (user_id, eaten_at)",
        "CREATE UNIQUE INDEX uq_meals_source_external ON meals (user_id, source, external_id)",
    )),
    "body_metrics": ("""
CREATE TABLE body_metrics__v3 (
	id INTEGER NOT NULL,
	user_id INTEGER NOT NULL,
	measured_at DATETIME NOT NULL,
	weight FLOAT,
	body_fat FLOAT,
	skeletal_muscle FLOAT,
	memo TEXT,
	external_id VARCHAR(200),
	source VARCHAR(30) DEFAULT 'local' NOT NULL,
	source_updated_at DATETIME,
	PRIMARY KEY (id),
	CONSTRAINT ck_body_weight CHECK (weight IS NULL OR weight > 0),
	CONSTRAINT ck_body_fat CHECK (body_fat IS NULL OR body_fat BETWEEN 0 AND 100),
	CONSTRAINT ck_body_muscle CHECK (skeletal_muscle IS NULL OR skeletal_muscle >= 0),
	CONSTRAINT ck_body_value CHECK (weight IS NOT NULL OR body_fat IS NOT NULL OR skeletal_muscle IS NOT NULL),
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE RESTRICT
)""", (
        "CREATE INDEX ix_body_metrics_user_measured_at ON body_metrics (user_id, measured_at)",
        "CREATE UNIQUE INDEX uq_body_metrics_source_external ON body_metrics (user_id, source, external_id)",
    )),
    "sleep_records": ("""
CREATE TABLE sleep_records__v3 (
	id INTEGER NOT NULL,
	user_id INTEGER NOT NULL,
	sleep_start DATETIME NOT NULL,
	sleep_end DATETIME NOT NULL,
	duration_minutes INTEGER NOT NULL,
	sleep_type VARCHAR(20) NOT NULL,
	memo TEXT,
	external_id VARCHAR(200),
	source VARCHAR(30) DEFAULT 'local' NOT NULL,
	source_updated_at DATETIME,
	PRIMARY KEY (id),
	CONSTRAINT ck_sleep_time CHECK (sleep_end > sleep_start),
	CONSTRAINT ck_sleep_duration CHECK (duration_minutes >= 0),
	CONSTRAINT ck_sleep_type CHECK (sleep_type IN ('main', 'nap')),
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE RESTRICT
)""", (
        "CREATE INDEX ix_sleep_records_user_start ON sleep_records (user_id, sleep_start)",
        "CREATE INDEX ix_sleep_records_user_end ON sleep_records (user_id, sleep_end)",
        "CREATE UNIQUE INDEX uq_sleep_records_source_external ON sleep_records (user_id, source, external_id)",
    )),
    "sync_state": ("""
CREATE TABLE sync_state__v3 (
	id INTEGER NOT NULL,
	user_id INTEGER NOT NULL,
	spreadsheet_id VARCHAR(200),
	spreadsheet_title VARCHAR(300),
	last_sync_at DATETIME,
	last_sync_status VARCHAR(30),
	last_sync_error TEXT,
	last_result TEXT,
	PRIMARY KEY (id),
	CONSTRAINT uq_sync_state_user UNIQUE (user_id),
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE RESTRICT
)""", ()),
    "import_archives": ("""
CREATE TABLE import_archives__v3 (
	id INTEGER NOT NULL,
	user_id INTEGER NOT NULL,
	sha256 VARCHAR(64) NOT NULL,
	filename VARCHAR(255) NOT NULL,
	original BLOB NOT NULL,
	payload TEXT NOT NULL,
	report TEXT NOT NULL,
	created_at DATETIME NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_archive_user_sha256 UNIQUE (user_id, sha256),
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE RESTRICT
)""", ()),
    "excel_previews": ("""
CREATE TABLE excel_previews__v3 (
	token VARCHAR(64) NOT NULL,
	user_id INTEGER NOT NULL,
	payload TEXT NOT NULL,
	original BLOB NOT NULL,
	created_at DATETIME NOT NULL,
	result TEXT,
	PRIMARY KEY (token),
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE RESTRICT
)""", (
        "CREATE INDEX ix_excel_previews_user_created ON excel_previews (user_id, created_at)",
    )),
}

EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def migrate_v3(engine: Engine, owner_email: str | None = None) -> None:
    """Add users and give every existing row to the owner account (FITLOG_OWNER_EMAIL).

    Session, invite and consent tables are new and come from create_all, like
    sync_state did in v2. Any failure rolls the whole step back to v2.
    """
    if owner_email is None:
        owner_email = os.environ.get("FITLOG_OWNER_EMAIL", "")
    owner_email = owner_email.strip().lower()
    if owner_email and not EMAIL.fullmatch(owner_email):
        raise RuntimeError("FITLOG_OWNER_EMAIL is not a valid email address")
    with engine.connect() as c:
        # Must precede BEGIN: SQLite ignores this pragma inside a transaction.
        c.exec_driver_sql("PRAGMA foreign_keys=OFF")
        try:
            c.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                rebuild_v3(c, owner_email)
                c.exec_driver_sql("PRAGMA user_version=3")
                c.commit()
            except Exception:
                c.rollback()
                raise
        finally:
            c.exec_driver_sql("PRAGMA foreign_keys=ON")


def rebuild_v3(c: Connection, owner_email: str) -> None:
    existing = {table: columns(c, table) for table in V3_TABLES}
    rows = {table: count(c, table) for table, cols in existing.items() if cols}
    if any(rows.values()) and not owner_email:
        raise RuntimeError("FITLOG_OWNER_EMAIL is required to assign existing records to the owner account")
    c.exec_driver_sql(V3_USERS)
    owner_id = None
    if owner_email:
        owner_id = c.exec_driver_sql(
            "INSERT INTO users (email, role, status, created_at) VALUES (?, 'admin', 'active', ?) RETURNING id",
            # SQLAlchemy's SQLite DateTime text format, UTC-naive.
            (owner_email, datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")),
        ).scalar_one()
    for table, (ddl, indexes) in V3_TABLES.items():
        if not existing[table]:
            continue  # create_all builds it with the current shape
        c.exec_driver_sql(ddl)
        shared = [name for name in columns(c, table + "__v3") if name in existing[table] and name != "user_id"]
        names = ", ".join(shared)
        c.exec_driver_sql(f"INSERT INTO {table}__v3 ({names}, user_id) SELECT {names}, ? FROM {table}", (owner_id,))
        if count(c, table + "__v3") != rows[table]:
            raise RuntimeError(f"{table}: row count changed during migration")
        c.exec_driver_sql(f"DROP TABLE {table}")
        c.exec_driver_sql(f"ALTER TABLE {table}__v3 RENAME TO {table}")
        for statement in indexes:
            c.exec_driver_sql(statement)
    if c.exec_driver_sql("PRAGMA foreign_key_check").first() is not None:
        raise RuntimeError("Existing rows violate foreign keys; migration cancelled")
    if c.exec_driver_sql("PRAGMA integrity_check").scalar_one() != "ok":
        raise RuntimeError("Integrity check failed; migration cancelled")


def columns(c: Connection, table: str) -> list[str]:
    return [r[1] for r in c.exec_driver_sql(f"PRAGMA table_info({table})")]


def count(c: Connection, table: str) -> int:
    return c.exec_driver_sql(f"SELECT count(*) FROM {table}").scalar_one()


V4_PRESET_INDEX = ("CREATE UNIQUE INDEX uq_exercise_user_preset ON exercises (user_id, preset_id) "
                   "WHERE preset_id IS NOT NULL")


def migrate_v4(engine: Engine) -> None:
    """Link exercises to built-in presets: add exercises.preset_id and fill it where a name clearly matches.

    Only an exact name or alias match (ignoring spaces and case) links, and only the first such
    exercise per user and preset, so the unique index holds. Nothing else is renamed or merged.
    """
    from app.services.exercise_presets import match_name
    with engine.connect() as c:
        c.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            c.exec_driver_sql("ALTER TABLE exercises ADD COLUMN preset_id VARCHAR(64)")
            c.exec_driver_sql(V4_PRESET_INDEX)
            linked = set()
            for exercise_id, user_id, name in c.exec_driver_sql("SELECT id, user_id, name FROM exercises ORDER BY id").all():
                preset = match_name(name)
                if preset and (user_id, preset) not in linked:
                    linked.add((user_id, preset))
                    c.exec_driver_sql("UPDATE exercises SET preset_id = ? WHERE id = ?", (preset, exercise_id))
            c.exec_driver_sql("PRAGMA user_version=4")
            c.commit()
        except Exception:
            c.rollback()
            raise


STEPS: dict[int, Callable[[Engine], None]] = {2: migrate_v2, 3: migrate_v3, 4: migrate_v4}


def finish_migration(engine: Engine) -> None:
    """Stamp a newly created schema; existing databases were stamped by their steps."""
    with engine.begin() as c:
        if c.exec_driver_sql("PRAGMA user_version").scalar_one() == 0:
            c.exec_driver_sql(f"PRAGMA user_version={SCHEMA_VERSION}")
