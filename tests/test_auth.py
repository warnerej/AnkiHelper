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
        if password != CREDS["password"]:
            raise _401()
        return TOKENS

    def refresh(self, refresh_token):
        if refresh_token != "ref":
            raise _401()
        return TOKENS

    def get_user(self, token):
        if token != "acc":
            raise _401()
        return USER

    def logout(self, token):
        self.get_user(token)


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
