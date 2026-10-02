from contextlib import closing
import copy
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from support import TEMP
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import Workout, WorkoutSet, Meal, SleepRecord, SyncState
from app.sync_schemas import COLUMNS
from app.services.google_sheets import SheetSnapshot, SyncError, GoogleSettings, GoogleSheetsReader
from app.services.sync_service import sync_google_sheets, parse_tables, RUN_LOCK
from app.migrations import migrate, finish_migration

STAMP = "2026-09-26T12:00:00+09:00"


def fixture():
    data = {
      "workouts": [{"external_id":"w1","workout_date":"2026-09-25","title":"Legs"}],
      "workout_sets": [{"external_id":"s1","workout_external_id":"w1","exercise":"Squat","set_number":1,"weight":60,"reps":8,"completed":"true","rpe":8,"rir":2}],
      "meals": [{"external_id":"m1","eaten_at":"2026-09-25T12:00:00+09:00","meal_type":"lunch","name":"Meal","protein":30,"image_url":"https://example.com/photo.jpg"}],
      "body_metrics": [{"external_id":"b1","measured_at":"2026-09-25T08:00:00+09:00","weight":70}],
      "sleep": [{"external_id":"z1","sleep_start":"2026-09-24T23:00:00+09:00","sleep_end":"2026-09-25T06:00:00+09:00","sleep_type":"main","duration_minutes":420}],
    }
    return {key:[cols]+[[{**row,"updated_at":STAMP}.get(c) for c in cols] for row in data[key]] for key,cols in COLUMNS.items()}


def edit(tables,key,column,value,row=1):
    tables[key][row][tables[key][0].index(column)] = value


