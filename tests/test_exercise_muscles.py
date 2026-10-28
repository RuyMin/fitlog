import json
import unittest
from pathlib import Path

from support import fresh_owner
from fastapi.testclient import TestClient

from app.main import app
from app.services.exercise_presets import similar

PRESETS = json.loads((Path(__file__).resolve().parents[1] / "app" / "static" / "data" / "exercise_presets.json").read_text(encoding="utf-8"))
# Tags the anatomy figure cannot draw (anatomy.js TAGS maps them to nothing).
UNDRAWN = {"심폐", "척추기립근"}


class PresetMuscleTests(unittest.TestCase):
    def test_every_preset_has_a_muscle_to_draw(self) -> None:
        for preset in PRESETS["presets"]:
            with self.subTest(preset=preset["id"]):
                self.assertTrue(set(preset["muscles"]) - UNDRAWN, "the figure would be blank")
                self.assertTrue(set(preset["muscles"]) <= set(preset["tags"]), "muscles are searchable")

    def test_similar_names(self) -> None:
        cases = {"해머 스트렝스 인클라인 프레스": "인클라인 바벨 벤치프레스", "머신 랫풀다운 원암": "랫풀다운",
                 "덤벨 컬 얼터네이트": "덤벨 컬", "풀업 어시스트": "풀업", "내 맘대로 운동": None}
        for name, expected in cases.items():
            with self.subTest(name=name):
                self.assertEqual((similar(name) or {}).get("name"), expected)


class OwnExerciseMuscleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.client.__enter__()
        fresh_owner()

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)

    def exercise(self, name, **fields):
        response = self.client.post("/api/exercises", json={"name": name, **fields})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_suggestions_list_own_exercises_without_muscles(self) -> None:
        assisted = self.exercise("풀업 어시스트")
        odd = self.exercise("내 맘대로 운동")
        self.exercise("랫풀다운 페러럴그립")  # merged by the cleanup instead
        self.exercise("랫풀다운", preset_id="lat_pulldown")
        self.exercise("케이블 Y 레이즈", muscles=["측면 삼각근"])
        items = {item["exercise_id"]: item for item in self.client.get("/api/exercise-muscles").json()}
        self.assertEqual(set(items), {assisted["id"], odd["id"]})
        self.assertEqual((items[assisted["id"]]["like"], items[assisted["id"]]["muscles"]), ("풀업", ["광배근", "이두근"]))
        self.assertEqual((items[odd["id"]]["like"], items[odd["id"]]["muscles"]), (None, []))

    def test_picked_muscles_are_saved_in_order(self) -> None:
        mine = self.exercise("내 맘대로 운동")
        body = {"name": mine["name"], "muscles": ["둔근", "햄스트링", "둔근"]}
        saved = self.client.put(f"/api/exercises/{mine['id']}", json=body).json()
        self.assertEqual(saved["muscles"], ["둔근", "햄스트링"])
        self.assertEqual(self.client.get("/api/exercise-muscles").json(), [])
        cleared = self.client.put(f"/api/exercises/{mine['id']}", json={"name": mine["name"], "muscles": []}).json()
        self.assertIsNone(cleared["muscles"])

    def test_unknown_muscles_and_presets(self) -> None:
        self.assertEqual(self.client.post("/api/exercises", json={"name": "날개 운동", "muscles": ["날개"]}).status_code, 422)
        # A preset brings its own muscles.
        linked = self.exercise("랫풀다운", preset_id="lat_pulldown", muscles=["둔근"])
        self.assertIsNone(linked["muscles"])


if __name__ == "__main__":
    unittest.main()
