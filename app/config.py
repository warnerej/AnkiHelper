from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


# Mirrored in supabase/migrations/0004_groups.sql, which enforces them; change both together.
MAX_OWNED_GROUPS = 20
MAX_ALLOWED_USERNAMES = 50
# Failed joins allowed per user per window (0006_join_rate_limit.sql); mirrored there too.
JOIN_MAX_FAILURES = 10
JOIN_WINDOW_MINUTES = 60
# History upload limits (0008_review_history.sql); mirrored there, change both together.
# The end date may be this many days ahead of the server's date, for clients ahead of UTC.
HISTORY_MAX_DAYS = 365
HISTORY_SYNC_MAX_PER_HOUR = 5
HISTORY_FUTURE_SLACK_DAYS = 1
# Password reset requests allowed per window (0009_password_reset_rate_limit.sql); mirrored there.
RESET_MAX_PER_IP_PER_HOUR = 10
RESET_MAX_PER_EMAIL_PER_HOUR = 3


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    supabase_url: str
    supabase_key: str  # anon/public key; user access is enforced by RLS
    # Page on the site that reads the recovery token and sets a new password. Must also be in
    # the Supabase project's Redirect URLs allowlist.
    password_reset_redirect_url: str


@lru_cache
def get_settings() -> Settings:
    return Settings()
