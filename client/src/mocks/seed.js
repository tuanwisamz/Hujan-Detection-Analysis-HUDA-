// Mock seed data, shaped exactly like api-spec.md responses. Used when VITE_USE_MOCKS=true.

const MIN = 60000
export const now = () => new Date()
export const iso = (d) => new Date(d).toISOString()
export const ago = (m) => iso(Date.now() - m * MIN)

// spec §5 townships (approximate coordinates)
export const ZONES = [
  ['City of Elmina', 'city-of-elmina', 'Selangor', 'Petaling', 3.183, 101.486],
  ['Denai Alam', 'denai-alam', 'Selangor', 'Petaling', 3.14, 101.495],
  ['Bukit Jelutong', 'bukit-jelutong', 'Selangor', 'Petaling', 3.105, 101.531],
  ['Bukit Subang', 'bukit-subang', 'Selangor', 'Petaling', 3.16, 101.52],
  ['Ara Damansara', 'ara-damansara', 'Selangor', 'Petaling', 3.117, 101.582],
  ['KLGCC Resort', 'klgcc-resort', 'Kuala Lumpur', 'Kuala Lumpur', 3.155, 101.625],
  ['Bandar Bukit Raja', 'bandar-bukit-raja', 'Selangor', 'Klang', 3.09, 101.43],
  ['Putra Heights', 'putra-heights', 'Selangor', 'Petaling', 2.996, 101.573],
  ['USJ Heights', 'usj-heights', 'Selangor', 'Petaling', 3.046, 101.574],
  ['Serenia City', 'serenia-city', 'Selangor', 'Sepang', 2.87, 101.69],
  ['Saujana Impian', 'saujana-impian', 'Selangor', 'Hulu Langat', 2.99, 101.795],
  ['Nilai Impian', 'nilai-impian', 'Negeri Sembilan', 'Seremban', 2.81, 101.77],
  ['Bandar Ainsdale', 'bandar-ainsdale', 'Negeri Sembilan', 'Seremban', 2.7, 101.93],
  ['Bandar Universiti Pagoh', 'bandar-universiti-pagoh', 'Johor', 'Muar', 2.15, 102.73],
  ['Taman Pasir Putih', 'taman-pasir-putih', 'Johor', 'Johor Bahru', 1.47, 103.89],
].map(([name, slug, state, district, lat, lon], i) => ({
  id: `z${String(i + 1).padStart(2, '0')}`,
  name,
  slug,
  state,
  district,
  met_location_id: null,
  match_terms: [],
  lat,
  lon,
  radius_m: 2500,
  polygon: null,
  active: true,
}))

const RED = {
  level: 'RED',
  rain_rate_max: 38.4,
  eta_min: 20,
  accum_1h: 12.1,
  accum_24h: 54.0,
  p_ml: 0.81,
  official_warning: 'Thunderstorm warning – Petaling',
  explanation: {
    rule: 'nowcast_rate>=30',
    rules_fired: ['nowcast_rate>=30', 'p_ml>=0.70', 'met_warning'],
    wet_ground_bump: true,
    top_features: [
      ['fcst_precip_3h', 0.31],
      ['cape', 0.22],
      ['precip_lag_3h', 0.12],
    ],
  },
}
const amber = (rate, eta, p) => ({
  level: 'AMBER',
  rain_rate_max: rate,
  eta_min: eta,
  accum_1h: rate / 3,
  accum_24h: 21,
  p_ml: p,
  official_warning: 'Thunderstorm warning – Petaling',
  explanation: { rule: 'nowcast_rate>=10', rules_fired: ['nowcast_rate>=10', 'met_warning'], wet_ground_bump: false, top_features: [['cape', 0.18], ['rh', 0.09], ['hour_sin', 0.05]] },
})
const green = (p) => ({
  level: 'GREEN',
  rain_rate_max: 0.4,
  eta_min: null,
  accum_1h: 0.1,
  accum_24h: 3.2,
  p_ml: p,
  official_warning: null,
  explanation: { rule: null, rules_fired: [], wet_ground_bump: false, top_features: [['precip_lag_24h', -0.12], ['cape', -0.08], ['month_cos', 0.03]] },
})

export function seedPredictions() {
  const ts = ago(3)
  const special = { z01: RED, z02: amber(22.5, 30, 0.52), z03: amber(14.2, 40, 0.44), z04: amber(11.0, 50, 0.31) }
  return Object.fromEntries(ZONES.map((z, i) => [z.id, { ts, zone_id: z.id, ...(special[z.id] || green(0.04 + (i % 5) * 0.03)) }]))
}

