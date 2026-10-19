import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from support import TEMP  # noqa: F401 — isolate FITLOG_DATA_DIR before app imports
from sqlalchemy import create_engine

from app.migrations import migrate

SCHEMA_V2 = (Path(__file__).parent / "fixtures" / "schema_v2.sql").read_text(encoding="utf-8")
OWNED = ("exercises", "workouts", "workout_sets", "meals", "body_metrics", "sleep_records",
         "sync_state", "import_archives", "excel_previews")
SEED = """
INSERT INTO exercises VALUES (1, 'Squat', NULL, '하체', '2026-09-01 00:00:00');
INSERT INTO workouts VALUES (1, '2026-09-25', '하체', '하체', NULL, NULL, NULL,
    '2026-09-25 01:00:00', '2026-09-25 01:00:00', 'w1', 'google_sheets', '2026-09-25 01:00:00');
INSERT INTO workout_sets VALUES (1, 1, 1, 1, 60, 8, 1, NULL, 8, 2, NULL, 'local', NULL);
INSERT INTO meals VALUES (1, '2026-09-25 03:00:00', 'lunch', '닭가슴살', 300, 40, 10, 5, NULL, NULL, NULL,
    '2026-09-25 03:00:00', NULL, 'local', NULL);
INSERT INTO body_metrics VALUES (1, '2026-09-25 00:00:00', 70.5, NULL, NULL, NULL, NULL, 'local', NULL);
INSERT INTO sleep_records VALUES (1, '2026-09-24 14:00:00', '2026-09-24 21:00:00', 420, 'main', NULL, NULL, 'local', NULL);
INSERT INTO sync_state VALUES (1, 'sheet_id', '기록', '2026-09-25 00:00:00', 'ok', NULL, '{}');
INSERT INTO import_archives VALUES (1, 'abc', 'a.xlsx', x'00', '{}', '{}', '2026-09-25 00:00:00');
INSERT INTO excel_previews VALUES ('tok', '{}', x'', '2026-09-25 00:00:00', NULL);
"""


