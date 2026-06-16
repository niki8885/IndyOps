import { useState } from 'react'
import { post } from '../../api/client'
import { useApi, fmtIsk, fmtNum, fmtDate } from './common'

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

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
        <span style={{ color: 'var(--text)', fontSize: 13 }}>{data.length} job(s)</span>
        <button className="btn btn-primary btn-sm" onClick={importJobs} disabled={busy || !data.length}>
          {busy ? 'Importing…' : 'Import into Production'}
        </button>
      </div>
      {msg && <div className="warning-box" style={{ marginBottom: 14 }}>{msg}</div>}
      {data.length === 0 ? (
        <div className="empty-state">No industry jobs synced yet.</div>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Product</th><th>Activity</th>
              <th style={{ textAlign: 'right' }}>Runs</th>
              <th>Status</th>
              <th style={{ textAlign: 'right' }}>Cost</th>
              <th>Ends</th>
            </tr>
          </thead>
          <tbody>
            {data.map(j => (
              <tr key={j.job_id}>
                <td>{j.product_name || j.product_type_id}</td>
                <td>{j.activity}</td>
                <td style={{ textAlign: 'right' }}>{fmtNum(j.runs)}</td>
                <td><span className="badge badge-warn">{j.status}</span></td>
                <td style={{ textAlign: 'right' }}>{fmtIsk(j.cost)}</td>
                <td>{fmtDate(j.end_date)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
