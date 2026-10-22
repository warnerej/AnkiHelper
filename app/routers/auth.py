from fastapi import APIRouter, Response, status

from app.dependencies import AuthServiceDep, ClientIp, CurrentUser, TokenDep
from app.models.auth import (
    Credentials,
    DeleteAccountRequest,
    ForgotPasswordRequest,
    MessageResponse,
    RefreshRequest,
    SignupRequest,
    SignupResponse,
    TokenResponse,
    UserResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=SignupResponse, status_code=status.HTTP_201_CREATED)
def signup(body: SignupRequest, auth: AuthServiceDep):
    return auth.sign_up(body.email, body.password, body.username)


@router.post("/login", response_model=TokenResponse)
def login(body: Credentials, auth: AuthServiceDep):
    return auth.login(body.email, body.password)


@router.post(
    "/forgot-password", response_model=MessageResponse, status_code=status.HTTP_202_ACCEPTED
)
def forgot_password(body: ForgotPasswordRequest, auth: AuthServiceDep, ip: ClientIp):
    auth.request_password_reset(body.email, ip)
    return MessageResponse(
        detail="If an account exists for that email, a reset link has been sent."
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh(body: RefreshRequest, auth: AuthServiceDep):
    return auth.refresh(body.refresh_token)


@router.get("/me", response_model=UserResponse)
def me(user: CurrentUser):
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(token: TokenDep, auth: AuthServiceDep):
    auth.logout(token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_me(body: DeleteAccountRequest, user: CurrentUser, auth: AuthServiceDep):
    auth.delete_account(user, body.password)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
