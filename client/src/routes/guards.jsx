import { Navigate, Outlet, useLocation, useParams } from 'react-router'
import { ErrorNote } from '../components/ui'
import { useMe } from '../hooks/queries'
import { useAppAuth } from '../lib/auth'

function Splash() {
  return (
    <div className="flex h-full items-center justify-center" aria-busy="true">
      <p className="text-2xl font-bold tracking-tight text-ink/60">HUDA</p>
    </div>
  )
}

/** Signed in + profile synced (POST /me/sync on first load, arch §7). New users go to onboarding. */
export function RequireAuth() {
  const auth = useAppAuth()
  const location = useLocation()
  const signedIn = auth.isLoaded && auth.isSignedIn
  const me = useMe({ enabled: signedIn })
  if (!auth.isLoaded) return <Splash />
  if (!auth.isSignedIn) {
    const redirect = encodeURIComponent(location.pathname + location.search)
    return <Navigate to={`/sign-in?redirect=${redirect}`} replace />
  }
  if (me.isLoading) return <Splash />
  if (me.error) {
    return (
      <div className="mx-auto max-w-lg p-8">
        <ErrorNote error={me.error} onRetry={me.refetch} />
      </div>
    )
  }
  if (me.data && !me.data.onboarded && location.pathname.startsWith('/app') && !auth.mock) {
    return <Navigate to="/onboarding" replace />
  }
  return <Outlet />
}

/** Admin-only routes are hidden from users (spec §10.1 Constraints); the API enforces it too. */
export function RequireAdmin() {
  const me = useMe()
  if (me.isLoading) return <Splash />
  if (me.data?.role !== 'admin') return <Navigate to="/app/live" replace />
  return <Outlet />
}

/** Telegram links point at /z/<slug> (implementation-plan D5). */
export function ZoneRedirect() {
  const { slug } = useParams()
  return <Navigate to={`/app/live?zone=${encodeURIComponent(slug)}`} replace />
}
