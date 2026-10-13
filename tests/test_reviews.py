from datetime import date, datetime, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.dependencies import get_auth_service, get_review_service
from app.main import app
from app.models.auth import UserResponse
from app.models.reviews import DailyReview

AUTH = {"Authorization": "Bearer acc"}
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


class FakeAuth:
    def get_user(self, token):
        if token != "acc":
            raise HTTPException(401, "nope")
        return UserResponse(id="u1")


class FakeReviews:
    def __init__(self):
        self.rows = {}

    def upsert(self, d, total):
        self.rows[d] = DailyReview(study_date=d, total_reviews=total, updated_at=NOW)
        return self.rows[d]

    def list(self, start, end, limit):
        return sorted(self.rows.values(), key=lambda r: r.study_date, reverse=True)

    def get(self, d):
        if d not in self.rows:
            raise HTTPException(404, "none")
        return self.rows[d]


@pytest.fixture
def fake():
    return FakeReviews()


@pytest.fixture
def client(fake):
    app.dependency_overrides[get_auth_service] = lambda: FakeAuth()
    app.dependency_overrides[get_review_service] = lambda: fake
    yield TestClient(app)
    app.dependency_overrides.clear()


BODY = {"total_reviews": 10, "study_date": "2026-01-01"}


def test_requires_auth(client):
    assert client.put("/reviews/daily", json=BODY).status_code in (401, 403)
    bad = {"Authorization": "Bearer bad"}
    assert client.put("/reviews/daily", json=BODY, headers=bad).status_code == 401
    assert client.get("/reviews/daily", headers=bad).status_code == 401
    assert client.get("/reviews/daily/2026-01-01", headers=bad).status_code == 401


def test_put_twice_keeps_one_row_with_latest_total(client):
    client.put("/reviews/daily", json=BODY, headers=AUTH)
    r = client.put("/reviews/daily", json={**BODY, "total_reviews": 25}, headers=AUTH)
    assert r.status_code == 200
    assert r.json()["total_reviews"] == 25
    rows = client.get("/reviews/daily", headers=AUTH).json()
    assert len(rows) == 1


def test_put_different_dates_make_separate_rows(client):
    client.put("/reviews/daily", json=BODY, headers=AUTH)
    client.put("/reviews/daily", json={**BODY, "study_date": "2026-01-02"}, headers=AUTH)
    rows = client.get("/reviews/daily", headers=AUTH).json()
    assert [r["study_date"] for r in rows] == ["2026-01-02", "2026-01-01"]


def test_put_validates_input(client):
    assert client.put("/reviews/daily", json={**BODY, "total_reviews": -1}, headers=AUTH).status_code == 422
    assert client.put("/reviews/daily", json={**BODY, "study_date": "not-a-date"}, headers=AUTH).status_code == 422
    assert client.put("/reviews/daily", json={"total_reviews": 10}, headers=AUTH).status_code == 422


def test_get_one_and_404(client):
    client.put("/reviews/daily", json=BODY, headers=AUTH)
    assert client.get("/reviews/daily/2026-01-01", headers=AUTH).status_code == 200
    assert client.get("/reviews/daily/2020-01-01", headers=AUTH).status_code == 404
