from datetime import date, datetime, timedelta, timezone
from itertools import count
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from postgrest.exceptions import APIError

from app.config import JOIN_MAX_FAILURES, MAX_ALLOWED_USERNAMES, MAX_OWNED_GROUPS
from app.dependencies import CurrentUser, get_auth_service, get_group_service
from app.main import app
from app.models.auth import UserResponse
from app.models.groups import GroupDetail, GroupReviews, GroupSummary, Member, MemberReviews
from app.models.profiles import FriendDailyReview
from app.services.groups import GroupService

USERS = {"alice": "u-alice", "bob": "u-bob", "carol": "u-carol"}
NAME_OF = {v: k for k, v in USERS.items()}
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def auth(who):
    return {"Authorization": f"Bearer {who}"}


class FakeAuth:
    def get_user(self, token):
        if token not in USERS:
            raise HTTPException(401, "nope")
        return UserResponse(id=USERS[token])


class Store:
    """In-memory stand-in for the Postgres rules in 0004_groups.sql."""

    def __init__(self):
        self.groups = {}  # id -> {name, owner, code, allowed:set, members:{user: (role, joined)}}
        self.codes = count(1)
        self.join_failures = {}  # username -> failed joins in the window
        self.reviews = {}  # username -> [FriendDailyReview]


class FakeGroups:
    def __init__(self, store: Store, user: UserResponse):
        self.s = store
        self.me = NAME_OF[user.id]

    def _member_group(self, gid):
        g = self.s.groups.get(gid)
        if not g or self.me not in g["members"]:
            raise HTTPException(404, "Group not found")
        return g

    def _owned(self, gid):
        g = self._member_group(gid)
        if g["owner"] != self.me:
            raise HTTPException(403, "owner only")
        return g

    def _detail(self, gid, g):
        d = GroupDetail(
            id=gid,
            name=g["name"],
            owner=g["owner"],
            members=[
                Member(username=u, role=r, joined_at=j + timedelta(seconds=i))
                for i, (u, (r, j)) in enumerate(g["members"].items())
            ],
        )
        if g["owner"] == self.me:
            d.invite_code = g["code"]
            d.allowed = sorted(g["allowed"])
        return d

    def create(self, name):
        if sum(g["owner"] == self.me for g in self.s.groups.values()) >= MAX_OWNED_GROUPS:
            raise HTTPException(409, "Limit reached")
        gid = uuid4()
        self.s.groups[gid] = {
            "name": name,
            "owner": self.me,
            "code": f"AAAA-{next(self.s.codes):04d}",
            "allowed": set(),
            "members": {self.me: ("owner", NOW)},
        }
        return self._detail(gid, self.s.groups[gid])

    def list(self):
        return [
            GroupSummary(
                id=i,
                name=g["name"],
                role=g["members"][self.me][0],
                member_count=len(g["members"]),
            )
            for i, g in self.s.groups.items()
            if self.me in g["members"]
        ]

    def get(self, gid):
        return self._detail(gid, self._member_group(gid))

    def rename(self, gid, name):
        g = self._owned(gid)
        g["name"] = name
        return self._detail(gid, g)

    def delete(self, gid):
        self._owned(gid)
        del self.s.groups[gid]

    def join(self, code):
        failures = self.s.join_failures.get(self.me, 0)
        if failures >= JOIN_MAX_FAILURES:
            raise HTTPException(429, "Too many failed join attempts; try again later")
        for gid, g in self.s.groups.items():
            if g["code"] == code and self.me in g["allowed"]:
                g["members"].setdefault(self.me, ("member", NOW))
                return self._detail(gid, g)
        self.s.join_failures[self.me] = failures + 1
        raise HTTPException(404, "Group not found")

    def leave(self, gid):
        g = self._member_group(gid)
        if g["owner"] == self.me:
            raise HTTPException(409, "owner can't leave")
        del g["members"][self.me]

    def allow(self, gid, username):
        g = self._owned(gid)
        if username not in g["allowed"] and len(g["allowed"]) >= MAX_ALLOWED_USERNAMES:
            raise HTTPException(409, "Limit reached")
        g["allowed"].add(username)
        return self._detail(gid, g)

    def disallow(self, gid, username):
        g = self._owned(gid)
        if username == g["owner"]:
            raise HTTPException(409, "owner can't be removed")
        g["allowed"].discard(username)
        g["members"].pop(username, None)

    def regenerate_invite_code(self, gid):
        g = self._owned(gid)
        g["code"] = f"BBBB-{next(self.s.codes):04d}"
        return g["code"]

    def transfer(self, gid, username):
        g = self._owned(gid)
        if username not in g["members"]:
            raise HTTPException(409, "not a member")
        g["members"][self.me] = ("member", g["members"][self.me][1])
        g["members"][username] = ("owner", g["members"][username][1])
        g["owner"] = username
        return self._detail(gid, g)

    def reviews(self, gid, days=30):
        g = self._member_group(gid)
        end = date.today()
        return GroupReviews(
            group_id=gid,
            start=end - timedelta(days=days - 1),
            end=end,
            members=[
                MemberReviews(username=u, days=self.s.reviews.get(u, [])) for u in g["members"]
            ],
        )


