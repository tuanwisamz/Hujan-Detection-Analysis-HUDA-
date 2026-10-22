import { AlertTriangle, BellRing, CircleCheck, Hourglass, Pencil, Plus, Radio, Siren, Square, Volume2, VolumeX } from 'lucide-react'
import { useEffect, useState } from 'react'
import SirenApprovals from '../components/SirenApprovals'
import { Button, ConfirmDialog, Dialog, EmptyState, ErrorNote, Field, inputClass, Loading, Page, Panel, useToast } from '../components/ui'
import { useApiMutation, useSirenActivations, useSirens, useZones } from '../hooks/queries'
import { api } from '../lib/api'
import { useT } from '../lib/i18n'
import { formatDateTime } from '../lib/time'

// Township sirens (spec FR-35, implementation-plan-v2 §6.3). Virtual sirens need no hardware;
// webhook sirens get signed siren.on / siren.off / siren.test POSTs.

const INVALIDATE = ['sirens', 'sirenActivations', 'automation', 'live']

// Icon + text for every state, never colour alone (NFR-06).
const STATE = {
  idle: { Icon: CircleCheck, box: 'bg-paper text-ink' },
  pending_approval: { Icon: Hourglass, box: 'bg-level-amber-soft text-ink' },
  active: { Icon: BellRing, box: 'bg-level-red text-white' },
  failed: { Icon: AlertTriangle, box: 'bg-level-red-soft text-level-red' },
}

/** A wailing tone in this browser while a virtual siren sounds. Off by default. */
function useTone(on) {
  useEffect(() => {
    if (!on) return undefined
    const Ctx = window.AudioContext || window.webkitAudioContext
    if (!Ctx) return undefined
    const ctx = new Ctx()
    const osc = ctx.createOscillator()
    const lfo = ctx.createOscillator()
    const depth = ctx.createGain()
    const vol = ctx.createGain()
    osc.frequency.value = 700
    lfo.frequency.value = 0.4
    depth.gain.value = 250
    vol.gain.value = 0.08
    lfo.connect(depth).connect(osc.frequency)
    osc.connect(vol).connect(ctx.destination)
    osc.start()
    lfo.start()
    return () => ctx.close()
  }, [on])
}

function SirenForm({ siren, onClose }) {
  const { t } = useT()
  const toast = useToast()
  const zones = useZones()
  const [form, setForm] = useState({
    zone_id: siren?.zone_id || '',
    name: siren?.name || '',
    endpoint_url: siren?.endpoint_url || '',
    note: siren?.note || '',
    active: siren?.active ?? true,
  })
  const save = useApiMutation(
    (body) => (siren ? api(`/admin/sirens/${siren.id}`, { method: 'PATCH', body }) : api('/admin/sirens', { method: 'POST', body })),
    INVALIDATE,
  )
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value }))
  const urlBad = form.endpoint_url && !form.endpoint_url.startsWith('https://')
  return (
    <Dialog open title={siren ? t('sirens.edit') : t('sirens.add')} onClose={onClose}>
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault()
          if (urlBad) return
          save.mutate(
            { ...form, endpoint_url: form.endpoint_url || null, note: form.note || null },
            { onSuccess: () => (toast(t('sirens.saved')), onClose()), onError: (err) => toast(err.message, 'error') },
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
        <Field label={t('sirens.name')}>
          <input required maxLength={120} value={form.name} onChange={set('name')} className={inputClass} />
        </Field>
        <Field label={t('sirens.endpoint')} hint={t('sirens.endpointHint')} error={urlBad ? t('sirens.endpointHttps') : null}>
          <input type="url" placeholder="https://" value={form.endpoint_url} onChange={set('endpoint_url')} className={inputClass} />
        </Field>
        <Field label={t('sirens.note')}>
          <input maxLength={300} value={form.note} onChange={set('note')} className={inputClass} />
        </Field>
        <label className="flex min-h-11 items-center gap-2 font-semibold">
          <input type="checkbox" checked={form.active} onChange={set('active')} className="size-5 accent-[#1E5450]" />
          {t('sirens.activeToggle')}
        </label>
        <div className="flex justify-end gap-2 pt-1">
          <Button variant="secondary" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button type="submit" busy={save.isPending} disabled={urlBad}>
            {t('sirens.save')}
          </Button>
        </div>
      </form>
    </Dialog>
  )
}

