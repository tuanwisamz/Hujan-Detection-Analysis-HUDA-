import { Bot, Megaphone, Plus, Sparkles } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import RiskBadge from '../components/RiskBadge'
import { Button, ConfirmDialog, Dialog, EmptyState, ErrorNote, Field, inputClass, Loading, Page, Tabs, useToast } from '../components/ui'
import { useApiMutation, useAutomation, useWarnings, useZones } from '../hooks/queries'
import { api } from '../lib/api'
import { useT } from '../lib/i18n'
import { formatDateTime, formatTime } from '../lib/time'

const BANNER_STYLE = {
  active: 'border-level-green/40 bg-level-green-soft',
  paused: 'border-level-amber bg-level-amber-soft',
  quiet_hours: 'border-primary/30 bg-paper',
  off: 'border-level-red/40 bg-level-red-soft',
}

/** One-line automation state, so admins know why warnings are (or aren't) queued here. */
function AutomationBanner() {
  const { t, lang } = useT()
  const auto = useAutomation()
  const st = auto.data?.status
  if (!st) return null
  const text =
    st.state === 'paused'
      ? st.paused_until
        ? t('auto.state.pausedUntil', { time: formatTime(st.paused_until, lang) })
        : t('auto.state.pausedManual')
      : t(`auto.state.${st.state}`)
  return (
    <div className={`mb-4 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border px-4 py-3 text-sm ${BANNER_STYLE[st.state] || ''}`}>
      <Bot size={18} aria-hidden="true" />
      <span>
        <span className="font-semibold">{t('auto.statusLabel')}:</span> {text}
      </span>
      <Link to="/admin/automation" className="ml-auto font-semibold text-primary underline underline-offset-2">
        {t('auto.banner.manage')}
      </Link>
    </div>
  )
}

const TABS = ['pending_approval', 'draft', 'sent', 'cancelled']
const TAB_LABEL = { pending_approval: 'warnings.tabPending', draft: 'warnings.tabDraft', sent: 'warnings.tabSent', cancelled: 'warnings.tabCancelled' }
const MAX_LANG = 250

function WarningCard({ w }) {
  const { t, lang } = useT()
  const toast = useToast()
  const [text, setText] = useState({ en: w.message_en || '', ms: w.message_ms || '' })
  const [confirm, setConfirm] = useState(null)
  const invalidate = ['warnings', 'alerts']
  const generate = useApiMutation(() => api(`/admin/warnings/${w.id}/generate-text`, { method: 'POST' }), [])
  const approve = useApiMutation(() => api(`/admin/warnings/${w.id}/approve`, { method: 'POST' }), invalidate)
  const cancel = useApiMutation(() => api(`/admin/warnings/${w.id}/cancel`, { method: 'POST' }), invalidate)
  const rebroadcast = useApiMutation(() => api(`/admin/warnings/${w.id}/rebroadcast`, { method: 'POST' }), invalidate)
  const editable = ['draft', 'pending_approval'].includes(w.status)

  const runGenerate = () =>
    generate.mutate(undefined, {
      onSuccess: (r) => {
        setText({ en: r.message_en || '', ms: r.message_ms || '' })
        toast(r.fallback ? t('warnings.textFallback') : t('warnings.textReady'))
      },
      onError: (e) => toast(e.message, 'error'),
    })
  const done = (msg) => ({ onSuccess: () => (toast(msg), setConfirm(null)), onError: (e) => (toast(e.message, 'error'), setConfirm(null)) })

  return (
    <li className="rounded-xl border border-line bg-surface p-4">
      <div className="flex flex-wrap items-center gap-2">
        <RiskBadge value={w.level} />
        <span className="text-lg font-bold">{w.zone}</span>
        {w.status === 'pending_approval' && (
          <span className="rounded-full border border-ink/30 px-2 py-0.5 text-xs font-semibold">{t('warnings.requiresApproval')}</span>
        )}
        <span className="ml-auto text-sm text-muted">
          {t(`warnings.source.${w.source}`)} · {formatDateTime(w.created_at, lang)}
        </span>
      </div>

      {editable ? (
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          {[
            ['en', 'EN'],
            ['ms', 'BM'],
          ].map(([k, label]) => (
            <Field key={k} label={label} hint={`${text[k].length}/${MAX_LANG}`} error={text[k].length > MAX_LANG ? `> ${MAX_LANG}` : null}>
              <textarea rows={3} value={text[k]} placeholder={t('warnings.blankHint')} onChange={(e) => setText((x) => ({ ...x, [k]: e.target.value }))} className={`${inputClass} py-2`} />
            </Field>
          ))}
        </div>
      ) : (
        (w.message_en || w.message_ms) && (
          <div className="mt-3 space-y-1 text-sm">
            {w.message_en && <p>EN: {w.message_en}</p>}
            {w.message_ms && <p>BM: {w.message_ms}</p>}
          </div>
        )
      )}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        {editable && (
          <>
            <Button onClick={() => setConfirm('send')}>{t('warnings.approve')}</Button>
            <Button variant="secondary" busy={generate.isPending} onClick={runGenerate}>
              <Sparkles size={16} aria-hidden="true" />
              {t('warnings.writeText')}
            </Button>
          </>
        )}
        {w.status === 'sent' && (
          <>
            <Button variant="secondary" busy={rebroadcast.isPending} onClick={() => rebroadcast.mutate(undefined, done(t('warnings.sent')))}>
              {t('warnings.rebroadcast')}
            </Button>
            {w.telegram_message_id && <span className="text-sm text-muted">{t('warnings.telegramId', { id: w.telegram_message_id })}</span>}
          </>
        )}
        {w.status !== 'cancelled' && (
          <Button variant="danger" className="ml-auto" onClick={() => setConfirm('cancel')}>
            {t('warnings.cancel')}
          </Button>
        )}
      </div>

      <ConfirmDialog
        open={confirm === 'send'}
        title={t('warnings.approve')}
        body={t('warnings.confirmSend', { level: t(`level.${w.level}`), zone: w.zone })}
        confirmLabel={t('warnings.approve')}
        busy={approve.isPending}
        onClose={() => setConfirm(null)}
        onConfirm={async () => {
          // Save edited text first, then approve (the backend sends what is stored).
          if (text.en !== (w.message_en || '') || text.ms !== (w.message_ms || '')) {
            try {
              await api(`/admin/warnings/${w.id}`, { method: 'PATCH', body: { message_en: text.en || null, message_ms: text.ms || null } })
            } catch (e) {
              toast(e.message, 'error')
              setConfirm(null)
              return
            }
          }
          approve.mutate(undefined, done(t('warnings.sent')))
        }}
      />
      <ConfirmDialog
        open={confirm === 'cancel'}
        danger
        title={t('warnings.cancel')}
        body={t('warnings.confirmCancel')}
        confirmLabel={t('warnings.cancel')}
        busy={cancel.isPending}
        onClose={() => setConfirm(null)}
        onConfirm={() => cancel.mutate(undefined, done(t('warnings.cancelled')))}
      />
    </li>
  )
}

