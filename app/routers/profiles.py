from fastapi import APIRouter

from app.dependencies import CurrentUser, ProfileServiceDep
from app.models.profiles import FriendReviews

router = APIRouter(prefix="/profiles", tags=["profiles"])


@router.get("/{username}/reviews", response_model=FriendReviews)
def friend_reviews(username: str, user: CurrentUser, profiles: ProfileServiceDep):
    """Another user's daily review totals for the past 30 days."""
    return profiles.friend_reviews(username)
