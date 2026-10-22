import { CloudRain, MapPin, Waves } from 'lucide-react'
import { useState } from 'react'
import { Circle, CircleMarker, MapContainer, TileLayer, Tooltip, useMapEvents } from 'react-leaflet'
import { Button, Dialog, EmptyState, ErrorNote, Field, inputClass, Loading, Page, Panel, useToast } from '../components/ui'
import { useApiMutation, useSensors, useZones } from '../hooks/queries'
import { api } from '../lib/api'
import { useT } from '../lib/i18n'
import { BASEMAP } from '../lib/map'
import { formatDateTime } from '../lib/time'

// JPS rain gauges and river stations near the zones (spec FR-13, implementation-plan-v2 §6.2).

const RIVER_STYLE = {
  NORMAL: 'bg-paper text-ink',
  ALERT: 'bg-level-amber-soft text-ink',
  WARNING: 'bg-level-amber-soft text-ink font-bold',
  DANGER: 'bg-level-red-soft text-level-red font-bold',
}

function SourceStrip({ sources }) {
  const { t, lang } = useT()
  const pages = Object.entries(sources?.pages || {})
  return (
    <Panel title={t('sensors.sources')}>
      {!pages.length ? (
        <p className="text-sm text-muted">{t('sensors.sourcesNone')}</p>
      ) : (
        <ul className="flex flex-wrap gap-2 text-sm">
          {pages.map(([k, v]) => (
            <li key={k} className={`rounded-lg px-2.5 py-1 font-semibold ${v === 'ok' ? 'bg-paper' : 'bg-level-red-soft text-level-red'}`}>
              {t(`sensors.kind.${k.split(':')[0]}`)} · {k.split(':')[1]}: {v === 'ok' ? t('sensors.ok') : t('sensors.failed')}
            </li>
          ))}
        </ul>
      )}
      {sources?.checked_at && <p className="mt-2 text-xs text-muted">{t('sensors.checkedAt', { time: formatDateTime(sources.checked_at, lang) })}</p>}
    </Panel>
  )
}

function Reading({ s }) {
  const { t } = useT()
  const r = s.latest
  if (!r) return <span className="text-muted">{t('sensors.noReading')}</span>
  const age = <span className={r.fresh ? 'text-muted' : 'font-semibold text-level-red'}>{t('sensors.age', { n: r.age_min })}</span>
  if (s.kind === 'rain')
    return (
      <span>
        <span className="font-semibold tabular">{r.rain_1h_mm ?? '–'} mm</span> {t('sensors.lastHour')} · {age}
      </span>
    )
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      {r.indicator && <span className={`rounded px-1.5 py-0.5 text-xs ${RIVER_STYLE[r.indicator]}`}>{t(`sensors.river.${r.indicator}`)}</span>}
      <span className="tabular">{r.water_level_m ?? '–'} m</span> · {age}
    </span>
  )
}

function Quality({ s }) {
  const { t } = useT()
  if (s.lat == null) return <span className="rounded bg-level-red-soft px-1.5 py-0.5 text-xs font-semibold text-level-red">{t('sensors.quality.none')}</span>
  return s.location_quality === 'verified' ? (
    <span className="rounded bg-level-green-soft px-1.5 py-0.5 text-xs font-semibold text-ink">{t(`sensors.quality.${s.location_source || 'admin'}`)}</span>
  ) : (
    <span className="rounded bg-level-amber-soft px-1.5 py-0.5 text-xs font-semibold text-ink">{t('sensors.quality.grid')}</span>
  )
}

function PickPoint({ onPick }) {
  useMapEvents({ click: (e) => onPick([+e.latlng.lat.toFixed(5), +e.latlng.lng.toFixed(5)]) })
  return null
}

/** Admins correct a station's location by typing it or clicking the map (D21). */
function LocationDialog({ station, zones, onClose }) {
  const { t } = useT()
  const toast = useToast()
  const [pos, setPos] = useState(() => [station.lat ?? '', station.lon ?? ''])
  const save = useApiMutation((body) => api(`/admin/sensors/${encodeURIComponent(station.id)}`, { method: 'PATCH', body }), ['sensors'])
  const lat = Number(pos[0])
  const lon = Number(pos[1])
  const valid = pos[0] !== '' && pos[1] !== '' && lat >= 1 && lat <= 7.5 && lon >= 99 && lon <= 105
  const centre = valid ? [lat, lon] : zones[0] ? [zones[0].lat, zones[0].lon] : [3.1, 101.6]
  const submit = () =>
    save.mutate({ lat, lon }, { onSuccess: () => (toast(t('sensors.saved')), onClose()), onError: (e) => toast(e.message, 'error') })
  return (
    <Dialog
      open
      title={t('sensors.editTitle', { name: station.name || station.station_code })}
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button busy={save.isPending} disabled={!valid} onClick={submit}>
            {t('sensors.saveLocation')}
          </Button>
        </>
      }
    >
      <p className="mb-3 text-sm text-muted">{t('sensors.editIntro')}</p>
      <div className="mb-3 grid grid-cols-2 gap-3">
        <Field label={t('sensors.lat')}>
          <input type="number" step="0.00001" value={pos[0]} onChange={(e) => setPos([e.target.value, pos[1]])} className={inputClass} />
        </Field>
        <Field label={t('sensors.lon')}>
          <input type="number" step="0.00001" value={pos[1]} onChange={(e) => setPos([pos[0], e.target.value])} className={inputClass} />
        </Field>
      </div>
      <div className="h-64 overflow-hidden rounded-lg border border-line">
        <MapContainer center={centre} zoom={12} className="h-full w-full">
          <TileLayer url={BASEMAP} className="basemap" maxZoom={19} attribution="© OpenStreetMap contributors" />
          {zones.map((z) => (
            <Circle key={z.id} center={[z.lat, z.lon]} radius={z.radius_m || 2500} pathOptions={{ color: '#1E5450', weight: 1, fillOpacity: 0.08 }}>
              <Tooltip>{z.name}</Tooltip>
            </Circle>
          ))}
          {valid && <CircleMarker center={[lat, lon]} radius={8} pathOptions={{ color: '#18302E', fillColor: '#1F6FB2', fillOpacity: 0.9 }} />}
          <PickPoint onPick={setPos} />
        </MapContainer>
      </div>
    </Dialog>
  )
}

