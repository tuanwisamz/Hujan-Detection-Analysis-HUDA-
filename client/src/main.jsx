import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { RouterProvider } from 'react-router'
import { ToastProvider } from './components/ui'
import './index.css'
import { AuthGate } from './lib/auth'
import { I18nProvider } from './lib/i18n'
import { ThemeProvider } from './lib/theme'
import { router } from './routes/router'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (count, error) => count < 2 && ![401, 403, 404, 422].includes(error?.status),
      refetchOnWindowFocus: true,
    },
  },
})

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <I18nProvider>
      <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <ToastProvider>
          <AuthGate>
            <RouterProvider router={router} />
          </AuthGate>
        </ToastProvider>
      </QueryClientProvider>
      </ThemeProvider>
    </I18nProvider>
  </StrictMode>,
)
