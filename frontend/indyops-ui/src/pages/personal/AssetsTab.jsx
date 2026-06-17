import { useState } from 'react'
import { post } from '../../api/client'
import { useApi, fmtNum } from './common'

export default function AssetsTab({ charId }) {
  const { data, loading, error } = useApi(`/characters/${charId}/assets`, [charId])
  const [msg, setMsg]   = useState('')
  const [busy, setBusy] = useState(false)

  async function importAssets() {
    setBusy(true); setMsg('')
    try {
      const r = await post(`/characters/${charId}/import/assets`, {})
      setMsg(`Imported ${r.imported} item type(s) into Inventory.`)
    } catch (e) { setMsg(e.message) }
    finally { setBusy(false) }
  }

  if (loading) return <div className="empty-state">Loading…</div>
  if (error)   return <div className="error-box">{error}</div>

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
        <span style={{ color: 'var(--text)', fontSize: 13 }}>{data.length} stack(s)</span>
        <button className="btn btn-primary btn-sm" onClick={importAssets} disabled={busy || !data.length}>
          {busy ? 'Importing…' : 'Import into Inventory'}
        </button>
      </div>
      {msg && <div className="warning-box" style={{ marginBottom: 14 }}>{msg}</div>}
      {data.length === 0 ? (
        <div className="empty-state">No assets synced yet.</div>
      ) : (
        <table>
          <thead>
            <tr><th>Item</th><th style={{ textAlign: 'right' }}>Qty</th><th>Location</th><th>Flag</th></tr>
          </thead>
          <tbody>
            {data.map(a => (
              <tr key={a.item_id}>
                <td>{a.type_name || a.type_id}</td>
                <td style={{ textAlign: 'right' }}>{fmtNum(a.quantity)}</td>
                <td>{a.location_name || a.location_id}</td>
                <td style={{ color: 'var(--text)', fontSize: 12 }}>{a.location_flag}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
