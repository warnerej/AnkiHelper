from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from postgrest.exceptions import APIError
from supabase import Client

from app.models.profiles import FriendDailyReview, FriendReviews

DEFAULT_WINDOW_DAYS = 30
MAX_WINDOW_DAYS = 365


def _db_error(e: APIError) -> HTTPException:
    return HTTPException(status.HTTP_502_BAD_GATEWAY, e.message or "database error")


class ProfileService:
    """Expects a client authenticated as the caller (profiles are readable by any signed-in user)."""

    def __init__(self, client: Client):
        self._client = client

    def friend_reviews(
        self, username: str, days: int = DEFAULT_WINDOW_DAYS
    ) -> FriendReviews:
        # Clients own study_date, so "today" is UTC's; the query runs a day past it (see groups).
        end = datetime.now(timezone.utc).date()
        start = end - timedelta(days=days - 1)
        username = username.lower()
        try:
            profile = (
                self._client.table("profiles")
                .select("user_id,username")
                .eq("username", username)
                .execute()
            )
            if not profile.data:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "No such user")
            rows = self._client.rpc(
                "friend_daily_reviews",
                {
                    "p_user_id": profile.data[0]["user_id"],
                    "p_start": start.isoformat(),
                    "p_end": (end + timedelta(days=1)).isoformat(),
                },
            ).execute()
        except APIError as e:
            if e.message == "not_found":  # no shared group; same answer as an unknown user
                raise HTTPException(status.HTTP_404_NOT_FOUND, "No such user") from e
            raise _db_error(e) from e
        return FriendReviews(
            username=profile.data[0]["username"],
            start=start,
            end=end,
            days=[FriendDailyReview(**r) for r in rows.data],
        )
