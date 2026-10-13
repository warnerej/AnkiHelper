create table public.daily_reviews (
  user_id       uuid not null default auth.uid() references auth.users(id) on delete cascade,
  study_date    date not null,
  total_reviews integer not null check (total_reviews >= 0),
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  primary key (user_id, study_date)
);

create function public.set_updated_at() returns trigger
language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create trigger daily_reviews_set_updated_at
  before update on public.daily_reviews
  for each row execute function public.set_updated_at();

alter table public.daily_reviews enable row level security;

create policy "select own" on public.daily_reviews for select to authenticated
  using (user_id = (select auth.uid()));
create policy "insert own" on public.daily_reviews for insert to authenticated
  with check (user_id = (select auth.uid()));
create policy "update own" on public.daily_reviews for update to authenticated
  using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));
-- No delete policy: deletes are denied by default.
