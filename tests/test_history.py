from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from postgrest.exceptions import APIError

from app.dependencies import get_auth_service, get_review_service
from app.main import app
from app.models.auth import UserResponse
from app.models.reviews import HistoryResult, HistoryStatus, HistoryUpload
from app.services.reviews import ReviewService

AUTH = {"Authorization": "Bearer acc"}
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
START = date(2026, 1, 1)


class FakeAuth:
    def get_user(self, token):
        if token != "acc":
            raise HTTPException(401, "nope")
        return UserResponse(id="u1")


class FakeReviews:
    def __init__(self):
        self.synced_at = None
        self.calls = []

    def replace_history(self, body, user_id):
        self.calls.append((body, user_id))
        self.synced_at = NOW
        return HistoryResult(
            start=body.start,
            end=body.end,
            days_written=len(body.days),
            history_synced_at=NOW,
        )

    def history_status(self, user_id):
        return HistoryStatus(history_synced_at=self.synced_at)


@pytest.fixture
def fake():
    return FakeReviews()


@pytest.fixture
def client(fake):
    app.dependency_overrides[get_auth_service] = lambda: FakeAuth()
    app.dependency_overrides[get_review_service] = lambda: fake
    yield TestClient(app)
    app.dependency_overrides.clear()


def body(start=START, end=START + timedelta(days=6), days=None):
    if days is None:
        days = [{"study_date": start.isoformat(), "total_reviews": 10}]
    return {"start": start.isoformat(), "end": end.isoformat(), "days": days}


def put(client, payload):
    return client.put("/reviews/history", json=payload, headers=AUTH)


# --- validation ---


def test_end_before_start_is_422(client):
    assert put(client, body(end=START - timedelta(days=1), days=[])).status_code == 422


def test_366_day_span_is_422(client):
    assert put(client, body(end=START + timedelta(days=365), days=[])).status_code == 422


def test_365_day_span_is_ok(client):
    assert put(client, body(end=START + timedelta(days=364), days=[])).status_code == 200


def test_date_outside_range_is_422(client):
    days = [{"study_date": (START - timedelta(days=1)).isoformat(), "total_reviews": 1}]
    assert put(client, body(days=days)).status_code == 422


def test_duplicate_dates_are_422(client):
    days = [{"study_date": START.isoformat(), "total_reviews": 1}] * 2
    assert put(client, body(days=days)).status_code == 422


def test_more_than_365_items_is_422(client):
    days = [{"study_date": START.isoformat(), "total_reviews": 1}] * 366
    assert put(client, body(end=START + timedelta(days=364), days=days)).status_code == 422


def test_negative_total_is_422(client):
    days = [{"study_date": START.isoformat(), "total_reviews": -1}]
    assert put(client, body(days=days)).status_code == 422


def test_retention_above_100_is_422(client):
    days = [{"study_date": START.isoformat(), "total_reviews": 1, "retention": 100.5}]
    assert put(client, body(days=days)).status_code == 422


# --- success and status ---


def test_upload_returns_days_written_and_timestamp(client, fake):
    r = put(client, body())
    assert r.status_code == 200
    assert r.json()["days_written"] == 1
    assert r.json()["history_synced_at"].startswith("2026-01-01")
    assert fake.calls[0][1] == "u1"


def test_empty_days_clears_the_range(client):
    r = put(client, body(days=[]))
    assert r.status_code == 200
    assert r.json()["days_written"] == 0


def test_status_null_before_upload_and_timestamp_after(client):
    assert client.get("/reviews/history/status", headers=AUTH).json() == {
        "history_synced_at": None
    }
    put(client, body())
    r = client.get("/reviews/history/status", headers=AUTH)
    assert r.json()["history_synced_at"].startswith("2026-01-01")


# --- auth ---


def test_endpoints_require_auth(client):
    assert client.put("/reviews/history", json=body()).status_code == 401
    assert client.get("/reviews/history/status").status_code == 401


# --- service: error mapping and read-back ---


class Result:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows
        self.filters = {}

    def select(self, *_):
        return self

    def eq(self, col, val):
        self.filters[col] = val
        return self

    def execute(self):
        return Result([r for r in self.rows if all(r[k] == v for k, v in self.filters.items())])


class FakeClient:
    def __init__(self, error=None, written=3, profiles=None):
        self.error = error
        self.written = written
        self.profiles = profiles if profiles is not None else [
            {"user_id": "u1", "history_synced_at": NOW.isoformat()}
        ]
        self.rpc_calls = []

    def table(self, name):
        return FakeQuery(self.profiles if name == "profiles" else [])

    def rpc(self, fn, params):
        self.rpc_calls.append((fn, params))
        client = self

        class Call:
            def execute(self):
                if client.error:
                    raise APIError({"message": client.error, "code": "P0001"})
                return Result(client.written)

        return Call()


def upload():
    return HistoryUpload(**body())


@pytest.mark.parametrize(
    "token,code", [("rate_limited", 429), ("invalid_range", 422), ("boom", 502)]
)
def test_service_maps_error_tokens(token, code):
    svc = ReviewService(FakeClient(error=token))
    with pytest.raises(HTTPException) as exc:
        svc.replace_history(upload(), "u1")
    assert exc.value.status_code == code


def test_service_calls_rpc_and_reads_back_timestamp():
    client = FakeClient(written=1)
    res = ReviewService(client).replace_history(upload(), "u1")
    fn, params = client.rpc_calls[0]
    assert fn == "replace_daily_reviews"
    assert params["p_start"] == "2026-01-01" and params["p_end"] == "2026-01-07"
    assert params["p_days"] == [
        {"study_date": "2026-01-01", "total_reviews": 10, "retention": None, "study_minutes": None}
    ]
    assert res.days_written == 1
    assert res.history_synced_at == NOW


def test_service_status_filters_to_caller_and_handles_missing_profile():
    svc = ReviewService(FakeClient(profiles=[{"user_id": "other", "history_synced_at": None}]))
    assert svc.history_status("u1").history_synced_at is None
    assert ReviewService(FakeClient()).history_status("u1").history_synced_at == NOW
