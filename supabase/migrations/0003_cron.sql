-- pg_cron jobs. pg_cron runs in UTC; MYT = UTC+8.
-- Before running: enable the pg_cron and pg_net extensions, store the secret in Vault,
-- and set the backend host (live: hujan-detection-analysis-huda.onrender.com on Render):
--   select vault.create_secret('<CRON_SECRET value>', 'cron_secret');

create extension if not exists pg_cron;
create extension if not exists pg_net;

-- Every 10 min: pipeline run (also keeps the Render free instance awake).
select cron.schedule('huda-ingest', '*/10 * * * *', $$
  select net.http_post(
    url     := 'https://hujan-detection-analysis-huda.onrender.com/api/v1/internal/ingest',
    headers := jsonb_build_object(
      'Content-Type', 'application/json',
      'X-Cron-Secret', (select decrypted_secret from vault.decrypted_secrets where name = 'cron_secret')),
    body    := '{}'::jsonb);
$$);

-- 08:00 MYT = 00:00 UTC: daily report.
select cron.schedule('huda-daily-report', '0 0 * * *', $$
  select net.http_post(
    url     := 'https://hujan-detection-analysis-huda.onrender.com/api/v1/internal/daily-report',
    headers := jsonb_build_object(
      'Content-Type', 'application/json',
      'X-Cron-Secret', (select decrypted_secret from vault.decrypted_secrets where name = 'cron_secret')),
    body    := '{}'::jsonb);
$$);

-- 03:30 MYT: retention (architecture.md §6). Nowcast PNGs are pruned by the backend (D9).
select cron.schedule('huda-retention', '30 19 * * *', $$
  delete from radar_frames where ts < now() - interval '3 days';
  delete from predictions  where ts < now() - interval '90 days';
$$);
