import { ClerkProvider, useAuth, useClerk } from '@clerk/react'
import { msMY } from '@clerk/localizations/ms-MY'
import { createContext, useContext, useEffect, useMemo, useState } from 'react'
import { setTokenGetter, USE_MOCKS } from './api'
import { useT } from './i18n'
import { useTheme } from './theme'

// One auth shape for the app, whether Clerk is live or we're in mock mode
// (VITE_USE_MOCKS=true lets the frontend run without Clerk or the backend).
const AuthContext = createContext(null)
const MOCK_ROLE_KEY = 'huda.mockRole'

export function ClerkAuthBridge({ children }) {
  const { isLoaded, isSignedIn, getToken } = useAuth()
  const clerk = useClerk()
  useEffect(() => {
    setTokenGetter(() => getToken())
  }, [getToken])
  const value = useMemo(
    () => ({ isLoaded, isSignedIn: !!isSignedIn, signOut: () => clerk.signOut({ redirectUrl: '/sign-in' }), mock: false }),
    [isLoaded, isSignedIn, clerk],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function MockAuthProvider({ children }) {
  const [mockRole, setMockRoleState] = useState(() => {
    try {
      return localStorage.getItem(MOCK_ROLE_KEY) || 'admin'
    } catch {
      return 'admin'
    }
  })
  const value = useMemo(
    () => ({
      isLoaded: true,
      isSignedIn: true,
      signOut: () => {},
      mock: true,
      mockRole,
      setMockRole: (role) => {
        try {
          localStorage.setItem(MOCK_ROLE_KEY, role)
        } catch {
          /* ignore */
        }
        setMockRoleState(role)
      },
    }),
    [mockRole],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAppAuth() {
  return useContext(AuthContext)
}

const publishableKey = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY

// Clerk's sign-in, reset and account screens in HUDA's colours, light or dark (implementation-plan-v2 D24–D25).
const CLERK_COLORS = {
  light: { colorPrimary: '#1E5450', colorBackground: '#FFFFFF', colorText: '#18302E', colorTextSecondary: '#5A6B69', colorInputBackground: '#FFFFFF', colorInputText: '#18302E', colorDanger: '#C62828' },
  dark: { colorPrimary: '#7FD0C5', colorBackground: '#172524', colorText: '#E3ECEA', colorTextSecondary: '#9FB1AE', colorInputBackground: '#0F1A19', colorInputText: '#E3ECEA', colorDanger: '#FF8A80', colorTextOnPrimaryBackground: '#0B1413' },
}

/** Clerk in real mode, a fake signed-in user in mock mode. */
export function AuthGate({ children }) {
  const { mode } = useTheme()
  const { lang } = useT()
  if (USE_MOCKS) return <MockAuthProvider>{children}</MockAuthProvider>
  if (!publishableKey) {
    return (
      <div className="mx-auto max-w-lg p-8">
        <h1 className="text-xl font-bold">HUDA isn’t configured</h1>
        <p className="mt-2 text-muted">
          Set <code>VITE_CLERK_PUBLISHABLE_KEY</code> in <code>client/.env</code>, or run with <code>VITE_USE_MOCKS=true</code> to try the app without a backend.
        </p>
      </div>
    )
  }
  return (
    <ClerkProvider
      publishableKey={publishableKey}
      afterSignOutUrl="/sign-in"
      localization={lang === 'ms' ? msMY : undefined}
      appearance={{ variables: { ...CLERK_COLORS[mode], fontFamily: 'var(--font-sans)', borderRadius: '0.5rem' } }}
    >
      <ClerkAuthBridge>{children}</ClerkAuthBridge>
    </ClerkProvider>
  )
}
