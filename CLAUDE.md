# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status

Auth is implemented (signup, login, refresh, me, logout, delete account) under `/auth`. Daily review totals live under `/reviews` (table in `supabase/migrations/`, RLS-protected). Signup requires a username, stored in `profiles` (created by a DB trigger); `GET /profiles/{username}/reviews` returns that user's last `days` days (default 30, max 365) via a security-definer SQL function, so `daily_reviews` RLS stays own-rows-only. `README.md` documents the add-on flow. No lint config yet.

## Groups

Groups live under `/groups` (`supabase/migrations/0004_groups.sql`): an owner, an allowed list of usernames and an invite code; a user joins only with the code *and* an allowed username, and only joined members see each other's reviews (last 365 days, including before joining). Every rule is a `security definer` function checking `auth.uid()`, which raises a token (`not_found`, `forbidden`, ...) that `app/services/groups.py` maps to an HTTP status; non-members always get 404. Limits (20 owned groups, 50 allowed usernames) are constants in `app/config.py` and mirrored in the SQL, so change both.

`POST /groups/join` is rate limited in Postgres (`0006`): 10 failed attempts per user per hour, then 429 (also mirrored in `app/config.py`); `join_group` returns null on failure instead of raising so the failed attempt row survives the transaction.

`DELETE /auth/me` (password re-checked by a fresh sign-in) calls `delete_my_account()` (`0007`): each owned group goes to its longest-standing member (earliest `joined_at`) or is deleted if it has no other members, the username leaves all allowed lists, then the `auth.users` row is deleted and the rest cascades. `groups.owner_id` has no cascade, hence the hand-off first. Account data is deleted for real; nothing is retained server-side.

`groups.plan` exists but isn't enforced. `GET /profiles/{username}/reviews` is deprecated and now returns 404 unless both users joined a common group (`0005`).

## Stack and commands

Migrations in `supabase/migrations/` (`0001`-`0007`) are applied by hand in Supabase, in order. Don't edit an applied one; add the next number.

Python 3.14 project managed with `uv` (`pyproject.toml`, `uv.lock`). Dependencies: FastAPI, uvicorn, pydantic-settings, supabase.

- Install deps: `uv sync`
- Run the dev server: `uv run uvicorn app.main:app --reload` (needs `.env`, see `.env.example`)
- Run tests: `uv run pytest`; single test: `uv run pytest tests/test_auth.py::test_login_success`
- Add a dependency: `uv add <package>`

pytest is configured (`tests/`). No linter is configured yet.

## Architecture

The intended layout is a layered FastAPI app under `app/`:

- `routers/`: HTTP route handlers
- `services/`: business logic
- `models/`: data/schema models
- `dependencies.py`: shared FastAPI dependencies (e.g. the Supabase client, settings)

Configuration is expected to come from environment variables via pydantic-settings, loaded from a git-ignored `.env` at the repo root. Supabase is the backend data store.

## Auth

The Anki add-on logs in with the email/password from its config via `POST /auth/login` and sends `Authorization: Bearer <access_token>` on every other call. `AuthService` (`app/services/auth.py`) wraps Supabase Auth; a new Supabase client is created per request because the client keeps session state in memory. Protect routes with `CurrentUser`; use `UserClient` (from `app/dependencies.py`) for Supabase queries so RLS applies as that user. Only the anon key is used; never add the service-role key. Tests override `get_auth_service` with a fake, so they need no Supabase project.
