"""SQLite lifecycle and request-scoped sessions.

Use a local filesystem on the NAS, not SMB/NFS, for the live database.
"""
import os
import sqlite3
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DATA_DIR = Path(os.environ.get("FITLOG_DATA_DIR", Path(__file__).resolve().parents[1] / "data"))
DATABASE_PATH = DATA_DIR / "fitlog.db"


class Base(DeclarativeBase):
    pass


engine = create_engine(
    "sqlite:///" + DATABASE_PATH.as_posix(),
    connect_args={"check_same_thread": False, "timeout": 30},
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


@event.listens_for(engine, "connect")
def configure_sqlite(connection: sqlite3.Connection, _: object) -> None:
    cursor = connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()


def initialize_database() -> None:
    from app import models  # noqa: F401 — register metadata before creation

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "uploads").mkdir(exist_ok=True)
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA journal_mode=WAL")
    # Initial schema only. Future changes must use explicit migrations.
    Base.metadata.create_all(bind=engine)


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
