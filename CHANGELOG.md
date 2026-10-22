# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

Targeting 0.1.0, the first public release.

### Added
- Auth under `/auth`: signup (with unique username), login, refresh, logout, current user.
- Daily review stats under `/reviews` (`PUT/GET /reviews/daily`), with optional `retention` and `study_minutes`.
- Groups under `/groups`: owner, allowed list, invite codes, join, leave, transfer, and `GET /groups/{id}/reviews`; a user joins only with the code and an allowed username.
- Account deletion `DELETE /auth/me`; owned groups pass to the longest-standing member or are deleted if empty.
- Review history backfill: `PUT /reviews/history` and `GET /reviews/history/status`.
- Password reset: `POST /auth/forgot-password` (needs `PASSWORD_RESET_REDIRECT_URL`).
- Per-IP rate limits on signup, login, refresh and account deletion; Postgres limits on joins, history uploads and password reset.
- MIT license, CI (pytest) and `SECURITY.md`.

### Changed
- Group reviews are returned one element per member (`0010`), fixing truncation of large groups; review windows use UTC with one day of slack.
- Unexpected database errors return a generic 502 `Database error`; unhandled errors return a generic 500.
- Refresh failures are logged with the Supabase cause; provider failures return 502 instead of 401.
- `LoginRequest` no longer enforces a minimum password length; `SignupRequest` requires 8 to 256 characters.

### Deprecated
- `GET /profiles/{username}/reviews`, now limited to users who share a group; use `GET /groups/{id}/reviews`.
