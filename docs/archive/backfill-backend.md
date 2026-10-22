> **Archived 2026-10-22.** Done: `PUT /reviews/history` and `GET /reviews/history/status` shipped in migration 0008. Reference: `docs/API_GUIDE.md`.

# AnkiHelper backend: review history backfill

Handoff for Claude Code, for the **backend repo** (`AnkiHelper`). Work through the tasks **in order** and stop for review after each one.

**Ship before the add-on side.** The add-on handoff (`backfill-addon.md`) depends on both endpoints here being deployed.

## Context

Today the add-on only ever sends the current day (`PUT /reviews/daily`). Two things go wrong because of that:

- **New users join a group with an empty heatmap.** Their past year of reviews is in their local Anki collection but never reaches the server.
- **Reviews done on a phone are lost.** AnkiDroid and AnkiMobile have no add-on, so their reviews only show up on desktop after a sync. By then they're usually for a past day, which never gets pushed.

The fix is a bulk "history" upload. The add-on computes per-day stats for the last year from its local revlog and sends them in one request. The server **replaces** that date range for the user. This happens automatically once for every account and can be triggered manually from the add-on if the user's data looks wrong.

The local revlog is the source of truth. Anki syncs the whole collection, so after a sync the desktop revlog includes mobile reviews too. That's why the endpoint replaces the range rather than merging it. Replacing also fixes past bad pushes.

Read `CLAUDE.md`, `README.md` and `docs/API_GUIDE.md` first. Commands: `uv sync`, `uv run pytest`.

## Ground rules

- Follow the existing pattern: the rules live in Postgres (security-definer functions that check `auth.uid()`), and FastAPI validates shapes and maps error tokens to HTTP codes.
- Any limit that appears in both SQL and `app/config.py` gets the "mirrored, change both together" comment, like the group limits.
- Every change gets tests in the existing style.
- Update `docs/API_GUIDE.md` and `README.md` when behavior changes.
- Ask before making any design decision that isn't covered here.

---

## Task 1: Migration `0008_review_history.sql`

1. **Add `profiles.history_synced_at`.** It's a nullable `timestamptz`, and `null` means the account has never uploaded its history. The add-on uses it to decide whether to run the automatic backfill. Keeping it server-side means a reinstall or a second computer doesn't trigger another automatic upload.

2. **Create a `history_syncs` table** with `user_id` (references `auth.users`, on delete cascade) and `synced_at timestamptz default now()`. Add an index on `(user_id, synced_at)` and enable RLS with no policies. It works like `join_attempts` and is only touched by the function below.

