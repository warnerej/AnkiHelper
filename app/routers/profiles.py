from fastapi import APIRouter, Query

from app.dependencies import CurrentUser, ProfileServiceDep
from app.models.profiles import FriendReviews
from app.services.profiles import DEFAULT_WINDOW_DAYS, MAX_WINDOW_DAYS

router = APIRouter(prefix="/profiles", tags=["profiles"])


@router.get("/{username}/reviews", response_model=FriendReviews, deprecated=True)
def friend_reviews(
    username: str,
    user: CurrentUser,
    profiles: ProfileServiceDep,
    days: int = Query(DEFAULT_WINDOW_DAYS, ge=1, le=MAX_WINDOW_DAYS),
):
    """Deprecated: use `GET /groups/{id}/reviews`.

    Another user's daily review totals for the past `days` days (default 30, max 365),
    only if you and that user have both joined a common group (404 otherwise).
    """
    return profiles.friend_reviews(username, days)
