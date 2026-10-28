"""Daily goals per user: the server defaults, an estimate from the user's body details, or their own numbers.

The estimate uses the Mifflin-St Jeor resting energy equation times an activity factor, then a fixed
adjustment for losing or gaining weight. Protein follows body weight, more while losing (to keep muscle
in a deficit) and a little more while gaining; fat takes a fixed share of the
calories and carbohydrate the rest. It is a general-population estimate, not a prescription.
"""
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import CALORIE_GOAL_KCAL, CARBOHYDRATE_GOAL_GRAMS, FAT_GOAL_GRAMS, PROTEIN_GOAL_GRAMS, SLEEP_GOAL_MINUTES
from app.models import BodyMetric, GoalProfile, utc_now
from app.services.persistence import commit

ACTIVITY_FACTORS = {"sedentary": 1.2, "light": 1.375, "moderate": 1.55, "active": 1.725, "very_active": 1.9}
AIM_ADJUSTMENT_KCAL = {"lose": -400, "maintain": 0, "gain": 300}
# 1.6 g/kg is where muscle gain levels off for most people (Morton et al. 2018, upper bound about 2.2).
PROTEIN_G_PER_KG = {"lose": 2.0, "maintain": 1.6, "gain": 1.8}
FAT_SHARE = 0.25
AGE_RANGE = (15, 100)  # the equation is for adults and older teenagers


@dataclass
class Estimate:
    age: int
    weight: float
    bmr: float
    activity_factor: float
    adjustment_kcal: float
    protein_g_per_kg: float
    calorie_kcal: float
    protein_g: float
    carbohydrate_g: float
    fat_g: float


@dataclass
class Goals:
    calorie_kcal: float
    protein_g: float
    carbohydrate_g: float
    fat_g: float
    sleep_minutes: float
    source: str  # default | auto | manual


def default_goals() -> Goals:
    return Goals(CALORIE_GOAL_KCAL, PROTEIN_GOAL_GRAMS, CARBOHYDRATE_GOAL_GRAMS, FAT_GOAL_GRAMS, SLEEP_GOAL_MINUTES, "default")


def missing_details(profile: GoalProfile, weight: float | None) -> list[str]:
    """What the estimate still needs, in form order."""
    return [name for name, value in (("sex", profile.sex), ("birth_year", profile.birth_year),
                                     ("height", profile.height_cm), ("weight", weight)) if value is None]


def estimate(profile: GoalProfile, weight: float | None, today: date) -> Estimate | None:
    if missing_details(profile, weight):
        return None
    age = today.year - profile.birth_year
    if not AGE_RANGE[0] <= age <= AGE_RANGE[1]:
        return None
    bmr = 10 * weight + 6.25 * profile.height_cm - 5 * age + (5 if profile.sex == "male" else -161)
    factor = ACTIVITY_FACTORS[profile.activity]
    adjustment = AIM_ADJUSTMENT_KCAL[profile.aim]
    # Losing weight never goes below the resting energy itself.
    calories = round(max(bmr * factor + adjustment, bmr) / 10) * 10
    per_kg = PROTEIN_G_PER_KG[profile.aim]
    protein = round(weight * per_kg)
    fat = round(calories * FAT_SHARE / 9)
    carbohydrate = max(0, round((calories - protein * 4 - fat * 9) / 4))
    return Estimate(age, weight, round(bmr), factor, adjustment, per_kg, calories, protein, carbohydrate, fat)


def latest_weight(session: Session, user_id: int) -> BodyMetric | None:
    return session.scalar(select(BodyMetric).where(BodyMetric.user_id == user_id, BodyMetric.weight.is_not(None))
                          .order_by(BodyMetric.measured_at.desc(), BodyMetric.id.desc()).limit(1))


def resolve(profile: GoalProfile | None, weight: float | None, today: date) -> Goals:
    """The goals in effect. Auto mode without enough details (or weight) falls back to the defaults."""
    goals = default_goals()
    if profile is None:
        return goals
    if profile.sleep_minutes is not None:
        goals.sleep_minutes = profile.sleep_minutes
    if profile.mode == "manual":
        return Goals(profile.calorie_kcal, profile.protein_g, profile.carbohydrate_g, profile.fat_g, goals.sleep_minutes, "manual")
    found = estimate(profile, weight, today)
    if found:
        return Goals(found.calorie_kcal, found.protein_g, found.carbohydrate_g, found.fat_g, goals.sleep_minutes, "auto")
    return goals


def get_profile(session: Session, user_id: int) -> GoalProfile | None:
    return session.get(GoalProfile, user_id)


def save_profile(session: Session, user_id: int, values: dict) -> GoalProfile:
    profile = get_profile(session, user_id) or GoalProfile(user_id=user_id)
    for key, value in values.items():
        setattr(profile, key, value)
    profile.updated_at = utc_now()
    session.add(profile)
    commit(session)
    return profile


def delete_profile(session: Session, user_id: int) -> None:
    profile = get_profile(session, user_id)
    if profile is not None:
        session.delete(profile)
        commit(session)
