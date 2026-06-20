import { useState } from 'react'
import { post } from '../../api/client'
import { fmtIsk, fmtNum } from '../personal/common'
import { idBody, Selectors } from './researchCommon'

export default function InventionOptimizerTab({ facilities, characters }) {
  const [type, setType] = useState(null)
  const [facilityId, setFacilityId] = useState('')
  const [characterId, setCharacterId] = useState('')
  const [res, setRes] = useState(null)
  const [err, setErr] = useState('')
  const [loading, setLoading] = useState(false)

  async function run() {
    if (!type) return
    setLoading(true); setErr('')
    const body = {
      ...idBody(type),
      facility_id: facilityId ? Number(facilityId) : null,
      character_id: characterId ? Number(characterId) : null,
    }
    try { setRes(await post('/manufacturing/research/invention/optimize', body)) }
    catch (e) { setErr(e.message); setRes(null) }
    finally { setLoading(false) }
  }

  return (
    <div style={{ marginTop: 18 }}>
      <Selectors {...{ type, setType, facilities, facilityId, setFacilityId, characters, characterId, setCharacterId }} />
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 14 }}>
        <button className="btn btn-primary" disabled={!type || loading} onClick={run}>
          {loading ? 'Optimizing…' : 'Optimize all decryptors × products'}
        </button>
        {res && (
          <span style={{ fontSize: 11, color: 'var(--text)' }}>
            ranked by production profit · engine: <b style={{ color: 'var(--accent)' }}>{res.engine}</b>
          </span>
        )}
      </div>

      {err && <div className="error-box">{err}</div>}

      {res && (
        <>
          {!res.prices_available && <div className="warning-box" style={{ marginBottom: 10 }}>ESI adjusted prices unavailable.</div>}
          <div className="card" style={{ padding: 0, overflowX: 'auto' }}>
            <table>
              <thead>
                <tr>
                  <th>#</th><th>Product</th><th>Decryptor</th>
                  <th style={{ textAlign: 'right' }}>Chance</th>
                  <th style={{ textAlign: 'right' }}>BPC</th>
                  <th style={{ textAlign: 'right' }}>Cost/BPC</th>
                  <th style={{ textAlign: 'right' }}>Cost/unit</th>
                  <th style={{ textAlign: 'right' }}>Profit/run</th>
                  <th style={{ textAlign: 'right' }}>Margin</th>
                </tr>
              </thead>
              <tbody>
                {res.ranked.map(c => (
                  <tr key={c.label} style={c.rank === 1 ? { background: 'var(--accent-glow)' } : undefined}>
                    <td style={{ color: c.rank === 1 ? 'var(--accent)' : 'var(--text)', fontWeight: c.rank === 1 ? 700 : 400 }}>{c.rank}</td>
                    <td style={{ color: 'var(--text-white)', whiteSpace: 'nowrap' }}>{c.product_name}</td>
                    <td style={{ whiteSpace: 'nowrap' }}>{c.decryptor}</td>
                    <td style={{ textAlign: 'right' }}>{(c.probability * 100).toFixed(1)}%</td>
                    <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>
                      {fmtNum(c.bpc_runs)}r · {c.bpc_me}/{c.bpc_te}
                    </td>
                    <td style={{ textAlign: 'right' }}>{fmtIsk(c.cost_per_bpc)}</td>
                    <td style={{ textAlign: 'right' }}>{fmtIsk(c.cost_per_unit)}</td>
                    <td style={{ textAlign: 'right', color: c.profit_per_run > 0 ? 'var(--success)' : 'var(--danger)' }}>
                      {fmtIsk(c.profit_per_run)}
                    </td>
                    <td style={{ textAlign: 'right' }}>{c.margin_pct?.toFixed(1)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}
