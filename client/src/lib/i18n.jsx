import { createContext, useCallback, useContext, useMemo, useState } from 'react'
import { STRINGS } from './strings'

const I18nContext = createContext(null)
const STORAGE_KEY = 'huda.lang'

function readStored() {
  try {
    return localStorage.getItem(STORAGE_KEY)
  } catch {
    return null
  }
}

export function I18nProvider({ children }) {
  const [lang, setLangState] = useState(() => (readStored() === 'ms' ? 'ms' : 'en'))

  const setLang = useCallback((next) => {
    setLangState(next)
    try {
      localStorage.setItem(STORAGE_KEY, next)
    } catch {
      /* private mode */
    }
    document.documentElement.lang = next === 'ms' ? 'ms' : 'en'
  }, [])

  const t = useCallback(
    (key, vars) => {
      let s = STRINGS[lang][key] ?? STRINGS.en[key] ?? key
      if (vars) for (const [k, v] of Object.entries(vars)) s = s.replaceAll(`{${k}}`, v)
      return s
    },
    [lang],
  )

  const value = useMemo(() => ({ lang, setLang, t }), [lang, setLang, t])
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useT() {
  return useContext(I18nContext)
}
