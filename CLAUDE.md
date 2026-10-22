# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status

FastAPI backend (Supabase-backed) for the AnkiHelper Anki add-on, heading for the first public release (0.1.0). Its client is the sibling repo `AnkiHelperExtension`: this repo owns the API contract and the limits, the add-on mirrors a few of them (group name length, 365-day windows), so check it when you change one.

- `docs/API_GUIDE.md`: endpoint reference for client authors (auth, reviews, history, groups, profiles).
- `README.md`: setup, migrations, deployment, rate limits, errors. `SECURITY.md`: known risks. `CHANGELOG.md`: what changed. `LICENSE`: MIT.
- `ROADMAP.md`: open work, read first when continuing. `docs/archive/`: finished plans and handoffs.

## Stack and commands

Python 3.14 project managed with `uv` (`pyproject.toml`, `uv.lock`). Dependencies: FastAPI, uvicorn, pydantic-settings, supabase.

- Install deps: `uv sync`
- Run the dev server: `uv run uvicorn app.main:app --reload` (needs `.env`, see `.env.example`)
- Run tests: `uv run pytest`; single test: `uv run pytest tests/test_auth.py::test_login_success`
- Add a dependency: `uv add <package>`

pytest runs in CI (`.github/workflows/ci.yml`). No linter is configured. All tests use fake services; none exercises the SQL or RLS, so changes to migrations need a manual check in Supabase.

Migrations in `supabase/migrations/` (`0001`-`0010`) are applied by hand in Supabase, in order. Don't edit an applied one; add the next number.

## Architecture

Layered FastAPI app under `app/`:

- `routers/`: HTTP route handlers
- `services/`: business logic
- `models/`: data/schema models
- `dependencies.py`: shared FastAPI dependencies (Supabase client, settings, `get_client_ip`)
- `ratelimit.py`: in-memory per-IP sliding-window limiter for the auth endpoints (`rate_limit(...)` dependency; tests call `reset_all()` from `tests/conftest.py`)
- `services/errors.py`: `_upstream_db_error`, the generic 502 `Database error` used by every service
- `main.py`: app wiring, `/health`, and the handlers for `httpx.RequestError` (502) and unexpected errors (500)

Configuration comes from environment variables via pydantic-settings, loaded from a git-ignored `.env` at the repo root.

## Auth

The add-on logs in with `POST /auth/login` and sends `Authorization: Bearer <access_token>` on every other call. `AuthService` (`app/services/auth.py`) wraps Supabase Auth; a new Supabase client is created per request because the client keeps session state in memory. Protect routes with `CurrentUser`; use `UserClient` (from `app/dependencies.py`) for Supabase queries so RLS applies as that user. Only the anon key is used; never add the service-role key. `models/auth.py` has separate `SignupRequest` (password 8-256 chars) and `LoginRequest` (no minimum, max 256, so old accounts can still log in). Tests override `get_auth_service` with a fake, so they need no Supabase project.

Supabase auth failures other than a definite rejection (429, 5xx, network) return 502, never 401, and network errors anywhere return 502.

Run uvicorn with `--proxy-headers --forwarded-allow-ips='*'` behind a proxy and keep to one instance, or the in-memory rate limits break (see `README.md` Deployment). The client IP is `request.client.host`.

## Database and SQL rules

- Signup requires a username, stored in `profiles` (created by a DB trigger). `daily_reviews` RLS is own-rows-only; cross-user reads go through security-definer SQL functions.
- Groups (`0004`): an owner, an allowed list of usernames and an invite code. A user joins only with the code *and* an allowed username; only joined members see each other's reviews (last 365 days, including before joining). Every rule is a `security definer` function checking `auth.uid()` that raises a token (`not_found`, `forbidden`, ...), which `app/services/groups.py` maps to an HTTP status. Non-members always get 404.
- Limits are constants in `app/config.py` and mirrored in the SQL, so change both: 20 owned groups, 50 allowed usernames, join failures, password-reset limits, history uploads.
- Join limiter (`0006`): 10 failed attempts per user per hour, then 429. `join_group` returns null on failure instead of raising so the failed-attempt row survives the transaction.
- `PUT /reviews/history` (`0008`) replaces the caller's `daily_reviews` rows in a date range (max 365 days) in one transaction via `replace_daily_reviews`, 5 uploads per hour (`history_syncs`). `profiles.history_synced_at` (read by `GET /reviews/history/status`) tells the add-on whether to backfill.
- `DELETE /auth/me` (password re-checked by a fresh sign-in) calls `delete_my_account()` (`0007`): each owned group goes to its longest-standing member (earliest `joined_at`) or is deleted if it has no other members, the username leaves all allowed lists, then the `auth.users` row is deleted and the rest cascades. `groups.owner_id` has no cascade, hence the hand-off first. Nothing is retained server-side.
- `POST /auth/forgot-password` (`0009`) emails a Supabase reset link to `PASSWORD_RESET_REDIRECT_URL` (optional; 503 while unset, also needs to be in the Supabase redirect allowlist) and always returns the same 202. Limited to 3/email and 10/IP per hour by `check_password_reset_limit` (anon-callable, stores an email hash only). The site sets the new password via supabase-js; there is no backend endpoint.
- `GET /groups/{id}/reviews` calls `group_reviews_by_member` (`0010`), one jsonb element per member: the older row-per-day version hit PostgREST's 1000-row cap on big groups. "Today" for review windows is UTC's, and queries run one day past it for clients ahead of UTC.
- `GET /profiles/{username}/reviews` is deprecated and returns 404 unless both users joined a common group (`0005`). `groups.plan` exists but isn't enforced (see `ROADMAP.md`).
