-- Account deletion. groups.owner_id has no cascade, so owned groups are handed to the
-- longest-standing member (or deleted when nobody else joined) before the auth.users row goes.
-- Everything else cascades from auth.users: profiles, daily_reviews, group_members, join_attempts.
-- The user's username is also dropped from allowed lists so a later user reusing the name
-- doesn't inherit access.

create function public.delete_my_account() returns void
language plpgsql security definer set search_path = '' as $$
declare
  uid       uuid := auth.uid();
  g         record;
  successor uuid;
begin
  if uid is null then
    raise exception 'forbidden';
  end if;

  for g in
    select id from public.groups where owner_id = uid for update
  loop
    select user_id into successor
    from public.group_members
    where group_id = g.id and role = 'member'
    order by joined_at, user_id
    limit 1;

    if successor is null then
      delete from public.groups where id = g.id;  -- members and allowed rows cascade
    else
      update public.group_members set role = 'owner'
      where group_id = g.id and user_id = successor;
      update public.groups set owner_id = successor where id = g.id;
    end if;
  end loop;

  delete from public.group_allowed
  where username = (select lower(username) from public.profiles where user_id = uid);

  delete from auth.users where id = uid;
end;
$$;

revoke execute on function public.delete_my_account() from public;
grant execute on function public.delete_my_account() to authenticated;
