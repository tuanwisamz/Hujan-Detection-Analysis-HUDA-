import { Download, FileText, Printer } from 'lucide-react'
import { useState } from 'react'
import { Button, Dialog, EmptyState, ErrorNote, Field, inputClass, Loading, Page, useToast } from '../components/ui'
import { useApiMutation, useReport, useReports, useZones } from '../hooks/queries'
import { api, download } from '../lib/api'
import { useT } from '../lib/i18n'
import { formatDateTime, fromLocalInput, toLocalInput } from '../lib/time'

/** Minimal Markdown renderer for report content: headings, bold, tables, lists, paragraphs. */
function Markdown({ text }) {
  const inline = (s) =>
    s.split(/(\*\*[^*]+\*\*|_[^_]+_)/g).map((part, i) =>
      part.startsWith('**') ? <strong key={i}>{part.slice(2, -2)}</strong> : part.startsWith('_') && part.endsWith('_') ? <em key={i}>{part.slice(1, -1)}</em> : part,
    )
  const blocks = text.split(/\n\n+/)
  return (
    <div className="space-y-3">
      {blocks.map((b, i) => {
        if (b.startsWith('# ')) return <h2 key={i} className="text-xl font-bold">{b.slice(2)}</h2>
        if (b.startsWith('## ')) return <h3 key={i} className="text-lg font-bold">{b.slice(3)}</h3>
        if (b.startsWith('|')) {
          const rows = b.split('\n').filter((r) => !/^\|\s*-/.test(r)).map((r) => r.split('|').slice(1, -1).map((c) => c.trim()))
          return (
            <div key={i} className="overflow-x-auto">
              <table className="w-full min-w-[36rem] text-left text-sm">
                <thead className="border-b border-line text-muted">
                  <tr>{rows[0].map((c) => <th key={c} className="px-2 py-1.5 font-semibold">{c}</th>)}</tr>
                </thead>
                <tbody className="divide-y divide-line tabular">
                  {rows.slice(1).map((r, j) => (
                    <tr key={j}>{r.map((c, k) => <td key={k} className="px-2 py-1.5">{c}</td>)}</tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        }
        if (b.startsWith('- ')) return <ul key={i} className="list-disc pl-5">{b.split('\n').map((l, j) => <li key={j}>{inline(l.slice(2))}</li>)}</ul>
        return <p key={i} className="max-w-prose">{inline(b)}</p>
      })}
    </div>
  )
}

function ReportView({ id, onClose }) {
  const { t } = useT()
  const report = useReport(id)
  const r = report.data
  const file = (format) => `huda-report-${(r?.created_at || '').slice(0, 10)}.${format}`
  return (
    <Dialog open title={t('reports.title')} onClose={onClose}>
      {report.isLoading && <Loading />}
      {r?.content_md && (
        <>
          <div id="report-print" className="max-h-[60vh] overflow-y-auto rounded-lg border border-line p-4">
            <Markdown text={r.content_md} />
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            <Button variant="secondary" onClick={() => download(`/reports/${id}/download`, { format: 'md' }, file('md'))}>
              <Download size={16} aria-hidden="true" />
              {t('reports.downloadMd')}
            </Button>
            <Button variant="secondary" onClick={() => download(`/reports/${id}/download`, { format: 'csv' }, file('csv'))}>
              <Download size={16} aria-hidden="true" />
              {t('reports.downloadCsv')}
            </Button>
            <Button variant="secondary" onClick={() => window.print()}>
              <Printer size={16} aria-hidden="true" />
              {t('reports.print')}
            </Button>
          </div>
        </>
      )}
    </Dialog>
  )
}

export default function ReportsPage() {
  const { t, lang } = useT()
  const toast = useToast()
  const reports = useReports()
  const zones = useZones()
  const [from, setFrom] = useState(() => toLocalInput(new Date(Date.now() - 7 * 86400000)))
  const [to, setTo] = useState(() => toLocalInput(new Date()))
  const [zoneIds, setZoneIds] = useState([])
  const [viewing, setViewing] = useState(null)
  const create = useApiMutation((body) => api('/reports', { method: 'POST', body }), ['reports'])
  const items = reports.data?.items || []

  const submit = (e) => {
    e.preventDefault()
    create.mutate(
      { type: 'custom', zone_ids: zoneIds, period_start: fromLocalInput(from), period_end: fromLocalInput(to) },
      { onSuccess: () => toast(t('reports.started')), onError: (err) => toast(err.message, 'error') },
    )
  }

  return (
    <Page title={t('reports.title')} intro={t('reports.intro')}>
      <form onSubmit={submit} className="mb-6 grid gap-3 rounded-xl border border-line bg-surface p-4 sm:grid-cols-[1fr_1fr_2fr_auto] sm:items-end">
        <Field label={t('reports.from')}>
          <input type="datetime-local" required value={from} onChange={(e) => setFrom(e.target.value)} className={inputClass} />
        </Field>
        <Field label={t('reports.to')}>
          <input type="datetime-local" required value={to} min={from} onChange={(e) => setTo(e.target.value)} className={inputClass} />
        </Field>
        <Field label={t('reports.zones')}>
          <select multiple value={zoneIds} onChange={(e) => setZoneIds([...e.target.selectedOptions].map((o) => o.value))} className={`${inputClass} h-24 py-1`}>
            {(zones.data?.items || []).map((z) => (
              <option key={z.id} value={z.id}>
                {z.name}
              </option>
            ))}
          </select>
        </Field>
        <Button type="submit" busy={create.isPending}>
          {t('reports.generate')}
        </Button>
      </form>

      {reports.isLoading && <Loading />}
      {reports.error && <ErrorNote error={reports.error} onRetry={reports.refetch} />}
      {reports.data && !items.length && <EmptyState icon={FileText} text={t('reports.empty')} />}
      <ul className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-surface">
        {items.map((r) => (
          <li key={r.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
            <FileText size={18} aria-hidden="true" className="text-muted" />
            <span className="min-w-0 flex-1">
              <span className="block font-semibold">
                {formatDateTime(r.period_start, lang)} – {formatDateTime(r.period_end, lang)}
              </span>
              <span className="block text-sm text-muted">
                {r.type} · {formatDateTime(r.created_at, lang)}
              </span>
            </span>
            {r.status === 'ready' ? (
              <Button variant="secondary" onClick={() => setViewing(r.id)}>
                {t('reports.open')}
              </Button>
            ) : (
              <span className={`text-sm font-semibold ${r.status === 'failed' ? 'text-level-red' : 'text-muted'}`}>
                {r.status === 'failed' ? t('reports.failed') : t('reports.generating')}
              </span>
            )}
          </li>
        ))}
      </ul>
      {viewing && <ReportView id={viewing} onClose={() => setViewing(null)} />}
    </Page>
  )
}
