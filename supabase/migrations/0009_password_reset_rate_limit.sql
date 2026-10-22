-- Rate limit on POST /auth/forgot-password: at most 10 requests per IP and 3 per email per hour.
-- Mirrors RESET_MAX_PER_IP_PER_HOUR / RESET_MAX_PER_EMAIL_PER_HOUR in app/config.py; change both.
--
-- Every request is counted whether or not the email has an account, so hitting the limit reveals
-- nothing about who is registered. Only a hash of the email is stored. The function returns false
-- instead of raising so the row recording the request survives the transaction (see 0006).
-- Callers are not logged in, so it is granted to anon (like username_available).
create table public.password_reset_requests (
  ip           text not null,
  email_hash   text not null,
  requested_at timestamptz not null default now()
);

create index password_reset_requests_ip_idx on public.password_reset_requests (ip, requested_at);
create index password_reset_requests_email_idx
  on public.password_reset_requests (email_hash, requested_at);

-- No policies: only check_password_reset_limit (security definer) touches this table.
alter table public.password_reset_requests enable row level security;

create function public.check_password_reset_limit(p_ip text, p_email text) returns boolean
language plpgsql security definer set search_path = '' as $$
declare
  v_ip   text := coalesce(p_ip, 'unknown');
  v_hash text := encode(sha256(convert_to(lower(trim(coalesce(p_email, ''))), 'utf8')), 'hex');
begin
  delete from public.password_reset_requests where requested_at < now() - interval '1 hour';
  if (select count(*) from public.password_reset_requests where ip = v_ip) >= 10
     or (select count(*) from public.password_reset_requests where email_hash = v_hash) >= 3 then
    return false;
  end if;
  insert into public.password_reset_requests (ip, email_hash) values (v_ip, v_hash);
  return true;
end;
$$;

revoke execute on function public.check_password_reset_limit(text, text) from public;
grant execute on function public.check_password_reset_limit(text, text) to anon;
