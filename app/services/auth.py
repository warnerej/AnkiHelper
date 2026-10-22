import logging

from fastapi import HTTPException, status
from postgrest.exceptions import APIError
from supabase import Client
from supabase_auth.errors import AuthApiError, AuthError

from app.models.auth import SignupResponse, TokenResponse, UserResponse

logger = logging.getLogger(__name__)


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

    def __init__(self, client: Client, reset_redirect_url: str = ""):
        self._client = client
        self._reset_redirect_url = reset_redirect_url
        self._auth = client.auth

    def _username_taken(self) -> HTTPException:
        return HTTPException(status.HTTP_409_CONFLICT, "Username already taken")

    def sign_up(self, email: str, password: str, username: str) -> SignupResponse:
        try:
            available = self._client.rpc("username_available", {"p_username": username}).execute()
        except APIError as e:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, e.message or "database error") from e
        if not available.data:
            raise self._username_taken()
        try:
            res = self._auth.sign_up(
                {
                    "email": email,
                    "password": password,
                    # The on_auth_user_created trigger turns this into a profile row.
                    "options": {"data": {"username": username}},
                }
            )
        except AuthApiError as e:
            if e.code == "user_already_exists":
                raise HTTPException(status.HTTP_409_CONFLICT, e.message) from e
            # Lost a race for the username: the trigger's unique index rejected the insert.
            if e.code == "unexpected_failure" and "profiles" in (e.message or ""):
                raise self._username_taken() from e
            raise HTTPException(status.HTTP_400_BAD_REQUEST, e.message) from e
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

    def request_password_reset(self, email: str, ip: str) -> None:
        """Send a reset email. Every outcome except the rate limit looks the same to the caller,
        so this can't be used to find out which emails have accounts."""
        if not self._reset_redirect_url:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "Password reset is not available"
            )
        try:
            allowed = self._client.rpc(
                "check_password_reset_limit", {"p_ip": ip, "p_email": email}
            ).execute()
        except APIError as e:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, e.message or "database error") from e
        if not allowed.data:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS, "Too many reset requests; try again later"
            )
        try:
            self._auth.reset_password_for_email(
                email, {"redirect_to": self._reset_redirect_url}
            )
        except AuthError:
            # Unknown email, Supabase's own throttling or a mail failure: don't tell the caller.
            logger.warning("password reset email not sent", exc_info=True)

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

    def delete_account(self, user: UserResponse, password: str) -> None:
        """Re-check the password with a fresh sign-in, then delete the account in Postgres
        (delete_my_account hands off or removes owned groups, and the rest cascades)."""
        try:
            res = self._auth.sign_in_with_password({"email": user.email, "password": password})
        except AuthApiError as e:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Incorrect password") from e
        # Act as the user whose password was just verified.
        self._client.postgrest.auth(res.session.access_token)
        try:
            self._client.rpc("delete_my_account").execute()
        except APIError as e:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, e.message or "database error") from e
