// Shared formatters for the Tracking tab (orders + account dashboard).

export const GREEN = '#4caf7d'
export const RED = '#e05252'
export const AMBER = '#c8a951'

export function fmtIsk(v) {
  if (v == null) return '—'
  const n = Number(v), abs = Math.abs(n)
  if (abs >= 1e12) return (n / 1e12).toFixed(2) + 'T'
  if (abs >= 1e9) return (n / 1e9).toFixed(2) + 'B'
  if (abs >= 1e6) return (n / 1e6).toFixed(2) + 'M'
  if (abs >= 1e3) return (n / 1e3).toFixed(1) + 'K'
  return n.toLocaleString(undefined, { maximumFractionDigits: 2 })
}

export function fmtInt(v) {
  return v == null ? '—' : Number(v).toLocaleString()
}

// Human "time left" until an ISO timestamp (e.g. "3d 4h", "12m", "expired").
export function timeUntil(iso) {
  if (!iso) return '—'
  const s = (new Date(iso).getTime() - Date.now()) / 1000
  if (s <= 0) return 'expired'
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60)
  if (d > 0) return `${d}d ${h}h`
  if (h > 0) return `${h}h ${m}m`
  return `${m}m`
}
