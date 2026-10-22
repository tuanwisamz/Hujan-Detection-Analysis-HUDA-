import { Bot, ExternalLink, Send } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import { Button, ErrorNote, Field, inputClass, Loading, Page, Panel, useToast } from '../components/ui'
import { useAdminSettings, useApiMutation, useMe, useRuns } from '../hooks/queries'
import { api } from '../lib/api'
import { useT } from '../lib/i18n'

export function LanguageChoice() {
  const { t, lang, setLang } = useT()
  const toast = useToast()
  const save = useApiMutation((language) => api('/me', { method: 'PATCH', body: { language } }), ['me'])
  return (
    <fieldset>
      <legend className="mb-2 text-sm font-semibold">{t('settings.language')}</legend>
      <div className="flex gap-2">
        {[
          ['en', 'English'],
          ['ms', 'Bahasa Melayu'],
        ].map(([code, label]) => (
          <label key={code} className={`flex min-h-11 cursor-pointer items-center gap-2 rounded-lg border px-4 ${lang === code ? 'border-ink bg-paper font-semibold' : 'border-line'}`}>
            <input
              type="radio"
              name="language"
              checked={lang === code}
              onChange={() => {
                setLang(code)
                save.mutate(code, { onSuccess: () => toast(t('settings.saved')) })
              }}
            />
            {label}
          </label>
        ))}
      </div>
    </fieldset>
  )
}

export function TelegramLink() {
  const { t } = useT()
  const toast = useToast()
  const me = useMe()
  const [link, setLink] = useState(null)
  const create = useApiMutation(() => api('/me/telegram/link', { method: 'POST' }), [])
  const unlink = useApiMutation(() => api('/me/telegram/link', { method: 'DELETE' }), ['me'])
  const linked = me.data?.telegram_linked
  return (
    <div>
      <p className="mb-3">{linked ? t('settings.telegramLinked') : t('settings.telegramNot')}</p>
      {linked ? (
        <Button variant="secondary" busy={unlink.isPending} onClick={() => unlink.mutate(undefined, { onSuccess: () => toast(t('settings.saved')) })}>
          {t('settings.telegramUnlink')}
        </Button>
      ) : link ? (
        <a
          href={link.deep_link}
          target="_blank"
          rel="noreferrer"
          onClick={() => setTimeout(() => me.refetch(), 5000)}
          className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-primary px-4 text-sm font-semibold text-white hover:bg-primary-strong"
        >
          <ExternalLink size={16} aria-hidden="true" />
          {t('settings.telegramOpen')}
        </a>
      ) : (
        <Button busy={create.isPending} onClick={() => create.mutate(undefined, { onSuccess: setLink, onError: (e) => toast(e.message, 'error') })}>
          <Send size={16} aria-hidden="true" />
          {t('settings.telegramLink')}
        </Button>
      )}
      <p className="mt-3 text-sm text-muted">{t('settings.channel')}</p>
    </div>
  )
}

