# Security

## Reporting a vulnerability

Please report security issues privately to the maintainer (contact address to be added before release) rather than opening a public issue.

## Design

- The backend only holds the Supabase **anon** key. Access to data is enforced by Postgres RLS and `security definer` functions that check `auth.uid()`, not just by the routes.
- Passwords are checked by Supabase Auth and never stored by this service; the add-on stores only a refresh token.
- Auth endpoints have per-IP rate limits; password reset, group joins and history uploads are limited in Postgres. See "Rate limits and errors" in `README.md`.
- Database error details are logged, not returned to the client.

## Known limitations

These are accepted for now and disclosed here rather than hidden.

- **Username enumeration.** `username_available` is granted to `anon` (`0003_profiles.sql`) and the backend holds only the anon key, so revoking it would break signup. Anyone calling PostgREST directly can check whether a username exists.
- **Email enumeration on signup.** A duplicate signup returns 409 `user_already_exists`, which reveals that an email is registered. Mitigated only by the signup rate limit (10/hour per IP).
- **Profiles are readable by every authenticated user** (`using (true)`), so any account can list usernames and `history_synced_at`.
- **Sharing is all-or-nothing.** There is no per-group opt-out or hiding stats from one group, and a new member sees the last 365 days of every member on joining.
- **In-memory rate limits.** Signup/login/refresh/delete limits are per process and per IP; they assume a single instance behind a proxy configured with `--proxy-headers --forwarded-allow-ips`.
- **Deprecated endpoint.** `GET /profiles/{username}/reviews` still exists for old add-on versions and is limited to users sharing a group. It will be removed once those versions are retired.
- **Untested SQL.** The SQL/RLS logic (join limits, group visibility, account deletion, upload limits) has no automated tests; the test suite uses fake services.
- **Availability.** Free-tier cold starts can exceed the add-on's 60 s timeout, and a Supabase outage makes authenticated requests return 502.
