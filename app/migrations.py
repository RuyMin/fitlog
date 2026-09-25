"""Explicit additive SQLite migrations. Back up before upgrading an existing DB."""
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import Engine

TABLES = ("workouts", "workout_sets", "meals", "body_metrics", "sleep_records")


def migrate(engine: Engine, path: Path) -> None:
    with engine.connect() as c:
        version = c.exec_driver_sql("PRAGMA user_version").scalar_one()
        old = c.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table' AND name='workouts'").first()
    if version > 1:
        raise RuntimeError("Database schema is newer than this application")
    if version == 1:
        return
    if old:
        directory = path.parent / "backups"
        directory.mkdir(exist_ok=True)
        target = directory / ("before-sync-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f") + ".db")
        with closing(sqlite3.connect(path)) as source, closing(sqlite3.connect(target)) as dest:
            source.backup(dest)
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
            c.commit()
        except Exception:
            c.rollback()
            raise


def finish_migration(engine: Engine) -> None:
    with engine.begin() as c:
        for table in TABLES:
            c.exec_driver_sql(f"CREATE UNIQUE INDEX IF NOT EXISTS uq_{table}_source_external ON {table}(source, external_id)")
        c.exec_driver_sql("PRAGMA user_version=1")
