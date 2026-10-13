-- Profiles map a unique username to a user so friends can be looked up by name.
create table public.profiles (
  user_id    uuid primary key references auth.users(id) on delete cascade,
  username   text not null check (username ~ '^[a-z0-9_]{3,20}$'),
  created_at timestamptz not null default now()
);

create unique index profiles_username_key on public.profiles (lower(username));

alter table public.profiles enable row level security;

-- A username is the public lookup key, so any signed-in user can read profiles.
-- No insert/update/delete policies: rows are created by the signup trigger below.
create policy "select all" on public.profiles for select to authenticated
  using (true);

-- Create the profile when a user signs up, from the username passed as signup metadata.
-- Done in the database so it works even when email confirmation means there is no session yet.
create function public.handle_new_user() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
  if new.raw_user_meta_data ->> 'username' is not null then
    insert into public.profiles (user_id, username)
    values (new.id, lower(new.raw_user_meta_data ->> 'username'));
  end if;
  return new;
end;
$$;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- Lets signup return a clean "taken" error before the auth user is created.
create function public.username_available(p_username text) returns boolean
language sql stable security definer set search_path = '' as $$
  select not exists (
    select 1 from public.profiles where lower(username) = lower(p_username)
  );
$$;

revoke execute on function public.username_available(text) from public;
grant execute on function public.username_available(text) to anon, authenticated;

-- Another user's daily totals for a date range. Security definer so daily_reviews RLS
-- (own rows only) stays untouched; only these four columns are exposed.
create function public.friend_daily_reviews(p_user_id uuid, p_start date, p_end date)
returns table (
  study_date    date,
  total_reviews integer,
  retention     numeric,
  study_minutes numeric
)
language sql stable security definer set search_path = '' as $$
  select d.study_date, d.total_reviews, d.retention, d.study_minutes
  from public.daily_reviews d
  where d.user_id = p_user_id
    and d.study_date between p_start and p_end
  order by d.study_date desc;
$$;

revoke execute on function public.friend_daily_reviews(uuid, date, date) from public;
grant execute on function public.friend_daily_reviews(uuid, date, date) to authenticated;
