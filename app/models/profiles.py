from datetime import date

from pydantic import BaseModel


class FriendDailyReview(BaseModel):
    study_date: date
    total_reviews: int
    retention: float | None = None
    study_minutes: float | None = None


class FriendReviews(BaseModel):
    username: str
    start: date
    end: date
    days: list[FriendDailyReview]
