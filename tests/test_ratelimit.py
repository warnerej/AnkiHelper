import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_auth_service
from app.main import app
from app.ratelimit import RateLimiter, reset_all


@pytest.fixture(autouse=True)
def _fresh_limits():
    reset_all()
    yield
    reset_all()


def test_allows_up_to_max_then_blocks():
    now = [0.0]
    limiter = RateLimiter(2, 10, clock=lambda: now[0])
    assert limiter.allow("a") and limiter.allow("a")
    assert not limiter.allow("a")
    assert limiter.allow("b")  # keys are independent


def test_window_expires():
    now = [0.0]
    limiter = RateLimiter(1, 10, clock=lambda: now[0])
    assert limiter.allow("a")
    now[0] = 10.0
    assert limiter.allow("a")


def test_login_is_limited_with_429_and_retry_after():
    from fastapi import HTTPException

    class Denying:
        def login(self, email, password):
            raise HTTPException(401, "nope")

    app.dependency_overrides[get_auth_service] = lambda: Denying()
    try:
        c = TestClient(app)
        body = {"email": "a@example.com", "password": "x"}
        codes = [c.post("/auth/login", json=body).status_code for _ in range(25)]
        assert codes[0] == 401 and codes[-1] == 429
        assert c.post("/auth/login", json=body).headers["retry-after"] == "300"
    finally:
        app.dependency_overrides.clear()


def test_short_password_may_still_log_in_but_not_sign_up():
    class Auth:
        def login(self, email, password):
            from app.models.auth import TokenResponse

            return TokenResponse(access_token="a", refresh_token="r", expires_in=1)

    app.dependency_overrides[get_auth_service] = lambda: Auth()
    try:
        c = TestClient(app)
        assert c.post("/auth/login", json={"email": "a@example.com", "password": "short"}).status_code == 200
        r = c.post("/auth/signup", json={"email": "a@example.com", "password": "short", "username": "abc"})
        assert r.status_code == 422
    finally:
        app.dependency_overrides.clear()
