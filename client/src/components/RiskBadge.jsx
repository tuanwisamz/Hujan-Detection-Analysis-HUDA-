import { level } from '../lib/levels'
import { useT } from '../lib/i18n'

/** Colour + icon + text, always (NFR-06). size: 'sm' | 'md' | 'lg'. */
export default function RiskBadge({ value, size = 'md', className = '' }) {
  const { t } = useT()
  const l = level(value)
  const Icon = l.Icon
  const sizes = {
    sm: 'gap-1 px-2 py-0.5 text-xs',
    md: 'gap-1.5 px-2.5 py-1 text-sm',
    lg: 'gap-2 px-3.5 py-1.5 text-base',
  }
  return (
    <span
      className={`inline-flex shrink-0 items-center rounded-full font-semibold ${sizes[size]} ${className}`}
      style={{ background: l.color, color: l.text }}
    >
      {Icon && <Icon aria-hidden="true" size={size === 'lg' ? 18 : size === 'sm' ? 13 : 15} strokeWidth={2.5} />}
      {t(`level.${l.key}`)}
    </span>
  )
}

/** Small swatch for dense lists: shape + colour, label for screen readers. */
export function LevelDot({ value }) {
  const { t } = useT()
  const l = level(value)
  const Icon = l.Icon
  return (
    <span className="inline-flex size-6 shrink-0 items-center justify-center rounded-full" style={{ background: l.color, color: l.text }}>
      {Icon ? <Icon aria-hidden="true" size={14} strokeWidth={2.75} /> : <span aria-hidden="true">–</span>}
      <span className="sr-only">{t(`level.${l.key}`)}</span>
    </span>
  )
}
