import { useState, useEffect } from 'react'
import { get, post } from '../api/client'
import TypeSearch from '../components/TypeSearch'
import SystemSearch from '../components/SystemSearch'
import RegionSearch from '../components/RegionSearch'
import { fmtIsk, fmtNum } from '../lib/plot'

const TABS = ['Acquisition Comparison', 'Gas (compressed vs regular)', 'Reprocessing Calculator']

// precise ISK for small per-unit values (fmtIsk collapses to K/M/B)
const isk = (n, dp = 2) =>
  n == null ? '—' : Number(n).toLocaleString('en-US', { maximumFractionDigits: dp })

const BASE_YIELD_PRESETS = [
  { label: 'NPC station', value: 0.50 },
  { label: 'Athanor', value: 0.50 },
  { label: 'Tatara', value: 0.55 },
]

const defaultRefine = () => ({
  base_yield: 0.50, reprocessing_lvl: 5, efficiency_lvl: 5, ore_specific_lvl: 4,
  implant_pct: 0, rig_type_ids: [], tax_pct: 5,
})

export default function OreAcquisitionPage() {
  const [tab, setTab] = useState(0)
  const [rigs, setRigs] = useState([])
  const [hubs, setHubs] = useState([])
  const [cj, setCj] = useState(null)

  useEffect(() => {
    get('/ore/rigs').then(r => setRigs(r.rigs || [])).catch(() => {})
    get('/ore/hubs').then(r => { setHubs(r.hubs || []); setCj(r.cj) }).catch(() => {})
  }, [])

  return (
    <div>
      <h2 style={{ marginBottom: 6 }}>Ore Acquisition &amp; Refining</h2>
      <p style={{ color: 'var(--text)', fontSize: 13, marginBottom: 18, maxWidth: 760 }}>
        Compare buying minerals, raw ore, or compressed ore — transport and refining
        yield/tax included — and find the cheapest way to stock each mineral.
      </p>
      <div className="tabs">
        {TABS.map((t, i) => (
          <button key={i} className={`tab-btn ${tab === i ? 'active' : ''}`} onClick={() => setTab(i)}>{t}</button>
        ))}
      </div>
      {tab === 0 && <ComparisonTab rigs={rigs} hubs={hubs} cj={cj} />}
      {tab === 1 && <GasTab hubs={hubs} cj={cj} />}
      {tab === 2 && <ReprocessTab rigs={rigs} />}
    </div>
  )
}

// Shared buy-location picker: hub presets + C-J (special parser) + region search.
function SourcePicker({ hubs, cj, sources, setSources }) {
  const has = (key) => sources.some(s => s.key === key)
  const toggle = (src) => setSources(has(src.key) ? sources.filter(s => s.key !== src.key) : [...sources, src])
  const addRegion = (r) => {
    if (!r || has(`r${r.region_id}`)) return
    setSources([...sources, { key: `r${r.region_id}`, label: r.region_name, region_id: r.region_id, system_name: null, cj: false }])
  }
  return (
    <>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 8 }}>
        {hubs.map(h => (
          <button key={h.key} type="button" className={`btn btn-sm ${has(h.key) ? '' : 'btn-ghost'}`}
                  onClick={() => toggle(h)}>{h.label}</button>
        ))}
        {cj && (
          <button type="button" className={`btn btn-sm ${has('cj') ? '' : 'btn-ghost'}`}
                  onClick={() => toggle(cj)} title="C-J6MT local market (special parser)">{cj.label} ⚡</button>
        )}
      </div>
      <RegionSearch onChange={addRegion} placeholder="Add another region…" />
      {sources.filter(s => s.key.startsWith('r')).map(s => (
        <div key={s.key} style={{ fontSize: 11, color: 'var(--text)', marginTop: 4 }}>
          {s.label} <button className="btn btn-ghost btn-sm" onClick={() => toggle(s)}>✕</button>
        </div>
      ))}
    </>
  )
}

// ────────────────────────────────────────────────────────────────────────────
// Shared sub-forms
// ────────────────────────────────────────────────────────────────────────────

function Panel({ title, children, right }) {
  return (
    <div className="card" style={{ padding: '12px 14px', marginBottom: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 8 }}>
        <div style={{ fontSize: 11, color: 'var(--accent)', fontWeight: 700, letterSpacing: 1 }}>{title.toUpperCase()}</div>
        <div style={{ marginLeft: 'auto' }}>{right}</div>
      </div>
      {children}
    </div>
  )
}

function Field({ label, children, hint }) {
  return (
    <label style={{ display: 'block', marginBottom: 10, minWidth: 0 }}>
      <span style={{ display: 'block', fontSize: 11, color: 'var(--text)', marginBottom: 3 }}>{label}</span>
      {children}
      {hint && <span style={{ display: 'block', fontSize: 10, color: 'var(--border2)', marginTop: 2 }}>{hint}</span>}
    </label>
  )
}

// inputs/selects fill their grid cell and never overflow it
const FIT = { width: '100%', boxSizing: 'border-box', maxWidth: '100%' }

function num(v) { const n = Number(v); return Number.isFinite(n) ? n : 0 }

