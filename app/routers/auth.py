from fastapi import APIRouter, Depends, Response, status

from app.dependencies import AuthServiceDep, ClientIp, CurrentUser, TokenDep
from app.ratelimit import rate_limit
from app.models.auth import (
    LoginRequest,
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

# Per client IP. Generous enough for a shared network, tight enough to stop scripted abuse.
limit_signup = rate_limit(10, 3600, "signup")
limit_login = rate_limit(20, 300, "login")
limit_refresh = rate_limit(60, 300, "refresh")
limit_delete = rate_limit(5, 3600, "delete")


@router.post(
    "/signup",
    response_model=SignupResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(limit_signup)],
)
def signup(body: SignupRequest, auth: AuthServiceDep):
    return auth.sign_up(body.email, body.password, body.username)


@router.post("/login", response_model=TokenResponse, dependencies=[Depends(limit_login)])
def login(body: LoginRequest, auth: AuthServiceDep):
    return auth.login(body.email, body.password)


@router.post(
    "/forgot-password", response_model=MessageResponse, status_code=status.HTTP_202_ACCEPTED
)
def forgot_password(body: ForgotPasswordRequest, auth: AuthServiceDep, ip: ClientIp):
    auth.request_password_reset(body.email, ip)
    return MessageResponse(
        detail="If an account exists for that email, a reset link has been sent."
    )


@router.post("/refresh", response_model=TokenResponse, dependencies=[Depends(limit_refresh)])
def refresh(body: RefreshRequest, auth: AuthServiceDep):
    return auth.refresh(body.refresh_token)


@router.get("/me", response_model=UserResponse)
def me(user: CurrentUser):
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(token: TokenDep, auth: AuthServiceDep):
    auth.logout(token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(limit_delete)])
def delete_me(body: DeleteAccountRequest, user: CurrentUser, auth: AuthServiceDep):
    auth.delete_account(user, body.password)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
