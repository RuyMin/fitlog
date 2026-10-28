import unittest

from support import create_user, fresh_owner
from fastapi.testclient import TestClient

from app.main import app
from app.services.exercise_presets import split_variant


class NameSplitTests(unittest.TestCase):
    def test_grip_in_the_name(self) -> None:
        cases = {
            "랫풀다운 페러럴그립": ("lat_pulldown", "parallel"), "랫풀다운 패러럴바": ("lat_pulldown", "parallel"),
            "와이드 랫풀다운": ("lat_pulldown", "wide"), "랫풀다운(언더그립)": ("lat_pulldown", "under"),
            "랫풀다운 브이바": ("lat_pulldown", "v_bar"), "시티드 케이블 로우 패러럴": ("seated_cable_row", "parallel"),
            "풀업 패러럴": ("pull_up", "parallel"), "벤치프레스 내로우": ("bench_press", "narrow"),
            "랫 풀다운": ("lat_pulldown", None),
        }
        for name, expected in cases.items():
            with self.subTest(name=name):
                self.assertEqual(split_variant(name), expected)

    def test_unsure_names_are_left_alone(self) -> None:
        for name in ["랫풀다운 머신", "내 맘대로 운동", "케이블 Y 레이즈", "랫풀다운 아무거나"]:
            with self.subTest(name=name):
                self.assertIsNone(split_variant(name))


class MergeApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.client.__enter__()
        fresh_owner()

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)

    def exercise(self, name, preset_id=None):
        return self.client.post("/api/exercises", json={"name": name, "preset_id": preset_id}).json()

    def workout(self, day):
        return self.client.post("/api/workouts", json={"workout_date": day, "title": "등"}).json()

    def add(self, workout, exercise, number, **fields):
        response = self.client.post(f"/api/workouts/{workout['id']}/sets",
                                    json={"exercise_id": exercise["id"], "set_number": number, "weight": 50, "reps": 10, "completed": True, **fields})
        self.assertEqual(response.status_code, 201, response.text)

    def test_suggest_then_merge_moves_sets_with_the_grip(self) -> None:
        pulldown = self.exercise("랫풀다운", "lat_pulldown")
        old = self.exercise("랫풀다운 페러럴그립")
        self.exercise("케이블 Y 레이즈")
        first, second = self.workout("2026-09-01"), self.workout("2026-09-03")
        self.add(first, old, 1); self.add(first, old, 2)
        self.add(second, pulldown, 1, variant="wide"); self.add(second, pulldown, 2); self.add(second, old, 1)
        suggestions = self.client.get("/api/exercise-cleanup").json()
        self.assertEqual(suggestions, [{"exercise_id": old["id"], "name": "랫풀다운 페러럴그립", "sets": 3, "preset_id": "lat_pulldown",
                                        "preset_name": "랫풀다운", "variant": "parallel", "variant_label": "패러럴 바"}])
        response = self.client.post(f"/api/exercises/{old['id']}/merge", json={"preset_id": "lat_pulldown", "variant": "parallel"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual((response.json()["moved"], response.json()["target"]["id"]), (3, pulldown["id"]))
        sets = lambda w: [(s["exercise"]["id"], s["set_number"], s["variant"]) for s in self.client.get(f"/api/workouts/{w['id']}").json()["sets"]]
        self.assertEqual(sorted(sets(first)), [(pulldown["id"], 1, "parallel"), (pulldown["id"], 2, "parallel")])
        # A workout that already had 랫풀다운 keeps its sets; the moved one follows them.
        self.assertEqual(sorted(sets(second)), [(pulldown["id"], 1, "wide"), (pulldown["id"], 2, None), (pulldown["id"], 3, "parallel")])
        self.assertEqual(self.client.get(f"/api/exercises/{old['id']}").status_code, 404)
        self.assertEqual(self.client.get("/api/exercise-cleanup").json(), [])

    def test_merge_makes_the_preset_exercise_when_missing(self) -> None:
        old = self.exercise("와이드 랫풀다운")
        self.add(self.workout("2026-09-01"), old, 1)
        target = self.client.post(f"/api/exercises/{old['id']}/merge", json={"preset_id": "lat_pulldown", "variant": "wide"}).json()["target"]
        self.assertEqual((target["name"], target["preset_id"], target["body_part"]), ("랫풀다운", "lat_pulldown", "등"))

    def test_invalid_merges_are_refused(self) -> None:
        linked = self.exercise("랫풀다운", "lat_pulldown")
        old = self.exercise("랫풀다운 페러럴그립")
        self.assertEqual(self.client.post(f"/api/exercises/{linked['id']}/merge", json={"preset_id": "lat_pulldown"}).status_code, 409)
        self.assertEqual(self.client.post(f"/api/exercises/{old['id']}/merge", json={"preset_id": "lat_pulldown", "variant": "feet_high"}).status_code, 422)
        self.assertEqual(self.client.post(f"/api/exercises/{old['id']}/merge", json={"preset_id": "no_such"}).status_code, 422)
        from support import act_as
        act_as(create_user("friend@example.com", "member"))
        self.assertEqual(self.client.post(f"/api/exercises/{old['id']}/merge", json={"preset_id": "lat_pulldown"}).status_code, 404)


if __name__ == "__main__":
    unittest.main()