@pytest.fixture
def store():
    return Store()


@pytest.fixture
def client(store):
    def group_service(user: CurrentUser):
        return FakeGroups(store, user)

    app.dependency_overrides[get_auth_service] = lambda: FakeAuth()
    app.dependency_overrides[get_group_service] = group_service
    yield TestClient(app)
    app.dependency_overrides.clear()


def make_group(client, who="alice", name="Study"):
    r = client.post("/groups", json={"name": name}, headers=auth(who))
    assert r.status_code == 201
    return r.json()


def join_with(client, who, g):
    client.post(f"/groups/{g['id']}/allowed", json={"username": who}, headers=auth("alice"))
    return client.post("/groups/join", json={"invite_code": g["invite_code"]}, headers=auth(who))


def test_requires_auth(client):
    assert client.get("/groups").status_code in (401, 403)
    assert client.get("/groups", headers=auth("nobody")).status_code == 401


def test_lifecycle(client, store):
    today = date.today()
    store.reviews["alice"] = [FriendDailyReview(study_date=today, total_reviews=5)]
    store.reviews["bob"] = [FriendDailyReview(study_date=today, total_reviews=9, retention=90.0)]

    g = make_group(client)
    assert g["owner"] == "alice" and g["invite_code"] and g["allowed"] == []

    r = client.post(f"/groups/{g['id']}/allowed", json={"username": "Bob"}, headers=auth("alice"))
    assert r.json()["allowed"] == ["bob"]

    r = client.post("/groups/join", json={"invite_code": g["invite_code"]}, headers=auth("bob"))
    assert r.status_code == 200
    body = r.json()
    assert {m["username"] for m in body["members"]} == {"alice", "bob"}
    # Plain members don't see the code or the allowed list.
    assert "invite_code" not in body and "allowed" not in body

    r = client.get(f"/groups/{g['id']}/reviews", headers=auth("bob"))
    assert r.status_code == 200
    by_user = {m["username"]: m["days"] for m in r.json()["members"]}
    assert by_user["alice"][0]["total_reviews"] == 5
    assert by_user["bob"][0]["retention"] == 90.0

    assert client.post(f"/groups/{g['id']}/leave", headers=auth("bob")).status_code == 204
    assert client.get(f"/groups/{g['id']}/reviews", headers=auth("bob")).status_code == 404

    # Still on the allowed list, so rejoining works.
    r = client.post("/groups/join", json={"invite_code": g["invite_code"]}, headers=auth("bob"))
    assert r.status_code == 200
    assert client.get(f"/groups/{g['id']}/reviews", headers=auth("bob")).status_code == 200


def test_list_groups(client):
    g = make_group(client)
    join_with(client, "bob", g)
    rows = client.get("/groups", headers=auth("bob")).json()
    assert rows == [{"id": g["id"], "name": "Study", "role": "member", "member_count": 2}]
    assert client.get("/groups", headers=auth("carol")).json() == []


def test_not_allowed_cannot_join_and_error_matches_bad_code(client):
    g = make_group(client)
    not_allowed = client.post(
        "/groups/join", json={"invite_code": g["invite_code"]}, headers=auth("carol")
    )
    bad_code = client.post("/groups/join", json={"invite_code": "ZZZZ-9999"}, headers=auth("carol"))
    assert not_allowed.status_code == bad_code.status_code == 404
    assert not_allowed.json() == bad_code.json()


