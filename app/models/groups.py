from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.models.profiles import FriendDailyReview


class GroupName(BaseModel):
    name: str = Field(min_length=1, max_length=50)

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be blank")
        return v


class JoinRequest(BaseModel):
    invite_code: str = Field(min_length=1, max_length=32)


class UsernameRequest(BaseModel):
    username: str = Field(pattern=r"^[A-Za-z0-9_]{3,20}$")

    @field_validator("username")
    @classmethod
    def _lowercase(cls, v: str) -> str:
        return v.lower()


class InviteCode(BaseModel):
    invite_code: str


class GroupSummary(BaseModel):
    id: UUID
    name: str
    role: str
    member_count: int


class Member(BaseModel):
    username: str
    role: str
    joined_at: datetime


class GroupDetail(BaseModel):
    id: UUID
    name: str
    owner: str
    members: list[Member]
    # Owner only; omitted from the response for plain members.
    invite_code: str | None = None
    allowed: list[str] | None = None


class MemberReviews(BaseModel):
    username: str
    days: list[FriendDailyReview]


class GroupReviews(BaseModel):
    group_id: UUID
    start: date
    end: date
    members: list[MemberReviews]