function RefineSetup({ refine, setRefine, rigs }) {
  const set = (k, v) => setRefine({ ...refine, [k]: v })
  const [chars, setChars] = useState([])
  const [charId, setCharId] = useState('')
  const [charMsg, setCharMsg] = useState('')

  useEffect(() => { get('/characters').then(setChars).catch(() => {}) }, [])

  async function loadChar(id) {
    setCharId(id); setCharMsg('')
    if (!id) return
    try {
      const s = await get(`/ore/character-skills?character_id=${id}`)
      setRefine({
        ...refine,
        reprocessing_lvl: s.reprocessing_lvl,
        efficiency_lvl: s.efficiency_lvl,
        ore_specific_lvl: s.ore_specific_max,
      })
      setCharMsg(`Loaded ${s.character_name}: Reproc ${s.reprocessing_lvl} · Eff ${s.efficiency_lvl} · ore-specific ${s.ore_specific_max}`)
    } catch (e) { setCharMsg(e.message) }
  }
  const lvl = (k) => (
    <select value={refine[k]} onChange={e => set(k, Number(e.target.value))} style={FIT}>
      {[0, 1, 2, 3, 4, 5].map(l => <option key={l} value={l}>{l}</option>)}
    </select>
  )
  function toggleRig(id) {
    const has = refine.rig_type_ids.includes(id)
    set('rig_type_ids', has ? refine.rig_type_ids.filter(x => x !== id) : [...refine.rig_type_ids, id])
  }
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: '0 12px' }}>
      {chars.length > 0 && (
        <div style={{ gridColumn: '1 / -1', marginBottom: 6 }}>
          <Field label="Load skills from character" hint={charMsg || 'or enter levels manually below'}>
            <select value={charId} onChange={e => loadChar(e.target.value)} style={FIT}>
              <option value="">— manual —</option>
              {chars.map(c => <option key={c.id} value={c.id}>{c.character_name}</option>)}
            </select>
          </Field>
        </div>
      )}
      <div style={{ gridColumn: '1 / -1' }}>
        <Field label="Base yield" hint="structure / station base">
          <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', alignItems: 'center' }}>
            <input type="number" step="0.01" value={refine.base_yield}
                   onChange={e => set('base_yield', num(e.target.value))} style={{ width: 70 }} />
            {BASE_YIELD_PRESETS.map(p => (
              <button key={p.label} type="button" className="btn btn-ghost btn-sm"
                      title={p.label} onClick={() => set('base_yield', p.value)}>{p.label}</button>
            ))}
          </div>
        </Field>
      </div>
      <Field label="Reprocessing (+3%/lvl)">{lvl('reprocessing_lvl')}</Field>
      <Field label="Reproc. Efficiency (+2%/lvl)">{lvl('efficiency_lvl')}</Field>
      <Field label="Ore-specific (+2%/lvl)">{lvl('ore_specific_lvl')}</Field>
      <Field label="Implant">
        <select value={refine.implant_pct} onChange={e => set('implant_pct', Number(e.target.value))} style={FIT}>
          <option value={0}>None</option><option value={1}>RX-801 (+1%)</option>
          <option value={2}>RX-802 (+2%)</option><option value={4}>RX-804 (+4%)</option>
        </select>
      </Field>
      <Field label="Facility tax %">
        <input type="number" step="0.1" value={refine.tax_pct}
               onChange={e => set('tax_pct', num(e.target.value))} style={FIT} />
      </Field>
      <div style={{ gridColumn: '1 / -1' }}>
        <Field label={`Reprocessing rigs (${refine.rig_type_ids.length} selected · data-driven from SDE)`}>
          {rigs.length === 0
            ? <span style={{ fontSize: 11, color: 'var(--border2)' }}>No rigs in SDE — run an EVE sync to enable rig bonuses.</span>
            : <div style={{ maxHeight: 110, overflowY: 'auto', border: '1px solid var(--border2)', borderRadius: 4, padding: 6 }}>
                {rigs.map(r => (
                  <label key={r.type_id} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, padding: '2px 0' }}>
                    <input type="checkbox" checked={refine.rig_type_ids.includes(r.type_id)} onChange={() => toggleRig(r.type_id)} />
                    <span style={{ color: 'var(--text-white)' }}>{r.name}</span>
                    <span style={{ color: 'var(--border2)', marginLeft: 'auto' }}>+{r.yield_bonus}%</span>
                  </label>
                ))}
              </div>}
        </Field>
      </div>
    </div>
  )
}

function YieldBadge({ ry }) {
  if (!ry) return null
  return (
    <span style={{ fontSize: 12, color: 'var(--text)' }}>
      Effective yield <b style={{ color: 'var(--accent)' }}>{(ry.effective_yield * 100).toFixed(1)}%</b>
      {' '}— base {(ry.base_yield * 100).toFixed(0)}% × skills {ry.skill_mult}× × implant {ry.implant_mult}×
      {ry.rig_bonus_pct ? ` × rigs +${ry.rig_bonus_pct}%` : ''} × (1 − tax {ry.tax_pct}%)
    </span>
  )
}

function defaultShipping() {
  return { mode: 'regular', isk_per_jump_m3: 1000, isk_per_m3: 5,
           jf_ship: 'Ark', isotopes_per_ly: 305, isotope_price: 800, round_trip: false }
}

