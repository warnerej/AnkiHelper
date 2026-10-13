from datetime import date

from fastapi import HTTPException, status
from postgrest.exceptions import APIError
from supabase import Client

from app.models.reviews import DailyReview

COLUMNS = "study_date,total_reviews,updated_at"


def _db_error(e: APIError) -> HTTPException:
    return HTTPException(status.HTTP_502_BAD_GATEWAY, e.message or "database error")


class ReviewService:
    """Expects a client authenticated as the user, so RLS scopes every query."""

    def __init__(self, client: Client):
        self._table = client.table("daily_reviews")

    def upsert(self, study_date: date, total_reviews: int) -> DailyReview:
        row = {
            "study_date": study_date.isoformat(),
            "total_reviews": total_reviews,
        }
        try:
            # user_id is omitted so the column default (auth.uid()) fills it.
            res = (
                self._table.upsert(row, on_conflict="user_id,study_date")
                .execute()
            )
        except APIError as e:
            raise _db_error(e) from e
        return DailyReview(**res.data[0])

    def list(self, start: date | None, end: date | None, limit: int) -> list[DailyReview]:
        q = self._table.select(COLUMNS).order("study_date", desc=True).limit(limit)
        if start:
            q = q.gte("study_date", start.isoformat())
        if end:
            q = q.lte("study_date", end.isoformat())
        try:
            res = q.execute()
        except APIError as e:
            raise _db_error(e) from e
        return [DailyReview(**r) for r in res.data]

    def get(self, study_date: date) -> DailyReview:
        try:
            res = (
                self._table.select(COLUMNS)
                .eq("study_date", study_date.isoformat())
                .execute()
            )
        except APIError as e:
            raise _db_error(e) from e
        if not res.data:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No entry for that date")
        return DailyReview(**res.data[0])
