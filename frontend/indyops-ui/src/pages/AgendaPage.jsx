import { useState, useEffect, useCallback } from 'react'
import { get, post, del } from '../api/client'
import AccountDashboard from './tracking/AccountDashboard'

// ── formatting ───────────────────────────────────────────────────────────────
const GREEN = '#4caf7d', RED = '#e05252'

function fmtPrice(v) {
  if (v == null) return '—'
  const n = Number(v), abs = Math.abs(n)
  if (abs >= 1e9) return (n / 1e9).toFixed(2) + 'B'
  if (abs >= 1e6) return (n / 1e6).toFixed(2) + 'M'
  if (abs >= 1e3) return (n / 1e3).toFixed(1) + 'K'
  return n.toLocaleString(undefined, { maximumFractionDigits: 2 })
}
const fmtPct = (v) => (v == null ? '' : `${v > 0 ? '+' : ''}${v.toFixed(2)}%`)
const pctColor = (v) => (v == null ? 'var(--text)' : v > 0 ? GREEN : v < 0 ? RED : 'var(--text)')
const sevColor = (s) => (s === 'up' ? GREEN : s === 'down' ? RED : 'var(--accent)')

function timeAgo(iso) {
  if (!iso) return ''
  const s = (Date.now() - new Date(iso).getTime()) / 1000
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return `${Math.floor(s / 86400)}d ago`
}

/** Fetch `path` on mount + every `ms`; returns [data, reload]. setState only in
 *  async callbacks (no synchronous setState in the effect body). */
function usePoll(path, ms) {
  const [data, setData] = useState(null)
  const reload = useCallback(() => get(path).then(setData).catch(() => {}), [path])
  useEffect(() => {
    let alive = true
    const tick = () => get(path).then(d => { if (alive) setData(d) }).catch(() => {})
    tick()
    const id = setInterval(tick, ms)
    return () => { alive = false; clearInterval(id) }
  }, [path, ms])
  return [data, reload]
}

// ── page ───────────────────────────────────────────────────────────────────
// Alerts are created from the 🔔 icon on the Analysis page's Indices / Tracking
// tabs (components/AlertDialog). This dashboard just shows the ticker + the feed.
export default function AgendaPage() {
  return (
    <div>
      <h2 style={{ marginBottom: 14 }}>Agenda</h2>
      <AccountDashboard />
      <Ticker />
      <div style={{ marginTop: 20 }}>
        <NotificationsFeed />
      </div>
    </div>
  )
}

// ── ticker ───────────────────────────────────────────────────────────────────
function Ticker() {
  const [data] = usePoll('/agenda/ticker', 60_000)
  const entries = data?.entries || []

  if (!entries.length) {
    return (
      <div className="ticker">
        <div style={{ padding: '12px 16px', fontSize: 13, color: 'var(--text)' }}>
          No index or tracked-item data yet — it builds as the hourly collectors run.
        </div>
      </div>
    )
  }
  const loop = [...entries, ...entries]   // duplicate for a seamless marquee loop
  return (
    <div className="ticker">
      <div className="ticker-track">
        {loop.map((e, i) => (
          <span key={`${e.kind}-${e.key}-${i}`} className="ticker-item">
            <span style={{ color: 'var(--text)', fontSize: 10, textTransform: 'uppercase' }}>
              {e.kind === 'index' ? '◆' : '•'}
            </span>
            <span style={{ color: 'var(--text-white)' }}>{e.label}</span>
            <span style={{ color: 'var(--text-bright)' }}>{fmtPrice(e.price)}</span>
            {e.change_pct != null && (
              <span style={{ color: pctColor(e.change_pct), fontSize: 12 }}>{fmtPct(e.change_pct)}</span>
            )}
          </span>
        ))}
      </div>
    </div>
  )
}

// ── notifications feed ───────────────────────────────────────────────────────
function NotificationsFeed() {
  const [data, reload] = usePoll('/agenda/notifications', 30_000)
  const notifs = data?.notifications || []
  const unread = data?.unread || 0

  async function markAll() { await post('/agenda/notifications/read-all'); reload() }
  async function markOne(id) { await post(`/agenda/notifications/${id}/read`); reload() }
  async function dismiss(id) { await del(`/agenda/notifications/${id}`); reload() }

  return (
    <div className="card" style={{ padding: 0, minWidth: 0 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '14px 18px', borderBottom: '1px solid var(--border)' }}>
        <span style={{ fontSize: 12, fontWeight: 700, letterSpacing: 1, color: 'var(--accent)' }}>NOTIFICATIONS</span>
        {unread > 0 && <span className="badge badge-warn">{unread} new</span>}
        {unread > 0 && (
          <button className="btn btn-ghost btn-sm" style={{ marginLeft: 'auto' }} onClick={markAll}>Mark all read</button>
        )}
      </div>

      {notifs.length === 0 ? (
        <div className="empty-state" style={{ padding: '40px 20px' }}>
          No notifications yet. Create alerts from the 🔔 icon in Analysis → Indices / Tracking.
        </div>
      ) : (
        <div style={{ maxHeight: 620, overflowY: 'auto' }}>
          {notifs.map(n => (
            <div key={n.id} style={{
              display: 'flex', gap: 12, padding: '12px 18px', borderBottom: '1px solid var(--border)',
              background: n.read ? 'transparent' : 'var(--surface2)',
            }}>
              <span style={{ color: sevColor(n.severity), fontSize: 18, lineHeight: 1 }}>
                {n.severity === 'down' ? '▾' : n.severity === 'up' ? '▴' : '•'}
              </span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ color: 'var(--text-white)', fontSize: 13 }}>{n.title}</div>
                {n.body && <div style={{ color: 'var(--text)', fontSize: 12, marginTop: 2 }}>{n.body}</div>}
                <div style={{ color: 'var(--border2)', fontSize: 11, marginTop: 4 }}>{timeAgo(n.created_at)}</div>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                {!n.read && <button className="btn btn-ghost btn-sm" onClick={() => markOne(n.id)}>Read</button>}
                <button className="btn btn-ghost btn-sm" onClick={() => dismiss(n.id)}>✕</button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
