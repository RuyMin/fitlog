"""Adapter for the existing Korean workbook. Google I/O stays in google_sheets.py.

No source cells are modified. Semantic identities survive row sorting. Immutable
JSON snapshots retain all fetched cells, including non-record tabs and extra data.
"""
import hashlib
import json
import re
from datetime import date, datetime, timezone

from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Exercise, ImportArchive, utc_now
from app.services.google_sheets import SyncError
from app.services.legacy_xlsx import convert_book

SHEETS = {"12주 루틴", "러닝 기록", "웨이트 기록", "인바디 기록", "대시보드", "식사 기록", "일일 운동 기록"}
RECORD_SHEETS = SHEETS - {"12주 루틴", "대시보드"}


def prepare_korean(tables: dict[str, list[list]]) -> dict:
    """Validate bounded API values and adapt date cells to the shared converter."""
    if set(tables) != SHEETS:
        raise SyncError("한글 통합기록의 7개 시트가 모두 필요합니다.")
    if any(len(rows) > 5000 or any(len(row) > 50 for row in rows) for rows in tables.values()):
        raise SyncError("한글 시트는 각각 5,000행·50열까지 지원합니다.")
    if sum(sum(len(row) for row in rows) for rows in tables.values()) > 200000:
        raise SyncError("한글 시트의 셀 수가 너무 많습니다.")
    archive = {name: [{"row": i, "values": row} for i, row in enumerate(rows, 1)
                      if any(v is not None and v != "" for v in row)] for name, rows in tables.items()}
    original = json.dumps(archive, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()
    if len(original) > 10 * 1024 * 1024:
        raise SyncError("한글 시트 원본은 10MB 이하이어야 합니다.")
    book = Workbook()
    book.remove(book.active)
    try:
        for name, rows in tables.items():
            sheet = book.create_sheet(name)
            start = 2 if name == "일일 운동 기록" else 4
            example = False
            example_record_seen = False
            for number, cells in enumerate(rows, 1):
                values = [None if v == "" else v for v in cells]
                if name in RECORD_SHEETS and number >= start and values:
                    if values[0] == "입력 예시":
                        example = True
                    if not example and values[0] is None and any(v is not None for v in values[1:]):
                        raise SyncError(f"{name} {number}행: 내용이 있는 기록에는 날짜가 필요합니다.")
                    if example and re.match(r"^\d{4}[-.]", str(values[0])):
                        if example_record_seen:
                            raise SyncError(f"{name} {number}행: 새 기록은 '입력 예시' 행 위에 추가해 주세요.")
                        example_record_seen = True
                    if values[0] is not None and not example:
                        try:
                            # Accept ISO dates and Korean Sheets' yyyy. m. d. display.
                            raw = str(values[0]).strip()
                            raw = re.sub(r"^(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.?", lambda m: f"{m[1]}-{int(m[2]):02}-{int(m[3]):02}", raw)
                            raw = re.sub(r" (\d):", r" 0\1:", raw)
                            values[0] = datetime.fromisoformat(raw)
                            if values[0].tzinfo is not None:
                                from app.services.legacy_xlsx import KST
                                values[0] = values[0].astimezone(KST).replace(tzinfo=None)
                        except (TypeError, ValueError):
                            raise SyncError(f"{name} {number}행: 날짜를 YYYY-MM-DD 또는 YYYY-MM-DD HH:mm 형식으로 입력해 주세요.") from None
                sheet.append(values)
        converted, report = convert_book(book, archive, merge_legacy_daily=False)
    except ValueError as exc:
        raise SyncError(str(exc)) from None
    finally:
        book.close()
    from app.services.sync_service import parse_tables
    rows = parse_tables(converted)
    # A daily summary supplements an unambiguous detailed session; never merge on date alone.
    workouts = rows["workouts"]
    details = [w for w in workouts if "_daily_" not in w.external_id]
    merged = 0
    for daily in list(workouts):
        if "_daily_" not in daily.external_id:
            continue
        candidates = [w for w in details if w.workout_date == daily.workout_date and
                      (w.title == daily.title or daily.title.startswith(w.title + " + ") or
                       (daily.title == "러닝" and w.title.startswith("러닝 · ")))]
        if len(candidates) == 1:
            parent = candidates[0]
            parent.memo = (parent.memo or "") + "\n" + (daily.memo or "")
            workouts.remove(daily)
            merged += 1
    report["counts"] = {key: len(value) for key, value in rows.items()}
    report["notes"].extend([
        "한글 Sheets: 행 순서 대신 날짜·이름·세트 번호로 기존 기록과 비교하며 변경된 값만 반영합니다.",
        "러닝 시간은 표시 원문 그대로 보존합니다. 46:19:00 등을 임의로 분·초 또는 시·분·초로 해석하지 않습니다.",
        "수면 시작·종료 기록이 없어 수면 레코드는 만들지 않습니다. 원본 수면(시간) 값은 메모에 보존합니다.",
    ])
    report["summary"] = f"한글 Google Sheets 원본 7개 탭 보존 · 일일 요약 {merged}건을 상세 운동에 연결."
    return {"rows": rows, "archive": archive, "original": original, "report": report}


def entry_identity(entry: dict, entries: dict) -> str:
    from app.services.excel_import import identity
    value = identity(entry["kind"], entry["incoming"])
    if entry["parent"] is not None:
        parent = entries[entry["parent"]]
        value = (identity("workouts", parent["incoming"]), *value)
    return json.dumps([entry["kind"], value], ensure_ascii=False)


def apply_korean(session: Session, plan: dict, spreadsheet_id: str) -> dict:
    """Caller owns one transaction for records, snapshot and sync state."""
    from app.services.excel_import import compare, normalized
    from app.services.sync_service import MODELS
    filename = f"google-sheets-{spreadsheet_id}.json"
    previous = session.scalar(select(ImportArchive).where(ImportArchive.filename == filename).order_by(ImportArchive.id.desc()))
    baseline = json.loads(previous.report).get("bindings", {}) if previous else {}
    entries = {e["key"]: e for e in compare(session, plan["rows"])}
    identities = {key: entry_identity(e, entries) for key, e in entries.items()}
    current = set(identities.values())
    # Without an explicit source ID, renames cannot safely be distinguished from delete+add.
    for kind in MODELS:
        old = {k for k, v in baseline.items() if v["kind"] == kind}
        new = {identities[k] for k, e in entries.items() if e["kind"] == kind}
        if old - current and new - set(baseline):
            raise SyncError("기록의 날짜·이름·세트 식별값 변경 또는 삭제와 추가가 함께 감지됐습니다. 중복 방지를 위해 취소했습니다. 기존 식별값을 복원한 뒤 다시 동기화해 주세요.", 409)
    counts = {key: {"inserted": 0, "updated": 0, "skipped": 0} for key in MODELS}
    ids = {key: e["target_id"] for key, e in entries.items()}
    bindings = dict(baseline)
    for key, entry in entries.items():
        kind, ident = entry["kind"], identities[key]
        old = baseline.get(ident)
        if entry["status"] == "conflict" or (old and old["id"] != entry["target_id"]):
            raise SyncError("같은 날짜·이름의 기록이 중복되거나 연결된 기록이 바뀌었습니다. 기존 데이터 확인 후 다시 동기화해 주세요.", 409)
        incoming = normalized(entry["incoming"])
        before = normalized(entry["before"]) if entry["before"] else None
        changed = list(incoming) if before is None else [k for k in incoming if incoming[k] != before.get(k)]
        if old:
            # Unchanged Sheet fields never overwrite a local edit.
            changed = [k for k in changed if incoming[k] != old["values"].get(k)]
            if any(before.get(k) != old["values"].get(k) for k in changed):
                raise SyncError("동일한 항목이 FitLog와 Google Sheets 양쪽에서 수정되었습니다. 값을 일치시킨 후 다시 동기화해 주세요.", 409)
        model = MODELS[kind]
        record = session.get(model, entry["target_id"]) if entry["target_id"] is not None else model(
            source="google_sheets", external_id="ko_" + hashlib.sha256((spreadsheet_id + ident).encode()).hexdigest())
        if changed:
            values = {k: entry["incoming"][k] for k in changed}
            if kind == "workout_sets":
                name = entry["incoming"]["exercise"]
                exercise = session.scalar(select(Exercise).where(Exercise.name == name))
                if exercise is None:
                    exercise = Exercise(name=name)
                    session.add(exercise)
                    session.flush()
                values.pop("exercise", None)
                values.update(workout_id=ids[entry["parent"]], exercise_id=exercise.id)
            for name, value in values.items():
                if value is not None and name == "workout_date":
                    value = date.fromisoformat(value)
                elif value is not None and name in {"started_at", "ended_at", "eaten_at", "measured_at", "sleep_start", "sleep_end"}:
                    value = datetime.fromisoformat(value).astimezone(timezone.utc).replace(tzinfo=None)
                setattr(record, name, value)
            record.source_updated_at = utc_now()
            session.add(record)
            session.flush()
            ids[key] = record.id
            counts[kind]["inserted" if entry["target_id"] is None else "updated"] += 1
        else:
            counts[kind]["skipped"] += 1
        bindings[ident] = {"kind": kind, "id": record.id, "values": incoming}
    # Reverting to an older snapshot is a new version, not a jump to stale bindings.
    if previous and previous.original == plan["original"] and baseline == bindings:
        return {**counts, "format": "korean", "archive_id": previous.id}
    digest = hashlib.sha256((spreadsheet_id + (previous.sha256 if previous else "")).encode() + plan["original"] +
                            json.dumps(bindings, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    archive = session.scalar(select(ImportArchive).where(ImportArchive.sha256 == digest))
    if archive is None:
        archive = ImportArchive(sha256=digest, filename=filename, original=plan["original"],
            payload=json.dumps(plan["archive"], ensure_ascii=False),
            report=json.dumps({**plan["report"], "bindings": bindings}, ensure_ascii=False))
        session.add(archive)
        session.flush()
    return {**counts, "format": "korean", "archive_id": archive.id}