3. **Create `public.replace_daily_reviews(p_start date, p_end date, p_days jsonb) returns integer`.** It's `security definer` with `set search_path = ''`, and it returns the number of rows written. In order, it:
   - raises `forbidden` if `auth.uid()` is null.
   - raises `invalid_range` if `p_end < p_start`, or if `p_end - p_start > 364` (at most 365 days inclusive, which matches the add-on's `year_stats`).
   - raises `invalid_range` if `p_end > current_date + 1`. The `+ 1` allows clients ahead of UTC, such as Japan, whose Anki day can already be tomorrow by the server's date.
   - prunes `history_syncs` rows older than one hour. It raises `rate_limited` if there are already 5 or more in the window. Use 5 per hour: enough for a few manual retries, not enough to hammer the database.
   - raises `invalid_range` if any element of `p_days` has a `study_date` outside `[p_start, p_end]`. Read the array with `jsonb_to_recordset(p_days) as d(study_date date, total_reviews integer, retention numeric, study_minutes numeric)`.
   - deletes the user's `daily_reviews` rows in `[p_start, p_end]`, then inserts the rows from `p_days` with `user_id = auth.uid()`. The table's existing check constraints still validate the values.
   - sets `profiles.history_synced_at = now()` for the user and inserts a `history_syncs` row.

   The function runs as one transaction, so a failure anywhere leaves the old rows untouched. Because a raised error also rolls back the `history_syncs` insert, failed uploads don't count toward the rate limit. That's intended.

   `daily_reviews` has no delete policy. Deleting here is fine because the function only ever touches `auth.uid()`'s rows. Say so in a comment.

4. **Set grants:** revoke execute from `public` and grant to `authenticated`.

**Done when** the migration applies cleanly on a fresh database and on one that already has 0001–0007 applied.

## Task 2: Config, models and service

1. **In `app/config.py`,** add `HISTORY_MAX_DAYS = 365`, `HISTORY_SYNC_MAX_PER_HOUR = 5` and `HISTORY_FUTURE_SLACK_DAYS = 1`, each with the mirrored comment.

2. **In `app/models/reviews.py`,** add:
   - `HistoryDay`: `study_date`, `total_reviews` (≥ 0), and optional `retention` (0–100) and `study_minutes` (0–1440). These are the same constraints as `DailyReviewUpsert`.
   - `HistoryUpload`: `start: date`, `end: date`, `days: list[HistoryDay]` (at most `HISTORY_MAX_DAYS` items). Add a model validator that checks `start <= end`, that the span is at most 365 days, that every `study_date` falls in range, and that dates are unique. Pydantic gives a clean 422 for these, so the SQL checks are a backstop rather than the main path.
   - `HistoryResult`: `start`, `end`, `days_written: int`, `history_synced_at: datetime`.
   - `HistoryStatus`: `history_synced_at: datetime | None`.

3. **In `ReviewService`,** add:
   - `replace_history(body) -> HistoryResult`, which calls the RPC. Map `rate_limited` to 429 and `invalid_range` to 422, following the `ERROR_STATUS` pattern in `groups.py`. Everything else stays 502. Read `history_synced_at` back from `profiles` for the response.
   - `history_status(user_id) -> HistoryStatus`, which selects `history_synced_at` from `profiles` for the caller. If the user has no profile row, return `null`.

## Task 3: Endpoints

Add both to `app/routers/reviews.py`:

- **`PUT /reviews/history`**, with body `HistoryUpload` and response `HistoryResult`.
  - It replaces the caller's rows in `[start, end]` with `days`. A date in range that's missing from `days` is removed, meaning no reviews that day.
  - It's idempotent, so clients may retry it.
  - Put the replace semantics in the docstring, since it shows up on `/docs`.
- **`GET /reviews/history/status`**, with response `HistoryStatus`.

Register `/reviews/history` before `/reviews/daily/{study_date}` isn't strictly necessary, since the prefixes differ, but check that the paths don't collide.

## Task 4: Tests

Add these to `tests/test_reviews.py`, or a new `tests/test_history.py`:

- **Validation (422):** an empty range, a span of 366 days, a date outside the range, duplicate dates, more than 365 items, negative totals, and retention above 100.
- **Error mapping:** `rate_limited` maps to 429, `invalid_range` maps to 422, and any other error maps to 502.
- **Success:** a valid upload returns `days_written` and `history_synced_at`. An empty `days` list in a valid range is accepted and returns `days_written: 0`. That's legitimate: it clears the range.
- **Status:** returns `null` before any upload and a timestamp after.
- **Auth:** both endpoints return 401 without a token.

If you have a way to run SQL tests against a local Supabase, also check:

- a replace removes in-range rows that weren't resent and leaves out-of-range rows alone.
- one user can't touch another user's rows.
- `group_reviews` returns the new rows to group members.

If there's no way to run SQL tests, list these as manual checks in the PR.

## Task 5: Docs

In `docs/API_GUIDE.md`, document both endpoints with an example request and response. Spell out:

- the replace semantics.
- the 365-day limit.
- the one-day future slack.
- the 5-per-hour limit.
- that clients should upload **after** an Anki sync, so the collection includes mobile reviews.

Add a line to the README's feature list.

---

## Out of scope (note for later)

- **Group heatmaps can still miss today for friends in Japan.** `group_reviews` and `friend_reviews` still end their window at the server's `date.today()`, so from midnight to 9am JST a Japanese member's current day is excluded. The fix is a one-line change: end the window at `date.today() + timedelta(days=1)`, or accept an `end` query parameter. Worth a separate small PR, since the add-on's group heatmaps depend on it.
