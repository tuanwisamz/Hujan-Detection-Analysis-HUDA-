import { BellOff, CirclePause, CirclePlay, Clock3, MessageSquareText, Moon, Send, ShieldCheck } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router'
import RiskBadge from '../components/RiskBadge'
import { Button, ConfirmDialog, EmptyState, ErrorNote, Field, inputClass, Loading, Page, Panel, useToast } from '../components/ui'
import { useApiMutation, useAutomation, useAutomationActivity, useZones } from '../hooks/queries'
import { api } from '../lib/api'
import { useT } from '../lib/i18n'
import { formatDateTime, formatTime } from '../lib/time'

// Admin owns every Telegram announcement (docs/automation-control.md).
// The radar pipeline keeps running; this page decides what gets posted, when and where.

const EVENTS = ['amber', 'red', 'all_clear']
const EVENT_LEVEL = { amber: 'AMBER', red: 'RED', all_clear: 'GREEN' }
const MODES = ['auto', 'approval', 'off']
const PAUSES = [60, 180, 720]
const INVALIDATE = ['automation', 'settings', 'warnings', 'automationActivity']

const STATE_STYLE = {
  active: { box: 'border-level-green/40 bg-level-green-soft', Icon: CirclePlay, icon: 'text-level-green' },
  paused: { box: 'border-level-amber bg-level-amber-soft', Icon: CirclePause, icon: 'text-ink' },
  quiet_hours: { box: 'border-primary/30 bg-paper', Icon: Moon, icon: 'text-primary' },
  off: { box: 'border-level-red/40 bg-level-red-soft', Icon: BellOff, icon: 'text-level-red' },
}

function editable(data) {
  const a = data.automation
  return {
    modes: { ...a.modes },
    quiet_hours: { ...a.quiet_hours, events: [...a.quiet_hours.events] },
    zone_overrides: { ...a.zone_overrides },
    use_ai_text: a.use_ai_text,
    send_dms: a.send_dms,
    auto_expires_min: a.auto_expires_min,
    cooldown_min: data.cooldown_min,
    all_clear_after_min: data.all_clear_after_min,
  }
}

function EventName({ event }) {
  const { t } = useT()
  return (
    <span className="flex flex-wrap items-center gap-2">
      <RiskBadge value={EVENT_LEVEL[event]} size="sm" />
      <span className="font-semibold">{t(`auto.event.${event}`)}</span>
    </span>
  )
}

/** Live state + pause / resume. These act immediately; they don't wait for Save. */
function StatusCard({ data }) {
  const { t, lang } = useT()
  const toast = useToast()
  const act = useApiMutation((body) => api('/admin/automation', { method: 'PATCH', body }), INVALIDATE)
  const st = data.status
  const style = STATE_STYLE[st.state] || STATE_STYLE.active
  const paused = st.state === 'paused'
  const run = (body, msg) => act.mutate(body, { onSuccess: () => toast(msg), onError: (e) => toast(e.message, 'error') })

  const headline = paused
    ? st.paused_until
      ? t('auto.state.pausedUntil', { time: formatTime(st.paused_until, lang) })
      : t('auto.state.pausedManual')
    : t(`auto.state.${st.state}`)

  return (
    <section className={`rounded-xl border p-4 sm:p-5 ${style.box}`} aria-live="polite">
      <div className="flex items-start gap-3">
        <style.Icon aria-hidden="true" size={28} className={`mt-0.5 shrink-0 ${style.icon}`} />
        <div className="min-w-0 flex-1">
          <p className="text-xs font-semibold tracking-wide text-muted uppercase">{t('auto.statusLabel')}</p>
          <h2 className="text-xl font-bold">{headline}</h2>
          <p className="mt-1 text-sm text-muted">{t(`auto.stateHint.${st.state}`)}</p>
        </div>
      </div>

      <ul className="mt-4 grid gap-2 sm:grid-cols-3">
        {EVENTS.map((e) => (
          <li key={e} className="rounded-lg bg-surface/80 px-3 py-2">
            <EventName event={e} />
            <p className="mt-1 text-sm">{t(`auto.effective.${st.effective[e]}`)}</p>
          </li>
        ))}
      </ul>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        {paused ? (
          <Button busy={act.isPending} onClick={() => run({ resume: true }, t('auto.resumed'))}>
            <CirclePlay size={16} aria-hidden="true" />
            {t('auto.resume')}
          </Button>
        ) : (
          <>
            <span className="text-sm font-semibold">{t('auto.pauseFor')}</span>
            {PAUSES.map((m) => (
              <Button key={m} variant="secondary" disabled={act.isPending} onClick={() => run({ pause_minutes: m }, t('auto.pausedToast'))}>
                {t('auto.hours', { n: m / 60 })}
              </Button>
            ))}
            <Button variant="secondary" disabled={act.isPending} onClick={() => run({ enabled: false }, t('auto.pausedToast'))}>
              <CirclePause size={16} aria-hidden="true" />
              {t('auto.pauseManual')}
            </Button>
          </>
        )}
        {data.pending_count > 0 && (
          <Link to="/admin/warnings" className="ml-auto text-sm font-semibold text-primary underline underline-offset-2">
            {t('auto.pendingLink', { n: data.pending_count })}
          </Link>
        )}
      </div>
    </section>
  )
}

