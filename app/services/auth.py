from fastapi import HTTPException, status
from supabase import Client
from supabase_auth.errors import AuthApiError, AuthError

from app.models.auth import SignupResponse, TokenResponse, UserResponse


def _tokens(session) -> TokenResponse:
    return TokenResponse(
        access_token=session.access_token,
        refresh_token=session.refresh_token,
        expires_in=session.expires_in,
    )


def _user(user) -> UserResponse:
    return UserResponse(id=str(user.id), email=user.email)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


class AuthService:
    """Thin wrapper over Supabase Auth. Expects a client used for one request only,
    since the client keeps the signed-in session in memory."""

    def __init__(self, client: Client):
        self._auth = client.auth

    def sign_up(self, email: str, password: str) -> SignupResponse:
        try:
            res = self._auth.sign_up({"email": email, "password": password})
        except AuthApiError as e:
            code = 409 if e.code == "user_already_exists" else 400
            raise HTTPException(code, e.message) from e
        if res.user is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Sign up failed")
        return SignupResponse(
            user=_user(res.user),
            tokens=_tokens(res.session) if res.session else None,
            confirmation_required=res.session is None,
        )

    def login(self, email: str, password: str) -> TokenResponse:
        try:
            res = self._auth.sign_in_with_password({"email": email, "password": password})
        except AuthApiError as e:
            raise _unauthorized("Invalid email or password") from e
        return _tokens(res.session)

    def refresh(self, refresh_token: str) -> TokenResponse:
        try:
            res = self._auth.refresh_session(refresh_token)
        except AuthError as e:
            raise _unauthorized("Invalid or expired refresh token") from e
        if res.session is None:
            raise _unauthorized("Invalid or expired refresh token")
        return _tokens(res.session)

    def get_user(self, token: str) -> UserResponse:
        try:
            res = self._auth.get_user(token)
        except AuthError as e:
            raise _unauthorized("Invalid or expired token") from e
        if res is None or res.user is None:
            raise _unauthorized("Invalid or expired token")
        return _user(res.user)

    def logout(self, token: str) -> None:
        """End only this session (other devices stay signed in)."""
        try:
            self._auth.admin.sign_out(token, "local")
        except AuthError as e:
            raise _unauthorized("Invalid or expired token") from e
