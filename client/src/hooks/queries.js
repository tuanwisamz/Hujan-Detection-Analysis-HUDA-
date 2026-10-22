import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'

// One place for every server call the UI makes (api-spec.md).

export const useMe = ({ enabled = true } = {}) =>
  useQuery({ queryKey: ['me'], queryFn: () => api('/me/sync', { method: 'POST', body: {} }), staleTime: 5 * 60000, enabled })

export const useLiveSummary = () =>
  useQuery({ queryKey: ['live'], queryFn: () => api('/live/summary'), refetchInterval: 60000 }) // arch §8: poll 60 s

export const useRadarFrames = () =>
  useQuery({ queryKey: ['radar'], queryFn: () => api('/radar/frames'), refetchInterval: 5 * 60000 })

export const useZone = (id) => useQuery({ queryKey: ['zone', id], queryFn: () => api(`/zones/${id}`), enabled: !!id })

export const useTimeseries = (id, hours = 6) =>
  useQuery({ queryKey: ['timeseries', id, hours], queryFn: () => api(`/zones/${id}/timeseries`, { query: { hours } }), enabled: !!id })

export const useZones = (active = 'true') =>
  useQuery({ queryKey: ['zones', active], queryFn: () => api('/zones', { query: { active } }) })

export const useSubscriptions = () => useQuery({ queryKey: ['subs'], queryFn: () => api('/me/subscriptions') })

export const useAlerts = () => useQuery({ queryKey: ['alerts'], queryFn: () => api('/alerts', { query: { limit: 100 } }) })

export const useWarnings = (status) =>
  useQuery({ queryKey: ['warnings', status], queryFn: () => api('/admin/warnings', { query: { status } }), refetchInterval: 30000 })

export const useAdminSettings = (enabled = true) =>
  useQuery({ queryKey: ['settings'], queryFn: () => api('/admin/settings'), enabled })

export const useAutomation = (enabled = true) =>
  useQuery({ queryKey: ['automation'], queryFn: () => api('/admin/automation'), refetchInterval: 60000, enabled })

export const useAutomationActivity = () =>
  useQuery({
    queryKey: ['automationActivity'],
    queryFn: () => api('/admin/logs', { query: { category: 'alert', limit: 8 } }),
    refetchInterval: 60000,
  })

export const useRuns = () => useQuery({ queryKey: ['runs'], queryFn: () => api('/admin/runs'), refetchInterval: 60000 })

export const useReports = () =>
  useQuery({
    queryKey: ['reports'],
    queryFn: () => api('/reports'),
    refetchInterval: (q) => (q.state.data?.items?.some((r) => r.status === 'generating') ? 2000 : false),
  })

export const useReport = (id) => useQuery({ queryKey: ['report', id], queryFn: () => api(`/reports/${id}`), enabled: !!id })

/** Mutation that invalidates the given query keys on success. */
export function useApiMutation(fn, invalidate = []) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: () => invalidate.forEach((key) => qc.invalidateQueries({ queryKey: [key] })),
  })
}

export function usePutSubscriptions() {
  return useApiMutation((subscriptions) => api('/me/subscriptions', { method: 'PUT', body: { subscriptions } }), ['subs', 'live'])
}
