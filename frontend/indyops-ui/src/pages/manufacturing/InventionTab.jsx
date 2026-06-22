import { useState } from 'react'
import { post } from '../../api/client'
import MoneyInput from '../../components/MoneyInput'
import { fmtIsk, fmtNum } from '../personal/common'
import { idBody, Label, Selectors } from './researchCommon'

export default function InventionTab({ facilities, characters }) {
  const [type, setType] = useState(null)
  const [facilityId, setFacilityId] = useState('')
  const [characterId, setCharacterId] = useState('')
  const [finalProduct, setFinalProduct] = useState('')
  const [decryptor, setDecryptor] = useState('No Decryptor')
  const [runs, setRuns] = useState(10)
  const [refPrice, setRefPrice] = useState('')
  const [res, setRes] = useState(null)
  const [err, setErr] = useState('')
  const [loading, setLoading] = useState(false)

  async function run(overrides = {}) {
    if (!type) return
    setLoading(true); setErr('')
    const body = {
      ...idBody(type),
      facility_id: facilityId ? Number(facilityId) : null,
      character_id: characterId ? Number(characterId) : null,
      final_product_type_id: (overrides.finalProduct ?? finalProduct) ? Number(overrides.finalProduct ?? finalProduct) : null,
      decryptor: overrides.decryptor ?? decryptor,
      runs: Number(runs) || 10,
      reference_bpc_price: refPrice !== '' ? Number(refPrice) : null,
    }
    try {
      const r = await post('/manufacturing/research/invention', body)
      setRes(r)
      if (!finalProduct && r.final_product_type_id) setFinalProduct(String(r.final_product_type_id))
    } catch (e) { setErr(e.message); setRes(null) }
    finally { setLoading(false) }
  }

  const r = res?.result
  return (
    <div style={{ marginTop: 18 }}>
      <Selectors {...{ type, setType, facilities, facilityId, setFacilityId, characters, characterId, setCharacterId }} />

      <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end', marginBottom: 14, flexWrap: 'wrap' }}>
        {res?.products?.length > 1 && (
          <div style={{ minWidth: 180 }}>
            <Label>Final product</Label>
            <select value={finalProduct} onChange={e => { setFinalProduct(e.target.value); run({ finalProduct: e.target.value }) }}>
              {res.products.map(p => <option key={p.product_type_id} value={p.product_type_id}>{p.product_name}</option>)}
            </select>
          </div>
        )}
        <div style={{ minWidth: 170 }}>
          <Label>Decryptor</Label>
          <select value={decryptor} onChange={e => { setDecryptor(e.target.value); if (res) run({ decryptor: e.target.value }) }}>
            {(res?.decryptors || ['No Decryptor']).map(d => <option key={d} value={d}>{d}</option>)}
          </select>
        </div>
        <div style={{ width: 90 }}>
          <Label>Runs</Label>
          <input type="number" min="1" value={runs} onChange={e => setRuns(e.target.value)} />
        </div>
        <div style={{ width: 150 }}>
          <Label>Ref. BPC price <span style={{ color: 'var(--border2)' }}>(contract)</span></Label>
          <MoneyInput value={refPrice} onChange={e => setRefPrice(e.target.value)} placeholder="optional" />
        </div>
        <button className="btn btn-primary" disabled={!type || loading} onClick={() => run()}>
          {loading ? 'Calculating…' : 'Calculate'}
        </button>
      </div>

      {err && <div className="error-box">{err}</div>}

      {res && r && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, maxWidth: 760 }}>
          <div className="card">
            <h3 style={{ fontSize: 14, marginBottom: 10 }}>{res.final_product_name} · {res.decryptor}</h3>
            {!res.products && <div className="warning-box">No prices.</div>}
            <Headline label={`${fmtNum(res.runs)} runs →`} value={`${fmtNum(res.expected_successful_bpcs)} BPC`} />
            <Row k="Success chance" v={`${(r.probability * 100).toFixed(1)}%`} />
            <Row k="Resulting BPC" v={`ME ${r.bpc_me} · TE ${r.bpc_te} · ${fmtNum(r.bpc_runs)} runs`} />
            <Row k="Datacores / attempt" v={fmtIsk(res.datacore_cost_per_attempt)} dim />
            <Row k="Decryptor / attempt" v={fmtIsk(res.decryptor_price)} dim />
            <Row k="Total cost (all runs)" v={fmtIsk(res.total_cost)} />
          </div>

          <div className="card">
            <h3 style={{ fontSize: 14, marginBottom: 10 }}>Per resulting blueprint</h3>
            <Headline label="Cost / BPC" value={fmtIsk(r.cost_per_bpc)} />
            <Row k="Cost / run" v={fmtIsk(r.cost_per_run)} />
            <Row k="Cost / unit (with mfg)" v={fmtIsk(r.cost_per_unit)} />
            <Row k="Profit / run" v={fmtIsk(r.profit_per_run)} strong={r.profit_per_run > 0} />
            <Row k="Margin" v={`${r.margin_pct?.toFixed(1)}%`} />
            {res.reference && (
              <div style={{ marginTop: 10, paddingTop: 10, borderTop: '1px solid var(--border)' }}>
                <Row k="Contract BPC price" v={fmtIsk(res.reference.reference_bpc_price)} dim />
                <Row k={res.reference.cheaper_to_invent ? '✓ Invent saves' : '✗ Buy is cheaper by'}
                     v={fmtIsk(Math.abs(res.reference.savings_per_bpc))}
                     strong={res.reference.cheaper_to_invent} />
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function Headline({ label, value }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline',
                  padding: '8px 0', borderBottom: '1px solid var(--border)', marginBottom: 8 }}>
      <span style={{ fontSize: 12, color: 'var(--text)' }}>{label}</span>
      <span style={{ fontSize: 18, fontWeight: 600, color: 'var(--accent)' }}>{value}</span>
    </div>
  )
}

function Row({ k, v, dim, strong }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', padding: '3px 0',
                  fontSize: 13, color: dim ? 'var(--text)' : 'var(--text-bright)' }}>
      <span>{k}</span>
      <span style={{ color: strong ? 'var(--success)' : undefined, fontWeight: strong ? 600 : 400 }}>{v}</span>
    </div>
  )
}
