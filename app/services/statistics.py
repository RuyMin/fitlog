"""Bounded, read-only aggregations. Missing measurements never become zero."""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BodyMetric, Exercise, SleepRecord, Workout, WorkoutSet
from app.services.records import utc_naive
from app.statistics_schemas import (
    DailyStatistics, ExerciseStatistics, ExerciseVolumePoint, StatisticsResponse,
    StatisticsSummary, WeeklyStatistics,
)


def local_day(value: datetime, zone: ZoneInfo) -> date:
    return value.replace(tzinfo=timezone.utc).astimezone(zone).date()


def get_statistics(
    session: Session, date_from: date, date_to: date, zone: ZoneInfo, completed_only: bool,
) -> StatisticsResponse:
    days = {
        date_from + timedelta(days=index): DailyStatistics(date=date_from + timedelta(days=index))
        for index in range((date_to - date_from).days + 1)
    }
    weeks: dict[date, WeeklyStatistics] = {}
    for day in days:
        monday = day - timedelta(days=day.weekday())
        if monday not in weeks:
            weeks[monday] = WeeklyStatistics(
                week_start=monday, period_start=max(monday, date_from),
                period_end=min(monday + timedelta(days=6), date_to),
            )
    workouts = session.execute(select(Workout.id, Workout.workout_date).where(
        Workout.workout_date >= date_from, Workout.workout_date <= date_to
    )).all()
    for _, day in workouts:
        days[day].workouts_count += 1
    sets_query = select(
        Workout.workout_date, WorkoutSet.exercise_id, Exercise.name, WorkoutSet.weight, WorkoutSet.reps
    ).join(WorkoutSet, WorkoutSet.workout_id == Workout.id).join(
        Exercise, Exercise.id == WorkoutSet.exercise_id
    ).where(Workout.workout_date >= date_from, Workout.workout_date <= date_to)
    if completed_only:
        sets_query = sets_query.where(WorkoutSet.completed.is_(True))
    exercises: dict[int, ExerciseStatistics] = {}
    exercise_days: dict[int, dict[date, ExerciseVolumePoint]] = {}
    for day, exercise_id, name, weight, reps in session.execute(sets_query):
        if exercise_id not in exercises:
            exercises[exercise_id] = ExerciseStatistics(
                exercise_id=exercise_id, name=name, sets_count=0, known_volume_sets=0,
                max_weight=None, volume_kg_reps=None, daily_volume=[],
            )
            exercise_days[exercise_id] = {}
        exercise = exercises[exercise_id]
        point = exercise_days[exercise_id].setdefault(day, ExerciseVolumePoint(date=day))
        exercise.sets_count += 1
        days[day].sets_count += 1
        point.sets_count += 1
        if weight is not None:
            exercise.max_weight = weight if exercise.max_weight is None else max(exercise.max_weight, weight)
        if weight is not None and reps is not None:
            volume = weight * reps
            for target in (exercise, point, days[day]):
                target.known_volume_sets += 1
                target.volume_kg_reps = (target.volume_kg_reps or 0) + volume
    for exercise_id, exercise in exercises.items():
        exercise.daily_volume = [point for _, point in sorted(exercise_days[exercise_id].items())]
    start = utc_naive(datetime.combine(date_from, time.min, zone))
    end = utc_naive(datetime.combine(date_to + timedelta(days=1), time.min, zone))
    # Ascending timestamp + id means the final weight on a local day wins.
    measurements = session.execute(select(BodyMetric.measured_at, BodyMetric.weight).where(
        BodyMetric.measured_at >= start, BodyMetric.measured_at < end, BodyMetric.weight.is_not(None)
    ).order_by(BodyMetric.measured_at, BodyMetric.id))
    for measured_at, weight in measurements:
        point = days[local_day(measured_at, zone)]
        point.weight = weight
        point.weight_measured_at = measured_at
    for ended_at, minutes in session.execute(select(SleepRecord.sleep_end, SleepRecord.duration_minutes).where(
        SleepRecord.sleep_end >= start, SleepRecord.sleep_end < end
    )):
        point = days[local_day(ended_at, zone)]
        point.sleep_records_count += 1
        point.sleep_minutes = (point.sleep_minutes or 0) + minutes
    for day, point in days.items():
        week = weeks[day - timedelta(days=day.weekday())]
        week.workouts_count += point.workouts_count
        week.sets_count += point.sets_count
    weights = [point.weight for point in days.values() if point.weight is not None]
    sleeps = [point.sleep_minutes for point in days.values() if point.sleep_minutes is not None]
    volumes = [point.volume_kg_reps for point in days.values() if point.volume_kg_reps is not None]
    summary = StatisticsSummary(
        workouts_count=len(workouts), sets_count=sum(point.sets_count for point in days.values()),
        known_volume_sets=sum(point.known_volume_sets for point in days.values()),
        volume_kg_reps=sum(volumes) if volumes else None,
        weight_change_kg=round(weights[-1] - weights[0], 6) if len(weights) >= 2 else None,
        weight_days=len(weights), sleep_days=len(sleeps),
        average_sleep_minutes=sum(sleeps) / len(sleeps) if sleeps else None,
    )
    return StatisticsResponse(
        date_from=date_from, date_to=date_to, timezone=zone.key, completed_only=completed_only,
        summary=summary, daily=list(days.values()), weekly=list(weeks.values()),
        exercises=sorted(exercises.values(), key=lambda item: (
            item.max_weight is None, -(item.max_weight or 0), item.name, item.exercise_id
        )),
    )
