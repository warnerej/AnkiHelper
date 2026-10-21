-- Groups: users share daily reviews with the members who have joined the same group.
-- Joining needs the invite code AND the joiner's username on the group's allowed list.
-- All writes go through security-definer functions that check auth.uid(); the tables
-- have no insert/update/delete policies.
--
-- Errors are raised as `raise exception '<token>'`; the API maps the token to an HTTP status
-- (see app/services/groups.py). Limits below mirror MAX_OWNED_GROUPS / MAX_ALLOWED_USERNAMES
-- in app/config.py; change both together.

create extension if not exists pgcrypto with schema extensions;

create table public.groups (
  id          uuid primary key default gen_random_uuid(),
  name        text not null check (char_length(name) between 1 and 50),
  owner_id    uuid not null references auth.users(id),
  invite_code text not null unique,
  plan        text not null default 'free',
  created_at  timestamptz not null default now()
);

create table public.group_allowed (
  group_id uuid not null references public.groups(id) on delete cascade,
  username text not null check (username ~ '^[a-z0-9_]{3,20}$'),
  primary key (group_id, username)
);

create table public.group_members (
  group_id  uuid not null references public.groups(id) on delete cascade,
  user_id   uuid not null references auth.users(id) on delete cascade,
  role      text not null check (role in ('owner', 'member')),
  joined_at timestamptz not null default now(),
  primary key (group_id, user_id)
);

create index group_members_user_idx on public.group_members (user_id);

alter table public.groups        enable row level security;
alter table public.group_allowed enable row level security;
alter table public.group_members enable row level security;

-- Membership checks are security definer so the group_members policy doesn't recurse into itself.
create function public.is_group_member(p_group_id uuid) returns boolean
language sql stable security definer set search_path = '' as $$
  select exists (
    select 1 from public.group_members
    where group_id = p_group_id and user_id = (select auth.uid())
  );
$$;

revoke execute on function public.is_group_member(uuid) from public;
grant execute on function public.is_group_member(uuid) to authenticated;

-- Only the owner can read the groups row (it holds invite_code). Members read name, owner and
-- members through get_group()/my_groups() below, which leave the code out.
create policy "owner select" on public.groups for select to authenticated
  using (owner_id = (select auth.uid()));

create policy "member select" on public.group_members for select to authenticated
  using (public.is_group_member(group_id));

create policy "owner select" on public.group_allowed for select to authenticated
  using (exists (
    select 1 from public.groups g
    where g.id = group_id and g.owner_id = (select auth.uid())
  ));

-- ---------------------------------------------------------------------------
-- Internal helpers (not granted to API roles)
-- ---------------------------------------------------------------------------

-- Random XXXX-XXXX code from an alphabet without 0/O/1/I/L. The tiny modulo bias is harmless.
create function public._new_invite_code() returns text
language plpgsql volatile set search_path = '' as $$
declare
  alphabet constant text := 'ABCDEFGHJKMNPQRSTUVWXYZ23456789';
  bytes bytea;
  code  text;
  i     int;
  tries int := 0;
begin
  loop
    bytes := extensions.gen_random_bytes(8);
    code := '';
    for i in 0..7 loop
      code := code || substr(alphabet, (get_byte(bytes, i) % length(alphabet)) + 1, 1);
    end loop;
    code := substr(code, 1, 4) || '-' || substr(code, 5, 4);
    -- The unique constraint is the final guard; this just avoids the obvious collision.
    exit when not exists (select 1 from public.groups where invite_code = code);
    tries := tries + 1;
    if tries >= 10 then
      raise exception 'invite_code_unavailable';
    end if;
  end loop;
  return code;
end;
$$;

revoke execute on function public._new_invite_code() from public;

-- Raises not_found for non-members (so a group's existence isn't revealed) and forbidden for
-- members who are not the owner.
create function public._require_owner(p_group_id uuid) returns void
language plpgsql stable security definer set search_path = '' as $$
begin
  if not exists (
    select 1 from public.group_members
    where group_id = p_group_id and user_id = auth.uid()
  ) then
    raise exception 'not_found';
  end if;
  if not exists (
    select 1 from public.groups where id = p_group_id and owner_id = auth.uid()
  ) then
    raise exception 'forbidden';
  end if;
end;
$$;

revoke execute on function public._require_owner(uuid) from public;

