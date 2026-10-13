# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status

Auth is implemented (signup, login, refresh, me, logout) under `/auth`. Daily review totals live under `/reviews` (table in `supabase/migrations/`, RLS-protected). Signup requires a username, stored in `profiles` (created by a DB trigger); `GET /profiles/{username}/reviews` returns that user's last 30 days via a security-definer SQL function, so `daily_reviews` RLS stays own-rows-only. `README.md` documents the add-on flow. No lint config yet.

## Stack and commands

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
