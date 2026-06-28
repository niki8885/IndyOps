/**
 * Reaction Planner (IO-59) — Manufacturing sub-tab.
 *
 * Inputs: a reaction station (+ optional component factory), the available manufacturing
 * and reaction slots, the buy markets (base regions + C-J, like the calculator) and a sell
 * venue. Sweeps the candidate universe (final reaction products + T2 components), ranks
 * them by ROI / income-per-hour (scatter), compares building reactions from scratch vs
 * buying the finished intermediates, fills the slots so they don't idle, and runs Monte-
 * Carlo on demand per candidate. Backend: /manufacturing/reaction-planner/*.
 */
import { useState, useEffect, useMemo } from 'react'
import { get, post } from '../../api/client'

const REGIONS = [
  { id: 10000002, name: 'Jita (The Forge)' },
  { id: 10000043, name: 'Amarr (Domain)' },
  { id: 10000032, name: 'Dodixie (Sinq Laison)' },
  { id: 10000030, name: 'Rens (Heimatar)' },
  { id: 10000042, name: 'Hek (Metropolis)' },
]
const REACTION_FAC = new Set(['Athanor', 'Tatara'])
const EC_FAC = new Set(['Raitaru', 'Azbel', 'Sotiyo'])
const iconUrl = (id, size = 32) => `https://images.evetech.net/types/${id}/icon?size=${size}`

const fmtIsk = n => {
  if (n == null || !isFinite(n)) return '—'
  const a = Math.abs(n)
  if (a >= 1e9) return (n / 1e9).toFixed(2) + 'B'
  if (a >= 1e6) return (n / 1e6).toFixed(2) + 'M'
  if (a >= 1e3) return (n / 1e3).toFixed(1) + 'k'
  return n.toFixed(0)
}
const fmtPct = n => (n == null || !isFinite(n) ? '—' : (n * 100).toFixed(1) + '%')
const fmtH = s => (s == null ? '—' : (s / 3600).toFixed(1) + 'h')

function structFromFacility(f) {
  return {
    place_id: f.id, name: f.name,
    system_cost_index: f.system_cost_index || 0,
    facility_tax_pct: f.tax || 0,
    structure_discount_pct: f.cost_bonus || 0,
    man_lines: 0, react_lines: 0,
  }
}