function SoundDialog({ siren, onClose }) {
  const { t } = useT()
  const toast = useToast()
  const [reason, setReason] = useState('')
  const sound = useApiMutation((body) => api(`/admin/sirens/${siren.id}/sound`, { method: 'POST', body }), INVALIDATE)
  return (
    <Dialog
      open
      title={t('sirens.soundTitle', { name: siren.name })}
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button
            variant="danger"
            busy={sound.isPending}
            disabled={reason.trim().length < 3}
            onClick={() =>
              sound.mutate({ reason: reason.trim() }, { onSuccess: () => (toast(t('sirens.sounding')), onClose()), onError: (e) => toast(e.message, 'error') })
            }
          >
            <Siren size={16} aria-hidden="true" />
            {t('sirens.sound')}
          </Button>
        </>
      }
    >
      <p className="mb-3 text-muted">{t('sirens.soundBody', { zone: siren.zone_name })}</p>
      <Field label={t('sirens.reason')}>
        <textarea rows={2} required maxLength={300} value={reason} onChange={(e) => setReason(e.target.value)} className={`${inputClass} py-2`} />
      </Field>
    </Dialog>
  )
}

function SirenCard({ s, onEdit, onSound }) {
  const { t, lang } = useT()
  const toast = useToast()
  const [confirmStop, setConfirmStop] = useState(false)
  const test = useApiMutation(() => api(`/admin/sirens/${s.id}/test`, { method: 'POST' }), ['sirenActivations'])
  const stop = useApiMutation(() => api(`/admin/siren-activations/${s.last_activation.id}/stop`, { method: 'POST' }), INVALIDATE)
  const st = STATE[s.state] || STATE.idle
  return (
    <li className={`rounded-xl border bg-surface p-4 ${s.state === 'active' ? 'border-2 border-level-red' : 'border-line'} ${s.active ? '' : 'opacity-70'}`}>
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-lg font-bold">{s.name}</p>
          <p className="text-sm text-muted">
            {s.zone_name} · {s.virtual ? t('sirens.virtual') : t('sirens.webhook')}
            {!s.active && ` · ${t('sirens.inactive')}`}
          </p>
          {s.note && <p className="mt-1 text-sm">{s.note}</p>}
        </div>
        <span className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-sm font-bold ${st.box}`}>
          <st.Icon size={16} aria-hidden="true" />
          {t(`sirens.state.${s.state}`)}
        </span>
      </div>
      {s.state === 'failed' && s.last_activation?.last_error && (
        <p className="mt-2 text-sm font-semibold text-level-red">{s.last_activation.last_error}</p>
      )}
      {s.state === 'active' && s.last_activation?.started_at && (
        <p className="mt-2 text-sm">{t('sirens.since', { time: formatDateTime(s.last_activation.started_at, lang) })}</p>
      )}
      <div className="mt-3 flex flex-wrap gap-2">
        {s.state === 'active' ? (
          <Button variant="danger" onClick={() => setConfirmStop(true)}>
            <Square size={16} aria-hidden="true" />
            {t('sirens.stop')}
          </Button>
        ) : (
          <Button variant="danger" disabled={!s.active} onClick={onSound}>
            <Siren size={16} aria-hidden="true" />
            {t('sirens.sound')}
          </Button>
        )}
        <Button
          variant="secondary"
          busy={test.isPending}
          onClick={() =>
            test.mutate(undefined, {
              onSuccess: (r) => toast(r.virtual ? t('sirens.testVirtual') : t('sirens.testOk', { ms: r.latency_ms })),
              onError: (e) => toast(e.message, 'error'),
            })
          }
        >
          <Radio size={16} aria-hidden="true" />
          {t('sirens.test')}
        </Button>
        <Button variant="ghost" onClick={onEdit}>
          <Pencil size={16} aria-hidden="true" />
          {t('sirens.edit')}
        </Button>
      </div>
      <ConfirmDialog
        open={confirmStop}
        title={t('sirens.stop')}
        body={t('sirens.confirmStop', { name: s.name })}
        confirmLabel={t('sirens.stop')}
        busy={stop.isPending}
        onClose={() => setConfirmStop(false)}
        onConfirm={() =>
          stop.mutate(undefined, { onSuccess: () => (toast(t('sirens.stopped')), setConfirmStop(false)), onError: (e) => (toast(e.message, 'error'), setConfirmStop(false)) })
        }
      />
    </li>
  )
}

function History() {
  const { t, lang } = useT()
  const acts = useSirenActivations()
  const items = acts.data?.items || []
  if (acts.isLoading) return <Loading />
  if (acts.error) return <ErrorNote error={acts.error} onRetry={acts.refetch} />
  if (!items.length) return <p className="text-sm text-muted">{t('sirens.historyEmpty')}</p>
  return (
    <ol className="space-y-2">
      {items.map((a) => (
        <li key={a.id} className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-sm">
          <time className="w-32 shrink-0 text-muted tabular" dateTime={a.created_at}>
            {formatDateTime(a.created_at, lang)}
          </time>
          <span className="min-w-0 flex-1">
            <span className="font-semibold">{a.siren_name}</span> ({a.zone_name}) · {t(`sirens.status.${a.status}`)}
            {a.stop_reason && ` · ${t(`sirens.stopReason.${a.stop_reason}`)}`} · {t(`sirens.source.${a.source}`)}
            {a.reason && a.source === 'manual' && ` · “${a.reason}”`}
          </span>
        </li>
      ))}
    </ol>
  )
}

export default function SirensPage() {
  const { t } = useT()
  const sirens = useSirens()
  const [editing, setEditing] = useState(null)
  const [sounding, setSounding] = useState(null)
  const [tone, setTone] = useState(false)
  const items = sirens.data?.items || []
  const virtualActive = items.some((s) => s.virtual && s.state === 'active')
  useTone(tone && virtualActive)

  return (
    <Page
      title={t('sirens.title')}
      intro={t('sirens.intro')}
      actions={
        <Button onClick={() => setEditing({})}>
          <Plus size={16} aria-hidden="true" />
          {t('sirens.add')}
        </Button>
      }
    >
      <SirenApprovals />
      {sirens.isLoading && <Loading />}
      {sirens.error && <ErrorNote error={sirens.error} onRetry={sirens.refetch} />}
      {sirens.data && !items.length && <EmptyState icon={Siren} text={t('sirens.empty')} />}
      {items.some((s) => s.virtual) && (
        <label className="mb-3 flex min-h-11 w-fit cursor-pointer items-center gap-2 text-sm font-semibold">
          <input type="checkbox" checked={tone} onChange={(e) => setTone(e.target.checked)} className="size-5 accent-[#1E5450]" />
          {tone ? <Volume2 size={18} aria-hidden="true" /> : <VolumeX size={18} aria-hidden="true" />}
          {t('sirens.tone')}
        </label>
      )}
      <ul className="grid gap-3 lg:grid-cols-2">
        {items.map((s) => (
          <SirenCard key={s.id} s={s} onEdit={() => setEditing(s)} onSound={() => setSounding(s)} />
        ))}
      </ul>
      <Panel title={t('sirens.history')} className="mt-4">
        <History />
      </Panel>
      {editing && <SirenForm siren={editing.id ? editing : null} onClose={() => setEditing(null)} />}
      {sounding && <SoundDialog siren={sounding} onClose={() => setSounding(null)} />}
    </Page>
  )
}
