import { useState, useEffect } from 'react'
import { get, post, downloadPost } from '../api/client'
import { fmtIsk, fmtNum } from './personal/common'

// method key → short label for the picker (full label comes back from the API)
const METHODS = [
  { key: 'sell_buy',  label: 'Sell→Buy', hint: 'Jita sell orders → C-J buy orders (fastest)' },
  { key: 'sell_sell', label: 'Sell→Sell', hint: 'Jita sell orders → sell order @ C-J' },
  { key: 'buy_buy',   label: 'Buy→Buy', hint: 'Buy order @ Jita → C-J buy orders' },
  { key: 'buy_sell',  label: 'Buy→Sell', hint: 'Buy order @ Jita → sell order @ C-J (best margin, slowest)' },
]
const methodLabel = key => METHODS.find(m => m.key === key)?.label || key || '—'

const CATEGORIES = [
  { id: '', label: 'All' }, { id: 6, label: 'Ships' }, { id: 7, label: 'Modules' },
  { id: 8, label: 'Charges' }, { id: 18, label: 'Drones' }, { id: 'drugs', label: 'Drugs' },
]

// tech-level meta groups (EVE invMetaTypes); NULL meta_group_id ⇒ Tech I.
const META_FLAGS = [
  { key: 't1', label: 'T1', meta: 1 },
  { key: 't2', label: 'T2', meta: 2 },
  { key: 'faction', label: 'Faction', meta: 4 },
]
// portfolio risk aversion λ presets (max wᵀμ − (λ/2)·wᵀΣw)
const RISK_LEVELS = [
  { key: 'low', label: 'Low', lambda: 2, hint: 'Return-hungry — concentrate on top ROI' },
  { key: 'med', label: 'Medium', lambda: 8, hint: 'Balanced (default)' },
  { key: 'high', label: 'High', lambda: 20, hint: 'Risk-averse — spread to low-volatility items' },
]
const DEFAULT_COURIER = 1200

// Recompute a scanner row's profit/ROI for a new courier rate, purely from the
// stored fields (capital incl. shipping = profit/roi; strip scan-rate shipping, add new).
function recomputed(i, rate) {
  const roi = Number(i.roi) || 0
  const profit = Number(i.profit_per_unit) || 0
  const transport = Number(i.transport_per_unit) || 0
  const vol = Number(i.volume_each) || 0
  if (roi <= 0) return { profit_disp: profit, roi_disp: roi }
  const gross = profit + transport                       // profit before shipping
  const capital = profit / roi                           // capital incl. scan-rate shipping
  const newTransport = vol * (Number(rate) || 0)
  const newProfit = gross - newTransport
  const newCapital = capital - transport + newTransport  // acquire cost + new shipping
  return { profit_disp: newProfit, roi_disp: newCapital > 0 ? newProfit / newCapital : 0 }
}

export default function HaulEvaluatorPage() {
  const [mode, setMode] = useState('manual')
  return (
    <div>
      <div className="tabs" style={{ marginBottom: 16 }}>
        <button className={`tab-btn ${mode === 'manual' ? 'active' : ''}`} onClick={() => setMode('manual')}>Manual list</button>
        <button className={`tab-btn ${mode === 'scanner' ? 'active' : ''}`} onClick={() => setMode('scanner')}>Auto scanner</button>
      </div>
      {mode === 'manual' ? <ManualHaul /> : <HaulScanner />}
    </div>
  )
}

// ── Auto scanner: precomputed, auto-discovered profitable hauls ────────────────

function catDisplay(i) {
  const l = CATEGORIES.find(c => c.id === i.category_id)?.label
  if (l) return l
  return i.group_id ? 'Drugs' : ''     // boosters enter by group (category 20), not the category list
}