export default function SensorsPage() {
  const { t } = useT()
  const [filters, setFilters] = useState({ kind: '', zone_id: '', needs_location: false, stale: false })
  const sensors = useSensors(filters)
  const zones = useZones()
  const [editing, setEditing] = useState(null)
  const items = sensors.data?.items || []
  const set = (k) => (e) => setFilters((f) => ({ ...f, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value }))

  return (
    <Page title={t('sensors.title')} intro={t('sensors.intro')}>
      <div className="space-y-4">
        <SourceStrip sources={sensors.data?.sources} />
        <div className="flex flex-wrap items-end gap-3">
          <label className="text-sm">
            <span className="mb-1 block font-semibold">{t('sensors.kind')}</span>
            <select value={filters.kind} onChange={set('kind')} className={`${inputClass} w-40`}>
              <option value="">{t('logs.all')}</option>
              <option value="rain">{t('sensors.kind.rain')}</option>
              <option value="river">{t('sensors.kind.river')}</option>
            </select>
          </label>
          <label className="text-sm">
            <span className="mb-1 block font-semibold">{t('sensors.zone')}</span>
            <select value={filters.zone_id} onChange={set('zone_id')} className={`${inputClass} w-56`}>
              <option value="">{t('logs.all')}</option>
              {(zones.data?.items || []).map((z) => (
                <option key={z.id} value={z.id}>
                  {z.name}
                </option>
              ))}
            </select>
          </label>
          <label className="flex min-h-11 items-center gap-2 text-sm font-semibold">
            <input type="checkbox" checked={filters.needs_location} onChange={set('needs_location')} className="size-5 accent-primary" />
            {t('sensors.needsLocation')}
          </label>
          <label className="flex min-h-11 items-center gap-2 text-sm font-semibold">
            <input type="checkbox" checked={filters.stale} onChange={set('stale')} className="size-5 accent-primary" />
            {t('sensors.staleOnly')}
          </label>
        </div>

        {sensors.isLoading && <Loading />}
        {sensors.error && <ErrorNote error={sensors.error} onRetry={sensors.refetch} />}
        {sensors.data && !items.length && <EmptyState icon={MapPin} text={t('sensors.empty')} />}
        {items.length > 0 && (
          <p className="text-sm text-muted">{t('sensors.count', { n: items.length })}</p>
        )}
        <ul className="space-y-2">
          {items.map((s) => {
            const Icon = s.kind === 'rain' ? CloudRain : Waves
            const nearest = s.zones?.[0]
            return (
              <li key={s.id} className="flex flex-wrap items-start gap-3 rounded-xl border border-line bg-surface p-3">
                <Icon size={20} aria-hidden="true" className="mt-0.5 shrink-0 text-primary" />
                <div className="min-w-0 flex-1">
                  <p className="font-semibold">
                    {s.name || s.station_code} <span className="text-sm font-normal text-muted">· {s.station_code} · {t(`sensors.kind.${s.kind}`)}</span>
                  </p>
                  <p className="text-sm text-muted">{[s.district, s.state].filter(Boolean).join(', ')}</p>
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-sm">
                    <Quality s={s} />
                    {nearest && (
                      <span className={nearest.in_range ? '' : 'text-muted'}>
                        {t('sensors.nearest', { zone: nearest.name, km: nearest.distance_km })}
                      </span>
                    )}
                  </div>
                </div>
                <div className="text-sm sm:text-right">
                  <Reading s={s} />
                </div>
                <Button variant="secondary" onClick={() => setEditing(s)} className="shrink-0">
                  <MapPin size={16} aria-hidden="true" />
                  {t('sensors.editLocation')}
                </Button>
              </li>
            )
          })}
        </ul>
      </div>
      {editing && <LocationDialog station={editing} zones={zones.data?.items || []} onClose={() => setEditing(null)} />}
    </Page>
  )
}
