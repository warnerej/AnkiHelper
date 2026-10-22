-- group_reviews returned one row per member-day, so PostgREST's row cap (1000 by default)
-- silently truncated big groups (3 members x 365 days is already over it). This returns one
-- jsonb array with one element per member instead, so the response is always at most one row.
-- The old group_reviews stays so the API can be rolled back; it is unused once this is applied.
create function public.group_reviews_by_member(p_group_id uuid, p_start date, p_end date)
returns jsonb
language plpgsql stable security definer set search_path = '' as $$
begin
  if not public.is_group_member(p_group_id) then
    raise exception 'not_found';
  end if;
  return coalesce((
    select jsonb_agg(
             jsonb_build_object(
               'username', member.username,
               'days', coalesce((
                 select jsonb_agg(
                          jsonb_build_object(
                            'study_date', d.study_date,
                            'total_reviews', d.total_reviews,
                            'retention', d.retention,
                            'study_minutes', d.study_minutes)
                          order by d.study_date desc)
                 from public.daily_reviews d
                 where d.user_id = member.user_id
                   and d.study_date between greatest(p_start, p_end - 364) and p_end
               ), '[]'::jsonb))
             order by member.username)
    from (
      select p.username, m.user_id
      from public.group_members m
      join public.profiles p on p.user_id = m.user_id
      where m.group_id = p_group_id
    ) member
  ), '[]'::jsonb);
end;
$$;

revoke execute on function public.group_reviews_by_member(uuid, date, date) from public;
grant execute on function public.group_reviews_by_member(uuid, date, date) to authenticated;
