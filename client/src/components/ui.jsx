import { ChevronDown, LoaderCircle, X } from 'lucide-react'
import { createContext, useCallback, useContext, useEffect, useId, useRef, useState } from 'react'
import { useT } from '../lib/i18n'

// Small shared UI pieces. Primary buttons are filled, secondary outlined (spec §10.1 Affordances).

export function Button({ variant = 'primary', busy = false, className = '', children, ...props }) {
  const styles = {
    primary: 'bg-primary text-white hover:bg-primary-strong disabled:bg-muted',
    secondary: 'border border-ink/25 bg-surface text-ink hover:border-ink/50 hover:bg-paper',
    danger: 'border border-level-red/40 bg-surface text-level-red hover:bg-level-red-soft',
    ghost: 'text-ink hover:bg-ink/5',
  }
  return (
    <button
      type="button"
      className={`inline-flex min-h-11 items-center justify-center gap-2 rounded-lg px-4 text-sm font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${styles[variant]} ${className}`}
      disabled={busy || props.disabled}
      {...props}
    >
      {busy && <LoaderCircle aria-hidden="true" size={16} className="animate-spin" />}
      {children}
    </button>
  )
}

export function Field({ label, hint, error, children, id }) {
  return (
    <label className="block" htmlFor={id}>
      <span className="mb-1 block text-sm font-semibold">{label}</span>
      {children}
      {hint && !error && <span className="mt-1 block text-xs text-muted">{hint}</span>}
      {error && <span className="mt-1 block text-xs font-semibold text-level-red">{error}</span>}
    </label>
  )
}

export const inputClass =
  'block min-h-11 w-full rounded-lg border border-line bg-surface px-3 text-base text-ink placeholder:text-muted/70 focus:border-primary'

/**
 * Dropdown of checkboxes, sized like the other inputs. An empty selection means "all":
 * the first row (allLabel) clears it. Escape or a click outside closes the menu.
 */
