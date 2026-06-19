import { useState, useEffect } from 'react'
import { get, post, patch, del } from '../api/client'
import SystemSearch from '../components/SystemSearch'

const PRICE_METHODS = ['Buy', 'Split', 'Sell']

export default function InventoryPage() {
  const [tab, setTab] = useState(0)
  const TABS = ['Warehouse', 'Parse & Import', 'Delivery']
  return (
    <div>
      <h2 style={{ marginBottom: 20 }}>Inventory</h2>
      <div className="tabs">
        {TABS.map((t, i) => (
          <button key={i} className={`tab-btn ${tab === i ? 'active' : ''}`} onClick={() => setTab(i)}>{t}</button>
        ))}
      </div>
      {tab === 0 ? <WarehouseTab /> : tab === 1 ? <ParseTab /> : <DeliveryTab />}
    </div>
  )
}

/* ════════════════════════════ WAREHOUSE ════════════════════════════ */

function WarehouseTab() {
  const [items, setItems]       = useState([])
  const [orgs, setOrgs]         = useState([])
  const [projects, setProjects] = useState([])
  const [filter, setFilter]     = useState({ org_id: '', project_id: '', place: '' })
  const [error, setError]       = useState('')
  const [clearing, setClearing] = useState(false)
  const [view, setView]         = useState('stacked')   // 'stacked' | 'lots'
  const [method, setMethod]     = useState('AVG')        // AVG | FIFO | LIFO
  const [expand, setExpand]     = useState(null)

  async function load() {
    const p = new URLSearchParams()
    if (filter.project_id)   p.set('project_id', filter.project_id)
    else if (filter.org_id)  p.set('organisation_id', filter.org_id)
    if (filter.place)        p.set('place', filter.place)
    try { setItems(await get(`/inventory?${p}`)) } catch {}
  }

  useEffect(() => {
    get('/organisations').then(async os => {
      setOrgs(os)
      const all = []
      for (const o of os) {
        try { all.push(...(await get(`/projects?org_id=${o.id}`)).map(p => ({ ...p, orgName: o.name }))) } catch {}
      }
      setProjects(all)
    }).catch(() => {})
  }, [])

  useEffect(() => { load() }, [filter])

  const visibleProjects = filter.org_id
    ? projects.filter(p => String(p.organisation_id) === String(filter.org_id))
    : projects

  async function remove(id) {
    if (!confirm('Delete item?')) return
    try { await del(`/inventory/${id}`); load() } catch {}
  }

  async function sell(item) {
    const p = prompt(`Sell "${item.name}" ×${item.quantity.toLocaleString()}\nSale price per unit (ISK):`, item.price || '')
    if (p == null) return
    const sp = Number(p)
    if (!sp || sp <= 0) { setError('Invalid sale price'); return }
    try { await post(`/inventory/${item.id}/sell`, { sale_price: sp }); load() }
    catch (e) { setError(e.message) }
  }

  async function consumeItem(item) {
    const reason = prompt(`Write off "${item.name}" ×${item.quantity.toLocaleString()} for internal use.\nReason:`, 'internal use')
    if (reason == null) return
    try { await post(`/inventory/${item.id}/use`, { reason }); load() }
    catch (e) { setError(e.message) }
  }

  async function splitItem(item) {
    const p = prompt(`Split "${item.name}" ×${item.quantity.toLocaleString()}\nUnits to move into a new stack (1…${(item.quantity - 1).toLocaleString()}):`, Math.floor(item.quantity / 2))
    if (p == null) return
    const qty = Math.floor(Number(p))
    if (!qty || qty <= 0 || qty >= item.quantity) { setError(`Split qty must be between 1 and ${item.quantity - 1}`); return }
    try { await post(`/inventory/${item.id}/split`, { quantity: qty }); load() }
    catch (e) { setError(e.message) }
  }

  const flowBadge = f => (
    <span style={{
      fontSize: 9, fontWeight: 700, padding: '1px 5px', borderRadius: 3, marginLeft: 6,
      background: f === 'output' ? '#0e2a1a' : '#10243d',
      color: f === 'output' ? '#4caf7d' : '#3a9bd6',
    }}>{f === 'output' ? 'OUT' : 'IN'}</span>
  )

  const ItemActions = ({ item }) => (
    <span style={{ whiteSpace: 'nowrap' }}>
      <button className="btn btn-ghost btn-sm" onClick={() => splitItem(item)} style={{ marginRight: 3, padding: '3px 7px' }} title="Split stack" disabled={item.quantity < 2}>✂️</button>
      <button className="btn btn-ghost btn-sm" onClick={() => sell(item)} style={{ marginRight: 3, padding: '3px 7px' }} title="Sell (record price)">💰</button>
      <button className="btn btn-ghost btn-sm" onClick={() => consumeItem(item)} style={{ marginRight: 3, padding: '3px 7px' }} title="Write off / internal use">🔧</button>
      <button className="btn btn-danger btn-sm" onClick={() => remove(item.id)} title="Delete">✕</button>
    </span>
  )
  async function clearProject() {
    const proj = projects.find(p => String(p.id) === filter.project_id)
    if (!confirm(`Clear ALL items in project "${proj?.name}"?\nCannot be undone.`)) return
    setClearing(true); setError('')
    try { await del(`/inventory?project_id=${filter.project_id}`); load() }
    catch (e) { setError(e.message) } finally { setClearing(false) }
  }
  async function clearAll() {
    if (!confirm(`Delete ALL ${items.length} items from warehouse?\nCannot be undone.`)) return
    setClearing(true); setError('')
    try { await del('/inventory'); load() }
    catch (e) { setError(e.message) } finally { setClearing(false) }
  }

  const projName = id => projects.find(p => p.id === id)?.name || '—'

  // group lots into stacks by eve_type_id (fallback to name)
  const groups = (() => {
    const m = new Map()
    for (const it of items) {
      const key = it.eve_type_id ?? `n:${it.name}`
      let g = m.get(key)
      if (!g) { g = { key, name: it.name, volume: it.volume, qty: 0, value: 0, pricedQty: 0, lots: [], places: new Set() }; m.set(key, g) }
      g.qty += it.quantity
      if (it.price) { g.value += it.price * it.quantity; g.pricedQty += it.quantity }
      g.lots.push(it)
      if (it.place) g.places.add(it.place)
    }
    return [...m.values()]
  })()

  function unitCost(g) {
    if (g.pricedQty === 0) return null
    if (method === 'AVG') return g.value / g.pricedQty
    const priced = g.lots.filter(l => l.price).sort((a, b) => new Date(a.created_at) - new Date(b.created_at))
    return method === 'FIFO' ? priced[0].price : priced[priced.length - 1].price
  }

  const totalValue = items.reduce((s, i) => s + (i.price ?? 0) * i.quantity, 0)
  const totalVol   = items.reduce((s, i) => s + (i.volume ?? 0) * i.quantity, 0)

  return (
    <div>
      {error && <div className="error-box">{error}</div>}
      <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap', alignItems: 'flex-end' }}>
        <select value={filter.org_id} onChange={e => setFilter(f => ({ ...f, org_id: e.target.value, project_id: '' }))} style={{ width: 170 }}>
          <option value="">All organisations</option>
          {orgs.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
        </select>
        <select value={filter.project_id} onChange={e => setFilter(f => ({ ...f, project_id: e.target.value }))} style={{ width: 170 }}>
          <option value="">All projects{filter.org_id ? ' (in org)' : ''}</option>
          {visibleProjects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
        <input value={filter.place} onChange={e => setFilter(f => ({ ...f, place: e.target.value }))} placeholder="Filter by system…" style={{ width: 150 }} />
        <div style={{ display: 'flex', gap: 4 }}>
          {['stacked', 'lots'].map(v => (
            <button key={v} className={`btn btn-sm ${view === v ? 'btn-primary' : 'btn-ghost'}`} onClick={() => setView(v)}>
              {v === 'stacked' ? 'Stacked' : 'Lots'}
            </button>
          ))}
        </div>
        {view === 'stacked' && (
          <div style={{ display: 'flex', gap: 4 }}>
            {['AVG', 'FIFO', 'LIFO'].map(m => (
              <button key={m} className={`btn btn-sm ${method === m ? 'btn-primary' : 'btn-ghost'}`} onClick={() => setMethod(m)}>{m}</button>
            ))}
          </div>
        )}
        <button className="btn btn-ghost btn-sm" onClick={load}>Refresh</button>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
          {filter.project_id && (
            <button className="btn btn-danger btn-sm" onClick={clearProject} disabled={clearing || items.length === 0}>
              {clearing ? '…' : 'Clear project'}
            </button>
          )}
          <button className="btn btn-danger btn-sm" onClick={clearAll} disabled={clearing || items.length === 0}>
            {clearing ? '…' : 'Clear ALL warehouse'}
          </button>
        </div>
      </div>

      {items.length === 0
        ? <div className="empty-state">No items in inventory</div>
        : (
          <>
            <div style={{ display: 'flex', gap: 16, marginBottom: 12, flexWrap: 'wrap' }}>
              <Stat label={view === 'stacked' ? 'Unique items' : 'Lots'} value={view === 'stacked' ? groups.length : items.length} />
              <Stat label="Total volume" value={totalVol > 0 ? fmtVol(totalVol) : '—'} />
              <Stat label="Total value" value={totalValue > 0 ? fmtIsk(totalValue) : '—'} />
            </div>

            {view === 'stacked' ? (
              <div className="card" style={{ padding: 0, overflowX: 'auto' }}>
                <table>
                  <thead>
                    <tr>
                      <th>Name</th><th>Total Qty</th><th>Lots</th>
                      <th>{method} cost/unit</th><th>Total value</th><th>Locations</th><th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...groups].sort((a, b) => b.value - a.value).map(g => {
                      const uc = unitCost(g)
                      return [
                        <tr key={g.key} style={{ cursor: 'pointer' }} onClick={() => setExpand(expand === g.key ? null : g.key)}>
                          <td style={{ color: 'var(--text-white)', whiteSpace: 'nowrap' }}>{g.name}</td>
                          <td style={{ color: 'var(--text-white)' }}>{g.qty.toLocaleString()}</td>
                          <td style={{ color: 'var(--text)', fontSize: 12 }}>{g.lots.length}</td>
                          <td style={{ color: 'var(--accent)' }}>{uc != null ? fmtIsk(uc) : <span style={{ color: 'var(--text)' }}>—</span>}</td>
                          <td style={{ color: 'var(--text-white)' }}>{g.value > 0 ? fmtIsk(g.value) : '—'}</td>
                          <td style={{ color: 'var(--text)', fontSize: 12 }}>{[...g.places].join(', ') || '—'}</td>
                          <td style={{ color: 'var(--text)', fontSize: 12 }}>{expand === g.key ? '▲' : '▼'}</td>
                        </tr>,
                        expand === g.key && (
                          <tr key={`x-${g.key}`}>
                            <td colSpan={7} style={{ background: 'var(--surface2)', padding: 0 }}>
                              <table>
                                <tbody>
                                  {g.lots.map(l => (
                                    <tr key={l.id}>
                                      <td style={{ color: 'var(--text)', paddingLeft: 28, whiteSpace: 'nowrap' }}>
                                        {l.quantity.toLocaleString()}{flowBadge(l.flow)}
                                      </td>
                                      <td style={{ color: 'var(--text)' }}>{l.price ? fmtIsk(l.price) : '—'}</td>
                                      <td style={{ color: 'var(--text)', fontSize: 12 }}>{l.place || '—'}</td>
                                      <td style={{ color: 'var(--text)', fontSize: 12 }}>{projName(l.project_id)}</td>
                                      <td style={{ color: 'var(--text)', fontSize: 11 }}>{l.created_at ? new Date(l.created_at).toLocaleDateString() : ''}</td>
                                      <td><ItemActions item={l} /></td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </td>
                          </tr>
                        ),
                      ]
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="card" style={{ padding: 0, overflowX: 'auto' }}>
                <table>
                  <thead>
                    <tr>
                      <th>Name</th><th>Qty</th><th>Vol/unit</th><th>Price/unit</th>
                      <th>Total value</th><th>Location</th><th>Project</th><th>Note</th><th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map(item => (
                      <tr key={item.id}>
                        <td style={{ color: 'var(--text-white)', whiteSpace: 'nowrap' }}>{item.name}{flowBadge(item.flow)}</td>
                        <td>{item.quantity.toLocaleString()}</td>
                        <td style={{ color: 'var(--text)' }}>{item.volume != null ? item.volume + ' m³' : '—'}</td>
                        <td>{item.price ? fmtIsk(item.price) : '—'}</td>
                        <td style={{ color: 'var(--accent)' }}>{item.price ? fmtIsk(item.price * item.quantity) : '—'}</td>
                        <td style={{ color: 'var(--text)', fontSize: 12 }}>{item.place || '—'}</td>
                        <td style={{ color: 'var(--text)', fontSize: 12 }}>{projName(item.project_id)}</td>
                        <td style={{ color: 'var(--text)', fontSize: 12, maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis' }}>{item.note || '—'}</td>
                        <td><ItemActions item={item} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )
      }
    </div>
  )
}

/* ════════════════════════════ PARSE TAB ════════════════════════════ */

function ParseTab() {
  const [rawText, setRawText]       = useState('')
  const [rows, setRows]             = useState([])
  const [projects, setProjects]     = useState([])
  const [warnings, setWarnings]     = useState([])
  const [error, setError]           = useState('')
  const [parsing, setParsing]       = useState(false)
  const [saving, setSaving]         = useState(false)
  const [saveResult, setSaveResult] = useState(null)
  const [fetchingPrices, setFetchingPrices] = useState(false)

  // global controls
  const [globalProject, setGlobalProject] = useState('')
  const [globalPlace, setGlobalPlace]     = useState('')
  const [priceMethod, setPriceMethod]     = useState('Buy')
  const [market, setMarket]               = useState('Jita')
  const [flow, setFlow]                   = useState('input')   // input | output
  const [deliveryCoef, setDeliveryCoef]   = useState(1200)      // ISK/m³ added to buy price
  const [deliveryApplied, setDeliveryApplied] = useState(false)

  function applyDelivery() {
    setRows(rs => rs.map(r => {
      if (!r.volume) return r
      const base = Number(r.price) || 0
      return { ...r, price: (base + Number(deliveryCoef || 0) * r.volume).toFixed(2) }
    }))
    setDeliveryApplied(true)
  }

  useEffect(() => {
    get('/organisations').then(async orgs => {
      const all = []
      for (const o of orgs) {
        try { all.push(...(await get(`/projects?org_id=${o.id}`)).map(p => ({ ...p, orgName: o.name }))) } catch {}
      }
      setProjects(all)
    }).catch(() => {})
  }, [])

  async function parse() {
    if (!rawText.trim()) return
    setParsing(true); setError(''); setSaveResult(null)
    try {
      const res = await post('/inventory/preview', { text: rawText })
      setWarnings(res.warnings)
      setDeliveryApplied(false)
      setRows(res.items.map(item => ({
        ...item,
        price: '',
        place: globalPlace,
        note: '',
        project_id: globalProject,
      })))
    } catch (err) { setError(err.message) }
    finally { setParsing(false) }
  }

  function updateRow(i, key, val) {
    setRows(r => r.map((row, idx) => idx === i ? { ...row, [key]: val } : row))
  }

  function applyGlobalProject(pid) {
    setGlobalProject(pid)
    setRows(r => r.map(row => ({ ...row, project_id: pid })))
  }

  function applyGlobalPlace(place) {
    setGlobalPlace(place)
    setRows(r => r.map(row => ({ ...row, place })))
  }

  async function fetchPrices() {
    const withType = rows.filter(r => r.eve_type_id)
    if (!withType.length) {
      setError('No items with resolved EVE type IDs — make sure SDE is synced (yellow banner above)')
      return
    }
    setFetchingPrices(true); setError('')
    try {
      const ids = [...new Set(withType.map(r => r.eve_type_id))]
      let priceMap = {}

      if (market === 'Jita') {
        const res = await fetch(`https://market.fuzzwork.co.uk/aggregates/?station=60003760&types=${ids.join(',')}`)
        if (!res.ok) throw new Error(`Fuzzwork returned ${res.status}`)
        const data = await res.json()
        for (const [tid, p] of Object.entries(data)) {
          const buy  = Number.parseFloat(p.buy.max)
          const sell = Number.parseFloat(p.sell.min)
          priceMap[Number(tid)] = { Buy: buy, Split: (buy + sell) / 2, Sell: sell }
        }
      } else if (market === 'C-J') {
        const data = await get(`/eve/prices/cj?type_ids=${ids.join(',')}`)
        for (const [tid, p] of Object.entries(data)) {
          priceMap[Number(tid)] = { Buy: p.buy, Split: p.split, Sell: p.sell }
        }
      }

      setRows(prev => prev.map(row => {
        if (!row.eve_type_id || !priceMap[row.eve_type_id]) return row
        const price = priceMap[row.eve_type_id][priceMethod]
        return { ...row, price: price != null ? price.toFixed(2) : row.price }
      }))
    } catch (e) { setError('Price fetch failed: ' + e.message) }
    finally { setFetchingPrices(false) }
  }

  async function saveAll() {
    setSaving(true); setError('')
    try {
      const proj = projects.find(p => String(p.id) === globalProject)
      const methodLabel = market !== 'Other' ? `${market} ${priceMethod}` : 'Manual'
      const dateStr = new Date().toLocaleDateString('ru-RU')
      const autoNote = proj ? `${proj.name} | ${dateStr} | ${methodLabel}` : `${dateStr} | ${methodLabel}`

      await post('/inventory/batch', {
        items: rows.map(r => ({
          eve_type_id: r.eve_type_id || null,
          name:       r.name,
          quantity:   r.quantity,
          volume:     r.volume || null,
          price:      r.price !== '' ? Number(r.price) : null,
          place:      r.place || null,
          note:       r.note || autoNote,
          project_id: r.project_id ? Number(r.project_id) : null,
          flow,
        })),
      })

      const totalValue = rows.reduce((s, r) => s + (Number(r.price) || 0) * r.quantity, 0)
      const contractNote = [
        proj ? `P${proj.id}` : null,
        proj?.name,
        dateStr,
        methodLabel,
        fmtIsk(totalValue),
      ].filter(Boolean).join(' | ')

      setSaveResult({ count: rows.length, totalValue, contractNote, projName: proj?.name, method: methodLabel })
      setRows([]); setRawText(''); setWarnings([])
    } catch (err) { setError(err.message) }
    finally { setSaving(false) }
  }

  const totalVol   = rows.reduce((s, r) => s + (r.volume_total ?? 0), 0)
  const totalValue = rows.reduce((s, r) => s + (Number(r.price) || 0) * r.quantity, 0)

  return (
    <div>
      {/* Paste area */}
      <div className="card" style={{ marginBottom: 20 }}>
        <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
          <div style={{ flex: 1 }}>
            <label htmlFor="inv-paste" style={{ display: 'block', fontSize: 12, color: 'var(--text)', marginBottom: 6 }}>
              Paste from EVE inventory (Name ⇥ Qty or Qty ⇥ Name, one per line)
            </label>
            <textarea
              id="inv-paste"
              value={rawText}
              onChange={e => setRawText(e.target.value)}
              placeholder={'80190\tCoolant\n35640\tEnriched Uranium\nLiquid Ozone\t3118500'}
              rows={7}
              style={{ fontFamily: 'monospace', fontSize: 13 }}
            />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, paddingTop: 22 }}>
            <button className="btn btn-primary" onClick={parse} disabled={parsing || !rawText.trim()}>
              {parsing ? 'Parsing…' : '▶ Parse'}
            </button>
            <button className="btn btn-ghost btn-sm" onClick={() => { setRawText(''); setRows([]); setWarnings([]); setSaveResult(null) }}>
              Clear
            </button>
          </div>
        </div>
      </div>

      {error && <div className="error-box">{error}</div>}

      {/* Save result banner */}
      {saveResult && (
        <div style={{ background: '#0e2a1a', border: '1px solid #2e6b44', borderRadius: 6, padding: '14px 18px', marginBottom: 16 }}>
          <div style={{ color: '#4caf7d', fontWeight: 600, fontSize: 14, marginBottom: 8 }}>
            ✓ {saveResult.count} items saved to inventory
          </div>
          <div style={{ display: 'flex', gap: 24, fontSize: 12, color: 'var(--text)', flexWrap: 'wrap', marginBottom: 10 }}>
            <span>Total: <b style={{ color: 'var(--text-white)' }}>{fmtIsk(saveResult.totalValue)}</b></span>
            <span>Method: <b style={{ color: 'var(--accent)' }}>{saveResult.method}</b></span>
            {saveResult.projName && <span>Project: <b style={{ color: 'var(--accent)' }}>{saveResult.projName}</b></span>}
          </div>
          {saveResult.contractNote && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{ fontSize: 11, color: 'var(--text)', whiteSpace: 'nowrap' }}>Contract note:</span>
              <code style={{ flex: 1, fontSize: 11, background: 'var(--surface3)', padding: '5px 10px', borderRadius: 4, color: 'var(--text-white)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {saveResult.contractNote}
              </code>
              <button className="btn btn-ghost btn-sm" onClick={() => navigator.clipboard.writeText(saveResult.contractNote)} style={{ whiteSpace: 'nowrap' }}>
                Copy
              </button>
            </div>
          )}
        </div>
      )}

      {warnings.length > 0 && (
        <div className="warning-box">{warnings.map((w, i) => <div key={i}>⚠ {w}</div>)}</div>
      )}

      {rows.length > 0 && (
        <>
          {/* Global controls */}
          <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 6, padding: '14px 16px', marginBottom: 14 }}>
            <div style={{ display: 'flex', gap: 14, alignItems: 'flex-end', flexWrap: 'wrap' }}>
              <span style={{ fontSize: 13, color: 'var(--text)', alignSelf: 'center' }}>
                {rows.length} items
              </span>

              {/* Project */}
              <div style={{ minWidth: 180 }}>
                <L>Project (all)</L>
                <select value={globalProject} onChange={e => applyGlobalProject(e.target.value)}>
                  <option value="">No project</option>
                  {projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                </select>
              </div>

              {/* Location */}
              <div style={{ minWidth: 210 }}>
                <L>Location (all)</L>
                <SystemSearch value={globalPlace} onChange={applyGlobalPlace} placeholder="Jita, RYC-19…" />
              </div>

              {/* Price method */}
              <div>
                <L>Price</L>
                <div style={{ display: 'flex', gap: 4 }}>
                  {PRICE_METHODS.map(m => (
                    <button key={m} className={`btn btn-sm ${priceMethod === m ? 'btn-primary' : 'btn-ghost'}`} onClick={() => setPriceMethod(m)}>{m}</button>
                  ))}
                </div>
              </div>

              {/* Market */}
              <div style={{ minWidth: 90 }}>
                <L>Market</L>
                <select value={market} onChange={e => setMarket(e.target.value)}>
                  <option value="Jita">Jita</option>
                  <option value="C-J">C-J</option>
                  <option value="Other">Other</option>
                </select>
              </div>

              {(market === 'Jita' || market === 'C-J') && (
                <button className="btn btn-ghost btn-sm" onClick={fetchPrices} disabled={fetchingPrices} style={{ alignSelf: 'flex-end' }}>
                  {fetchingPrices
                    ? `⚡ Fetching ${market}…`
                    : `⚡ ${market} prices`
                  }
                </button>
              )}

              {/* Flow marker */}
              <div>
                <L>Mark as</L>
                <div style={{ display: 'flex', gap: 4 }}>
                  {['input', 'output'].map(f => (
                    <button key={f} className={`btn btn-sm ${flow === f ? 'btn-primary' : 'btn-ghost'}`} onClick={() => setFlow(f)}>
                      {f}
                    </button>
                  ))}
                </div>
              </div>

              <button className="btn btn-primary" onClick={saveAll} disabled={saving} style={{ marginLeft: 'auto', alignSelf: 'flex-end' }}>
                {saving ? 'Saving…' : `💾 Save ${rows.length} items`}
              </button>
            </div>

            {/* Delivery surcharge */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 12, paddingTop: 12, borderTop: '1px solid var(--border)', flexWrap: 'wrap' }}>
              <span style={{ fontSize: 12, color: 'var(--text)' }}>Delivery to add to buy price:</span>
              <label style={{ fontSize: 12, color: 'var(--text)', display: 'flex', alignItems: 'center', gap: 6 }}>
                ISK/m³
                <input type="number" value={deliveryCoef} onChange={e => setDeliveryCoef(e.target.value)} style={{ width: 100 }} />
              </label>
              <button className="btn btn-ghost btn-sm" onClick={applyDelivery}>🚚 Apply delivery</button>
              {deliveryApplied && <span style={{ fontSize: 11, color: '#4caf7d' }}>✓ added {fmtIsk(Number(deliveryCoef))}/m³ to unit prices</span>}
            </div>
          </div>

          {/* Table */}
          <div className="card" style={{ padding: 0, overflowX: 'auto' }}>
            <table>
              <thead>
                <tr>
                  <th>Item</th>
                  <th>Qty</th>
                  <th>Volume</th>
                  <th>Price / unit (ISK)</th>
                  <th>Est. value</th>
                  <th>Location</th>
                  <th>Project</th>
                  <th>Note</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row, i) => (
                  <tr key={i}>
                    <td style={{ whiteSpace: 'nowrap' }}>
                      {row.warning
                        ? <span title={row.warning} style={{ color: '#c8a951' }}>⚠ {row.name}</span>
                        : <span style={{ color: 'var(--text-white)' }}>{row.name}</span>
                      }
                    </td>
                    <td>{row.quantity.toLocaleString()}</td>
                    <td style={{ color: 'var(--text)', fontSize: 12, whiteSpace: 'nowrap' }}>
                      {row.volume_total != null ? fmtVol(row.volume_total) : '—'}
                    </td>
                    <td style={{ minWidth: 140 }}>
                      <input
                        type="number" min="0" step="0.01"
                        value={row.price}
                        onChange={e => updateRow(i, 'price', e.target.value)}
                        placeholder="0"
                      />
                    </td>
                    <td style={{ color: 'var(--accent)', fontSize: 12, whiteSpace: 'nowrap' }}>
                      {row.price ? fmtIsk(Number(row.price) * row.quantity) : '—'}
                    </td>
                    <td style={{ minWidth: 150 }}>
                      <input
                        value={row.place}
                        onChange={e => updateRow(i, 'place', e.target.value)}
                        placeholder="system…"
                      />
                    </td>
                    <td style={{ minWidth: 150 }}>
                      <select value={row.project_id} onChange={e => updateRow(i, 'project_id', e.target.value)}>
                        <option value="">—</option>
                        {projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                      </select>
                    </td>
                    <td style={{ minWidth: 130 }}>
                      <input value={row.note} onChange={e => updateRow(i, 'note', e.target.value)} placeholder="auto…" />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Bottom totals + save */}
          <div style={{ display: 'flex', gap: 16, marginTop: 14, flexWrap: 'wrap', alignItems: 'center' }}>
            <Stat label="Total volume" value={totalVol > 0 ? fmtVol(totalVol) : '—'} />
            <Stat label="Est. total value" value={totalValue > 0 ? fmtIsk(totalValue) : '—'} />
            <button className="btn btn-primary" onClick={saveAll} disabled={saving} style={{ marginLeft: 'auto' }}>
              {saving ? 'Saving…' : `💾 Save ${rows.length} items to inventory`}
            </button>
          </div>
        </>
      )}
    </div>
  )
}

/* ════════════════════════════ DELIVERY ════════════════════════════ */

const JF_SHIPS = [
  { ship: 'Ark',    iso: 'Helium Isotopes' },
  { ship: 'Rhea',   iso: 'Nitrogen Isotopes' },
  { ship: 'Nomad',  iso: 'Hydrogen Isotopes' },
  { ship: 'Anshar', iso: 'Oxygen Isotopes' },
]

const STATUS_STYLE = {
  pending:   { bg: '#2a2410', color: '#c8a951', label: 'PENDING' },
  completed: { bg: '#0e2a1a', color: '#4caf7d', label: 'COMPLETED' },
  failed:    { bg: '#2e1414', color: '#d66', label: 'FAILED' },
}

function DeliveryTab() {
  const [orgs, setOrgs]           = useState([])
  const [projects, setProjects]   = useState([])
  const [chars, setChars]         = useState([])
  const [warehouses, setWarehouses] = useState([])
  const [items, setItems]         = useState([])
  const [deliveries, setDeliveries] = useState([])

  // builder
  const [orgId, setOrgId]         = useState('')
  const [projectId, setProjectId] = useState('')
  const [place, setPlace]         = useState('')
  const [selected, setSelected]   = useState({})        // { item_id: qtyString }
  const [fromSystem, setFromSystem] = useState('')
  const [targetSystem, setTargetSystem] = useState('')
  const [mode, setMode]           = useState('regular') // regular | jf
  const [jumps, setJumps]         = useState('')        // '' = auto via ESI
  const [iskPerJumpM3, setIskPerJumpM3] = useState(1000)
  const [jfShip, setJfShip]       = useState('Ark')
  const [isotopesPerLy, setIsotopesPerLy] = useState(400)
  const [isotopePrice, setIsotopePrice]   = useState(0)
  const [roundTrip, setRoundTrip] = useState(false)
  const [sender, setSender]       = useState('')

  const [calc, setCalc]           = useState(null)
  const [calcing, setCalcing]     = useState(false)
  const [sending, setSending]     = useState(false)
  const [sendResult, setSendResult] = useState(null)
  const [error, setError]         = useState('')

  // ── loaders ──────────────────────────────────────────────
  useEffect(() => {
    get('/organisations').then(async os => {
      setOrgs(os)
      const all = []
      for (const o of os) {
        try { all.push(...(await get(`/projects?org_id=${o.id}`)).map(p => ({ ...p, orgName: o.name }))) } catch {}
      }
      setProjects(all)
    }).catch(() => {})
    get('/organisations/me/characters').then(setChars).catch(() => {})
    loadDeliveries()
  }, [])

  useEffect(() => {
    const url = orgId ? `/deliveries/warehouses?organisation_id=${orgId}` : '/deliveries/warehouses'
    get(url).then(setWarehouses).catch(() => setWarehouses([]))
    setPlace(''); setItems([]); setSelected({})
  }, [orgId])

  useEffect(() => {
    if (!place) { setItems([]); return }
    const p = new URLSearchParams({ place, item_status: 'in_stock' })
    if (orgId) p.set('organisation_id', orgId)
    get(`/inventory?${p}`).then(rows => {
      setItems(rows.filter(r => !r.delivery_id))   // hide lots already in a delivery
      setSelected({})
    }).catch(() => setItems([]))
  }, [place, orgId])

  function loadDeliveries() {
    // sync reconciles pending deliveries against the sender's ESI contracts
    // (finished → auto-complete) and returns the annotated list.
    post('/deliveries/sync').then(setDeliveries)
      .catch(() => get('/deliveries').then(setDeliveries).catch(() => {}))
  }

  // ── selection ────────────────────────────────────────────
  const selectedItems = items.filter(i => selected[i.id] != null)
  const totalVolume = selectedItems.reduce((s, i) => s + (i.volume || 0) * Number(selected[i.id] || 0), 0)
  const totalValue  = selectedItems.reduce((s, i) => s + (i.price  || 0) * Number(selected[i.id] || 0), 0)

  function toggle(item) {
    setSelected(s => {
      const n = { ...s }
      if (n[item.id] != null) delete n[item.id]
      else n[item.id] = item.quantity
      return n
    })
  }
  function setQty(item, v) {
    const q = Math.max(0, Math.min(Number(v) || 0, item.quantity))
    setSelected(s => ({ ...s, [item.id]: q }))
  }

  // ── cost calc (debounced) ────────────────────────────────
  function calcBody() {
    return {
      mode,
      source_system: fromSystem || place,
      target_system: targetSystem,
      total_volume: totalVolume,
      total_value: totalValue,
      jumps: jumps === '' ? null : Number(jumps),
      isk_per_jump_m3: Number(iskPerJumpM3) || 0,
      jf_ship: jfShip,
      isotopes_per_ly: Number(isotopesPerLy) || 0,
      isotope_price: Number(isotopePrice) || 0,
      round_trip: roundTrip,
    }
  }

  useEffect(() => {
    if (totalVolume <= 0 || !targetSystem) { setCalc(null); return }
    setCalcing(true)
    const t = setTimeout(async () => {
      try { setCalc(await post('/deliveries/calc', calcBody())) }
      catch (e) { setError(e.message) }
      finally { setCalcing(false) }
    }, 450)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, fromSystem, targetSystem, totalVolume, jumps, iskPerJumpM3, jfShip, isotopesPerLy, isotopePrice, roundTrip])

  // ── send ─────────────────────────────────────────────────
  async function send() {
    if (selectedItems.length === 0) { setError('Select at least one item'); return }
    if (!targetSystem) { setError('Pick a target system'); return }
    setSending(true); setError('')
    try {
      const d = await post('/deliveries', {
        organisation_id: orgId ? Number(orgId) : null,
        project_id: projectId ? Number(projectId) : null,
        source_place: place || null,
        source_system: fromSystem || place || null,
        target_system: targetSystem,
        target_place: targetSystem,
        mode,
        sender_character: sender || null,
        items: selectedItems.map(i => ({ item_id: i.id, quantity: Number(selected[i.id]) })),
        ...calcBody(),
      })
      setSendResult(d)
      setSelected({}); setCalc(null)
      get(`/inventory?${new URLSearchParams({ place, item_status: 'in_stock', ...(orgId ? { organisation_id: orgId } : {}) })}`)
        .then(rows => setItems(rows.filter(r => !r.delivery_id))).catch(() => {})
      loadDeliveries()
    } catch (e) { setError(e.message) }
    finally { setSending(false) }
  }

  async function setStatus(d, status) {
    const verb = status === 'completed' ? 'mark COMPLETED (items move to target)' : 'mark FAILED (items will be deleted)'
    if (!confirm(`Delivery ${d.code}: ${verb}?`)) return
    try { await patch(`/deliveries/${d.id}/status`, { status }); loadDeliveries() }
    catch (e) { setError(e.message) }
  }
  async function removeDelivery(d) {
    if (!confirm(`Delete delivery ${d.code}?${d.status === 'pending' ? '\nIts items return to the warehouse.' : ''}`)) return
    try { await del(`/deliveries/${d.id}`); loadDeliveries() }
    catch (e) { setError(e.message) }
  }

  const projName = id => projects.find(p => p.id === id)?.name || '—'
  const visibleProjects = orgId ? projects.filter(p => String(p.organisation_id) === String(orgId)) : projects
  const curIso = JF_SHIPS.find(s => s.ship === jfShip)?.iso

  return (
    <div>
      {error && <div className="error-box" role="button" tabIndex={0}
        onClick={() => setError('')}
        onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setError('') } }}>{error}</div>}

      {/* ── BUILDER ── */}
      <div className="card" style={{ marginBottom: 20 }}>
        <div style={{ fontSize: 13, color: 'var(--text-white)', fontWeight: 600, marginBottom: 14 }}>New delivery</div>

        {/* origin */}
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 14 }}>
          <div style={{ minWidth: 170 }}>
            <L>Organisation</L>
            <select value={orgId} onChange={e => setOrgId(e.target.value)}>
              <option value="">All organisations</option>
              {orgs.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
            </select>
          </div>
          <div style={{ minWidth: 170 }}>
            <L>Warehouse (from)</L>
            <select value={place} onChange={e => setPlace(e.target.value)}>
              <option value="">— pick location —</option>
              {warehouses.map(w => <option key={w} value={w}>{w}</option>)}
            </select>
          </div>
          <div style={{ minWidth: 170 }}>
            <L>From system (routing)</L>
            <SystemSearch value={fromSystem} onChange={setFromSystem} placeholder={place || 'origin system…'} />
          </div>
          <div style={{ minWidth: 170 }}>
            <L>Project (optional)</L>
            <select value={projectId} onChange={e => setProjectId(e.target.value)}>
              <option value="">No project</option>
              {visibleProjects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </div>
        </div>

        {/* items */}
        {place && (
          items.length === 0
            ? <div className="empty-state" style={{ padding: 14 }}>No shippable items at this location</div>
            : (
              <div className="card" style={{ padding: 0, overflowX: 'auto', marginBottom: 14 }}>
                <table>
                  <thead><tr><th></th><th>Item</th><th>Available</th><th>Ship qty</th><th>Vol/unit</th><th>Volume</th><th>Value</th></tr></thead>
                  <tbody>
                    {items.map(i => {
                      const on = selected[i.id] != null
                      const q = Number(selected[i.id] || 0)
                      return (
                        <tr key={i.id} style={{ background: on ? 'var(--surface2)' : '' }}>
                          <td><input type="checkbox" checked={on} onChange={() => toggle(i)} /></td>
                          <td style={{ color: 'var(--text-white)', whiteSpace: 'nowrap' }}>{i.name}</td>
                          <td>{i.quantity.toLocaleString()}</td>
                          <td style={{ minWidth: 110 }}>
                            <input type="number" min="0" max={i.quantity} value={on ? q : ''} disabled={!on}
                              onChange={e => setQty(i, e.target.value)} placeholder="—" style={{ width: 100 }} />
                          </td>
                          <td style={{ color: 'var(--text)', fontSize: 12 }}>{i.volume != null ? i.volume + ' m³' : '—'}</td>
                          <td style={{ color: 'var(--text)', fontSize: 12 }}>{on && i.volume ? fmtVol(i.volume * q) : '—'}</td>
                          <td style={{ color: 'var(--accent)', fontSize: 12 }}>{on && i.price ? fmtIsk(i.price * q) : '—'}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )
        )}

        {/* destination + mode */}
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-end', marginBottom: 14 }}>
          <div style={{ minWidth: 200 }}>
            <L>Target system</L>
            <SystemSearch value={targetSystem} onChange={setTargetSystem} placeholder="destination…" />
          </div>
          <div>
            <L>Mode</L>
            <div style={{ display: 'flex', gap: 4 }}>
              {['regular', 'jf'].map(m => (
                <button key={m} className={`btn btn-sm ${mode === m ? 'btn-primary' : 'btn-ghost'}`} onClick={() => setMode(m)}>
                  {m === 'jf' ? 'Jump Freighter' : 'Regular'}
                </button>
              ))}
            </div>
          </div>
          <div style={{ minWidth: 180 }}>
            <L>Sender character</L>
            {chars.length > 0
              ? <select value={sender} onChange={e => setSender(e.target.value)}>
                  <option value="">— none —</option>
                  {chars.map(c => <option key={c.id} value={c.name}>{c.name}</option>)}
                </select>
              : <input value={sender} onChange={e => setSender(e.target.value)} placeholder="character name…" />}
          </div>
        </div>

        {/* mode params */}
        <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', alignItems: 'flex-end', paddingTop: 12, borderTop: '1px solid var(--border)' }}>
          {mode === 'regular' ? (
            <>
              <div style={{ width: 130 }}>
                <L>Jumps (blank = auto)</L>
                <input type="number" min="0" value={jumps} onChange={e => setJumps(e.target.value)}
                  placeholder={calc?.jumps_auto ? `auto ${calc.jumps}` : 'auto'} />
              </div>
              <div style={{ width: 140 }}>
                <L>ISK / jump / m³</L>
                <input type="number" min="0" value={iskPerJumpM3} onChange={e => setIskPerJumpM3(e.target.value)} />
              </div>
            </>
          ) : (
            <>
              <div style={{ width: 150 }}>
                <L>Jump freighter</L>
                <select value={jfShip} onChange={e => setJfShip(e.target.value)}>
                  {JF_SHIPS.map(s => <option key={s.ship} value={s.ship}>{s.ship}</option>)}
                </select>
              </div>
              <div style={{ alignSelf: 'center', fontSize: 12, color: 'var(--text)' }}>
                fuel: <b style={{ color: 'var(--accent)' }}>{curIso}</b>
              </div>
              <div style={{ width: 120 }}>
                <L>Isotopes / ly</L>
                <input type="number" min="0" value={isotopesPerLy} onChange={e => setIsotopesPerLy(e.target.value)} />
              </div>
              <div style={{ width: 140 }}>
                <L>Isotope price (ISK)</L>
                <input type="number" min="0" value={isotopePrice} onChange={e => setIsotopePrice(e.target.value)} />
              </div>
              <label style={{ fontSize: 12, color: 'var(--text)', display: 'flex', alignItems: 'center', gap: 6, alignSelf: 'center' }}>
                <input type="checkbox" checked={roundTrip} onChange={e => setRoundTrip(e.target.checked)} /> round trip
              </label>
            </>
          )}
        </div>

        {/* summary + send */}
        <div style={{ display: 'flex', gap: 14, marginTop: 16, flexWrap: 'wrap', alignItems: 'center' }}>
          <Stat label="Items" value={selectedItems.length} />
          <Stat label="Volume" value={totalVolume > 0 ? fmtVol(totalVolume) : '—'} />
          <Stat label="Collateral" value={totalValue > 0 ? fmtIsk(totalValue) : '—'} />
          {mode === 'jf' && calc && <Stat label="Light years" value={calc.light_years ?? '—'} />}
          {mode === 'jf' && calc && <Stat label="Trips / isotopes" value={`${calc.trips ?? 0} / ${(calc.total_isotopes ?? 0).toLocaleString()}`} />}
          {mode === 'regular' && calc && <Stat label="Jumps" value={calc.jumps ?? '—'} />}
          <Stat label="Ship cost" value={calcing ? '…' : calc ? `${fmtIsk(calc.est_cost)} (${fmtIsk(calc.cost_per_m3)}/m³)` : '—'} />
          <button className="btn btn-primary" onClick={send} disabled={sending || selectedItems.length === 0 || !targetSystem} style={{ marginLeft: 'auto' }}>
            {sending ? 'Sending…' : '📦 Send to pending'}
          </button>
        </div>
        {calc?.warnings?.length > 0 && (
          <div className="warning-box" style={{ marginTop: 10 }}>{calc.warnings.map((w, i) => <div key={i}>⚠ {w}</div>)}</div>
        )}
      </div>

      {/* send result */}
      {sendResult && (
        <div style={{ background: '#0e2a1a', border: '1px solid #2e6b44', borderRadius: 6, padding: '14px 18px', marginBottom: 16 }}>
          <div style={{ color: '#4caf7d', fontWeight: 600, fontSize: 14, marginBottom: 8 }}>
            ✓ Delivery {sendResult.code} created — pending
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontSize: 11, color: 'var(--text)', whiteSpace: 'nowrap' }}>Contract comment:</span>
            <code style={{ flex: 1, fontSize: 11, background: 'var(--surface3)', padding: '5px 10px', borderRadius: 4, color: 'var(--text-white)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {sendResult.comment}
            </code>
            <button className="btn btn-ghost btn-sm" onClick={() => navigator.clipboard.writeText(sendResult.comment)}>Copy</button>
            <button className="btn btn-ghost btn-sm" onClick={() => setSendResult(null)}>✕</button>
          </div>
        </div>
      )}

      {/* ── DELIVERIES TABLE ── */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
        <h3 style={{ margin: 0, fontSize: 15, color: 'var(--text-white)' }}>Deliveries</h3>
        <button className="btn btn-ghost btn-sm" onClick={loadDeliveries}>Refresh</button>
      </div>
      {deliveries.length === 0
        ? <div className="empty-state">No deliveries yet</div>
        : (
          <div className="card" style={{ padding: 0, overflowX: 'auto' }}>
            <table>
              <thead>
                <tr>
                  <th>Code</th><th>Status</th><th>Mode</th><th>Project</th><th>Target</th>
                  <th>Volume</th><th>Collateral</th><th>Ship cost</th><th>Items</th><th></th>
                </tr>
              </thead>
              <tbody>
                {deliveries.map(d => {
                  const st = STATUS_STYLE[d.status] || STATUS_STYLE.pending
                  return (
                    <tr key={d.id}>
                      <td style={{ color: 'var(--text-white)', fontFamily: 'monospace', fontSize: 12 }}>{d.code}</td>
                      <td style={{ whiteSpace: 'nowrap' }}>
                        <span style={{ fontSize: 10, fontWeight: 700, padding: '2px 6px', borderRadius: 3, background: st.bg, color: st.color }}>{st.label}</span>
                        {d.tracked && (
                          <span title={d.contract_status ? `contract: ${d.contract_status}` : 'ESI contract found'}
                            style={{ marginLeft: 6, fontSize: 9, fontWeight: 700, padding: '2px 5px', borderRadius: 3, background: '#10243d', color: '#3a9bd6' }}>
                            🔗 TRACKED
                          </span>
                        )}
                      </td>
                      <td style={{ fontSize: 12 }}>{d.mode === 'jf' ? `JF ${d.jf_ship || ''}` : 'Regular'}</td>
                      <td style={{ color: 'var(--text)', fontSize: 12 }}>{projName(d.project_id)}</td>
                      <td style={{ color: 'var(--text)', fontSize: 12 }}>{d.target_system || '—'}</td>
                      <td style={{ color: 'var(--text)', fontSize: 12 }}>{d.total_volume ? fmtVol(d.total_volume) : '—'}</td>
                      <td style={{ color: 'var(--text)', fontSize: 12 }}>{d.total_value ? fmtIsk(d.total_value) : '—'}</td>
                      <td style={{ color: 'var(--accent)', fontSize: 12 }}>{d.est_cost ? fmtIsk(d.est_cost) : '—'}</td>
                      <td style={{ color: 'var(--text)', fontSize: 12 }}>{(d.items_snapshot || []).length}</td>
                      <td style={{ whiteSpace: 'nowrap' }}>
                        {d.status === 'pending' && (
                          <>
                            <button className="btn btn-ghost btn-sm" title="Mark completed" onClick={() => setStatus(d, 'completed')} style={{ marginRight: 3, padding: '3px 7px' }}>✅</button>
                            <button className="btn btn-ghost btn-sm" title="Mark failed" onClick={() => setStatus(d, 'failed')} style={{ marginRight: 3, padding: '3px 7px' }}>❌</button>
                          </>
                        )}
                        <button className="btn btn-ghost btn-sm" title="Copy comment" onClick={() => navigator.clipboard.writeText(d.comment || '')} style={{ marginRight: 3, padding: '3px 7px' }}>📋</button>
                        <button className="btn btn-danger btn-sm" title="Delete" onClick={() => removeDelivery(d)}>✕</button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )
      }
    </div>
  )
}

/* ─── UI helpers ──────────────────────────────────────────── */

function Stat({ label, value }) {
  return (
    <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 6, padding: '8px 16px' }}>
      <div style={{ fontSize: 11, color: 'var(--text)', marginBottom: 2 }}>{label}</div>
      <div style={{ color: 'var(--text-white)', fontWeight: 500 }}>{value}</div>
    </div>
  )
}

function L({ children }) {
  return <label style={{ display: 'block', fontSize: 11, color: 'var(--text)', marginBottom: 5 }}>{children}</label>
}

function fmtVol(v) {
  if (!v) return '—'
  if (v >= 1e6) return (v / 1e6).toFixed(2) + ' M m³'
  if (v >= 1000) return (v / 1000).toFixed(1) + ' k m³'
  return v.toFixed(1) + ' m³'
}

function fmtIsk(v) {
  if (!v) return '—'
  const n = Number(v)
  if (n >= 1e9) return (n / 1e9).toFixed(2) + ' B ISK'
  if (n >= 1e6) return (n / 1e6).toFixed(2) + ' M ISK'
  return n.toLocaleString(undefined, { maximumFractionDigits: 0 }) + ' ISK'
}
