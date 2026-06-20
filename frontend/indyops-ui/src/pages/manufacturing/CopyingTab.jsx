import { useState } from 'react'
import { post } from '../../api/client'
import { fmtIsk, fmtNum } from '../personal/common'
import { fmtTime, idBody, Label, Selectors } from './researchCommon'

export default function CopyingTab({ facilities, characters }) {
  const [type, setType] = useState(null)
  const [facilityId, setFacilityId] = useState('')
  const [characterId, setCharacterId] = useState('')
  const [runs, setRuns] = useState('')      // runs per copy; blank = blueprint max
  const [copies, setCopies] = useState(1)
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
      copies: Number(copies) || 1,
    }
    if (runs) body.runs_per_copy = Number(runs)
    try { setRes(await post('/manufacturing/research/copy', body)) }
    catch (e) { setErr(e.message); setRes(null) }
    finally { setLoading(false) }
  }

  const c = res?.copy
  return (
    <div style={{ marginTop: 18 }}>
      <Selectors {...{ type, setType, facilities, facilityId, setFacilityId, characters, characterId, setCharacterId }} />

      <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end', marginBottom: 14 }}>
        <div style={{ width: 140 }}>
          <Label>Runs / copy <span style={{ color: 'var(--border2)' }}>(blank = max)</span></Label>
          <input type="number" min="1" value={runs} onChange={e => setRuns(e.target.value)} placeholder="max" />
        </div>
        <div style={{ width: 100 }}>
          <Label>Copies</Label>
          <input type="number" min="1" value={copies} onChange={e => setCopies(e.target.value)} />
        </div>
        <button className="btn btn-primary" disabled={!type || loading} onClick={run}>
          {loading ? 'Calculating…' : 'Calculate'}
        </button>
      </div>

      {err && <div className="error-box">{err}</div>}

      {res && c && (
        <div className="card" style={{ maxWidth: 560 }}>
          <h3 style={{ fontSize: 14, marginBottom: 12 }}>{res.blueprint_name || res.product_name}</h3>
          {!res.prices_available && (
            <div className="warning-box" style={{ marginBottom: 10 }}>ESI adjusted prices unavailable — cost may read 0.</div>
          )}
          <Row k="Copies × runs" v={`${fmtNum(c.copies)} × ${fmtNum(c.runs_per_copy)} = ${fmtNum(c.total_runs)} runs`} />
          <Row k="Total time" v={fmtTime(c.time_s)} />
          <Row k="Time / copy" v={fmtTime(c.time_per_copy_s)} />
          <hr style={{ border: 'none', borderTop: '1px solid var(--border)', margin: '10px 0' }} />
          <Row k="System cost index" v={`${((res.facility?.copy_index ?? 0) * 100).toFixed(2)}%`} dim />
          <Row k="Job base cost" v={fmtIsk(c.cost.base_cost)} dim />
          {c.cost.structure_bonus > 0 && (
            <Row k={`Structure / rig bonus −${(res.facility?.cost_bonus_pct ?? 0).toFixed(1)}%`}
                 v={`− ${fmtIsk(c.cost.structure_bonus)}`} dim />
          )}
          <Row k="Facility tax + SCC" v={fmtIsk((c.cost.facility_tax || 0) + (c.cost.scc_surcharge || 0))} dim />
          <Row k="Install cost" v={fmtIsk(c.cost.install_cost)} strong />
        </div>
      )}
    </div>
  )
}

function Row({ k, v, dim, strong }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0',
                  fontSize: 13, color: dim ? 'var(--text)' : 'var(--text-bright)' }}>
      <span>{k}</span>
      <span style={{ color: strong ? 'var(--accent)' : undefined, fontWeight: strong ? 600 : 400 }}>{v}</span>
    </div>
  )
}
