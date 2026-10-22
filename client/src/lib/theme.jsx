import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'

// Night mode (spec FR-40, implementation-plan-v2 D24). The preference is system | light | dark,
// saved to the profile and cached here for first paint (index.html reads the same key).
const ThemeContext = createContext(null)
const STORAGE_KEY = 'huda.theme'
// eslint-disable-next-line react-refresh/only-export-components
export const THEMES = ['system', 'light', 'dark']
const DARK_QUERY = '(prefers-color-scheme: dark)'

function readStored() {
  try {
    const v = localStorage.getItem(STORAGE_KEY)
    return THEMES.includes(v) ? v : 'system'
  } catch {
    return 'system'
  }
}

const systemDark = () => (typeof window !== 'undefined' && window.matchMedia ? window.matchMedia(DARK_QUERY).matches : false)

export function ThemeProvider({ children }) {
  const [pref, setPrefState] = useState(readStored)
  const [osDark, setOsDark] = useState(systemDark)
  const mode = pref === 'system' ? (osDark ? 'dark' : 'light') : pref

  useEffect(() => {
    if (!window.matchMedia) return undefined
    const mq = window.matchMedia(DARK_QUERY)
    const onChange = (e) => setOsDark(e.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])

  useEffect(() => {
    const root = document.documentElement
    root.dataset.theme = mode
    root.style.colorScheme = mode
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', mode === 'dark' ? '#0B1413' : '#18302E')
  }, [mode])

  const setPref = useCallback((next) => {
    if (!THEMES.includes(next)) return
    setPrefState(next)
    try {
      localStorage.setItem(STORAGE_KEY, next)
    } catch {
      /* private mode */
    }
  }, [])

  const value = useMemo(() => ({ pref, mode, setPref }), [pref, mode, setPref])
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useTheme() {
  return useContext(ThemeContext)
}

// Token values for places that can't use CSS variables (SVG attributes, Leaflet paths).
// Keep in step with index.css.
const PALETTE = {
  light: { ink: '#18302E', muted: '#5A6B69', grid: '#E3E8E7', accent: '#1E5450' },
  dark: { ink: '#E3ECEA', muted: '#9FB1AE', grid: '#2C3D3B', accent: '#7FD0C5' },
}

// eslint-disable-next-line react-refresh/only-export-components
export function useThemeColors() {
  return PALETTE[useTheme().mode]
}
