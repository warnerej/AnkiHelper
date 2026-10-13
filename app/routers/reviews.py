from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query

from app.dependencies import CurrentUser, ReviewServiceDep
from app.models.reviews import DailyReview, DailyReviewUpsert

router = APIRouter(prefix="/reviews", tags=["reviews"])


@router.put("/daily", response_model=DailyReview)
def upsert_daily(body: DailyReviewUpsert, user: CurrentUser, reviews: ReviewServiceDep):
    return reviews.upsert(body)


@router.get("/daily", response_model=list[DailyReview])
def list_daily(
    user: CurrentUser,
    reviews: ReviewServiceDep,
    start: date | None = None,
    end: date | None = None,
    limit: Annotated[int, Query(ge=1, le=365)] = 90,
):
    return reviews.list(start, end, limit)


@router.get("/daily/{study_date}", response_model=DailyReview)
def get_daily(study_date: date, user: CurrentUser, reviews: ReviewServiceDep):
    return reviews.get(study_date)