-- ---------------------------------------------------------------------------
-- Reads
-- ---------------------------------------------------------------------------

create function public.my_groups()
returns table (id uuid, name text, role text, member_count bigint)
language sql stable security definer set search_path = '' as $$
  select g.id, g.name, m.role,
         (select count(*) from public.group_members c where c.group_id = g.id)
  from public.group_members m
  join public.groups g on g.id = m.group_id
  where m.user_id = auth.uid()
  order by g.created_at, g.id;
$$;

-- Group details as json. invite_code and allowed are present only for the owner.
create function public.get_group(p_group_id uuid) returns jsonb
language plpgsql stable security definer set search_path = '' as $$
declare
  g      public.groups;
  result jsonb;
begin
  if not public.is_group_member(p_group_id) then
    raise exception 'not_found';
  end if;
  select * into g from public.groups where id = p_group_id;

  result := jsonb_build_object(
    'id', g.id,
    'name', g.name,
    'owner', (select p.username from public.profiles p where p.user_id = g.owner_id),
    'members', coalesce((
      select jsonb_agg(
               jsonb_build_object('username', p.username, 'role', m.role, 'joined_at', m.joined_at)
               order by m.joined_at, p.username)
      from public.group_members m
      join public.profiles p on p.user_id = m.user_id
      where m.group_id = g.id
    ), '[]'::jsonb)
  );

  if g.owner_id = auth.uid() then
    result := result || jsonb_build_object(
      'invite_code', g.invite_code,
      'allowed', coalesce((
        select jsonb_agg(a.username order by a.username)
        from public.group_allowed a where a.group_id = g.id
      ), '[]'::jsonb)
    );
  end if;
  return result;
end;
$$;

-- Every joined member's daily rows (members with no rows in the window come back with a null
-- study_date). Only callable by a joined member. This is the main access check for shared data.
create function public.group_reviews(p_group_id uuid, p_start date, p_end date)
returns table (
  username      text,
  study_date    date,
  total_reviews integer,
  retention     numeric,
  study_minutes numeric
)
language plpgsql stable security definer set search_path = '' as $$
#variable_conflict use_column
begin
  if not public.is_group_member(p_group_id) then
    raise exception 'not_found';
  end if;
  return query
    select p.username, d.study_date, d.total_reviews, d.retention, d.study_minutes
    from public.group_members m
    join public.profiles p on p.user_id = m.user_id
    left join public.daily_reviews d
      on d.user_id = m.user_id
     and d.study_date between greatest(p_start, p_end - 364) and p_end
    where m.group_id = p_group_id
    order by p.username, d.study_date desc;
end;
$$;

-- ---------------------------------------------------------------------------
-- Writes
-- ---------------------------------------------------------------------------

create function public.create_group(p_name text) returns uuid
language plpgsql security definer set search_path = '' as $$
declare
  uid  uuid := auth.uid();
  v_name text := btrim(p_name);
  gid  uuid;
begin
  if v_name is null or char_length(v_name) not between 1 and 50 then
    raise exception 'invalid_name';
  end if;
  if not exists (select 1 from public.profiles where user_id = uid) then
    raise exception 'forbidden';
  end if;
  if (select count(*) from public.groups where owner_id = uid) >= 20 then
    raise exception 'limit_reached';
  end if;

  insert into public.groups (name, owner_id, invite_code)
  values (v_name, uid, public._new_invite_code())
  returning id into gid;
  insert into public.group_members (group_id, user_id, role) values (gid, uid, 'owner');
  return gid;
end;
$$;

-- A bad code and "not on the allowed list" raise the same error.
create function public.join_group(p_code text) returns uuid
language plpgsql security definer set search_path = '' as $$
declare
  uid   uuid := auth.uid();
  code  text := upper(regexp_replace(coalesce(p_code, ''), '[^A-Za-z0-9]', '', 'g'));
  gid   uuid;
  uname text;
begin
  if char_length(code) = 8 then
    code := substr(code, 1, 4) || '-' || substr(code, 5, 4);
  end if;
  select id into gid from public.groups where invite_code = code;
  select username into uname from public.profiles where user_id = uid;

  if gid is null or uname is null or not exists (
    select 1 from public.group_allowed where group_id = gid and username = lower(uname)
  ) then
    raise exception 'not_found';
  end if;

  insert into public.group_members (group_id, user_id, role)
  values (gid, uid, 'member')
  on conflict do nothing;
  return gid;