function NewWarning({ onClose }) {
  const { t } = useT()
  const toast = useToast()
  const zones = useZones()
  const [form, setForm] = useState({ zone_id: '', level: 'AMBER', message_en: '', message_ms: '', expires_in_min: 120 })
  const create = useApiMutation((body) => api('/admin/warnings', { method: 'POST', body }), ['warnings'])
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))
  return (
    <Dialog open title={t('warnings.new')} onClose={onClose}>
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault()
          create.mutate(
            { ...form, expires_in_min: Number(form.expires_in_min), message_en: form.message_en || null, message_ms: form.message_ms || null },
            { onSuccess: () => (toast(t('warnings.drafted')), onClose()), onError: (err) => toast(err.message, 'error') },
          )
        }}
      >
        <Field label={t('nav.zones')}>
          <select required value={form.zone_id} onChange={set('zone_id')} className={inputClass}>
            <option value="" disabled>
              –
            </option>
            {(zones.data?.items || []).map((z) => (
              <option key={z.id} value={z.id}>
                {z.name}
              </option>
            ))}
          </select>
        </Field>
        <fieldset>
          <legend className="mb-1 text-sm font-semibold">{t('live.legend')}</legend>
          <div className="flex gap-2">
            {['AMBER', 'RED'].map((l) => (
              <label key={l} className={`flex min-h-11 cursor-pointer items-center gap-2 rounded-lg border px-3 ${form.level === l ? 'border-ink' : 'border-line'}`}>
                <input type="radio" name="level" value={l} checked={form.level === l} onChange={set('level')} />
                <RiskBadge value={l} size="sm" />
              </label>
            ))}
          </div>
        </fieldset>
        <Field label="EN">
          <textarea rows={2} maxLength={MAX_LANG} value={form.message_en} onChange={set('message_en')} className={`${inputClass} py-2`} />
        </Field>
        <Field label="BM">
          <textarea rows={2} maxLength={MAX_LANG} value={form.message_ms} onChange={set('message_ms')} className={`${inputClass} py-2`} />
        </Field>
        <Field label={t('warnings.expires')}>
          <input type="number" min={5} max={1440} value={form.expires_in_min} onChange={set('expires_in_min')} className={inputClass} />
        </Field>
        <div className="flex justify-end gap-2 pt-1">
          <Button variant="secondary" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button type="submit" busy={create.isPending}>
            {t('warnings.new')}
          </Button>
        </div>
      </form>
    </Dialog>
  )
}

export default function WarningsPage() {
  const { t } = useT()
  const [tab, setTab] = useState('pending_approval')
  const [creating, setCreating] = useState(false)
  const all = useWarnings()
  const items = (all.data?.items || []).filter((w) => w.status === tab)
  const count = (s) => (all.data?.items || []).filter((w) => w.status === s).length

  return (
    <Page
      title={t('warnings.title')}
      intro={t('warnings.intro')}
      actions={
        <Button onClick={() => setCreating(true)}>
          <Plus size={16} aria-hidden="true" />
          {t('warnings.new')}
        </Button>
      }
    >
      <AutomationBanner />
      <Tabs label={t('warnings.title')} value={tab} onChange={setTab} tabs={TABS.map((s) => ({ value: s, label: t(TAB_LABEL[s]), count: count(s) }))} />
      {all.isLoading && <Loading />}
      {all.error && <ErrorNote error={all.error} onRetry={all.refetch} />}
      {all.data && !items.length && <EmptyState icon={Megaphone} text={t('warnings.empty')} />}
      <ul className="space-y-3">
        {items.map((w) => (
          <WarningCard key={`${w.id}-${w.status}-${w.message_en}`} w={w} />
        ))}
      </ul>
      {creating && <NewWarning onClose={() => setCreating(false)} />}
    </Page>
  )
}
