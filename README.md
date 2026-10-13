# AnkiHelper backend

FastAPI backend (Supabase for auth and data) for an Anki add-on.

## Setup

```
uv sync
cp .env.example .env   # fill in SUPABASE_URL and SUPABASE_KEY (anon key)
uv run uvicorn app.main:app --reload
uv run pytest
```

## Auth API

| Endpoint | Body | Result |
| --- | --- | --- |
| `POST /auth/signup` | `{email, password}` (password >= 8 chars) | user, tokens (or `confirmation_required: true`) |
| `POST /auth/login` | `{email, password}` | `access_token`, `refresh_token`, `expires_in` |
| `POST /auth/refresh` | `{refresh_token}` | new tokens |
| `GET /auth/me` | Bearer token | current user |
| `POST /auth/logout` | Bearer token | 204, ends this session |

## Daily reviews API

Requires the Bearer token. One row per user per study day; the add-on sends the study date, so it decides when a day rolls over. Apply `supabase/migrations/0001_daily_reviews.sql` in Supabase first (it enables RLS).

| Endpoint | Body / query | Result |
| --- | --- | --- |
| `PUT /reviews/daily` | `{total_reviews, study_date}` (ISO date, e.g. `2026-01-31`) | inserts that day's row or overwrites its total |
| `GET /reviews/daily` | `start`, `end` (dates), `limit` (1-365, default 90) | your rows, newest first |
| `GET /reviews/daily/{date}` | | that day's row, or 404 |

## Add-on flow

1. On startup, read email/password from the add-on config and call `/auth/login`.
2. Keep the tokens in memory (not in the config) and send `Authorization: Bearer <access_token>` on every call.
3. On a 401, call `/auth/refresh`; if that fails, log in again.
4. Use HTTPS in deployment, since the password is sent on login and signup.
