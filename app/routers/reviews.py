from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query

from app.dependencies import CurrentUser, ReviewServiceDep
from app.models.reviews import (
    DailyReview,
    DailyReviewUpsert,
    HistoryResult,
    HistoryStatus,
    HistoryUpload,
)

router = APIRouter(prefix="/reviews", tags=["reviews"])


@router.put("/history", response_model=HistoryResult)
def replace_history(body: HistoryUpload, user: CurrentUser, reviews: ReviewServiceDep):
    """Replace the caller's daily totals for the inclusive range `start`..`end`.

    Rows in the range are deleted and `days` is inserted in their place, so a date in the range
    that is missing from `days` ends up with no reviews. Rows outside the range are untouched.
    The range is at most 365 days and `end` may be at most one day ahead of the server's date.
    Idempotent, so clients may retry. Limited to 5 successful uploads per hour (429). Upload
    after an Anki sync so the collection includes reviews done on mobile.
    """
    return reviews.replace_history(body, user.id)


@router.get("/history/status", response_model=HistoryStatus)
def history_status(user: CurrentUser, reviews: ReviewServiceDep):
    """When the caller last uploaded history; null if never (the add-on's backfill trigger)."""
    return reviews.history_status(user.id)


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