function ModePicker({ event, value, onChange }) {
  const { t } = useT()
  return (
    <div role="radiogroup" aria-label={t(`auto.event.${event}`)} className="grid grid-cols-3 gap-1 rounded-lg border border-line bg-paper p-1">
      {MODES.map((m) => (
        <label
          key={m}
          className={`flex min-h-11 cursor-pointer items-center justify-center rounded-md px-2 text-center text-sm font-semibold leading-tight ${
            value === m ? (m === 'off' ? 'bg-level-red text-white' : 'bg-primary text-white') : 'text-ink hover:bg-surface'
          }`}
        >
          <input type="radio" className="sr-only" name={`mode-${event}`} value={m} checked={value === m} onChange={() => onChange(m)} />
          {t(`auto.mode.${m}`)}
        </label>
      ))}
    </div>
  )
}

function Toggle({ label, hint, checked, onChange }) {
  return (
    <label className="flex min-h-11 cursor-pointer items-start gap-3">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} className="mt-1 size-5 accent-[#1E5450]" />
      <span>
        <span className="font-semibold">{label}</span>
        {hint && <span className="block text-sm text-muted">{hint}</span>}
      </span>
    </label>
  )
}

function NumberField({ label, hint, value, onChange, min, max }) {
  const n = Number(value)
  const bad = value === '' || Number.isNaN(n) || n < min || n > max
  return (
    <Field label={label} hint={hint || `${min}–${max}`} error={bad ? `${min}–${max}` : null}>
      <input type="number" min={min} max={max} required value={value} onChange={(e) => onChange(e.target.value)} className={inputClass} />
    </Field>
  )
}

