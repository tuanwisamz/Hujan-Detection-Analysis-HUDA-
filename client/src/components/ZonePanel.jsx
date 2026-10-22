import { Bell, BellRing, X } from 'lucide-react'
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { useSubscriptions, usePutSubscriptions, useTimeseries, useZone } from '../hooks/queries'
import { level } from '../lib/levels'
import { describeRule } from '../lib/rules'
import { useT } from '../lib/i18n'
import { formatTime } from '../lib/time'
import RiskBadge from './RiskBadge'
import { ErrorNote, Loading, useToast } from './ui'

const FEATURE_LABELS = {
  fcst_precip_3h: 'Forecast rain, next 3 h',
  fcst_precip_1h: 'Forecast rain, next 1 h',
  precip_lag_1h: 'Rain, past 1 h',
  precip_lag_3h: 'Rain, past 3 h',
  precip_lag_6h: 'Rain, past 6 h',
  precip_lag_24h: 'Rain, past 24 h',
  cape: 'Storm energy (CAPE)',
  rh: 'Humidity',
  dewpoint_depression: 'Dew-point spread',
  surface_pressure: 'Air pressure',
  pressure_tendency_3h: 'Pressure change, 3 h',
  cloud_cover_low: 'Low cloud',
  cloud_cover_mid: 'Mid cloud',
  wind_speed_10m: 'Wind speed',
  hour_sin: 'Time of day',
  hour_cos: 'Time of day',
  month_sin: 'Season',
  month_cos: 'Season',
  monsoon: 'Monsoon phase',
}

function Stat({ label, children }) {
  return (
    <div className="rounded-lg bg-paper px-3 py-2.5">
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="mt-0.5 text-lg font-bold tabular">{children}</dd>
    </div>
  )
}

function FollowButton({ zoneId }) {
  const { t } = useT()
  const toast = useToast()
  const subs = useSubscriptions()
  const put = usePutSubscriptions()
  const list = subs.data?.subscriptions || []
  const following = list.some((s) => s.zone_id === zoneId)
  const toggle = () => {
    const next = following ? list.filter((s) => s.zone_id !== zoneId) : [...list, { zone_id: zoneId, min_level: 'AMBER' }]
    put.mutate(next, { onSuccess: () => toast(t('zones.saved')), onError: (e) => toast(e.message, 'error') })
  }
  return (
    <button
      type="button"
      onClick={toggle}
      disabled={put.isPending || subs.isLoading}
      aria-pressed={following}
      className={`inline-flex min-h-11 items-center gap-2 rounded-lg px-4 text-sm font-semibold ${
        following ? 'bg-primary/10 text-primary' : 'bg-primary text-white hover:bg-primary-strong'
      }`}
    >
      {following ? <BellRing size={16} aria-hidden="true" /> : <Bell size={16} aria-hidden="true" />}
      {following ? t('zones.following') : t('zone.follow')}
    </button>
  )
}

