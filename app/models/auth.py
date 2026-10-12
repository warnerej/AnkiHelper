from pydantic import BaseModel, EmailStr, Field


class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class UserResponse(BaseModel):
    id: str
    email: str | None = None


class SignupResponse(BaseModel):
    user: UserResponse
    # None when the Supabase project requires email confirmation before login.
    tokens: TokenResponse | None = None
    confirmation_required: bool = False
