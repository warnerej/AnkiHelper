from fastapi import APIRouter, Query

from app.dependencies import CurrentUser, ProfileServiceDep
from app.models.profiles import FriendReviews
from app.services.profiles import DEFAULT_WINDOW_DAYS, MAX_WINDOW_DAYS

router = APIRouter(prefix="/profiles", tags=["profiles"])


@router.get("/{username}/reviews", response_model=FriendReviews)
def friend_reviews(
    username: str,
    user: CurrentUser,
    profiles: ProfileServiceDep,
    days: int = Query(DEFAULT_WINDOW_DAYS, ge=1, le=MAX_WINDOW_DAYS),
):
    """Another user's daily review totals for the past `days` days (default 30, max 365)."""
    return profiles.friend_reviews(username, days)