function NumberField({ label, value, onChange, min, max, step = 1, error }) {
  return (
    <Field label={label} error={error} hint={`${min}–${max}`}>
      <input type="number" min={min} max={max} step={step} required value={value} onChange={(e) => onChange(e.target.value)} className={inputClass} />
    </Field>
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

/** Thresholds are bounded and Amber can't exceed Red (spec §10.1 Constraints). */
function AdminSettings() {
  const { t } = useT()
  const toast = useToast()
  const settings = useAdminSettings()
  const runs = useRuns()
  const [draft, setDraft] = useState(null)
  const save = useApiMutation((body) => api('/admin/settings', { method: 'PATCH', body }), ['settings'])
  if (settings.isLoading) return <Loading />
  if (settings.error) return <ErrorNote error={settings.error} onRetry={settings.refetch} />
  const s = draft || settings.data
  const th = s.thresholds
  const setTh = (k) => (v) => setDraft({ ...s, thresholds: { ...th, [k]: v } })
  const set = (k) => (v) => setDraft({ ...s, [k]: v })
  const rateErr = Number(th.amber_rate_mmh) >= Number(th.red_rate_mmh) ? t('settings.error.order') : null
  const pErr = Number(th.amber_p) >= Number(th.red_p) ? t('settings.error.order') : null
  const veryErr = Number(th.red_rate_mmh) >= Number(th.very_heavy_mmh) ? t('settings.error.veryHeavy') : null
  const gaugeErr = Number(th.gauge_amber_1h_mm) >= Number(th.gauge_red_1h_mm) ? t('settings.error.order') : null
  const stepErr = (k) => (Number(th[k]) % 10 ? t('settings.error.step10') : null)
  const errors = [rateErr, pErr, veryErr, gaugeErr, stepErr('red_duration_min'), stepErr('very_heavy_duration_min')]
  const sources = runs.data?.items?.[0]?.sources || {}

  const submit = (e) => {
    e.preventDefault()
    if (errors.some(Boolean)) return
    const body = {
      thresholds: Object.fromEntries(Object.entries(th).map(([k, v]) => [k, Number(v)])),
      pipeline_enabled: s.pipeline_enabled,
    }
    save.mutate(body, { onSuccess: () => (setDraft(null), toast(t('settings.saved'))), onError: (err) => toast(err.message, 'error') })
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <Panel title={t('settings.thresholds')}>
        <p className="mb-3 text-sm text-muted">{t('settings.thresholdsIntro')}</p>
        <div className="grid gap-3 sm:grid-cols-2">
          <NumberField label={t('settings.amberRate')} value={th.amber_rate_mmh} onChange={setTh('amber_rate_mmh')} min={0} max={100} step={0.5} error={rateErr} />
          <NumberField label={t('settings.redRate')} value={th.red_rate_mmh} onChange={setTh('red_rate_mmh')} min={0} max={100} step={0.5} />
          <NumberField label={t('settings.amberP')} value={th.amber_p} onChange={setTh('amber_p')} min={0} max={1} step={0.01} error={pErr} />
          <NumberField label={t('settings.redP')} value={th.red_p} onChange={setTh('red_p')} min={0} max={1} step={0.01} />
          <NumberField label={t('settings.wet')} value={th.wet_ground_mm24h} onChange={setTh('wet_ground_mm24h')} min={0} max={500} />
        </div>
      </Panel>
      <Panel title={t('settings.redNeeds')}>
        <p className="mb-3 text-sm text-muted">{t('settings.redNeedsIntro')}</p>
        <div className="grid gap-3 sm:grid-cols-2">
          <NumberField label={t('settings.redArea')} value={th.red_area_frac} onChange={setTh('red_area_frac')} min={0.05} max={1} step={0.05} />
          <NumberField label={t('settings.redDuration')} value={th.red_duration_min} onChange={setTh('red_duration_min')} min={10} max={60} step={10} error={stepErr('red_duration_min')} />
          <NumberField label={t('settings.redAccum')} value={th.red_accum_1h_mm} onChange={setTh('red_accum_1h_mm')} min={5} max={200} />
          <NumberField label={t('settings.veryHeavy')} value={th.very_heavy_mmh} onChange={setTh('very_heavy_mmh')} min={0} max={150} error={veryErr} />
          <NumberField label={t('settings.veryHeavyArea')} value={th.very_heavy_area_frac} onChange={setTh('very_heavy_area_frac')} min={0.05} max={1} step={0.05} />
          <NumberField label={t('settings.veryHeavyDuration')} value={th.very_heavy_duration_min} onChange={setTh('very_heavy_duration_min')} min={10} max={60} step={10} error={stepErr('very_heavy_duration_min')} />
        </div>
      </Panel>
      <Panel title={t('settings.sensorThresholds')}>
        <p className="mb-3 text-sm text-muted">{t('settings.sensorThresholdsIntro')}</p>
        <div className="grid gap-3 sm:grid-cols-2">
          <NumberField label={t('settings.gaugeAmber')} value={th.gauge_amber_1h_mm} onChange={setTh('gauge_amber_1h_mm')} min={1} max={200} error={gaugeErr} />
          <NumberField label={t('settings.gaugeRed')} value={th.gauge_red_1h_mm} onChange={setTh('gauge_red_1h_mm')} min={1} max={300} />
          <NumberField label={t('settings.gaugeRed3h')} value={th.gauge_red_3h_mm} onChange={setTh('gauge_red_3h_mm')} min={1} max={500} />
          <NumberField label={t('settings.sensorConfirm')} value={th.sensor_confirm_1h_mm} onChange={setTh('sensor_confirm_1h_mm')} min={1} max={100} />
        </div>
      </Panel>
      <Panel title={t('settings.alerts')}>
        <Toggle label={t('settings.pipeline')} hint={!s.pipeline_enabled ? t('settings.pipelineOff') : null} checked={s.pipeline_enabled} onChange={set('pipeline_enabled')} />
        <div className="mt-3 flex flex-wrap items-center gap-3 rounded-lg bg-paper px-3 py-3">
          <p className="min-w-0 flex-1 text-sm">{t('settings.automationMoved')}</p>
          <Link to="/admin/automation" className="inline-flex min-h-11 items-center gap-2 rounded-lg border border-ink/25 bg-surface px-4 text-sm font-semibold hover:border-ink/50">
            <Bot size={16} aria-hidden="true" />
            {t('settings.automationOpen')}
          </Link>
        </div>
      </Panel>
      <Panel title={t('settings.sources')}>
        <ul className="flex flex-wrap gap-2 text-sm">
          {['radar', 'open_meteo', 'met_warnings', 'infobanjir', 'nowcast', 'model'].map((k) => (
            <li key={k} className={`rounded-lg px-2.5 py-1 font-semibold ${sources[k] === 'failed' ? 'bg-level-red-soft text-level-red' : 'bg-paper'}`}>
              {k}: {sources[k] ?? '–'}
            </li>
          ))}
        </ul>
      </Panel>
      <Button type="submit" busy={save.isPending} disabled={!draft || errors.some(Boolean)}>
        {t('settings.save')}
      </Button>
    </form>
  )
}

export default function SettingsPage({ admin = false }) {
  const { t } = useT()
  return (
    <Page title={t('settings.title')}>
      <div className="space-y-4">
        <Panel title={t('settings.profile')}>
          <LanguageChoice />
        </Panel>
        <Panel title={t('settings.telegram')}>
          <TelegramLink />
        </Panel>
        {admin && <AdminSettings />}
      </div>
    </Page>
  )
}
