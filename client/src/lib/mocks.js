// In-memory mock of the HUDA API (api-spec.md). Lets the frontend run with no backend:
// VITE_USE_MOCKS=true. State resets on reload.
import { ago, iso, REPORT_MD, seedLogs, seedPredictions, seedRuns, seedSensors, seedSirenActs, seedSirens, seedWarnings, SETTINGS, ZONES } from '../mocks/seed'
import { ApiError } from './api'

const state = {
  zones: structuredClone(ZONES),
  predictions: seedPredictions(),
  warnings: seedWarnings(),
  logs: seedLogs(),
  runs: seedRuns(),
  settings: structuredClone(SETTINGS),
  sensors: seedSensors(),
  sirens: seedSirens(),
  sirenActs: seedSirenActs(),
  subs: [{ zone_id: 'z01', min_level: 'AMBER' }, { zone_id: 'z02', min_level: 'AMBER' }],
  me: { id: 'user_demo', email: 'demo@huda.my', full_name: 'Demo User', language: 'en', theme: 'system', telegram_linked: false, onboarded: true },
  reports: [
    { id: 'r1', type: 'custom', zone_ids: null, period_start: ago(10080), period_end: ago(0), created_by: 'user_demo', created_at: ago(60), status: 'ready', content_md: REPORT_MD },
  ],
  conversations: {},
}

const delay = (ms) => new Promise((r) => setTimeout(r, ms))

// Mirrors server/app/services/alerts.py resolve_mode / automation_status.
const EVENTS = ['amber', 'red', 'all_clear', 'siren']
function automationStatus(s) {
  const a = s.automation
  const now = Date.now()
  const paused = !a.enabled || (!!a.paused_until && new Date(a.paused_until).getTime() > now)
  const q = a.quiet_hours
  const mins = (hhmm) => Number(hhmm.slice(0, 2)) * 60 + Number(hhmm.slice(3, 5))
  const myt = new Date(now + 8 * 3600000)
  const t = myt.getUTCHours() * 60 + myt.getUTCMinutes()
  const [start, end] = [mins(q.start), mins(q.end)]
  const quiet = q.enabled && (start < end ? t >= start && t < end : t >= start || t < end)
  const resolve = (e) => {
    const m = a.modes[e]
    if (m === 'auto' && (paused || (quiet && q.events.includes(e)))) return 'approval'
    return m
  }
  const current = ['amber', 'red', 'all_clear'].every((e) => a.modes[e] === 'off') ? 'off' : paused ? 'paused' : quiet && q.events.length ? 'quiet_hours' : 'active'
  return {
    state: current,
    paused_until: a.enabled && paused ? a.paused_until : null,
    quiet_now: quiet,
    effective: Object.fromEntries(EVENTS.map((e) => [e, resolve(e)])),
    zones_overridden: Object.keys(a.zone_overrides).length,
  }
}
const automationOut = () => ({
  automation: state.settings.automation,
  cooldown_min: state.settings.cooldown_min,
  all_clear_after_min: state.settings.all_clear_after_min,
  pipeline_enabled: state.settings.pipeline_enabled,
  status: automationStatus(state.settings),
  pending_count:
    state.warnings.filter((w) => w.status === 'pending_approval').length + state.sirenActs.filter((a) => a.status === 'pending_approval').length,
})
const role = () => {
  try {
    return localStorage.getItem('huda.mockRole') || 'admin'
  } catch {
    return 'admin'
  }
}
const zone = (id) => state.zones.find((z) => z.id === id || z.slug === id)
const live = (z) => {
  const p = state.predictions[z.id] || {}
  return {
    ...z,
    level: p.level ?? null,
    rain_rate_max: p.rain_rate_max ?? null,
    eta_min: p.eta_min ?? null,
    p_ml: p.p_ml ?? null,
    official_warning: p.official_warning ?? null,
    replay: false,
    sensor_check: p.explanation?.sensor_check ?? null,
    siren_active: state.sirenActs.some((a) => a.zone_id === z.id && a.status === 'active'),
    subscribed: state.subs.some((s) => s.zone_id === z.id),
    updated_at: p.ts ?? null,
  }
}
const activationOut = (a) => {
  const s = state.sirens.find((x) => x.id === a.siren_id)
  return { ...a, siren_name: s?.name, zone_name: zone(a.zone_id)?.name, virtual: !s?.endpoint_url }
}
const sirenOut = (s) => {
  const last = state.sirenActs.find((a) => a.siren_id === s.id)
  const st = last && ['pending_approval', 'active', 'failed'].includes(last.status) ? last.status : 'idle'
  return { ...s, zone_name: zone(s.zone_id)?.name, virtual: !s.endpoint_url, state: st, last_activation: last || null }
}
const warningOut = (w) => ({ ...w, zone: zone(w.zone_id)?.name, zone_slug: zone(w.zone_id)?.slug })
const log = (category, message, meta = {}) =>
  state.logs.unshift({ id: Date.now(), ts: iso(Date.now()), severity: 'info', category, actor: role() === 'admin' ? 'admin_demo' : 'user_demo', message, meta })
