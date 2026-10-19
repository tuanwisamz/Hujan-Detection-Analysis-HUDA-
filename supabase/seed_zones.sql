-- 15 Sime Darby Property townships (spec.md §5).
-- !! Coordinates and districts are APPROXIMATE. Verify against official township
-- boundaries before the demo. met_location_id (data.gov.my "Ds..." district codes)
-- must be looked up from https://api.data.gov.my/weather/forecast and filled in.

insert into zones (name, slug, state, district, met_location_id, match_terms, lat, lon) values
  ('City of Elmina',          'city-of-elmina',          'Selangor',        'Petaling',     null, '{"Shah Alam"}',             3.183, 101.486),
  ('Denai Alam',              'denai-alam',              'Selangor',        'Petaling',     null, '{"Shah Alam"}',             3.140, 101.495),
  ('Bukit Jelutong',          'bukit-jelutong',          'Selangor',        'Petaling',     null, '{"Shah Alam"}',             3.105, 101.531),
  ('Bukit Subang',            'bukit-subang',            'Selangor',        'Petaling',     null, '{"Shah Alam","Subang"}',    3.160, 101.520),
  ('Ara Damansara',           'ara-damansara',           'Selangor',        'Petaling',     null, '{"Petaling Jaya"}',         3.117, 101.582),
  ('KLGCC Resort',            'klgcc-resort',            'Kuala Lumpur',    'Kuala Lumpur', null, '{"WP Kuala Lumpur"}',       3.155, 101.625),
  ('Bandar Bukit Raja',       'bandar-bukit-raja',       'Selangor',        'Klang',        null, '{}',                        3.090, 101.430),
  ('Putra Heights',           'putra-heights',           'Selangor',        'Petaling',     null, '{"Subang Jaya"}',           2.996, 101.573),
  ('USJ Heights',             'usj-heights',             'Selangor',        'Petaling',     null, '{"Subang Jaya"}',           3.046, 101.574),
  ('Serenia City',            'serenia-city',            'Selangor',        'Sepang',       null, '{}',                        2.870, 101.690),
  ('Saujana Impian',          'saujana-impian',          'Selangor',        'Hulu Langat',  null, '{"Kajang"}',                2.990, 101.795),
  ('Nilai Impian',            'nilai-impian',            'Negeri Sembilan', 'Seremban',     null, '{"Nilai"}',                 2.810, 101.770),
  ('Bandar Ainsdale',         'bandar-ainsdale',         'Negeri Sembilan', 'Seremban',     null, '{}',                        2.700, 101.930),
  ('Bandar Universiti Pagoh', 'bandar-universiti-pagoh', 'Johor',           'Muar',         null, '{"Pagoh"}',                 2.150, 102.730),
  ('Taman Pasir Putih',       'taman-pasir-putih',       'Johor',           'Johor Bahru',  null, '{"Pasir Gudang"}',          1.470, 103.890)
on conflict (slug) do nothing;
