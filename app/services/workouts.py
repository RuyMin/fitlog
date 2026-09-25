"""Workout business rules shared by REST and future import adapters."""
from datetime import date, datetime, timezone

from sqlalchemy import Select, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models import Exercise, Workout, WorkoutSet, utc_now
from app.schemas import ExerciseInput, SetInput, WorkoutInput


from app.services.persistence import RecordConflict, RecordNotFound, commit


def get_exercise(session: Session, exercise_id: int) -> Exercise:
    item = session.get(Exercise, exercise_id)
    if item is None:
        raise RecordNotFound("운동 종목을 찾을 수 없습니다.")
    return item


def list_exercises(session: Session, limit: int, offset: int) -> list[Exercise]:
    return list(session.scalars(select(Exercise).order_by(Exercise.name, Exercise.id).limit(limit).offset(offset)))


def save_exercise(session: Session, data: ExerciseInput, exercise_id: int | None = None) -> Exercise:
    item = get_exercise(session, exercise_id) if exercise_id is not None else Exercise()
    for key, value in data.model_dump().items():
        setattr(item, key, value)
    session.add(item)
    commit(session)
    return item


def delete_exercise(session: Session, exercise_id: int) -> None:
    item = get_exercise(session, exercise_id)
    if session.scalar(select(WorkoutSet.id).where(WorkoutSet.exercise_id == exercise_id).limit(1)):
        raise RecordConflict("세트에서 사용 중인 종목은 삭제할 수 없습니다.")
    session.delete(item)
    commit(session)


def workout_query() -> Select[tuple[Workout]]:
    return select(Workout).options(selectinload(Workout.sets).joinedload(WorkoutSet.exercise))


def list_workouts(session: Session, limit: int, offset: int, date_from: date | None, date_to: date | None) -> list[Workout]:
    query = workout_query()
    if date_from is not None:
        query = query.where(Workout.workout_date >= date_from)
    if date_to is not None:
        query = query.where(Workout.workout_date <= date_to)
    return list(session.scalars(query.order_by(Workout.workout_date.desc(), Workout.id.desc()).limit(limit).offset(offset)))


def get_workout(session: Session, workout_id: int) -> Workout:
    item = session.scalar(workout_query().where(Workout.id == workout_id).execution_options(populate_existing=True))
    if item is None:
        raise RecordNotFound("운동 기록을 찾을 수 없습니다.")
    return item


def save_workout(session: Session, data: WorkoutInput, workout_id: int | None = None) -> Workout:
    item = get_workout(session, workout_id) if workout_id is not None else Workout()
    for key, value in data.model_dump().items():
        if isinstance(value, datetime):
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        setattr(item, key, value)
    session.add(item)
    commit(session)
    return get_workout(session, item.id)


def delete_workout(session: Session, workout_id: int) -> None:
    session.delete(get_workout(session, workout_id))
    commit(session)


def get_set(session: Session, workout_id: int, set_id: int) -> WorkoutSet:
    item = session.scalar(select(WorkoutSet).options(joinedload(WorkoutSet.exercise)).where(
        WorkoutSet.id == set_id, WorkoutSet.workout_id == workout_id
    ).execution_options(populate_existing=True))
    if item is None:
        raise RecordNotFound("이 운동의 세트를 찾을 수 없습니다.")
    return item


def save_set(session: Session, workout_id: int, data: SetInput, set_id: int | None = None) -> WorkoutSet:
    workout = get_workout(session, workout_id)
    item = get_set(session, workout_id, set_id) if set_id is not None else WorkoutSet(workout_id=workout_id)
    get_exercise(session, data.exercise_id)
    for key, value in data.model_dump().items():
        setattr(item, key, value)
    workout.updated_at = utc_now()
    session.add(item)
    commit(session)
    return get_set(session, workout_id, item.id)


def delete_set(session: Session, workout_id: int, set_id: int) -> None:
    workout = get_workout(session, workout_id)
    session.delete(get_set(session, workout_id, set_id))
    workout.updated_at = utc_now()
    commit(session)
