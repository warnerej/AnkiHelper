from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from supabase import Client, create_client

from app.config import Settings, get_settings
from app.models.auth import UserResponse
from app.services.auth import AuthService

bearer_scheme = HTTPBearer()

SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_supabase(settings: SettingsDep) -> Client:
    # New client per request: the client holds session state in memory.
    return create_client(settings.supabase_url, settings.supabase_key)


def get_auth_service(client: Annotated[Client, Depends(get_supabase)]) -> AuthService:
    return AuthService(client)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
BearerDep = Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)]


def get_token(creds: BearerDep) -> str:
    return creds.credentials


TokenDep = Annotated[str, Depends(get_token)]


def get_current_user(token: TokenDep, auth: AuthServiceDep) -> UserResponse:
    return auth.get_user(token)


CurrentUser = Annotated[UserResponse, Depends(get_current_user)]


def get_user_client(
    token: TokenDep, user: CurrentUser, settings: SettingsDep
) -> Client:
    """Supabase client acting as the user, so Postgres RLS applies to its queries."""
    client = create_client(settings.supabase_url, settings.supabase_key)
    client.postgrest.auth(token)
    return client


UserClient = Annotated[Client, Depends(get_user_client)]
