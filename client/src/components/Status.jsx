import { CloudOff, RefreshCw } from 'lucide-react'
import { useEffect, useState } from 'react'
import { LEVEL_ORDER, LEVELS } from '../lib/levels'
import { useT } from '../lib/i18n'
import { minutesSince } from '../lib/time'

const STALE_MIN = 20 // FR-05

function useNow(intervalMs = 30000) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs)
    return () => clearInterval(id)
  }, [intervalMs])
  return now
}

/** "Updated X min ago" — turns grey when data is older than 20 min (FR-05). */
export function FreshnessStamp({ at, className = '' }) {
  const { t } = useT()
  const now = useNow()
  const n = minutesSince(at, now)
  const stale = n != null && n > STALE_MIN
  const text = n == null ? t('fresh.none') : stale ? t('fresh.stale', { n }) : n < 1 ? t('fresh.justNow') : t('fresh.updated', { n })
  return (
    <span className={`inline-flex items-center gap-1.5 text-sm tabular ${stale ? 'text-muted' : 'text-ink'} ${className}`} title={at || ''}>
      <RefreshCw aria-hidden="true" size={14} className={stale ? 'opacity-50' : ''} />
      {text}
    </span>
  )
}

/** NFR-07: shown when any data source failed on the last run. */
export function DegradedBadge({ status }) {
  const { t } = useT()
  const failed = Object.entries(status || {})
    .filter(([, v]) => v !== 'ok')
    .map(([k]) => t(`source.${k}`))
  if (!failed.length) return null
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full border border-ink/20 bg-surface px-2.5 py-1 text-xs font-semibold"
      title={t('degraded.detail', { sources: failed.join(', ') })}
    >
      <CloudOff aria-hidden="true" size={14} />
      {t('degraded.badge')}
      <span className="sr-only">: {t('degraded.detail', { sources: failed.join(', ') })}</span>
    </span>
  )
}

/** Always-visible legend, ordered Green → Amber → Red top to bottom (spec §10.1 Mapping). */
export function Legend({ counts, compact = false }) {
  const { t } = useT()
  return (
    <div>
      <h2 className="mb-2 text-sm font-semibold text-muted">{t('live.legend')}</h2>
      <ul className="space-y-1.5">
        {LEVEL_ORDER.map((key) => {
          const l = LEVELS[key]
          return (
            <li key={key} className="flex items-start gap-2.5">
              <span className="mt-0.5 inline-flex size-6 shrink-0 items-center justify-center rounded-full" style={{ background: l.color, color: l.text }}>
                <l.Icon aria-hidden="true" size={14} strokeWidth={2.75} />
              </span>
              <span className="min-w-0 text-sm leading-snug">
                <span className="font-semibold">{t(`level.${key}`)}</span>
                {counts && <span className="ml-1 text-muted tabular">({counts[key] ?? 0})</span>}
                {!compact && <span className="block text-muted">{t(`level.${key}.meaning`)}</span>}
              </span>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

export function AttributionFooter({ className = '' }) {
  const { t } = useT()
  return (
    <p className={`text-xs leading-relaxed text-muted ${className}`}>
      {t('footer.attribution')
        .split(' · ')
        .map((part, i) => {
          const href = [
            'https://www.rainviewer.com/',
            'https://open-meteo.com/',
            'https://data.gov.my/',
            'https://www.openstreetmap.org/copyright',
          ][i]
          return (
            <span key={part}>
              {i > 0 && ' · '}
              <a href={href} target="_blank" rel="noreferrer" className="underline decoration-line underline-offset-2 hover:text-ink">
                {part}
              </a>
            </span>
          )
        })}
    </p>
  )
}