class Reader:
    def __init__(self,tables): self.tables=tables
    def read(self): return SheetSnapshot("FitLog test",self.tables)


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.client=TestClient(app); self.client.__enter__()
        with engine.begin() as c:
            for table in reversed(Base.metadata.sorted_tables): c.execute(table.delete())
        self.env=patch.dict(os.environ,{"GOOGLE_SPREADSHEET_ID":"test_sheet_12345","GOOGLE_SERVICE_ACCOUNT_FILE":"missing.json"});self.env.start()
        self.tables=fixture()
    def tearDown(self):
        self.env.stop();self.client.__exit__(None,None,None)
    def run_sync(self): return sync_google_sheets(Reader(self.tables))
    def counts(self):
        with SessionLocal() as s:
            return {t:s.execute(text("select count(*) from "+t)).scalar() for t in ["workouts","workout_sets","exercises","meals","body_metrics","sleep_records"]}
    def test_missing_configuration_app_healthy(self):
        self.assertEqual(self.client.get("/api/health").status_code,200)
        self.assertFalse(self.client.get("/api/sync/status").json()["configured"])
        r=self.client.post("/api/sync/google",json={});self.assertEqual(r.status_code,503)
        self.assertEqual(self.counts()["workouts"],0)
    def test_insert_repeat_update_stale_and_utc(self):
        first=self.run_sync();self.assertTrue(all(first[k]["inserted"]==1 for k in COLUMNS))
        before=self.counts();second=self.run_sync();self.assertEqual(before,self.counts())
        self.assertTrue(all(second[k]["skipped"]==1 for k in COLUMNS))
        edit(self.tables,"workout_sets","weight",65);edit(self.tables,"workout_sets","updated_at","2026-09-26T13:00:00+09:00")
        self.assertEqual(self.run_sync()["workout_sets"]["updated"],1)
        with SessionLocal() as s:
            self.assertEqual(s.scalar(select(WorkoutSet)).weight,65)
            self.assertEqual(s.scalar(select(Meal)).eaten_at.hour,3)
            self.assertEqual(s.scalar(select(Meal)).image_url,"https://example.com/photo.jpg")
        edit(self.tables,"workout_sets","weight",1);edit(self.tables,"workout_sets","updated_at",STAMP)
        self.assertEqual(self.run_sync()["workout_sets"]["skipped"],1)
        self.assertEqual(self.client.get("/api/dashboard?date=2026-09-25").json()["protein_grams"],30)
    def test_source_deleted_rows_not_deleted(self):
        self.run_sync();before=self.counts()
        self.tables={k:[v[0]] for k,v in self.tables.items()};self.run_sync();self.assertEqual(before,self.counts())
    def test_unknown_nutrition_and_zero(self):
        edit(self.tables,"meals","calories",0);edit(self.tables,"meals","protein","");self.run_sync()
        with SessionLocal() as s:
            m=s.scalar(select(Meal));self.assertEqual(m.calories,0);self.assertIsNone(m.protein)
    def test_local_id_not_overwritten(self):
        with SessionLocal() as s:
            from datetime import date
            s.add(Workout(workout_date=date(2026,9,25),title="Local",external_id="w1"));s.commit()
        self.run_sync();self.assertEqual(self.counts()["workouts"],2)
    def test_bad_reference_rolls_back_everything(self):
        edit(self.tables,"workout_sets","workout_external_id","missing")
        with self.assertRaises(SyncError):self.run_sync()
        self.assertTrue(all(x==0 for x in self.counts().values()))
        self.assertEqual(self.client.get("/api/sync/status").json()["last_sync_status"],"error")
    def test_late_conflict_rolls_back_updates(self):
        self.run_sync();edit(self.tables,"workouts","title","Changed");edit(self.tables,"workouts","updated_at","2026-09-27T12:00:00+09:00")
        self.tables["workout_sets"].append(copy.deepcopy(self.tables["workout_sets"][1]));edit(self.tables,"workout_sets","external_id","s2",2)
        with self.assertRaises(SyncError):self.run_sync()
        with SessionLocal() as s:self.assertEqual(s.scalar(select(Workout)).title,"Legs")
    def test_overlap_rolls_back_all(self):
        self.tables["sleep"].append(copy.deepcopy(self.tables["sleep"][1]));edit(self.tables,"sleep","external_id","z2",2)
        with self.assertRaises(SyncError):self.run_sync()
        self.assertTrue(all(x==0 for x in self.counts().values()))
    def test_validation_duplicates_headers_numeric_dates(self):
        for key,column,value in [("workout_sets","rpe",11),("workout_sets","reps",1.5),("workout_sets","completed","maybe"),("workouts","updated_at","2026-09-26T12:00:00"),("meals","eaten_at",45000),("body_metrics","weight",True),("sleep","duration_minutes",400),("meals","image_url","javascript:alert(1)")]:
            with self.subTest(column=column):
                t=fixture();edit(t,key,column,value)
                with self.assertRaises(SyncError):parse_tables(t)
        t=fixture();t["meals"].append(t["meals"][1]);
        with self.assertRaises(SyncError):parse_tables(t)
        t=fixture();t["meals"][0].append("unknown")
        with self.assertRaises(SyncError):parse_tables(t)
        t=fixture();del t["sleep"]
        with self.assertRaises(SyncError):parse_tables(t)
    def test_safe_errors_never_echo_secret(self):
        with patch("app.services.sync_service.GoogleSheetsReader.read",side_effect=RuntimeError("private_key TOKEN secret")):
            r=self.client.post("/api/sync/google",json={})
        self.assertEqual(r.status_code,502);self.assertNotIn("secret",r.text)
        self.assertNotIn("secret",self.client.get("/api/sync/status").text)
    def test_other_spreadsheet_rejected(self):
        self.run_sync();before=self.counts()
        with patch.dict(os.environ,{"GOOGLE_SPREADSHEET_ID":"other_sheet_123"}):
            with self.assertRaises(SyncError):self.run_sync()
        self.assertEqual(before,self.counts())
    def test_lock_and_form_post_rejected(self):
        RUN_LOCK.acquire()
        try:
            with self.assertRaises(SyncError) as cm:self.run_sync()
            self.assertEqual(cm.exception.code,409)
        finally:RUN_LOCK.release()
        self.assertEqual(self.client.post("/api/sync/google").status_code,415)
        self.assertEqual(self.client.post("/api/sync/google",json={},headers={"sec-fetch-site":"cross-site"}).status_code,403)
    def test_api_assets_and_status_persist(self):
        with patch("app.services.sync_service.GoogleSheetsReader.read",return_value=Reader(self.tables).read()):
            self.assertEqual(self.client.post("/api/sync/google",json={}).status_code,200)
        engine.dispose();r=self.client.get("/api/sync/status")
        self.assertEqual(r.json()["last_sync_status"],"ok");self.assertEqual(r.headers["cache-control"],"no-store")
        for path in ["/settings","/statistics","/static/js/settings.js","/static/css/settings.css"]:self.assertEqual(self.client.get(path).status_code,200)
        self.assertEqual(self.client.get("/api/sync/archives/123").status_code,404)
    def test_google_invalid_id(self):
        with tempfile.NamedTemporaryFile() as f:
            cfg=GoogleSettings(f.name,"bad url",{k:k for k in COLUMNS})
            with self.assertRaises(SyncError) as cm:GoogleSheetsReader(cfg).read()
            self.assertIn("ID",cm.exception.message)
    def test_google_adapter_readonly_batch(self):
        from unittest.mock import MagicMock
        book=MagicMock();book.title="Test";book.values_batch_get.return_value={"valueRanges":[{"values":v} for v in self.tables.values()]}
        client=MagicMock();client.open_by_key.return_value=book
        with tempfile.NamedTemporaryFile() as f, patch("google.oauth2.service_account.Credentials.from_service_account_file") as auth, patch("google.auth.transport.requests.AuthorizedSession"), patch("gspread.Client",return_value=client):
            cfg=GoogleSettings(f.name,"valid_id_12345",{k:k for k in COLUMNS})
            snapshot=GoogleSheetsReader(cfg).read()
            self.assertEqual(snapshot.tables,self.tables)
            self.assertEqual(auth.call_args.kwargs["scopes"],["https://www.googleapis.com/auth/spreadsheets.readonly"])
            self.assertEqual(len(book.values_batch_get.call_args.args[0]),5)
            client.set_timeout.assert_called_once_with((5,25))
    def test_google_404_and_timeout(self):
        import gspread
        from requests.exceptions import Timeout
        for error in [gspread.SpreadsheetNotFound("secret"),Timeout("secret")]:
            with tempfile.NamedTemporaryFile() as f, patch("google.oauth2.service_account.Credentials.from_service_account_file"), patch("google.auth.transport.requests.AuthorizedSession"), patch("gspread.Client") as c:
                c.return_value.open_by_key.side_effect=error
                with self.assertRaises(SyncError) as cm:GoogleSheetsReader(GoogleSettings(f.name,"valid_id_12345",{k:k for k in COLUMNS})).read()
                self.assertNotIn("secret",cm.exception.message)


class MigrationTests(unittest.TestCase):
    def test_old_database_backup_and_idempotence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"fitlog.db"
            with closing(sqlite3.connect(path)) as c:
                for name in ["workouts","workout_sets","meals","body_metrics","sleep_records"]:
                    c.execute(f"CREATE TABLE {name}(id INTEGER PRIMARY KEY, memo TEXT)")
                    c.execute(f"INSERT INTO {name}(id,memo) VALUES(1,'original')")
                c.commit()
            e=create_engine("sqlite:///"+path.as_posix())
            try:
                migrate(e,path);finish_migration(e);migrate(e,path);finish_migration(e)
                with e.connect() as c:
                    self.assertEqual(c.exec_driver_sql("SELECT source,memo FROM workouts").one(),("local","original"))
                    self.assertEqual(c.exec_driver_sql("PRAGMA user_version").scalar(),2)
                backups=list((path.parent/"backups").glob("*.db"));self.assertEqual(len(backups),1)
                with closing(sqlite3.connect(backups[0])) as c:self.assertEqual(c.execute("SELECT memo FROM meals").fetchone()[0],"original")
            finally:e.dispose()
