from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import Integer, func, select
from sqlalchemy.orm import Session

from app.config import PROTEIN_GOAL_GRAMS
from app.models import BodyMetric, Meal, SleepRecord, Workout, WorkoutSet
from app.schemas import BodyMetricResponse, DashboardResponse
from app.services.records import utc_naive


def get_dashboard(session: Session, day: date, zone: ZoneInfo) -> DashboardResponse:
    start = utc_naive(datetime.combine(day, time.min, zone))
    end = utc_naive(datetime.combine(day + timedelta(days=1), time.min, zone))
    workout_ids = select(Workout.id).where(Workout.workout_date == day)
    workouts_count = session.scalar(select(func.count()).select_from(Workout).where(Workout.workout_date == day))
    total_sets, completed_sets = session.execute(select(
        func.count(WorkoutSet.id), func.sum(WorkoutSet.completed.cast(Integer))
    ).where(WorkoutSet.workout_id.in_(workout_ids))).one()
    meals_count, known_count, protein = session.execute(select(
        func.count(Meal.id), func.count(Meal.protein), func.sum(Meal.protein)
    ).where(Meal.eaten_at >= start, Meal.eaten_at < end)).one()
    latest = session.scalar(select(BodyMetric).where(
        BodyMetric.measured_at < end, BodyMetric.weight.is_not(None)
    ).order_by(BodyMetric.measured_at.desc(), BodyMetric.id.desc()).limit(1))
    sleep_count, sleep_minutes = session.execute(select(
        func.count(SleepRecord.id), func.sum(SleepRecord.duration_minutes)
    ).where(SleepRecord.sleep_end >= start, SleepRecord.sleep_end < end)).one()
    return DashboardResponse(
        date=day, timezone=zone.key, workouts_count=workouts_count or 0,
        total_sets=total_sets, completed_sets=completed_sets or 0,
        latest_weight=BodyMetricResponse.model_validate(latest) if latest else None,
        meals_count=meals_count, protein_known_count=known_count, protein_grams=protein,
        protein_goal_grams=PROTEIN_GOAL_GRAMS,
        sleep_records_count=sleep_count, sleep_minutes=sleep_minutes,
    )
