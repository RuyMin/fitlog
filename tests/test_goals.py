import unittest
from datetime import date, datetime, timedelta, timezone

from support import create_user, fresh_owner
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import GoalProfile
from app.services import accounts

THIS_YEAR = date.today().year
# Male, 30, 175 cm, 70 kg, moderately active, maintaining:
# BMR 10×70 + 6.25×175 − 5×30 + 5 = 1648.75 → ×1.55 = 2555.6 → 2560 kcal; protein 70×1.6 = 112 g;
# (maintaining uses 1.6 g/kg) fat 25% = 71 g; carbohydrate (2560 − 448 − 639) / 4 = 368 g.
PROFILE = {"mode": "auto", "sex": "male", "birth_year": THIS_YEAR - 30, "height_cm": 175, "activity": "moderate", "aim": "maintain"}


class GoalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.client.__enter__()
        self.user = fresh_owner()

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)

    def weigh(self, kg: float, days_ago: int = 0) -> None:
        at = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
        response = self.client.post("/api/body-metrics", json={"measured_at": at, "weight": kg})
        self.assertEqual(response.status_code, 201, response.text)

    def save(self, body: dict, status: int = 200) -> dict:
        response = self.client.put("/api/me/goals", json=body)
        self.assertEqual(response.status_code, status, response.text)
        return response.json()

    def dashboard(self) -> dict:
        response = self.client.get("/api/dashboard?timezone=UTC")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def targets(self, data: dict) -> tuple:
        return (data["calorie_goal_kcal"], data["protein_goal_grams"], data["carbohydrate_goal_grams"], data["fat_goal_grams"], data["goal_source"])

    def test_without_a_profile_everyone_gets_the_defaults(self) -> None:
        data = self.client.get("/api/me/goals").json()
        self.assertFalse(data["saved"])
        self.assertEqual(data["goals"]["source"], "default")
        self.assertEqual(data["goals"], data["defaults"])
        self.assertEqual(self.targets(self.dashboard()), (2100, 150, 262, 70, "default"))

    def test_auto_goals_follow_the_latest_weight(self) -> None:
        self.weigh(70)
        data = self.save(PROFILE)
        self.assertEqual(data["estimate"]["bmr"], 1649)
        self.assertEqual(data["estimate"]["activity_factor"], 1.55)
        self.assertEqual(data["goals"], {"calorie_kcal": 2560, "protein_g": 112, "carbohydrate_g": 368, "fat_g": 71, "sleep_minutes": 420, "source": "auto"})
        self.assertEqual(self.targets(self.dashboard()), (2560, 112, 368, 71, "auto"))
        self.weigh(80)  # a new weight changes the goals without saving the profile again
        self.assertEqual(self.dashboard()["protein_goal_grams"], 128)
        self.assertEqual(self.client.get("/api/me/goals").json()["weight"], 80)

    def test_protein_per_kg_follows_the_aim(self) -> None:
        # Same body as PROFILE: losing 2160 kcal with 2.0 g/kg, gaining 2860 kcal with 1.8 g/kg; carbohydrate takes the rest.
        self.weigh(70)
        lose = self.save({**PROFILE, "aim": "lose"})
        self.assertEqual(lose["estimate"]["protein_g_per_kg"], 2.0)
        self.assertEqual(lose["goals"], {"calorie_kcal": 2160, "protein_g": 140, "carbohydrate_g": 265, "fat_g": 60, "sleep_minutes": 420, "source": "auto"})
        gain = self.save({**PROFILE, "aim": "gain"})
        self.assertEqual(gain["estimate"]["protein_g_per_kg"], 1.8)
        self.assertEqual(gain["goals"], {"calorie_kcal": 2860, "protein_g": 126, "carbohydrate_g": 411, "fat_g": 79, "sleep_minutes": 420, "source": "auto"})
        self.assertEqual(self.save(PROFILE)["estimate"]["protein_g_per_kg"], 1.6)

    def test_heavy_body_losing_still_leaves_carbohydrate(self) -> None:
        # Female, 70, 150 cm, 150 kg, sedentary, losing: the BMR floor (1930 kcal) with 300 g protein still leaves some carbohydrate.
        self.weigh(150)
        goals = self.save({"mode": "auto", "sex": "female", "birth_year": THIS_YEAR - 70, "height_cm": 150, "activity": "sedentary", "aim": "lose"})["goals"]
        self.assertEqual((goals["calorie_kcal"], goals["protein_g"]), (1930, 300))
        self.assertGreater(goals["carbohydrate_g"], 0)

    def test_auto_without_details_or_weight_keeps_the_defaults(self) -> None:
        data = self.save({"mode": "auto", "sex": "female", "height_cm": 160})
        self.assertEqual(data["missing"], ["birth_year", "weight"])
        self.assertIsNone(data["estimate"])
        self.assertEqual(data["goals"]["source"], "default")
        self.weigh(55)
        self.assertEqual(self.client.get("/api/me/goals").json()["missing"], ["birth_year"])

    def test_losing_weight_never_goes_below_resting_energy(self) -> None:
        # Female, 60, 150 cm, 45 kg, sedentary: BMR 926.5; 926.5 × 1.2 − 400 is lower, so the goal is the BMR.
        self.weigh(45)
        data = self.save({"mode": "auto", "sex": "female", "birth_year": THIS_YEAR - 60, "height_cm": 150, "activity": "sedentary", "aim": "lose"})
        self.assertEqual(data["goals"]["calorie_kcal"], 930)
        self.assertEqual(data["estimate"]["adjustment_kcal"], -400)
        self.assertEqual(data["goals"]["protein_g"], 90)

    def test_manual_goals_need_all_four_and_ignore_weight(self) -> None:
        self.assertIn("모두", self.save({"mode": "manual", "calorie_kcal": 1800}, 422)["detail"][0]["msg"])
        manual = {"mode": "manual", "calorie_kcal": 1800, "protein_g": 120, "carbohydrate_g": 180, "fat_g": 60, "sleep_minutes": 450}
        self.save({**PROFILE, **manual})
        self.weigh(90)
        dashboard = self.dashboard()
        self.assertEqual(self.targets(dashboard), (1800, 120, 180, 60, "manual"))
        self.assertEqual(dashboard["sleep_goal_minutes"], 450)
        # The body details stay, so switching back to auto needs no retyping.
        self.assertEqual(self.client.get("/api/me/goals").json()["profile"]["height_cm"], 175)

    def test_out_of_range_input_is_rejected(self) -> None:
        self.save({**PROFILE, "birth_year": THIS_YEAR - 10}, 422)
        self.save({**PROFILE, "height_cm": 300}, 422)
        self.save({**PROFILE, "sleep_minutes": 60}, 422)
        self.save({**PROFILE, "activity": "athlete"}, 422)

    def test_preview_does_not_save(self) -> None:
        self.weigh(70)
        response = self.client.post("/api/me/goals/preview", json=PROFILE)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["goals"]["calorie_kcal"], 2560)
        self.assertFalse(response.json()["saved"])
        self.assertFalse(self.client.get("/api/me/goals").json()["saved"])

    def test_delete_returns_to_the_defaults(self) -> None:
        self.weigh(70)
        self.save(PROFILE)
        self.assertEqual(self.client.delete("/api/me/goals").status_code, 200)
        self.assertFalse(self.client.get("/api/me/goals").json()["saved"])
        self.assertEqual(self.dashboard()["goal_source"], "default")

    def test_goals_are_per_user_and_removed_with_the_user(self) -> None:
        self.weigh(70)
        self.save(PROFILE)
        member = create_user("friend@example.com", "member")
        with SessionLocal() as session:
            session.add(GoalProfile(user_id=member.id, mode="manual", calorie_kcal=1500, protein_g=90, carbohydrate_g=150, fat_g=50))
            session.commit()
        self.assertEqual(self.dashboard()["calorie_goal_kcal"], 2560)
        with SessionLocal() as session:
            accounts.delete_user(session, member.id)
            self.assertIsNone(session.get(GoalProfile, member.id))
            self.assertIsNotNone(session.get(GoalProfile, self.user.id))


if __name__ == "__main__":
    unittest.main()