def test_join_rate_limited_after_repeated_failures(client):
    g = make_group(client)
    bad = {"invite_code": "ZZZZ-9999"}
    for _ in range(JOIN_MAX_FAILURES):
        assert client.post("/groups/join", json=bad, headers=auth("carol")).status_code == 404
    # Even the right code (once allowed) is refused until the window passes...
    client.post(f"/groups/{g['id']}/allowed", json={"username": "carol"}, headers=auth("alice"))
    good = {"invite_code": g["invite_code"]}
    assert client.post("/groups/join", json=good, headers=auth("carol")).status_code == 429
    # ...and the limit is per user.
    join_with(client, "bob", g)
    assert client.get("/groups", headers=auth("bob")).json()[0]["role"] == "member"


def test_disallow_removes_membership_and_access(client):
    g = make_group(client)
    join_with(client, "bob", g)
    r = client.delete(f"/groups/{g['id']}/allowed/bob", headers=auth("alice"))
    assert r.status_code == 204
    assert client.get(f"/groups/{g['id']}/reviews", headers=auth("bob")).status_code == 404
    members = client.get(f"/groups/{g['id']}/reviews", headers=auth("alice")).json()["members"]
    assert [m["username"] for m in members] == ["alice"]
    # And can't come back with the code.
    r = client.post("/groups/join", json={"invite_code": g["invite_code"]}, headers=auth("bob"))
    assert r.status_code == 404


def test_owner_cannot_leave_or_be_disallowed(client):
    g = make_group(client)
    assert client.post(f"/groups/{g['id']}/leave", headers=auth("alice")).status_code == 409
    r = client.delete(f"/groups/{g['id']}/allowed/alice", headers=auth("alice"))
    assert r.status_code == 409


def test_transfer_ownership(client):
    g = make_group(client)
    r = client.post(f"/groups/{g['id']}/transfer", json={"username": "bob"}, headers=auth("alice"))
    assert r.status_code == 409  # bob hasn't joined

    join_with(client, "bob", g)
    r = client.post(f"/groups/{g['id']}/transfer", json={"username": "bob"}, headers=auth("alice"))
    assert r.status_code == 200 and r.json()["owner"] == "bob"
    # Alice is now a plain member: she can leave but can't manage.
    r = client.post(f"/groups/{g['id']}/allowed", json={"username": "carol"}, headers=auth("alice"))
    assert r.status_code == 403
    assert client.post(f"/groups/{g['id']}/leave", headers=auth("alice")).status_code == 204


def test_delete_group_cascades(client, store):
    g = make_group(client)
    join_with(client, "bob", g)
    assert client.delete(f"/groups/{g['id']}", headers=auth("bob")).status_code == 403
    assert client.delete(f"/groups/{g['id']}", headers=auth("alice")).status_code == 204
    assert store.groups == {}
    for who in ("alice", "bob"):
        assert client.get(f"/groups/{g['id']}", headers=auth(who)).status_code == 404
    r = client.post("/groups/join", json={"invite_code": g["invite_code"]}, headers=auth("bob"))
    assert r.status_code == 404


def test_non_member_gets_404(client):
    g = make_group(client)
    for path in ("", "/reviews"):
        assert client.get(f"/groups/{g['id']}{path}", headers=auth("carol")).status_code == 404
    missing = client.get(f"/groups/{uuid4()}", headers=auth("carol"))
    existing = client.get(f"/groups/{g['id']}", headers=auth("carol"))
    assert missing.status_code == 404 and missing.json() == existing.json()


def test_owner_only_actions_forbidden_for_members(client):
    g = make_group(client)
    join_with(client, "bob", g)
    b, gid = auth("bob"), g["id"]
    assert client.patch(f"/groups/{gid}", json={"name": "x"}, headers=b).status_code == 403
    assert client.post(f"/groups/{gid}/invite-code", headers=b).status_code == 403
    r = client.post(f"/groups/{gid}/allowed", json={"username": "carol"}, headers=b)
    assert r.status_code == 403
    assert client.delete(f"/groups/{gid}/allowed/carol", headers=b).status_code == 403


def test_rename_and_regenerate_invite_code(client):
    g = make_group(client)
    r = client.patch(f"/groups/{g['id']}", json={"name": "Renamed"}, headers=auth("alice"))
    assert r.json()["name"] == "Renamed"
    r = client.post(f"/groups/{g['id']}/invite-code", headers=auth("alice"))
    new = r.json()["invite_code"]
    assert new != g["invite_code"]
    assert join_with(client, "bob", {**g, "invite_code": new}).status_code == 200
    r = client.post("/groups/join", json={"invite_code": g["invite_code"]}, headers=auth("carol"))
    assert r.status_code == 404  # old code is dead


