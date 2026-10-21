from datetime import date, datetime

from pydantic import BaseModel, Field, model_validator

from app.config import HISTORY_MAX_DAYS


class DailyReviewUpsert(BaseModel):
    total_reviews: int = Field(ge=0)
    # The study day, chosen by the client (so it also owns the day-rollover rule).
    study_date: date
    # Percent, 0-100. Omitted fields leave any stored value untouched.
    retention: float | None = Field(default=None, ge=0, le=100)
    study_minutes: float | None = Field(default=None, ge=0, le=1440)


class HistoryDay(BaseModel):
    study_date: date
    total_reviews: int = Field(ge=0)
    retention: float | None = Field(default=None, ge=0, le=100)
    study_minutes: float | None = Field(default=None, ge=0, le=1440)


class HistoryUpload(BaseModel):
    # Inclusive range the server replaces; dates in it missing from `days` are removed.
    start: date
    end: date
    days: list[HistoryDay] = Field(max_length=HISTORY_MAX_DAYS)

    @model_validator(mode="after")
    def check_range(self):
        if self.end < self.start:
            raise ValueError("end must not be before start")
        if (self.end - self.start).days > HISTORY_MAX_DAYS - 1:
            raise ValueError(f"range is limited to {HISTORY_MAX_DAYS} days")
        dates = [d.study_date for d in self.days]
        if any(d < self.start or d > self.end for d in dates):
            raise ValueError("every study_date must fall within start and end")
        if len(set(dates)) != len(dates):
            raise ValueError("study_date values must be unique")
        return self


class HistoryResult(BaseModel):
    start: date
    end: date
    days_written: int
    history_synced_at: datetime


class HistoryStatus(BaseModel):
    # null until the account has uploaded its history once.
    history_synced_at: datetime | None = None


class DailyReview(BaseModel):
    study_date: date
    total_reviews: int
    retention: float | None = None
    study_minutes: float | None = None
    updated_at: datetime
