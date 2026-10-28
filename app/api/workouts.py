from datetime import date
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser
from app.database import get_session
from app.models import Exercise, Routine, Workout, WorkoutSet
from app.schemas import (DeleteResponse, ExerciseInput, ExerciseResponse, MergeInput, RoutineInput, RoutineOrder, RoutineResponse, SetInput,
                         SetResponse, VariantInput, WorkoutInput, WorkoutResponse)
from app.services import exercise_presets, workouts as service

router = APIRouter(prefix="/api", tags=["workouts"])
DB = Annotated[Session, Depends(get_session)]
PRIVATE_IMMUTABLE = "private, max-age=31536000, immutable"
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


@router.get("/exercise-presets")
def list_exercise_presets(user: CurrentUser, v: str | None = None) -> JSONResponse:
    """Built-in presets with the admin's changes; the same for every user. The workouts page links it as
    ?v=<catalog version>, and that exact address is kept by the phone until the list changes."""
    fresh = v is not None and v == exercise_presets.version()
    return JSONResponse(exercise_presets.catalog(), headers={"Cache-Control": PRIVATE_IMMUTABLE if fresh else "no-store"})


@router.get("/exercise-cleanup")
def exercise_cleanup(db: DB, user: CurrentUser) -> list[dict]:
    """My exercises that duplicate a built-in one (often with the grip in the name), to merge."""
    return service.cleanup_suggestions(db, user.id)


@router.get("/exercise-muscles")
def exercise_muscles(db: DB, user: CurrentUser) -> list[dict]:
    """My own exercises with no muscle figure, each with muscles suggested from the closest built-in one."""
    return service.muscle_suggestions(db, user.id)


@router.post("/exercises/{exercise_id}/merge")
def merge_exercise(exercise_id: int, data: MergeInput, db: DB, user: CurrentUser) -> dict:
    target, moved = service.merge_exercise(db, user.id, exercise_id, data.preset_id, data.variant)
    return {"moved": moved, "target": ExerciseResponse.model_validate(target).model_dump(mode="json")}


@router.get("/exercises", response_model=list[ExerciseResponse])
def list_exercises(db: DB, user: CurrentUser, limit: Limit = 50, offset: Offset = 0) -> list[Exercise]:
    return service.list_exercises(db, user.id, limit, offset)


@router.get("/exercises/{exercise_id}", response_model=ExerciseResponse)
def get_exercise(exercise_id: int, db: DB, user: CurrentUser) -> Exercise:
    return service.get_exercise(db, user.id, exercise_id)


@router.post("/exercises", response_model=ExerciseResponse, status_code=201)
def create_exercise(data: ExerciseInput, db: DB, user: CurrentUser) -> Exercise:
    return service.save_exercise(db, user.id, data)


@router.put("/exercises/{exercise_id}", response_model=ExerciseResponse)
def update_exercise(exercise_id: int, data: ExerciseInput, db: DB, user: CurrentUser) -> Exercise:
    return service.save_exercise(db, user.id, data, exercise_id)


@router.delete("/exercises/{exercise_id}", response_model=DeleteResponse)
def delete_exercise(exercise_id: int, db: DB, user: CurrentUser) -> DeleteResponse:
    service.delete_exercise(db, user.id, exercise_id)
    return DeleteResponse()


@router.get("/workouts", response_model=list[WorkoutResponse])
def list_workouts(db: DB, user: CurrentUser, limit: Limit = 50, offset: Offset = 0, date_from: date | None = None, date_to: date | None = None) -> list[Workout]:
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "시작 날짜는 종료 날짜 이전이어야 합니다.")
    return service.list_workouts(db, user.id, limit, offset, date_from, date_to)


@router.post("/workouts", response_model=WorkoutResponse, status_code=201)
def create_workout(data: WorkoutInput, db: DB, user: CurrentUser) -> Workout:
    return service.save_workout(db, user.id, data)


@router.get("/workouts/{workout_id}", response_model=WorkoutResponse)
def get_workout(workout_id: int, db: DB, user: CurrentUser) -> Workout:
    return service.get_workout(db, user.id, workout_id)


