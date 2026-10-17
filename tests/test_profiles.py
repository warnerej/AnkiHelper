from datetime import date, timedelta

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.dependencies import get_auth_service, get_profile_service
from app.main import app
from app.models.auth import UserResponse
from app.models.profiles import FriendDailyReview, FriendReviews

AUTH = {"Authorization": "Bearer acc"}


class FakeAuth:
    def get_user(self, token):
        if token != "acc":
            raise HTTPException(401, "nope")
        return UserResponse(id="u1")


class FakeProfiles:
    def __init__(self):
        today = date.today()
        self.users = {
            "bob": [
                FriendDailyReview(study_date=today, total_reviews=20, retention=88.0),
                FriendDailyReview(study_date=today - timedelta(days=1), total_reviews=10),
            ]
        }

    def friend_reviews(self, username, days=30):
        username = username.lower()
        if username not in self.users:
            raise HTTPException(404, "No such user")
        end = date.today()
        return FriendReviews(
            username=username,
            start=end - timedelta(days=days - 1),
            end=end,
            days=self.users[username],
        )


@pytest.fixture
def client():
    app.dependency_overrides[get_auth_service] = lambda: FakeAuth()
    app.dependency_overrides[get_profile_service] = lambda: FakeProfiles()
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_requires_auth(client):
    assert client.get("/profiles/bob/reviews").status_code in (401, 403)
    bad = {"Authorization": "Bearer bad"}
    assert client.get("/profiles/bob/reviews", headers=bad).status_code == 401


def test_friend_reviews(client):
    r = client.get("/profiles/bob/reviews", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["username"] == "bob"
    assert [d["total_reviews"] for d in body["days"]] == [20, 10]
    assert body["days"][0]["retention"] == 88.0
    assert body["days"][1]["study_minutes"] is None
    assert "updated_at" not in body["days"][0]
    assert date.fromisoformat(body["end"]) - date.fromisoformat(body["start"]) == timedelta(days=29)


def test_days_param(client):
    r = client.get("/profiles/bob/reviews?days=365", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert date.fromisoformat(body["end"]) - date.fromisoformat(body["start"]) == timedelta(days=364)


@pytest.mark.parametrize("days", [0, 366, "x"])
def test_days_param_out_of_range_422(client, days):
    r = client.get(f"/profiles/bob/reviews?days={days}", headers=AUTH)
    assert r.status_code == 422


def test_username_lookup_is_case_insensitive(client):
    assert client.get("/profiles/BOB/reviews", headers=AUTH).status_code == 200


def test_unknown_user_404(client):
    assert client.get("/profiles/nobody/reviews", headers=AUTH).status_code == 404
