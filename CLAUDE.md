# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status

Early scaffold: `README.md` is empty, there are no tests or lint config yet, and `app/dependencies.py` is an empty file. `app/models/`, `app/routers/` and `app/services/` are empty directories. Update this file as real code lands.

## Stack and commands

Python 3.14 project managed with `uv` (`pyproject.toml`, `uv.lock`). Dependencies: FastAPI, uvicorn, pydantic-settings, supabase.

- Install deps: `uv sync`
- Run the dev server (no entrypoint exists yet; once `app/main.py` defines `app`): `uv run uvicorn app.main:app --reload`
- Add a dependency: `uv add <package>`

No test runner or linter is configured. If you add one (e.g. pytest, ruff), document the commands here, including how to run a single test.

## Architecture

The intended layout is a layered FastAPI app under `app/`:

- `routers/`: HTTP route handlers
- `services/`: business logic
- `models/`: data/schema models
- `dependencies.py`: shared FastAPI dependencies (e.g. the Supabase client, settings)

Configuration is expected to come from environment variables via pydantic-settings, loaded from a git-ignored `.env` at the repo root. Supabase is the backend data store.
