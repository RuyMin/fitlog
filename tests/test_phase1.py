"""Integration tests using a disposable local database."""
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from support import TEMP as _TEMP

from fastapi.testclient import TestClient
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from app.database import DATABASE_PATH, SessionLocal, engine
from app.main import app
from app.models import BodyMetric, Exercise, Meal, SleepRecord, Workout, WorkoutSet


class PhaseOneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.__exit__(None, None, None)
        engine.dispose()

    def test_health_and_database_configuration(self) -> None:
        result = self.client.get("/api/health")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json(), {"status": "ok", "app": "FitLog"})
        self.assertTrue(DATABASE_PATH.is_file())
        self.assertTrue((Path(_TEMP.name) / "uploads").is_dir())
        self.assertEqual(set(inspect(engine).get_table_names()), {
            "workouts", "exercises", "workout_sets", "meals", "body_metrics", "sleep_records", "sync_state", "import_archives"
        })
        with engine.connect() as connection:
            self.assertEqual(connection.scalar(text("PRAGMA foreign_keys")), 1)
            self.assertEqual(connection.scalar(text("PRAGMA journal_mode")), "wal")
            self.assertEqual(connection.scalar(text("PRAGMA busy_timeout")), 30000)

    def test_ui_pwa_and_private_files(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("FitLog", response.text)
        manifest = self.client.get("/manifest.json").json()
        self.assertEqual(manifest["display"], "standalone")
        for asset in ["/static/css/app.css", "/static/js/app.js", "/service-worker.js"]:
            self.assertEqual(self.client.get(asset).status_code, 200)
        for icon in manifest["icons"]:
            response = self.client.get(icon["src"])
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(self.client.get("/service-worker.js").headers["cache-control"], "no-cache")
        for path in ["/data/fitlog.db", "/uploads/example.jpg", "/api/unknown"]:
            self.assertEqual(self.client.get(path).status_code, 404)
        self.assertEqual(self.client.get("/api/unknown").json(), {"detail": "Not Found"})

    def test_health_database_failure(self) -> None:
        with patch("sqlalchemy.orm.Session.execute", side_effect=OperationalError("SELECT 1", {}, Exception("private"))):
            result = self.client.get("/api/health")
        self.assertEqual(result.status_code, 503)
        self.assertEqual(result.json(), {"detail": "Database unavailable"})

    def test_persistence_foreign_keys_and_cascade(self) -> None:
        with SessionLocal() as session:
            exercise = Exercise(name="Test squat")
            workout = Workout(workout_date=date.today(), title="Test workout")
            session.add_all([exercise, workout])
            session.flush()
            workout_id, exercise_id = workout.id, exercise.id
            session.add(WorkoutSet(workout_id=workout_id, exercise_id=exercise_id, set_number=1, weight=60, reps=8))
            session.commit()
        engine.dispose()
        with SessionLocal() as session:
            self.assertEqual(session.get(Workout, workout_id).title, "Test workout")
            session.delete(session.get(Exercise, exercise_id))
            with self.assertRaises(IntegrityError):
                session.commit()
            session.rollback()
            session.execute(text("DELETE FROM workouts WHERE id = :id"), {"id": workout_id})
            session.commit()
            self.assertIsNone(session.scalar(select(WorkoutSet).where(WorkoutSet.workout_id == workout_id)))

    def test_invalid_values_rejected(self) -> None:
        now = datetime.now()
        invalid = [
            Workout(workout_date=date.today(), title=" "),
            WorkoutSet(workout_id=999999, exercise_id=999999, set_number=1),
            Meal(eaten_at=now, meal_type="lunch", name="Invalid", protein=-1),
            BodyMetric(measured_at=now, weight=-1),
            SleepRecord(sleep_start=now, sleep_end=now - timedelta(hours=1), duration_minutes=60),
            SleepRecord(sleep_start=now, sleep_end=now + timedelta(hours=1), duration_minutes=60, sleep_type="invalid"),
        ]
        for record in invalid:
            with self.subTest(model=type(record).__name__), SessionLocal() as session:
                session.add(record)
                with self.assertRaises(IntegrityError):
                    session.commit()

    def test_nullable_nutrition_and_split_sleep(self) -> None:
        now = datetime.now()
        with SessionLocal() as session:
            meal = Meal(eaten_at=now, meal_type="lunch", name="Unknown nutrition")
            session.add(meal)
            session.add_all([
                SleepRecord(sleep_start=now, sleep_end=now + timedelta(hours=4), duration_minutes=240),
                SleepRecord(sleep_start=now + timedelta(hours=6), sleep_end=now + timedelta(hours=7), duration_minutes=60, sleep_type="nap"),
            ])
            session.commit()
            self.assertIsNone(meal.protein)
            self.assertEqual(len(session.scalars(select(SleepRecord)).all()), 2)


if __name__ == "__main__":
    unittest.main()