export function MultiSelect({ label, options, value, onChange, allLabel, countLabel }) {
  const id = useId()
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  const buttonRef = useRef(null)

  useEffect(() => {
    if (!open) return
    const onDown = (e) => !ref.current?.contains(e.target) && setOpen(false)
    const onKey = (e) => {
      if (e.key !== 'Escape') return
      setOpen(false)
      buttonRef.current?.focus()
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const toggle = (v) => onChange(value.includes(v) ? value.filter((x) => x !== v) : [...value, v])
  const chosen = options.filter((o) => value.includes(o.value))
  const summary = !chosen.length ? allLabel : chosen.length === 1 ? chosen[0].label : countLabel(chosen.length)
  const row = 'flex min-h-10 cursor-pointer items-center gap-2 rounded-md px-2 text-sm hover:bg-paper'

  return (
    <div ref={ref} className="relative">
      <span id={`${id}-label`} className="mb-1 block text-sm font-semibold">
        {label}
      </span>
      <button
        ref={buttonRef}
        type="button"
        aria-labelledby={`${id}-label ${id}-value`}
        aria-expanded={open}
        aria-controls={`${id}-menu`}
        onClick={() => setOpen((o) => !o)}
        className={`${inputClass} flex items-center justify-between gap-2 text-left`}
      >
        <span id={`${id}-value`} className="truncate">
          {summary}
        </span>
        <ChevronDown size={16} aria-hidden="true" className={`shrink-0 text-muted transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && (
        <div
          id={`${id}-menu`}
          role="group"
          aria-labelledby={`${id}-label`}
          className="absolute z-20 mt-1 max-h-72 w-full min-w-56 overflow-y-auto rounded-lg border border-line bg-surface p-1 shadow-lg"
        >
          <label className={`${row} border-b border-line font-semibold`}>
            <input type="checkbox" checked={!value.length} onChange={() => onChange([])} className="size-4 accent-primary" />
            {allLabel}
          </label>
          {options.map((o) => (
            <label key={o.value} className={row}>
              <input type="checkbox" checked={value.includes(o.value)} onChange={() => toggle(o.value)} className="size-4 accent-primary" />
              {o.label}
            </label>
          ))}
        </div>
      )}
    </div>
  )
}

export function Page({ title, intro, actions, children }) {
  return (
    <div className="mx-auto w-full max-w-5xl px-4 py-6 sm:px-8 sm:py-8">
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div className="max-w-2xl">
          <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">{title}</h1>
          {intro && <p className="mt-1 text-muted">{intro}</p>}
        </div>
        {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
      </div>
      {children}
    </div>
  )
}

export function Panel({ title, children, className = '' }) {
  return (
    <section className={`rounded-xl border border-line bg-surface p-4 sm:p-5 ${className}`}>
      {title && <h2 className="mb-3 text-lg font-bold">{title}</h2>}
      {children}
    </section>
  )
}

export function EmptyState({ icon: Icon, text, action }) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-line px-6 py-10 text-center">
      {Icon && <Icon aria-hidden="true" size={28} className="text-muted" />}
      <p className="max-w-sm text-muted">{text}</p>
      {action}
    </div>
  )
}

export function Loading() {
  const { t } = useT()
  return (
    <div className="space-y-2" aria-busy="true" aria-label={t('common.loading')}>
      {[0, 1, 2].map((i) => (
        <div key={i} className="h-14 animate-pulse rounded-lg bg-line/50" />
      ))}
    </div>
  )
}

export function ErrorNote({ error, onRetry }) {
  const { t } = useT()
  return (
    <div role="alert" className="flex flex-wrap items-center gap-3 rounded-lg border border-level-red/30 bg-level-red-soft px-4 py-3 text-sm">
      <span>{t('common.error', { msg: error?.message || '' })}</span>
      {onRetry && (
        <Button variant="secondary" onClick={onRetry}>
          {t('common.retry')}
        </Button>
      )}
    </div>
  )
}

export function Tabs({ tabs, value, onChange, label }) {
  return (
    <div role="tablist" aria-label={label} className="mb-4 flex gap-1 overflow-x-auto border-b border-line">
      {tabs.map((tab) => (
        <button
          key={tab.value}
          role="tab"
          type="button"
          aria-selected={value === tab.value}
          onClick={() => onChange(tab.value)}
          className={`-mb-px min-h-11 whitespace-nowrap border-b-2 px-3 text-sm font-semibold ${
            value === tab.value ? 'border-primary text-ink' : 'border-transparent text-muted hover:text-ink'
          }`}
        >
          {tab.label}
          {tab.count != null && <span className="ml-1.5 rounded-full bg-ink/10 px-1.5 text-xs tabular">{tab.count}</span>}
        </button>
      ))}
    </div>
  )
}

/** Accessible modal: focus moves in, Escape closes, focus returns to the opener. */
export function Dialog({ open, title, onClose, children, footer }) {
  const ref = useRef(null)
  const { t } = useT()
  useEffect(() => {
    const el = ref.current
    if (!el) return
    if (open && !el.open) el.showModal()
    if (!open && el.open) el.close()
  }, [open])
  return (
    <dialog
      ref={ref}
      onClose={onClose}
      onCancel={onClose}
      className="m-auto w-[min(32rem,calc(100vw-2rem))] rounded-xl border border-line bg-surface p-0 text-ink shadow-xl backdrop:bg-ink/40"
    >
      {open && (
        <div className="p-5">
          <div className="mb-3 flex items-start justify-between gap-4">
            <h2 className="text-lg font-bold">{title}</h2>
            <button type="button" onClick={onClose} className="-m-2 rounded-lg p-2 text-muted hover:text-ink" aria-label={t('common.close')}>
              <X size={20} aria-hidden="true" />
            </button>
          </div>
          {children}
          {footer && <div className="mt-5 flex flex-wrap justify-end gap-2">{footer}</div>}
        </div>
      )}
    </dialog>
  )
}

/** Confirmation for destructive / outward-facing actions (spec §10.1 Constraints). */
export function ConfirmDialog({ open, title, body, confirmLabel, danger, busy, onConfirm, onClose }) {
  const { t } = useT()
  return (
    <Dialog
      open={open}
      title={title}
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button variant={danger ? 'danger' : 'primary'} busy={busy} onClick={onConfirm}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      <p className="text-muted">{body}</p>
    </Dialog>
  )
}

// ---- Toasts: feedback on every save (spec §10.1 Feedback) ----

const ToastContext = createContext(() => {})

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([])
  const push = useCallback((text, tone = 'ok') => {
    const id = Math.random().toString(36).slice(2)
    setToasts((ts) => [...ts, { id, text, tone }])
    setTimeout(() => setToasts((ts) => ts.filter((x) => x.id !== id)), 4500)
  }, [])
  return (
    <ToastContext.Provider value={push}>
      {children}
      <div aria-live="polite" className="pointer-events-none fixed inset-x-0 bottom-20 z-[2000] flex flex-col items-center gap-2 px-4 lg:bottom-6">
        {toasts.map((x) => (
          <div
            key={x.id}
            className={`pointer-events-auto rounded-lg px-4 py-3 text-sm font-semibold shadow-lg ${x.tone === 'error' ? 'bg-level-red text-white' : 'bg-chrome text-on-chrome ring-1 ring-on-chrome/20'}`}
          >
            {x.text}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

// eslint-disable-next-line react-refresh/only-export-components
export function useToast() {
  return useContext(ToastContext)
}
