import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from support import TEMP, fresh_owner  # noqa: F401 — isolate FITLOG_DATA_DIR before app imports
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.main import app
from app.migrations import migrate
from app.services import exercise_presets

SCHEMA_V2 = (Path(__file__).parent / "fixtures" / "schema_v2.sql").read_text(encoding="utf-8")


class PresetCatalogTests(unittest.TestCase):
    def test_catalog_is_consistent(self) -> None:
        data = exercise_presets.catalog()
        presets = data["presets"]
        self.assertGreaterEqual(len(presets), 100)
        self.assertEqual(len({p["id"] for p in presets}), len(presets))
        self.assertEqual(len({p["name"] for p in presets}), len(presets))
        for preset in presets:
            self.assertIn(preset["body_part"], data["parts"], preset["id"])
            self.assertIn(preset["equipment"], data["equipment"], preset["id"])
            self.assertIn(preset["tracking"], {"weight_reps", "reps", "time", "distance_time"}, preset["id"])
            self.assertTrue(preset["muscles"], preset["id"])

    def test_name_matching(self) -> None:
        self.assertEqual(exercise_presets.match_name("바벨 벤치프레스"), "bench_press")
        self.assertEqual(exercise_presets.match_name(" 사레레 "), "lateral_raise")
        self.assertEqual(exercise_presets.match_name("barbell bench press"), "bench_press")
        self.assertIsNone(exercise_presets.match_name("나만의 운동"))


class PresetApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.client.__enter__()
        fresh_owner()

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)

    def test_presets_endpoint_and_exercise_link(self) -> None:
        catalog = self.client.get("/api/exercise-presets").json()
        self.assertEqual(len(catalog["presets"]), len(exercise_presets.catalog()["presets"]))
        created = self.client.post("/api/exercises", json={"name": "사이드 레터럴 레이즈", "body_part": "어깨", "category": "덤벨", "preset_id": "lateral_raise"})
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()["preset_id"], "lateral_raise")
        again = self.client.post("/api/exercises", json={"name": "사레레 두번째", "preset_id": "lateral_raise"})
        self.assertEqual(again.status_code, 409)
        unknown = self.client.post("/api/exercises", json={"name": "모르는 운동", "preset_id": "nope"})
        self.assertEqual(unknown.status_code, 422)
        custom = self.client.post("/api/exercises", json={"name": "내 운동"})
        self.assertEqual(custom.status_code, 201)
        self.assertIsNone(custom.json()["preset_id"])


class MigrationV4Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "fitlog.db"
        with closing(sqlite3.connect(self.path)) as c:
            c.executescript(SCHEMA_V2)
            c.executescript("""
INSERT INTO exercises VALUES (1, '스쿼트', NULL, '하체', '2026-09-01 00:00:00');
INSERT INTO exercises VALUES (2, 'Barbell Back Squat', NULL, NULL, '2026-09-01 00:00:00');
INSERT INTO exercises VALUES (3, '사레레', NULL, NULL, '2026-09-01 00:00:00');
INSERT INTO exercises VALUES (4, '내 맘대로 운동', NULL, NULL, '2026-09-01 00:00:00');
""")
        self.engine = create_engine("sqlite:///" + self.path.as_posix())

    def tearDown(self) -> None:
        self.engine.dispose()
        self.tmp.cleanup()

    def test_v3_to_v4_adds_preset_id_and_links_clear_names(self) -> None:
        env = {**os.environ, "FITLOG_OWNER_EMAIL": "owner@example.com"}
        with patch("app.migrations.SCHEMA_VERSION", 3), patch.dict(os.environ, env, clear=True):
            migrate(self.engine, self.path)
        with patch.dict(os.environ, env, clear=True):
            migrate(self.engine, self.path)
        with closing(sqlite3.connect(self.path)) as c:
            self.assertEqual(c.execute("PRAGMA user_version").fetchone()[0], 4)
            linked = dict(c.execute("SELECT id, preset_id FROM exercises ORDER BY id").fetchall())
        # 스쿼트 is an alias of the back squat; the second back-squat row stays unlinked (one per user and preset).
        self.assertEqual(linked, {1: "back_squat", 2: None, 3: "lateral_raise", 4: None})


if __name__ == "__main__":
    unittest.main()
