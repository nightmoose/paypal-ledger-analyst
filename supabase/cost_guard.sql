-- Tables + RPCs used by ledger/costguard.py. Replace <APP_SECRET> with the value of your APP_SECRET env var.
-- RLS is enabled with no policies, so the tables are only reachable through these secret-checked functions.
create table if not exists public.pla_secret (id int primary key default 1, s text not null);
insert into public.pla_secret(id,s) values (1,'<APP_SECRET>') on conflict (id) do update set s=excluded.s;
create table if not exists public.pla_spend (id bigserial primary key, ts timestamptz default now(), usd numeric not null, in_tok int, out_tok int, model text);
create table if not exists public.pla_hits (id bigserial primary key, ts timestamptz default now(), ip text not null);
create index if not exists pla_hits_ip_ts on public.pla_hits(ip, ts);
create table if not exists public.pla_actions (id bigserial primary key, ts timestamptz default now(), action_id text, kind text, target text, status int, detail text);
alter table public.pla_secret enable row level security;
alter table public.pla_spend enable row level security;
alter table public.pla_hits enable row level security;
alter table public.pla_actions enable row level security;
create or replace function public.pla_gate(p_secret text, p_ip text, p_cap numeric, p_per_10min int, p_per_day int)
returns json language plpgsql security definer set search_path=public as $$
declare spent numeric; n10 int; nday int;
begin
  if p_secret is distinct from (select s from pla_secret where id=1) then raise exception 'forbidden'; end if;
  select coalesce(sum(usd),0) into spent from pla_spend;
  if spent >= p_cap then return json_build_object('allowed',false,'reason','budget','spent',spent); end if;
  select count(*) into n10 from pla_hits where ip=p_ip and ts > now()-interval '10 minutes';
  select count(*) into nday from pla_hits where ip=p_ip and ts > now()-interval '1 day';
  if n10 >= p_per_10min or nday >= p_per_day then return json_build_object('allowed',false,'reason','rate','spent',spent); end if;
  insert into pla_hits(ip) values (p_ip);
  return json_build_object('allowed',true,'spent',spent);
end $$;
create or replace function public.pla_add_spend(p_secret text, p_usd numeric, p_in int, p_out int, p_model text)
returns numeric language plpgsql security definer set search_path=public as $$
begin
  if p_secret is distinct from (select s from pla_secret where id=1) then raise exception 'forbidden'; end if;
  insert into pla_spend(usd,in_tok,out_tok,model) values (p_usd,p_in,p_out,p_model);
  return (select coalesce(sum(usd),0) from pla_spend);
end $$;
create or replace function public.pla_log_action(p_secret text, p_action_id text, p_kind text, p_target text, p_status int, p_detail text)
returns void language plpgsql security definer set search_path=public as $$
begin
  if p_secret is distinct from (select s from pla_secret where id=1) then raise exception 'forbidden'; end if;
  insert into pla_actions(action_id,kind,target,status,detail) values (p_action_id,p_kind,p_target,p_status,left(p_detail,2000));
end $$;
revoke all on function public.pla_gate(text,text,numeric,int,int) from public;
revoke all on function public.pla_add_spend(text,numeric,int,int,text) from public;
revoke all on function public.pla_log_action(text,text,text,text,int,text) from public;
grant execute on function public.pla_gate(text,text,numeric,int,int) to anon;
grant execute on function public.pla_add_spend(text,numeric,int,int,text) to anon;
grant execute on function public.pla_log_action(text,text,text,text,int,text) to anon;
