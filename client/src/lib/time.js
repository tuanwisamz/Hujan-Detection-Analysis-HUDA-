const MYT = 'Asia/Kuala_Lumpur'

export function minutesSince(iso, now = Date.now()) {
  if (!iso) return null
  return Math.max(0, Math.round((now - new Date(iso).getTime()) / 60000))
}

export function formatTime(iso, lang = 'en') {
  if (!iso) return '–'
  return new Intl.DateTimeFormat(lang === 'ms' ? 'ms-MY' : 'en-MY', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    timeZone: MYT,
  }).format(new Date(iso))
}

export function formatDateTime(iso, lang = 'en') {
  if (!iso) return '–'
  return new Intl.DateTimeFormat(lang === 'ms' ? 'ms-MY' : 'en-MY', {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    timeZone: MYT,
  }).format(new Date(iso))
}

/** Value for <input type="datetime-local"> in MYT. */
export function toLocalInput(date) {
  const d = new Date(date.getTime() + 8 * 3600000)
  return d.toISOString().slice(0, 16)
}

export function fromLocalInput(value) {
  return new Date(new Date(value + ':00Z').getTime() - 8 * 3600000).toISOString()
}
