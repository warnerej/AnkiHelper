from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    supabase_url: str
    supabase_key: str  # anon/public key; user access is enforced by RLS


@lru_cache
def get_settings() -> Settings:
    return Settings()
