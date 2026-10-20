"""Natural-language assistant: per-user encrypted keys, consent and quota gates, drafts, atomic save.

Claude is never called: the network layer is replaced in every test.
"""
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from support import TEMP, act_as, create_user, fresh_owner
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import config
from app.database import SessionLocal
from app.main import app
from app.models import AiCredential, AiUsage, BodyMetric, Consent, Exercise, Meal, SleepRecord, Workout, WorkoutSet
from app.services import accounts, claude_records
from app.services.claude_records import AssistantError

KEY = "sk-ant-api03-" + "x" * 40
SECRET = {"FITLOG_SECRET_KEY": "s" * 48}
MEAL = {"eaten_at": "2026-10-20T12:30:00+09:00", "meal_type": "lunch", "name": "제육덮밥",
        "calories": None, "protein": None, "carbohydrates": None, "fat": None, "memo": None}
DRAFT = {
    "meals": [MEAL, {**MEAL, "name": "닭가슴살", "protein": -5}],
    "body_metrics": [{"measured_at": "2026-10-20T07:30:00+09:00", "weight": 72.4, "body_fat": None, "skeletal_muscle": None, "memo": None}],
    "sleep": [{"sleep_start": "2026-10-20T00:30:00+09:00", "sleep_end": "2026-10-20T07:00:00+09:00", "sleep_type": "main", "memo": None}],
    "workouts": [{"workout_date": "2026-10-20", "title": "하체", "body_part": None, "memo": None, "sets": [
        {"exercise": "스쿼트", "set_number": 1, "weight": 60, "reps": 8, "completed": True}]}],
    "unparsed": ["기분 좋음"],
}


def count(model, *where):
    with SessionLocal() as s:
        return s.scalar(select(func.count()).select_from(model).where(*where))


class AssistantApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.__enter__()
        self.user = fresh_owner()
        self.env = patch.dict(os.environ, SECRET)
        self.env.start()
        self.addCleanup(self.env.stop)

    def tearDown(self):
        self.client.__exit__(None, None, None)

    def consent(self, user=None):
        with SessionLocal() as s:
            accounts.grant_ai_consent(s, (user or self.user).id)

    def register(self):
        with patch.object(claude_records, "verify_key") as verify:
            r = self.client.put("/api/assistant/key", json={"api_key": KEY})
        self.assertEqual(r.status_code, 200, r.text)
        return verify

    def draft(self, result=DRAFT, text="오늘 점심 제육덮밥"):
        with patch.object(claude_records, "extract", return_value=json.loads(json.dumps(result))) as extract:
            r = self.client.post("/api/assistant/draft", json={"text": text, "timezone": "Asia/Seoul"})
        self.extract = extract
        return r

    def test_key_is_verified_encrypted_and_never_returned(self):
        verify = self.register()
        verify.assert_called_once_with(KEY, config.AI_MODEL)
        with SessionLocal() as s:
            stored = s.get(AiCredential, self.user.id)
            self.assertNotIn(KEY.encode(), stored.ciphertext)
            self.assertNotIn("x" * 20, stored.hint)
        status = self.client.get("/api/assistant/status").json()
        self.assertEqual(status["key_hint"], KEY[:10] + "…" + KEY[-4:])
        self.assertNotIn(KEY, json.dumps(status))
        self.assertEqual(self.client.delete("/api/assistant/key").status_code, 200)
        self.assertIsNone(self.client.get("/api/assistant/status").json()["key_hint"])

    def test_bad_keys_and_missing_server_secret_store_nothing(self):
        for bad in ["not-a-key", "sk-ant- has space", "sk-ant-short"]:
            self.assertEqual(self.client.put("/api/assistant/key", json={"api_key": bad}).status_code, 422, bad)
        with patch.object(claude_records, "verify_key", side_effect=AssistantError("invalid_key", 400)):
            r = self.client.put("/api/assistant/key", json={"api_key": KEY})
        self.assertEqual((r.status_code, r.json()["detail"]), (400, {"code": "invalid_key"}))
        with patch.dict(os.environ, {"FITLOG_SECRET_KEY": "short"}), patch.object(claude_records, "verify_key") as verify:
            r = self.client.put("/api/assistant/key", json={"api_key": KEY})
            self.assertEqual(r.json()["detail"], {"code": "server_not_configured"})
            verify.assert_not_called()
            self.assertFalse(self.client.get("/api/assistant/status").json()["server_ready"])
        self.assertEqual(count(AiCredential), 0)

    def test_draft_needs_consent_and_key(self):
        self.assertEqual(self.draft().json()["detail"], {"code": "no_consent"})
        self.consent()
        self.assertEqual(self.draft().json()["detail"], {"code": "no_key"})
        self.extract.assert_not_called()
        self.assertEqual(count(AiUsage), 0)

    def test_draft_sends_only_text_time_and_own_exercises(self):
        self.consent()
        self.register()
        other = create_user("friend@example.com", "member")
        with SessionLocal() as s:
            s.add_all([Exercise(user_id=self.user.id, name="스쿼트"), Exercise(user_id=other.id, name="남의 종목")])
            s.commit()
        r = self.draft()
        self.assertEqual(r.status_code, 200, r.text)
        key, model, text, now, zone, exercises = self.extract.call_args.args
        self.assertEqual((key, model, text, zone, exercises), (KEY, config.AI_MODEL, "오늘 점심 제육덮밥", "Asia/Seoul", ["스쿼트"]))
        self.assertEqual(now.utcoffset().total_seconds(), 9 * 3600)
        data = r.json()
        self.assertEqual([m["errors"] for m in data["meals"]][0], [])
        self.assertEqual(data["meals"][1]["errors"], ["단백질: 0 이상이어야 합니다."])
        self.assertEqual(data["workouts"][0]["data"]["sets"][0]["exercise"], "스쿼트")
        self.assertEqual(data["unparsed"], ["기분 좋음"])
        # Drafting stores no record.
        self.assertEqual((count(Meal), count(Workout), count(SleepRecord), count(BodyMetric)), (0, 0, 0, 0))

    def test_daily_limit_counts_failed_attempts(self):
        self.consent()
        self.register()
        with patch.object(config, "AI_DAILY_LIMIT", 2):
            with patch.object(claude_records, "extract", side_effect=AssistantError("unreachable", 504)):
                self.assertEqual(self.client.post("/api/assistant/draft", json={"text": "a"}).status_code, 504)
            self.assertEqual(self.draft().status_code, 200)
            r = self.draft()
            self.assertEqual((r.status_code, r.json()["detail"]), (429, {"code": "daily_limit"}))
            self.extract.assert_not_called()
            self.assertEqual(self.client.get("/api/assistant/status").json()["used_today"], 2)

    def test_rotated_server_secret_asks_to_register_again(self):
        self.consent()
        self.register()
        with patch.dict(os.environ, {"FITLOG_SECRET_KEY": "t" * 48}):
            self.assertEqual(self.draft().json()["detail"], {"code": "key_unreadable"})

    def test_keys_and_consent_are_per_user(self):
        self.consent()
        self.register()
        other = create_user("friend@example.com", "member")
        act_as(other)
        status = self.client.get("/api/assistant/status").json()
        self.assertEqual((status["key_hint"], status["consent"]), (None, False))
        self.assertEqual(self.draft().json()["detail"], {"code": "no_consent"})

    def commit(self, body):
        return self.client.post("/api/assistant/commit", json=body)

    def confirmed(self):
        body = {kind: [i for i in DRAFT[kind] if kind != "meals" or i["protein"] is None] for kind in ["meals", "body_metrics", "sleep", "workouts"]}
        return json.loads(json.dumps(body))

    def test_commit_saves_everything_for_this_user(self):
        other = create_user("friend@example.com", "member")
        with SessionLocal() as s:
            s.add(Exercise(user_id=other.id, name="스쿼트"))
            s.commit()
        body = self.confirmed()
        body["workouts"][0]["sets"].append({"exercise": "레그프레스", "set_number": 1, "weight": 100, "reps": 12, "completed": True})
        r = self.commit(body)
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(r.json(), {"meals": 1, "body_metrics": 1, "sleep": 1, "workouts": 1, "sets": 2})
        with SessionLocal() as s:
            meal = s.scalar(select(Meal))
            self.assertEqual((meal.user_id, meal.eaten_at.hour), (self.user.id, 3))
            sleep = s.scalar(select(SleepRecord))
            self.assertEqual(sleep.duration_minutes, 390)
            names = s.scalars(select(Exercise.name).where(Exercise.user_id == self.user.id).order_by(Exercise.name)).all()
            self.assertEqual(names, ["레그프레스", "스쿼트"])
            self.assertEqual(s.scalar(select(func.count()).select_from(WorkoutSet).where(WorkoutSet.user_id == self.user.id)), 2)

    def test_commit_is_all_or_nothing(self):
        self.commit(self.confirmed())
        before = (count(Meal), count(Workout), count(SleepRecord))
        # Same sleep again overlaps -> nothing in the request is saved, including the new meal.
        body = self.confirmed()
        body["meals"][0]["name"] = "새 메뉴"
        r = self.commit(body)
        self.assertEqual(r.status_code, 409, r.text)
        self.assertEqual((count(Meal), count(Workout), count(SleepRecord)), before)
        bad = {"meals": [{**MEAL, "protein": -1}], "sleep": []}
        r = self.commit(bad)
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.json()["detail"][0]["loc"][:3], ["body", "meals", 0])
        duplicate = self.confirmed()
        duplicate.update(sleep=[], meals=[], body_metrics=[])
        duplicate["workouts"][0]["sets"].append(dict(duplicate["workouts"][0]["sets"][0]))
        self.assertEqual(self.commit(duplicate).status_code, 409)
        self.assertEqual((count(Meal), count(Workout), count(SleepRecord)), before)
        self.assertEqual(self.commit({}).status_code, 422)


