# AnkiHelper backend roadmap: groups and account deletion

Handoff for Claude Code, for the **backend repo** (`AnkiHelper`). Work through the tasks **in order** and stop for review after each one. The add-on has its own roadmap. It is a separate repo and will be updated after these endpoints exist.

## Context

AnkiHelper is an Anki add-on plus this FastAPI + Supabase backend that lets people share daily study stats. It's being prepared for public users and, later, paid plans.

Sharing is moving from per-user friends to **groups ("rooms")**: everyone who has joined a group can see every other member's daily reviews, and shares their own. The add-on has already been updated so it no longer stores passwords (login dialog, refresh token only) and no longer uses pydantic. Nothing on the backend has changed for that.

Read `CLAUDE.md`, `README.md` and `docs/API_GUIDE.md` first. Commands: `uv sync`, `uv run pytest`.

## Ground rules

- Follow the existing layering: `routers/` → `services/` → `models/`, with `CurrentUser` and `UserClient` from `dependencies.py`.
- **Never use the Supabase service-role key.** Access control lives in Postgres: RLS plus `security definer` functions that check `auth.uid()` (use `set search_path = ''`, as in the existing migrations). Checks in the router alone are not enough.
- New migrations go in `supabase/migrations/` with the next number. Don't edit old migrations.
- Every change gets tests in the existing style (faked services, no real Supabase).
- Update `docs/API_GUIDE.md`, `README.md` and `CLAUDE.md` whenever endpoints or decisions change.
- Ask before making any design decision that isn't covered here.

---

## Task 0: Check for leaked secrets

Before this repo goes private, check its full git history for committed secrets (`.env` files, Supabase keys, JWT secrets), for example with `git log -p --all -S` on key prefixes, or `gitleaks` if available. **Report what you find; don't rewrite history.** Any leaked key must be rotated in the Supabase dashboard.

---

## Task 1: Groups

### How it works

- A user creates a group and becomes its **owner**.
- Each group has an **invite code**: a random, human-friendly code (for example `K7QF-29XM`), separate from the group's internal ID. The owner can regenerate it.
- The owner manages an **allowed list** of usernames.
- A user joins by entering the invite code. Joining succeeds **only if their username is on that group's allowed list**.
- Being on the allowed list shares nothing. Data is shared only between **joined** members.
- Joined members can see every other joined member's daily review rows. A user in several groups shares with each of them.

### Decisions (defaults, confirm with me if one seems wrong)

- **History:** members see each other's last 365 days, including days before joining.
- **Removing a username from the allowed list** also removes that user's membership right away.
- **The owner can't leave** their own group. They must transfer ownership or delete the group.
- **If the owner deletes their account,** ownership passes to the longest-standing member. If there are no other members, the group is deleted.
- **Limits** (constants in config): at most 20 owned groups per user, at most 50 allowed usernames per group.
- **The owner is the only one who sees** the invite code and the allowed list. Members see the group name and member list.
- **Billing:** add a `plan` column on `groups` (default `'free'`), but don't enforce anything yet.

### Migration `0004_groups.sql`

Tables:
- `groups`: `id uuid`, `name text` (1–50 characters), `owner_id` (references `auth.users`), `invite_code text unique`, `plan text default 'free'`, `created_at`
- `group_allowed`: `group_id` (`on delete cascade`), `username text` (stored lowercase), primary key `(group_id, username)`
- `group_members`: `group_id` (`on delete cascade`), `user_id` (references `auth.users`, `on delete cascade`), `role` (`owner` | `member`), `joined_at`, primary key `(group_id, user_id)`

Enable RLS on all three tables. Members can select their groups' rows and member lists; only the owner can see `invite_code` and `group_allowed`. Do all writes through `security definer` functions:

- `create_group(name)`: creates the group with a fresh invite code and adds the caller as owner.
- `join_group(code)`: the caller must be on that group's allowed list. Joining twice does nothing. **A bad code and "not allowed" must return the same error,** so the endpoint doesn't reveal which codes exist.
- `leave_group(group_id)`: not allowed for the owner.
- `allow_username(group_id, username)` and `disallow_username(group_id, username)`: owner only. Disallowing also removes the membership.
- `regenerate_invite_code(group_id)`, `rename_group(group_id, name)`, `transfer_ownership(group_id, username)`, `delete_group(group_id)`: owner only. A transfer target must already be a joined member.
- `group_reviews(group_id, start, end)`: returns `(username, study_date, total_reviews, retention, study_minutes)` for every joined member, **only if the caller is a joined member.** This is the main security check.

