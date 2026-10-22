import { Bot, FileText, Gauge, LogOut, Map as MapIcon, Megaphone, MessageCircle, Moon, ScrollText, Settings, Shield, Siren, Sun, User } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router'
import { useApiMutation, useMe } from '../hooks/queries'
import { api } from '../lib/api'
import { useAppAuth } from '../lib/auth'
import { useT } from '../lib/i18n'
import { useTheme } from '../lib/theme'
import AssistantDrawer from './AssistantDrawer'

function navFor(base, admin) {
  const items = [
    { to: `${base}/live`, label: 'nav.live', Icon: MapIcon },
    { to: `${base}/zones`, label: 'nav.zones', Icon: Shield },
    { to: `${base}/logs`, label: admin ? 'nav.adminLogs' : 'nav.logs', Icon: ScrollText },
    { to: `${base}/reports`, label: 'nav.reports', Icon: FileText },
  ]
  if (admin) {
    items.push({ to: `${base}/warnings`, label: 'nav.warnings', Icon: Megaphone })
    items.push({ to: `${base}/automation`, label: 'nav.automation', Icon: Bot })
    items.push({ to: `${base}/sensors`, label: 'nav.sensors', Icon: Gauge })
    items.push({ to: `${base}/sirens`, label: 'nav.sirens', Icon: Siren })
  }
  items.push({ to: `${base}/settings`, label: 'nav.settings', Icon: Settings })
  return items
}

function LanguageToggle() {
  const { lang, setLang } = useT()
  return (
    <div role="group" aria-label="Language / Bahasa" className="inline-flex rounded-lg border border-on-chrome/25 p-0.5">
      {[
        ['en', 'EN'],
        ['ms', 'BM'],
      ].map(([code, label]) => (
        <button
          key={code}
          type="button"
          aria-pressed={lang === code}
          onClick={() => setLang(code)}
          className={`min-h-9 rounded-md px-3 text-sm font-semibold ${lang === code ? 'bg-on-chrome text-chrome' : 'text-on-chrome/80 hover:text-on-chrome'}`}
        >
          {label}
        </button>
      ))}
    </div>
  )
}

/** Night mode switch (spec FR-40). Settings also offers "follow the device". */
function ThemeToggle() {
  const { t } = useT()
  const { mode, setPref } = useTheme()
  const save = useApiMutation((theme) => api('/me', { method: 'PATCH', body: { theme } }), ['me'])
  const dark = mode === 'dark'
  return (
    <button
      type="button"
      aria-pressed={dark}
      onClick={() => {
        const next = dark ? 'light' : 'dark'
        setPref(next)
        save.mutate(next)
      }}
      className="inline-flex min-h-9 min-w-9 items-center justify-center gap-1.5 rounded-lg border border-on-chrome/25 px-2 text-sm font-semibold text-on-chrome hover:bg-on-chrome/10"
    >
      {dark ? <Sun size={17} aria-hidden="true" /> : <Moon size={17} aria-hidden="true" />}
      <span className="sr-only lg:not-sr-only">{t('theme.night')}</span>
    </button>
  )
}

/** On first load, take the theme saved on the profile (it follows the user across devices). */
function useProfileTheme(me) {
  const { pref, setPref } = useTheme()
  const synced = useRef(false)
  useEffect(() => {
    const saved = me.data?.theme
    if (!synced.current && saved) {
      synced.current = true
      if (saved !== pref) setPref(saved)
    }
  }, [me.data?.theme, pref, setPref])
}

