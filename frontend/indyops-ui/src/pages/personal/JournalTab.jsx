import { useState } from 'react'
import { post, del } from '../../api/client'
import { useApi, fmtIsk, fmtNum } from './common'

const PERIODS = ['day', 'month', 'quarter', 'year']
const BASES = [['buy', 'Buy'], ['sell', 'Sell'], ['split', 'Split']]
const CAT_LABELS = [
  ['ore', 'Regular ore'],
  ['moon_ore', 'Moon ore'],
  ['ice', 'Ice'],
  ['gas', 'Gas'],
  ['other', 'Other'],
]

export default function JournalTab({ charId }) {
  const [period, setPeriod] = useState('month')
  const [offset, setOffset] = useState(0)
  const [scope, setScope]   = useState('character')
  const [basis, setBasis]   = useState(null)   // null → use the saved default
  const [nonce, setNonce]   = useState(0)
  const [busy, setBusy]     = useState(false)

  const qs = new URLSearchParams({ period, offset: String(offset), scope })
  if (basis) qs.set('basis', basis)
  const { data, loading, error } = useApi(
    `/characters/${charId}/mining-journal?${qs}`,
    [charId, period, offset, scope, basis, nonce],
  )

  async function writeOff() {
    setBusy(true)
    try { await post(`/characters/${charId}/mining-journal/writeoff`, { period, offset, scope }); setNonce(n => n + 1) }
    finally { setBusy(false) }
  }
  async function undo() {
    setBusy(true)
    try {
      await del(`/characters/${charId}/mining-journal/writeoff?period=${period}&offset=${offset}&scope=${scope}`)
      setNonce(n => n + 1)
    } finally { setBusy(false) }
  }

  const activeBasis = basis || data?.basis || 'sell'
  const cats = data?.categories || {}
  const wo = data?.written_off

  return (
    <div>
      {/* controls */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 14, alignItems: 'center', marginBottom: 16 }}>
        <Seg options={[['character', 'This character'], ['all', 'All characters']]} value={scope} onChange={setScope} />
        <Seg options={PERIODS.map(p => [p, p[0].toUpperCase() + p.slice(1)])} value={period} onChange={v => { setPeriod(v); setOffset(0) }} />
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <button className="btn btn-ghost btn-sm" onClick={() => setOffset(o => o - 1)}>‹</button>
          <span style={{ fontSize: 13, color: 'var(--text-white)', minWidth: 90, textAlign: 'center' }}>
            {data?.period?.key || '—'}
          </span>
          <button className="btn btn-ghost btn-sm" onClick={() => setOffset(o => Math.min(0, o + 1))} disabled={offset >= 0}>›</button>
        </div>
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ fontSize: 11, color: 'var(--text)' }}>Jita</span>
          <Seg options={BASES} value={activeBasis} onChange={setBasis} />
        </div>
      </div>

      {error && <div className="error-box">{error}</div>}
      {loading && !data && <div className="empty-state">Loading…</div>}

      {data && (
        <>
          {/* totals */}
          <div className="card" style={{ display: 'flex', flexWrap: 'wrap', gap: 24, alignItems: 'center', marginBottom: 16 }}>
            <Stat label="Gross (refined → Jita)" value={fmtIsk(data.gross_value)} big />
            <Stat label={`Tax (${data.tax_pct}%)`} value={`− ${fmtIsk(data.tax_amount)}`} color="#e0884f" />
            <Stat label="Net" value={fmtIsk(data.net_value)} color="#4caf7d" big />
            <div style={{ marginLeft: 'auto' }}>
              {wo ? (
                <div style={{ textAlign: 'right' }}>
                  <span className="badge badge-ok">✓ Tax written off</span>
                  <div style={{ marginTop: 6 }}>
                    <button className="btn btn-ghost btn-sm" onClick={undo} disabled={busy}>Undo</button>
                  </div>
                </div>
              ) : (
                <button className="btn btn-primary" onClick={writeOff} disabled={busy || !data.gross_value}>
                  {busy ? '…' : 'Write off tax'}
                </button>
              )}
            </div>
          </div>

          {/* category breakdown */}
          <table>
            <thead>
              <tr><th>Category</th><th style={{ textAlign: 'right' }}>Units mined</th><th style={{ textAlign: 'right' }}>Value (Jita {activeBasis})</th></tr>
            </thead>
            <tbody>
              {CAT_LABELS.map(([key, label]) => {
                const c = cats[key] || { value: 0, qty: 0 }
                if (key === 'other' && !c.value && !c.qty) return null
                return (
                  <tr key={key}>
                    <td style={{ color: 'var(--text-white)' }}>{label}</td>
                    <td style={{ textAlign: 'right' }}>{fmtNum(c.qty)}</td>
                    <td style={{ textAlign: 'right' }}>{fmtIsk(c.value)}</td>
                  </tr>
                )
              })}
              <tr style={{ borderTop: '2px solid var(--border2)' }}>
                <td style={{ color: 'var(--accent)', fontWeight: 600 }}>Total</td>
                <td />
                <td style={{ textAlign: 'right', color: 'var(--accent)', fontWeight: 600 }}>{fmtIsk(data.gross_value)}</td>
              </tr>
            </tbody>
          </table>

          {data.items?.length === 0 && (
            <div className="empty-state" style={{ marginTop: 12 }}>
              No mining recorded for this period. The ledger syncs from ESI (last ~30 days) and accumulates over time.
            </div>
          )}

          {/* top mined types */}
          {data.items?.length > 0 && (
            <details style={{ marginTop: 14 }}>
              <summary style={{ cursor: 'pointer', fontSize: 12, color: 'var(--accent)' }}>
                Per-type detail ({data.items.length})
              </summary>
              <table style={{ marginTop: 8 }}>
                <thead><tr><th>Type</th><th>Category</th><th style={{ textAlign: 'right' }}>Units</th><th style={{ textAlign: 'right' }}>Value</th></tr></thead>
                <tbody>
                  {data.items.map(it => (
                    <tr key={it.type_id}>
                      <td style={{ color: 'var(--text-white)' }}>{it.name}</td>
                      <td style={{ color: 'var(--text)', fontSize: 12 }}>{(CAT_LABELS.find(c => c[0] === it.category) || ['', it.category])[1]}</td>
                      <td style={{ textAlign: 'right' }}>{fmtNum(it.qty)}</td>
                      <td style={{ textAlign: 'right' }}>{fmtIsk(it.value)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
          )}

          {/* 30-day stats */}
          {data.stats_30d && (
            <div style={{ marginTop: 18 }}>
              <div style={{ fontSize: 11, color: 'var(--accent)', fontWeight: 700, letterSpacing: 1, marginBottom: 8 }}>
                LAST 30 DAYS
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
                <Stat label="Total mined value" value={fmtIsk(data.stats_30d.total)} />
                {CAT_LABELS.map(([key, label]) => {
                  const c = data.stats_30d.categories?.[key]
                  if (!c || !c.value) return null
                  return <Stat key={key} label={label} value={fmtIsk(c.value)} />
                })}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}

function Seg({ options, value, onChange }) {
  return (
    <div style={{ display: 'flex', gap: 4 }}>
      {options.map(([v, label]) => (
        <button key={v} onClick={() => onChange(v)}
          className={`btn btn-sm ${value === v ? 'btn-primary' : 'btn-ghost'}`}
          style={{ padding: '3px 10px', fontSize: 12 }}>{label}</button>
      ))}
    </div>
  )
}

function Stat({ label, value, color, big }) {
  return (
    <div>
      <div style={{ fontSize: 10, color: 'var(--text)', textTransform: 'uppercase', letterSpacing: 0.5 }}>{label}</div>
      <div style={{ fontSize: big ? 20 : 15, fontWeight: 600, color: color || 'var(--text-white)', marginTop: 2 }}>{value}</div>
    </div>
  )
}
