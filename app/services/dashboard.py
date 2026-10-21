from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import Integer, func, select
from sqlalchemy.orm import Session

from app.config import CALORIE_GOAL_KCAL, PROTEIN_GOAL_GRAMS, SLEEP_GOAL_MINUTES
from app.models import BodyMetric, Meal, SleepRecord, Workout, WorkoutSet
from app.schemas import BodyMetricResponse, DashboardResponse, WeekDay, WeightPoint
from app.services.records import utc_naive

WEIGHT_DAYS = 30  # the home sparkline's window


def get_dashboard(session: Session, user_id: int, day: date, zone: ZoneInfo) -> DashboardResponse:
    start = utc_naive(datetime.combine(day, time.min, zone))
    end = utc_naive(datetime.combine(day + timedelta(days=1), time.min, zone))
    workout_ids = select(Workout.id).where(Workout.user_id == user_id, Workout.workout_date == day)
    workouts_count = session.scalar(select(func.count()).select_from(Workout).where(Workout.user_id == user_id, Workout.workout_date == day))
    total_sets, completed_sets = session.execute(select(
        func.count(WorkoutSet.id), func.sum(WorkoutSet.completed.cast(Integer))
    ).where(WorkoutSet.workout_id.in_(workout_ids))).one()
    volume = session.scalar(select(func.sum(WorkoutSet.weight * WorkoutSet.reps)).where(
        WorkoutSet.workout_id.in_(workout_ids), WorkoutSet.completed.is_(True)))
    titles = list(session.scalars(select(Workout.title).where(Workout.user_id == user_id, Workout.workout_date == day).order_by(Workout.id)))
    meals_count, known_count, protein, calories, carbohydrates, fat = session.execute(select(
        func.count(Meal.id), func.count(Meal.protein), func.sum(Meal.protein),
        func.sum(Meal.calories), func.sum(Meal.carbohydrates), func.sum(Meal.fat),
    ).where(Meal.user_id == user_id, Meal.eaten_at >= start, Meal.eaten_at < end)).one()
    latest = session.scalar(select(BodyMetric).where(
        BodyMetric.user_id == user_id, BodyMetric.measured_at < end, BodyMetric.weight.is_not(None)
    ).order_by(BodyMetric.measured_at.desc(), BodyMetric.id.desc()).limit(1))
    sleep_count, sleep_minutes = session.execute(select(
        func.count(SleepRecord.id), func.sum(SleepRecord.duration_minutes)
    ).where(SleepRecord.user_id == user_id, SleepRecord.sleep_end >= start, SleepRecord.sleep_end < end)).one()
    last_sleep = session.scalar(select(SleepRecord).where(
        SleepRecord.user_id == user_id, SleepRecord.sleep_end >= start, SleepRecord.sleep_end < end
    ).order_by(SleepRecord.duration_minutes.desc(), SleepRecord.id.desc()).limit(1))
    weights = session.scalars(select(BodyMetric).where(
        BodyMetric.user_id == user_id, BodyMetric.weight.is_not(None),
        BodyMetric.measured_at >= end - timedelta(days=WEIGHT_DAYS), BodyMetric.measured_at < end,
    ).order_by(BodyMetric.measured_at, BodyMetric.id))
    return DashboardResponse(
        date=day, timezone=zone.key, workouts_count=workouts_count or 0,
        total_sets=total_sets, completed_sets=completed_sets or 0,
        latest_weight=BodyMetricResponse.model_validate(latest) if latest else None,
        meals_count=meals_count, protein_known_count=known_count, protein_grams=protein,
        protein_goal_grams=PROTEIN_GOAL_GRAMS,
        sleep_records_count=sleep_count, sleep_minutes=sleep_minutes,
        volume_kg=volume, workout_titles=titles,
        calories=calories, carbohydrates_grams=carbohydrates, fat_grams=fat, calorie_goal_kcal=CALORIE_GOAL_KCAL,
        sleep_goal_minutes=SLEEP_GOAL_MINUTES,
        main_sleep_start=last_sleep.sleep_start if last_sleep else None,
        main_sleep_end=last_sleep.sleep_end if last_sleep else None,
        week=week(session, user_id, day, zone),
        weights=[WeightPoint(measured_at=m.measured_at, weight=m.weight) for m in weights],
    )


def week(session: Session, user_id: int, day: date, zone: ZoneInfo) -> list[WeekDay]:
    """Monday to Sunday around `day`: which local days have a workout, and which have any record."""
    monday = day - timedelta(days=day.weekday())
    days = [monday + timedelta(days=n) for n in range(7)]
    start = utc_naive(datetime.combine(monday, time.min, zone))
    end = utc_naive(datetime.combine(monday + timedelta(days=7), time.min, zone))
    trained = set(session.scalars(select(Workout.workout_date).where(
        Workout.user_id == user_id, Workout.workout_date >= monday, Workout.workout_date < monday + timedelta(days=7))))
    stamps = [*session.scalars(select(Meal.eaten_at).where(Meal.user_id == user_id, Meal.eaten_at >= start, Meal.eaten_at < end)),
              *session.scalars(select(BodyMetric.measured_at).where(BodyMetric.user_id == user_id, BodyMetric.measured_at >= start, BodyMetric.measured_at < end)),
              *session.scalars(select(SleepRecord.sleep_end).where(SleepRecord.user_id == user_id, SleepRecord.sleep_end >= start, SleepRecord.sleep_end < end))]
    logged = trained | {stamp.replace(tzinfo=timezone.utc).astimezone(zone).date() for stamp in stamps}
    return [WeekDay(date=d, workout=d in trained, logged=d in logged) for d in days]
