-- Bulk review history upload. The add-on sends per-day stats for up to a year from its local
-- revlog and the server REPLACES that date range for the caller (the revlog is the source of
-- truth, and after an Anki sync it includes mobile reviews).
-- Limits mirror HISTORY_MAX_DAYS / HISTORY_SYNC_MAX_PER_HOUR / HISTORY_FUTURE_SLACK_DAYS in
-- app/config.py; change both together.

-- null = this account has never uploaded its history; the add-on uses it to decide whether to
-- run the automatic backfill (server-side, so a reinstall or second computer doesn't repeat it).
alter table public.profiles add column history_synced_at timestamptz;

create table public.history_syncs (
  user_id   uuid not null references auth.users(id) on delete cascade,
  synced_at timestamptz not null default now()
);

create index history_syncs_user_idx on public.history_syncs (user_id, synced_at);

-- No policies: only replace_daily_reviews (security definer) touches this table.
alter table public.history_syncs enable row level security;

create function public.replace_daily_reviews(p_start date, p_end date, p_days jsonb)
returns integer
language plpgsql security definer set search_path = '' as $$
declare
  uid     uuid := auth.uid();
  written integer;
begin
  if uid is null then
    raise exception 'forbidden';
  end if;

  -- At most 365 days inclusive. The end may be one day ahead of the server's date so clients
  -- ahead of UTC (e.g. Japan), whose Anki day is already tomorrow, are accepted.
  if p_end < p_start or p_end - p_start > 364 or p_end > current_date + 1 then
    raise exception 'invalid_range';
  end if;

  -- 5 uploads per user per hour. A raised exception rolls back the history_syncs insert below,
  -- so failed uploads don't count toward the limit (intended).
  delete from public.history_syncs
  where user_id = uid and synced_at < now() - interval '1 hour';
  if (select count(*) from public.history_syncs where user_id = uid) >= 5 then
    raise exception 'rate_limited';
  end if;

  if exists (
    select 1
    from jsonb_to_recordset(coalesce(p_days, '[]'::jsonb))
      as d(study_date date, total_reviews integer, retention numeric, study_minutes numeric)
    where d.study_date is null or d.study_date < p_start or d.study_date > p_end
  ) then
    raise exception 'invalid_range';
  end if;

  -- daily_reviews has no delete policy; deleting here is safe because this function only ever
  -- touches auth.uid()'s own rows. Runs as one transaction, so a failure keeps the old rows.
  delete from public.daily_reviews
  where user_id = uid and study_date between p_start and p_end;

  insert into public.daily_reviews (user_id, study_date, total_reviews, retention, study_minutes)
  select uid, d.study_date, d.total_reviews, d.retention, d.study_minutes
  from jsonb_to_recordset(coalesce(p_days, '[]'::jsonb))
    as d(study_date date, total_reviews integer, retention numeric, study_minutes numeric);
  get diagnostics written = row_count;

  update public.profiles set history_synced_at = now() where user_id = uid;
  insert into public.history_syncs (user_id) values (uid);

  return written;
end;
$$;

revoke execute on function public.replace_daily_reviews(date, date, jsonb) from public;
grant execute on function public.replace_daily_reviews(date, date, jsonb) to authenticated;
