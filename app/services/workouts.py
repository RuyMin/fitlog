"""Workout business rules shared by REST and import adapters. Always scoped to one user."""
from datetime import date, datetime, timezone

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models import Exercise, Workout, WorkoutSet, utc_now
from app.schemas import ExerciseInput, SetInput, WorkoutInput


from app.services import exercise_presets
from app.services.persistence import RecordConflict, RecordInvalid, RecordNotFound, commit, owned


def get_exercise(session: Session, user_id: int, exercise_id: int) -> Exercise:
    return owned(session, Exercise, user_id, exercise_id, "운동 종목을 찾을 수 없습니다.")


def exercise_named(session: Session, user_id: int, name: str) -> Exercise:
    """The user's exercise with this name, created when missing. A new one links to the preset of the same
    name (러닝 → running) unless the user already has an exercise for that preset, so imported runs are
    recorded like runs picked from the list."""
    exercise = session.scalar(select(Exercise).where(Exercise.user_id == user_id, Exercise.name == name))
    if exercise is None:
        preset_id = exercise_presets.match_name(name)
        if preset_id and session.scalar(select(Exercise.id).where(Exercise.user_id == user_id, Exercise.preset_id == preset_id)):
            preset_id = None
        preset = exercise_presets.find(preset_id)
        exercise = Exercise(user_id=user_id, name=name, preset_id=preset_id,
                            body_part=preset and preset["body_part"], category=preset and preset["equipment"])
        session.add(exercise)
        session.flush()
    return exercise


def list_exercises(session: Session, user_id: int, limit: int, offset: int) -> list[Exercise]:
    query = select(Exercise).where(Exercise.user_id == user_id)
    return list(session.scalars(query.order_by(Exercise.name, Exercise.id).limit(limit).offset(offset)))


def save_exercise(session: Session, user_id: int, data: ExerciseInput, exercise_id: int | None = None) -> Exercise:
    item = get_exercise(session, user_id, exercise_id) if exercise_id is not None else Exercise(user_id=user_id)
    for key, value in data.model_dump().items():
        setattr(item, key, value)
    session.add(item)
    commit(session)
    return item


def delete_exercise(session: Session, user_id: int, exercise_id: int) -> None:
    item = get_exercise(session, user_id, exercise_id)
    if session.scalar(select(WorkoutSet.id).where(WorkoutSet.exercise_id == exercise_id).limit(1)):
        raise RecordConflict("세트에서 사용 중인 종목은 삭제할 수 없습니다.")
    session.delete(item)
    commit(session)


def cleanup_suggestions(session: Session, user_id: int) -> list[dict]:
    """The user's own exercises whose name is a built-in one, often with the grip in it ("랫풀다운 페러럴그립"),
    each with the preset and variant it would merge into and how many sets it holds."""
    presets = {preset["id"]: preset for preset in exercise_presets.catalog()["presets"]}
    counts = dict(session.execute(select(WorkoutSet.exercise_id, func.count()).where(WorkoutSet.user_id == user_id)
                                  .group_by(WorkoutSet.exercise_id)).all())
    found = []
    for exercise in session.scalars(select(Exercise).where(Exercise.user_id == user_id, Exercise.preset_id.is_(None)).order_by(Exercise.name)):
        match = exercise_presets.split_variant(exercise.name)
        if match is None:
            continue
        preset = presets[match[0]]
        variant = next((v for v in preset.get("variants", []) if v["id"] == match[1]), None)
        found.append({"exercise_id": exercise.id, "name": exercise.name, "sets": counts.get(exercise.id, 0),
                      "preset_id": preset["id"], "preset_name": preset["name"],
                      "variant": match[1], "variant_label": variant and variant["label"]})
    return found


