import { Activity, ChevronRight, CircleHelp } from 'lucide-react'
import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import RadarMap from '../components/RadarMap'
import RiskBadge, { LevelDot } from '../components/RiskBadge'
import { AttributionFooter, DegradedBadge, FreshnessStamp, Legend } from '../components/Status'
import TimelineSlider from '../components/TimelineSlider'
import Tour from '../components/Tour'
import { ErrorNote, Loading } from '../components/ui'
import { useAdminSettings, useLiveSummary, useRadarFrames, useRuns, useTimeseries } from '../hooks/queries'
import { level } from '../lib/levels'
import { useT } from '../lib/i18n'
import { formatTime } from '../lib/time'

const ZonePanel = lazy(() => import('../components/ZonePanel')) // pulls in Recharts; load on first click

const LAST_ZONE_KEY = 'huda.lastZone'

function storedZone() {
  try {
    return localStorage.getItem(LAST_ZONE_KEY)
  } catch {
    return null
  }
}

/** 12 observed frames + 6 nowcast steps. Forecast steps exist even if the PNGs are missing. */
function buildFrames(radar) {
  const observed = (radar?.observed || []).map((f) => ({ ...f, kind: 'observed' }))
  let nowcast = (radar?.nowcast || []).map((f) => ({ ...f, kind: 'nowcast' }))
  const last = observed.at(-1)
  if (!nowcast.length && last) {
    nowcast = [1, 2, 3, 4, 5, 6].map((k) => ({ ts: new Date(new Date(last.ts).getTime() + k * 600000).toISOString(), kind: 'nowcast' }))
  }
  return [...observed, ...nowcast]
}

/** Per-step level for the selected zone: history for the past, ETA for the forecast. */
function zoneStrip(frames, series, zone) {
  if (!zone) return []
  const nowTs = frames.findLast((f) => f.kind === 'observed')?.ts
  return frames.map((f) => {
    if (f.kind === 'observed') {
      const t = new Date(f.ts).getTime()
      const row = (series || []).findLast((r) => new Date(r.ts).getTime() <= t + 5 * 60000)
      return row?.level
    }
    const ahead = (new Date(f.ts) - new Date(nowTs)) / 60000
    if (!zone.level || zone.level === 'GREEN') return 'GREEN'
    if (zone.eta_min == null) return zone.level // set by model/MET, not by an arriving cell
    return ahead >= zone.eta_min ? zone.level : 'GREEN'
  })
}

/** Age of the data = newest prediction, not when the summary was served. */
function latestUpdate(zones) {
  const times = zones.map((z) => z.updated_at).filter(Boolean)
  return times.length ? times.reduce((a, b) => (a > b ? a : b)) : null
}

function ZoneRow({ zone, selected, onSelect }) {
  const { t } = useT()
  return (
    <li>
      <button
        type="button"
        onClick={() => onSelect(zone)}
        aria-current={selected ? 'true' : undefined}
        className={`flex min-h-12 w-full items-center gap-3 rounded-lg px-2.5 py-2 text-left ${selected ? 'bg-paper ring-2 ring-ink' : 'hover:bg-paper'}`}
      >
        <LevelDot value={zone.level} />
        <span className="min-w-0 flex-1">
          <span className="block truncate font-semibold">{zone.name}</span>
          <span className="block text-xs text-muted">
            {t(`level.${level(zone.level).key}`)}
            {zone.eta_min != null && zone.level !== 'GREEN' && ` · ${zone.eta_min === 0 ? t('zone.etaNow') : t('zone.etaIn', { n: zone.eta_min })}`}
          </span>
        </span>
        <ChevronRight size={16} aria-hidden="true" className="text-muted" />
      </button>
    </li>
  )
}

function HealthStrip() {
  const { t, lang } = useT()
  const runs = useRuns()
  const last = runs.data?.items?.[0]
  if (!last) return null
  const sources = Object.entries(last.sources || {}).filter(([, v]) => ['ok', 'failed', 'skipped', 'synthetic', 'archive'].includes(v))
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg border border-line bg-surface px-3 py-2 text-sm">
      <span className="inline-flex items-center gap-1.5 font-semibold">
        <Activity size={15} aria-hidden="true" />
        {t('live.health')}
      </span>
      <span className="text-muted">{t('live.lastRun', { time: formatTime(last.started_at, lang) })} · {last.duration_s ?? '–'} s</span>
      <span className="flex flex-wrap gap-1.5">
        {sources.map(([k, v]) => (
          <span key={k} className={`rounded px-1.5 py-0.5 text-xs font-semibold ${v === 'failed' ? 'bg-level-red-soft text-level-red' : 'bg-paper text-muted'}`}>
            {k}: {v}
          </span>
        ))}
      </span>
    </div>
  )
}

