# AnkiHelper API guide

For an agent building the client (the Anki add-on) or extending the backend. `README.md` and `CLAUDE.md` in the repo root are authoritative if anything here disagrees. Interactive docs are at `/docs` when the server is running (`uv run uvicorn app.main:app --reload`).

## Endpoints

All bodies and responses are JSON. Every endpoint except `/health`, `/auth/signup`, `/auth/login` and `/auth/refresh` needs the header `Authorization: Bearer <access_token>`.

| Method and path | Auth | Request | Success response |
| --- | --- | --- | --- |
| `GET /health` | no | | status |
| `POST /auth/signup` | no | `{email, password, username}` (password >= 8 chars; username 3-20 chars of letters, digits, `_`, stored lowercase; 409 if taken) | 201 `{user: {id, email}, tokens \| null, confirmation_required}` |
| `POST /auth/login` | no | `{email, password}` | `{access_token, refresh_token, token_type, expires_in}` |
| `POST /auth/refresh` | no | `{refresh_token}` | new `{access_token, refresh_token, token_type, expires_in}` |
| `GET /auth/me` | yes | | `{id, email}` |
| `POST /auth/logout` | yes | | 204, ends this session |
| `DELETE /auth/me` | yes | `{password}` | 204; 403 for a wrong password. Irreversible: deletes the profile, reviews and memberships; owned groups pass to the longest-standing member, or are deleted if empty |
| `PUT /reviews/daily` | yes | `{total_reviews, study_date, retention?, study_minutes?}` | the saved row (below) |
| `GET /reviews/daily` | yes | query: `start`, `end` (ISO dates, optional), `limit` (1-365, default 90) | list of rows, newest first |
| `GET /reviews/daily/{study_date}` | yes | | one row, or 404 |
| `GET /profiles/{username}/reviews` | yes | | **Deprecated, use `GET /groups/{id}/reviews`; removed once the new add-on ships.** `{username, start, end, days}` with that user's rows for the past `days` days (query param, 1-365, default 30; newest first, same fields as a row minus `updated_at`); 404 if no such username *or* you and that user haven't both joined a common group |
| `POST /groups` | yes | `{name}` (1-50 chars) | 201 the group incl. `invite_code`; you become owner (max 20 owned groups, else 409) |
| `GET /groups` | yes | | your groups: `[{id, name, role, member_count}]` |
| `GET /groups/{id}` | yes | | `{id, name, owner, members: [{username, role, joined_at}]}`; the owner also gets `invite_code` and `allowed` (list of usernames); 404 for non-members, whether or not the group exists |
| `PATCH /groups/{id}` | yes | `{name}` | owner only; the group |
| `DELETE /groups/{id}` | yes | | owner only; 204, deletes members and allowed list |
| `POST /groups/join` | yes | `{invite_code}` | the group; 404 for a bad code and for "your username isn't on the allowed list" (identical, so codes can't be probed); joining twice is fine; 429 after 10 failed attempts in an hour (per user) |
| `POST /groups/{id}/leave` | yes | | 204; 409 for the owner (transfer or delete instead) |
| `POST /groups/{id}/allowed` | yes | `{username}` | owner only; adds the lowercased username (needn't exist yet; max 50, else 409); returns the group |
| `DELETE /groups/{id}/allowed/{username}` | yes | | owner only; 204; also removes that user's membership; 409 for the owner's own name |
| `POST /groups/{id}/invite-code` | yes | | owner only; `{invite_code}` (new; the old one stops working) |
| `POST /groups/{id}/transfer` | yes | `{username}` | owner only; the target must have joined (else 409); you become a member; returns the group |
| `GET /groups/{id}/reviews` | yes | query: `days` (1-365, default 30) | `{group_id, start, end, members: [{username, days: [...]}]}`; every joined member appears (`days` may be empty); day rows have the same fields as the friend rows; 404 for non-members |

Groups: sharing happens only between members who have **joined** the same group. Joining needs the invite code *and* the joiner's username on the group's allowed list (being allowed alone shares nothing). Members see each other's last 365 days, including days before they joined. Removing a username from the allowed list drops that user from the group immediately. Group endpoints return 403 when a member (not the owner) calls an owner-only action, and 404 when a non-member touches the group at all.

A review row is `{study_date: "YYYY-MM-DD", total_reviews: int, retention: float | null, study_minutes: float | null, updated_at: ISO datetime}`. `retention` is a percent (0-100) and `study_minutes` is the minutes studied that day (0-1440). Both are optional on PUT; if omitted, any stored value is kept (null if never sent). Send them as running values for the day, like `total_reviews`.

## Auth flow for the client

1. On startup, call `POST /auth/login` with the email and password from the add-on config.
2. Keep both tokens in memory only (not in the config file). Send `Authorization: Bearer <access_token>` on every call.
3. On a 401, call `POST /auth/refresh` once and retry the original request once. Refresh tokens rotate and are single use, so always store the new refresh token, and do not refresh before every call. If the refresh fails, log in again.
4. Use HTTPS in deployment since the password is sent on login and signup.

## Designing review calls

`PUT /reviews/daily` is an idempotent upsert keyed on the user and `study_date`.

- **The client owns the date.** The server does no timezone or day-rollover logic. The add-on must work out which study day it is (for example, treating 00:00 to 03:59 as the previous day, as Anki does with its "next day starts at" setting) and send it as an ISO date, `YYYY-MM-DD`.
- **Send the running total, not a delta.** `total_reviews` overwrites the stored value for that date, so the last PUT wins. To record progress, send today's current total again (for example after each review session or on a timer). Do not send "reviews since last sync".
- **Retries are safe.** Repeating the same PUT gives the same result, so a failed or timed-out call can be retried without double counting.
- **New day, new row.** Sending a different `study_date` inserts a new row. Past dates can be written too, which allows back-filling history.
- **Reading back:** use `GET /reviews/daily?start=...&end=...` for a range, or `GET /reviews/daily/{study_date}` for one day (404 means nothing stored for that date, which is not an error for the client to retry).
- A user only ever sees and writes their own rows. This is enforced by Postgres Row Level Security, so the client never sends a user id.

Example:

```
PUT /reviews/daily
Authorization: Bearer <access_token>
{"total_reviews": 42, "study_date": "2026-01-31", "retention": 87.5, "study_minutes": 31.5}

200 {"study_date": "2026-01-31", "total_reviews": 42, "retention": 87.5, "study_minutes": 31.5, "updated_at": "2026-01-31T21:04:11.2+00:00"}
```

## Error handling

| Status | Meaning | Client action |
| --- | --- | --- |
| 401 | missing, invalid or expired token | refresh once, retry once, else log in again |
| 403 | a group member called an owner-only endpoint | don't retry |
| 404 | no review row for that date; or a group / user that doesn't exist or isn't visible to you | treat as "no data" / "not found" |
| 409 | group conflict: owner leaving, group or allowed-list limit reached, transfer target hasn't joined | show the message, don't retry |
| 429 | too many failed `POST /groups/join` attempts | stop; wait up to an hour |
| 422 | body or query failed validation (negative total, bad or missing date, short password) | fix the request, don't retry unchanged |
| 502 | the database call failed | retry later with backoff |

## Extending the backend

Follow `CLAUDE.md`. In short:

- Layers: `app/routers/` (HTTP), `app/services/` (logic, takes a Supabase `Client`), `app/models/` (pydantic). Register new routers in `app/main.py`.
- Protect routes with `CurrentUser`. Query Supabase through `UserClient` (from `app/dependencies.py`) so RLS applies as that user. Only the anon key is used. Never add the service-role key.
- New tables go in a numbered file in `supabase/migrations/` (the user applies it in Supabase). Always enable RLS. For per-user data give the table a `user_id uuid not null default auth.uid()` and per-operation policies for `user_id = (select auth.uid())` (`0001_daily_reviews.sql` is the template). For data shared between users (`0004_groups.sql` is the template) skip write policies and do writes in `security definer` functions with `set search_path = ''` that check `auth.uid()`, raising a short error token (`raise exception 'not_found'`) that the service maps to an HTTP status. It uses a `(user_id, study_date)` primary key and an `updated_at` trigger.
- Tests override dependencies with fakes (`get_auth_service`, `get_review_service`, `get_group_service`, ...), so they need no Supabase project. See `tests/test_reviews.py`. Run `uv run pytest`.
- Update the endpoint tables in `README.md` and this file when adding endpoints.

## Note on the older handoff doc

`docs/ANKI_HANDOFF.md` was written before the reviews endpoints existed and says only auth is built. Treat it as background on conventions and open questions. This file and the README describe the current state.