export default function ReactionPlannerTab() {
  const [facilities, setFacilities] = useState([])
  const [characters, setCharacters] = useState([])
  const [universe, setUniverse] = useState({ reaction_groups: [], t2_groups: [] })

  const [reactionFacId, setReactionFacId] = useState('')
  const [componentFacId, setComponentFacId] = useState('')
  const [manSlots, setManSlots] = useState(10)
  const [reactSlots, setReactSlots] = useState(10)
  const [horizonDays, setHorizonDays] = useState(1)

  const [selectedRegions, setSelectedRegions] = useState(new Set([10000002]))
  const [basis, setBasis] = useState('buy')
  const [includeCJ, setIncludeCJ] = useState(false)
  const [delivery, setDelivery] = useState({})    // {regionId|'cj': ISK per unit}
  const [sellVenue, setSellVenue] = useState('jita_sell')
  const [freight, setFreight] = useState(0)

  const [includeReactions, setIncludeReactions] = useState(true)
  const [includeT2, setIncludeT2] = useState(true)
  const [reactGroups, setReactGroups] = useState(new Set())   // checked group ids (empty = all)
  const [t2Groups, setT2Groups] = useState(new Set())
  const [batchRuns, setBatchRuns] = useState(10)
  const [maxCandidates, setMaxCandidates] = useState(50)
  const [produceChar, setProduceChar] = useState('')
  const [sellChar, setSellChar] = useState('')

  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [sortKey, setSortKey] = useState('roi')
  const [expanded, setExpanded] = useState(null)
  const [mc, setMc] = useState({})            // {type_id: {loading, data, error}}

  useEffect(() => {
    get('/facilities').then(setFacilities).catch(() => {})
    get('/characters').then(setCharacters).catch(() => {})
    get('/manufacturing/reaction-planner/candidate-universe')
      .then(u => {
        setUniverse(u)
        setReactGroups(new Set((u.reaction_groups || []).map(g => g.group_id)))
        setT2Groups(new Set((u.t2_groups || []).map(g => g.group_id)))
      }).catch(() => {})
  }, [])

  const reactionFacilities = useMemo(
    () => facilities.filter(f => REACTION_FAC.has(f.facility_type)), [facilities])
  const componentFacilities = useMemo(
    () => facilities.filter(f => EC_FAC.has(f.facility_type)), [facilities])

  function toggleRegion(rid) {
    setSelectedRegions(prev => {
      const next = new Set(prev)
      if (next.has(rid)) { if (next.size > 1) next.delete(rid) } else next.add(rid)
      return next
    })
  }
  const setDeliv = (key, v) => setDelivery(d => ({ ...d, [key]: v }))
  const toggleIn = (set, setter) => id =>
    setter(prev => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n })

  // Send the checked group ids unless ALL are checked (then [] = no filter / all).
  function groupParam(checked, all) {
    return checked.size && checked.size < all.length ? [...checked] : []
  }

  function buildBody() {
    const structures = []
    const rf = facilities.find(f => f.id === Number(reactionFacId))
    const cf = facilities.find(f => f.id === Number(componentFacId))
    if (rf) structures.push(structFromFacility(rf))
    if (cf) structures.push(structFromFacility(cf))
    return {
      structures,
      man_slots: Number(manSlots) || 0,
      react_slots: Number(reactSlots) || 0,
      horizon_hours: (Number(horizonDays) || 1) * 24,
      region_ids: [...selectedRegions],
      region_id: [...selectedRegions][0] || 10000002,
      price_basis: basis,
      include_cj: includeCJ,
      region_delivery: Object.fromEntries(
        [...selectedRegions].map(rid => [rid, Number(delivery[rid]) || 0]).filter(([, v]) => v > 0)),
      cj_delivery: Number(delivery.cj) || 0,
      sell_venue: sellVenue,
      freight_per_unit: Number(freight) || 0,
      include_reaction_products: includeReactions,
      include_t2_components: includeT2,
      reaction_group_ids: groupParam(reactGroups, universe.reaction_groups),
      t2_group_ids: groupParam(t2Groups, universe.t2_groups),
      batch_runs: Number(batchRuns) || 10,
      max_candidates: Number(maxCandidates) || 50,
      produce_character_id: produceChar ? Number(produceChar) : null,
      sell_character_id: sellChar ? Number(sellChar) : null,
    }
  }

  async function runSweep() {
    setError(''); setLoading(true); setResult(null); setExpanded(null); setMc({})
    try {
      setResult(await post('/manufacturing/reaction-planner/sweep', buildBody()))
    } catch (e) {
      setError(e.message || 'Sweep failed')
    } finally {
      setLoading(false)
    }
  }

  async function runMC(typeId) {
    setMc(m => ({ ...m, [typeId]: { loading: true } }))
    try {
      const data = await post(`/manufacturing/reaction-planner/candidate/${typeId}/simulate`,
        { ...buildBody(), sim: { n_iterations: 25000 } })
      setMc(m => ({ ...m, [typeId]: { data } }))
    } catch (e) {
      setMc(m => ({ ...m, [typeId]: { error: e.message || 'Simulation failed' } }))
    }
  }

  const sorted = useMemo(() => {
    if (!result?.candidates) return []
    const k = sortKey
    return [...result.candidates].sort((a, b) => (b[k] ?? -Infinity) - (a[k] ?? -Infinity))
  }, [result, sortKey])

  return (
    <div>
      <p style={{ fontSize: 12, color: 'var(--text)', marginTop: 4 }}>
        Which final reaction products and T2 components are worth producing from scratch — ranked by
        ROI and income/hour, with a slot-fill plan so manufacturing and reaction slots don't sit idle.
      </p>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(230px, 1fr))', gap: 14 }}>
        <Panel title="Facilities & slots">
          <Field label="Reaction station">
            <select value={reactionFacId} onChange={e => setReactionFacId(e.target.value)} style={sel}>
              <option value="">— select —</option>
              {reactionFacilities.map(f => <option key={f.id} value={f.id}>{f.name}</option>)}
            </select>
          </Field>
          <Field label="Component factory (optional)">
            <select value={componentFacId} onChange={e => setComponentFacId(e.target.value)} style={sel}>
              <option value="">— none (reactions only) —</option>
              {componentFacilities.map(f => <option key={f.id} value={f.id}>{f.name}</option>)}
            </select>
          </Field>
          <Row>
            <Field label="Mfg slots"><input type="number" min={0} value={manSlots} onChange={e => setManSlots(e.target.value)} style={inp} /></Field>
            <Field label="Reaction slots"><input type="number" min={0} value={reactSlots} onChange={e => setReactSlots(e.target.value)} style={inp} /></Field>
            <Field label="Horizon (days)"><input type="number" min={1} value={horizonDays} onChange={e => setHorizonDays(e.target.value)} style={inp} /></Field>
          </Row>
        </Panel>

        <Panel title="Buy materials">
          <div style={{ display: 'flex', justifyContent: 'flex-end', fontSize: 9.5, color: 'var(--border2)', marginBottom: 2 }}>
            delivery ISK/unit
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            {REGIONS.map(r => {
              const on = selectedRegions.has(r.id)
              return (
                <div key={r.id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 6 }}>
                  <label style={{ ...chk, marginTop: 0 }}>
                    <input type="checkbox" checked={on} onChange={() => toggleRegion(r.id)} />
                    {r.name}
                  </label>
                  <input type="number" min={0} step={1} placeholder="—" value={delivery[r.id] ?? ''} disabled={!on}
                    onChange={e => setDeliv(r.id, e.target.value)} title="Optional delivery cost, ISK per unit"
                    style={{ width: 60, padding: '1px 4px', fontSize: 10, opacity: on ? 1 : 0.4 }} />
                </div>
              )
            })}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 6 }}>
              <label style={{ ...chk, marginTop: 0, color: includeCJ ? '#c8a951' : 'var(--text)' }}>
                <input type="checkbox" checked={includeCJ} onChange={e => setIncludeCJ(e.target.checked)} />
                C-J6MT <span style={{ fontSize: 10, color: 'var(--border2)' }}>(slow)</span>
              </label>
              <input type="number" min={0} step={1} placeholder="—" value={delivery.cj ?? ''} disabled={!includeCJ}
                onChange={e => setDeliv('cj', e.target.value)} title="Optional delivery cost, ISK per unit"
                style={{ width: 60, padding: '1px 4px', fontSize: 10, opacity: includeCJ ? 1 : 0.4 }} />
            </div>
          </div>
          <Field label="Price side">
            <select value={basis} onChange={e => setBasis(e.target.value)} style={sel}>
              <option value="buy">Buy orders</option>
              <option value="sell">Sell orders</option>
            </select>
          </Field>
        </Panel>

        <Panel title="Sell side">
          <Field label="Sell venue">
            <select value={sellVenue} onChange={e => setSellVenue(e.target.value)} style={sel}>
              <option value="jita_sell">Jita sell</option>
              <option value="cj_sell">C-J sell</option>
            </select>
          </Field>
          <Field label="Delivery / freight (ISK per unit)">
            <input type="number" min={0} value={freight} onChange={e => setFreight(e.target.value)} style={inp} />
          </Field>
          <Field label="Selling character (tax/broker)">
            <select value={sellChar} onChange={e => setSellChar(e.target.value)} style={sel}>
              <option value="">— default (no fees) —</option>
              {characters.map(c => <option key={c.id} value={c.id}>{c.character_name}</option>)}
            </select>
          </Field>
          <Field label="Producing character (skills)">
            <select value={produceChar} onChange={e => setProduceChar(e.target.value)} style={sel}>
              <option value="">— default —</option>
              {characters.map(c => <option key={c.id} value={c.id}>{c.character_name}</option>)}
            </select>
          </Field>
        </Panel>

        <Panel title="Candidates">
          <label style={chk}>
            <input type="checkbox" checked={includeReactions} onChange={e => setIncludeReactions(e.target.checked)} />
            Final reaction products
          </label>
          <GroupFilter groups={universe.reaction_groups} checked={reactGroups}
            toggle={toggleIn(reactGroups, setReactGroups)} disabled={!includeReactions} />
          <label style={{ ...chk, marginTop: 8 }}>
            <input type="checkbox" checked={includeT2} onChange={e => setIncludeT2(e.target.checked)} />
            T2 components
          </label>
          <GroupFilter groups={universe.t2_groups} checked={t2Groups}
            toggle={toggleIn(t2Groups, setT2Groups)} disabled={!includeT2} />
          <Row>
            <Field label="Runs / batch"><input type="number" min={1} value={batchRuns} onChange={e => setBatchRuns(e.target.value)} style={inp} /></Field>
            <Field label="Max candidates"><input type="number" min={1} max={200} value={maxCandidates} onChange={e => setMaxCandidates(e.target.value)} style={inp} /></Field>
          </Row>
        </Panel>
      </div>

      <div style={{ marginTop: 14, display: 'flex', alignItems: 'center', gap: 12 }}>
        <button className="btn btn-primary" onClick={runSweep} disabled={loading}>
          {loading ? 'Analysing…' : 'Run sweep'}
        </button>
        {error && <span style={{ color: 'var(--danger, #c0392b)', fontSize: 12 }}>{error}</span>}
        {result && (
          <span style={{ fontSize: 12, color: 'var(--text)' }}>
            {result.analysed} candidates · engine {result.engine}
            {result.truncated && <span style={{ color: '#c8a951' }}> · list truncated to max</span>}
          </span>
        )}
      </div>

      {result && (
        <div style={{ marginTop: 16 }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'minmax(280px, 1fr) minmax(280px, 1fr)', gap: 14 }}>
            <Panel title="ROI × income / hour">
              <RoiScatter points={result.scatter} />
            </Panel>
            <Panel title="Slot-fill plan (so slots don't idle)">
              <SlotFill fill={result.slot_fill} />
            </Panel>
          </div>

          <div className="card" style={{ padding: 0, marginTop: 14, overflowX: 'auto' }}>
            <table className="data-table" style={{ width: '100%', fontSize: 12 }}>
              <thead>
                <tr>
                  <Th>Product</Th>
                  <Th r>Make cost</Th>
                  <Th r>Sell</Th>
                  <Th r>Profit</Th>
                  <Th r sortable onClick={() => setSortKey('roi')} active={sortKey === 'roi'}>ROI</Th>
                  <Th r sortable onClick={() => setSortKey('isk_per_hour')} active={sortKey === 'isk_per_hour'}>ISK / h</Th>
                  <Th r>ISK / slot·h</Th>
                  <Th r>Reactions</Th>
                  <Th r>Mfg</Th>
                  <Th>Scratch vs bought</Th>
                  <Th></Th>
                </tr>
              </thead>
              <tbody>
                {sorted.map(c => (
                  <CandidateRow key={c.type_id} c={c} expanded={expanded === c.type_id}
                    onToggle={() => setExpanded(expanded === c.type_id ? null : c.type_id)}
                    onMC={() => runMC(c.type_id)} mc={mc[c.type_id]} />
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}

function CandidateRow({ c, expanded, onToggle, onMC, mc }) {
  const svb = c.scratch_vs_bought
  const profitColor = c.profit >= 0 ? 'var(--accent)' : 'var(--danger, #c0392b)'
  return (
    <>
      <tr style={{ cursor: 'pointer' }} onClick={onToggle}>
        <td>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            <img src={iconUrl(c.type_id, 24)} width={20} height={20} alt="" style={{ borderRadius: 3 }} />
            {c.name}
          </span>
        </td>
        <td style={tr}>{fmtIsk(c.total_make_cost)}</td>
        <td style={tr}>{fmtIsk(c.revenue)}</td>
        <td style={{ ...tr, color: profitColor }}>{fmtIsk(c.profit)}</td>
        <td style={{ ...tr, fontWeight: 700 }}>{fmtPct(c.roi)}</td>
        <td style={tr}>{fmtIsk(c.isk_per_hour)}</td>
        <td style={tr}>{fmtIsk(c.isk_per_slot_hour)}</td>
        <td style={tr}>{c.runs_by_activity?.['11'] || 0}</td>
        <td style={tr}>{c.runs_by_activity?.['1'] || 0}</td>
        <td>
          {svb
            ? <span style={{ color: svb.cheaper === 'scratch' ? 'var(--accent)' : '#c8a951' }}>
                {svb.cheaper === 'scratch' ? 'Scratch' : 'Buy reactions'} · saves {fmtIsk(Math.abs(svb.delta))}
              </span>
            : <span style={{ color: 'var(--border2)' }}>—</span>}
        </td>
        <td style={{ textAlign: 'right', color: 'var(--accent)' }}>{expanded ? '▾' : '▸'}</td>
      </tr>
      {expanded && (
        <tr>
          <td colSpan={11} style={{ background: 'var(--panel, #161b24)', padding: 12 }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'minmax(280px,1.2fr) minmax(260px,1fr)', gap: 16 }}>
              <div>
                <div style={subTitle}>Staged plan — reaction runs & blueprints needed</div>
                <table style={{ width: '100%', fontSize: 11 }}>
                  <thead><tr><Th>Blueprint / formula</Th><Th>Act</Th><Th r>Runs</Th><Th r>Jobs</Th><Th r>Batch</Th></tr></thead>
                  <tbody>
                    {c.blueprints.map(b => (
                      <tr key={b.type_id}>
                        <td>{b.name}</td>
                        <td>{b.activity === 11 ? 'Reaction' : 'Mfg'}</td>
                        <td style={tr}>{b.runs}</td>
                        <td style={tr}>{b.jobs}</td>
                        <td style={tr}>
                          {b.is_component
                            ? <span title="components batched 10–20" style={{ color: '#c8a951' }}>
                                {b.batches}×{b.batch_size}
                              </span>
                            : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div style={{ fontSize: 10.5, color: 'var(--border2)', marginTop: 4 }}>
                  Makespan {fmtH(c.total_time_s)} · {c.total_stages} stages · peak {c.peak_man} mfg / {c.peak_react} reaction slots.
                  Component blueprints flagged for 10–20 batches.
                </div>
              </div>
              <div>
                <div style={subTitle}>Monte-Carlo risk (25k)</div>
                <button className="btn btn-sm" onClick={onMC} disabled={mc?.loading}>
                  {mc?.loading ? 'Simulating…' : 'Run Monte-Carlo'}
                </button>
                {mc?.error && <div style={{ color: 'var(--danger,#c0392b)', fontSize: 11, marginTop: 6 }}>{mc.error}</div>}
                {mc?.data && <MCSummary m={mc.data.metrics} engine={mc.data.engine} />}
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  )
}

function MCSummary({ m, engine }) {
  if (!m) return null
  return (
    <div style={{ marginTop: 8, fontSize: 11.5 }}>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
        <Stat label="Expected profit" value={fmtIsk(m.expected_profit)} accent />
        <Stat label="P(loss)" value={fmtPct(m.prob_loss)} />
        <Stat label="Median" value={fmtIsk(m.median_profit)} />
        <Stat label="VaR 5%" value={fmtIsk(m.var5)} />
        <Stat label="Std dev" value={fmtIsk(m.std)} />
        <Stat label="Sharpe-like" value={(m.sharpe_like ?? 0).toFixed(2)} />
      </div>
      <div style={{ fontSize: 10, color: 'var(--border2)', marginTop: 4 }}>engine {engine}</div>
    </div>
  )
}

function SlotFill({ fill }) {
  if (!fill || fill.status === 'empty' || !fill.chosen?.length) {
    return <div style={{ fontSize: 12, color: 'var(--text)' }}>{fill?.note || 'No profitable fill for the given slots.'}</div>
  }
  return (
    <div>
      <div style={{ display: 'flex', gap: 16, marginBottom: 8, fontSize: 12 }}>
        <Stat label="Total ISK / hour" value={fmtIsk(fill.total_isk_per_hour)} accent />
        <Stat label="Reaction slots" value={fmtPct(fill.react_util)} />
        <Stat label="Mfg slots" value={fmtPct(fill.man_util)} />
      </div>
      <table style={{ width: '100%', fontSize: 11.5 }}>
        <thead><tr><Th>Product</Th><Th r>Batches</Th><Th r>React h</Th><Th r>Mfg h</Th><Th r>Profit</Th></tr></thead>
        <tbody>
          {fill.chosen.map(p => (
            <tr key={p.type_id}>
              <td>{p.name}</td>
              <td style={tr}>{p.count}</td>
              <td style={tr}>{fmtH(p.react_seconds)}</td>
              <td style={tr}>{fmtH(p.man_seconds)}</td>
              <td style={{ ...tr, color: 'var(--accent)' }}>{fmtIsk(p.profit)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ROI (x) × income/hour (y) scatter — inline SVG, same pattern as TradePortfolio Frontier.
function RoiScatter({ points }) {
  if (!points || !points.length) return <div style={{ color: 'var(--text)', fontSize: 12 }}>—</div>
  const W = 320, H = 240, P = 40
  const xs = points.map(p => p.roi)
  const ys = points.map(p => p.isk_per_hour)
  const xMin = Math.min(...xs, 0), xMax = Math.max(...xs) || 1
  const yMin = Math.min(...ys, 0), yMax = Math.max(...ys) || 1
  const sx = v => P + ((v - xMin) / (xMax - xMin || 1)) * (W - 2 * P)
  const sy = v => H - P - ((v - yMin) / (yMax - yMin || 1)) * (H - 2 * P)
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto' }}>
      <line x1={P} y1={H - P} x2={W - P} y2={H - P} stroke="var(--border2)" strokeWidth="1" />
      <line x1={P} y1={P} x2={P} y2={H - P} stroke="var(--border2)" strokeWidth="1" />
      {xMin < 0 && <line x1={sx(0)} y1={P} x2={sx(0)} y2={H - P} stroke="var(--border)" strokeWidth="0.6" strokeDasharray="3 3" />}
      <text x={W / 2} y={H - 6} fill="var(--text)" fontSize="10" textAnchor="middle">ROI →</text>
      <text x={12} y={H / 2} fill="var(--text)" fontSize="10" textAnchor="middle"
        transform={`rotate(-90 12 ${H / 2})`}>ISK / hour →</text>
      {points.map(p => (
        <circle key={p.type_id} cx={sx(p.roi)} cy={sy(p.isk_per_hour)} r="3"
          fill={p.profit >= 0 ? 'var(--accent)' : 'var(--danger, #c0392b)'} opacity="0.75">
          <title>{`${p.name}: ROI ${fmtPct(p.roi)}, ${fmtIsk(p.isk_per_hour)}/h`}</title>
        </circle>
      ))}
    </svg>
  )
}

function GroupFilter({ groups, checked, toggle, disabled }) {
  if (!groups?.length) return null
  return (
    <div style={{ maxHeight: 120, overflowY: 'auto', marginTop: 4, paddingLeft: 6,
      opacity: disabled ? 0.4 : 1, pointerEvents: disabled ? 'none' : 'auto' }}>
      {groups.map(g => (
        <label key={g.group_id} style={{ ...chk, fontSize: 11 }}>
          <input type="checkbox" checked={checked.has(g.group_id)} onChange={() => toggle(g.group_id)} />
          {g.group_name} <span style={{ color: 'var(--border2)' }}>({g.count})</span>
        </label>
      ))}
    </div>
  )
}

// ── small presentational helpers ──
const sel = { width: '100%', padding: '3px 5px', fontSize: 12 }
const inp = { width: '100%', padding: '3px 5px', fontSize: 12 }
const tr = { textAlign: 'right', fontVariantNumeric: 'tabular-nums' }
const chk = { display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, cursor: 'pointer', color: 'var(--text)' }
const subTitle = { fontSize: 11, color: 'var(--accent)', fontWeight: 700, letterSpacing: 0.5, marginBottom: 6 }

function Panel({ title, children }) {
  return (
    <div className="card" style={{ padding: '12px 14px' }}>
      <div style={{ fontSize: 11, color: 'var(--accent)', fontWeight: 700, letterSpacing: 1, marginBottom: 8 }}>
        {title.toUpperCase()}
      </div>
      {children}
    </div>
  )
}
function Field({ label, children }) {
  return (
    <div style={{ marginBottom: 8, flex: 1 }}>
      <div style={{ fontSize: 10.5, color: 'var(--text)', marginBottom: 2 }}>{label}</div>
      {children}
    </div>
  )
}
function Row({ children }) {
  return <div style={{ display: 'flex', gap: 8 }}>{children}</div>
}
function Th({ children, r, sortable, onClick, active }) {
  return (
    <th onClick={onClick} style={{
      textAlign: r ? 'right' : 'left', cursor: sortable ? 'pointer' : 'default',
      color: active ? 'var(--accent)' : undefined, whiteSpace: 'nowrap', padding: '6px 8px',
    }}>{children}{sortable && (active ? ' ▾' : ' ⇅')}</th>
  )
}
function Stat({ label, value, accent }) {
  return (
    <div>
      <div style={{ fontSize: 10, color: 'var(--text)', textTransform: 'uppercase', letterSpacing: 0.4 }}>{label}</div>
      <div style={{ fontSize: 13, fontWeight: 600, color: accent ? 'var(--accent)' : 'var(--text-white)' }}>{value}</div>
    </div>
  )
}
