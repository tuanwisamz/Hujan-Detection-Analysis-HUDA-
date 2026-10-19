// API client: Clerk bearer token, api-spec error envelope, and a mock switch.

export const USE_MOCKS = import.meta.env.VITE_USE_MOCKS === 'true'
const BASE = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:7860/api/v1').replace(/\/$/, '')

let tokenGetter = async () => null
export function setTokenGetter(fn) {
  tokenGetter = fn
}

export class ApiError extends Error {
  constructor(status, code, message, requestId) {
    super(message)
    this.status = status
    this.code = code
    this.requestId = requestId
  }
}

function withQuery(path, query) {
  if (!query) return path
  const params = new URLSearchParams()
  for (const [k, v] of Object.entries(query)) {
    if (v !== undefined && v !== null && v !== '') params.set(k, v)
  }
  const qs = params.toString()
  return qs ? `${path}?${qs}` : path
}

export async function api(path, { method = 'GET', body, query, raw = false } = {}) {
  if (USE_MOCKS) {
    const { mockFetch } = await import('./mocks')
    return mockFetch(method, path, query || {}, body)
  }
  const token = await tokenGetter()
  let res
  try {
    res = await fetch(BASE + withQuery(path, query), {
      method,
      headers: {
        ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
  } catch {
    throw new ApiError(0, 'NETWORK', 'Can’t reach the HUDA server. Check your connection.')
  }
  if (!res.ok) {
    let err = {}
    try {
      err = (await res.json()).error || {}
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, err.code || 'INTERNAL', err.message || `Request failed (${res.status})`, err.request_id)
  }
  if (res.status === 204) return null
  if (raw) return res.text()
  return res.json()
}

/** Download an authenticated file (reports). */
export async function download(path, query, filename) {
  const text = USE_MOCKS ? await api(path, { query }) : await api(path, { query, raw: true })
  const blob = new Blob([typeof text === 'string' ? text : JSON.stringify(text)], { type: 'text/plain' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}