function shippingPayload(s) {
  if (s.mode === 'jf') return { mode: 'jf', jf_ship: s.jf_ship, isotopes_per_ly: s.isotopes_per_ly, isotope_price: s.isotope_price, round_trip: s.round_trip }
  if (s.mode === 'flat') return { mode: 'flat', isk_per_m3: s.isk_per_m3 }
  return { mode: 'regular', isk_per_jump_m3: s.isk_per_jump_m3 }
}

function TransportControls({ shipping, setShipping }) {
  const set = (k, v) => setShipping({ ...shipping, [k]: v })
  return (
    <>
      <Field label="Mode">
        <select value={shipping.mode} onChange={e => set('mode', e.target.value)} style={FIT}>
          <option value="regular">Freighter (ISK / jump / m³)</option>
          <option value="flat">Flat (ISK / m³, no jumps)</option>
          <option value="jf">Jump freighter</option>
        </select>
      </Field>
      {shipping.mode === 'regular' && (
        <Field label="ISK per jump per m³"><input type="number" value={shipping.isk_per_jump_m3} onChange={e => set('isk_per_jump_m3', num(e.target.value))} style={FIT} /></Field>
      )}
      {shipping.mode === 'flat' && (
        <Field label="ISK per m³ (flat)" hint="applied directly, no route lookup"><input type="number" value={shipping.isk_per_m3} onChange={e => set('isk_per_m3', num(e.target.value))} style={FIT} /></Field>
      )}
      {shipping.mode === 'jf' && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0,1fr))', gap: '0 10px' }}>
          <Field label="JF ship"><select value={shipping.jf_ship} onChange={e => set('jf_ship', e.target.value)} style={FIT}>{['Ark', 'Rhea', 'Nomad', 'Anshar'].map(s => <option key={s}>{s}</option>)}</select></Field>
          <Field label="Isotopes / ly"><input type="number" value={shipping.isotopes_per_ly} onChange={e => set('isotopes_per_ly', num(e.target.value))} style={FIT} /></Field>
          <Field label="Isotope price"><input type="number" value={shipping.isotope_price} onChange={e => set('isotope_price', num(e.target.value))} style={FIT} /></Field>
          <Field label="Round trip"><input type="checkbox" checked={shipping.round_trip} onChange={e => set('round_trip', e.target.checked)} /></Field>
        </div>
      )}
    </>
  )
}

// Paste-a-list adder shared by every tab. kind: mineral | gas | any.
function PasteAdder({ kind, label, onParsed }) {
  const [text, setText] = useState('')
  const [msg, setMsg] = useState('')
  async function go() {
    if (!text.trim()) return
    try {
      const r = await post('/ore/parse-items', { text, kind })
      onParsed(r.needs)
      const parts = [`✓ ${r.needs.length} ${label}`]
      if (r.skipped.length) parts.push(`skipped ${r.skipped.length}`)
      if (r.unmatched.length) parts.push(`${r.unmatched.length} unmatched`)
      setMsg(parts.join(' · '))
    } catch (e) { setMsg(e.message) }
  }
  return (
    <details style={{ marginBottom: 8 }}>
      <summary style={{ cursor: 'pointer', fontSize: 12, color: 'var(--accent)' }}>Paste a list (auto-extracts {label})</summary>
      <textarea value={text} onChange={e => setText(e.target.value)} rows={4}
                placeholder={'Tritanium\t1000\nPyerite 5000\nMexallon x250…'}
                style={{ width: '100%', boxSizing: 'border-box', marginTop: 6, fontFamily: 'monospace', fontSize: 12 }} />
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 4 }}>
        <button className="btn btn-sm" onClick={go}>Parse</button>
        {msg && <span style={{ fontSize: 11, color: 'var(--text)' }}>{msg}</span>}
      </div>
    </details>
  )
}

// ────────────────────────────────────────────────────────────────────────────
// Tab 1 — Acquisition comparison
// ────────────────────────────────────────────────────────────────────────────