@router.put("/workouts/{workout_id}", response_model=WorkoutResponse)
def update_workout(workout_id: int, data: WorkoutInput, db: DB, user: CurrentUser) -> Workout:
    return service.save_workout(db, user.id, data, workout_id)


@router.delete("/workouts/{workout_id}", response_model=DeleteResponse)
def delete_workout(workout_id: int, db: DB, user: CurrentUser) -> DeleteResponse:
    service.delete_workout(db, user.id, workout_id)
    return DeleteResponse()


@router.get("/workouts/{workout_id}/sets", response_model=list[SetResponse])
def list_sets(workout_id: int, db: DB, user: CurrentUser) -> list[WorkoutSet]:
    return service.get_workout(db, user.id, workout_id).sets


@router.get("/workouts/{workout_id}/sets/{set_id}", response_model=SetResponse)
def get_set(workout_id: int, set_id: int, db: DB, user: CurrentUser) -> WorkoutSet:
    return service.get_set(db, user.id, workout_id, set_id)


@router.post("/workouts/{workout_id}/sets", response_model=SetResponse, status_code=201)
def create_set(workout_id: int, data: SetInput, db: DB, user: CurrentUser) -> WorkoutSet:
    return service.save_set(db, user.id, workout_id, data)


@router.put("/workouts/{workout_id}/sets/{set_id}", response_model=SetResponse)
def update_set(workout_id: int, set_id: int, data: SetInput, db: DB, user: CurrentUser) -> WorkoutSet:
    return service.save_set(db, user.id, workout_id, data, set_id)


@router.delete("/workouts/{workout_id}/sets/{set_id}", response_model=DeleteResponse)
def delete_set(workout_id: int, set_id: int, db: DB, user: CurrentUser) -> DeleteResponse:
    service.delete_set(db, user.id, workout_id, set_id)
    return DeleteResponse()


@router.post("/workouts/{workout_id}/sets/batch", response_model=WorkoutResponse, status_code=201)
def create_sets(workout_id: int, data: Annotated[list[SetInput], Body(min_length=1, max_length=300)], db: DB, user: CurrentUser) -> Workout:
    return service.add_sets(db, user.id, workout_id, data)


@router.put("/workouts/{workout_id}/exercises/{exercise_id}/variant", response_model=WorkoutResponse)
def set_exercise_variant(workout_id: int, exercise_id: int, data: VariantInput, db: DB, user: CurrentUser) -> Workout:
    return service.set_exercise_variant(db, user.id, workout_id, exercise_id, data.variant)


@router.delete("/workouts/{workout_id}/exercises/{exercise_id}", response_model=WorkoutResponse)
def remove_exercise(workout_id: int, exercise_id: int, db: DB, user: CurrentUser) -> Workout:
    return service.remove_exercise(db, user.id, workout_id, exercise_id)


@router.get("/routines", response_model=list[RoutineResponse])
def list_routines(db: DB, user: CurrentUser) -> list[Routine]:
    return service.list_routines(db, user.id)


@router.post("/routines", response_model=RoutineResponse, status_code=201)
def create_routine(data: RoutineInput, db: DB, user: CurrentUser) -> Routine:
    return service.save_routine(db, user.id, data)


# Before /routines/{routine_id} so "order" is not read as an id.
@router.put("/routines/order", response_model=list[RoutineResponse])
def order_routines(data: RoutineOrder, db: DB, user: CurrentUser) -> list[Routine]:
    return service.order_routines(db, user.id, data.ids)


@router.put("/routines/{routine_id}", response_model=RoutineResponse)
def update_routine(routine_id: int, data: RoutineInput, db: DB, user: CurrentUser) -> Routine:
    return service.save_routine(db, user.id, data, routine_id)


@router.delete("/routines/{routine_id}", response_model=DeleteResponse)
def delete_routine(routine_id: int, db: DB, user: CurrentUser) -> DeleteResponse:
    service.delete_routine(db, user.id, routine_id)
    return DeleteResponse()
