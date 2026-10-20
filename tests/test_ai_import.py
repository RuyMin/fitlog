"""AI-assisted Excel import: an arbitrary workbook is mapped by Claude, reviewed, then committed.

Claude is never called: claude_import.extract is replaced in every test.
"""
import json
import os
import unittest
from io import BytesIO
from unittest.mock import patch

from support import TEMP, act_as, create_user, fresh_owner
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import func, select

from app import config
from app.database import SessionLocal
from app.main import app
from app.models import AiCredential, AiUsage, BodyMetric, Meal, SleepRecord, Workout, WorkoutSet
from app.services import accounts, assistant, claude_import, excel_import

MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
KEY = "sk-ant-api03-" + "x" * 40
SECRET = {"FITLOG_SECRET_KEY": "s" * 48}

# What the model "returns" for an arbitrary workbook: one of each record type, one invalid meal, one unmapped row.
DRAFT = {
    "meals": [
        {"eaten_at": "2026-09-25T12:30:00+09:00", "meal_type": "lunch", "name": "제육덮밥",
         "calories": 700, "protein": 35, "carbohydrates": 90, "fat": 20, "nutrition_estimated": True, "memo": None},
        {"eaten_at": "2026-09-25T19:00:00+09:00", "meal_type": "dinner", "name": "닭가슴살",
         "calories": None, "protein": -5, "carbohydrates": None, "fat": None, "nutrition_estimated": False, "memo": None},
    ],
    "body_metrics": [{"measured_at": "2026-09-25T07:30:00+09:00", "weight": 72.4, "body_fat": 18.0, "skeletal_muscle": None, "memo": None}],
    "sleep": [{"sleep_start": "2026-09-24T23:30:00+09:00", "sleep_end": "2026-09-25T07:00:00+09:00", "sleep_type": "main", "memo": None}],
    "workouts": [{"workout_date": "2026-09-25", "title": "하체", "body_part": "하체", "memo": None, "sets": [
        {"exercise": "스쿼트", "set_number": 1, "weight": 60, "reps": 8, "completed": True},
        {"exercise": "스쿼트", "set_number": 2, "weight": 60, "reps": 8, "completed": True}]}],
    "unparsed": ["메모 탭: 컨디션 좋음"],
}


def book_bytes(rows=3):
    book = Workbook()
    sheet = book.active
    sheet.title = "내 기록"
    sheet.append(["날짜", "항목", "값"])
    for i in range(rows):
        sheet.append(["2026-09-25", f"행{i}", i])
    buf = BytesIO()
    book.save(buf)
    book.close()
    return buf.getvalue()


def count(model, *where):
    with SessionLocal() as s:
        return s.scalar(select(func.count()).select_from(model).where(*where))


class AiImportTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.__enter__()
        self.user = fresh_owner()
        self.env = patch.dict(os.environ, SECRET)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.original = book_bytes()

    def tearDown(self):
        self.client.__exit__(None, None, None)

    def consent(self, user=None):
        with SessionLocal() as s:
            accounts.grant_ai_consent(s, (user or self.user).id)

    def register(self):
        with patch.object(assistant.claude_records, "verify_key"):
            r = self.client.put("/api/assistant/key", json={"api_key": KEY})
        self.assertEqual(r.status_code, 200, r.text)

    def preview(self, result=DRAFT, data=None, timezone="Asia/Seoul"):
        with patch.object(claude_import, "extract", return_value=json.loads(json.dumps(result))) as extract:
            r = self.client.post(f"/api/import/preview?filename=a.xlsx&timezone={timezone}",
                                 content=self.original if data is None else data, headers={"content-type": MIME})
        self.extract = extract
        return r

    def test_consent_and_key_are_required_before_any_call(self):
        self.register()
        r = self.preview()
        self.assertEqual((r.status_code, r.json()["detail"][:4]), (403, "AI 외"))
        self.extract.assert_not_called()
        # Consent without a key.
        self.consent()
        with SessionLocal() as s:
            assistant.delete_key(s)
        r = self.preview()
        self.assertEqual(r.status_code, 400)
        self.extract.assert_not_called()
        self.assertEqual(count(AiUsage), 0)

    def test_maps_arbitrary_sheet_and_commits(self):
        self.consent()
        self.register()
        r = self.preview()
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        # The invalid meal (protein -5) is dropped into unparsed; everything else maps.
        self.assertEqual(body["counts"].get("new"), 6)  # 1 meal + 1 body + 1 sleep + 1 workout + 2 sets
        self.assertTrue(any("닭가슴살" in u for u in body["unparsed"]))
        self.assertTrue(any("메모 탭" in u for u in body["unparsed"]))
        # The sheet cells reached the model, nothing else.
        sheets = self.extract.call_args.args[2]
        self.assertIn("내 기록", sheets)
        self.assertEqual(self.extract.call_args.args[4], "Asia/Seoul")
        selected = [e["key"] for e in body["entries"] if e["status"] == "new"]
        saved = self.client.post(f"/api/import/{body['token']}/commit", json={"selected": selected})
        self.assertEqual(saved.status_code, 200, saved.text)
        with SessionLocal() as s:
            meal = s.scalar(select(Meal))
            self.assertEqual((meal.name, meal.calories, meal.user_id), ("제육덮밥", 700, self.user.id))
            self.assertEqual(meal.memo, assistant.ESTIMATE_NOTE)  # estimated nutrition is labelled in the saved memo
            self.assertEqual(s.scalar(select(SleepRecord)).duration_minutes, 450)
            self.assertEqual(s.scalar(select(func.count()).select_from(WorkoutSet)), 2)
            self.assertEqual(s.scalar(select(BodyMetric)).weight, 72.4)

    def test_row_limit_and_bad_timezone_and_empty(self):
        self.consent()
        self.register()
        r = self.preview(data=book_bytes(rows=excel_import.AI_ROW_LIMIT + 1))
        self.assertEqual(r.status_code, 422)
        self.extract.assert_not_called()
        r = self.preview(timezone="Mars/Olympus")
        self.assertEqual(r.status_code, 422)
        self.extract.assert_not_called()
        empty = Workbook(); empty.active.title = "빈"; buf = BytesIO(); empty.save(buf); empty.close()
        r = self.preview(data=buf.getvalue())
        self.assertEqual(r.status_code, 422)
        self.assertEqual(count(AiUsage), 0)

    def test_quota_counts_and_blocks(self):
        self.consent()
        self.register()
        with patch.object(config, "AI_DAILY_LIMIT", 1):
            self.assertEqual(self.preview().status_code, 200)
            r = self.preview()
            self.assertEqual(r.status_code, 429)
            self.extract.assert_not_called()
        self.assertEqual(self.client.get("/api/assistant/status").json()["used_today"], 1)

    def test_members_can_import_with_the_shared_key(self):
        self.register()
        member = create_user("friend@example.com", "member")
        self.consent(member)
        act_as(member)
        r = self.preview()
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.extract.call_args.args[0], KEY)
        with SessionLocal() as s:
            self.assertEqual(dict(s.execute(select(AiUsage.user_id, AiUsage.count)).all()), {member.id: 1})


class AiImportPageTests(unittest.TestCase):
    def test_settings_page_wires_ai_import(self):
        client = TestClient(app)
        settings = client.get("/settings").text
        self.assertIn('id="excel-timezone"', settings)
        self.assertIn("AI가 양식을 분석", settings)
        self.assertIn("/api/import", client.get("/static/js/excel-import.js").text)


if __name__ == "__main__":
    unittest.main()
