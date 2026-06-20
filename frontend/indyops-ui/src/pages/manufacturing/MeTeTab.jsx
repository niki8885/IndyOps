import { useState } from 'react'
import { post } from '../../api/client'
import { fmtIsk, fmtNum } from '../personal/common'
import { fmtTime, idBody, Label, Selectors } from './researchCommon'

export default function MeTeTab({ facilities, characters }) {
  const [type, setType] = useState(null)
  const [facilityId, setFacilityId] = useState('')
  const [characterId, setCharacterId] = useState('')
  const [fromMe, setFromMe] = useState(0)
  const [toMe, setToMe] = useState(10)
  const [fromTe, setFromTe] = useState(0)
  const [toTe, setToTe] = useState(20)
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
      from_me: Number(fromMe), to_me: Number(toMe),
      from_te: Number(fromTe), to_te: Number(toTe),
    }
    try { setRes(await post('/manufacturing/research/me-te', body)) }
    catch (e) { setErr(e.message); setRes(null) }
    finally { setLoading(false) }
  }

  return (
    <div style={{ marginTop: 18 }}>
      <Selectors {...{ type, setType, facilities, facilityId, setFacilityId, characters, characterId, setCharacterId }} />

      <div style={{ display: 'flex', gap: 18, alignItems: 'flex-end', marginBottom: 14, flexWrap: 'wrap' }}>
        <LevelPair label="ME" from={fromMe} to={toMe} setFrom={setFromMe} setTo={setToMe} max={10} />
        <LevelPair label="TE" from={fromTe} to={toTe} setFrom={setFromTe} setTo={setToTe} max={20} step={2} />
        <button className="btn btn-primary" disabled={!type || loading} onClick={run}>
          {loading ? 'Calculating…' : 'Calculate payback'}
        </button>
      </div>

      {err && <div className="error-box">{err}</div>}

      {res && (
        <div style={{ display: 'grid', gridTemplateColumns: '1.4fr 1fr', gap: 16 }}>
          <MeCard me={res.me} fac={res.facility} pricesOk={res.prices_available} />
          <TeCard te={res.te} fac={res.facility} />
        </div>
      )}
    </div>
  )
}

function MeCard({ me, fac, pricesOk }) {
  return (
    <div className="card">
      <h3 style={{ fontSize: 14, marginBottom: 10 }}>Material Efficiency {me.from} → {me.to}</h3>
      {!pricesOk && <div className="warning-box" style={{ marginBottom: 10 }}>ESI adjusted prices unavailable.</div>}
      <Headline
        label="Payback"
        value={me.payback_runs == null ? 'never (no saving)' : `${fmtNum(me.payback_runs)} runs`}
      />
      <Row k="Saving / run" v={fmtIsk(me.saving_per_run)} />
      <Row k="Research time" v={fmtTime(me.research_time_s)} />
      <Row k="Research cost" v={fmtIsk(me.research_cost.install_cost)} />
      {me.research_cost.structure_bonus > 0 && (
        <Row k={`Structure / rig bonus −${(fac?.cost_bonus_pct ?? 0).toFixed(1)}%`}
             v={`− ${fmtIsk(me.research_cost.structure_bonus)}`} dim />
      )}
      <Row k="ME index" v={`${((fac?.me_index ?? 0) * 100).toFixed(2)}%`} dim />

      <table style={{ marginTop: 12 }}>
        <thead>
          <tr><th>Material</th><th style={{ textAlign: 'right' }}>{me.from}</th>
            <th style={{ textAlign: 'right' }}>{me.to}</th>
            <th style={{ textAlign: 'right' }}>Saved/run</th></tr>
        </thead>
        <tbody>
          {me.materials.map(m => (
            <tr key={m.type_id} style={m.me_no_effect ? { opacity: 0.5 } : undefined}
                title={m.me_no_effect ? 'ME has no effect — rounds to the same quantity' : ''}>
              <td>{m.name}{m.me_no_effect && <span style={{ color: 'var(--border2)', marginLeft: 6 }}>· no ME effect</span>}</td>
              <td style={{ textAlign: 'right' }}>{fmtNum(m.qty_from)}</td>
              <td style={{ textAlign: 'right' }}>{fmtNum(m.qty_to)}</td>
              <td style={{ textAlign: 'right', color: m.saved_units ? 'var(--success)' : 'var(--border2)' }}>
                {m.saved_units ? `${fmtNum(m.saved_units)} (${fmtIsk(m.saved_isk)})` : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function TeCard({ te, fac }) {
  return (
    <div className="card">
      <h3 style={{ fontSize: 14, marginBottom: 10 }}>Time Efficiency {te.from} → {te.to}</h3>
      <Headline
        label="Time payback"
        value={te.time_payback_runs == null ? 'never' : `${fmtNum(te.time_payback_runs)} runs`}
      />
      <Row k="Faster / run" v={fmtTime(te.saving_per_run_s)} />
      <Row k="Manuf time / run" v={`${fmtTime(te.manuf_time_from_s)} → ${fmtTime(te.manuf_time_to_s)}`} />
      <Row k="Research time" v={fmtTime(te.research_time_s)} />
      <Row k="Research cost" v={fmtIsk(te.research_cost.install_cost)} />
      {te.research_cost.structure_bonus > 0 && (
        <Row k={`Structure / rig bonus −${(fac?.cost_bonus_pct ?? 0).toFixed(1)}%`}
             v={`− ${fmtIsk(te.research_cost.structure_bonus)}`} dim />
      )}
      <Row k="TE index" v={`${((fac?.te_index ?? 0) * 100).toFixed(2)}%`} dim />
    </div>
  )
}

function LevelPair({ label, from, to, setFrom, setTo, max, step = 1 }) {
  return (
    <div>
      <Label>{label} level</Label>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
        <input type="number" min="0" max={max} step={step} value={from}
               onChange={e => setFrom(e.target.value)} style={{ width: 64 }} />
        <span style={{ color: 'var(--text)' }}>→</span>
        <input type="number" min="0" max={max} step={step} value={to}
               onChange={e => setTo(e.target.value)} style={{ width: 64 }} />
      </div>
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

function Row({ k, v, dim }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', padding: '3px 0',
                  fontSize: 13, color: dim ? 'var(--text)' : 'var(--text-bright)' }}>
      <span>{k}</span><span>{v}</span>
    </div>
  )
}
