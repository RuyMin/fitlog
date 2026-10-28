import unittest

from support import act_as, create_user, fresh_owner
from fastapi.testclient import TestClient

from app.main import app
from app.services import exercise_presets

NEW = {"name": "케이블 Y 레이즈", "name_en": "Cable Y Raise", "aliases": ["Y 레이즈"], "body_part": "어깨", "equipment": "케이블",
       "muscles": ["측면 삼각근", "승모근 하부"], "kind": "isolation", "tracking": "weight_reps"}


class PresetAdminTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.client.__enter__()
        self.admin = fresh_owner()

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)

    def preset(self, preset_id):
        return next(p for p in self.client.get("/api/exercise-presets").json()["presets"] if p["id"] == preset_id)

    def edit_body(self, preset_id, **changes):
        preset = self.preset(preset_id)
        return {**{key: preset[key] for key in ("name", "name_en", "aliases", "body_part", "equipment", "muscles", "kind", "tracking")}, **changes}

    def test_edit_shows_for_everyone_and_can_be_undone(self) -> None:
        mine = self.client.post("/api/exercises", json={"name": "랫풀다운", "preset_id": "lat_pulldown"}).json()
        before = exercise_presets.version()
        response = self.client.put("/api/admin/presets/lat_pulldown", json=self.edit_body("lat_pulldown", name="렛 풀다운"))
        self.assertEqual(response.status_code, 200, response.text)
        member = create_user("friend@example.com", "member")
        act_as(member)
        changed = self.preset("lat_pulldown")
        self.assertEqual((changed["name"], changed["edited"]), ("렛 풀다운", True))
        self.assertTrue(changed["variants"], "grip options stay")
        self.assertNotEqual(exercise_presets.version(), before, "phones must fetch the changed list")
        act_as(self.admin)
        # A user's own exercise keeps its name; only the shared list changed.
        self.assertEqual(self.client.get(f"/api/exercises/{mine['id']}").json()["name"], "랫풀다운")
        undone = self.client.delete("/api/admin/presets/lat_pulldown").json()
        self.assertEqual((undone["result"], undone["preset"]["name"]), ("reset", "랫풀다운"))
        self.assertNotIn("edited", self.preset("lat_pulldown"))
        self.assertEqual(exercise_presets.version(), before)

    def test_hidden_presets_leave_the_picker_but_keep_working(self) -> None:
        self.client.post("/api/exercises", json={"name": "랫풀다운", "preset_id": "lat_pulldown"})
        self.assertEqual(self.client.put("/api/admin/presets/lat_pulldown/hidden", json={"hidden": True}).status_code, 200)
        self.assertTrue(self.preset("lat_pulldown")["hidden"])
        self.assertIsNone(exercise_presets.match_name("랫풀다운"), "imports no longer link to it")
        self.assertEqual(exercise_presets.variant_ids("lat_pulldown"), exercise_presets.variant_ids("lat_pulldown") | {"parallel"})
        self.client.put("/api/admin/presets/lat_pulldown/hidden", json={"hidden": False})
        self.assertNotIn("hidden", self.preset("lat_pulldown"))
        self.assertEqual(exercise_presets.match_name("랫풀다운"), "lat_pulldown")

    def test_add_use_and_delete_a_preset(self) -> None:
        created = self.client.post("/api/admin/presets", json=NEW)
        self.assertEqual(created.status_code, 201, created.text)
        preset = created.json()
        self.assertTrue(preset["id"].startswith("admin_") and preset["added"])
        self.assertEqual(preset["tags"], ["어깨", "측면 삼각근", "승모근 하부", "케이블", "기구", "고립"])
        self.assertEqual(exercise_presets.match_name("y레이즈"), preset["id"])
        used = self.client.post("/api/exercises", json={"name": "케이블 Y 레이즈", "preset_id": preset["id"]})
        self.assertEqual(used.status_code, 201, used.text)
        self.assertEqual(self.client.delete(f"/api/admin/presets/{preset['id']}").status_code, 409)
        self.client.delete(f"/api/exercises/{used.json()['id']}")
        self.assertEqual(self.client.delete(f"/api/admin/presets/{preset['id']}").json()["result"], "deleted")
        self.assertIsNone(exercise_presets.find(preset["id"]))

    def test_names_must_stay_unique(self) -> None:
        clash = self.client.post("/api/admin/presets", json={**NEW, "name": "랫 풀다운", "aliases": []})
        self.assertEqual(clash.status_code, 409)
        self.assertIn("랫풀다운", clash.json()["detail"])
        self.assertEqual(self.client.post("/api/admin/presets", json={**NEW, "aliases": ["사레레"]}).status_code, 409)
        # Keeping its own name while editing is fine.
        self.assertEqual(self.client.put("/api/admin/presets/lat_pulldown", json=self.edit_body("lat_pulldown")).status_code, 200)

    def test_values_come_from_the_lists(self) -> None:
        for changes in [{"body_part": "꼬리"}, {"equipment": "로켓"}, {"muscles": ["날개"]}, {"muscles": []}, {"kind": "yoga"}, {"tracking": "laps"}, {"name": ""}]:
            with self.subTest(changes=changes):
                self.assertIn(self.client.post("/api/admin/presets", json={**NEW, **changes}).status_code, {409, 422})
        self.assertEqual(self.client.put("/api/admin/presets/no_such", json=NEW).status_code, 404)
        self.assertEqual(self.client.delete("/api/admin/presets/bench_press").status_code, 404, "nothing to undo")

    def test_members_cannot_change_the_list(self) -> None:
        act_as(create_user("friend@example.com", "member"))
        self.assertEqual(self.client.get("/api/admin/presets").status_code, 403)
        self.assertEqual(self.client.post("/api/admin/presets", json=NEW).status_code, 403)
        self.assertEqual(self.client.put("/api/admin/presets/lat_pulldown/hidden", json={"hidden": True}).status_code, 403)
        self.assertEqual(self.client.delete("/api/admin/presets/lat_pulldown").status_code, 403)


if __name__ == "__main__":
    unittest.main()
