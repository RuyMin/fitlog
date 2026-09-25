from datetime import date as Date, datetime, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_session
from app.services.statistics import get_statistics
from app.statistics_schemas import StatisticsResponse

router = APIRouter(prefix="/api", tags=["statistics"])


@router.get("/statistics", response_model=StatisticsResponse)
def statistics(
    db: Annotated[Session, Depends(get_session)],
    date_from: Date | None = None,
    date_to: Date | None = None,
    timezone: str = "Asia/Seoul",
    completed_only: bool = True,
) -> StatisticsResponse:
    try:
        zone = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise HTTPException(422, "올바른 IANA 시간대를 지정해 주세요.") from None
    end = date_to or datetime.now(zone).date()
    try:
        start = date_from or end - timedelta(days=29)
    except OverflowError:
        raise HTTPException(422, "지원하지 않는 조회 날짜입니다.") from None
    if start.year < 2 or end.year > 9998:
        raise HTTPException(422, "지원하지 않는 조회 날짜입니다.")
    if start > end or (end - start).days >= 366:
        raise HTTPException(422, "조회 기간은 시작일부터 종료일까지 1~366일이어야 합니다.")
    return get_statistics(db, start, end, zone, completed_only)