export default function LivePage({ admin = false }) {
  const { t } = useT()
  const live = useLiveSummary()
  const radar = useRadarFrames()
  const settings = useAdminSettings(admin)
  const [params, setParams] = useSearchParams()
  const zones = useMemo(() => live.data?.zones || [], [live.data])
  const frames = useMemo(() => buildFrames(radar.data), [radar.data])
  const nowIdx = frames.findLastIndex((f) => f.kind === 'observed')
  const [index, setIndex] = useState(-1)
  const [playing, setPlaying] = useState(false)
  const activeIndex = index < 0 ? nowIdx : index

  const param = params.get('zone')
  const selected = useMemo(() => {
    const key = param ?? (admin ? null : storedZone())
    return zones.find((z) => z.slug === key || z.id === key) || null
  }, [param, zones, admin])
  const series = useTimeseries(selected?.id, 3)
  const strip = useMemo(() => zoneStrip(frames, series.data, selected), [frames, series.data, selected])

  const select = useCallback(
    (z) => {
      const next = new URLSearchParams(params)
      if (z) {
        next.set('zone', z.slug)
        try {
          localStorage.setItem(LAST_ZONE_KEY, z.slug)
        } catch {
          /* ignore */
        }
      } else {
        next.delete('zone')
        try {
          localStorage.removeItem(LAST_ZONE_KEY)
        } catch {
          /* ignore */
        }
      }
      setParams(next, { replace: true })
    },
    [params, setParams],
  )

  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && selected && select(null)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [selected, select])

  const mine = zones.filter((z) => z.subscribed)
  const others = admin ? zones : zones.filter((z) => !z.subscribed)
  const counts = live.data?.counts

  return (
    <div className="flex h-full flex-col lg:flex-row">
      <Tour />

      {/* Zone list + legend. Keyboard path to every zone (map shapes aren't focusable). */}
      <section className="order-2 flex flex-col border-line bg-surface lg:order-1 lg:min-h-0 lg:w-80 lg:border-r">
        <div className="space-y-2 border-b border-line px-4 py-3">
          <div className="flex flex-wrap items-center gap-2">
            <FreshnessStamp at={latestUpdate(zones)} />
            <DegradedBadge status={live.data?.data_status} />
          </div>
          {counts && (
            <p className="text-sm text-muted tabular">{t('live.counts', { red: counts.RED, amber: counts.AMBER, green: counts.GREEN })}</p>
          )}
        </div>

        <div className="px-2 py-3 lg:min-h-0 lg:flex-1 lg:overflow-y-auto">
          {live.isLoading && <Loading />}
          {live.error && <ErrorNote error={live.error} onRetry={live.refetch} />}
          {!admin && live.data && (
            <>
              <h2 className="px-2 pb-1 text-sm font-semibold text-muted">{t('live.myZones')}</h2>
              {mine.length ? (
                <ul className="mb-4 space-y-0.5">
                  {mine.map((z) => (
                    <ZoneRow key={z.id} zone={z} selected={z.id === selected?.id} onSelect={select} />
                  ))}
                </ul>
              ) : (
                <div className="mx-2 mb-4 rounded-lg border border-dashed border-line px-3 py-3 text-sm">
                  <p className="text-muted">{t('live.noSubs')}</p>
                  <Link to="/app/zones" className="mt-1 inline-flex min-h-11 items-center font-semibold text-primary underline underline-offset-2">
                    {t('live.pickZones')}
                  </Link>
                </div>
              )}
            </>
          )}
          {live.data && (
            <>
              <h2 className="px-2 pb-1 text-sm font-semibold text-muted">{t('live.allZones')}</h2>
              <ul className="space-y-0.5">
                {others.map((z) => (
                  <ZoneRow key={z.id} zone={z} selected={z.id === selected?.id} onSelect={select} />
                ))}
              </ul>
            </>
          )}
        </div>

        <div className="space-y-3 border-t border-line px-4 py-3">
          <details className="group">
            <summary className="flex min-h-11 cursor-pointer list-none items-center gap-2 text-sm font-semibold text-primary">
              <CircleHelp size={16} aria-hidden="true" />
              {t('live.whatMeans')}
            </summary>
            <div className="pt-1">
              <Legend counts={counts} />
            </div>
          </details>
          <AttributionFooter />
        </div>
      </section>

      {/* Map + timeline */}
      <section className="relative order-1 h-[58vh] min-h-80 lg:order-2 lg:h-auto lg:flex-1">
        <RadarMap zones={zones} frames={frames} activeIndex={activeIndex} selectedId={selected?.id} onSelect={select} focusZone={selected} />

        {admin && (
          <div className="absolute left-14 right-3 top-3 z-[500] lg:right-56">
            <HealthStrip />
          </div>
        )}

        {/* Compact always-visible legend on the map (FR-05) */}
        <div className="absolute right-3 top-3 z-[500] hidden rounded-xl border border-line bg-surface/95 p-3 shadow-sm lg:block">
          <Legend compact counts={counts} />
        </div>

        <div className={`absolute inset-x-3 bottom-3 z-[500] rounded-xl border border-line bg-surface/95 px-3 py-3 shadow-sm ${selected ? 'lg:right-[25.5rem]' : 'lg:right-auto lg:w-[34rem]'}`}>
          {selected && (
            <p className="mb-2 flex items-center gap-2 text-sm">
              <RiskBadge value={selected.level} size="sm" />
              <span className="truncate font-semibold">{selected.name}</span>
              {selected.replay && <span className="rounded bg-ink/10 px-1.5 text-xs font-semibold">{t('live.replay')}</span>}
            </p>
          )}
          <TimelineSlider
            frames={frames}
            index={activeIndex}
            onChange={(v) => setIndex(typeof v === 'function' ? v(activeIndex) : v)}
            playing={playing}
            onTogglePlay={() => setPlaying((p) => !p)}
            strip={strip}
          />
        </div>

        {/* Zone panel opens beside the map content (desktop) / as a bottom sheet (mobile) */}
        {selected && (
          <div className="absolute inset-x-0 bottom-0 z-[600] max-h-[85%] lg:inset-x-auto lg:bottom-3 lg:right-3 lg:top-3 lg:max-h-none lg:w-96">
            <Suspense fallback={<div className="h-64 rounded-2xl border border-line bg-surface" />}>
              <ZonePanel zoneId={selected.id} onClose={() => select(null)} thresholds={settings.data?.thresholds} />
            </Suspense>
          </div>
        )}
      </section>
    </div>
  )
}
