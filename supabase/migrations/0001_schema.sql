-- HUDA schema: architecture.md §6 + implementation-plan.md D4/D7/D12 additions.

create extension if not exists pgcrypto;

create type role_t as enum ('user','admin');
create type level_t as enum ('GREEN','AMBER','RED');
create type warn_status_t as enum ('draft','pending_approval','sent','cancelled','expired');

create table profiles (
  id text primary key,                -- Clerk user id
  email text unique, full_name text,
  role role_t default 'user',
  language text default 'en',         -- 'en' | 'ms'
  telegram_chat_id bigint, telegram_link_code text,
  telegram_link_expires_at timestamptz,             -- D4
  onboarded boolean default false,                  -- D4
  created_at timestamptz default now()
);

create table zones (
  id uuid primary key default gen_random_uuid(),
  name text not null, slug text unique not null,
  state text, district text, met_location_id text,
  match_terms text[] default '{}',                  -- D7: extra names to find in MET warning text
  lat double precision not null, lon double precision not null,
  radius_m int default 2500, polygon jsonb,         -- GeoJSON, optional
  active boolean default true,
  created_at timestamptz default now()
);

create table subscriptions (
  user_id text references profiles(id) on delete cascade,
  zone_id uuid references zones(id) on delete cascade,
  min_level level_t default 'AMBER',
  primary key (user_id, zone_id)
);

create table runs (
  id uuid primary key default gen_random_uuid(),
  started_at timestamptz default now(), finished_at timestamptz,
  status text, sources jsonb, error text,
  backfill_ts timestamptz
);
create index on runs (started_at desc);

create table radar_frames (
  id bigserial primary key, run_id uuid references runs(id) on delete cascade,
  ts timestamptz not null, kind text check (kind in ('observed','nowcast')),
  source_url text, image_path text, bounds jsonb
);
create index on radar_frames (run_id);

create table predictions (
  id bigserial primary key, run_id uuid references runs(id) on delete cascade,
  zone_id uuid references zones(id), ts timestamptz not null,
  rain_rate_max real, eta_min int, accum_1h real, accum_24h real,
  p_ml real, official_warning text, level level_t not null,
  explanation jsonb
);
create index on predictions (zone_id, ts desc);

create table warnings (
  id uuid primary key default gen_random_uuid(),
  zone_id uuid references zones(id), level level_t,
  status warn_status_t default 'draft', source text check (source in ('auto','manual','agent')),
  message_en text, message_ms text,
  created_by text, approved_by text,
  created_at timestamptz default now(), sent_at timestamptz, expires_at timestamptz,
  last_broadcast_at timestamptz,                    -- D4: 5-min rebroadcast minimum
  telegram_message_id bigint
);
create index on warnings (zone_id, created_at desc);
create index on warnings (status);

create table reports (
  id uuid primary key default gen_random_uuid(),
  type text check (type in ('daily','event','custom')),
  zone_ids uuid[], period_start timestamptz, period_end timestamptz,
  content_md text, created_by text, created_at timestamptz default now(),
  status text default 'generating' check (status in ('generating','ready','failed')),  -- D4
  error text                                                                          -- D4
);

create table logs (
  id bigserial primary key, ts timestamptz default now(),
  severity text, category text,        -- ingest|model|agent|alert|auth|admin
  actor text, message text, meta jsonb
);
create index on logs (ts desc);

create table settings (key text primary key, value jsonb, updated_by text, updated_at timestamptz default now());

-- RLS on, no anon policies: only the backend (service role) reads/writes.
alter table profiles      enable row level security;
alter table zones         enable row level security;
alter table subscriptions enable row level security;
alter table runs          enable row level security;
alter table radar_frames  enable row level security;
alter table predictions   enable row level security;
alter table warnings      enable row level security;
alter table reports       enable row level security;
alter table logs          enable row level security;
alter table settings      enable row level security;

-- One latest row per zone, for /live/summary (PostgREST can't express DISTINCT ON).
create view latest_predictions with (security_invoker = true) as
  select distinct on (zone_id) * from predictions order by zone_id, ts desc;

-- D12: start a run unless one is running or started < p_min_gap_min ago.
-- Serialised with a transaction-level advisory lock, so pg_cron + GitHub backup can't both start.
-- Returns the new run id, or null if skipped. A 'running' row older than 5 min is treated as dead.
create or replace function start_run(p_min_gap_min int default 8, p_backfill_ts timestamptz default null)
returns uuid language plpgsql as $$
declare
  new_id uuid;
begin
  perform pg_advisory_xact_lock(hashtext('huda_start_run'));
  if p_backfill_ts is null and exists (
    select 1 from runs
    where backfill_ts is null
      and (started_at > now() - make_interval(mins => p_min_gap_min)
           or (status = 'running' and started_at > now() - interval '5 minutes'))
  ) then
    return null;
  end if;
  insert into runs (status, backfill_ts) values ('running', p_backfill_ts) returning id into new_id;
  return new_id;
end $$;
