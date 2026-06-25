// Agenda → unified tracking summary. One call (/account/tracking-summary) runs every
// Tracking stream across all characters over a window and returns each stream's headline
// number; this renders the account grand total + per-stream bars. Fetch-on-mount + manual
// refresh (the aggregate is heavy — it re-runs the FIFO ledgers + Jita valuation), with a
// 7/30/90-day window switch.
import { useState, useEffect } from 'react'
import { get } from '../../api/client'
import { fmtIsk, RED } from './fmt'

const PERIODS = [7, 30, 90]
const COLORS = {
  trade: '#3a9bd6', manufacturing: '#9b6dd6', contracts: '#e0884f',
  missions: '#4caf7d', ratting: '#c8a951', mining: '#5bb7b0', deliveries: '#d6708f',
}

export default function TrackingSummary() {
  const [days, setDays] = useState(30)
  const [data, setData] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  // fetch on mount / window change — setState only in async callbacks (no sync setState
  // in the effect body), matching the AccountDashboard polling pattern.
  useEffect(() => {
    let alive = true
    get(`/account/tracking-summary?days=${days}`)
      .then(d => { if (alive) { setData(d); setErr('') } })
      .catch(e => { if (alive) setErr(e.message) })
    return () => { alive = false }
  }, [days])

  function reload() {
    setBusy(true)
    get(`/account/tracking-summary?days=${days}`)
      .then(d => { setData(d); setErr('') })
      .catch(e => setErr(e.message))
      .finally(() => setBusy(false))
  }

  const streams = data?.streams || []
  const grand = data?.grand_total || 0
  const maxVal = Math.max(1, ...streams.map(s => Math.abs(s.value || 0)))

  return (
    <div className="card" style={{ marginBottom: 18 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 14, flexWrap: 'wrap' }}>
        <span className="sec-label">Tracking summary</span>
        <span style={{ flex: 1 }} />
        <div className="tabs" style={{ margin: 0 }}>
          {PERIODS.map(p => (
            <button key={p} className={`tab-btn ${days === p ? 'active' : ''}`} onClick={() => setDays(p)}>{p}d</button>
          ))}
        </div>
        <button className="btn btn-ghost btn-sm" onClick={reload} disabled={busy} title="Refresh">{busy ? '…' : '⟳'}</button>
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 32, alignItems: 'baseline', marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 11, color: 'var(--text)', textTransform: 'uppercase', letterSpacing: 0.4 }}>Total ({days}d)</div>
          <div style={{ fontSize: 22, color: 'var(--accent)', fontWeight: 700 }}>{fmtIsk(grand)}</div>
        </div>
        <div>
          <div style={{ fontSize: 11, color: 'var(--text)', textTransform: 'uppercase', letterSpacing: 0.4 }}>Per day</div>
          <div style={{ fontSize: 15, color: 'var(--text-white)', fontWeight: 600 }}>{fmtIsk(data?.per_day)}</div>
        </div>
      </div>

      {streams.map(s => (
        <div key={s.key} style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 7 }}>
          <span style={{ width: 130, fontSize: 12, color: 'var(--text-bright)' }}>{s.label}</span>
          <div style={{ flex: 1, height: 14, background: 'var(--bg)', borderRadius: 3, overflow: 'hidden' }}>
            <div style={{ width: `${Math.abs(s.value || 0) / maxVal * 100}%`, height: '100%', background: COLORS[s.key] || 'var(--accent)' }} />
          </div>
          <span style={{ width: 96, textAlign: 'right', fontSize: 12, color: (s.value || 0) < 0 ? RED : 'var(--text-white)' }}>{fmtIsk(s.value)}</span>
        </div>
      ))}

      {!data && !err && <div style={{ fontSize: 12, color: 'var(--text)' }}>Loading…</div>}
      {err && <div style={{ fontSize: 12, color: RED }}>{err}</div>}

      <div style={{ fontSize: 11, color: 'var(--text)', marginTop: 10 }}>
        Realized profit (Market · Manufacturing · Contracts) + income (Missions · Ratting · Deliveries) + refined value
        (Mining), across all characters over the last {days} days.
      </div>
    </div>
  )
}