export default function ZonePanel({ zoneId, onClose, thresholds }) {
  const { t, lang } = useT()
  const zone = useZone(zoneId)
  const series = useTimeseries(zoneId, 6)
  const z = zone.data
  const p = z?.latest || {}
  const l = level(p.level)
  const ex = p.explanation || {}
  const amber = thresholds?.amber_rate_mmh ?? 10
  const red = thresholds?.red_rate_mmh ?? 30

  return (
    <aside
      aria-label={z?.name}
      className="flex max-h-full flex-col overflow-hidden rounded-t-2xl border border-line bg-surface shadow-xl lg:rounded-2xl"
    >
      <div className="h-1.5 shrink-0" style={{ background: l.color }} />
      <div className="flex items-start justify-between gap-3 px-5 pt-4">
        <div className="min-w-0">
          <h2 className="truncate text-xl font-bold">{z?.name || '…'}</h2>
          {z && (
            <p className="text-sm text-muted">
              {z.district}, {z.state}
            </p>
          )}
        </div>
        <button type="button" onClick={onClose} className="-mr-2 rounded-lg p-2 text-muted hover:bg-paper hover:text-ink" aria-label={t('zone.close')}>
          <X size={22} aria-hidden="true" />
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-5 pb-5 pt-3">
        {zone.isLoading && <Loading />}
        {zone.error && <ErrorNote error={zone.error} onRetry={zone.refetch} />}
        {z && (
          <>
            {/* Zone → Level → Action */}
            <div className="rounded-xl p-4" style={{ background: l.soft }}>
              <RiskBadge value={p.level} size="lg" />
              {p.level && (
                <>
                  <p className="mt-2 font-semibold">{t(`level.${p.level}.meaning`)}</p>
                  <p className="mt-1 text-sm">{t(`level.${p.level}.action`)}</p>
                </>
              )}
            </div>

            <dl className="mt-4 grid grid-cols-2 gap-2">
              <Stat label={t('zone.eta')}>
                {p.eta_min == null ? <span className="text-base font-semibold">{t('zone.etaNone')}</span> : p.eta_min === 0 ? t('zone.etaNow') : t('zone.etaIn', { n: p.eta_min })}
              </Stat>
              <Stat label={t('zone.maxRain')}>
                {p.rain_rate_max != null ? `${Math.round(p.rain_rate_max)} ${t('common.mmh')}` : '–'}
              </Stat>
              <Stat label={t('zone.ml')}>{p.p_ml != null ? `${Math.round(p.p_ml * 100)}%` : '–'}</Stat>
              <Stat label={t('zone.accum24')}>{p.accum_24h != null ? `${Math.round(p.accum_24h)} mm` : '–'}</Stat>
            </dl>

            <section className="mt-4">
              <h3 className="text-sm font-semibold text-muted">{t('zone.official')}</h3>
              <p className="mt-0.5">{p.official_warning || t('zone.officialNone')}</p>
            </section>

            {ex.sensor_check && (
              <section className="mt-4">
                <h3 className="text-sm font-semibold text-muted">{t('zone.ground')}</h3>
                <p className="mt-0.5">{t(`zone.ground.${ex.sensor_check}`)}</p>
                {z.sensors?.length > 0 && (
                  <ul className="mt-1 space-y-0.5 text-sm text-muted">
                    {z.sensors.map((s) => (
                      <li key={s.id || s.station}>
                        {s.kind === 'rain'
                          ? t('zone.ground.rain', { name: s.station, v: s.value, km: s.distance_km, age: s.age_min })
                          : t('zone.ground.river', { name: s.station, state: t(`sensors.river.${s.indicator}`).toLowerCase(), km: s.distance_km, age: s.age_min })}
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            )}

            <section className="mt-4">
              <h3 className="text-sm font-semibold text-muted">{t('zone.why')}</h3>
              {ex.rules_fired?.length ? (
                <ul className="mt-1 list-disc space-y-1 pl-5">
                  {ex.rules_fired.map((r) => (
                    <li key={r}>{describeRule(r, t, thresholds)}</li>
                  ))}
                  {ex.wet_ground_bump && <li>{t('rule.wet_bump')}</li>}
                </ul>
              ) : (
                <p className="mt-0.5">{t('zone.whyGreen')}</p>
              )}
              {ex.top_features?.length > 0 && (
                <p className="mt-2 text-sm text-muted">
                  {t('rule.features')}: {ex.top_features.map(([f]) => FEATURE_LABELS[f] || f).join(', ')}
                </p>
              )}
            </section>

            <section className="mt-4">
              <h3 className="mb-1 text-sm font-semibold text-muted">{t('zone.chart')}</h3>
              <div className="h-36">
                {series.data && (
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={series.data} margin={{ top: 6, right: 6, bottom: 0, left: -18 }}>
                      <CartesianGrid stroke="#E3E8E7" vertical={false} />
                      <XAxis dataKey="ts" tickFormatter={(v) => formatTime(v, lang)} minTickGap={40} tick={{ fontSize: 11, fill: '#5A6B69' }} />
                      <YAxis tick={{ fontSize: 11, fill: '#5A6B69' }} width={44} />
                      <ReferenceLine y={red} stroke="#C62828" strokeDasharray="4 3" />
                      <ReferenceLine y={amber} stroke="#F9A825" strokeDasharray="4 3" />
                      <Tooltip
                        labelFormatter={(v) => `${formatTime(v, lang)} MYT`}
                        formatter={(v, name) => (name === 'rain_rate_max' ? [`${v} ${t('common.mmh')}`, t('zone.maxRain')] : [v, name])}
                      />
                      <Line type="monotone" dataKey="rain_rate_max" stroke="#1E5450" strokeWidth={2} dot={false} isAnimationActive={false} />
                    </LineChart>
                  </ResponsiveContainer>
                )}
              </div>
            </section>

            <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
              <FollowButton zoneId={z.id} />
              <span className="text-xs text-muted">{t('zone.updated', { time: `${formatTime(p.ts, lang)} MYT` })}</span>
            </div>
          </>
        )}
      </div>
    </aside>
  )
}