def muscle_suggestions(session: Session, user_id: int) -> list[dict]:
    """The user's own exercises with no muscles to draw: not linked to a preset, none picked, and not one the
    cleanup above would merge. Each carries the muscles of the closest preset by name, when there is one."""
    counts = dict(session.execute(select(WorkoutSet.exercise_id, func.count()).where(WorkoutSet.user_id == user_id)
                                  .group_by(WorkoutSet.exercise_id)).all())
    found = []
    for exercise in session.scalars(select(Exercise).where(Exercise.user_id == user_id, Exercise.preset_id.is_(None)).order_by(Exercise.name)):
        if exercise.muscles or exercise_presets.split_variant(exercise.name) is not None:
            continue
        preset = exercise_presets.similar(exercise.name)
        found.append({"exercise_id": exercise.id, "name": exercise.name, "sets": counts.get(exercise.id, 0),
                      "muscles": preset["muscles"] if preset else [], "like": preset and preset["name"]})
    return found


def merge_exercise(session: Session, user_id: int, exercise_id: int, preset_id: str, variant: str | None) -> tuple[Exercise, int]:
    """Move a duplicate exercise's sets onto the user's exercise for `preset_id` (made when missing), mark
    them with `variant` where they had none, then delete the duplicate. Returns (target, sets moved)."""
    source = get_exercise(session, user_id, exercise_id)
    if source.preset_id is not None:
        raise RecordConflict("기본 종목에 연결된 종목은 합칠 수 없습니다.")
    preset = exercise_presets.find(preset_id)
    if preset is None:
        raise RecordInvalid("알 수 없는 기본 종목입니다.")
    if variant is not None and variant not in exercise_presets.variant_ids(preset_id):
        raise RecordInvalid("이 종목에 없는 그립·자세입니다.")
    target = session.scalar(select(Exercise).where(Exercise.user_id == user_id, Exercise.preset_id == preset_id))
    if target is None:
        # An unlinked exercise already called by the preset's name becomes the linked one; else make it.
        target = session.scalar(select(Exercise).where(Exercise.user_id == user_id, Exercise.name == preset["name"], Exercise.id != source.id))
        if target is None:
            target = Exercise(user_id=user_id, name=preset["name"])
            session.add(target)
        target.preset_id, target.muscles = preset_id, None
        target.body_part = target.body_part or preset["body_part"]
        target.category = target.category or preset["equipment"]
        session.flush()
    sets = list(session.scalars(select(WorkoutSet).where(WorkoutSet.user_id == user_id, WorkoutSet.exercise_id == source.id)
                                .order_by(WorkoutSet.workout_id, WorkoutSet.set_number)))
    taken: dict[int, int] = dict(session.execute(select(WorkoutSet.workout_id, func.max(WorkoutSet.set_number)).where(
        WorkoutSet.user_id == user_id, WorkoutSet.exercise_id == target.id).group_by(WorkoutSet.workout_id)).all())
    for item in sets:
        # In a workout that already has the target exercise, the moved sets follow its last set.
        if item.workout_id in taken:
            taken[item.workout_id] += 1
            item.set_number = taken[item.workout_id]
        item.exercise_id = target.id
        if item.variant is None:
            item.variant = variant
    session.flush()
    session.delete(source)
    commit(session)
    session.refresh(target)
    return target, len(sets)


def workout_query(user_id: int) -> Select[tuple[Workout]]:
    return select(Workout).where(Workout.user_id == user_id).options(
        selectinload(Workout.sets).joinedload(WorkoutSet.exercise)
    )


def list_workouts(session: Session, user_id: int, limit: int, offset: int, date_from: date | None, date_to: date | None) -> list[Workout]:
    query = workout_query(user_id)
    if date_from is not None:
        query = query.where(Workout.workout_date >= date_from)
    if date_to is not None:
        query = query.where(Workout.workout_date <= date_to)
    return list(session.scalars(query.order_by(Workout.workout_date.desc(), Workout.id.desc()).limit(limit).offset(offset)))


def get_workout(session: Session, user_id: int, workout_id: int) -> Workout:
    item = session.scalar(workout_query(user_id).where(Workout.id == workout_id).execution_options(populate_existing=True))
    if item is None:
        raise RecordNotFound("운동 기록을 찾을 수 없습니다.")
    return item


