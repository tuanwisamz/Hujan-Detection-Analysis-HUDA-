import { useInfiniteQuery } from '@tanstack/react-query'
import { BellOff } from 'lucide-react'
import { useState } from 'react'
import RiskBadge from '../components/RiskBadge'
import { Button, EmptyState, ErrorNote, inputClass, Loading, Page, Tabs } from '../components/ui'
import { useAlerts, useRuns } from '../hooks/queries'
import { api } from '../lib/api'
import { useT } from '../lib/i18n'
import { formatDateTime } from '../lib/time'

function UserLogs() {
  const { t, lang } = useT()
  const alerts = useAlerts()
  const items = alerts.data?.items || []
  return (
    <Page title={t('logs.title')} intro={t('logs.intro')}>
      {alerts.isLoading && <Loading />}
      {alerts.error && <ErrorNote error={alerts.error} onRetry={alerts.refetch} />}
      {alerts.data && !items.length && <EmptyState icon={BellOff} text={t('logs.empty')} />}
      <ol className="space-y-3">
        {items.map((a) => (
          <li key={a.id} className="rounded-xl border border-line bg-surface p-4">
            <div className="flex flex-wrap items-center gap-2">
              <RiskBadge value={a.level} size="sm" />
              <span className="font-semibold">{a.zone}</span>
              <time className="ml-auto text-sm text-muted tabular" dateTime={a.sent_at}>
                {formatDateTime(a.sent_at, lang)}
              </time>
            </div>
            {(lang === 'ms' ? a.message_ms : a.message_en) && <p className="mt-2">{lang === 'ms' ? a.message_ms : a.message_en}</p>}
          </li>
        ))}
      </ol>
    </Page>
  )
}

const CATEGORIES = ['ingest', 'model', 'agent', 'alert', 'auth', 'admin']
const SEVERITIES = ['info', 'warn', 'error']
const SEVERITY_STYLE = { info: 'bg-paper text-muted', warn: 'bg-level-amber-soft text-ink', error: 'bg-level-red-soft text-level-red' }

function EventLog() {
  const { t, lang } = useT()
  const [filters, setFilters] = useState({ category: '', severity: '', q: '' })
  const [q, setQ] = useState('')
  const logs = useInfiniteQuery({
    queryKey: ['adminLogs', filters],
    queryFn: ({ pageParam }) => api('/admin/logs', { query: { ...filters, cursor: pageParam, limit: 50 } }),
    initialPageParam: undefined,
    getNextPageParam: (last) => last.next_cursor || undefined,
  })
  const rows = logs.data?.pages.flatMap((p) => p.items) || []
  const select = (key, options) => (
    <label className="text-sm">
      <span className="mb-1 block font-semibold">{t(`logs.${key}`)}</span>
      <select value={filters[key]} onChange={(e) => setFilters((f) => ({ ...f, [key]: e.target.value }))} className={`${inputClass} w-40`}>
        <option value="">{t('logs.all')}</option>
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    </label>
  )
  return (
    <>
      <form
        className="mb-4 flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault()
          setFilters((f) => ({ ...f, q }))
        }}
      >
        {select('category', CATEGORIES)}
        {select('severity', SEVERITIES)}
        <label className="min-w-48 flex-1 text-sm">
          <span className="mb-1 block font-semibold">{t('logs.search')}</span>
          <input type="search" value={q} onChange={(e) => setQ(e.target.value)} onBlur={() => setFilters((f) => ({ ...f, q }))} className={inputClass} />
        </label>
      </form>
      {logs.isLoading && <Loading />}
      {logs.error && <ErrorNote error={logs.error} onRetry={logs.refetch} />}
      <div className="overflow-x-auto rounded-xl border border-line bg-surface">
        <table className="w-full min-w-[40rem] text-left text-sm">
          <tbody className="divide-y divide-line">
            {rows.map((r) => (
              <tr key={r.id}>
                <td className="whitespace-nowrap px-4 py-2 text-muted tabular">{formatDateTime(r.ts, lang)}</td>
                <td className="px-2 py-2">
                  <span className={`rounded px-1.5 py-0.5 text-xs font-semibold ${SEVERITY_STYLE[r.severity] || ''}`}>{r.severity}</span>
                </td>
                <td className="px-2 py-2 font-semibold">{r.category}</td>
                <td className="px-2 py-2">{r.message}</td>
                <td className="px-4 py-2 text-muted">{r.actor}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {logs.hasNextPage && (
        <Button variant="secondary" className="mt-3" busy={logs.isFetchingNextPage} onClick={() => logs.fetchNextPage()}>
          {t('logs.more')}
        </Button>
      )}
    </>
  )
}

function RunsTable() {
  const { t, lang } = useT()
  const runs = useRuns()
  if (runs.isLoading) return <Loading />
  if (runs.error) return <ErrorNote error={runs.error} onRetry={runs.refetch} />
  return (
    <div className="overflow-x-auto rounded-xl border border-line bg-surface">
      <table className="w-full min-w-[44rem] text-left text-sm">
        <thead className="border-b border-line text-muted">
          <tr>
            <th className="px-4 py-2.5 font-semibold">{t('runs.started')}</th>
            <th className="px-4 py-2.5 font-semibold">{t('runs.status')}</th>
            <th className="px-4 py-2.5 font-semibold">{t('runs.duration')}</th>
            <th className="px-4 py-2.5 font-semibold">{t('runs.sources')}</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {(runs.data?.items || []).map((r) => (
            <tr key={r.id}>
              <td className="whitespace-nowrap px-4 py-2 tabular">{formatDateTime(r.started_at, lang)}</td>
              <td className="px-4 py-2">
                <span className={`rounded px-1.5 py-0.5 text-xs font-semibold ${r.status === 'ok' ? 'bg-level-green-soft' : r.status === 'failed' ? 'bg-level-red-soft text-level-red' : 'bg-level-amber-soft'}`}>
                  {r.status || 'running'}
                </span>
              </td>
              <td className="px-4 py-2 tabular">{r.duration_s != null ? `${r.duration_s} s` : '–'}</td>
              <td className="px-4 py-2 text-muted">
                {Object.entries(r.sources || {})
                  .filter(([k]) => ['radar', 'open_meteo', 'met_warnings', 'nowcast', 'model', 'alerts', 'mode'].includes(k))
                  .map(([k, v]) => `${k}: ${v}`)
                  .join(', ')}
                {r.error && <span className="block text-level-red">{r.error}</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function AdminLogs() {
  const { t } = useT()
  const [tab, setTab] = useState('logs')
  return (
    <Page title={t('logs.adminTitle')}>
      <Tabs
        label={t('logs.adminTitle')}
        value={tab}
        onChange={setTab}
        tabs={[
          { value: 'logs', label: t('logs.tabLogs') },
          { value: 'runs', label: t('logs.tabRuns') },
        ]}
      />
      {tab === 'logs' ? <EventLog /> : <RunsTable />}
    </Page>
  )
}

export default function LogsPage({ admin = false }) {
  return admin ? <AdminLogs /> : <UserLogs />
}
