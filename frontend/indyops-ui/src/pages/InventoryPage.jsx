import { useState, useEffect } from 'react'
import { get, post, del } from '../api/client'
import SystemSearch from '../components/SystemSearch'

const PRICE_METHODS = ['Buy', 'Split', 'Sell']

export default function InventoryPage() {
  const [tab, setTab] = useState(0)
  return (
    <div>
      <h2 style={{ marginBottom: 20 }}>Inventory</h2>
      <div className="tabs">
        {['Warehouse', 'Parse & Import'].map((t, i) => (
          <button key={i} className={`tab-btn ${tab === i ? 'active' : ''}`} onClick={() => setTab(i)}>{t}</button>
        ))}
      </div>
      {tab === 0 ? <WarehouseTab /> : <ParseTab />}
    </div>
  )
}

/* ════════════════════════════ WAREHOUSE ════════════════════════════ */

function WarehouseTab() {
  const [items, setItems]       = useState([])
  const [projects, setProjects] = useState([])
  const [filter, setFilter]     = useState({ project_id: '', place: '' })
  const [error, setError]       = useState('')
  const [clearing, setClearing] = useState(false)

  async function load() {
    const p = new URLSearchParams()
    if (filter.project_id) p.set('project_id', filter.project_id)
    if (filter.place)      p.set('place', filter.place)
    try { setItems(await get(`/inventory?${p}`)) } catch {}
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

  useEffect(() => { load() }, [filter])

  async function remove(id) {
    if (!confirm('Delete item?')) return
    try { await del(`/inventory/${id}`); load() } catch {}
  }

  async function clearProject() {
    const proj = projects.find(p => String(p.id) === filter.project_id)
    if (!confirm(`Clear ALL items in project "${proj?.name}"?\nCannot be undone.`)) return
    setClearing(true); setError('')
    try { await del(`/inventory?project_id=${filter.project_id}`); load() }
    catch (e) { setError(e.message) }
    finally { setClearing(false) }
  }

  async function clearAll() {
    if (!confirm(`Delete ALL ${items.length} items from warehouse?\nCannot be undone.`)) return
    setClearing(true); setError('')
    try { await del('/inventory'); load() }
    catch (e) { setError(e.message) }
    finally { setClearing(false) }
  }

  const totalValue = items.reduce((s, i) => s + (i.price ?? 0) * i.quantity, 0)
  const totalVol   = items.reduce((s, i) => s + (i.volume ?? 0) * i.quantity, 0)

  return (
    <div>
      {error && <div className="error-box">{error}</div>}
      <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap', alignItems: 'flex-end' }}>
        <select value={filter.project_id} onChange={e => setFilter(f => ({ ...f, project_id: e.target.value }))} style={{ width: 200 }}>
          <option value="">All projects</option>
          {projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
        <input value={filter.place} onChange={e => setFilter(f => ({ ...f, place: e.target.value }))} placeholder="Filter by system…" style={{ width: 180 }} />
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
              <Stat label="Items" value={items.length} />
              <Stat label="Total volume" value={totalVol > 0 ? fmtVol(totalVol) : '—'} />
              <Stat label="Total value" value={totalValue > 0 ? fmtIsk(totalValue) : '—'} />
            </div>
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
                      <td style={{ color: 'var(--text-white)', whiteSpace: 'nowrap' }}>{item.name}</td>
                      <td>{item.quantity.toLocaleString()}</td>
                      <td style={{ color: 'var(--text)' }}>{item.volume != null ? item.volume + ' m³' : '—'}</td>
                      <td>{item.price ? fmtIsk(item.price) : '—'}</td>
                      <td style={{ color: 'var(--accent)' }}>{item.price ? fmtIsk(item.price * item.quantity) : '—'}</td>
                      <td style={{ color: 'var(--text)', fontSize: 12 }}>{item.place || '—'}</td>
                      <td style={{ color: 'var(--text)', fontSize: 12 }}>{projects.find(p => p.id === item.project_id)?.name || '—'}</td>
                      <td style={{ color: 'var(--text)', fontSize: 12, maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis' }}>{item.note || '—'}</td>
                      <td><button className="btn btn-danger btn-sm" onClick={() => remove(item.id)}>✕</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
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
          const buy  = parseFloat(p.buy.max)
          const sell = parseFloat(p.sell.min)
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
            <label style={{ display: 'block', fontSize: 12, color: 'var(--text)', marginBottom: 6 }}>
              Paste from EVE inventory (Name ⇥ Qty or Qty ⇥ Name, one per line)
            </label>
            <textarea
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

              <button className="btn btn-primary" onClick={saveAll} disabled={saving} style={{ marginLeft: 'auto', alignSelf: 'flex-end' }}>
                {saving ? 'Saving…' : `💾 Save ${rows.length} items`}
              </button>
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