end;
$$;

create function public.leave_group(p_group_id uuid) returns void
language plpgsql security definer set search_path = '' as $$
declare
  r text;
begin
  select role into r from public.group_members
  where group_id = p_group_id and user_id = auth.uid();
  if r is null then
    raise exception 'not_found';
  end if;
  if r = 'owner' then
    raise exception 'owner_cannot_leave';
  end if;
  delete from public.group_members where group_id = p_group_id and user_id = auth.uid();
end;
$$;

create function public.allow_username(p_group_id uuid, p_username text) returns void
language plpgsql security definer set search_path = '' as $$
declare
  uname text := lower(btrim(p_username));
begin
  perform public._require_owner(p_group_id);
  if uname is null or uname !~ '^[a-z0-9_]{3,20}$' then
    raise exception 'invalid_username';
  end if;
  if not exists (
    select 1 from public.group_allowed where group_id = p_group_id and username = uname
  ) then
    if (select count(*) from public.group_allowed where group_id = p_group_id) >= 50 then
      raise exception 'limit_reached';
    end if;
    insert into public.group_allowed (group_id, username) values (p_group_id, uname);
  end if;
end;
$$;

-- Removes the username from the allowed list and drops that user's membership.
create function public.disallow_username(p_group_id uuid, p_username text) returns void
language plpgsql security definer set search_path = '' as $$
declare
  uname text := lower(btrim(p_username));
  target uuid;
begin
  perform public._require_owner(p_group_id);
  select user_id into target from public.profiles where lower(username) = uname;
  if target is not null and target = auth.uid() then
    raise exception 'cannot_remove_owner';
  end if;
  delete from public.group_allowed where group_id = p_group_id and username = uname;
  if target is not null then
    delete from public.group_members where group_id = p_group_id and user_id = target;
  end if;
end;
$$;

create function public.regenerate_invite_code(p_group_id uuid) returns text
language plpgsql security definer set search_path = '' as $$
declare
  code text;
begin
  perform public._require_owner(p_group_id);
  code := public._new_invite_code();
  update public.groups set invite_code = code where id = p_group_id;
  return code;
end;
$$;

create function public.rename_group(p_group_id uuid, p_name text) returns void
language plpgsql security definer set search_path = '' as $$
declare
  v_name text := btrim(p_name);
begin
  perform public._require_owner(p_group_id);
  if v_name is null or char_length(v_name) not between 1 and 50 then
    raise exception 'invalid_name';
  end if;
  update public.groups set name = v_name where id = p_group_id;
end;
$$;

-- The target must already be a joined member. The old owner becomes a plain member.
create function public.transfer_ownership(p_group_id uuid, p_username text) returns void
language plpgsql security definer set search_path = '' as $$
declare
  target uuid;
begin
  perform public._require_owner(p_group_id);
  select m.user_id into target
  from public.group_members m
  join public.profiles p on p.user_id = m.user_id
  where m.group_id = p_group_id and lower(p.username) = lower(btrim(p_username));
  if target is null then
    raise exception 'not_member';
  end if;
  if target = auth.uid() then
    return;
  end if;

  update public.group_members set role = 'member'
  where group_id = p_group_id and user_id = auth.uid();
  update public.group_members set role = 'owner'
  where group_id = p_group_id and user_id = target;
  update public.groups set owner_id = target where id = p_group_id;
end;
$$;

create function public.delete_group(p_group_id uuid) returns void
language plpgsql security definer set search_path = '' as $$
begin
  perform public._require_owner(p_group_id);
  delete from public.groups where id = p_group_id;  -- members and allowed rows cascade
end;
$$;

do $$
declare
  f text;
begin
  foreach f in array array[
    'my_groups()', 'get_group(uuid)', 'group_reviews(uuid, date, date)',
    'create_group(text)', 'join_group(text)', 'leave_group(uuid)',
    'allow_username(uuid, text)', 'disallow_username(uuid, text)',
    'regenerate_invite_code(uuid)', 'rename_group(uuid, text)',
    'transfer_ownership(uuid, text)', 'delete_group(uuid)'
  ] loop
    execute format('revoke execute on function public.%s from public', f);
    execute format('grant execute on function public.%s to authenticated', f);
  end loop;
end;
$$;
