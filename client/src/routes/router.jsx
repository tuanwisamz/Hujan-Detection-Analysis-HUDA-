/* eslint-disable react-refresh/only-export-components -- route config module, not a component file */
import { lazy, Suspense } from 'react'
import { createBrowserRouter, Navigate } from 'react-router'
import Layout from '../components/Layout'
import { Loading } from '../components/ui'
import LivePage from '../pages/LivePage'
import { RequireAdmin, RequireAuth, ZoneRedirect } from './guards'

// Live map is the landing page and loads eagerly; everything else is split out (NFR-03).
const AuthPage = lazy(() => import('../pages/AuthPage'))
const NotFound = lazy(() => import('../pages/AuthPage').then((m) => ({ default: m.NotFound })))
const LogsPage = lazy(() => import('../pages/LogsPage'))
const OnboardingPage = lazy(() => import('../pages/OnboardingPage'))
const ReportsPage = lazy(() => import('../pages/ReportsPage'))
const SettingsPage = lazy(() => import('../pages/SettingsPage'))
const WarningsPage = lazy(() => import('../pages/WarningsPage'))
const ZonesPage = lazy(() => import('../pages/ZonesPage'))

const page = (el) => (
  <Suspense
    fallback={
      <div className="mx-auto max-w-5xl p-8">
        <Loading />
      </div>
    }
  >
    {el}
  </Suspense>
)

// architecture.md §8 + /z/:slug (implementation-plan D5)
export const router = createBrowserRouter([
  { path: '/', element: <Navigate to="/app/live" replace /> },
  { path: '/sign-in/*', element: page(<AuthPage mode="sign-in" />) },
  { path: '/sign-up/*', element: page(<AuthPage mode="sign-up" />) },
  { path: '/z/:slug', element: <ZoneRedirect /> },
  {
    element: <RequireAuth />,
    children: [
      { path: '/onboarding', element: page(<OnboardingPage />) },
      {
        path: '/app',
        element: <Layout />,
        children: [
          { index: true, element: <Navigate to="live" replace /> },
          { path: 'live', element: <LivePage /> },
          { path: 'zones', element: page(<ZonesPage />) },
          { path: 'logs', element: page(<LogsPage />) },
          { path: 'reports', element: page(<ReportsPage />) },
          { path: 'settings', element: page(<SettingsPage />) },
        ],
      },
      {
        element: <RequireAdmin />,
        children: [
          {
            path: '/admin',
            element: <Layout admin />,
            children: [
              { index: true, element: <Navigate to="live" replace /> },
              { path: 'live', element: <LivePage admin /> },
              { path: 'zones', element: page(<ZonesPage admin />) },
              { path: 'logs', element: page(<LogsPage admin />) },
              { path: 'reports', element: page(<ReportsPage />) },
              { path: 'warnings', element: page(<WarningsPage />) },
              { path: 'settings', element: page(<SettingsPage admin />) },
            ],
          },
        ],
      },
    ],
  },
  { path: '*', element: page(<NotFound />) },
])
