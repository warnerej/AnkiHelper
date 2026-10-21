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
| `POST /auth/signup` | `{email, password, username}` (password >= 8 chars; username 3-20 chars of letters, digits, `_`, stored lowercase; 409 if taken) | user, tokens (or `confirmation_required: true`) |
| `POST /auth/login` | `{email, password}` | `access_token`, `refresh_token`, `expires_in` |
| `POST /auth/refresh` | `{refresh_token}` | new tokens |
| `GET /auth/me` | Bearer token | current user |
| `POST /auth/logout` | Bearer token | 204, ends this session |

## Daily reviews API

Requires the Bearer token. One row per user per study day; the add-on sends the study date, so it decides when a day rolls over. Apply `supabase/migrations/0001_daily_reviews.sql` and `0002_daily_review_stats.sql` in Supabase first (0001 enables RLS).

| Endpoint | Body / query | Result |
| --- | --- | --- |
| `PUT /reviews/daily` | `{total_reviews, study_date, retention?, study_minutes?}` (ISO date, e.g. `2026-01-31`; `retention` is a percent 0-100; `study_minutes` is 0-1440) | inserts that day's row or overwrites its values; omitted optional fields keep their stored value |
| `GET /reviews/daily` | `start`, `end` (dates), `limit` (1-365, default 90) | your rows, newest first |
| `GET /reviews/daily/{date}` | | that day's row, or 404 |
| `GET /profiles/{username}/reviews?days=` | | `{username, start, end, days}`: **deprecated** (use the groups endpoint below): that user's daily rows for the past `days` days (1-365, default 30), newest first (no `updated_at`); 404 if the username doesn't exist or you don't share a joined group with them |

## Groups API

Requires the Bearer token and `supabase/migrations/0004_groups.sql` and `0005_friend_reviews_via_groups.sql` and `0006_join_rate_limit.sql`. A user creates a group (and owns it), the owner keeps an allowed list of usernames, and a user joins with the invite code only if their username is on that list. Only joined members share daily reviews with each other (last 365 days). All rules are enforced in Postgres (RLS and `security definer` functions), not just in the routes.

| Endpoint | Body / query | Result |
| --- | --- | --- |
| `POST /groups` | `{name}` (1-50 chars) | 201 the group incl. `invite_code`; you become owner (max 20 owned groups, else 409) |
| `GET /groups` |  | your groups: `[{id, name, role, member_count}]` |
| `GET /groups/{id}` |  | `{id, name, owner, members: [{username, role, joined_at}]}`; the owner also gets `invite_code` and `allowed` (list of usernames); 404 for non-members, whether or not the group exists |
| `PATCH /groups/{id}` | `{name}` | owner only; the group |
| `DELETE /groups/{id}` |  | owner only; 204, deletes members and allowed list |
| `POST /groups/join` | `{invite_code}` | the group; 404 for a bad code and for "your username isn't on the allowed list" (identical, so codes can't be probed); joining twice is fine; 429 after 10 failed attempts in an hour (per user) |
| `POST /groups/{id}/leave` |  | 204; 409 for the owner (transfer or delete instead) |
| `POST /groups/{id}/allowed` | `{username}` | owner only; adds the lowercased username (needn't exist yet; max 50, else 409); returns the group |
| `DELETE /groups/{id}/allowed/{username}` |  | owner only; 204; also removes that user's membership; 409 for the owner's own name |
| `POST /groups/{id}/invite-code` |  | owner only; `{invite_code}` (new; the old one stops working) |
| `POST /groups/{id}/transfer` | `{username}` | owner only; the target must have joined (else 409); you become a member; returns the group |
| `GET /groups/{id}/reviews` | query: `days` (1-365, default 30) | `{group_id, start, end, members: [{username, days: [...]}]}`; every joined member appears (`days` may be empty); day rows have the same fields as the friend rows; 404 for non-members |

Details (status codes, limits) are in `docs/API_GUIDE.md`.

## Add-on flow

1. On startup, read email/password from the add-on config and call `/auth/login`.
2. Keep the tokens in memory (not in the config) and send `Authorization: Bearer <access_token>` on every call.
3. On a 401, call `/auth/refresh`; if that fails, log in again.
4. Use HTTPS in deployment, since the password is sent on login and signup.
