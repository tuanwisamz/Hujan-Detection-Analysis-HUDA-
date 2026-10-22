import { Pencil, Plus, Search } from 'lucide-react'
import { useMemo, useState } from 'react'
import RadarMap from '../components/RadarMap'
import RiskBadge from '../components/RiskBadge'
import { Button, ConfirmDialog, Dialog, ErrorNote, Field, inputClass, Loading, Page, useToast } from '../components/ui'
import { useApiMutation, useLiveSummary, usePutSubscriptions, useSubscriptions, useZones } from '../hooks/queries'
import { api } from '../lib/api'
import { LEVEL_ORDER } from '../lib/levels'
import { useT } from '../lib/i18n'

function useLevels() {
  const live = useLiveSummary()
  return useMemo(() => Object.fromEntries((live.data?.zones || []).map((z) => [z.id, z.level])), [live.data])
}

function groupByState(zones) {
  const groups = {}
  for (const z of zones) (groups[z.state || '–'] ||= []).push(z)
  return Object.entries(groups)
}

// ---- Resident: follow zones and choose the minimum alert level ----

function UserZones() {
  const { t } = useT()
  const toast = useToast()
  const zones = useZones()
  const subs = useSubscriptions()
  const put = usePutSubscriptions()
  const levels = useLevels()
  const [query, setQuery] = useState('')
  const [draft, setDraft] = useState(null)
  const current = draft ?? Object.fromEntries((subs.data?.subscriptions || []).map((s) => [s.zone_id, s.min_level]))
  const dirty = draft !== null

  const list = (zones.data?.items || []).filter((z) => z.name.toLowerCase().includes(query.toLowerCase()))
  const toggle = (id) => {
    const next = { ...current }
    if (next[id]) delete next[id]
    else next[id] = 'AMBER'
    setDraft(next)
  }
  const save = () =>
    put.mutate(
      Object.entries(current).map(([zone_id, min_level]) => ({ zone_id, min_level })),
      {
        onSuccess: () => {
          setDraft(null)
          toast(t('zones.saved'))
        },
        onError: (e) => toast(e.message, 'error'),
      },
    )

  return (
    <Page
      title={t('zones.title')}
      intro={t('zones.intro')}
      actions={
        <Button onClick={save} busy={put.isPending} disabled={!dirty}>
          {t('common.save')}
        </Button>
      }
    >
      <label className="relative mb-4 block max-w-sm">
        <span className="sr-only">{t('zones.search')}</span>
        <Search size={18} aria-hidden="true" className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
        <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t('zones.search')} className={`${inputClass} pl-10`} />
      </label>
      {(zones.isLoading || subs.isLoading) && <Loading />}
      {zones.error && <ErrorNote error={zones.error} onRetry={zones.refetch} />}
      <div className="space-y-6">
        {groupByState(list).map(([state, items]) => (
          <section key={state}>
            <h2 className="mb-2 text-lg font-bold">{state}</h2>
            <ul className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-surface">
              {items.map((z) => {
                const on = !!current[z.id]
                return (
                  <li key={z.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
                    <label className="flex min-h-11 flex-1 cursor-pointer items-center gap-3">
                      <input type="checkbox" checked={on} onChange={() => toggle(z.id)} className="size-5 accent-primary" />
                      <span className="min-w-0">
                        <span className="block font-semibold">{z.name}</span>
                        <span className="block text-sm text-muted">{z.district}</span>
                      </span>
                    </label>
                    <RiskBadge value={levels[z.id]} size="sm" />
                    {on && (
                      <label className="flex items-center gap-2 text-sm">
                        <span className="text-muted">{t('zones.minLevel')}</span>
                        <select
                          value={current[z.id]}
                          onChange={(e) => setDraft({ ...current, [z.id]: e.target.value })}
                          className="min-h-11 rounded-lg border border-line bg-surface px-2"
                        >
                          {LEVEL_ORDER.slice(1).map((l) => (
                            <option key={l} value={l}>
                              {t(`level.${l}`)}
                            </option>
                          ))}
                        </select>
                      </label>
                    )}
                  </li>
                )
              })}
            </ul>
          </section>
        ))}
      </div>
    </Page>
  )
}

// ---- Admin: CRUD ----

const EMPTY = { name: '', slug: '', state: 'Selangor', district: '', met_location_id: '', match_terms: '', lat: '', lon: '', radius_m: 2500, active: true }

const slugify = (s) =>
  s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '')

