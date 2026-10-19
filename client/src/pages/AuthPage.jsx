import { SignIn, SignUp } from '@clerk/react'
import { Link, Navigate, useSearchParams } from 'react-router'
import { LEVEL_ORDER, LEVELS } from '../lib/levels'
import { useAppAuth } from '../lib/auth'
import { useT } from '../lib/i18n'

/** Clerk sign-in / sign-up (email or Google), framed with what HUDA does. */
export default function AuthPage({ mode = 'sign-in' }) {
  const { t } = useT()
  const auth = useAppAuth()
  const [params] = useSearchParams()
  const redirect = params.get('redirect') || '/app/live'
  if (auth.mock || (auth.isLoaded && auth.isSignedIn)) return <Navigate to={redirect} replace />

  return (
    <div className="grid min-h-full lg:grid-cols-[1fr_1.1fr]">
      <section className="flex flex-col justify-between bg-ink px-6 py-8 text-white sm:px-12 sm:py-12">
        <div>
          <p className="text-3xl font-bold tracking-tight">HUDA</p>
          <p className="mt-1 text-white/75">Hujan Detection Analysis</p>
        </div>
        <div className="my-10 max-w-md">
          <h1 className="text-3xl font-bold leading-tight sm:text-4xl">{t('app.tagline')}</h1>
          <ul className="mt-6 space-y-3">
            {LEVEL_ORDER.map((key) => {
              const l = LEVELS[key]
              return (
                <li key={key} className="flex items-start gap-3">
                  <span className="mt-0.5 inline-flex size-7 shrink-0 items-center justify-center rounded-full" style={{ background: l.color, color: l.text }}>
                    <l.Icon aria-hidden="true" size={16} strokeWidth={2.75} />
                  </span>
                  <span>
                    <span className="font-semibold">{t(`level.${key}`)}</span>
                    <span className="block text-sm text-white/75">{t(`level.${key}.meaning`)}</span>
                  </span>
                </li>
              )
            })}
          </ul>
        </div>
        <p className="text-xs text-white/60">Sime Darby Property townships · Peninsular Malaysia</p>
      </section>
      <section className="flex items-center justify-center px-4 py-10">
        {mode === 'sign-in' ? (
          <SignIn routing="path" path="/sign-in" signUpUrl="/sign-up" fallbackRedirectUrl={redirect} />
        ) : (
          <SignUp routing="path" path="/sign-up" signInUrl="/sign-in" fallbackRedirectUrl="/onboarding" />
        )}
      </section>
    </div>
  )
}

export function NotFound() {
  const { t } = useT()
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 p-8 text-center">
      <p className="text-xl font-bold">{t('notFound')}</p>
      <Link to="/app/live" className="inline-flex min-h-11 items-center font-semibold text-primary underline underline-offset-2">
        {t('notFound.back')}
      </Link>
    </div>
  )
}
