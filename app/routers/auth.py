from fastapi import APIRouter, Response, status

from app.dependencies import AuthServiceDep, CurrentUser, TokenDep
from app.models.auth import (
    Credentials,
    RefreshRequest,
    SignupResponse,
    TokenResponse,
    UserResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=SignupResponse, status_code=status.HTTP_201_CREATED)
def signup(body: Credentials, auth: AuthServiceDep):
    return auth.sign_up(body.email, body.password)


@router.post("/login", response_model=TokenResponse)
def login(body: Credentials, auth: AuthServiceDep):
    return auth.login(body.email, body.password)


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