function ComparisonTab({ rigs, hubs, cj }) {
  const [minerals, setMinerals] = useState([])

  const [target, setTarget] = useState('')
  const [sources, setSources] = useState([])          // [{key,label,region_id,system_name,cj}]
  const [needs, setNeeds] = useState({})              // {type_id: {name, qty, on}}
  const [include, setInclude] = useState({ minerals: true, raw: true, compressed: true })
  const [basis, setBasis] = useState('sell')
  const [refine, setRefine] = useState(defaultRefine())
  const [shipping, setShipping] = useState(defaultShipping())
  const [volAlert, setVolAlert] = useState(true)

  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')
  const [res, setRes] = useState(null)

  useEffect(() => {
    get('/ore/catalog').then(r => setMinerals(r.minerals || [])).catch(() => {})
  }, [])

  function toggleNeed(m) {
    const cur = needs[m.type_id]
    setNeeds({ ...needs, [m.type_id]: { name: m.name, qty: cur?.qty || 0, on: !cur?.on } })
  }
  function setNeedQty(tid, qty) {
    setNeeds({ ...needs, [tid]: { ...needs[tid], qty: num(qty) } })
  }
  function mergeParsed(parsed) {
    const merged = { ...needs }
    parsed.forEach(n => { merged[n.type_id] = { name: n.name, qty: n.qty, on: true } })
    setNeeds(merged)
  }
  const toggleInc = (k) => setInclude({ ...include, [k]: !include[k] })

  async function run() {
    const chosenNeeds = Object.entries(needs).filter(([, v]) => v.on)
      .map(([tid, v]) => ({ type_id: Number(tid), qty: v.qty }))
    if (!chosenNeeds.length) { setErr('Select at least one mineral'); return }
    if (!sources.length) { setErr('Select at least one buy location'); return }
    setLoading(true); setErr(''); setRes(null)
    try {
      const body = {
        target_system: target || null,
        needs: chosenNeeds,
        sources,
        include_minerals: include.minerals,
        include_raw: include.raw,
        include_compressed: include.compressed,
        basis,
        refine,
        shipping: shippingPayload(shipping),
        volatility_alert: volAlert,
      }
      setRes(await post('/ore/compare', body))
    } catch (e) { setErr(e.message) } finally { setLoading(false) }
  }

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '360px 1fr', gap: 18, alignItems: 'start' }}>
      {/* ---- controls ---- */}
      <div>
        <Panel title="Where to buy">
          <SourcePicker hubs={hubs} cj={cj} sources={sources} setSources={setSources} />
        </Panel>

        <Panel title="Target system">
          <SystemSearch value={target} onChange={(name) => setTarget(name)} placeholder="Refine / deliver to…" />
          <div style={{ marginTop: 10 }}>
            <span style={{ display: 'block', fontSize: 11, color: 'var(--text)', marginBottom: 4 }}>Analyze (what to consider)</span>
            <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap' }}>
              {[['minerals', 'Buy minerals'], ['raw', 'Raw ore'], ['compressed', 'Compressed ore']].map(([k, lab]) => (
                <label key={k} style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 12, color: 'var(--text-white)' }}>
                  <input type="checkbox" checked={include[k]} onChange={() => toggleInc(k)} /> {lab}
                </label>
              ))}
            </div>
          </div>
          <div style={{ marginTop: 10 }}>
            <Field label="Price basis">
              <select value={basis} onChange={e => setBasis(e.target.value)} style={FIT}>
                <option value="sell">Sell (buy now)</option>
                <option value="buy">Buy (place order)</option>
              </select>
            </Field>
          </div>
        </Panel>

        <Panel title="Resources needed">
          <PasteAdder kind="mineral" label="minerals" onParsed={mergeParsed} />
          <div style={{ maxHeight: 200, overflowY: 'auto' }}>
            {minerals.map(m => (
              <div key={m.type_id} style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: 6, flex: 1, fontSize: 12 }}>
                  <input type="checkbox" checked={!!needs[m.type_id]?.on} onChange={() => toggleNeed(m)} />
                  <span style={{ color: 'var(--text-white)' }}>{m.name}</span>
                </label>
                {needs[m.type_id]?.on && (
                  <input type="number" placeholder="qty" value={needs[m.type_id]?.qty || ''}
                         onChange={e => setNeedQty(m.type_id, e.target.value)} style={{ width: 110 }} />
                )}
              </div>
            ))}
          </div>
        </Panel>

        <Panel title="Refining setup">
          <RefineSetup refine={refine} setRefine={setRefine} rigs={rigs} />
        </Panel>

        <Panel title="Transport">
          <TransportControls shipping={shipping} setShipping={setShipping} />
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, marginTop: 4 }}>
            <input type="checkbox" checked={volAlert} onChange={e => setVolAlert(e.target.checked)} />
            Low-volatility / liquidity alert
          </label>
        </Panel>

        <button className="btn" disabled={loading} onClick={run} style={{ width: '100%' }}>
          {loading ? 'Calculating…' : 'Compare acquisition paths'}
        </button>
        {err && <div style={{ color: '#e05252', fontSize: 12, marginTop: 8 }}>{err}</div>}
      </div>

      {/* ---- results ---- */}
      <div>
        {!res && !loading && <div className="empty-state">Pick locations, minerals and a target, then run the comparison.</div>}
        {res && <Results res={res} />}
      </div>
    </div>
  )
}

