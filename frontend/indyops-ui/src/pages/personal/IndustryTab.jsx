import { useState } from 'react'
import { post } from '../../api/client'
import { useApi, fmtIsk, fmtNum, fmtDate } from './common'

// Slot summary cards, in the usual EVE order.
const SLOT_LABELS = [
  ['manufacturing', 'Manufacturing'],
  ['science', 'Research'],
  ['reaction', 'Reaction'],
]

// "95d 2h 21m left" from an end timestamp.
function fmtLeft(end) {
  if (!end) return '—'
  const ms = new Date(end) - new Date()
  if (ms <= 0) return 'ready'
  const d = Math.floor(ms / 86400000)
  const h = Math.floor((ms % 86400000) / 3600000)
  const m = Math.floor((ms % 3600000) / 60000)
  if (d > 0) return `${d}d ${h}h ${m}m left`
  if (h > 0) return `${h}h ${m}m left`
  return `${m}m left`
}

function progressPct(start, end) {
  if (!start || !end) return null
  const s = new Date(start).getTime(), e = new Date(end).getTime()
  if (e <= s) return 100
  return Math.max(0, Math.min(100, ((Date.now() - s) / (e - s)) * 100))
}

export default function IndustryTab({ charId }) {
  const { data, loading, error } = useApi(`/characters/${charId}/industry-jobs`, [charId])
  const [msg, setMsg]   = useState('')
  const [busy, setBusy] = useState(false)

  async function importJobs() {
    setBusy(true); setMsg('')
    try {
      const r = await post(`/characters/${charId}/import/industry-jobs`, {})
      setMsg(`Imported ${r.imported} job(s); skipped ${r.skipped}.`)
    } catch (e) { setMsg(e.message) }
    finally { setBusy(false) }
  }

  if (loading) return <div className="empty-state">Loading…</div>
  if (error)   return <div className="error-box">{error}</div>

  const jobs  = data.jobs  || []
  const slots = data.slots || {}

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, marginBottom: 14, flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          {SLOT_LABELS.map(([key, label]) => {
            const s = slots[key] || { used: 0, max: 0 }
            const full = s.max > 0 && s.used >= s.max
            return (
              <div key={key} style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 6, padding: '6px 14px', minWidth: 96 }}>
                <div style={{ fontSize: 10, color: 'var(--text)', textTransform: 'uppercase', letterSpacing: 0.5 }}>{label}</div>
                <div style={{ fontSize: 16, fontWeight: 600, color: full ? '#e0884f' : 'var(--text-white)' }}>
                  {s.used}<span style={{ color: 'var(--text)', fontWeight: 400, fontSize: 13 }}> / {s.max}</span>
                </div>
              </div>
            )
          })}
        </div>
        <button className="btn btn-primary btn-sm" onClick={importJobs} disabled={busy || !jobs.length}>
          {busy ? 'Importing…' : 'Import into Production'}
        </button>
      </div>

      {msg && <div className="warning-box" style={{ marginBottom: 14 }}>{msg}</div>}

      {jobs.length === 0 ? (
        <div className="empty-state">No industry jobs synced yet.</div>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Product</th><th>Activity</th>
              <th style={{ textAlign: 'right' }}>Runs</th>
              <th>Status</th>
              <th style={{ minWidth: 170 }}>Progress</th>
              <th style={{ textAlign: 'right' }}>Cost</th>
              <th>Ends</th>
              <th>Location</th>
            </tr>
          </thead>
          <tbody>
            {jobs.map(j => {
              const pct = progressPct(j.start_date, j.end_date)
              const done = pct != null && pct >= 100
              return (
                <tr key={j.job_id}>
                  <td>{j.product_name || j.product_type_id}</td>
                  <td>{j.activity}</td>
                  <td style={{ textAlign: 'right' }}>{fmtNum(j.runs)}</td>
                  <td><span className="badge badge-warn">{j.status}</span></td>
                  <td>
                    {pct == null ? '—' : (
                      <>
                        <div style={{ height: 6, background: 'var(--surface3)', borderRadius: 3, overflow: 'hidden' }}>
                          <div style={{ width: `${pct}%`, height: '100%', background: done ? '#4caf7d' : 'var(--accent)' }} />
                        </div>
                        <div style={{ fontSize: 11, color: 'var(--text)', marginTop: 3 }}>
                          {pct.toFixed(0)}% · {fmtLeft(j.end_date)}
                        </div>
                      </>
                    )}
                  </td>
                  <td style={{ textAlign: 'right' }}>{fmtIsk(j.cost)}</td>
                  <td>{fmtDate(j.end_date)}</td>
                  <td style={{ color: 'var(--text)', fontSize: 12 }}>{j.location_name || '—'}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </div>
  )
}
