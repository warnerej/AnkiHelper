from datetime import date, datetime

from pydantic import BaseModel, Field


class DailyReviewUpsert(BaseModel):
    total_reviews: int = Field(ge=0)
    # The study day, chosen by the client (so it also owns the day-rollover rule).
    study_date: date
    # Percent, 0-100. Omitted fields leave any stored value untouched.
    retention: float | None = Field(default=None, ge=0, le=100)
    study_minutes: float | None = Field(default=None, ge=0, le=1440)


class DailyReview(BaseModel):
    study_date: date
    total_reviews: int
    retention: float | None = None
    study_minutes: float | None = None
    updated_at: datetime
