# AnkiHelper backend

FastAPI backend (Supabase for auth and data) for the AnkiHelper Anki add-on. It stores each user's daily review stats and lets members of the same group see each other's heatmaps. Python 3.14, managed with `uv`. Interactive API docs are served at `/docs` when the server runs. The add-on lives in a separate repo (`AnkiHelperExtension`).

## Setup

```
uv sync
cp .env.example .env   # fill in SUPABASE_URL and SUPABASE_KEY (anon key)
uv run uvicorn app.main:app --reload
uv run pytest
```

Then apply the migrations (below) to your Supabase project.

### Configuration

Settings come from environment variables or a git-ignored `.env` (`app/config.py`, template in `.env.example`):

| Variable | Required | Meaning |
| --- | --- | --- |
| `SUPABASE_URL` | yes | Project URL |
| `SUPABASE_KEY` | yes | The **anon** key. Never use the service-role key; access is enforced by RLS |
| `PASSWORD_RESET_REDIRECT_URL` | no | Site page that sets a new password. Must also be in Supabase Auth > URL Configuration > Redirect URLs. While empty, `POST /auth/forgot-password` returns 503 and everything else works |

### Migrations

Apply `supabase/migrations/` by hand in the Supabase SQL editor, in numeric order. Never edit an applied one; add the next number.

| File | Adds |
| --- | --- |
| `0001_daily_reviews.sql` | `daily_reviews` table (one row per user per study day) with RLS |
| `0002_daily_review_stats.sql` | optional `retention` and `study_minutes` columns |
| `0003_profiles.sql` | `profiles` (unique username, created by a trigger on signup), `username_available` |
| `0004_groups.sql` | groups, members, allowed list, invite codes and the `security definer` functions that enforce the rules |
| `0005_friend_reviews_via_groups.sql` | limits the deprecated friend lookup to users who share a group |
| `0006_join_rate_limit.sql` | 10 failed joins per user per hour |
| `0007_delete_account.sql` | `delete_my_account()`: hands over or deletes owned groups, then deletes the user |
| `0008_review_history.sql` | `replace_daily_reviews`, `history_synced_at`, 5 uploads per hour |
| `0009_password_reset_rate_limit.sql` | `check_password_reset_limit` (10 per IP, 3 per email per hour) |
| `0010_group_reviews_by_member.sql` | `group_reviews_by_member`, one element per member (avoids PostgREST's 1000-row cap) |

### Deployment

Deployed on Render (free tier) at https://ankihelper.onrender.com. Start command:

```
uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips='*'
```

- Without `--proxy-headers --forwarded-allow-ips`, every request appears to come from the proxy's IP, so the per-IP limits below become global and one user can lock everyone out.
- Run a single instance: the auth rate limiter is in memory.
- Free-tier instances sleep when idle; the first request after a pause can take a minute (the add-on's default timeout is 60 s).
- Use HTTPS only; passwords are sent on login and signup.

## Auth API

| Endpoint | Body | Result |
| --- | --- | --- |
| `POST /auth/signup` | `{email, password, username}` (password >= 8 chars; username 3-20 chars of letters, digits, `_`, stored lowercase; 409 if taken) | user, tokens (or `confirmation_required: true`) |
| `POST /auth/login` | `{email, password}` | `access_token`, `refresh_token`, `expires_in` |
| `POST /auth/refresh` | `{refresh_token}` | new tokens |
| `POST /auth/forgot-password` | `{email}` | 202 with the same message whether or not the account exists; 429 after 3 requests per email or 10 per IP in an hour. Emails a link to `PASSWORD_RESET_REDIRECT_URL`; the site page sets the new password through Supabase. 503 until `PASSWORD_RESET_REDIRECT_URL` is set. Apply `0009` first |
| `GET /auth/me` | Bearer token | current user |
| `POST /auth/logout` | Bearer token | 204, ends this session |
| `DELETE /auth/me` | Bearer token | body `{password}`; 204, 403 for a wrong password. Irreversible; owned groups pass to the longest-standing member, or are deleted if empty |

## Rate limits and errors

Per-IP limits, in memory (`app/ratelimit.py`, wired in `app/routers/auth.py`; see Deployment for the proxy flags): signup 10/hour, login 20 per 5 minutes, refresh 60 per 5 minutes, delete account 5/hour. Limits kept in Postgres: forgot-password 10/hour per IP and 3/hour per email (`0009`), failed group joins 10/hour per user (`0006`), history uploads 5/hour per user (`0008`). Every limit answers 429; the in-memory ones also send `Retry-After`.

`LoginRequest` has no minimum password length (existing accounts); `SignupRequest` requires 8 to 256 characters.

Error behavior:
- 502 `{"detail": "Database error"}` for any unexpected Postgres/PostgREST error; the real cause is only in the server log (`app/services/errors.py`).
- 502 `Upstream service unavailable` when Supabase times out or is unreachable (`app/main.py`).
- 502, never 401, for Supabase auth failures other than a definite rejection (429, 5xx, network).
- 500 `Internal server error` from the catch-all handler (`app/main.py`); the traceback is logged.
- Non-members always get 404 for groups, whether or not the group exists.

## Daily reviews API

Requires the Bearer token. One row per user per study day; the add-on sends the study date, so it decides when a day rolls over. Apply `supabase/migrations/0001_daily_reviews.sql` and `0002_daily_review_stats.sql` in Supabase first (0001 enables RLS).

| Endpoint | Body / query | Result |
| --- | --- | --- |
| `PUT /reviews/daily` | `{total_reviews, study_date, retention?, study_minutes?}` (ISO date, e.g. `2026-01-31`; `retention` is a percent 0-100; `study_minutes` is 0-1440) | inserts that day's row or overwrites its values; omitted optional fields keep their stored value |
| `GET /reviews/daily` | `start`, `end` (dates), `limit` (1-365, default 90) | your rows, newest first |
| `GET /reviews/daily/{date}` | | that day's row, or 404 |
| `PUT /reviews/history` | `{start, end, days: [{study_date, total_reviews, retention?, study_minutes?}]}` (max 365 days; `end` up to 1 day ahead of the server date; 5 uploads/hour) | replaces your rows in that range with `days` (missing dates are removed); upload after an Anki sync so mobile reviews are included. Apply `0008_review_history.sql` first |
| `GET /reviews/history/status` | | `{history_synced_at}`, null until the first history upload (tells the add-on whether to run the automatic backfill) |
| `GET /profiles/{username}/reviews?days=` | | `{username, start, end, days}`: **deprecated** (use the groups endpoint below): that user's daily rows for the past `days` days (1-365, default 30), newest first (no `updated_at`); 404 if the username doesn't exist or you don't share a joined group with them |

## Groups API

Requires the Bearer token. Apply `supabase/migrations/0004_groups.sql`, `0005_friend_reviews_via_groups.sql` and `0006_join_rate_limit.sql` in Supabase, in that order. A user creates a group (and owns it), the owner keeps an allowed list of usernames, and a user joins with the invite code only if their username is on that list. Only joined members share daily reviews with each other (last 365 days). All rules are enforced in Postgres (RLS and `security definer` functions), not just in the routes.

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

1. The user logs in or signs up in the add-on's dialog (`/auth/login`, `/auth/signup`); the password is never stored.
2. The add-on keeps the access token in memory and only the refresh token on disk, and sends `Authorization: Bearer <access_token>` on every call.
3. On a 401 it calls `/auth/refresh`; if that is rejected it clears the session and asks the user to log in again.
4. Sharing is opt-in on the add-on side: nothing is uploaded until the user consents.

## Security

Known limitations and how they are handled are in `SECURITY.md`.
