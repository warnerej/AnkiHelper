from datetime import date, timedelta

from fastapi import HTTPException, status
from postgrest.exceptions import APIError
from supabase import Client

from app.models.profiles import FriendDailyReview, FriendReviews

WINDOW_DAYS = 30


def _db_error(e: APIError) -> HTTPException:
    return HTTPException(status.HTTP_502_BAD_GATEWAY, e.message or "database error")


class ProfileService:
    """Expects a client authenticated as the caller (profiles are readable by any signed-in user)."""

    def __init__(self, client: Client):
        self._client = client

    def friend_reviews(self, username: str) -> FriendReviews:
        # The server has no timezone logic (clients own study_date), so "today" is the server's.
        end = date.today()
        start = end - timedelta(days=WINDOW_DAYS - 1)
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
                    "p_end": end.isoformat(),
                },
            ).execute()
        except APIError as e:
            raise _db_error(e) from e
        return FriendReviews(
            username=profile.data[0]["username"],
            start=start,
            end=end,
            days=[FriendDailyReview(**r) for r in rows.data],
        )
