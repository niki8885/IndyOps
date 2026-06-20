import { useState, useEffect } from 'react'
import { get, post } from '../api/client'
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
  { id: 8, label: 'Charges' }, { id: 18, label: 'Drones' }, { id: 87, label: 'Fighters' },
]
const catLabel = id => CATEGORIES.find(c => c.id === id)?.label || ''

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

function HaulScanner() {
  const [minMargin, setMinMargin] = useState(0)
  const [cat, setCat] = useState('')
  const [rankBy, setRankBy] = useState('profit')
  const [res, setRes] = useState(null)
  const [err, setErr] = useState('')
  const [loading, setLoading] = useState(false)

  async function load() {
    setLoading(true); setErr('')
    try {
      const q = new URLSearchParams({ rank_by: rankBy, min_margin: String((Number(minMargin) || 0) / 100), limit: '200' })
      if (cat !== '') q.set('category_id', String(cat))
      setRes(await get(`/trade/haul/scan?${q.toString()}`))
    } catch (e) { setErr(e.message); setRes(null) }
    finally { setLoading(false) }
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps, react-hooks/set-state-in-effect
  useEffect(() => { load() }, [])  // auto-load on mount

  return (
    <div>
      <p style={{ color: 'var(--text)', fontSize: 13, marginBottom: 14, maxWidth: 780 }}>
        Auto-discovered profitable hauls — the most liquid Jita items (≥100 traded/day; ships, modules,
        charges, drones, fighters) priced against C-J6MT and refreshed in the background. Per-unit
        profit/ROI at a default courier rate; use the Manual list to size a specific buy.
      </p>

      <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end', flexWrap: 'wrap', marginBottom: 14 }}>
        <Field label="Min ROI %"><input type="number" min="0" step="1" value={minMargin} onChange={e => setMinMargin(e.target.value)} style={{ width: 90 }} /></Field>
        <Field label="Category">
          <select value={cat} onChange={e => setCat(e.target.value === '' ? '' : Number(e.target.value))}>
            {CATEGORIES.map(c => <option key={c.label} value={c.id}>{c.label}</option>)}
          </select>
        </Field>
        <Field label="Rank by">
          <select value={rankBy} onChange={e => setRankBy(e.target.value)}>
            <option value="profit">Profit / unit</option>
            <option value="roi">ROI</option>
          </select>
        </Field>
        <button className="btn btn-primary" disabled={loading} onClick={load}>{loading ? 'Loading…' : 'Refresh'}</button>
      </div>

      {err && <div className="error-box">{err}</div>}

      {res && (
        <>
          {res.stale && <div className="warning-box" style={{ marginBottom: 10 }}>Data is stale — the scanner hasn’t refreshed recently.</div>}
          <div style={{ fontSize: 12, color: 'var(--text)', marginBottom: 8 }}>
            {res.count} candidate{res.count === 1 ? '' : 's'} · {res.updated_at ? `updated ${new Date(res.updated_at).toLocaleString()}` : 'never run yet'}
          </div>
          {res.count === 0
            ? <div className="empty-state">No profitable hauls right now (or the scanner hasn’t run — needs Jita history data first).</div>
            : (
              <div className="card" style={{ padding: 0, overflowX: 'auto' }}>
                <table>
                  <thead>
                    <tr>
                      <th>Item</th><th>Cat</th>
                      <th style={{ textAlign: 'right' }}>Jita sell</th>
                      <th style={{ textAlign: 'right' }}>C-J buy</th>
                      <th style={{ textAlign: 'right' }}>C-J sell</th>
                      <th style={{ textAlign: 'right' }}>Vol/day</th>
                      <th>Method</th>
                      <th style={{ textAlign: 'right' }}>Profit/unit</th>
                      <th style={{ textAlign: 'right' }}>ROI</th>
                    </tr>
                  </thead>
                  <tbody>
                    {res.items.map(i => (
                      <tr key={i.type_id}>
                        <td style={{ color: 'var(--text-white)', whiteSpace: 'nowrap' }}>{i.name}</td>
                        <td style={{ fontSize: 11, color: 'var(--text)' }}>{catLabel(i.category_id)}</td>
                        <td style={{ textAlign: 'right', color: 'var(--text)' }}>{i.jita_sell != null ? fmtIsk(i.jita_sell) : '—'}</td>
                        <td style={{ textAlign: 'right', color: 'var(--text)' }}>{i.cj_buy != null ? fmtIsk(i.cj_buy) : '—'}</td>
                        <td style={{ textAlign: 'right', color: 'var(--text)' }}>{i.cj_sell != null ? fmtIsk(i.cj_sell) : '—'}</td>
                        <td style={{ textAlign: 'right', color: 'var(--text)' }}>{fmtNum(i.daily_volume)}</td>
                        <td style={{ whiteSpace: 'nowrap', fontSize: 12 }}>{methodLabel(i.best_method)}</td>
                        <td style={{ textAlign: 'right', color: 'var(--success)' }}>{fmtIsk(i.profit_per_unit)}</td>
                        <td style={{ textAlign: 'right', color: 'var(--success)' }}>{(i.roi * 100).toFixed(1)}%</td>
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
  const [shipM3, setShipM3] = useState(1500)
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
