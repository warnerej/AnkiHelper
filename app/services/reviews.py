from datetime import date

from fastapi import HTTPException, status
from postgrest.exceptions import APIError
from supabase import Client

from app.models.reviews import (
    DailyReview,
    DailyReviewUpsert,
    HistoryResult,
    HistoryStatus,
    HistoryUpload,
)

COLUMNS = "study_date,total_reviews,retention,study_minutes,updated_at"

# Error tokens raised by replace_daily_reviews in supabase/migrations/0008_review_history.sql.
ERROR_STATUS = {
    "rate_limited": (
        status.HTTP_429_TOO_MANY_REQUESTS,
        "Too many history uploads; try again later",
    ),
    "invalid_range": (422, "Invalid date range"),
}


def _db_error(e: APIError) -> HTTPException:
    if e.message in ERROR_STATUS:
        code, detail = ERROR_STATUS[e.message]
        return HTTPException(code, detail)
    return HTTPException(status.HTTP_502_BAD_GATEWAY, e.message or "database error")


class ReviewService:
    """Expects a client authenticated as the user, so RLS scopes every query."""

    def __init__(self, client: Client):
        self._client = client
        self._table = client.table("daily_reviews")

    def _synced_at(self, user_id: str) -> str | None:
        # profiles is readable by everyone, so filter to the caller's row explicitly.
        try:
            res = (
                self._client.table("profiles")
                .select("history_synced_at")
                .eq("user_id", user_id)
                .execute()
            )
        except APIError as e:
            raise _db_error(e) from e
        return res.data[0]["history_synced_at"] if res.data else None

    def replace_history(self, body: HistoryUpload, user_id: str) -> HistoryResult:
        params = {
            "p_start": body.start.isoformat(),
            "p_end": body.end.isoformat(),
            "p_days": [d.model_dump(mode="json") for d in body.days],
        }
        try:
            written = self._client.rpc("replace_daily_reviews", params).execute().data
        except APIError as e:
            raise _db_error(e) from e
        synced_at = self._synced_at(user_id)
        if synced_at is None:  # no profile row to stamp, so the SQL couldn't record the sync
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "profile not found")
        return HistoryResult(
            start=body.start, end=body.end, days_written=written, history_synced_at=synced_at
        )

    def history_status(self, user_id: str) -> HistoryStatus:
        return HistoryStatus(history_synced_at=self._synced_at(user_id))

    def upsert(self, body: DailyReviewUpsert) -> DailyReview:
        row = {
            "study_date": body.study_date.isoformat(),
            "total_reviews": body.total_reviews,
        }
        # Only send optional stats that were provided, so a partial PUT keeps stored values.
        if body.retention is not None:
            row["retention"] = body.retention
        if body.study_minutes is not None:
            row["study_minutes"] = body.study_minutes
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