def save_workout(session: Session, user_id: int, data: WorkoutInput, workout_id: int | None = None) -> Workout:
    item = get_workout(session, user_id, workout_id) if workout_id is not None else Workout(user_id=user_id)
    for key, value in data.model_dump().items():
        if isinstance(value, datetime):
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        setattr(item, key, value)
    session.add(item)
    commit(session)
    return get_workout(session, user_id, item.id)


def delete_workout(session: Session, user_id: int, workout_id: int) -> None:
    session.delete(get_workout(session, user_id, workout_id))
    commit(session)


def get_set(session: Session, user_id: int, workout_id: int, set_id: int) -> WorkoutSet:
    item = session.scalar(select(WorkoutSet).options(joinedload(WorkoutSet.exercise)).where(
        WorkoutSet.id == set_id, WorkoutSet.workout_id == workout_id, WorkoutSet.user_id == user_id
    ).execution_options(populate_existing=True))
    if item is None:
        raise RecordNotFound("이 운동의 세트를 찾을 수 없습니다.")
    return item


def save_set(session: Session, user_id: int, workout_id: int, data: SetInput, set_id: int | None = None) -> WorkoutSet:
    workout = get_workout(session, user_id, workout_id)
    item = get_set(session, user_id, workout_id, set_id) if set_id is not None else WorkoutSet(workout_id=workout_id, user_id=user_id)
    exercise = get_exercise(session, user_id, data.exercise_id)
    if data.variant is not None and data.variant not in exercise_presets.variant_ids(exercise.preset_id):
        raise RecordInvalid("이 운동에서 고를 수 없는 그립·발 위치입니다.")
    for key, value in data.model_dump().items():
        setattr(item, key, value)
    workout.updated_at = utc_now()
    session.add(item)
    commit(session)
    return get_set(session, user_id, workout_id, item.id)


def delete_set(session: Session, user_id: int, workout_id: int, set_id: int) -> None:
    workout = get_workout(session, user_id, workout_id)
    session.delete(get_set(session, user_id, workout_id, set_id))
    workout.updated_at = utc_now()
    commit(session)


# Batch edits for the workout screen: one request per user action over a slow link.
def add_sets(session: Session, user_id: int, workout_id: int, items: list[SetInput]) -> Workout:
    """Add several sets in one transaction (repeat a past workout, add picked exercises)."""
    workout = get_workout(session, user_id, workout_id)
    exercises = {}
    for data in items:
        if data.exercise_id not in exercises:
            exercises[data.exercise_id] = get_exercise(session, user_id, data.exercise_id)
        if data.variant is not None and data.variant not in exercise_presets.variant_ids(exercises[data.exercise_id].preset_id):
            raise RecordInvalid("이 운동에서 고를 수 없는 그립·발 위치입니다.")
        session.add(WorkoutSet(workout_id=workout_id, user_id=user_id, **data.model_dump()))
    workout.updated_at = utc_now()
    commit(session)
    return get_workout(session, user_id, workout_id)


def set_exercise_variant(session: Session, user_id: int, workout_id: int, exercise_id: int, variant: str | None) -> Workout:
    """Give the exercise's unfinished sets in this workout one variant (None = default). Finished sets keep theirs."""
    workout = get_workout(session, user_id, workout_id)
    exercise = get_exercise(session, user_id, exercise_id)
    if variant is not None and variant not in exercise_presets.variant_ids(exercise.preset_id):
        raise RecordInvalid("이 운동에서 고를 수 없는 그립·발 위치입니다.")
    for item in workout.sets:
        if item.exercise_id == exercise_id and not item.completed:
            item.variant = variant
    workout.updated_at = utc_now()
    commit(session)
    return get_workout(session, user_id, workout_id)


def remove_exercise(session: Session, user_id: int, workout_id: int, exercise_id: int) -> Workout:
    """Delete every set of one exercise from this workout."""
    workout = get_workout(session, user_id, workout_id)
    get_exercise(session, user_id, exercise_id)
    for item in [item for item in workout.sets if item.exercise_id == exercise_id]:
        session.delete(item)
    workout.updated_at = utc_now()
    commit(session)
    return get_workout(session, user_id, workout_id)
