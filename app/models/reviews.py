from datetime import date, datetime

from pydantic import BaseModel, Field


class DailyReviewUpsert(BaseModel):
    total_reviews: int = Field(ge=0)
    # The study day, chosen by the client (so it also owns the day-rollover rule).
    study_date: date


class DailyReview(BaseModel):
    study_date: date
    total_reviews: int
    updated_at: datetime
