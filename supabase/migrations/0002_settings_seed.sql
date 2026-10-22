-- Default settings (api-spec.md §9). amber_p / red_p get replaced by the
-- validation-chosen cut-offs once the classifier is trained (implementation-plan §5.6 step 7).

insert into settings (key, value, updated_by) values
  ('thresholds', '{"amber_rate_mmh": 10, "red_rate_mmh": 30, "amber_p": 0.4, "red_p": 0.7, "wet_ground_mm24h": 50,
    "red_area_frac": 0.2, "red_duration_min": 30, "red_accum_1h_mm": 40,
    "very_heavy_mmh": 60, "very_heavy_area_frac": 0.1, "very_heavy_duration_min": 20,
    "gauge_amber_1h_mm": 31, "gauge_red_1h_mm": 60, "gauge_red_3h_mm": 60, "sensor_confirm_1h_mm": 11}', 'seed'),
  ('cooldown_min', '30', 'seed'),
  ('amber_requires_approval', 'false', 'seed'),
  ('all_clear_after_min', '30', 'seed'),
  ('pipeline_enabled', 'true', 'seed')
on conflict (key) do nothing;

-- Storage buckets: public nowcast PNGs, private storm archive (D2).
insert into storage.buckets (id, name, public) values
  ('radar', 'radar', true),
  ('radar-archive', 'radar-archive', false)
on conflict (id) do nothing;