function Results({ res }) {
  const rec = res.recommendation || {}
  const alerts = res.alerts || {}
  return (
    <>
      <div className="card" style={{ padding: '14px 16px', marginBottom: 16, borderLeft: '3px solid var(--accent)' }}>
        <div style={{ fontSize: 11, color: 'var(--accent)', fontWeight: 700, letterSpacing: 1 }}>RECOMMENDATION</div>
        <div style={{ fontSize: 15, color: 'var(--text-white)', margin: '4px 0' }}>
          {rec.label || '—'}{rec.total_cost != null && <> · <b>{fmtIsk(rec.total_cost)} ISK</b></>}
        </div>
        <div style={{ fontSize: 12, color: 'var(--text)' }}>{rec.reason}</div>
        <div style={{ marginTop: 8 }}><YieldBadge ry={res.refine_yield} /></div>
        {res.warnings?.length > 0 && (
          <div style={{ marginTop: 8, fontSize: 11, color: '#c8a951' }}>
            {res.warnings.map((w, i) => <div key={i}>⚠ {w}</div>)}
          </div>
        )}
      </div>

      <Panel title="Strategy totals">
        <table>
          <thead><tr><th>Strategy</th><th>Total (delivered)</th><th>Minerals covered</th><th>Missing</th></tr></thead>
          <tbody>
            {res.strategies.map(s => (
              <tr key={s.strategy} style={s.strategy === rec.strategy ? { background: 'var(--surface3)' } : null}>
                <td style={{ color: 'var(--text-white)' }}>{s.label}</td>
                <td>{s.total_cost == null ? '—' : fmtIsk(s.total_cost) + ' ISK'}</td>
                <td>{s.covered}</td>
                <td style={{ fontSize: 11, color: '#c8a951' }}>{s.missing?.join(', ') || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>

      {res.optimal_basket && res.optimal_basket.status !== 'empty' && (
        <Panel title="Optimal basket — min-cost ore mix (joint products, OR-Tools)">
          {res.optimal_basket.total_cost != null && (
            <div style={{ fontSize: 14, color: 'var(--text-white)', marginBottom: 8 }}>
              Cheapest full basket: <b style={{ color: 'var(--accent)' }}>{fmtIsk(res.optimal_basket.total_cost)} ISK</b> delivered
              <span style={{ fontSize: 11, color: 'var(--text)' }}> · {res.optimal_basket.status}</span>
            </div>
          )}
          {res.optimal_basket.uncoverable?.length > 0 && (
            <div style={{ fontSize: 11, color: '#c8a951', marginBottom: 6 }}>⚠ no source for: {res.optimal_basket.uncoverable.join(', ')}</div>
          )}
          <table>
            <thead><tr><th>Buy</th><th>Type</th><th>Source</th><th>Units</th><th>Unit</th><th>Total</th></tr></thead>
            <tbody>
              {res.optimal_basket.buys.map((b, i) => (
                <tr key={i}>
                  <td style={{ color: 'var(--text-white)' }}>{b.name}</td>
                  <td style={{ fontSize: 11, color: 'var(--text)' }}>{b.kind}</td>
                  <td>{b.source}</td>
                  <td>{fmtNum(b.units)}</td>
                  <td>{isk(b.unit_cost)}</td>
                  <td>{fmtIsk(b.total_cost)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {res.optimal_basket.coverage?.length > 0 && (
            <table style={{ marginTop: 8 }}>
              <thead><tr><th>Mineral</th><th>Needed</th><th>Produced</th><th>Surplus</th></tr></thead>
              <tbody>
                {res.optimal_basket.coverage.map(c => (
                  <tr key={c.type_id}>
                    <td style={{ color: 'var(--text-white)' }}>{c.name}</td>
                    <td>{fmtNum(c.needed)}</td>
                    <td>{fmtNum(c.produced)}</td>
                    <td style={{ color: c.surplus > 0 ? '#c8a951' : 'var(--text)' }}>{c.surplus > 0 ? '+' : ''}{fmtNum(c.surplus)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>
      )}

      <Panel title="Per-mineral best path">
        <table>
          <thead><tr><th>Mineral</th><th>Qty</th><th>Buy direct</th><th>Via ore (refine)</th><th>Recommended</th></tr></thead>
          <tbody>
            {res.minerals.map(m => {
              const a = alerts[m.type_id]
              return (
                <tr key={m.type_id}>
                  <td style={{ color: 'var(--text-white)' }}>
                    {m.name}
                    {a?.alert && <span title={a.reason} style={{ marginLeft: 6, color: '#c8a951', fontSize: 11 }}>⚠ low&nbsp;vol</span>}
                  </td>
                  <td>{m.qty ? fmtNum(m.qty) : '—'}</td>
                  <td>{m.direct_best ? `${isk(m.direct_best.effective_cost, 4)} @ ${m.direct_best.source}` : '—'}</td>
                  <td>{m.ore_best ? `${isk(m.ore_best.effective_cost, 4)} · ${m.ore_best.via_name}` : '—'}</td>
                  <td style={{ color: 'var(--accent)', fontWeight: 600 }}>
                    {m.recommended ? `${m.recommended.kind === 'ore' ? '⛏ ' : '💰 '}${isk(m.recommended.effective_cost, 4)}` : '—'}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </Panel>

      <Panel title={`Price table · basis ${res.basis}`}>
        <div style={{ overflowX: 'auto' }}>
          <table>
            <thead>
              <tr>
                <th>Item</th><th>Type</th>
                {res.sources.map(s => <th key={s.key}>{s.label}<div style={{ fontSize: 10, color: 'var(--border2)' }}>+{isk(s.cost_per_m3, 2)}/m³</div></th>)}
              </tr>
            </thead>
            <tbody>
              {res.items.map(it => (
                <tr key={it.type_id}>
                  <td style={{ color: 'var(--text-white)' }}>{it.name}</td>
                  <td style={{ fontSize: 11, color: 'var(--text)' }}>{it.kind === 'ore' ? (it.compressed ? 'compressed' : 'raw ore') : 'mineral'}</td>
                  {it.cells.map((c, i) => {
                    const best = it.best && c.delivered != null && c.delivered === it.best.delivered
                    return (
                      <td key={i} style={{ color: best ? 'var(--accent)' : 'var(--text)', fontWeight: best ? 600 : 400, whiteSpace: 'nowrap' }}
                          title={c.flag ? c.flag.reason : (c.price != null ? `price ${isk(c.price)}` : 'no price')}>
                        {c.delivered == null ? '—' : isk(c.delivered, 2)}
                        {c.flag && <span style={{ color: '#c8a951' }}> ⚑</span>}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      {res.ore_evals?.length > 0 && (
        <Panel title="Refine worthiness (per ore × source)">
          <div style={{ overflowX: 'auto', maxHeight: 360 }}>
            <table>
              <thead><tr><th>Ore</th><th>Source</th><th>Cost/unit</th><th>Refined value/unit</th><th>Margin</th></tr></thead>
              <tbody>
                {res.ore_evals.filter(e => e.cost_per_unit != null)
                  .sort((a, b) => (b.ratio || 0) - (a.ratio || 0))
                  .map((e, i) => (
                    <tr key={i}>
                      <td style={{ color: 'var(--text-white)' }}>{e.name}{e.compressed && <span style={{ color: 'var(--border2)', fontSize: 10 }}> (c)</span>}</td>
                      <td>{e.source}</td>
                      <td>{isk(e.cost_per_unit)}</td>
                      <td>{isk(e.refined_value_per_unit)}</td>
                      <td style={{ color: e.profitable ? '#4caf50' : '#e05252', fontWeight: 600 }}>
                        {e.margin_pct == null ? '—' : `${e.margin_pct > 0 ? '+' : ''}${e.margin_pct}%`}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}
    </>
  )
}

// ────────────────────────────────────────────────────────────────────────────
// Tab 2 — Gas: compressed vs regular
// ────────────────────────────────────────────────────────────────────────────

function GasTab({ hubs, cj }) {
  const [gases, setGases] = useState([])
  const [sources, setSources] = useState([])
  const [target, setTarget] = useState('')
  const [needs, setNeeds] = useState({})              // {reg_type_id: {name, qty, on}}
  const [basis, setBasis] = useState('sell')
  const [loss, setLoss] = useState(5)                 // decompression loss %
  const [shipping, setShipping] = useState(defaultShipping())
  const [volAlert, setVolAlert] = useState(true)
  const [res, setRes] = useState(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')

  useEffect(() => { get('/ore/gas/catalog').then(r => setGases(r.gases || [])).catch(() => {}) }, [])

  function toggleNeed(g) {
    const cur = needs[g.reg_type_id]
    setNeeds({ ...needs, [g.reg_type_id]: { name: g.reg_name, qty: cur?.qty || 0, on: !cur?.on } })
  }
  const setQty = (tid, q) => setNeeds({ ...needs, [tid]: { ...needs[tid], qty: num(q) } })
  function mergeParsed(parsed) {
    const merged = { ...needs }
    parsed.forEach(n => { merged[n.type_id] = { name: n.name, qty: n.qty, on: true } })
    setNeeds(merged)
  }

  async function run() {
    const chosen = Object.entries(needs).filter(([, v]) => v.on).map(([tid, v]) => ({ type_id: Number(tid), qty: v.qty }))
    if (!chosen.length) { setErr('Select at least one gas'); return }
    if (!sources.length) { setErr('Select at least one buy location'); return }
    setLoading(true); setErr(''); setRes(null)
    try {
      setRes(await post('/ore/gas-compare', {
        target_system: target || null, needs: chosen, sources, basis,
        decompression_loss_pct: loss,
        shipping: shippingPayload(shipping),
        volatility_alert: volAlert,
      }))
    } catch (e) { setErr(e.message) } finally { setLoading(false) }
  }

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '360px 1fr', gap: 18, alignItems: 'start' }}>
      <div>
        <Panel title="Where to buy"><SourcePicker hubs={hubs} cj={cj} sources={sources} setSources={setSources} /></Panel>

        <Panel title="Target system">
          <SystemSearch value={target} onChange={(name) => setTarget(name)} placeholder="Deliver to…" />
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0,1fr))', gap: '0 10px', marginTop: 8 }}>
            <Field label="Price basis">
              <select value={basis} onChange={e => setBasis(e.target.value)} style={FIT}>
                <option value="sell">Sell (buy now)</option><option value="buy">Buy (place order)</option>
              </select>
            </Field>
            <Field label="Decompression loss %" hint="~5% typical — editable">
              <input type="number" step="0.5" value={loss} onChange={e => setLoss(num(e.target.value))} style={FIT} />
            </Field>
          </div>
        </Panel>

        <Panel title="Gases needed">
          <PasteAdder kind="gas" label="gases" onParsed={mergeParsed} />
          <div style={{ maxHeight: 240, overflowY: 'auto' }}>
            {gases.map(g => (
              <div key={g.reg_type_id} style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: 6, flex: 1, fontSize: 12 }}>
                  <input type="checkbox" checked={!!needs[g.reg_type_id]?.on} onChange={() => toggleNeed(g)} />
                  <span style={{ color: 'var(--text-white)' }}>{g.reg_name}</span>
                  {!g.comp_type_id && <span title="no compressed variant" style={{ color: 'var(--border2)', fontSize: 10 }}>(no comp.)</span>}
                </label>
                {needs[g.reg_type_id]?.on && (
                  <input type="number" placeholder="qty" value={needs[g.reg_type_id]?.qty || ''}
                         onChange={e => setQty(g.reg_type_id, e.target.value)} style={{ width: 110 }} />
                )}
              </div>
            ))}
            {gases.length === 0 && <div style={{ fontSize: 11, color: 'var(--border2)' }}>No gases in SDE — run an EVE sync.</div>}
          </div>
        </Panel>

        <Panel title="Transport">
          <TransportControls shipping={shipping} setShipping={setShipping} />
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, marginTop: 4 }}>
            <input type="checkbox" checked={volAlert} onChange={e => setVolAlert(e.target.checked)} /> Low-volatility / liquidity alert
          </label>
        </Panel>

        <button className="btn" disabled={loading} onClick={run} style={{ width: '100%' }}>
          {loading ? 'Calculating…' : 'Compare gas forms'}
        </button>
        {err && <div style={{ color: '#e05252', fontSize: 12, marginTop: 8 }}>{err}</div>}
      </div>

      <div>
        {!res && !loading && <div className="empty-state">Pick locations, gases and a target, then compare compressed vs regular.</div>}
        {res && <GasResults res={res} />}
      </div>
    </div>
  )
}

function GasResults({ res }) {
  const rec = res.recommendation || {}
  const alerts = res.alerts || {}
  return (
    <>
      <div className="card" style={{ padding: '14px 16px', marginBottom: 16, borderLeft: '3px solid var(--accent)' }}>
        <div style={{ fontSize: 11, color: 'var(--accent)', fontWeight: 700, letterSpacing: 1 }}>RECOMMENDATION</div>
        <div style={{ fontSize: 15, color: 'var(--text-white)', margin: '4px 0' }}>
          {rec.label || '—'}{rec.total_cost != null && <> · <b>{fmtIsk(rec.total_cost)} ISK</b></>}
        </div>
        <div style={{ fontSize: 12, color: 'var(--text)' }}>{rec.reason}</div>
        <div style={{ fontSize: 11, color: 'var(--text)', marginTop: 6 }}>Decompression loss applied: {(res.decompression_loss * 100).toFixed(1)}%</div>
        {res.warnings?.length > 0 && <div style={{ marginTop: 8, fontSize: 11, color: '#c8a951' }}>{res.warnings.map((w, i) => <div key={i}>⚠ {w}</div>)}</div>}
      </div>

      <Panel title="Strategy totals">
        <table>
          <thead><tr><th>Strategy</th><th>Total (delivered)</th><th>Gases covered</th><th>Missing</th></tr></thead>
          <tbody>
            {res.strategies.map(s => (
              <tr key={s.strategy} style={s.strategy === rec.strategy ? { background: 'var(--surface3)' } : null}>
                <td style={{ color: 'var(--text-white)' }}>{s.label}</td>
                <td>{s.total_cost == null ? '—' : fmtIsk(s.total_cost) + ' ISK'}</td>
                <td>{s.covered}</td>
                <td style={{ fontSize: 11, color: '#c8a951' }}>{s.missing?.join(', ') || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>

      <Panel title="Per-gas: compressed vs regular (effective ISK / usable unit)">
        <div style={{ overflowX: 'auto' }}>
          <table>
            <thead><tr><th>Gas</th><th>Qty</th><th>Regular</th><th>Compressed</th><th>Per compressed</th><th>Recommended</th></tr></thead>
            <tbody>
              {res.gases.map(g => {
                const a = alerts[g.reg_type_id]
                return (
                  <tr key={g.reg_type_id}>
                    <td style={{ color: 'var(--text-white)' }}>
                      {g.name}
                      {a?.alert && <span title={a.reason} style={{ marginLeft: 6, color: '#c8a951', fontSize: 11 }}>⚠ low&nbsp;vol</span>}
                    </td>
                    <td>{g.qty ? fmtNum(g.qty) : '—'}</td>
                    <td>{g.reg_best ? `${isk(g.reg_best.effective_cost, 4)} @ ${g.reg_best.source}` : '—'}</td>
                    <td>{g.comp_best ? `${isk(g.comp_best.effective_cost, 4)} @ ${g.comp_best.source}` : '—'}</td>
                    <td style={{ fontSize: 11, color: 'var(--text)' }}>{g.units_per_compressed ? fmtNum(g.units_per_compressed) : '—'}</td>
                    <td style={{ color: 'var(--accent)', fontWeight: 600 }}>
                      {g.recommended ? `${g.recommended.kind === 'compressed' ? '🗜 ' : '⛽ '}${g.recommended.kind}` : '—'}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </Panel>
    </>
  )
}

// ────────────────────────────────────────────────────────────────────────────
// Tab 3 — Standalone reprocessing calculator
// ────────────────────────────────────────────────────────────────────────────

function ReprocessTab({ rigs }) {
  const [items, setItems] = useState([])          // [{type_id, name, qty}]
  const [pending, setPending] = useState(null)
  const [refine, setRefine] = useState(defaultRefine())
  const [system, setSystem] = useState('')
  const [valueRegion, setValueRegion] = useState('forge')
  const [basis, setBasis] = useState('sell')
  const [res, setRes] = useState(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')

  const VALUE_REGIONS = { forge: 10000002, domain: 10000043, sinq: 10000032 }

  function addItem() {
    if (!pending?.type_id) return
    setItems([...items, { type_id: pending.type_id, name: pending.name, qty: 1000 }])
    setPending(null)
  }
  const setQty = (i, q) => setItems(items.map((it, j) => j === i ? { ...it, qty: num(q) } : it))
  const removeItem = (i) => setItems(items.filter((_, j) => j !== i))
  function addParsed(parsed) {
    const byId = new Map(items.map(it => [it.type_id, { ...it }]))
    parsed.forEach(n => {
      const ex = byId.get(n.type_id)
      if (ex) ex.qty += n.qty || 0
      else byId.set(n.type_id, { type_id: n.type_id, name: n.name, qty: n.qty || 1000 })
    })
    setItems([...byId.values()])
  }

  async function run() {
    if (!items.length) { setErr('Add at least one item'); return }
    setLoading(true); setErr(''); setRes(null)
    try {
      const value_cj = valueRegion === 'cj'
      const region_id = (value_cj || valueRegion === 'none') ? null : VALUE_REGIONS[valueRegion]
      setRes(await post('/ore/reprocess', {
        items: items.map(it => ({ type_id: it.type_id, qty: it.qty })),
        refine, system_name: system || null,
        region_id, value_cj, basis,
      }))
    } catch (e) { setErr(e.message) } finally { setLoading(false) }
  }

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '360px 1fr', gap: 18, alignItems: 'start' }}>
      <div>
        <Panel title="Items to reprocess">
          <PasteAdder kind="any" label="items" onParsed={addParsed} />
          <div style={{ display: 'flex', gap: 6, alignItems: 'flex-start' }}>
            <div style={{ flex: 1 }}><TypeSearch value={pending} onChange={t => setPending(t?.type_id ? t : null)} placeholder="Add ore / item…" /></div>
            <button className="btn btn-sm" onClick={addItem}>Add</button>
          </div>
          <table style={{ marginTop: 8 }}>
            <tbody>
              {items.map((it, i) => (
                <tr key={i}>
                  <td style={{ color: 'var(--text-white)' }}>{it.name}</td>
                  <td><input type="number" value={it.qty} onChange={e => setQty(i, e.target.value)} style={{ width: 110 }} /></td>
                  <td><button className="btn btn-ghost btn-sm" onClick={() => removeItem(i)}>✕</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>

        <Panel title="Refining setup">
          <RefineSetup refine={refine} setRefine={setRefine} rigs={rigs} />
          <Field label="Facility system (sets rig security band)">
            <SystemSearch value={system} onChange={(name) => setSystem(name)} placeholder="e.g. C-J6MT-A…" />
          </Field>
        </Panel>

        <Panel title="Value minerals at">
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0,1fr))', gap: '0 10px' }}>
            <Field label="Market">
              <select value={valueRegion} onChange={e => setValueRegion(e.target.value)} style={FIT}>
                <option value="forge">The Forge (Jita)</option>
                <option value="domain">Domain (Amarr)</option>
                <option value="sinq">Sinq Laison (Dodixie)</option>
                <option value="cj">C-J6MT (local scrape)</option>
                <option value="none">— none —</option>
              </select>
            </Field>
            <Field label="Basis">
              <select value={basis} onChange={e => setBasis(e.target.value)} style={FIT}>
                <option value="sell">Sell</option><option value="buy">Buy</option><option value="split">Split (mid)</option>
              </select>
            </Field>
          </div>
        </Panel>

        <button className="btn" disabled={loading} onClick={run} style={{ width: '100%' }}>
          {loading ? 'Calculating…' : 'Reprocess'}
        </button>
        {err && <div style={{ color: '#e05252', fontSize: 12, marginTop: 8 }}>{err}</div>}
      </div>

      <div>
        {!res && !loading && <div className="empty-state">Add ore or items, set your skills/structure, then reprocess.</div>}
        {res && (
          <>
            {res.warnings?.length > 0 && (
              <div className="card" style={{ padding: '10px 14px', marginBottom: 16, fontSize: 12, color: '#c8a951' }}>
                {res.warnings.map((w, i) => <div key={i}>⚠ {w}</div>)}
              </div>
            )}
            <Panel title="Effective yield" right={res.total_value != null ? <b style={{ color: 'var(--accent)' }}>{fmtIsk(res.total_value)} ISK</b> : null}>
              <YieldBadge ry={res.refine_yield} />
              <div style={{ fontSize: 11, color: 'var(--text)', marginTop: 4 }}>Security band: {res.security_band}</div>
            </Panel>
            <Panel title="Minerals produced">
              <table>
                <thead><tr><th>Mineral</th><th>Qty</th><th>Unit</th><th>Value</th></tr></thead>
                <tbody>
                  {res.minerals.map(m => (
                    <tr key={m.type_id}>
                      <td style={{ color: 'var(--text-white)' }}>{m.name}</td>
                      <td>{fmtNum(m.qty)}</td>
                      <td>{m.unit_price != null ? isk(m.unit_price) : '—'}</td>
                      <td>{m.value != null ? fmtIsk(m.value) : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Panel>
            <Panel title="Per-item breakdown">
              <table>
                <thead><tr><th>Item</th><th>Batches</th><th>Refined</th><th>Leftover</th></tr></thead>
                <tbody>
                  {res.items.map((it, i) => (
                    <tr key={i}>
                      <td style={{ color: 'var(--text-white)' }}>{(items.find(x => x.type_id === it.input_type_id) || {}).name || it.input_type_id}</td>
                      <td>{fmtNum(it.batches)}</td>
                      <td>{fmtNum(it.refined_units)}</td>
                      <td>{fmtNum(it.leftover)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Panel>
          </>
        )}
      </div>
    </div>
  )
}
