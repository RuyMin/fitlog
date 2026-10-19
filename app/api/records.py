from datetime import date as Date, datetime
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AwareDatetime
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser
from app.database import get_session
from app.models import Meal, BodyMetric, SleepRecord
from app.schemas import (
    MealInput, MealResponse, BodyMetricInput, BodyMetricResponse,
    SleepInput, SleepResponse, DeleteResponse, DashboardResponse,
)
from app.services import records, dashboard

router = APIRouter(prefix="/api", tags=["daily records"])
DB = Annotated[Session, Depends(get_session)]


def validate_range(
    from_at: AwareDatetime | None = None, to_at: AwareDatetime | None = None,
) -> tuple[datetime | None, datetime | None]:
    if from_at is not None and to_at is not None and from_at >= to_at:
        raise HTTPException(422, "조회 시작 시각은 종료 시각보다 이전이어야 합니다.")
    return from_at, to_at


TimeRange = Annotated[tuple[datetime | None, datetime | None], Depends(validate_range)]


@router.get("/dashboard", response_model=DashboardResponse)
def get_dashboard(db: DB, user: CurrentUser, date: Date | None = None, timezone: str = "Asia/Seoul") -> DashboardResponse:
    try:
        zone = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise HTTPException(422, "올바른 IANA 시간대를 지정해 주세요. 예: Asia/Seoul") from None
    day = date or datetime.now(zone).date()
    if day == Date.max:
        raise HTTPException(422, "지원하지 않는 조회 날짜입니다.")
    return dashboard.get_dashboard(db, user.id, day, zone)


@router.get("/meals", response_model=list[MealResponse])
def list_meal(db: DB, time_range: TimeRange, user: CurrentUser, limit: Annotated[int, Query(ge=1, le=100)] = 50, offset: Annotated[int, Query(ge=0)] = 0) -> list[Meal]:
    return records.list_records(db, user.id, Meal, Meal.eaten_at, limit, offset, *time_range)


@router.get("/meals/{record_id}", response_model=MealResponse)
def get_meal(record_id: int, db: DB, user: CurrentUser) -> Meal:
    return records.get_record(db, user.id, Meal, record_id)


@router.post("/meals", response_model=MealResponse, status_code=201)
def create_meal(data: MealInput, db: DB, user: CurrentUser) -> Meal:
    return records.save_meal(db, user.id, data)


@router.put("/meals/{record_id}", response_model=MealResponse)
def update_meal(record_id: int, data: MealInput, db: DB, user: CurrentUser) -> Meal:
    return records.save_meal(db, user.id, data, record_id)


@router.delete("/meals/{record_id}", response_model=DeleteResponse)
def delete_meal(record_id: int, db: DB, user: CurrentUser) -> DeleteResponse:
    records.delete_record(db, user.id, Meal, record_id)
    return DeleteResponse()


@router.get("/body-metrics", response_model=list[BodyMetricResponse])
def list_body_metric(db: DB, time_range: TimeRange, user: CurrentUser, limit: Annotated[int, Query(ge=1, le=100)] = 50, offset: Annotated[int, Query(ge=0)] = 0) -> list[BodyMetric]:
    return records.list_records(db, user.id, BodyMetric, BodyMetric.measured_at, limit, offset, *time_range)


@router.get("/body-metrics/{record_id}", response_model=BodyMetricResponse)
def get_body_metric(record_id: int, db: DB, user: CurrentUser) -> BodyMetric:
    return records.get_record(db, user.id, BodyMetric, record_id)


@router.post("/body-metrics", response_model=BodyMetricResponse, status_code=201)
def create_body_metric(data: BodyMetricInput, db: DB, user: CurrentUser) -> BodyMetric:
    return records.save_body_metric(db, user.id, data)


@router.put("/body-metrics/{record_id}", response_model=BodyMetricResponse)
def update_body_metric(record_id: int, data: BodyMetricInput, db: DB, user: CurrentUser) -> BodyMetric:
    return records.save_body_metric(db, user.id, data, record_id)


@router.delete("/body-metrics/{record_id}", response_model=DeleteResponse)
def delete_body_metric(record_id: int, db: DB, user: CurrentUser) -> DeleteResponse:
    records.delete_record(db, user.id, BodyMetric, record_id)
    return DeleteResponse()


@router.get("/sleep", response_model=list[SleepResponse])
def list_sleep(db: DB, time_range: TimeRange, user: CurrentUser, limit: Annotated[int, Query(ge=1, le=100)] = 50, offset: Annotated[int, Query(ge=0)] = 0) -> list[SleepRecord]:
    return records.list_records(db, user.id, SleepRecord, SleepRecord.sleep_end, limit, offset, *time_range)


@router.get("/sleep/{record_id}", response_model=SleepResponse)
def get_sleep(record_id: int, db: DB, user: CurrentUser) -> SleepRecord:
    return records.get_record(db, user.id, SleepRecord, record_id)


@router.post("/sleep", response_model=SleepResponse, status_code=201)
def create_sleep(data: SleepInput, db: DB, user: CurrentUser) -> SleepRecord:
    return records.save_sleep(db, user.id, data)


@router.put("/sleep/{record_id}", response_model=SleepResponse)
def update_sleep(record_id: int, data: SleepInput, db: DB, user: CurrentUser) -> SleepRecord:
    return records.save_sleep(db, user.id, data, record_id)


@router.delete("/sleep/{record_id}", response_model=DeleteResponse)
def delete_sleep(record_id: int, db: DB, user: CurrentUser) -> DeleteResponse:
    records.delete_record(db, user.id, SleepRecord, record_id)
    return DeleteResponse()

