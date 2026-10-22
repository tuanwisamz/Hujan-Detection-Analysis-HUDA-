-- Phase 2 additional features (implementation-plan-v2 §6.6): night mode, JPS sensors, sirens.
-- Run after 0001–0003. Safe to re-run.

-- Night mode (D24)
alter table profiles add column if not exists theme text not null default 'system'
  check (theme in ('system','light','dark'));

-- JPS Public InfoBanjir stations and readings (D20–D21)
create table if not exists sensor_stations (
  id text primary key,                 -- 'jps-rain:3717101' | 'jps-river:3516423'
  kind text not null check (kind in ('rain','river')),
  source text not null default 'infobanjir',
  station_code text not null,          -- JPS station ID as InfoBanjir shows it
  name text, district text, state text,
  lat double precision, lon double precision,
  location_quality text not null default 'grid' check (location_quality in ('grid','verified')),
  location_source text,                -- 'station_id' (0.1° cell) | 'datagovmy' | 'admin'
  active boolean not null default true, note text,
  updated_by text, updated_at timestamptz default now()
);

create table if not exists sensor_readings (
  station_id text references sensor_stations(id) on delete cascade,
  ts timestamptz not null,             -- the station's own timestamp (UTC)
  rain_1h_mm real, rain_today_mm real,
  water_level_m real, indicator text,  -- NORMAL | ALERT | WARNING | DANGER
  fetched_at timestamptz default now(),
  primary key (station_id, ts)
);
create index if not exists sensor_readings_ts on sensor_readings (ts desc);

-- Township sirens (D22–D23)
do $$ begin
  create type siren_status_t as enum ('pending_approval','active','stopped','expired','cancelled','failed');
exception when duplicate_object then null; end $$;

create table if not exists sirens (
  id uuid primary key default gen_random_uuid(),
  zone_id uuid references zones(id) not null,
  name text not null,
  endpoint_url text,                   -- null = virtual
  active boolean not null default true, note text,
  created_by text, created_at timestamptz default now()
);

create table if not exists siren_activations (
  id uuid primary key default gen_random_uuid(),
  siren_id uuid references sirens(id) not null,
  zone_id uuid references zones(id) not null,
  status siren_status_t not null,
  source text check (source in ('auto','manual','test')),
  rule text, reason text,
  created_at timestamptz default now(), approved_by text,
  started_at timestamptz, stopped_at timestamptz,
  stop_reason text check (stop_reason in ('level_drop','max_duration','admin','expired','failed')),
  last_error text
);
create index if not exists siren_activations_zone on siren_activations (zone_id, created_at desc);

alter table sensor_stations   enable row level security;
alter table sensor_readings   enable row level security;
alter table sirens            enable row level security;
alter table siren_activations enable row level security;

-- Retention: also drop sensor readings older than 30 days (replaces the 0003 job).
select cron.schedule('huda-retention', '30 19 * * *', $$
  delete from radar_frames where ts < now() - interval '3 days';
  delete from predictions  where ts < now() - interval '90 days';
  delete from sensor_readings where ts < now() - interval '30 days';
$$);