export function seedWarnings() {
  const z = (id) => ZONES.find((x) => x.id === id)
  const w = (id, zoneId, level, status, source, minutesAgo, extra = {}) => ({
    id,
    zone_id: zoneId,
    level,
    status,
    source,
    message_en: null,
    message_ms: null,
    created_by: 'system',
    approved_by: null,
    created_at: ago(minutesAgo),
    sent_at: status === 'sent' ? ago(minutesAgo - 1) : null,
    last_broadcast_at: status === 'sent' ? ago(minutesAgo - 1) : null,
    expires_at: ago(minutesAgo - 120),
    telegram_message_id: status === 'sent' ? 4400 + minutesAgo : null,
    zones: { name: z(zoneId).name, slug: z(zoneId).slug },
    ...extra,
  })
  return [
    w('w1', 'z01', 'RED', 'sent', 'auto', 4, {
      message_en: 'Intense rain (~38 mm/h) expected in ~20 min. Flash floods likely in low-lying roads. Avoid underpasses; move vehicles to higher ground.',
      message_ms: 'Hujan lebat (~38 mm/j) dijangka dalam ~20 minit. Banjir kilat mungkin berlaku. Elakkan laluan bawah tanah; alihkan kenderaan ke tempat tinggi.',
    }),
    w('w2', 'z02', 'AMBER', 'pending_approval', 'auto', 6),
    w('w3', 'z03', 'AMBER', 'pending_approval', 'agent', 9, { created_by: 'admin_demo' }),
    w('w4', 'z07', 'RED', 'sent', 'auto', 1440 * 2),
    w('w5', 'z07', 'GREEN', 'sent', 'auto', 1440 * 2 - 70),
    w('w6', 'z10', 'AMBER', 'cancelled', 'manual', 1440 * 3),
  ]
}

export function seedLogs() {
  const rows = []
  let id = 9000
  for (let m = 2; m < 240; m += 10) {
    rows.push({ id: id++, ts: ago(m), severity: 'info', category: 'ingest', actor: 'system', message: `run ok in ${(38 + (m % 7) * 3.1).toFixed(1)} s`, meta: {} })
  }
  rows.push({ id: id++, ts: ago(32), severity: 'warn', category: 'ingest', actor: 'system', message: 'data.gov.my warning fetch timed out', meta: { retry: 2 } })
  rows.push({ id: id++, ts: ago(4), severity: 'info', category: 'alert', actor: 'system', message: 'RED sent for City of Elmina', meta: { zone_id: 'z01', warning_id: 'w1' } })
  rows.push({ id: id++, ts: ago(6), severity: 'info', category: 'alert', actor: 'system', message: 'raise AMBER for Denai Alam (amber requires approval)', meta: { zone_id: 'z02' } })
  rows.push({ id: id++, ts: ago(5), severity: 'info', category: 'agent', actor: 'system', message: 'alert_writer: gemini ok', meta: { latency_ms: 1840 } })
  rows.push({ id: id++, ts: ago(2880), severity: 'info', category: 'alert', actor: 'system', message: 'RED sent for Bandar Bukit Raja', meta: { zone_id: 'z07' } })
  rows.push({ id, ts: ago(1500), severity: 'info', category: 'admin', actor: 'admin_demo', message: 'settings updated', meta: { fields: ['cooldown_min'] } })
  return rows.sort((a, b) => (a.ts < b.ts ? 1 : -1))
}

export function seedRuns() {
  return Array.from({ length: 30 }, (_, i) => {
    const started = Date.now() - (i * 10 + 3) * MIN
    const degraded = i === 3
    return {
      id: `run-${i}`,
      started_at: iso(started),
      finished_at: iso(started + 41000 + (i % 5) * 3000),
      duration_s: 41 + (i % 5) * 3,
      status: degraded ? 'degraded' : 'ok',
      backfill_ts: null,
      error: null,
      sources: { mode: 'live', radar: 'ok', open_meteo: 'ok', met_warnings: degraded ? 'failed' : 'ok', nowcast: 'ok', nowcast_method: 'pysteps_lk', model: 'lgbm_v1', alerts: 'ok' },
    }
  })
}

export const SETTINGS = {
  thresholds: { amber_rate_mmh: 10, red_rate_mmh: 30, amber_p: 0.4, red_p: 0.7, wet_ground_mm24h: 50 },
  cooldown_min: 30,
  amber_requires_approval: true,
  all_clear_after_min: 30,
  pipeline_enabled: true,
}

export const REPORT_MD = `# HUDA Report

**Period:** 11 Oct 2026 00:00 – 18 Oct 2026 00:00 MYT

Rain risk was concentrated in Petaling district this week. City of Elmina spent the most time at High, with one RED alert sent, and Denai Alam and Bukit Jelutong reached Moderate during afternoon storms. Townships in Johor and Negeri Sembilan stayed Low throughout.

**Alerts sent:** 3 (2 RED) · **Zones reaching RED:** 2

| Zone | Runs | AMBER runs | RED runs | Alerts sent | Peak rain rate (mm/h) | Peak ML probability |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| City of Elmina | 1008 | 14 | 6 | 1 | 38.4 | 0.81 |
| Bandar Bukit Raja | 1008 | 9 | 3 | 1 | 33.0 | 0.72 |
| Denai Alam | 1008 | 11 | 0 | 0 | 22.5 | 0.52 |
| Bukit Jelutong | 1008 | 6 | 0 | 0 | 14.2 | 0.44 |

_Weather radar by RainViewer · Weather data by Open-Meteo.com (CC BY 4.0) · MET Malaysia via data.gov.my_`