const requireAdmin = () => {
  if (role() !== 'admin') throw new ApiError(403, 'FORBIDDEN', 'Admin role required')
}

let radarCache = null
async function radarFrames() {
  if (!radarCache || Date.now() - radarCache.at > 60000) {
    try {
      const data = await (await fetch('https://api.rainviewer.com/public/weather-maps.json')).json()
      const observed = data.radar.past.map((f) => ({
        ts: iso(f.time * 1000),
        tile_url: `${data.host}${f.path}/256/{z}/{x}/{y}/2/1_1.png`,
        max_native_zoom: 7,
      }))
      radarCache = { at: Date.now(), observed }
    } catch {
      radarCache = { at: Date.now(), observed: [] }
    }
  }
  return { observed: radarCache.observed, nowcast: [], attribution: 'Weather radar by RainViewer' }
}

function timeseries(id, hours) {
  const p = state.predictions[id]
  const steps = hours * 6
  return Array.from({ length: steps }, (_, i) => {
    const m = (steps - 1 - i) * 10
    const t = i / steps
    const rate = p.level === 'RED' ? Math.max(0, 40 * t ** 3 + Math.sin(i) * 2) : p.level === 'AMBER' ? 18 * t ** 2 : Math.abs(Math.sin(i / 3)) * 1.5
    const level = rate >= 30 || (p.level === 'RED' && i > steps - 3) ? 'RED' : rate >= 10 ? 'AMBER' : 'GREEN'
    return { ts: ago(m + 3), level, rain_rate_max: +rate.toFixed(1), p_ml: +Math.min(0.95, (p.p_ml ?? 0.1) * (0.4 + t * 0.6)).toFixed(2) }
  })
}

function page(items, query) {
  const limit = Number(query.limit || 50)
  const offset = Number(query.cursor || 0)
  const slice = items.slice(offset, offset + limit)
  return { items: slice, next_cursor: offset + limit < items.length ? String(offset + limit) : null }
}

function chatReply(message) {
  const text = message.toLowerCase()
  const at = (id) => state.predictions[id]
  if (text.includes('which') || text.includes('mana') || text.includes('risk')) {
    const risky = state.zones.filter((z) => ['AMBER', 'RED'].includes(at(z.id)?.level))
    return {
      reply: `${risky.length} townships are at Moderate or High: ${risky.map((z) => `${z.name} (${at(z.id).level})`).join(', ')}. City of Elmina is highest — heavy rain expected in about 20 minutes.`,
      tool_calls: [{ name: 'get_zone_status', args: {} }],
    }
  }
  if (text.includes('met') || text.includes('warning') || text.includes('amaran')) {
    return { reply: 'Yes — MET Malaysia has an active thunderstorm warning covering Petaling. It applies to City of Elmina, Denai Alam, Bukit Jelutong and Bukit Subang.', tool_calls: [{ name: 'get_official_warnings', args: { zone: 'Petaling' } }] }
  }
  return {
    reply: 'Yes — radar shows a cell moving east; rain up to ~38 mm/h is expected over City of Elmina in about 20 minutes. Level: RED. Avoid underpasses and move vehicles to higher ground.',
    tool_calls: [
      { name: 'get_zone_status', args: { zone: 'city-of-elmina' } },
      { name: 'get_nowcast', args: { zone: 'city-of-elmina' } },
    ],
  }
}

