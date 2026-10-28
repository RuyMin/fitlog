import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine

from app.migrations import UNREAD_SET, fill_imported_sets, fold_daily_summaries, migrate
from app.services.legacy_xlsx import daily_target, parse_set_text

SCHEMA_V2 = (Path(__file__).parent / "fixtures" / "schema_v2.sql").read_text(encoding="utf-8")


class SetTextTests(unittest.TestCase):
    def test_cells_the_old_importer_skipped(self) -> None:
        cases = {
            "60kg×8": (60.0, 8, None), "4kg×15(좌우)": (4.0, 15, "횟수는 한쪽 기준"), "6kg×15(양쪽)": (6.0, 15, "횟수는 한쪽 기준"),
            "20kg×5(워밍업)": (20.0, 5, "워밍업"), "맨몸×15(양쪽)": (None, 15, "횟수는 한쪽 기준"), "×10": (None, 10, None),
            "좌우 합쳐 10회": (None, 10, None), "25kg×5 + 15kg×8": (25.0, 5, "드롭 세트: 이어서 15kg×8"),
            "자세 교정": None, "": None, "60kg": None,
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(parse_set_text(text), expected)

    def test_daily_rows_find_their_session(self) -> None:
        self.assertEqual(daily_target([("가슴 보완", 1)], "저녁 보완 운동"), 1, "the only session that day")
        self.assertEqual(daily_target([("등", 1), ("러닝 · 저녁 러닝", 2)], "저녁 러닝"), 2)
        self.assertEqual(daily_target([("어깨+이두+삼두", 1), ("러닝 · Easy", 2)], "어깨 + 이두 + 삼두"), 1)
        self.assertIsNone(daily_target([], "벌초/야외 작업"))
        self.assertIsNone(daily_target([("등", 1), ("가슴", 2)], "PT"), "unclear: left as it is")


class MigrationV12Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "fitlog.db"
        with closing(sqlite3.connect(self.path)) as c:
            c.executescript(SCHEMA_V2)
        self.engine = create_engine("sqlite:///" + self.path.as_posix())
        with patch.dict(os.environ, {**os.environ, "FITLOG_OWNER_EMAIL": "owner@example.com"}, clear=True):
            migrate(self.engine, self.path)

    def tearDown(self) -> None:
        self.engine.dispose()
        self.tmp.cleanup()

    def test_sets_get_their_numbers_and_summaries_fold(self) -> None:
        stamp = "2026-10-02 00:00:00"
        with closing(sqlite3.connect(self.path)) as c:
            user = c.execute("SELECT id FROM users").fetchone()[0]
            add = "INSERT INTO workouts (user_id, workout_date, title, memo, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)"
            session = c.execute(add, (user, "2026-10-02", "어깨+팔 홈트", "웨이트 기록에서 이관.", stamp, stamp)).lastrowid
            summary = c.execute(add, (user, "2026-10-02", "어깨 + 이두 + 삼두 홈트", "원본: 일일 운동 기록 10행\n상태: 완료", stamp, stamp)).lastrowid
            outdoor = c.execute(add, (user, "2026-09-24", "벌초/야외 작업", "원본: 일일 운동 기록 3행", stamp, stamp)).lastrowid
            exercise = c.execute("INSERT INTO exercises (user_id, name, created_at) VALUES (?, '원암 덤벨컬', ?)", (user, stamp)).lastrowid
            sets = "INSERT INTO workout_sets (user_id, workout_id, exercise_id, set_number, completed, memo) VALUES (?, ?, ?, ?, 1, ?)"
            c.execute(sets, (user, session, exercise, 1, "원본: 웨이트 기록 64행 / 세트1" + UNREAD_SET + "10kg×12(좌우)\n주차: 3"))
            c.execute(sets, (user, session, exercise, 2, "원본: 웨이트 기록 64행 / 세트2" + UNREAD_SET + "자세 교정"))
            c.commit()
        with self.engine.begin() as c:
            fill_imported_sets(c)
            fold_daily_summaries(c)
        with closing(sqlite3.connect(self.path)) as c:
            rows = c.execute("SELECT set_number, weight, reps, memo FROM workout_sets ORDER BY set_number").fetchall()
            workouts = {row[0]: row[1] for row in c.execute("SELECT id, memo FROM workouts")}
        self.assertEqual(rows[0][:3], (1, 10.0, 12))
        self.assertEqual(rows[0][3], "원본: 웨이트 기록 64행 / 세트1\n원문: 10kg×12(좌우) (횟수는 한쪽 기준)\n주차: 3")
        self.assertEqual(rows[1][:3], (2, None, None), "a cell that is not weight × reps stays as it was")
        self.assertNotIn(summary, workouts)
        self.assertEqual(workouts[session], "웨이트 기록에서 이관.\n\n원본: 일일 운동 기록 10행\n상태: 완료")
        self.assertIn(outdoor, workouts, "a day with no session keeps its own")


if __name__ == "__main__":
    unittest.main()