function HaulScanner() {
  const [minMargin, setMinMargin] = useState(0)
  const [cat, setCat] = useState('')
  const [rankBy, setRankBy] = useState('profit')
  const [courier, setCourier] = useState(DEFAULT_COURIER)
  const [meta, setMeta] = useState({ t1: false, t2: true, faction: true })
  const [selected, setSelected] = useState(() => new Set())
  const [res, setRes] = useState(null)
  const [err, setErr] = useState('')
  const [loading, setLoading] = useState(false)

  async function load(catArg = cat, metaArg = meta) {
    setLoading(true); setErr('')
    try {
      const q = new URLSearchParams({ rank_by: rankBy, min_margin: '0', limit: '200' })
      if (catArg === 'drugs') q.set('group', 'drugs')
      else if (catArg !== '') q.set('category_id', String(catArg))
      const metaCsv = META_FLAGS.filter(f => metaArg[f.key]).map(f => f.meta).join(',')
      if (metaCsv) q.set('meta', metaCsv)
      setRes(await get(`/trade/haul/scan?${q.toString()}`))
    } catch (e) { setErr(e.message); setRes(null) }
    finally { setLoading(false) }
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps, react-hooks/set-state-in-effect
  useEffect(() => { load() }, [])  // auto-load on mount

  function setCategory(v) { const nv = v === '' ? '' : (v === 'drugs' ? 'drugs' : Number(v)); setCat(nv); load(nv, meta) }
  function toggleMeta(k) { const nm = { ...meta, [k]: !meta[k] }; setMeta(nm); load(cat, nm) }

  // Min ROI + courier + rank are applied client-side (instant, no refetch).
  const rate = Number(courier) || 0
  const items = (res?.items || [])
    .map(i => ({ ...i, ...recomputed(i, rate) }))
    .filter(i => i.roi_disp * 100 >= (Number(minMargin) || 0))
    .sort((a, b) => rankBy === 'roi' ? b.roi_disp - a.roi_disp : b.profit_disp - a.profit_disp)

  const visibleIds = items.map(i => i.type_id)
  const allSelected = visibleIds.length > 0 && visibleIds.every(id => selected.has(id))
  function toggle(id) { setSelected(s => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n }) }
  function toggleAll() {
    setSelected(s => {
      if (allSelected) { const n = new Set(s); visibleIds.forEach(id => n.delete(id)); return n }
      return new Set([...s, ...visibleIds])
    })
  }
  // selection restricted to the currently-loaded universe — changing category/meta
  // (which reloads the scan) auto-drops items no longer present, without mutating state.
  const universeIds = new Set((res?.items || []).map(i => i.type_id))
  const selectedIds = [...selected].filter(id => universeIds.has(id))

  return (
    <div>
      <p style={{ color: 'var(--text)', fontSize: 13, marginBottom: 14, maxWidth: 820 }}>
        Auto-discovered profitable hauls — the most liquid Jita items (≥100 traded/day; ships, modules,
        charges, drones, drugs) priced against C-J6MT and refreshed in the background. Tick items and
        build an optimized buy portfolio for a target budget below; adjust the courier rate to re-price
        instantly.
      </p>

      <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end', flexWrap: 'wrap', marginBottom: 12 }}>
        <Field label="Min ROI %"><input type="number" min="0" step="1" value={minMargin} onChange={e => setMinMargin(e.target.value)} style={{ width: 80 }} /></Field>
        <Field label="Category">
          <select value={cat} onChange={e => setCategory(e.target.value)}>
            {CATEGORIES.map(c => <option key={c.label} value={c.id}>{c.label}</option>)}
          </select>
        </Field>
        <Field label="Tech level">
          <div style={{ display: 'flex', gap: 6 }}>
            {META_FLAGS.map(f => (
              <button key={f.key} onClick={() => toggleMeta(f.key)}
                      className={`tab-btn ${meta[f.key] ? 'active' : ''}`}
                      style={{ fontSize: 12, padding: '4px 10px' }}>{f.label}</button>
            ))}
          </div>
        </Field>
        <Field label="Courier ISK/m³"><input type="number" min="0" value={courier} onChange={e => setCourier(e.target.value)} style={{ width: 100 }} /></Field>
        <Field label="Rank by">
          <select value={rankBy} onChange={e => setRankBy(e.target.value)}>
            <option value="profit">Profit / unit</option>
            <option value="roi">ROI</option>
          </select>
        </Field>
        <button className="btn btn-primary" disabled={loading} onClick={() => load()}>{loading ? 'Loading…' : 'Refresh'}</button>
      </div>

      {err && <div className="error-box">{err}</div>}

      {res && (
        <>
          {res.stale && <div className="warning-box" style={{ marginBottom: 10 }}>Data is stale — the scanner hasn’t refreshed recently.</div>}
          <div style={{ fontSize: 12, color: 'var(--text)', marginBottom: 8 }}>
            {items.length} candidate{items.length === 1 ? '' : 's'}{selectedIds.length > 0 ? ` · ${selectedIds.length} selected` : ''} · {res.updated_at ? `updated ${new Date(res.updated_at).toLocaleString()}` : 'never run yet'}
          </div>
          {items.length === 0
            ? <div className="empty-state">No profitable hauls match the filters (or the scanner hasn’t run — needs Jita history data first).</div>
            : (
              <div className="card" style={{ padding: 0, overflowX: 'auto' }}>
                <table>
                  <thead>
                    <tr>
                      <th style={{ width: 28 }}><input type="checkbox" checked={allSelected} onChange={toggleAll} title="Select all shown" /></th>
                      <th>Item</th><th>Cat</th>
                      <th style={{ textAlign: 'right' }}>Jita sell</th>
                      <th style={{ textAlign: 'right' }}>Jita buy</th>
                      <th style={{ textAlign: 'right' }}>C-J buy</th>
                      <th style={{ textAlign: 'right' }}>C-J sell</th>
                      <th style={{ textAlign: 'right' }}>Vol/day</th>
                      <th>Method</th>
                      <th style={{ textAlign: 'right' }}>Profit/unit</th>
                      <th style={{ textAlign: 'right' }}>ROI</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map(i => (
                      <tr key={i.type_id} style={selected.has(i.type_id) ? { background: 'var(--row-active, rgba(80,140,255,0.10))' } : undefined}>
                        <td style={{ textAlign: 'center' }}><input type="checkbox" checked={selected.has(i.type_id)} onChange={() => toggle(i.type_id)} /></td>
                        <td style={{ color: 'var(--text-white)', whiteSpace: 'nowrap' }}>{i.name}</td>
                        <td style={{ fontSize: 11, color: 'var(--text)' }}>{catDisplay(i)}</td>
                        <td style={{ textAlign: 'right', color: 'var(--text)' }}>{i.jita_sell != null ? fmtIsk(i.jita_sell) : '—'}</td>
                        <td style={{ textAlign: 'right', color: 'var(--text)' }}>{i.jita_buy != null ? fmtIsk(i.jita_buy) : '—'}</td>
                        <td style={{ textAlign: 'right', color: 'var(--text)' }}>{i.cj_buy != null ? fmtIsk(i.cj_buy) : '—'}</td>
                        <td style={{ textAlign: 'right', color: 'var(--text)' }}>{i.cj_sell != null ? fmtIsk(i.cj_sell) : '—'}</td>
                        <td style={{ textAlign: 'right', color: 'var(--text)' }}>{fmtNum(i.daily_volume)}</td>
                        <td style={{ whiteSpace: 'nowrap', fontSize: 12 }}>{methodLabel(i.best_method)}</td>
                        <td style={{ textAlign: 'right', color: i.profit_disp > 0 ? 'var(--success)' : 'var(--danger)' }}>{fmtIsk(i.profit_disp)}</td>
                        <td style={{ textAlign: 'right', color: i.roi_disp > 0 ? 'var(--success)' : 'var(--danger)' }}>{(i.roi_disp * 100).toFixed(1)}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

          <PortfolioPanel selectedIds={selectedIds} courier={rate} onClear={() => setSelected(new Set())} />
        </>
      )}
    </div>
  )
}

// ── Portfolio: Markowitz allocation of a budget across the ticked items ────────

function PortfolioPanel({ selectedIds, courier, onClear }) {
  const [budget, setBudget] = useState('')
  const [charId, setCharId] = useState('')
  const [risk, setRisk] = useState('med')
  const [sellDays, setSellDays] = useState(7)
  const [maxPct, setMaxPct] = useState(25)
  const [characters, setCharacters] = useState([])
  const [res, setRes] = useState(null)
  const [err, setErr] = useState('')
  const [loading, setLoading] = useState(false)
  const [pdfLoading, setPdfLoading] = useState(false)
  const [copied, setCopied] = useState(false)

  useEffect(() => { get('/characters').then(setCharacters).catch(() => {}) }, [])
  // a result belongs to the exact selection it was computed for; tagging it with that
  // key lets it auto-hide when the selection changes (no effect / setState needed).
  const selKey = selectedIds.join(',')

  function reqBody() {
    return {
      type_ids: selectedIds,
      budget: Number(budget) || 0,
      character_id: charId ? Number(charId) : null,
      courier_per_m3: Number(courier) || 0,
      risk_aversion: RISK_LEVELS.find(r => r.key === risk)?.lambda ?? 8,
      horizon_days: Number(sellDays) || 7,
      max_weight: Math.min(Math.max((Number(maxPct) || 25) / 100, 0.01), 1),
    }
  }

  async function optimize() {
    if (!selectedIds.length) { setErr('Tick at least one item above.'); return }
    if (!(Number(budget) > 0)) { setErr('Enter a budget.'); return }
    setLoading(true); setErr('')
    try { setRes({ key: selKey, data: await post('/trade/haul/portfolio', reqBody()) }) }
    catch (e) { setErr(e.message); setRes(null) }
    finally { setLoading(false) }
  }

  async function downloadPdf() {
    setPdfLoading(true); setErr('')
    try { await downloadPost('/trade/haul/portfolio/pdf', { ...reqBody(), share_base: window.location.origin }, 'haul-portfolio.pdf') }
    catch (e) { setErr(e.message) }
    finally { setPdfLoading(false) }
  }

  function copyBuyList(rows) {
    const text = rows.map(a => `${a.name}\t${a.qty}`).join('\n')
    navigator.clipboard?.writeText(text).then(() => {
      setCopied(true); setTimeout(() => setCopied(false), 1800)
    }).catch(() => setErr('Clipboard not available'))
  }

  if (!selectedIds.length) return null
  const live = (res && res.key === selKey) ? res.data : null   // hide a result from a stale selection
  const t = live?.result?.totals
  const allocs = (live?.result?.allocations || []).filter(a => a.qty > 0)

  return (
    <div className="card" style={{ marginTop: 18 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
        <h3 style={{ margin: 0, fontSize: 15 }}>Portfolio optimizer · {selectedIds.length} item{selectedIds.length === 1 ? '' : 's'}</h3>
        <button className="tab-btn" style={{ fontSize: 12 }} onClick={onClear}>Clear selection</button>
      </div>
      <p style={{ color: 'var(--text)', fontSize: 12, marginTop: 0, marginBottom: 12, maxWidth: 860 }}>
        Markowitz allocation that you can actually sell: spend the budget to maximize risk-adjusted
        profit, but cap each item by how much you can realistically offload (a slice of daily volume
        over your sell-through window) and by a max budget share. Prices use the trading character’s
        sales tax + broker fee and the courier rate set above ({fmtIsk(courier)}/m³).
      </p>

      <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end', flexWrap: 'wrap', marginBottom: 12 }}>
        <Field label="Budget (ISK)"><input type="number" min="0" value={budget} onChange={e => setBudget(e.target.value)} style={{ width: 160 }} placeholder="e.g. 2000000000" /></Field>
        <Field label="Trading character">
          <select value={charId} onChange={e => setCharId(e.target.value)}>
            <option value="">Default fees</option>
            {characters.map(c => <option key={c.id} value={c.id}>{c.character_name}</option>)}
          </select>
        </Field>
        <Field label="Risk">
          <div style={{ display: 'flex', gap: 6 }}>
            {RISK_LEVELS.map(r => (
              <button key={r.key} title={r.hint} onClick={() => setRisk(r.key)}
                      className={`tab-btn ${risk === r.key ? 'active' : ''}`}
                      style={{ fontSize: 12, padding: '4px 10px' }}>{r.label}</button>
            ))}
          </div>
        </Field>
        <Field label="Sell-through days"><input type="number" min="1" value={sellDays} onChange={e => setSellDays(e.target.value)} style={{ width: 90 }} title="How many days you expect to take selling a position — caps each item's quantity" /></Field>
        <Field label="Max / item %"><input type="number" min="1" max="100" value={maxPct} onChange={e => setMaxPct(e.target.value)} style={{ width: 80 }} title="Largest share of the budget any single item may take" /></Field>
        <button className="btn btn-primary" disabled={loading} onClick={optimize}>{loading ? 'Optimizing…' : 'Optimize'}</button>
        {allocs.length > 0 && <button className="btn" onClick={() => copyBuyList(allocs)}>{copied ? 'Copied!' : 'Copy buy list'}</button>}
        {live && <button className="btn" disabled={pdfLoading} onClick={downloadPdf}>{pdfLoading ? 'Building…' : 'Download PDF'}</button>}
      </div>

      {err && <div className="error-box" style={{ marginBottom: 12 }}>{err}</div>}
      {live?.unmatched?.length > 0 && (
        <div className="warning-box" style={{ marginBottom: 12 }}>{live.unmatched.length} selected item(s) had no fresh scan price and were skipped.</div>
      )}

      {t && (
        <>
          <div style={{ display: 'flex', gap: 26, flexWrap: 'wrap', marginBottom: 14 }}>
            <Stat label="Capital deployed" value={fmtIsk(t.capital_used)} />
            <Stat label="Leftover" value={fmtIsk(t.leftover)} />
            <Stat label="Expected profit" value={fmtIsk(t.expected_profit)} good={t.expected_profit > 0} />
            <Stat label="Expected ROI" value={`${(t.portfolio_roi * 100).toFixed(1)}%`} good={t.portfolio_roi > 0} />
            <Stat label="Portfolio σ" value={`${(t.stddev * 100).toFixed(1)}%`} />
            <Stat label="Cargo" value={`${fmtNum(t.total_volume_m3)} m³`} />
            <Stat label="Items bought" value={`${t.n_assets} / ${t.n_considered}`} good={t.n_assets > 0} />
          </div>

          {live.result?.frontier && (
            <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', marginBottom: 14 }}>
              <div className="card" style={{ flex: '1 1 380px', minWidth: 300 }}>
                <div style={{ fontSize: 12, color: 'var(--text)', marginBottom: 6 }}>
                  Efficient frontier — risk σ vs expected ROI · <span style={{ color: 'var(--success)' }}>●</span> chosen portfolio
                </div>
                <FrontierChart frontier={live.result.frontier} />
              </div>
              {allocs.length > 0 && (
                <div className="card" style={{ flex: '1 1 280px', minWidth: 240 }}>
                  <div style={{ fontSize: 12, color: 'var(--text)', marginBottom: 6 }}>Allocation weights</div>
                  <WeightBars allocs={allocs} />
                </div>
              )}
            </div>
          )}

          {allocs.length > 0 && (
            <div className="card" style={{ padding: 0, overflowX: 'auto' }}>
              <table>
                <thead>
                  <tr>
                    <th>Item</th><th>Method</th>
                    <th style={{ textAlign: 'right' }}>Qty</th>
                    <th style={{ textAlign: 'right' }}>Unit cost</th>
                    <th style={{ textAlign: 'right' }}>Capital</th>
                    <th style={{ textAlign: 'right' }}>Exp. profit</th>
                    <th style={{ textAlign: 'right' }}>ROI</th>
                    <th style={{ textAlign: 'right' }}>Wt%</th>
                    <th style={{ textAlign: 'right' }}>m³</th>
                  </tr>
                </thead>
                <tbody>
                  {allocs.map(a => (
                    <tr key={a.type_id}>
                      <td style={{ color: 'var(--text-white)', whiteSpace: 'nowrap' }}>{a.name}</td>
                      <td style={{ whiteSpace: 'nowrap', fontSize: 12 }}>{methodLabel(a.best_method)}</td>
                      <td style={{ textAlign: 'right' }}>{fmtNum(a.qty)}</td>
                      <td style={{ textAlign: 'right', color: 'var(--text)' }}>{fmtIsk(a.unit_cost)}</td>
                      <td style={{ textAlign: 'right', color: 'var(--text)' }}>{fmtIsk(a.capital)}</td>
                      <td style={{ textAlign: 'right', color: 'var(--success)' }}>{fmtIsk(a.expected_profit)}</td>
                      <td style={{ textAlign: 'right', color: 'var(--text)' }}>{(a.roi * 100).toFixed(1)}%</td>
                      <td style={{ textAlign: 'right', color: 'var(--text)' }}>{(a.weight * 100).toFixed(1)}</td>
                      <td style={{ textAlign: 'right', color: 'var(--text)' }}>{fmtNum(a.volume_m3)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  )
}

// ── Manual list: paste a shopping list and size it ────────────────────────────

const PLACEHOLDER = `Acolyte II\t1\t334,100.00\t334,100.00
Hobgoblin II\t10
Warrior II x5
Agency 'Pyrolancea' DB3 Dose I\t2`

function ManualHaul() {
  const [paste, setPaste] = useState('')
  const [methods, setMethods] = useState(['sell_buy'])
  const [shipM3, setShipM3] = useState(1200)
  const [shipFlat, setShipFlat] = useState('')
  const [broker, setBroker] = useState(3.0)
  const [tax, setTax] = useState(4.5)
  const [rankBy, setRankBy] = useState('profit')
  const [res, setRes] = useState(null)
  const [err, setErr] = useState('')
  const [loading, setLoading] = useState(false)

  function toggleMethod(k) {
    setMethods(m => m.includes(k) ? m.filter(x => x !== k) : [...m, k])
  }

  async function evaluate() {
    if (!paste.trim()) { setErr('Paste a list of items first.'); return }
    setLoading(true); setErr('')
    try {
      const r = await post('/trade/haul', {
        paste,
        methods: methods.length ? methods : ['sell_buy'],
        shipping_per_m3: Number(shipM3) || 0,
        shipping_flat: shipFlat !== '' ? Number(shipFlat) : 0,
        broker_fee_pct: Number(broker) || 0,
        sales_tax_pct: Number(tax) || 0,
        rank_by: rankBy,
      })
      setRes(r)
    } catch (e) { setErr(e.message); setRes(null) }
    finally { setLoading(false) }
  }

  const t = res?.totals
  return (
    <div>
      <p style={{ color: 'var(--text)', fontSize: 13, marginBottom: 16, maxWidth: 760 }}>
        Paste a shopping list (EVE multibuy / inventory copy), pick how you buy in Jita and sell in
        <b> C-J6MT</b>, set a courier rate, and see profit + ROI per item — to decide whether to haul.
        Live prices: Jita (Fuzzwork), C-J (appraise.gnf.lt).
      </p>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 320px', gap: 18, alignItems: 'start' }}>
        <div>
          <Label>Items</Label>
          <textarea value={paste} onChange={e => setPaste(e.target.value)} placeholder={PLACEHOLDER}
                    rows={10} style={{ width: '100%', fontFamily: 'monospace', fontSize: 12, resize: 'vertical' }} />
        </div>

        <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div>
            <Label>Method <span style={{ color: 'var(--border2)' }}>(buy side → sell side)</span></Label>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 4 }}>
              {METHODS.map(m => (
                <button key={m.key} title={m.hint} onClick={() => toggleMethod(m.key)}
                        className={`tab-btn ${methods.includes(m.key) ? 'active' : ''}`}
                        style={{ fontSize: 12, padding: '4px 10px' }}>{m.label}</button>
              ))}
            </div>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            <Field label="Courier ISK/m³"><input type="number" min="0" value={shipM3} onChange={e => setShipM3(e.target.value)} /></Field>
            <Field label="Flat ship (opt)"><input type="number" min="0" value={shipFlat} onChange={e => setShipFlat(e.target.value)} placeholder="0" /></Field>
            <Field label="Broker fee %"><input type="number" min="0" step="0.1" value={broker} onChange={e => setBroker(e.target.value)} /></Field>
            <Field label="Sales tax %"><input type="number" min="0" step="0.1" value={tax} onChange={e => setTax(e.target.value)} /></Field>
          </div>
          <div>
            <Label>Rank by</Label>
            <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
              {['profit', 'roi'].map(k => (
                <button key={k} onClick={() => setRankBy(k)}
                        className={`tab-btn ${rankBy === k ? 'active' : ''}`}
                        style={{ fontSize: 12, padding: '4px 12px' }}>{k === 'profit' ? 'Profit' : 'ROI'}</button>
              ))}
            </div>
          </div>
          <button className="btn btn-primary" disabled={loading} onClick={evaluate}>
            {loading ? 'Pricing…' : 'Evaluate haul'}
          </button>
        </div>
      </div>

      {err && <div className="error-box" style={{ marginTop: 14 }}>{err}</div>}

      {res && (
        <div style={{ marginTop: 20 }}>
          {!res.prices_available && <div className="warning-box" style={{ marginBottom: 12 }}>No live prices returned — Jita/C-J sources may be unavailable.</div>}
          {res.truncated && <div className="warning-box" style={{ marginBottom: 12 }}>List truncated to the first {res.max_items} items.</div>}
          {res.unmatched?.length > 0 && (
            <div className="warning-box" style={{ marginBottom: 12 }}>Unrecognised: {res.unmatched.join(', ')}</div>
          )}

          <div className="card" style={{ display: 'flex', gap: 28, flexWrap: 'wrap', marginBottom: 14 }}>
            <Stat label="Total profit (best method)" value={fmtIsk(t.profit)} good={t.profit > 0} />
            <Stat label="Capital needed" value={fmtIsk(t.capital)} />
            <Stat label="ROI" value={`${(t.roi * 100).toFixed(1)}%`} good={t.roi > 0} />
            <Stat label="Cargo" value={`${fmtNum(t.volume)} m³`} />
            <Stat label="Worth hauling" value={`${t.recommend_count} / ${t.count}`} good={t.recommend_count > 0} />
          </div>

          <div className="card" style={{ padding: 0, overflowX: 'auto' }}>
            <table>
              <thead>
                <tr>
                  <th></th><th>Item</th><th style={{ textAlign: 'right' }}>Qty</th>
                  <th style={{ textAlign: 'right' }}>Jita sell</th>
                  <th style={{ textAlign: 'right' }}>Jita buy</th>
                  <th style={{ textAlign: 'right' }}>C-J buy</th>
                  <th style={{ textAlign: 'right' }}>C-J sell</th>
                  <th>Best method</th>
                  <th style={{ textAlign: 'right' }}>Profit</th>
                  <th style={{ textAlign: 'right' }}>ROI</th>
                </tr>
              </thead>
              <tbody>
                {res.items.map(i => (
                  <tr key={i.type_id} style={i.best ? undefined : { opacity: 0.5 }}>
                    <td style={{ textAlign: 'center', fontSize: 14 }}>{i.recommend ? '✅' : (i.best ? '❌' : '—')}</td>
                    <td style={{ color: 'var(--text-white)', whiteSpace: 'nowrap' }}>{i.name}</td>
                    <td style={{ textAlign: 'right' }}>{fmtNum(i.qty)}</td>
                    <td style={{ textAlign: 'right', color: 'var(--text)' }}>{i.jita_sell != null ? fmtIsk(i.jita_sell) : '—'}</td>
                    <td style={{ textAlign: 'right', color: 'var(--text)' }}>{i.jita_buy != null ? fmtIsk(i.jita_buy) : '—'}</td>
                    <td style={{ textAlign: 'right', color: 'var(--text)' }}>{i.cj_buy != null ? fmtIsk(i.cj_buy) : '—'}</td>
                    <td style={{ textAlign: 'right', color: 'var(--text)' }}>{i.cj_sell != null ? fmtIsk(i.cj_sell) : '—'}</td>
                    <td style={{ whiteSpace: 'nowrap', fontSize: 12 }}>{i.best ? methodLabel(i.best.method) : '—'}</td>
                    <td style={{ textAlign: 'right', color: i.best ? (i.best.profit > 0 ? 'var(--success)' : 'var(--danger)') : undefined }}>
                      {i.best ? fmtIsk(i.best.profit) : '—'}
                    </td>
                    <td style={{ textAlign: 'right', color: i.best ? (i.best.roi > 0 ? 'var(--success)' : 'var(--danger)') : undefined }}>
                      {i.best ? `${(i.best.roi * 100).toFixed(1)}%` : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Markowitz plots (inline SVG — no Plotly, keeps it out of the main bundle) ──

function FrontierChart({ frontier }) {
  const points = frontier?.points || []
  const assets = frontier?.assets || []
  const chosen = frontier?.chosen
  if (points.length < 2) return null

  const W = 440, H = 250, ml = 46, mr = 14, mt = 12, mb = 32
  const pw = W - ml - mr, ph = H - mt - mb
  const all = [...points, ...assets, ...(chosen ? [chosen] : [])]
  const xv = all.map(p => p.stddev * 100), yv = all.map(p => p.exp_return * 100)
  let x0 = Math.min(...xv), x1 = Math.max(...xv), y0 = Math.min(...yv), y1 = Math.max(...yv)
  const xp = (x1 - x0) * 0.08 || 1, yp = (y1 - y0) * 0.08 || 1
  x0 -= xp; x1 += xp; y0 -= yp; y1 += yp
  const toX = v => ml + ((v * 100) - x0) / (x1 - x0) * pw
  const toY = v => mt + ph - ((v * 100) - y0) / (y1 - y0) * ph
  const axis = 'var(--border2, #8a93a3)', txt = 'var(--text, #aab)'
  const linePts = points.map(p => `${toX(p.stddev).toFixed(1)},${toY(p.exp_return).toFixed(1)}`).join(' ')

  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto' }} role="img" aria-label="Efficient frontier">
      <line x1={ml} y1={mt} x2={ml} y2={mt + ph} stroke={axis} strokeWidth="1" />
      <line x1={ml} y1={mt + ph} x2={ml + pw} y2={mt + ph} stroke={axis} strokeWidth="1" />
      {[[x0, mt + ph + 12, 'start'], [x1, mt + ph + 12, 'end']].map(([v, y, a], k) => (
        <text key={k} x={k === 0 ? ml : ml + pw} y={y} fontSize="9" fill={txt} textAnchor={a}>{v.toFixed(1)}</text>
      ))}
      {[[y1, mt + 3], [y0, mt + ph]].map(([v, y], k) => (
        <text key={k} x={ml - 5} y={y} fontSize="9" fill={txt} textAnchor="end">{v.toFixed(1)}</text>
      ))}
      <text x={ml + pw / 2} y={H - 4} fontSize="9" fill={txt} textAnchor="middle">risk σ (%)</text>
      <text x={10} y={mt + 2} fontSize="9" fill={txt}>ROI %</text>
      <polyline points={linePts} fill="none" stroke="var(--accent, #4f8cff)" strokeWidth="1.8" />
      {assets.map((a, k) => <circle key={k} cx={toX(a.stddev)} cy={toY(a.exp_return)} r="3" fill={axis} opacity="0.8" />)}
      {chosen && <circle cx={toX(chosen.stddev)} cy={toY(chosen.exp_return)} r="5.5" fill="var(--success, #1e9e5a)" stroke="#fff" strokeWidth="1.4" />}
    </svg>
  )
}

function WeightBars({ allocs }) {
  const rows = allocs.filter(a => a.qty > 0).slice().sort((a, b) => b.weight - a.weight).slice(0, 12)
  if (!rows.length) return null
  const max = Math.max(...rows.map(r => r.weight)) || 1
  return (
    <div style={{ marginTop: 6 }}>
      {rows.map(r => (
        <div key={r.type_id} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
          <div style={{ width: 130, fontSize: 12, color: 'var(--text-white)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.name}</div>
          <div style={{ flex: 1, background: 'var(--border, #2a2f3a)', borderRadius: 3, height: 13, overflow: 'hidden' }}>
            <div style={{ width: `${(r.weight / max) * 100}%`, height: '100%', background: 'var(--accent, #4f8cff)' }} />
          </div>
          <div style={{ width: 46, textAlign: 'right', fontSize: 12, color: 'var(--text)' }}>{(r.weight * 100).toFixed(1)}%</div>
        </div>
      ))}
    </div>
  )
}

function Label({ children }) {
  return <label style={{ display: 'block', fontSize: 11, color: 'var(--text)', marginBottom: 4 }}>{children}</label>
}

function Field({ label, children }) {
  return <div><Label>{label}</Label>{children}</div>
}

function Stat({ label, value, good }) {
  return (
    <div>
      <div style={{ fontSize: 11, color: 'var(--text)' }}>{label}</div>
      <div style={{ fontSize: 18, fontWeight: 700, color: good ? 'var(--success)' : 'var(--text-white)' }}>{value}</div>
    </div>
  )
}