def fake_response(stop_reason="end_turn", text=None):
    body = json.dumps({"meals": [], "body_metrics": [], "sleep": [], "workouts": [], "unparsed": []}) if text is None else text
    return SimpleNamespace(stop_reason=stop_reason, content=[SimpleNamespace(type="thinking"), SimpleNamespace(type="text", text=body)])


class ClaudeCallTests(unittest.TestCase):
    def run_extract(self, response=None, error=None, model="claude-opus-5-5"):
        calls = {}

        class Messages:
            def create(self, **kwargs):
                calls.update(kwargs)
                if error:
                    raise error
                return response or fake_response()

        fake = SimpleNamespace(beta=SimpleNamespace(messages=Messages()))
        from datetime import datetime
        from zoneinfo import ZoneInfo
        with patch.object(claude_records, "client_for", return_value=fake) as client_for:
            result = claude_records.extract(KEY, model, "점심 제육", datetime(2026, 10, 20, 9, 0, tzinfo=ZoneInfo("Asia/Seoul")), "Asia/Seoul", ["스쿼트"])
        client_for.assert_called_once_with(KEY)
        return result, calls

    def test_request_shape(self):
        result, calls = self.run_extract()
        self.assertEqual(result["meals"], [])
        self.assertEqual(calls["model"], "claude-opus-5-5")
        self.assertEqual(calls["output_config"]["effort"], "low")
        self.assertEqual(calls["output_config"]["format"], {"type": "json_schema", "schema": claude_records.SCHEMA})
        self.assertEqual((calls["betas"], calls["fallbacks"]), ([claude_records.FALLBACK_BETA], "default"))
        content = calls["messages"][0]["content"]
        self.assertIn("<journal>\n점심 제육\n</journal>", content)
        self.assertIn("2026-10-20T09:00+09:00", content)
        self.assertIn("스쿼트", content)
        self.assertNotIn(KEY, json.dumps(calls, default=str))

    def test_haiku_has_no_fallback(self):
        _, calls = self.run_extract(model="claude-haiku-5-5")
        self.assertNotIn("fallbacks", calls)
        self.assertNotIn("betas", calls)

    def test_schema_objects_are_closed_and_fully_required(self):
        def walk(node):
            if isinstance(node, dict):
                if node.get("type") == "object":
                    self.assertIs(node["additionalProperties"], False)
                    self.assertEqual(set(node["required"]), set(node["properties"]))
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)
        walk(claude_records.SCHEMA)

    def test_stop_reasons_and_bad_output(self):
        for response, code in [(fake_response("refusal"), "refused"), (fake_response("max_tokens"), "too_long"),
                               (fake_response(text="not json"), "unreadable"), (fake_response(text="[]"), "unreadable")]:
            with self.subTest(code=code), self.assertRaises(AssistantError) as raised:
                self.run_extract(response)
            self.assertEqual(raised.exception.code, code)

    def test_api_errors_map_to_safe_codes(self):
        import anthropic
        import httpx2
        request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")

        def status(cls, code):
            return cls("secret upstream detail", response=httpx2.Response(code, request=request), body=None)
        cases = [(status(anthropic.AuthenticationError, 401), "invalid_key"), (status(anthropic.PermissionDeniedError, 403), "key_forbidden"),
                 (status(anthropic.RateLimitError, 429), "rate_limited"), (status(anthropic.BadRequestError, 400), "request_rejected"),
                 (status(anthropic.InternalServerError, 500), "upstream"), (anthropic.APIConnectionError(request=request), "unreachable")]
        for error, code in cases:
            with self.subTest(code=code), self.assertRaises(AssistantError) as raised:
                self.run_extract(error=error)
            self.assertEqual(raised.exception.code, code)
            self.assertNotIn("secret", str(raised.exception))


class AssistantPageTests(unittest.TestCase):
    def test_pages_include_assistant(self):
        client = TestClient(app)
        home = client.get("/").text
        self.assertIn('id="assistant-form"', home)
        self.assertIn("/static/js/assistant.js", home)
        settings = client.get("/settings").text
        self.assertIn('id="ai-key"', settings)
        self.assertIn('type="password"', settings)


if __name__ == "__main__":
    unittest.main()
