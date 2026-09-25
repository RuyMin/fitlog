from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_session
from app.models import Exercise, Workout, WorkoutSet
from app.schemas import DeleteResponse, ExerciseInput, ExerciseResponse, SetInput, SetResponse, WorkoutInput, WorkoutResponse
from app.services import workouts as service

router = APIRouter(prefix="/api", tags=["workouts"])
DB = Annotated[Session, Depends(get_session)]
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


@router.get("/exercises", response_model=list[ExerciseResponse])
def list_exercises(db: DB, limit: Limit = 50, offset: Offset = 0) -> list[Exercise]:
    return service.list_exercises(db, limit, offset)


@router.get("/exercises/{exercise_id}", response_model=ExerciseResponse)
def get_exercise(exercise_id: int, db: DB) -> Exercise:
    return service.get_exercise(db, exercise_id)


@router.post("/exercises", response_model=ExerciseResponse, status_code=201)
def create_exercise(data: ExerciseInput, db: DB) -> Exercise:
    return service.save_exercise(db, data)


@router.put("/exercises/{exercise_id}", response_model=ExerciseResponse)
def update_exercise(exercise_id: int, data: ExerciseInput, db: DB) -> Exercise:
    return service.save_exercise(db, data, exercise_id)


@router.delete("/exercises/{exercise_id}", response_model=DeleteResponse)
def delete_exercise(exercise_id: int, db: DB) -> DeleteResponse:
    service.delete_exercise(db, exercise_id)
    return DeleteResponse()


@router.get("/workouts", response_model=list[WorkoutResponse])
def list_workouts(db: DB, limit: Limit = 50, offset: Offset = 0, date_from: date | None = None, date_to: date | None = None) -> list[Workout]:
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "시작 날짜는 종료 날짜 이전이어야 합니다.")
    return service.list_workouts(db, limit, offset, date_from, date_to)


@router.post("/workouts", response_model=WorkoutResponse, status_code=201)
def create_workout(data: WorkoutInput, db: DB) -> Workout:
    return service.save_workout(db, data)


@router.get("/workouts/{workout_id}", response_model=WorkoutResponse)
def get_workout(workout_id: int, db: DB) -> Workout:
    return service.get_workout(db, workout_id)


@router.put("/workouts/{workout_id}", response_model=WorkoutResponse)
def update_workout(workout_id: int, data: WorkoutInput, db: DB) -> Workout:
    return service.save_workout(db, data, workout_id)


@router.delete("/workouts/{workout_id}", response_model=DeleteResponse)
def delete_workout(workout_id: int, db: DB) -> DeleteResponse:
    service.delete_workout(db, workout_id)
    return DeleteResponse()


@router.get("/workouts/{workout_id}/sets", response_model=list[SetResponse])
def list_sets(workout_id: int, db: DB) -> list[WorkoutSet]:
    return service.get_workout(db, workout_id).sets


@router.get("/workouts/{workout_id}/sets/{set_id}", response_model=SetResponse)
def get_set(workout_id: int, set_id: int, db: DB) -> WorkoutSet:
    return service.get_set(db, workout_id, set_id)


@router.post("/workouts/{workout_id}/sets", response_model=SetResponse, status_code=201)
def create_set(workout_id: int, data: SetInput, db: DB) -> WorkoutSet:
    return service.save_set(db, workout_id, data)


@router.put("/workouts/{workout_id}/sets/{set_id}", response_model=SetResponse)
def update_set(workout_id: int, set_id: int, data: SetInput, db: DB) -> WorkoutSet:
    return service.save_set(db, workout_id, data, set_id)


@router.delete("/workouts/{workout_id}/sets/{set_id}", response_model=DeleteResponse)
def delete_set(workout_id: int, set_id: int, db: DB) -> DeleteResponse:
    service.delete_set(db, workout_id, set_id)
    return DeleteResponse()