Generate invite codes from `gen_random_bytes` using an unambiguous alphabet (no 0/O or 1/I), and retry if a code collides.

### Replace the old friends lookup

- Change `friend_daily_reviews` (or replace it) so `GET /profiles/{username}/reviews` returns data **only when the caller and that user share a group** in which both have joined. Otherwise return 404 (not 403), so usernames can't be probed.
- Keep that endpoint working for now so the current add-on doesn't break, and mark it deprecated in the API guide. It's removed once the new add-on is released.

### Endpoints (new router `app/routers/groups.py`)

| Method and path | Who | Notes |
| --- | --- | --- |
| `POST /groups` `{name}` | anyone | returns the group, including `invite_code` |
| `GET /groups` | anyone | the caller's groups: `id`, `name`, `role`, `member_count` |
| `GET /groups/{id}` | members | name, owner username, members (`username`, `role`, `joined_at`); owner also gets `invite_code` and `allowed` |
| `PATCH /groups/{id}` `{name}` | owner | rename |
| `DELETE /groups/{id}` | owner | 204 |
| `POST /groups/join` `{invite_code}` | anyone | returns the group; 404 for a bad code or not allowed |
| `POST /groups/{id}/leave` | members | 409 for the owner |
| `POST /groups/{id}/allowed` `{username}` | owner | adds the lowercase username; it doesn't have to exist yet |
| `DELETE /groups/{id}/allowed/{username}` | owner | also removes the member |
| `POST /groups/{id}/invite-code` | owner | regenerates and returns the new code |
| `POST /groups/{id}/transfer` `{username}` | owner | the target must be a member |
| `GET /groups/{id}/reviews?days=365` | members | `{group_id, start, end, members: [{username, days: [...]}]}`, with `days` 1–365 (default 30); each day has the same fields as today's friend rows |

A non-member asking for a group's details or reviews gets 404, whether or not the group exists.

### Tests

- The full lifecycle: create, allow, join, read reviews, leave, rejoin.
- A user who isn't allowed can't join, even with the right code.
- After being disallowed or leaving, a user can no longer read the group's reviews, and the group can no longer read theirs.
- An owner can't leave; transferring ownership works; deleting the group cascades.
- The old `/profiles/{username}/reviews` endpoint returns 404 for users who don't share a group.
- The limits are enforced.

Also consider a simple rate limit on `POST /groups/join`. Propose one before building it.

---

## Task 2: Account deletion

- Add a `public.delete_my_account()` `security definer` function. It first applies the owner rule (transfer each owned group to its longest-standing member, or delete the group if there are none), then deletes from `auth.users` where `id = auth.uid()`. Make sure every table cascades: profiles, daily reviews, group memberships and allowed entries.
- Add `DELETE /auth/me` with `{password}` in the body. Verify the password with a fresh sign-in before deleting, then return 204.
- Tests: the cascade, ownership transfer on deletion, wrong password rejected, and the deleted user can't log in.
- Update the "Nothing is deleted server-side" decision in `CLAUDE.md`.

---

## Task 3: Website (separate new repo, plan first)

**Propose a stack and hosting first and wait for approval.** Keep it simple and cheap. A static site that calls this API is fine. Add CORS on this backend for the site's domain only.

The first version needs:
- A landing page explaining AnkiHelper, with screenshots, and a link to install the add-on from AnkiWeb.
- Log in, plus an account page: username, email, **delete account** (calling `DELETE /auth/me`), and log out.
- Privacy policy and terms pages, with placeholder text clearly marked for me to review.

**Payments come later, in Stripe test mode only,** once Tasks 1–2 are merged. The plan, for reference: Stripe Checkout for subscriptions, the Stripe customer portal for canceling and switching plans, and a backend webhook (with Stripe's signature verified) that sets the plan. Pricing isn't decided yet: either group-size tiers or about $4.99/month per user, where paying users create groups and members join free.

---

## Later (context only, don't build)

- Group goals and group stats endpoints.
- Sharing newly added cards within a group.
- AI features (weekly insights, quizzes, reading practice from known vocabulary). These run server-side only, with per-plan usage limits.
