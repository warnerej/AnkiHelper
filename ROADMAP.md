# Roadmap

Open work for the backend. Finished plans are in `docs/archive/`.

## Before the public release
- Decide whether this repo becomes private or stays public (undecided). If public, keep `SECURITY.md`.
- Scan the full git history for secrets (`gitleaks`); rotate any leaked Supabase key.
- Confirm the Render start command includes `--proxy-headers --forwarded-allow-ips='*'` and that a single instance runs.
- Deploy, then smoke test production: signup, login, refresh, delete, group flows, the 429 path.
- Add the support contact to `SECURITY.md` once it exists.

## Password-reset site page
Not started (no site repo, no CORS). The page at `PASSWORD_RESET_REDIRECT_URL` loads supabase-js (anon key), takes the recovery session from the link, asks for a new password twice (min 8 chars), calls `supabase.auth.updateUser({password})`, then tells the user to log in again in Anki, with a "request a new link" message for expired links. Add the page URL to Supabase Auth > URL Configuration > Redirect URLs.

## Later
- Observability: request logging; make `/health` check Supabase (or add `/health/ready`); error tracking.
- Performance: every authenticated request makes an extra Supabase call to validate the token and builds a new client (`app/dependencies.py`). Add a short TTL token cache and reuse the client.
- SQL/RLS tests against a local Postgres: join limits, group visibility, `delete_my_account`, history upload limit, reset limiter.
- API compatibility: an `X-Client-Version` check with a clear "please update" error.
- Remove the deprecated `/profiles/{username}/reviews` once old add-on versions are retired.
- Billing/plans: `groups.plan` exists but is not enforced.
