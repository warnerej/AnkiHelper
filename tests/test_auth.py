import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.dependencies import get_auth_service
from app.main import app
from app.models.auth import SignupResponse, TokenResponse, UserResponse

TOKENS = TokenResponse(access_token="acc", refresh_token="ref", expires_in=3600)
USER = UserResponse(id="u1", email="a@example.com")
CREDS = {"email": "a@example.com", "password": "password123"}
SIGNUP = {**CREDS, "username": "Alice_1"}


def _401():
    return HTTPException(401, "nope")


class FakeAuth:
    confirm = False
    taken = False
    signed_up_as = None

    def sign_up(self, email, password, username):
        if self.taken:
            raise HTTPException(409, "Username already taken")
        self.signed_up_as = username
        if self.confirm:
            return SignupResponse(user=USER, confirmation_required=True)
        return SignupResponse(user=USER, tokens=TOKENS)

    def login(self, email, password):
        if self.deleted or password != CREDS["password"]:
            raise _401()
        return TOKENS

    def refresh(self, refresh_token):
        if refresh_token != "ref":
            raise _401()
        return TOKENS

    def get_user(self, token):
        if self.deleted or token != "acc":
            raise _401()
        return USER

    def logout(self, token):
        self.get_user(token)

    deleted = False
    limited = False
    reset_calls = []

    def request_password_reset(self, email, ip):
        if self.limited:
            raise HTTPException(429, "Too many reset requests; try again later")
        self.reset_calls.append((email, ip))

    def delete_account(self, user, password):
        if password != CREDS["password"]:
            raise HTTPException(403, "Incorrect password")
        self.deleted = True


@pytest.fixture
def fake():
    return FakeAuth()


@pytest.fixture
def client(fake):
    app.dependency_overrides[get_auth_service] = lambda: fake
    yield TestClient(app)
    app.dependency_overrides.clear()


AUTH = {"Authorization": "Bearer acc"}


def test_login_success(client):
    r = client.post("/auth/login", json=CREDS)
    assert r.status_code == 200
    assert r.json()["access_token"] == "acc"


def test_login_bad_password(client):
    r = client.post("/auth/login", json={**CREDS, "password": "wrongpass1"})
    assert r.status_code == 401


def test_login_validates_input(client):
    assert client.post("/auth/login", json={"email": "bad", "password": "x"}).status_code == 422


def test_signup(client, fake):
    r = client.post("/auth/signup", json=SIGNUP)
    assert r.status_code == 201
    assert r.json()["tokens"]["access_token"] == "acc"
    assert r.json()["confirmation_required"] is False
    assert fake.signed_up_as == "alice_1"


def test_signup_confirmation_required(client, fake):
    fake.confirm = True
    body = client.post("/auth/signup", json=SIGNUP).json()
    assert body["tokens"] is None
    assert body["confirmation_required"] is True


def test_signup_requires_valid_username(client):
    assert client.post("/auth/signup", json=CREDS).status_code == 422
    for bad in ("ab", "x" * 21, "has space", "bad-char"):
        assert client.post("/auth/signup", json={**CREDS, "username": bad}).status_code == 422


def test_signup_username_taken(client, fake):
    fake.taken = True
    assert client.post("/auth/signup", json=SIGNUP).status_code == 409


def test_refresh(client):
    assert client.post("/auth/refresh", json={"refresh_token": "ref"}).status_code == 200
    assert client.post("/auth/refresh", json={"refresh_token": "bad"}).status_code == 401


def test_me(client):
    r = client.get("/auth/me", headers=AUTH)
    assert r.status_code == 200
    assert r.json() == {"id": "u1", "email": "a@example.com"}


def test_me_requires_token(client):
    assert client.get("/auth/me").status_code in (401, 403)
    assert client.get("/auth/me", headers={"Authorization": "Bearer bad"}).status_code == 401


def test_logout(client):
    assert client.post("/auth/logout", headers=AUTH).status_code == 204
    assert client.post("/auth/logout", headers={"Authorization": "Bearer bad"}).status_code == 401


def test_delete_account(client, fake):
    r = client.request("DELETE", "/auth/me", headers=AUTH, json={"password": CREDS["password"]})
    assert r.status_code == 204
    assert fake.deleted
    assert client.post("/auth/login", json=CREDS).status_code == 401
    assert client.get("/auth/me", headers=AUTH).status_code == 401


def test_delete_account_wrong_password(client, fake):
    r = client.request("DELETE", "/auth/me", headers=AUTH, json={"password": "wrongpass1"})
    assert r.status_code == 403
    assert not fake.deleted
    assert client.post("/auth/login", json=CREDS).status_code == 200


def test_delete_account_requires_token_and_body(client, fake):
    body = {"password": CREDS["password"]}
    assert client.request("DELETE", "/auth/me", json=body).status_code in (401, 403)
    bad = {"Authorization": "Bearer bad"}
    assert client.request("DELETE", "/auth/me", headers=bad, json=body).status_code == 401
    assert client.request("DELETE", "/auth/me", headers=AUTH).status_code == 422
    assert not fake.deleted


def test_forgot_password_same_response_for_any_email(client, fake):
    fake.reset_calls = []
    a = client.post("/auth/forgot-password", json={"email": "a@example.com"})
    b = client.post("/auth/forgot-password", json={"email": "nobody@example.com"})
    assert a.status_code == b.status_code == 202
    assert a.json() == b.json()
    assert [c[0] for c in fake.reset_calls] == ["a@example.com", "nobody@example.com"]


def test_forgot_password_rate_limited(client, fake):
    fake.limited = True
    assert client.post("/auth/forgot-password", json={"email": "a@example.com"}).status_code == 429


def test_forgot_password_bad_email(client):
    assert client.post("/auth/forgot-password", json={"email": "nope"}).status_code == 422


def test_settings_load_without_reset_url(monkeypatch):
    from app.config import Settings

    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "key")
    monkeypatch.delenv("PASSWORD_RESET_REDIRECT_URL", raising=False)
    assert Settings(_env_file=None).password_reset_redirect_url == ""


def test_request_password_reset_unavailable_without_redirect_url():
    from types import SimpleNamespace

    from app.services.auth import AuthService

    with pytest.raises(HTTPException) as e:
        AuthService(SimpleNamespace(auth=None)).request_password_reset("a@example.com", "1.2.3.4")
    assert e.value.status_code == 503
