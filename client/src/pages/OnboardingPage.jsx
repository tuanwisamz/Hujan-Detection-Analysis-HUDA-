import { useState } from 'react'
import { useNavigate } from 'react-router'
import { Button, Loading, useToast } from '../components/ui'
import { useApiMutation, usePutSubscriptions, useZones } from '../hooks/queries'
import { api } from '../lib/api'
import { useT } from '../lib/i18n'
import { LanguageChoice, TelegramLink } from './SettingsPage'

/** First login: pick zones, language, Telegram (arch §8 /onboarding). These ARE ordered steps. */
export default function OnboardingPage() {
  const { t } = useT()
  const toast = useToast()
  const navigate = useNavigate()
  const zones = useZones()
  const [picked, setPicked] = useState([])
  const put = usePutSubscriptions()
  const finish = useApiMutation(() => api('/me', { method: 'PATCH', body: { onboarded: true } }), ['me'])

  const done = async (save) => {
    try {
      if (save && picked.length) await put.mutateAsync(picked.map((zone_id) => ({ zone_id, min_level: 'AMBER' })))
      await finish.mutateAsync()
    } catch (e) {
      toast(e.message, 'error')
    }
    navigate('/app/live', { replace: true })
  }

  return (
    <div className="min-h-full bg-paper px-4 py-10">
      <div className="mx-auto max-w-2xl">
        <p className="text-sm font-semibold text-primary">HUDA</p>
        <h1 className="mt-1 text-3xl font-bold tracking-tight">{t('onboarding.title')}</h1>
        <p className="mt-1 text-muted">{t('app.tagline')}</p>

        <ol className="mt-8 space-y-6">
          <li className="rounded-xl border border-line bg-surface p-5">
            <h2 className="mb-3 text-lg font-bold">1. {t('onboarding.step1')}</h2>
            {zones.isLoading && <Loading />}
            <div className="flex flex-wrap gap-2">
              {(zones.data?.items || []).map((z) => {
                const on = picked.includes(z.id)
                return (
                  <button
                    key={z.id}
                    type="button"
                    aria-pressed={on}
                    onClick={() => setPicked((p) => (on ? p.filter((x) => x !== z.id) : [...p, z.id]))}
                    className={`min-h-11 rounded-full border px-4 text-sm font-semibold ${on ? 'border-primary bg-primary text-white' : 'border-line bg-surface hover:border-ink/40'}`}
                  >
                    {z.name}
                  </button>
                )
              })}
            </div>
          </li>
          <li className="rounded-xl border border-line bg-surface p-5">
            <h2 className="mb-3 text-lg font-bold">2. {t('onboarding.step2')}</h2>
            <LanguageChoice />
          </li>
          <li className="rounded-xl border border-line bg-surface p-5">
            <h2 className="mb-3 text-lg font-bold">3. {t('onboarding.step3')}</h2>
            <TelegramLink />
          </li>
        </ol>

        <div className="mt-8 flex flex-wrap gap-3">
          <Button onClick={() => done(true)} busy={put.isPending || finish.isPending}>
            {t('onboarding.finish')}
          </Button>
          <Button variant="ghost" onClick={() => done(false)}>
            {t('onboarding.skip')}
          </Button>
        </div>
      </div>
    </div>
  )
}