function ZoneOverrides({ value, onChange }) {
  const { t } = useT()
  const zones = useZones()
  const [q, setQ] = useState('')
  const items = (zones.data?.items || []).filter((z) => !q || z.name.toLowerCase().includes(q.toLowerCase()))
  const set = (id, mode) => {
    const next = { ...value }
    if (mode === 'inherit') delete next[id]
    else next[id] = mode
    onChange(next)
  }
  if (zones.isLoading) return <Loading />
  if (zones.error) return <ErrorNote error={zones.error} onRetry={zones.refetch} />
  return (
    <div>
      {(zones.data?.items || []).length > 8 && (
        <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('auto.zoneSearch')} aria-label={t('auto.zoneSearch')} className={`${inputClass} mb-3`} />
      )}
      <ul className="max-h-96 divide-y divide-line overflow-y-auto rounded-lg border border-line">
        {items.map((z) => {
          const mode = value[z.id] || 'inherit'
          return (
            <li key={z.id} className={`flex flex-wrap items-center gap-2 px-3 py-2 ${mode !== 'inherit' ? 'bg-paper' : ''}`}>
              <span className="min-w-0 flex-1">
                <span className="block font-semibold">{z.name}</span>
                {z.district && <span className="block text-xs text-muted">{z.district}</span>}
              </span>
              <select aria-label={t('auto.zoneRuleFor', { zone: z.name })} value={mode} onChange={(e) => set(z.id, e.target.value)} className={`${inputClass} w-auto min-w-44`}>
                <option value="inherit">{t('auto.zone.inherit')}</option>
                <option value="approval">{t('auto.zone.approval')}</option>
                <option value="off">{t('auto.zone.off')}</option>
              </select>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

function Activity() {
  const { t, lang } = useT()
  const logs = useAutomationActivity()
  const items = logs.data?.items || []
  if (logs.isLoading) return <Loading />
  if (logs.error) return <ErrorNote error={logs.error} onRetry={logs.refetch} />
  if (!items.length) return <EmptyState icon={MessageSquareText} text={t('auto.activityEmpty')} />
  return (
    <ol className="space-y-2">
      {items.map((l) => (
        <li key={l.id || `${l.ts}-${l.message}`} className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-sm">
          <time className="w-28 shrink-0 text-muted tabular" dateTime={l.ts}>
            {formatDateTime(l.ts, lang)}
          </time>
          <span className={`min-w-0 flex-1 ${l.severity === 'error' ? 'font-semibold text-level-red' : ''}`}>{l.message}</span>
        </li>
      ))}
    </ol>
  )
}

function TestMessage() {
  const { t } = useT()
  const toast = useToast()
  const [open, setOpen] = useState(false)
  const test = useApiMutation(() => api('/admin/automation/test', { method: 'POST' }), ['automationActivity'])
  return (
    <>
      <Button variant="secondary" onClick={() => setOpen(true)}>
        <Send size={16} aria-hidden="true" />
        {t('auto.test')}
      </Button>
      <ConfirmDialog
        open={open}
        title={t('auto.test')}
        body={t('auto.testConfirm')}
        confirmLabel={t('auto.testSend')}
        busy={test.isPending}
        onClose={() => setOpen(false)}
        onConfirm={() =>
          test.mutate(undefined, {
            onSuccess: (r) => (toast(t('auto.testSent', { id: r.telegram_message_id })), setOpen(false)),
            onError: (e) => (toast(e.message, 'error'), setOpen(false)),
          })
        }
      />
    </>
  )
}

export default function AutomationPage() {
  const { t } = useT()
  const toast = useToast()
  const auto = useAutomation()
  const [draft, setDraft] = useState(null)
  const save = useApiMutation((body) => api('/admin/automation', { method: 'PATCH', body }), INVALIDATE)
  const base = useMemo(() => (auto.data ? editable(auto.data) : null), [auto.data])

  if (auto.isLoading)
    return (
      <Page title={t('auto.title')} intro={t('auto.intro')}>
        <Loading />
      </Page>
    )
  if (auto.error)
    return (
      <Page title={t('auto.title')} intro={t('auto.intro')}>
        <ErrorNote error={auto.error} onRetry={auto.refetch} />
      </Page>
    )

  const s = draft || base
  const dirty = JSON.stringify(s) !== JSON.stringify(base)
  const set = (k) => (v) => setDraft({ ...s, [k]: v })
  const setMode = (e) => (m) => setDraft({ ...s, modes: { ...s.modes, [e]: m } })
  const setQuiet = (k) => (v) => setDraft({ ...s, quiet_hours: { ...s.quiet_hours, [k]: v } })
  const toggleQuietEvent = (e) => (on) =>
    setQuiet('events')(on ? [...new Set([...s.quiet_hours.events, e])] : s.quiet_hours.events.filter((x) => x !== e))
  const quietBad = s.quiet_hours.start === s.quiet_hours.end
  const nums = [
    ['cooldown_min', 0, 1440],
    ['all_clear_after_min', 0, 1440],
    ['auto_expires_min', 15, 1440],
  ]
  const numsBad = nums.some(([k, min, max]) => s[k] === '' || Number.isNaN(Number(s[k])) || Number(s[k]) < min || Number(s[k]) > max)
  const overrideCount = Object.keys(s.zone_overrides).length

  const submit = (e) => {
    e.preventDefault()
    if (quietBad || numsBad) return
    const body = { ...s, ...Object.fromEntries(nums.map(([k]) => [k, Number(s[k])])) }
    save.mutate(body, {
      onSuccess: () => (setDraft(null), toast(t('auto.saved'))),
      onError: (err) => toast(err.message, 'error'),
    })
  }

  return (
    <Page title={t('auto.title')} intro={t('auto.intro')}>
      <div className="space-y-4">
        <StatusCard data={auto.data} />

        <form onSubmit={submit} className="space-y-4">
          <Panel title={t('auto.rules')}>
            <p className="mb-4 text-sm text-muted">{t('auto.rulesIntro')}</p>
            <ul className="space-y-4">
              {EVENTS.map((e) => (
                <li key={e} className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,22rem)] sm:items-center">
                  <div>
                    <EventName event={e} />
                    <p className="mt-1 text-sm text-muted">{t(`auto.eventHint.${e}`)}</p>
                  </div>
                  <ModePicker event={e} value={s.modes[e]} onChange={setMode(e)} />
                  {e === 'red' && s.modes.red === 'off' && (
                    <p role="alert" className="rounded-lg bg-level-red-soft px-3 py-2 text-sm font-semibold text-level-red sm:col-span-2">
                      {t('auto.redOffWarning')}
                    </p>
                  )}
                </li>
              ))}
            </ul>
          </Panel>

          <Panel title={t('auto.quiet')}>
            <Toggle label={t('auto.quietToggle')} hint={t('auto.quietHint')} checked={s.quiet_hours.enabled} onChange={setQuiet('enabled')} />
            {s.quiet_hours.enabled && (
              <div className="mt-3 space-y-3">
                <div className="grid gap-3 sm:grid-cols-2">
                  <Field label={t('auto.quietStart')} error={quietBad ? t('auto.quietSame') : null}>
                    <input type="time" required value={s.quiet_hours.start} onChange={(e) => setQuiet('start')(e.target.value)} className={inputClass} />
                  </Field>
                  <Field label={t('auto.quietEnd')}>
                    <input type="time" required value={s.quiet_hours.end} onChange={(e) => setQuiet('end')(e.target.value)} className={inputClass} />
                  </Field>
                </div>
                <fieldset>
                  <legend className="mb-1 text-sm font-semibold">{t('auto.quietEvents')}</legend>
                  <div className="flex flex-wrap gap-2">
                    {EVENTS.map((e) => (
                      <label key={e} className={`flex min-h-11 cursor-pointer items-center gap-2 rounded-lg border px-3 ${s.quiet_hours.events.includes(e) ? 'border-ink bg-paper' : 'border-line'}`}>
                        <input type="checkbox" checked={s.quiet_hours.events.includes(e)} onChange={(ev) => toggleQuietEvent(e)(ev.target.checked)} className="size-5 accent-[#1E5450]" />
                        <RiskBadge value={EVENT_LEVEL[e]} size="sm" />
                        <span className="text-sm font-semibold">{t(`auto.event.${e}`)}</span>
                      </label>
                    ))}
                  </div>
                </fieldset>
              </div>
            )}
          </Panel>

          <Panel title={t('auto.timing')}>
            <div className="grid gap-3 sm:grid-cols-3">
              <NumberField label={t('auto.cooldown')} value={s.cooldown_min} onChange={set('cooldown_min')} min={0} max={1440} />
              <NumberField label={t('auto.allClear')} value={s.all_clear_after_min} onChange={set('all_clear_after_min')} min={0} max={1440} />
              <NumberField label={t('auto.expires')} value={s.auto_expires_min} onChange={set('auto_expires_min')} min={15} max={1440} />
            </div>
          </Panel>

          <Panel title={t('auto.delivery')}>
            <div className="space-y-1">
              <Toggle label={t('auto.aiText')} hint={t('auto.aiTextHint')} checked={s.use_ai_text} onChange={set('use_ai_text')} />
              <Toggle label={t('auto.dms')} hint={t('auto.dmsHint')} checked={s.send_dms} onChange={set('send_dms')} />
            </div>
            <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-line pt-4">
              <TestMessage />
              <span className="text-sm text-muted">{t('auto.testHint')}</span>
            </div>
          </Panel>

          <Panel title={t('auto.zones')}>
            <p className="mb-3 text-sm text-muted">
              {t('auto.zonesIntro')} {overrideCount > 0 && <strong className="text-ink">{t('auto.zonesCount', { n: overrideCount })}</strong>}
            </p>
            <ZoneOverrides value={s.zone_overrides} onChange={set('zone_overrides')} />
          </Panel>

          <div className={`flex flex-wrap items-center gap-3 rounded-xl border border-line bg-surface p-3 ${dirty ? 'sticky bottom-16 z-10 shadow-sm lg:bottom-4' : ''}`}>
            <Button type="submit" busy={save.isPending} disabled={!dirty || quietBad || numsBad}>
              <ShieldCheck size={16} aria-hidden="true" />
              {t('auto.save')}
            </Button>
            {dirty && (
              <>
                <span className="text-sm font-semibold">{t('auto.unsaved')}</span>
                <Button variant="ghost" onClick={() => setDraft(null)}>
                  {t('auto.discard')}
                </Button>
              </>
            )}
          </div>
        </form>

        <Panel title={t('auto.activity')}>
          <Activity />
          <Link to="/admin/logs" className="mt-3 inline-flex items-center gap-1 text-sm font-semibold text-primary underline underline-offset-2">
            <Clock3 size={14} aria-hidden="true" />
            {t('auto.activityAll')}
          </Link>
        </Panel>
      </div>
    </Page>
  )
}
