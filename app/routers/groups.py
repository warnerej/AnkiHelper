from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from app.dependencies import CurrentUser, GroupServiceDep
from app.models.groups import (
    GroupDetail,
    GroupName,
    GroupReviews,
    GroupSummary,
    InviteCode,
    JoinRequest,
    UsernameRequest,
)
from app.services.profiles import DEFAULT_WINDOW_DAYS, MAX_WINDOW_DAYS

router = APIRouter(prefix="/groups", tags=["groups"])

# Group responses omit invite_code/allowed for plain members rather than sending nulls.
DETAIL = {"response_model": GroupDetail, "response_model_exclude_none": True}


@router.post("", status_code=status.HTTP_201_CREATED, **DETAIL)
def create_group(body: GroupName, user: CurrentUser, groups: GroupServiceDep):
    return groups.create(body.name)


@router.get("", response_model=list[GroupSummary])
def list_groups(user: CurrentUser, groups: GroupServiceDep):
    return groups.list()


# Registered before the /{group_id} routes so "join" is never read as an id.
@router.post("/join", **DETAIL)
def join_group(body: JoinRequest, user: CurrentUser, groups: GroupServiceDep):
    """404 for a bad code and for "not on the allowed list" alike; 429 after too many failures."""
    return groups.join(body.invite_code)


@router.get("/{group_id}", **DETAIL)
def get_group(group_id: UUID, user: CurrentUser, groups: GroupServiceDep):
    return groups.get(group_id)


@router.patch("/{group_id}", **DETAIL)
def rename_group(group_id: UUID, body: GroupName, user: CurrentUser, groups: GroupServiceDep):
    return groups.rename(group_id, body.name)


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_group(group_id: UUID, user: CurrentUser, groups: GroupServiceDep):
    groups.delete(group_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{group_id}/leave", status_code=status.HTTP_204_NO_CONTENT)
def leave_group(group_id: UUID, user: CurrentUser, groups: GroupServiceDep):
    groups.leave(group_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{group_id}/allowed", **DETAIL)
def allow_username(
    group_id: UUID, body: UsernameRequest, user: CurrentUser, groups: GroupServiceDep
):
    """Adds the username to the allowed list (it needn't exist yet); returns the group."""
    return groups.allow(group_id, body.username)


@router.delete("/{group_id}/allowed/{username}", status_code=status.HTTP_204_NO_CONTENT)
def disallow_username(
    group_id: UUID, username: str, user: CurrentUser, groups: GroupServiceDep
):
    """Also removes that user's membership."""
    groups.disallow(group_id, username)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{group_id}/invite-code", response_model=InviteCode)
def regenerate_invite_code(group_id: UUID, user: CurrentUser, groups: GroupServiceDep):
    return InviteCode(invite_code=groups.regenerate_invite_code(group_id))


@router.post("/{group_id}/transfer", **DETAIL)
def transfer_ownership(
    group_id: UUID, body: UsernameRequest, user: CurrentUser, groups: GroupServiceDep
):
    return groups.transfer(group_id, body.username)


@router.get("/{group_id}/reviews", response_model=GroupReviews)
def group_reviews(
    group_id: UUID,
    user: CurrentUser,
    groups: GroupServiceDep,
    days: int = Query(DEFAULT_WINDOW_DAYS, ge=1, le=MAX_WINDOW_DAYS),
):
    """Every joined member's daily rows for the past `days` days (default 30, max 365)."""
    return groups.reviews(group_id, days)