/** Same shell for User and Admin (spec §10.2 Memory: consistent layout across roles). */
export default function Layout({ admin = false }) {
  const { t } = useT()
  const auth = useAppAuth()
  const me = useMe()
  const location = useLocation()
  const isAdmin = me.data?.role === 'admin'
  const base = admin ? '/admin' : '/app'
  const items = navFor(base, admin)
  const fullBleed = location.pathname.endsWith('/live')
  const [assistantOpen, setAssistantOpen] = useState(false)
  useProfileTheme(me)

  return (
    <div className="flex h-full flex-col lg:flex-row">
      {/* Persistent sidebar with labelled icons (spec §10.1 Discoverability) */}
      <nav aria-label="Main" className="hidden w-60 shrink-0 flex-col bg-chrome px-3 py-5 text-on-chrome lg:flex">
        <div className="mb-6 px-3">
          <p className="text-2xl font-bold tracking-tight">HUDA</p>
          <p className="text-sm leading-snug text-on-chrome/70">{t('app.tagline')}</p>
          {admin && <p className="mt-2 inline-block rounded bg-on-chrome/15 px-2 py-0.5 text-xs font-semibold">{t('nav.admin')}</p>}
        </div>
        <ul className="space-y-1">
          {items.map(({ to, label, Icon }) => (
            <li key={to}>
              <NavLink
                to={to}
                className={({ isActive }) =>
                  `flex min-h-11 items-center gap-3 rounded-lg px-3 font-semibold ${isActive ? 'bg-on-chrome text-chrome' : 'text-on-chrome/85 hover:bg-on-chrome/10 hover:text-on-chrome'}`
                }
              >
                <Icon size={19} aria-hidden="true" />
                {t(label)}
              </NavLink>
            </li>
          ))}
        </ul>
        <button
          type="button"
          onClick={() => setAssistantOpen(true)}
          className="mt-4 flex min-h-11 items-center gap-3 rounded-lg border border-on-chrome/25 px-3 font-semibold text-on-chrome hover:bg-on-chrome/10"
        >
          <MessageCircle size={19} aria-hidden="true" />
          {t('nav.assistant')}
        </button>

        <div className="mt-auto space-y-3 px-3 pt-6">
          {isAdmin && (
            <NavLink to={admin ? '/app/live' : '/admin/live'} className="flex min-h-11 items-center gap-2 text-sm font-semibold text-on-chrome/85 hover:text-on-chrome">
              {admin ? <User size={17} aria-hidden="true" /> : <Shield size={17} aria-hidden="true" />}
              {admin ? t('nav.userView') : t('nav.admin')}
            </NavLink>
          )}
          <div className="flex items-center gap-2">
            <LanguageToggle />
            <ThemeToggle />
          </div>
          {auth.mock ? (
            <div className="text-xs text-on-chrome/70">
              <p className="mb-1">{t('auth.mock')}</p>
              <select
                value={auth.mockRole}
                onChange={(e) => {
                  auth.setMockRole(e.target.value)
                  window.location.assign(e.target.value === 'admin' ? '/admin/live' : '/app/live')
                }}
                className="min-h-9 w-full rounded-md bg-on-chrome/10 px-2 text-sm text-on-chrome"
              >
                <option value="user" className="text-ink">user</option>
                <option value="admin" className="text-ink">admin</option>
              </select>
            </div>
          ) : (
            <button type="button" onClick={auth.signOut} className="flex min-h-11 items-center gap-2 text-sm font-semibold text-on-chrome/85 hover:text-on-chrome">
              <LogOut size={17} aria-hidden="true" />
              {t('nav.signOut')}
            </button>
          )}
          {me.data?.email && <p className="truncate text-xs text-on-chrome/60">{me.data.email}</p>}
        </div>
      </nav>

      {/* Mobile top bar */}
      <header className="flex items-center justify-between bg-chrome px-4 py-2 text-on-chrome lg:hidden">
        <p className="text-lg font-bold">
          HUDA{admin && <span className="ml-2 rounded bg-on-chrome/15 px-1.5 py-0.5 text-xs">{t('nav.admin')}</span>}
        </p>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setAssistantOpen(true)}
            className="inline-flex min-h-11 items-center gap-1.5 rounded-lg px-2 text-sm font-semibold text-on-chrome"
          >
            <MessageCircle size={18} aria-hidden="true" />
            {t('nav.assistant')}
          </button>
          <LanguageToggle />
          <ThemeToggle />
        </div>
      </header>

      <main id="main" className={`min-h-0 flex-1 overflow-y-auto pb-16 lg:pb-0 ${fullBleed ? 'lg:overflow-hidden' : ''}`}>
        <Outlet />
      </main>

      {/* Mobile bottom nav, labelled icons */}
      <nav aria-label="Main" className="fixed inset-x-0 bottom-0 z-[1000] flex border-t border-line bg-surface lg:hidden">
        {items.map(({ to, label, Icon }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) => `flex min-h-14 flex-1 flex-col items-center justify-center gap-0.5 text-[11px] font-semibold ${isActive ? 'text-primary' : 'text-muted'}`}
          >
            <Icon size={20} aria-hidden="true" />
            <span className="max-w-full truncate px-0.5">{t(label)}</span>
          </NavLink>
        ))}
      </nav>

      <AssistantDrawer open={assistantOpen} onClose={() => setAssistantOpen(false)} />
    </div>
  )
}
