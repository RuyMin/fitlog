import copy
import json
import os
import unittest
from datetime import datetime
from unittest.mock import patch, MagicMock
from tempfile import NamedTemporaryFile

from support import TEMP
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import Workout, WorkoutSet, Meal, ImportArchive
from app.services.google_sheets import SheetSnapshot, GoogleSettings, GoogleSheetsReader, SyncError
from app.services.korean_sheets import prepare_korean
from app.services.sync_service import sync_google_sheets, apply_rows, parse_tables
from app.services.legacy_xlsx import build_plan
from app.sync_schemas import COLUMNS
from test_excel_import import workbook, content


def fixture():
    book = workbook()
    return {s.title: [[v.isoformat() if isinstance(v, datetime) else v for v in row] for row in s.values] for s in book}


class Reader:
    def __init__(self, tables): self.tables = tables
    def read(self): return SheetSnapshot('Korean log', self.tables, 'korean')


class KoreanSyncTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.client.__enter__()
        with engine.begin() as c:
            for table in reversed(Base.metadata.sorted_tables): c.execute(table.delete())
        self.env = patch.dict(os.environ, {'GOOGLE_SPREADSHEET_ID': 'korean_test_123'})
        self.env.start()
        self.tables = fixture()
    def tearDown(self):
        self.env.stop()
        self.client.__exit__(None, None, None)
    def sync(self): return sync_google_sheets(Reader(self.tables))
    def count(self, model):
        with SessionLocal() as s: return s.scalar(select(func.count()).select_from(model))
    def test_insert_repeat_update_revert_and_archive(self):
        r = self.sync()
        self.assertEqual(r['workout_sets']['inserted'], 1)
        self.assertEqual(r['format'], 'korean')
        self.assertEqual(self.sync()['meals']['skipped'], 1)
        self.assertEqual(self.count(ImportArchive), 1)
        self.tables['식사 기록'][3][7] = 42
        self.assertEqual(self.sync()['meals']['updated'], 1)
        self.tables['식사 기록'][3][7] = 30
        self.assertEqual(self.sync()['meals']['updated'], 1)
        self.assertEqual(self.sync()['meals']['skipped'], 1)
        self.assertEqual(self.count(ImportArchive), 3)
        data = self.client.get('/api/sync/archives').json()
        self.assertNotIn('bindings', data[0]['report'])
        download = self.client.get('/api/sync/archives/' + str(data[0]['id']) + '/download')
        self.assertEqual(download.headers['content-type'], 'application/json')
        self.assertEqual(set(download.json()), set(self.tables))
    def test_existing_legacy_ids_are_reused(self):
        plan = build_plan(content(workbook()), 'test.xlsx')
        with SessionLocal() as s:
            apply_rows(s, parse_tables(plan['tables']))
            s.commit()
            old_id = s.scalar(select(Meal)).external_id
        self.assertEqual(self.sync()['meals']['inserted'], 0)
        with SessionLocal() as s: self.assertEqual(s.scalar(select(Meal)).external_id, old_id)
        self.assertEqual(self.count(Workout), 1)
    def test_reorder_and_blank_row_no_duplicates(self):
        self.sync()
        for name in ['웨이트 기록', '식사 기록', '인바디 기록']:
            self.tables[name].insert(3, [])
        r = self.sync()
        self.assertTrue(all(r[k]['inserted'] == 0 and r[k]['updated'] == 0 for k in COLUMNS))
    def test_local_unchanged_source_preserved_and_conflict_atomic(self):
        self.sync()
        with SessionLocal() as s:
            meal = s.scalar(select(Meal)); meal.protein = 99; s.commit()
        self.assertEqual(self.sync()['meals']['skipped'], 1)
        self.tables['웨이트 기록'][3][3] = '70kg×8'
        self.tables['식사 기록'][3][7] = 42
        with self.assertRaises(SyncError): self.sync()
        with SessionLocal() as s:
            self.assertEqual(s.scalar(select(WorkoutSet)).weight, 60)
            self.assertEqual(s.scalar(select(Meal)).protein, 99)
        self.assertEqual(self.count(ImportArchive), 1)
    def test_nonconflicting_source_edit_keeps_local_field(self):
        self.sync()
        with SessionLocal() as s:
            meal=s.scalar(select(Meal));meal.image_url='https://example.com/image.jpg';s.commit()
        self.tables['식사 기록'][3][7]=42
        self.sync()
        with SessionLocal() as s: self.assertEqual(s.scalar(select(Meal)).image_url,'https://example.com/image.jpg')
    def test_deleted_source_rows_not_deleted(self):
        self.sync()
        self.tables['식사 기록']=self.tables['식사 기록'][:3]
        self.sync()
        self.assertEqual(self.count(Meal),1)
    def test_identity_edit_rejected(self):
        self.sync()
        self.tables['식사 기록'][3][2]='renamed'
        with self.assertRaises(SyncError):self.sync()
        self.assertEqual(self.count(Meal),1)
    def test_duplicate_and_bad_date_roll_back(self):
        self.tables['식사 기록'].append(copy.deepcopy(self.tables['식사 기록'][3]))
        with self.assertRaises(SyncError): self.sync()
        self.assertEqual(self.count(Workout),0)
        self.tables=fixture();self.tables['식사 기록'][3][0]='not a date'
        with self.assertRaises(SyncError):self.sync()
    def test_daily_merge_and_running_original_time(self):
        self.tables['일일 운동 기록'].append(['2026-09-25','하체','스쿼트 수행','완료','요약',1])
        self.tables['러닝 기록'].append(['2026-09-26','Easy',5.2,'46:19:00','6:22'])
        self.tables['일일 운동 기록'].append(['2026-09-26','러닝','5.2km','완료','요약',1])
        r=self.sync()
        self.assertEqual(r['workouts']['inserted'],2)
        with SessionLocal() as s:
            run=s.scalar(select(Workout).where(Workout.title=='러닝 · Easy'))
            self.assertIn('46:19:00',run.memo)
            self.assertIsNone(run.started_at)
            self.assertIn('일일 운동 기록',run.memo)
    def test_header_bounds_and_dates(self):
        data=fixture();data['식사 기록'][3][0]='2026-09-25 7:25'
        p=prepare_korean(data)
        self.assertEqual(p['rows']['meals'][0].eaten_at.hour,7)
        data['식사 기록'][2][0]='wrong'
        with self.assertRaises(SyncError):prepare_korean(data)
        data=fixture();data['대시보드']=[[]]*5001
        with self.assertRaises(SyncError):prepare_korean(data)
    def test_transport_auto_detects_readonly_korean(self):
        book=MagicMock();book.title='Korean'
        book.worksheets.return_value=[type('Sheet',(),{'title':k})() for k in self.tables]
        book.values_batch_get.return_value={'valueRanges':[{'values':self.tables[k]} for k in sorted(self.tables)]}
        client=MagicMock();client.open_by_key.return_value=book
        with NamedTemporaryFile() as f, patch('google.oauth2.service_account.Credentials.from_service_account_file') as auth, patch('google.auth.transport.requests.AuthorizedSession'), patch('gspread.Client',return_value=client):
            snapshot=GoogleSheetsReader(GoogleSettings(f.name,'korean_test_123',{k:k for k in COLUMNS})).read()
            self.assertEqual(snapshot.format,'korean')
            self.assertEqual(snapshot.tables,self.tables)
            self.assertEqual(auth.call_args.kwargs['scopes'],['https://www.googleapis.com/auth/spreadsheets.readonly'])
            self.assertTrue(all(r.endswith('A1:AY5001') for r in book.values_batch_get.call_args.args[0]))

    def test_undated_row_and_records_after_example_rejected(self):
        data=fixture();data['식사 기록'][3][0]=''
        with self.assertRaises(SyncError):prepare_korean(data)
        data=fixture();data['웨이트 기록'].extend([['입력 예시'],['2026-09-15','상체 A','벤치프레스','60×8']])
        self.assertEqual(len(prepare_korean(data)['rows']['workout_sets']),1)
        data['웨이트 기록'].append(['2026-10-03','하체','스쿼트','70kg×8'])
        with self.assertRaises(SyncError):prepare_korean(data)
