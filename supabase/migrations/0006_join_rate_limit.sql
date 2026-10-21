-- Rate limit on joining: at most 10 failed attempts per user per hour. Failures (bad code or
-- not allowed) are counted; successful joins are not. Mirrors JOIN_MAX_FAILURES /
-- JOIN_WINDOW_MINUTES in app/config.py; change both together.
--
-- join_group now RETURNS NULL on failure instead of raising: a raised exception rolls the
-- transaction back, which would also undo the row recording the failed attempt. The API turns a
-- null result into the same 404 as before. Once the limit is hit the call raises 'rate_limited'
-- before looking at the code, so the answer reveals nothing about which codes exist.
create table public.join_attempts (
  user_id      uuid not null references auth.users(id) on delete cascade,
  attempted_at timestamptz not null default now()
);

create index join_attempts_user_idx on public.join_attempts (user_id, attempted_at);

-- No policies: only join_group (security definer) touches this table.
alter table public.join_attempts enable row level security;

create or replace function public.join_group(p_code text) returns uuid
language plpgsql security definer set search_path = '' as $$
declare
  uid   uuid := auth.uid();
  code  text := upper(regexp_replace(coalesce(p_code, ''), '[^A-Za-z0-9]', '', 'g'));
  gid   uuid;
  uname text;
begin
  delete from public.join_attempts
  where user_id = uid and attempted_at < now() - interval '1 hour';
  if (select count(*) from public.join_attempts where user_id = uid) >= 10 then
    raise exception 'rate_limited';
  end if;

  if char_length(code) = 8 then
    code := substr(code, 1, 4) || '-' || substr(code, 5, 4);
  end if;
  select id into gid from public.groups where invite_code = code;
  select username into uname from public.profiles where user_id = uid;

  if gid is null or uname is null or not exists (
    select 1 from public.group_allowed where group_id = gid and username = lower(uname)
  ) then
    insert into public.join_attempts (user_id) values (uid);
    return null;
  end if;

  insert into public.group_members (group_id, user_id, role)
  values (gid, uid, 'member')
  on conflict do nothing;
  return gid;
end;
$$;
