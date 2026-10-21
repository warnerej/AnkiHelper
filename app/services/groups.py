from datetime import date, timedelta
from uuid import UUID

from fastapi import HTTPException, status
from postgrest.exceptions import APIError
from supabase import Client

from app.models.groups import (
    GroupDetail,
    GroupReviews,
    GroupSummary,
    MemberReviews,
)
from app.models.profiles import FriendDailyReview
from app.services.profiles import DEFAULT_WINDOW_DAYS

# Error tokens raised by the SQL functions in supabase/migrations/0004_groups.sql.
ERROR_STATUS = {
    "not_found": (status.HTTP_404_NOT_FOUND, "Group not found"),
    "forbidden": (status.HTTP_403_FORBIDDEN, "Only the group owner can do that"),
    "owner_cannot_leave": (
        status.HTTP_409_CONFLICT,
        "The owner can't leave; transfer ownership or delete the group",
    ),
    "cannot_remove_owner": (status.HTTP_409_CONFLICT, "The owner can't be removed"),
    "limit_reached": (status.HTTP_409_CONFLICT, "Limit reached"),
    "not_member": (status.HTTP_409_CONFLICT, "That user hasn't joined the group"),
    "rate_limited": (
        status.HTTP_429_TOO_MANY_REQUESTS,
        "Too many failed join attempts; try again later",
    ),
    "invalid_name": (422, "Invalid group name"),
    "invalid_username": (422, "Invalid username"),
}


def _db_error(e: APIError) -> HTTPException:
    if e.message in ERROR_STATUS:
        code, detail = ERROR_STATUS[e.message]
        return HTTPException(code, detail)
    return HTTPException(status.HTTP_502_BAD_GATEWAY, e.message or "database error")


class GroupService:
    """Expects a client authenticated as the user; every rule is enforced in Postgres."""

    def __init__(self, client: Client):
        self._client = client

    def _rpc(self, fn: str, params: dict | None = None):
        try:
            return self._client.rpc(fn, params or {}).execute().data
        except APIError as e:
            raise _db_error(e) from e

    def create(self, name: str) -> GroupDetail:
        return self.get(self._rpc("create_group", {"p_name": name}))

    def list(self) -> list[GroupSummary]:
        return [GroupSummary(**r) for r in self._rpc("my_groups")]

    def get(self, group_id: UUID | str) -> GroupDetail:
        return GroupDetail(**self._rpc("get_group", {"p_group_id": str(group_id)}))

    def rename(self, group_id: UUID, name: str) -> GroupDetail:
        self._rpc("rename_group", {"p_group_id": str(group_id), "p_name": name})
        return self.get(group_id)

    def delete(self, group_id: UUID) -> None:
        self._rpc("delete_group", {"p_group_id": str(group_id)})

    def join(self, invite_code: str) -> GroupDetail:
        gid = self._rpc("join_group", {"p_code": invite_code})
        if gid is None:  # bad code or not allowed: same answer (the SQL records the failure)
            code, detail = ERROR_STATUS["not_found"]
            raise HTTPException(code, detail)
        return self.get(gid)

    def leave(self, group_id: UUID) -> None:
        self._rpc("leave_group", {"p_group_id": str(group_id)})

    def allow(self, group_id: UUID, username: str) -> GroupDetail:
        self._rpc("allow_username", {"p_group_id": str(group_id), "p_username": username})
        return self.get(group_id)

    def disallow(self, group_id: UUID, username: str) -> None:
        self._rpc("disallow_username", {"p_group_id": str(group_id), "p_username": username})

    def regenerate_invite_code(self, group_id: UUID) -> str:
        return self._rpc("regenerate_invite_code", {"p_group_id": str(group_id)})

    def transfer(self, group_id: UUID, username: str) -> GroupDetail:
        self._rpc("transfer_ownership", {"p_group_id": str(group_id), "p_username": username})
        return self.get(group_id)

    def reviews(self, group_id: UUID, days: int = DEFAULT_WINDOW_DAYS) -> GroupReviews:
        # The server has no timezone logic (clients own study_date), so "today" is the server's.
        end = date.today()
        start = end - timedelta(days=days - 1)
        rows = self._rpc(
            "group_reviews",
            {
                "p_group_id": str(group_id),
                "p_start": start.isoformat(),
                "p_end": end.isoformat(),
            },
        )
        # The function returns one row per member-day, plus a null-date row for members
        # with no data in the window, so every member appears even with `days: []`.
        by_user: dict[str, list[FriendDailyReview]] = {}
        for r in rows:
            days_list = by_user.setdefault(r["username"], [])
            if r["study_date"] is not None:
                days_list.append(
                    FriendDailyReview(
                        study_date=r["study_date"],
                        total_reviews=r["total_reviews"],
                        retention=r["retention"],
                        study_minutes=r["study_minutes"],
                    )
                )
        return GroupReviews(
            group_id=group_id,
            start=start,
            end=end,
            members=[MemberReviews(username=u, days=d) for u, d in by_user.items()],
        )