const routes = [
  ['GET', /^\/health$/, () => ({ status: 'ok', last_run_at: state.runs[0].finished_at, last_run_status: 'ok', model_version: 'lgbm_v1' })],
  ['POST', /^\/me\/sync$/, () => ({ ...state.me, role: role() })],
  ['GET', /^\/me$/, () => ({ ...state.me, role: role() })],
  ['PATCH', /^\/me$/, (_m, _q, b) => Object.assign(state.me, b) && { ...state.me, role: role() }],
  ['GET', /^\/me\/subscriptions$/, () => ({ subscriptions: state.subs })],
  ['PUT', /^\/me\/subscriptions$/, (_m, _q, b) => ({ subscriptions: (state.subs = b.subscriptions) })],
  ['POST', /^\/me\/telegram\/link$/, () => {
    setTimeout(() => (state.me.telegram_linked = true), 4000)
    return { code: 'HUDA-7F3K2', deep_link: 'https://t.me/huda_alert_bot?start=HUDA-7F3K2', expires_at: ago(-15) }
  }],
  ['DELETE', /^\/me\/telegram\/link$/, () => {
    state.me.telegram_linked = false
    return null
  }],
  ['GET', /^\/live\/summary$/, () => {
    const zones = state.zones.filter((z) => z.active).map(live).sort((a, b) => b.subscribed - a.subscribed || a.name.localeCompare(b.name))
    const counts = { GREEN: 0, AMBER: 0, RED: 0 }
    zones.forEach((z) => z.level && counts[z.level]++)
    return { generated_at: iso(Date.now()), data_status: { radar: 'ok', open_meteo: 'ok', met_warnings: 'ok' }, counts, zones }
  }],
  ['GET', /^\/radar\/frames$/, () => radarFrames()],
  ['GET', /^\/zones$/, (_m, q) => ({ items: state.zones.filter((z) => (q.active === 'all' ? true : q.active === 'false' ? !z.active : z.active)) })],
  ['GET', /^\/zones\/([^/]+)$/, ([id]) => {
    const z = zone(id)
    if (!z) throw new ApiError(404, 'NOT_FOUND', 'Zone not found')
    return { ...z, latest: state.predictions[z.id], sensors: state.predictions[z.id]?.explanation?.sensors || [], siren_active: state.sirenActs.some((a) => a.zone_id === z.id && a.status === 'active') }
  }],
  ['GET', /^\/zones\/([^/]+)\/timeseries$/, ([id], q) => timeseries(zone(id).id, Number(q.hours || 6))],
  ['GET', /^\/alerts$/, (_m, q) => {
    const ids = state.subs.map((s) => s.zone_id)
    const items = state.warnings.filter((w) => w.status === 'sent' && (role() === 'admin' || ids.includes(w.zone_id))).map(warningOut)
    return page(items, q)
  }],
  ['GET', /^\/logs$/, (_m, q) => page(state.logs.filter((l) => l.category === 'alert' && state.subs.some((s) => s.zone_id === l.meta?.zone_id)), q)],
  ['POST', /^\/admin\/zones$/, (_m, _q, b) => {
    requireAdmin()
    const z = { id: `z${Date.now()}`, ...b }
    state.zones.push(z)
    state.predictions[z.id] = { ts: iso(Date.now()), zone_id: z.id, level: 'GREEN', rain_rate_max: 0, eta_min: null, p_ml: 0.05, explanation: { rule: null, rules_fired: [], top_features: [] } }
    log('admin', `zone created: ${z.name}`)
    return z
  }],
  ['PATCH', /^\/admin\/zones\/([^/]+)$/, ([id], _q, b) => {
    requireAdmin()
    const z = zone(id)
    Object.assign(z, b)
    log('admin', `zone updated: ${z.name}`)
    return z
  }],
  ['DELETE', /^\/admin\/zones\/([^/]+)$/, ([id]) => {
    requireAdmin()
    const z = zone(id)
    z.active = false
    log('admin', `zone deactivated: ${z.name}`)
    return z
  }],
  ['GET', /^\/admin\/warnings$/, (_m, q) => {
    requireAdmin()
    return { items: state.warnings.filter((w) => !q.status || w.status === q.status).map(warningOut) }
  }],
  ['POST', /^\/admin\/warnings$/, (_m, _q, b) => {
    requireAdmin()
    const w = { id: `w${Date.now()}`, zone_id: b.zone_id, level: b.level, status: 'draft', source: 'manual', message_en: b.message_en || null, message_ms: b.message_ms || null, created_by: 'admin_demo', created_at: iso(Date.now()), sent_at: null, expires_at: ago(-(b.expires_in_min || 120)), telegram_message_id: null }
    state.warnings.unshift(w)
    log('admin', `manual ${b.level} warning drafted`)
    return w
  }],
  ['PATCH', /^\/admin\/warnings\/([^/]+)$/, ([id], _q, b) => {
    requireAdmin()
    const w = state.warnings.find((x) => x.id === id)
    Object.assign(w, { message_en: b.message_en, message_ms: b.message_ms })
    return warningOut(w)
  }],
  ['POST', /^\/admin\/warnings\/([^/]+)\/generate-text$/, async ([id]) => {
    requireAdmin()
    await delay(900)
    const w = state.warnings.find((x) => x.id === id)
    const p = state.predictions[w.zone_id]
    const rate = Math.round(p.rain_rate_max ?? 0)
    Object.assign(w, w.level === 'RED'
      ? { message_en: `Intense rain (~${rate} mm/h) expected in ~${p.eta_min ?? 20} min. Avoid underpasses and low roads.`, message_ms: `Hujan lebat (~${rate} mm/j) dijangka dalam ~${p.eta_min ?? 20} minit. Elakkan laluan bawah tanah.` }
      : { message_en: `Heavy rain (~${rate} mm/h) possible in ~${p.eta_min ?? 30} min. Drive slowly and avoid flood-prone roads.`, message_ms: `Hujan lebat (~${rate} mm/j) mungkin dalam ~${p.eta_min ?? 30} minit. Pandu perlahan.` })
    return { ...warningOut(w), fallback: false }
  }],
  ['POST', /^\/admin\/warnings\/([^/]+)\/approve$/, async ([id]) => {
    requireAdmin()
    await delay(600)
    const w = state.warnings.find((x) => x.id === id)
    Object.assign(w, { status: 'sent', sent_at: iso(Date.now()), last_broadcast_at: iso(Date.now()), approved_by: 'admin_demo', telegram_message_id: 4500 + Math.floor(Math.random() * 99) })
    log('alert', `${w.level} sent for ${zone(w.zone_id).name}`, { zone_id: w.zone_id })
    return { id: w.id, status: w.status, telegram_message_id: w.telegram_message_id, sent_at: w.sent_at }
  }],
  ['POST', /^\/admin\/warnings\/([^/]+)\/cancel$/, ([id]) => {
    requireAdmin()
    const w = state.warnings.find((x) => x.id === id)
    w.status = 'cancelled'
    log('admin', `warning cancelled: ${zone(w.zone_id).name}`)
    return warningOut(w)
  }],
  ['POST', /^\/admin\/warnings\/([^/]+)\/rebroadcast$/, ([id]) => {
    requireAdmin()
    const w = state.warnings.find((x) => x.id === id)
    if (Date.now() - new Date(w.last_broadcast_at || w.sent_at).getTime() < 5 * 60000) {
      throw new ApiError(429, 'RATE_LIMITED', 'Re-broadcast allowed once every 5 min')
    }
    w.last_broadcast_at = iso(Date.now())
    return warningOut(w)
  }],
  ['GET', /^\/admin\/logs$/, (_m, q) => {
    requireAdmin()
    return page(state.logs.filter((l) => (!q.category || l.category === q.category) && (!q.severity || l.severity === q.severity) && (!q.q || l.message.toLowerCase().includes(q.q.toLowerCase()))), q)
  }],
  ['GET', /^\/admin\/sensors$/, (_m, q) => {
    requireAdmin()
    let items = state.sensors
    if (q.kind) items = items.filter((s) => s.kind === q.kind)
    if (q.zone_id) items = items.filter((s) => s.zones.some((z) => z.id === q.zone_id))
    if (q.needs_location) items = items.filter((s) => s.location_quality !== 'verified' && s.zones.length)
    if (q.stale) items = items.filter((s) => !s.latest?.fresh)
    const pages = { 'rain:SEL': 'ok', 'river:SEL': 'ok', 'rain:WLH': 'ok', 'river:WLH': 'ok', 'rain:NSN': 'ok', 'river:NSN': 'ok', 'rain:JHR': 'failed', 'river:JHR': 'ok' }
    return { sources: { status: 'partial', pages, checked_at: ago(4) }, items }
  }],
  ['PATCH', /^\/admin\/sensors\/([^/]+)$/, ([id], _q, b) => {
    requireAdmin()
    const s = state.sensors.find((x) => x.id === decodeURIComponent(id))
    if (!s) throw new ApiError(404, 'NOT_FOUND', 'Station not found')
    Object.assign(s, b, b.lat != null ? { location_quality: 'verified', location_source: 'admin' } : {})
    log('admin', `sensor station updated: ${s.name}`, { station_id: s.id })
    return s
  }],
  ['GET', /^\/admin\/sirens$/, () => {
    requireAdmin()
    return { items: state.sirens.map(sirenOut) }
  }],
  ['POST', /^\/admin\/sirens$/, (_m, _q, b) => {
    requireAdmin()
    if (!zone(b.zone_id)) throw new ApiError(422, 'VALIDATION_ERROR', 'Unknown zone')
    const s = { ...b, id: `s${Date.now()}`, created_at: iso(Date.now()) }
    state.sirens.push(s)
    log('admin', `siren added: ${s.name}`, { siren_id: s.id })
    return s
  }],
  ['PATCH', /^\/admin\/sirens\/([^/]+)$/, ([id], _q, b) => {
    requireAdmin()
    const s = state.sirens.find((x) => x.id === id)
    if (!s) throw new ApiError(404, 'NOT_FOUND', 'Siren not found')
    Object.assign(s, b)
    log('admin', `siren updated: ${s.name}`, { siren_id: id })
    return s
  }],
  ['POST', /^\/admin\/sirens\/([^/]+)\/test$/, async ([id]) => {
    requireAdmin()
    await delay(400)
    const s = state.sirens.find((x) => x.id === id)
    log('admin', `siren test sent: ${s.name}`, { siren_id: id })
    return s.endpoint_url ? { ok: true, status_code: 200, latency_ms: 180 } : { ok: true, virtual: true }
  }],
  ['POST', /^\/admin\/sirens\/([^/]+)\/sound$/, ([id], _q, b) => {
    requireAdmin()
    const s = state.sirens.find((x) => x.id === id)
    if (state.sirenActs.some((a) => a.siren_id === id && a.status === 'active')) throw new ApiError(409, 'CONFLICT', 'This siren is already sounding')
    const a = { id: `a${Date.now()}`, siren_id: id, zone_id: s.zone_id, status: 'active', source: 'manual', reason: b.reason, created_at: iso(Date.now()), started_at: iso(Date.now()) }
    state.sirenActs.unshift(a)
    log('siren', `siren sounding: ${s.name}`, { siren_id: id })
    return a
  }],
  ['GET', /^\/admin\/siren-activations$/, (_m, q) => {
    requireAdmin()
    const items = state.sirenActs.filter((a) => (!q.status || a.status === q.status) && (!q.zone_id || a.zone_id === q.zone_id))
    return { items: items.slice(0, Number(q.limit || 50)).map(activationOut) }
  }],
  ['POST', /^\/admin\/siren-activations\/([^/]+)\/(approve|stop|cancel)$/, ([id, action]) => {
    requireAdmin()
    const a = state.sirenActs.find((x) => x.id === id)
    if (!a) throw new ApiError(404, 'NOT_FOUND', 'Siren activation not found')
    const need = action === 'stop' ? 'active' : 'pending_approval'
    if (a.status !== need) throw new ApiError(409, 'CONFLICT', `Activation is ${a.status}, not ${need}`)
    const now = iso(Date.now())
    if (action === 'approve') Object.assign(a, { status: 'active', started_at: now, approved_by: 'admin_demo' })
    if (action === 'stop') Object.assign(a, { status: 'stopped', stopped_at: now, stop_reason: 'admin' })
    if (action === 'cancel') Object.assign(a, { status: 'cancelled', stopped_at: now })
    log('siren', `siren ${action}: ${state.sirens.find((s) => s.id === a.siren_id)?.name}`, { activation_id: id })
    return a
  }],
  ['GET', /^\/admin\/runs$/, () => (requireAdmin(), { items: state.runs })],
  ['GET', /^\/admin\/settings$/, () => (requireAdmin(), state.settings)],
  ['PATCH', /^\/admin\/settings$/, (_m, _q, b) => {
    requireAdmin()
    const next = { ...state.settings, ...b, thresholds: { ...state.settings.thresholds, ...(b.thresholds || {}) } }
    const t = next.thresholds
    if (t.amber_rate_mmh >= t.red_rate_mmh || t.amber_p >= t.red_p) throw new ApiError(422, 'VALIDATION_ERROR', 'thresholds: amber must be less than red')
    if (t.red_rate_mmh >= t.very_heavy_mmh) throw new ApiError(422, 'VALIDATION_ERROR', 'thresholds: red_rate_mmh must be less than very_heavy_mmh')
    if (t.gauge_amber_1h_mm >= t.gauge_red_1h_mm) throw new ApiError(422, 'VALIDATION_ERROR', 'thresholds: gauge amber must be less than gauge red')
    state.settings = next
    log('admin', 'settings updated', { fields: Object.keys(b) })
    return next
  }],
  ['GET', /^\/admin\/automation$/, () => (requireAdmin(), automationOut())],
  ['PATCH', /^\/admin\/automation$/, (_m, _q, b) => {
    requireAdmin()
    const a = structuredClone(state.settings.automation)
    const { modes, quiet_hours, resume, pause_minutes, cooldown_min, all_clear_after_min, ...rest } = b
    if (modes) Object.assign(a.modes, modes)
    if (quiet_hours) Object.assign(a.quiet_hours, quiet_hours)
    if (a.quiet_hours.start === a.quiet_hours.end) throw new ApiError(422, 'VALIDATION_ERROR', 'quiet hours start and end must differ')
    Object.assign(a, rest)
    if (resume || rest.enabled === true) Object.assign(a, { enabled: true, paused_until: null })
    if (pause_minutes) Object.assign(a, { enabled: true, paused_until: iso(Date.now() + pause_minutes * 60000) })
    state.settings = {
      ...state.settings,
      automation: a,
      amber_requires_approval: a.modes.amber === 'approval',
      ...(cooldown_min != null && { cooldown_min }),
      ...(all_clear_after_min != null && { all_clear_after_min }),
    }
    log('admin', resume ? 'automation resumed' : pause_minutes ? `automation paused for ${pause_minutes} min` : rest.enabled === false ? 'automation paused until resumed' : 'automation settings updated')
    return automationOut()
  }],
  ['POST', /^\/admin\/automation\/test$/, async () => {
    requireAdmin()
    await delay(500)
    const id = 4600 + Math.floor(Math.random() * 99)
    log('admin', 'automation test message sent', { telegram_message_id: id })
    return { telegram_message_id: id, sent_at: iso(Date.now()) }
  }],
  ['GET', /^\/admin\/users$/, () => ({ items: [{ id: 'user_demo', email: 'demo@huda.my', full_name: 'Demo User', role: role() }] })],
  ['GET', /^\/reports$/, () => ({ items: state.reports.map((r) => Object.fromEntries(Object.entries(r).filter(([k]) => k !== 'content_md'))) })],
  ['POST', /^\/reports$/, (_m, _q, b) => {
    const r = { id: `r${Date.now()}`, ...b, created_by: 'user_demo', created_at: iso(Date.now()), status: 'generating', content_md: null }
    state.reports.unshift(r)
    setTimeout(() => Object.assign(r, { status: 'ready', content_md: REPORT_MD }), 2500)
    return { id: r.id, status: 'generating' }
  }],
  ['GET', /^\/reports\/([^/]+)$/, ([id]) => state.reports.find((r) => r.id === id)],
  ['GET', /^\/reports\/([^/]+)\/download$/, ([id], q) => {
    const r = state.reports.find((x) => x.id === id)
    return q.format === 'csv'
      ? 'zone,runs,amber_runs,red_runs,alerts_sent,peak_rain_rate_mmh,peak_p_ml\nCity of Elmina,1008,14,6,1,38.4,0.81\n'
      : r.content_md
  }],
  ['POST', /^\/agent\/chat$/, async (_m, _q, b) => {
    await delay(1100)
    return { conversation_id: b.conversation_id || 'c-demo', model: 'gemini-flash (mock)', ...chatReply(b.message) }
  }],
]

export async function mockFetch(method, path, query, body) {
  await delay(150)
  for (const [m, re, handler] of routes) {
    const match = m === method && path.match(re)
    if (match) return structuredClone(await handler(match.slice(1), query, body))
  }
  throw new ApiError(404, 'NOT_FOUND', `Mock has no route for ${method} ${path}`)
}
