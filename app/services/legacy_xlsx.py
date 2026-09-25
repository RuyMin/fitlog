"""One-time adapter for the supplied Korean log workbook; never runs on startup.

Prepare needs optional openpyxl; apply needs only the normal application dependencies.
All nonempty cells and the exact original binary are archived. Plans/examples are not workouts.
"""
import argparse
import base64
import csv
import hashlib
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from app.sync_schemas import COLUMNS

KST = ZoneInfo("Asia/Seoul")


def cell_value(value):
    return value.isoformat() if isinstance(value, (datetime, date)) else value


def prepare(path: Path, directory: Path) -> dict:
    import openpyxl  # optional local conversion dependency, not a server requirement
    original = path.read_bytes()
    book = openpyxl.load_workbook(path, data_only=False)
    expected = {"12주 루틴", "러닝 기록", "웨이트 기록", "인바디 기록", "대시보드", "식사 기록", "일일 운동 기록"}
    if set(book.sheetnames) != expected:
        raise ValueError("예상한 7개 시트와 다릅니다. 원본 구조를 검토한 후 변환기를 조정하세요.")
    archive = {s.title: [{"row": i, "values": [cell_value(v) for v in row]}
               for i, row in enumerate(s.values, 1) if any(v is not None for v in row)] for s in book}
    rows = {key: [] for key in COLUMNS}
    stamp = datetime.now(timezone.utc).isoformat()
    prefix = "legacy_20260926"
    def add(key, identity, **values):
        record = {"external_id": prefix + "_" + identity, "updated_at": stamp, **values}
        rows[key].append(record)
        return record
    def memo(headers, values, source):
        return "원본: " + source + "\n" + "\n".join(str(h) + ": " + str(cell_value(v)) for h,v in zip(headers,values) if h and v is not None)
    groups = {}
    sheet = book["웨이트 기록"]
    headers = list(next(sheet.iter_rows(min_row=3,max_row=3,values_only=True)))
    strength_rows = 0
    complex_sets = 0
    for i, row in enumerate(sheet.iter_rows(min_row=4,values_only=True),4):
        if row[0] == "입력 예시":
            break
        if row[0] is None:
            continue
        if not isinstance(row[0], datetime):
            raise ValueError(f"웨이트 기록 {i}행 날짜 확인 필요")
        day, routine, exercise = row[0].date().isoformat(), row[1], row[2]
        key = (day,routine)
        if key not in groups:
            groups[key] = add("workouts", "w_" + day.replace("-","") + "_" + str(i), workout_date=day, title=routine,
                               body_part=routine, memo="웨이트 기록에서 이관. 시작·종료 시각 미기록.")
        parent = groups[key]
        strength_rows += 1
        for col, raw in enumerate(row[3:7],1):
            if raw is None:
                continue
            text = str(raw)
            weight, reps = None, None
            match = re.fullmatch(r"(\d+(?:\.\d+)?)kg×(\d+)(?:\(우/좌\))?", text)
            if match:
                weight, reps = float(match[1]), int(match[2])
            else:
                match = re.fullmatch(r"맨몸×(\d+)|좌우 합쳐 (\d+)회", text)
                if match:
                    reps = int(match[1] or match[2])
                else:
                    complex_sets += 1
            rir = float(row[8]) if row[8] is not None and re.fullmatch(r"\d+(?:\.\d+)?",str(row[8])) else None
            note = memo(headers,row,f"웨이트 기록 {i}행 / 세트{col}")
            if weight is None or reps is None:
                note += "\n중량×횟수를 단일 값으로 확정하지 않아 볼륨 합계에서 제외. 원문: " + text
            if "우/좌" in text:
                note += "\n횟수는 원문 12회(각 측) 그대로 보존; 좌우 합계로 배수 계산하지 않음."
            add("workout_sets", f"s_{i}_{col}", workout_external_id=parent["external_id"], exercise=exercise,
                set_number=col, weight=weight, reps=reps, completed=True, rir=rir, memo=note)
    for title, key, start in [("러닝 기록","run",4),("일일 운동 기록","daily",2)]:
        sheet=book[title]; headers=list(next(sheet.iter_rows(min_row=start-1,max_row=start-1,values_only=True)))
        for i,row in enumerate(sheet.iter_rows(min_row=start,values_only=True),start):
            if row[0] is None: continue
            if not isinstance(row[0],datetime): raise ValueError(f"{title} {i}행 날짜 확인 필요")
            day=row[0].date().isoformat(); note=memo(headers,row,f"{title} {i}행")
            if key=="daily" and (day,"등") in groups:
                groups[(day,"등")]["memo"] += "\n" + note
                continue
            values={"workout_date":day,"title":("걷기" if row[1]=="걷기" else "러닝 · "+str(row[1])) if key=="run" else str(row[1]),"memo":note}
            if key=="daily" and "13:30~17:30" in str(row[2]):
                values.update(started_at=day+"T13:30:00+09:00",ended_at=day+"T17:30:00+09:00")
            add("workouts",f"{key}_{i}",**values)
    sheet=book["식사 기록"]; headers=list(next(sheet.iter_rows(min_row=3,max_row=3,values_only=True)))
    for i,row in enumerate(sheet.iter_rows(min_row=4,values_only=True),4):
        if row[0] is None: continue
        if not isinstance(row[0],datetime): raise ValueError(f"식사 기록 {i}행 날짜 확인 필요")
        kind=str(row[1]); meal_type="other"
        if "점심" in kind: meal_type="lunch"
        elif "저녁" in kind: meal_type="dinner"
        elif "아침" in kind: meal_type="breakfast"
        elif any(t in kind for t in ["간식","쉐이크","후식"]): meal_type="snack"
        add("meals",f"meal_{i}",eaten_at=row[0].replace(tzinfo=KST).isoformat(),meal_type=meal_type,name=row[2],
            calories=row[4],carbohydrates=row[5],protein=row[7],fat=row[8],memo=memo(headers,row,f"식사 기록 {i}행"))
    sheet=book["인바디 기록"]; headers=list(next(sheet.iter_rows(min_row=3,max_row=3,values_only=True)))
    for i,row in enumerate(sheet.iter_rows(min_row=4,values_only=True),4):
        if row[0] is None: continue
        if not isinstance(row[0],datetime): raise ValueError(f"인바디 기록 {i}행 날짜 확인 필요")
        at=row[0].replace(tzinfo=KST); note=memo(headers,row,f"인바디 기록 {i}행")
        if "06:27 측정" in str(row[11]): at=at.replace(hour=6,minute=27)
        else: note+="\n측정 시각 미상: 날짜 정렬을 위해 00:00 Asia/Seoul로 저장. 실제 시각을 뜻하지 않음."
        add("body_metrics",f"body_{i}",measured_at=at.isoformat(),weight=row[1],skeletal_muscle=row[2],body_fat=row[3],memo=note)
    notes=["12주 루틴·대시보드·입력 예시는 원본 자료로 보존하며 실제 운동 횟수에 넣지 않았습니다.",
           "러닝/걷기 5회는 운동 세션으로 저장하고 거리·시간·심박·페이스 등은 메모와 원본 자료로 보존했습니다.",
           "드롭세트 2개와 자세 교정 1개는 원문을 유지하고 단일 중량×횟수를 만들지 않았습니다. 맨몸/코어 4세트도 중량 미상으로 볼륨 계산에서 제외합니다.",
           "어시스트 풀업 중량은 보조중량 원문 그대로입니다. 통계의 중량·볼륨은 실제 부하나 향상 정도를 뜻하지 않습니다.",
           "RIR 범위, 섭취량, 당류·나트륨 등 추가 영양소와 인바디 상세 수치는 각 기록 메모에도 보존했습니다.",
           "러닝에 반복 기재된 9/16 체중은 같은 날 인바디와 동일하여 중복 측정으로 만들지 않았습니다.",
           "수면 기록은 원본에 없어 생성하지 않았습니다. 8/31 인바디 측정 시각은 미상입니다."]
    report={"counts":{k:len(v) for k,v in rows.items()},"strength_rows":strength_rows,"complex_sets":complex_sets,
            "source_nonempty_rows":{k:len(v) for k,v in archive.items()},"notes":notes,
            "summary":f"운동 {len(rows['workouts'])}회 · 세트 {len(rows['workout_sets'])}개 · 식단 {len(rows['meals'])}건 · 인바디 {len(rows['body_metrics'])}건 이관. 원본 7개 시트 전체 보존."}
    tables={key:[cols]+[[record.get(c) for c in cols] for record in rows[key]] for key,cols in COLUMNS.items()}
    # Fail closed before producing an importable plan.
    from app.services.sync_service import parse_tables
    parse_tables(tables)
    plan={"sha256":hashlib.sha256(original).hexdigest(),"filename":path.name,"original":base64.b64encode(original).decode(),"archive":archive,"tables":tables,"report":report}
    directory.mkdir(parents=True,exist_ok=True)
    for key,table in tables.items():
        with (directory/(key+".csv")).open("w",encoding="utf-8-sig",newline="") as f: csv.writer(f).writerows(table)
    (directory/"plan.json").write_text(json.dumps(plan,ensure_ascii=False),encoding="utf-8")
    (directory/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    return report


def apply(plan_path: Path) -> dict:
    from sqlalchemy import select, text
    from app.database import SessionLocal, initialize_database
    from app.models import ImportArchive
    from app.services.sync_service import apply_rows, parse_tables
    plan=json.loads(plan_path.read_text(encoding="utf-8")); original=base64.b64decode(plan["original"],validate=True)
    if hashlib.sha256(original).hexdigest()!=plan["sha256"]: raise ValueError("원본 해시 불일치")
    parsed=parse_tables(plan["tables"])
    initialize_database()
    with SessionLocal() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        try:
            existing=session.scalar(select(ImportArchive).where(ImportArchive.sha256==plan["sha256"]))
            if existing: return {"status":"already_imported","archive_id":existing.id}
            result=apply_rows(session,parsed)
            archive=ImportArchive(sha256=plan["sha256"],filename=plan["filename"],original=original,
                                  payload=json.dumps(plan["archive"],ensure_ascii=False),report=json.dumps(plan["report"],ensure_ascii=False))
            session.add(archive); session.commit()
            return {"status":"ok","archive_id":archive.id,**result}
        except Exception:
            session.rollback(); raise


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--prepare",type=Path); group.add_argument("--apply",type=Path)
    parser.add_argument("--output",type=Path)
    args=parser.parse_args()
    if args.prepare and not args.output: parser.error("--prepare requires --output")
    print(json.dumps(prepare(args.prepare,args.output) if args.prepare else apply(args.apply),ensure_ascii=False,indent=2))
