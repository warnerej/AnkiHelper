-- Deprecated friend lookup, now limited to users who share a group with the caller
-- (both joined). Anyone else raises not_found, which the API turns into the same 404 as an
-- unknown username. Removed once the new add-on, which uses group_reviews, is released.
create or replace function public.friend_daily_reviews(p_user_id uuid, p_start date, p_end date)
returns table (
  study_date    date,
  total_reviews integer,
  retention     numeric,
  study_minutes numeric
)
language plpgsql stable security definer set search_path = '' as $$
#variable_conflict use_column
begin
  if not exists (
    select 1
    from public.group_members a
    join public.group_members b on b.group_id = a.group_id
    where a.user_id = auth.uid() and b.user_id = p_user_id
  ) then
    raise exception 'not_found';
  end if;
  return query
    select d.study_date, d.total_reviews, d.retention, d.study_minutes
    from public.daily_reviews d
    where d.user_id = p_user_id
      and d.study_date between p_start and p_end
    order by d.study_date desc;
end;
$$;
