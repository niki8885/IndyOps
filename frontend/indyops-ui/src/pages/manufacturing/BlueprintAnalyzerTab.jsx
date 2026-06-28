/**
 * Blueprint Collection Analyzer (IO-59 companion) — Manufacturing sub-tab.
 *
 * Paste a blueprint collection (one name per line, repeats grouped). Pick the factories,
 * ME/TE, runs and where materials are bought; rank which blueprints are worth building by
 * ROI and income/hour with a scatter — no Monte-Carlo, just the deterministic analytics.
 * Backend: /manufacturing/blueprint-analyzer/analyze.
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

const structFromFacility = f => ({
  place_id: f.id, name: f.name,
  system_cost_index: f.system_cost_index || 0,
  facility_tax_pct: f.tax || 0,
  structure_discount_pct: f.cost_bonus || 0,
  man_lines: 0, react_lines: 0,
})

const SAMPLE = `Miner II Blueprint
Acolyte II Blueprint
Acolyte II Blueprint
Acolyte II Blueprint
Armor Command Burst II Blueprint
Armor Command Burst II Blueprint`

export default function BlueprintAnalyzerTab() {
  const [facilities, setFacilities] = useState([])
  const [characters, setCharacters] = useState([])

  const [text, setText] = useState('')
  const [mfgFacId, setMfgFacId] = useState('')
  const [reactFacId, setReactFacId] = useState('')
  const [me, setMe] = useState(0)
  const [te, setTe] = useState(0)
  const [runs, setRuns] = useState(10)
  const [buyMaterials, setBuyMaterials] = useState(true)
  const [manSlots, setManSlots] = useState(10)
  const [reactSlots, setReactSlots] = useState(0)
  const [horizon, setHorizon] = useState(24)

  const [selectedRegions, setSelectedRegions] = useState(new Set([10000002]))
  const [basis, setBasis] = useState('buy')
  const [includeCJ, setIncludeCJ] = useState(false)
  const [sellVenue, setSellVenue] = useState('jita_sell')
  const [freight, setFreight] = useState(0)
  const [sellChar, setSellChar] = useState('')
  const [produceChar, setProduceChar] = useState('')

  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [sortKey, setSortKey] = useState('roi')

  useEffect(() => {
    get('/facilities').then(setFacilities).catch(() => {})
    get('/characters').then(setCharacters).catch(() => {})
  }, [])

  const mfgFacilities = useMemo(() => facilities.filter(f => EC_FAC.has(f.facility_type)), [facilities])
  const reactFacilities = useMemo(() => facilities.filter(f => REACTION_FAC.has(f.facility_type)), [facilities])

  function toggleRegion(rid) {
    setSelectedRegions(prev => {
      const next = new Set(prev)
      if (next.has(rid)) { if (next.size > 1) next.delete(rid) } else next.add(rid)
      return next
    })
  }

  async function runAnalyze() {
    setError(''); setLoading(true); setResult(null)
    const structures = []
    const mf = facilities.find(f => f.id === Number(mfgFacId))
    const rf = facilities.find(f => f.id === Number(reactFacId))
    if (mf) structures.push(structFromFacility(mf))
    if (rf) structures.push(structFromFacility(rf))
    try {
      setResult(await post('/manufacturing/blueprint-analyzer/analyze', {
        blueprint_text: text,
        me_pct: Number(me) || 0, te_pct: Number(te) || 0, runs: Number(runs) || 10,
        buy_materials: buyMaterials,
        structures,
        man_slots: Number(manSlots) || 0, react_slots: Number(reactSlots) || 0,
        horizon_hours: Number(horizon) || 24,
        region_ids: [...selectedRegions], region_id: [...selectedRegions][0] || 10000002,
        price_basis: basis, include_cj: includeCJ,
        sell_venue: sellVenue, freight_per_unit: Number(freight) || 0,
        produce_character_id: produceChar ? Number(produceChar) : null,
        sell_character_id: sellChar ? Number(sellChar) : null,
      }))
    } catch (e) {
      setError(e.message || 'Analyze failed')
    } finally {
      setLoading(false)
    }
  }

  const sorted = useMemo(() => {
    if (!result?.candidates) return []
    return [...result.candidates].sort((a, b) => (b[sortKey] ?? -Infinity) - (a[sortKey] ?? -Infinity))
  }, [result, sortKey])

  return (
    <div>
      <p style={{ fontSize: 12, color: 'var(--text)', marginTop: 4 }}>
        Paste your blueprint list — which of them are worth building, ranked by ROI and income/hour.
        Repeats are grouped (e.g. <em>Miner II Blueprint ×20</em>). No Monte-Carlo, just the deterministic analytics.
      </p>

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(280px, 1.1fr) minmax(320px, 1.4fr)', gap: 14 }}>
        <Panel title="Blueprint list">
          <textarea value={text} onChange={e => setText(e.target.value)} rows={12}
            placeholder={'Paste blueprint names, one per line…\n\n' + SAMPLE}
            style={{ width: '100%', fontSize: 12, fontFamily: 'monospace', resize: 'vertical', padding: 6 }} />
          <button type="button" className="btn btn-ghost btn-sm" style={{ marginTop: 6 }}
            onClick={() => setText(SAMPLE)}>Insert sample</button>
        </Panel>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 14 }}>
          <Panel title="Build settings">
            <Field label="Manufacturing factory">
              <select value={mfgFacId} onChange={e => setMfgFacId(e.target.value)} style={sel}>
                <option value="">— select —</option>
                {mfgFacilities.map(f => <option key={f.id} value={f.id}>{f.name}</option>)}
              </select>
            </Field>
            <Field label="Reaction station (optional, for optimal mode)">
              <select value={reactFacId} onChange={e => setReactFacId(e.target.value)} style={sel}>
                <option value="">— none —</option>
                {reactFacilities.map(f => <option key={f.id} value={f.id}>{f.name}</option>)}
              </select>
            </Field>
            <Row>
              <Field label="ME %"><input type="number" min={0} max={10} value={me} onChange={e => setMe(e.target.value)} style={inp} /></Field>
              <Field label="TE %"><input type="number" min={0} max={20} value={te} onChange={e => setTe(e.target.value)} style={inp} /></Field>
              <Field label="Runs / BP"><input type="number" min={1} value={runs} onChange={e => setRuns(e.target.value)} style={inp} /></Field>
            </Row>
            <label style={chk}>
              <input type="checkbox" checked={buyMaterials} onChange={e => setBuyMaterials(e.target.checked)} />
              Buy all materials <span style={{ fontSize: 10, color: 'var(--border2)' }}>(off = build sub-components when cheaper)</span>
            </label>
            <Row>
              <Field label="Mfg slots"><input type="number" min={0} value={manSlots} onChange={e => setManSlots(e.target.value)} style={inp} /></Field>
              <Field label="Reaction slots"><input type="number" min={0} value={reactSlots} onChange={e => setReactSlots(e.target.value)} style={inp} /></Field>
              <Field label="Horizon h"><input type="number" min={1} value={horizon} onChange={e => setHorizon(e.target.value)} style={inp} /></Field>
            </Row>
          </Panel>

          <Panel title="Markets">
            <div style={{ fontSize: 10.5, color: 'var(--text)', marginBottom: 2 }}>Buy materials at</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              {REGIONS.map(r => (
                <label key={r.id} style={chk}>
                  <input type="checkbox" checked={selectedRegions.has(r.id)} onChange={() => toggleRegion(r.id)} />
                  {r.name}
                </label>
              ))}
              <label style={{ ...chk, color: includeCJ ? '#c8a951' : 'var(--text)' }}>
                <input type="checkbox" checked={includeCJ} onChange={e => setIncludeCJ(e.target.checked)} />
                C-J6MT <span style={{ fontSize: 10, color: 'var(--border2)' }}>(slow)</span>
              </label>
            </div>
            <Row>
              <Field label="Price side">
                <select value={basis} onChange={e => setBasis(e.target.value)} style={sel}>
                  <option value="buy">Buy</option><option value="sell">Sell</option>
                </select>
              </Field>
              <Field label="Sell venue">
                <select value={sellVenue} onChange={e => setSellVenue(e.target.value)} style={sel}>
                  <option value="jita_sell">Jita sell</option><option value="cj_sell">C-J sell</option>
                </select>
              </Field>
            </Row>
            <Field label="Freight (ISK / unit)">
              <input type="number" min={0} value={freight} onChange={e => setFreight(e.target.value)} style={inp} />
            </Field>
            <Field label="Selling character">
              <select value={sellChar} onChange={e => setSellChar(e.target.value)} style={sel}>
                <option value="">— default —</option>
                {characters.map(c => <option key={c.id} value={c.id}>{c.character_name}</option>)}
              </select>
            </Field>
            <Field label="Producing character">
              <select value={produceChar} onChange={e => setProduceChar(e.target.value)} style={sel}>
                <option value="">— default —</option>
                {characters.map(c => <option key={c.id} value={c.id}>{c.character_name}</option>)}
              </select>
            </Field>
          </Panel>
        </div>
      </div>

      <div style={{ marginTop: 14, display: 'flex', alignItems: 'center', gap: 12 }}>
        <button className="btn btn-primary" onClick={runAnalyze} disabled={loading || !text.trim()}>
          {loading ? 'Analysing…' : 'Analyze collection'}
        </button>
        {error && <span style={{ color: 'var(--danger, #c0392b)', fontSize: 12 }}>{error}</span>}
        {result && (
          <span style={{ fontSize: 12, color: 'var(--text)' }}>
            {result.resolved} blueprints · engine {result.engine}
            {result.unresolved?.length > 0 &&
              <span style={{ color: '#c8a951' }}> · {result.unresolved.length} unresolved</span>}
          </span>
        )}
      </div>
      {result?.unresolved?.length > 0 && (
        <div style={{ fontSize: 11, color: '#c8a951', marginTop: 6 }}>
          Not found / not buildable: {result.unresolved.join(', ')}
        </div>
      )}

      {result && (
        <div style={{ marginTop: 16 }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'minmax(280px,1fr) minmax(280px,1fr)', gap: 14 }}>
            <Panel title="ROI × income / hour"><RoiScatter points={result.scatter} /></Panel>
            <Panel title="Best use of your slots"><SlotFill fill={result.slot_fill} /></Panel>
          </div>
          <div className="card" style={{ padding: 0, marginTop: 14, overflowX: 'auto' }}>
            <table className="data-table" style={{ width: '100%', fontSize: 12 }}>
              <thead>
                <tr>
                  <Th>Blueprint</Th>
                  <Th r>Qty</Th>
                  <Th r>Make cost</Th>
                  <Th r>Sell</Th>
                  <Th r>Profit / copy</Th>
                  <Th r sortable onClick={() => setSortKey('roi')} active={sortKey === 'roi'}>ROI</Th>
                  <Th r sortable onClick={() => setSortKey('isk_per_hour')} active={sortKey === 'isk_per_hour'}>ISK / h</Th>
                  <Th r>Group total</Th>
                </tr>
              </thead>
              <tbody>
                {sorted.map(c => {
                  const color = c.profit >= 0 ? 'var(--accent)' : 'var(--danger, #c0392b)'
                  return (
                    <tr key={c.type_id}>
                      <td>
                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                          <img src={iconUrl(c.type_id, 24)} width={20} height={20} alt="" style={{ borderRadius: 3 }} />
                          {c.name} <span style={{ color: 'var(--border2)' }}>×{c.count}</span>
                        </span>
                      </td>
                      <td style={tr}>{c.runs}r</td>
                      <td style={tr}>{fmtIsk(c.total_make_cost)}</td>
                      <td style={tr}>{fmtIsk(c.revenue)}</td>
                      <td style={{ ...tr, color }}>{fmtIsk(c.profit)}</td>
                      <td style={{ ...tr, fontWeight: 700 }}>{fmtPct(c.roi)}</td>
                      <td style={tr}>{fmtIsk(c.isk_per_hour)}</td>
                      <td style={{ ...tr, color }}>{fmtIsk(c.group_profit)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
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
        <Stat label="Mfg slots" value={fmtPct(fill.man_util)} />
        <Stat label="Reaction slots" value={fmtPct(fill.react_util)} />
      </div>
      <table style={{ width: '100%', fontSize: 11.5 }}>
        <thead><tr><Th>Blueprint</Th><Th r>Batches</Th><Th r>Mfg h</Th><Th r>Profit</Th></tr></thead>
        <tbody>
          {fill.chosen.map(p => (
            <tr key={p.type_id}>
              <td>{p.name}</td>
              <td style={tr}>{p.count}</td>
              <td style={tr}>{fmtH(p.man_seconds)}</td>
              <td style={{ ...tr, color: 'var(--accent)' }}>{fmtIsk(p.profit)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function RoiScatter({ points }) {
  if (!points || !points.length) return <div style={{ color: 'var(--text)', fontSize: 12 }}>—</div>
  const W = 320, H = 240, P = 40
  const xs = points.map(p => p.roi), ys = points.map(p => p.isk_per_hour)
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

const sel = { width: '100%', padding: '3px 5px', fontSize: 12 }
const inp = { width: '100%', padding: '3px 5px', fontSize: 12 }
const tr = { textAlign: 'right', fontVariantNumeric: 'tabular-nums' }
const chk = { display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, cursor: 'pointer', color: 'var(--text)', marginTop: 4 }

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
function Row({ children }) { return <div style={{ display: 'flex', gap: 8 }}>{children}</div> }
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