def test_limits(client):
    for i in range(MAX_OWNED_GROUPS):
        make_group(client, name=f"g{i}")
    r = client.post("/groups", json={"name": "one too many"}, headers=auth("alice"))
    assert r.status_code == 409

    gid = client.get("/groups", headers=auth("alice")).json()[0]["id"]

    def allow(name):
        return client.post(
            f"/groups/{gid}/allowed", json={"username": name}, headers=auth("alice")
        )

    for i in range(MAX_ALLOWED_USERNAMES):
        assert allow(f"user_{i:03d}").status_code == 200
    assert allow("extra_user").status_code == 409
    # Re-adding an existing name isn't a new entry.
    assert allow("user_000").status_code == 200


@pytest.mark.parametrize("name", ["", "   ", "x" * 51])
def test_invalid_group_name_422(client, name):
    assert client.post("/groups", json={"name": name}, headers=auth("alice")).status_code == 422


@pytest.mark.parametrize("username", ["ab", "bad name", "x" * 21])
def test_invalid_username_422(client, username):
    g = make_group(client)
    r = client.post(
        f"/groups/{g['id']}/allowed", json={"username": username}, headers=auth("alice")
    )
    assert r.status_code == 422


@pytest.mark.parametrize("days", [0, 366, "x"])
def test_reviews_days_out_of_range_422(client, days):
    g = make_group(client)
    r = client.get(f"/groups/{g['id']}/reviews?days={days}", headers=auth("alice"))
    assert r.status_code == 422


def test_reviews_window(client):
    g = make_group(client)
    body = client.get(f"/groups/{g['id']}/reviews?days=365", headers=auth("alice")).json()
    assert date.fromisoformat(body["end"]) - date.fromisoformat(body["start"]) == timedelta(days=364)
    body = client.get(f"/groups/{g['id']}/reviews", headers=auth("alice")).json()
    assert date.fromisoformat(body["end"]) - date.fromisoformat(body["start"]) == timedelta(days=29)


# --- GroupService against a stub Supabase client -----------------------------------------


class StubClient:
    def __init__(self, data=None, error=None):
        self.data, self.error, self.calls = data, error, []

    def rpc(self, fn, params):
        self.calls.append((fn, params))
        return self

    def execute(self):
        if self.error:
            raise APIError({"message": self.error, "code": "P0001"})
        return SimpleNamespace(data=self.data)


@pytest.mark.parametrize(
    "token,code",
    [
        ("not_found", 404),
        ("forbidden", 403),
        ("owner_cannot_leave", 409),
        ("limit_reached", 409),
        ("rate_limited", 429),
        ("invalid_name", 422),
        ("something else", 502),
    ],
)
def test_service_maps_db_errors(token, code):
    svc = GroupService(StubClient(error=token))
    with pytest.raises(HTTPException) as e:
        svc.leave(uuid4())
    assert e.value.status_code == code


def test_service_groups_review_rows_by_member():
    today = datetime.now(timezone.utc).date().isoformat()
    rows = [
        {"username": "alice", "days": [
            {"study_date": today, "total_reviews": 3, "retention": None, "study_minutes": 1.5}]},
        {"username": "bob", "days": []},
    ]
    stub = StubClient(data=rows)
    gid = UUID(int=1)
    out = GroupService(stub).reviews(gid, days=7)
    assert [(m.username, len(m.days)) for m in out.members] == [("alice", 1), ("bob", 0)]
    assert out.members[0].days[0].study_minutes == 1.5
    fn, params = stub.calls[0]
    assert fn == "group_reviews_by_member" and params["p_group_id"] == str(gid)
    # The window runs a day past the reported end for clients ahead of UTC.
    assert date.fromisoformat(params["p_end"]) - out.end == timedelta(days=1)
    assert date.fromisoformat(params["p_end"]) - date.fromisoformat(params["p_start"]) == timedelta(
        days=7
    )


def test_service_join_null_result_is_404():
    # join_group returns null (rather than raising) so the failed attempt can be recorded.
    with pytest.raises(HTTPException) as e:
        GroupService(StubClient(data=None)).join("ZZZZ-9999")
    assert e.value.status_code == 404
    assert e.value.detail == "Group not found"
