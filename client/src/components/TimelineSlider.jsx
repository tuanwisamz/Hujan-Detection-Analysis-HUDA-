import { Pause, Play } from 'lucide-react'
import { useEffect } from 'react'
import { level } from '../lib/levels'
import { useT } from '../lib/i18n'
import { formatTime } from '../lib/time'

const FRAME_MS = 500

/**
 * The rain strip: one bar per 10-min radar step, past on the left, forecast (hatched) on the
 * right of the "Now" divider (spec §10.1 Mapping). With a zone selected, bars take that zone's
 * level at each step, so the strip reads as "when does it get bad here?".
 * A native range input sits on top: drag, click and arrow keys all work.
 */
export default function TimelineSlider({ frames, index, onChange, playing, onTogglePlay, strip = [] }) {
  const { t, lang } = useT()
  const nowIdx = frames.findLastIndex((f) => f.kind === 'observed')

  useEffect(() => {
    if (!playing || frames.length < 2) return
    const id = setInterval(() => onChange((i) => (i + 1) % frames.length), FRAME_MS)
    return () => clearInterval(id)
  }, [playing, frames.length, onChange])

  if (!frames.length) {
    return <p className="text-sm text-muted">{t('timeline.noRadar')}</p>
  }

  const current = frames[index] || frames[nowIdx]
  const delta = Math.round((new Date(current.ts) - new Date(frames[nowIdx]?.ts || current.ts)) / 60000)
  const relative = delta === 0 ? t('timeline.now') : delta < 0 ? t('timeline.minAgo', { n: -delta }) : t('timeline.minAhead', { n: delta })

  const onKey = (e) => {
    if (e.key === ' ' || e.key === 'k') {
      e.preventDefault()
      onTogglePlay()
    }
  }

  return (
    <div className="flex items-center gap-3">
      <button
        type="button"
        onClick={onTogglePlay}
        className="inline-flex size-11 shrink-0 items-center justify-center rounded-full bg-primary text-white hover:bg-primary-strong"
        aria-label={playing ? t('timeline.pause') : t('timeline.play')}
      >
        {playing ? <Pause size={18} aria-hidden="true" /> : <Play size={18} aria-hidden="true" className="translate-x-px" />}
      </button>

      <div className="min-w-0 flex-1">
        <div className="mb-1 flex items-baseline justify-between gap-2 text-sm">
          <span className="font-semibold tabular" aria-live="polite">
            {relative}
            <span className="ml-2 font-normal text-muted">{formatTime(current.ts, lang)} MYT</span>
          </span>
          {current.kind === 'nowcast' && <span className="text-xs font-semibold text-muted">{t('timeline.forecast')}</span>}
        </div>

        <div className="relative rounded-md focus-within:outline focus-within:outline-3 focus-within:outline-offset-2 focus-within:outline-focus">
          <div className="flex h-8 items-end gap-[3px]" aria-hidden="true">
            {frames.map((f, i) => {
              const l = level(strip[i])
              const forecast = f.kind === 'nowcast'
              const active = i === index
              return (
                <div
                  key={f.ts}
                  className={`flex-1 rounded-[3px] transition-[height] ${forecast ? 'hatched' : ''} ${i === nowIdx + 1 ? 'ml-2' : ''}`}
                  style={{
                    height: active ? '100%' : '62%',
                    background: strip[i] ? l.color : forecast ? '#AEBAB8' : '#C4CDCB',
                    opacity: forecast && !f.image_url && !strip[i] ? 0.55 : 1,
                    boxShadow: active ? '0 0 0 2px var(--color-ink)' : 'none',
                  }}
                />
              )
            })}
          </div>
          <input
            type="range"
            min={0}
            max={frames.length - 1}
            step={1}
            value={Math.max(0, index)}
            onChange={(e) => onChange(Number(e.target.value))}
            onKeyDown={onKey}
            aria-label={t('timeline.label')}
            aria-valuetext={`${relative}, ${formatTime(current.ts, lang)}`}
            className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
          />
        </div>

        <div className="mt-1 flex text-xs text-muted">
          <span style={{ flex: nowIdx + 1 }}>{t('timeline.past')}</span>
          <span className="pl-2 font-semibold text-ink" style={{ flex: frames.length - nowIdx - 1 }}>
            {t('timeline.now')} → {t('timeline.forecast')}
          </span>
        </div>
      </div>
    </div>
  )
}