function ZoneForm({ initial, onClose }) {
  const { t } = useT()
  const toast = useToast()
  const [form, setForm] = useState(() => ({ ...EMPTY, ...initial, match_terms: (initial?.match_terms || []).join(', ') }))
  const [error, setError] = useState(null)
  const editing = !!initial?.id
  const save = useApiMutation(
    (body) => (editing ? api(`/admin/zones/${initial.id}`, { method: 'PATCH', body }) : api('/admin/zones', { method: 'POST', body })),
    ['zones', 'live'],
  )
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value, ...(k === 'name' && !editing ? { slug: slugify(e.target.value) } : {}) }))
  const submit = (e) => {
    e.preventDefault()
    setError(null)
    const body = {
      ...form,
      lat: Number(form.lat),
      lon: Number(form.lon),
      radius_m: Number(form.radius_m),
      met_location_id: form.met_location_id || null,
      match_terms: form.match_terms.split(',').map((s) => s.trim()).filter(Boolean),
    }
    delete body.id
    save.mutate(body, {
      onSuccess: () => {
        toast(editing ? t('zones.updated') : t('zones.created'))
        onClose()
      },
      onError: (err) => setError(err.message),
    })
  }
  const preview = form.lat && form.lon ? [{ id: 'preview', name: form.name || '…', lat: Number(form.lat), lon: Number(form.lon), radius_m: Number(form.radius_m), level: null }] : []

  return (
    <Dialog open title={editing ? t('zones.edit') : t('zones.add')} onClose={onClose}>
      <form onSubmit={submit} className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t('field.name')}>
            <input required value={form.name} onChange={set('name')} className={inputClass} />
          </Field>
          <Field label={t('field.slug')}>
            <input required pattern="[a-z0-9]+(-[a-z0-9]+)*" value={form.slug} onChange={set('slug')} className={inputClass} />
          </Field>
          <Field label={t('field.state')}>
            <input value={form.state} onChange={set('state')} className={inputClass} />
          </Field>
          <Field label={t('field.district')}>
            <input required value={form.district} onChange={set('district')} className={inputClass} />
          </Field>
        </div>
        <div className="h-44 overflow-hidden rounded-lg border border-line">
          <RadarMap zones={preview} onPick={({ lat, lon }) => setForm((f) => ({ ...f, lat, lon }))} />
        </div>
        <p className="text-xs text-muted">{t('zones.mapHint')}</p>
        <div className="grid grid-cols-3 gap-3">
          <Field label={t('field.lat')}>
            <input required type="number" step="0.0001" min="1" max="7.5" value={form.lat} onChange={set('lat')} className={inputClass} />
          </Field>
          <Field label={t('field.lon')}>
            <input required type="number" step="0.0001" min="99" max="105" value={form.lon} onChange={set('lon')} className={inputClass} />
          </Field>
          <Field label={t('field.radius')}>
            <input required type="number" step="100" min="500" max="20000" value={form.radius_m} onChange={set('radius_m')} className={inputClass} />
          </Field>
        </div>
        <Field label={t('field.matchTerms')}>
          <input value={form.match_terms} onChange={set('match_terms')} className={inputClass} />
        </Field>
        <Field label={t('field.metId')}>
          <input value={form.met_location_id || ''} onChange={set('met_location_id')} placeholder="Ds056" className={inputClass} />
        </Field>
        {error && <ErrorNote error={{ message: error }} />}
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="secondary" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button type="submit" busy={save.isPending}>
            {t('common.save')}
          </Button>
        </div>
      </form>
    </Dialog>
  )
}

function AdminZones() {
  const { t } = useT()
  const toast = useToast()
  const zones = useZones('all')
  const levels = useLevels()
  const [editing, setEditing] = useState(null)
  const [confirm, setConfirm] = useState(null)
  const setActive = useApiMutation(({ id, active }) => (active ? api(`/admin/zones/${id}`, { method: 'PATCH', body: { active: true } }) : api(`/admin/zones/${id}`, { method: 'DELETE' })), ['zones', 'live'])

  return (
    <Page
      title={t('zones.title')}
      actions={
        <Button onClick={() => setEditing({})}>
          <Plus size={16} aria-hidden="true" />
          {t('zones.add')}
        </Button>
      }
    >
      {zones.isLoading && <Loading />}
      {zones.error && <ErrorNote error={zones.error} onRetry={zones.refetch} />}
      <div className="overflow-x-auto rounded-xl border border-line bg-surface">
        <table className="w-full min-w-[40rem] text-left text-sm">
          <thead className="border-b border-line text-muted">
            <tr>
              <th className="px-4 py-2.5 font-semibold">{t('field.name')}</th>
              <th className="px-4 py-2.5 font-semibold">{t('field.district')}</th>
              <th className="px-4 py-2.5 font-semibold">{t('live.legend')}</th>
              <th className="px-4 py-2.5 font-semibold">{t('field.radius')}</th>
              <th className="px-4 py-2.5" />
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {(zones.data?.items || []).map((z) => (
              <tr key={z.id} className={z.active ? '' : 'text-muted'}>
                <td className="px-4 py-2 font-semibold">
                  {z.name}
                  {!z.active && <span className="ml-2 rounded bg-ink/10 px-1.5 text-xs">{t('zones.inactive')}</span>}
                </td>
                <td className="px-4 py-2">
                  {z.district}, {z.state}
                </td>
                <td className="px-4 py-2">{z.active && <RiskBadge value={levels[z.id]} size="sm" />}</td>
                <td className="px-4 py-2 tabular">{z.radius_m}</td>
                <td className="px-4 py-2">
                  <div className="flex justify-end gap-1">
                    <Button variant="ghost" onClick={() => setEditing(z)} aria-label={`${t('zones.edit')}: ${z.name}`}>
                      <Pencil size={16} aria-hidden="true" />
                    </Button>
                    {z.active ? (
                      <Button variant="danger" onClick={() => setConfirm(z)}>
                        {t('zones.deactivate')}
                      </Button>
                    ) : (
                      <Button variant="secondary" onClick={() => setActive.mutate({ id: z.id, active: true }, { onSuccess: () => toast(t('zones.updated')) })}>
                        {t('zones.activate')}
                      </Button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {editing && <ZoneForm initial={editing.id ? editing : null} onClose={() => setEditing(null)} />}
      <ConfirmDialog
        open={!!confirm}
        danger
        title={t('zones.deactivate')}
        body={confirm ? t('zones.confirmDeactivate', { name: confirm.name }) : ''}
        confirmLabel={t('zones.deactivate')}
        busy={setActive.isPending}
        onClose={() => setConfirm(null)}
        onConfirm={() =>
          setActive.mutate(
            { id: confirm.id, active: false },
            {
              onSuccess: () => {
                toast(t('zones.updated'))
                setConfirm(null)
              },
              onError: (e) => toast(e.message, 'error'),
            },
          )
        }
      />
    </Page>
  )
}

export default function ZonesPage({ admin = false }) {
  return admin ? <AdminZones /> : <UserZones />
}