class V3MigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "fitlog.db"
        with closing(sqlite3.connect(self.path)) as c:
            c.executescript(SCHEMA_V2)
        self.engine = create_engine("sqlite:///" + self.path.as_posix())

    def tearDown(self) -> None:
        self.engine.dispose()
        self.tmp.cleanup()

    def seed(self, sql: str = SEED) -> None:
        with closing(sqlite3.connect(self.path)) as c:
            c.executescript(sql)

    def connect(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path)
        c.execute("PRAGMA foreign_keys=ON")
        return c

    def upgrade(self, owner: str | None = "Owner@Example.com ") -> None:
        env = {k: v for k, v in os.environ.items() if k != "FITLOG_OWNER_EMAIL"}
        if owner is not None:
            env["FITLOG_OWNER_EMAIL"] = owner
        with patch("app.migrations.SCHEMA_VERSION", 3), patch.dict(os.environ, env, clear=True):
            migrate(self.engine, self.path)

    def version(self) -> int:
        with closing(sqlite3.connect(self.path)) as c:
            return c.execute("PRAGMA user_version").fetchone()[0]

    def columns(self, table: str) -> list[str]:
        with closing(sqlite3.connect(self.path)) as c:
            return [r[1] for r in c.execute(f"PRAGMA table_info({table})")]

    def test_existing_rows_belong_to_owner_and_values_survive(self) -> None:
        self.seed()
        self.upgrade()
        self.assertEqual(self.version(), 3)
        with closing(self.connect()) as c:
            users = c.execute("SELECT id, email, role, status, google_sub FROM users").fetchall()
            self.assertEqual(len(users), 1)
            owner, email, role, status, sub = users[0]
            self.assertEqual((email, role, status, sub), ("owner@example.com", "admin", "active", None))
            for table in OWNED:
                self.assertEqual(c.execute(f"SELECT DISTINCT user_id FROM {table}").fetchall(), [(owner,)], table)
            self.assertEqual(c.execute("SELECT id, workout_id, exercise_id, weight, reps, completed, rpe, rir FROM workout_sets").fetchone(),
                             (1, 1, 1, 60, 8, 1, 8, 2))
            self.assertEqual(c.execute("SELECT external_id, source FROM workouts").fetchone(), ("w1", "google_sheets"))
            self.assertEqual(c.execute("SELECT name, protein FROM meals").fetchone(), ("닭가슴살", 40))
            self.assertEqual(c.execute("SELECT token, original FROM excel_previews").fetchone(), ("tok", b""))
            self.assertEqual(c.execute("PRAGMA foreign_key_check").fetchall(), [])
        backups = list((self.path.parent / "backups").glob("before-v3-*.db"))
        self.assertEqual(len(backups), 1)
        with closing(sqlite3.connect(backups[0])) as c:
            self.assertEqual(c.execute("PRAGMA user_version").fetchone()[0], 2)
            self.assertEqual(c.execute("SELECT name FROM meals").fetchone()[0], "닭가슴살")
        self.upgrade()
        self.assertEqual(len(list((self.path.parent / "backups").glob("*.db"))), 1)

    def test_constraints_isolate_users(self) -> None:
        self.seed()
        self.upgrade()
        with closing(self.connect()) as c:
            owner = c.execute("SELECT id FROM users").fetchone()[0]
            other = c.execute("INSERT INTO users (google_sub, email, created_at) VALUES ('sub-b', 'b@example.com', '2026-10-01') RETURNING id").fetchone()[0]
            c.execute("INSERT INTO exercises (id, user_id, name, created_at) VALUES (2, ?, 'Squat', '2026-10-01')", (other,))
            with self.assertRaises(sqlite3.IntegrityError):
                c.execute("INSERT INTO exercises (user_id, name, created_at) VALUES (?, 'Squat', '2026-10-01')", (owner,))
            c.execute("INSERT INTO workouts (id, user_id, workout_date, title, created_at, updated_at, external_id, source)"
                      " VALUES (2, ?, '2026-10-01', '상체', '2026-10-01', '2026-10-01', 'w1', 'google_sheets')", (other,))
            insert_set = "INSERT INTO workout_sets (user_id, workout_id, exercise_id, set_number, completed) VALUES (?, ?, ?, 1, 0)"
            for workout, exercise in [(1, 2), (2, 1), (1, 1)]:
                with self.assertRaises(sqlite3.IntegrityError, msg=(workout, exercise)):
                    c.execute(insert_set, (other, workout, exercise))
            c.execute(insert_set, (other, 2, 2))
            c.execute("INSERT INTO import_archives (user_id, sha256, filename, original, payload, report, created_at)"
                      " VALUES (?, 'abc', 'a.xlsx', x'00', '{}', '{}', '2026-10-01')", (other,))
            with self.assertRaises(sqlite3.IntegrityError):
                c.execute("INSERT INTO sync_state (user_id) VALUES (?)", (owner,))
            with self.assertRaises(sqlite3.IntegrityError):
                c.execute("INSERT INTO users (email, created_at) VALUES ('c@example.com', '2026-10-01')")
            with self.assertRaises(sqlite3.IntegrityError):
                c.execute("DELETE FROM users WHERE id = ?", (other,))
            c.execute("DELETE FROM workouts WHERE id = 1")
            self.assertEqual(c.execute("SELECT count(*) FROM workout_sets WHERE user_id = ?", (owner,)).fetchone()[0], 0)

    def test_existing_rows_without_owner_refuse_and_keep_v2(self) -> None:
        self.seed()
        with self.assertRaisesRegex(RuntimeError, "FITLOG_OWNER_EMAIL"):
            self.upgrade(owner=None)
        self.assertEqual(self.version(), 2)
        self.assertNotIn("user_id", self.columns("workouts"))
        self.assertNotIn("users", self.tables())

    def test_invalid_owner_email_is_rejected(self) -> None:
        self.seed()
        with self.assertRaisesRegex(RuntimeError, "valid email"):
            self.upgrade(owner="owner")
        self.assertEqual(self.version(), 2)

    def test_empty_database_needs_no_owner(self) -> None:
        self.upgrade(owner=None)
        self.assertEqual(self.version(), 3)
        for table in OWNED:
            self.assertIn("user_id", self.columns(table), table)
        with closing(self.connect()) as c:
            self.assertEqual(c.execute("SELECT count(*) FROM users").fetchone()[0], 0)

    def test_foreign_key_violation_rolls_back_everything(self) -> None:
        self.seed(SEED + "INSERT INTO workout_sets VALUES (2, 99, 1, 1, NULL, NULL, 0, NULL, NULL, NULL, NULL, 'local', NULL);")
        with self.assertRaisesRegex(RuntimeError, "foreign keys"):
            self.upgrade()
        self.assertEqual(self.version(), 2)
        self.assertNotIn("users", self.tables())
        self.assertNotIn("user_id", self.columns("workout_sets"))
        self.assertFalse(any(name.endswith("__v3") for name in self.tables()))
        with closing(sqlite3.connect(self.path)) as c:
            self.assertEqual(c.execute("SELECT count(*) FROM workout_sets").fetchone()[0], 2)

    def test_newer_database_is_rejected(self) -> None:
        with closing(sqlite3.connect(self.path)) as c:
            c.execute("PRAGMA user_version=4")
        with self.assertRaisesRegex(RuntimeError, "newer"):
            self.upgrade()

    def tables(self) -> set[str]:
        with closing(sqlite3.connect(self.path)) as c:
            return {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}


if __name__ == "__main__":
    unittest.main()
