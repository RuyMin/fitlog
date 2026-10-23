import unittest

from support import TEMP, act_as, create_user, fresh_owner  # noqa: F401 — isolate FITLOG_DATA_DIR before app imports
from fastapi.testclient import TestClient

from app.main import app


class WorkoutBatchApiTests(unittest.TestCase):
    """One request per screen action: add many sets, change a variant, remove an exercise."""

    def setUp(self) -> None:
        self.client = TestClient(app)
        self.client.__enter__()
        fresh_owner()
        self.workout = self.client.post("/api/workouts", json={"workout_date": "2026-10-23", "title": "등"}).json()
        self.pulldown = self.client.post("/api/exercises", json={"name": "랫풀다운", "preset_id": "lat_pulldown"}).json()
        self.row = self.client.post("/api/exercises", json={"name": "바벨 로우", "preset_id": "barbell_row"}).json()
        self.base = f"/api/workouts/{self.workout['id']}"

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)

    def batch(self, items):
        return self.client.post(self.base + "/sets/batch", json=items)

    def test_batch_adds_all_or_nothing(self) -> None:
        created = self.batch([{"exercise_id": self.pulldown["id"], "set_number": n, "weight": 50, "reps": 10} for n in (1, 2)]
                             + [{"exercise_id": self.row["id"], "set_number": 1, "variant": "under"}])
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(len(created.json()["sets"]), 3)
        duplicate = self.batch([{"exercise_id": self.row["id"], "set_number": 2}, {"exercise_id": self.row["id"], "set_number": 1}])
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(self.batch([{"exercise_id": self.row["id"], "set_number": 3, "variant": "v_bar"}]).status_code, 422)
        self.assertEqual(len(self.client.get(self.base).json()["sets"]), 3)
        self.assertEqual(self.batch([]).status_code, 422)

    def test_variant_changes_unfinished_sets_only(self) -> None:
        self.batch([{"exercise_id": self.pulldown["id"], "set_number": 1, "completed": True, "variant": "wide"},
                    {"exercise_id": self.pulldown["id"], "set_number": 2},
                    {"exercise_id": self.row["id"], "set_number": 1}])
        result = self.client.put(f"{self.base}/exercises/{self.pulldown['id']}/variant", json={"variant": "parallel"})
        self.assertEqual(result.status_code, 200, result.text)
        variants = {(s["exercise_id"], s["set_number"]): s["variant"] for s in result.json()["sets"]}
        self.assertEqual(variants, {(self.pulldown["id"], 1): "wide", (self.pulldown["id"], 2): "parallel", (self.row["id"], 1): None})
        cleared = self.client.put(f"{self.base}/exercises/{self.pulldown['id']}/variant", json={"variant": None}).json()
        self.assertIsNone(next(s for s in cleared["sets"] if s["set_number"] == 2 and s["exercise_id"] == self.pulldown["id"])["variant"])
        self.assertEqual(self.client.put(f"{self.base}/exercises/{self.row['id']}/variant", json={"variant": "d_handle"}).status_code, 422)

    def test_remove_exercise_deletes_only_its_sets(self) -> None:
        self.batch([{"exercise_id": self.pulldown["id"], "set_number": 1}, {"exercise_id": self.pulldown["id"], "set_number": 2},
                    {"exercise_id": self.row["id"], "set_number": 1}])
        result = self.client.delete(f"{self.base}/exercises/{self.pulldown['id']}")
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual([s["exercise_id"] for s in result.json()["sets"]], [self.row["id"]])

    def test_other_users_workout_is_not_found(self) -> None:
        act_as(create_user("friend@example.com", "member"))
        self.assertEqual(self.batch([{"exercise_id": self.pulldown["id"], "set_number": 1}]).status_code, 404)
        self.assertEqual(self.client.put(f"{self.base}/exercises/{self.pulldown['id']}/variant", json={"variant": None}).status_code, 404)
        self.assertEqual(self.client.delete(f"{self.base}/exercises/{self.pulldown['id']}").status_code, 404)


if __name__ == "__main__":
    unittest.main()
