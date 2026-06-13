import { useState, useEffect } from 'react'
import { get, post, del } from '../api/client'
import SystemSearch from '../components/SystemSearch'

const TABS = ['Warehouse', 'Parse & Import']

export default function InventoryPage() {
  const [tab, setTab] = useState(0)

  return (
    <div>
      <h2 style={{ marginBottom: 20 }}>Inventory</h2>
      <div className="tabs">
        {TABS.map((t, i) => (
          <button key={i} className={`tab-btn ${tab === i ? 'active' : ''}`} onClick={() => setTab(i)}>
            {t}
          </button>
        ))}
      </div>
      {tab === 0 ? <WarehouseTab /> : <ParseTab />}
    </div>
  )
}

/* ─────────────────────────── WAREHOUSE TAB ─────────────────────────── */

function WarehouseTab() {
  const [items, setItems]     = useState([])
  const [projects, setProjects] = useState([])
  const [filter, setFilter]   = useState({ project_id: '', place: '' })

  async function load() {
    const params = new URLSearchParams()
    if (filter.project_id) params.set('project_id', filter.project_id)
    if (filter.place)      params.set('place', filter.place)
    try {
      const data = await get(`/inventory?${params}`)
      setItems(data)
    } catch {}
  }

  useEffect(() => {
    get('/organisations').then(async orgs => {
      const all = []
      for (const o of orgs) {
        try {
          const ps = await get(`/projects?org_id=${o.id}`)
          all.push(...ps.map(p => ({ ...p, orgName: o.name })))
        } catch {}
      }
      setProjects(all)
    }).catch(() => {})
  }, [])

  useEffect(() => { load() }, [filter])

  async function remove(id) {
    if (!confirm('Delete item?')) return
    try { await del(`/inventory/${id}`); load() } catch {}
  }

  function fmtPrice(p) {
    if (p == null) return '—'
    return p >= 1e9
      ? (p / 1e9).toFixed(2) + ' B'
      : p >= 1e6
        ? (p / 1e6).toFixed(2) + ' M'
        : p.toLocaleString()
  }

  const totalValue = items.reduce((s, i) => s + (i.price ?? 0) * i.quantity, 0)
  const totalVol   = items.reduce((s, i) => s + (i.volume ?? 0) * i.quantity, 0)

  return (
    <div>
      {/* filters */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
        <select
          value={filter.project_id}
          onChange={e => setFilter(f => ({ ...f, project_id: e.target.value }))}
          style={{ width: 200 }}
        >
          <option value="">All projects</option>
          {projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
        <input
          value={filter.place}
          onChange={e => setFilter(f => ({ ...f, place: e.target.value }))}
          placeholder="Filter by system…"
          style={{ width: 180 }}
        />
        <button className="btn btn-ghost btn-sm" onClick={load}>Refresh</button>
      </div>

      {items.length === 0
        ? <div className="empty-state">No items in inventory</div>
        : (
          <>
            <div style={{ display: 'flex', gap: 24, marginBottom: 12, fontSize: 13 }}>
              <Stat label="Items" value={items.length} />
              <Stat label="Total volume" value={totalVol.toFixed(1) + ' m³'} />
              <Stat label="Total value" value={fmtPrice(totalValue) + ' ISK'} />
            </div>
            <div className="card" style={{ padding: 0, overflowX: 'auto' }}>
              <table>
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Qty</th>
                    <th>Vol/unit</th>
                    <th>Price/unit</th>
                    <th>Total value</th>
                    <th>Location</th>
                    <th>Project</th>
                    <th>Note</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {items.map(item => (
                    <tr key={item.id}>
                      <td style={{ color: 'var(--text-white)', whiteSpace: 'nowrap' }}>{item.name}</td>
                      <td>{item.quantity.toLocaleString()}</td>
                      <td style={{ color: 'var(--text)' }}>
                        {item.volume != null ? item.volume + ' m³' : '—'}
                      </td>
                      <td>{fmtPrice(item.price)} ISK</td>
                      <td style={{ color: 'var(--accent)' }}>
                        {item.price ? fmtPrice(item.price * item.quantity) + ' ISK' : '—'}
                      </td>
                      <td style={{ color: 'var(--text)', fontSize: 12 }}>{item.place || '—'}</td>
                      <td style={{ color: 'var(--text)', fontSize: 12 }}>
                        {projects.find(p => p.id === item.project_id)?.name || '—'}
                      </td>
                      <td style={{ color: 'var(--text)', fontSize: 12, maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                        {item.note || '—'}
                      </td>
                      <td>
                        <button className="btn btn-danger btn-sm" onClick={() => remove(item.id)}>✕</button>
                      </td>
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

function Stat({ label, value }) {
  return (
    <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 6, padding: '8px 16px' }}>
      <div style={{ fontSize: 11, color: 'var(--text)', marginBottom: 2 }}>{label}</div>
      <div style={{ color: 'var(--text-white)', fontWeight: 500 }}>{value}</div>
    </div>
  )
}

/* ─────────────────────────── PARSE TAB ─────────────────────────── */

function ParseTab() {
  const [rawText, setRawText]   = useState('')
  const [rows, setRows]         = useState([])   // editable preview rows
  const [projects, setProjects] = useState([])
  const [globalProject, setGlobalProject] = useState('')
  const [warnings, setWarnings] = useState([])
  const [saving, setSaving]     = useState(false)
  const [saved, setSaved]       = useState(false)
  const [error, setError]       = useState('')
  const [parsing, setParsing]   = useState(false)

  useEffect(() => {
    get('/organisations').then(async orgs => {
      const all = []
      for (const o of orgs) {
        try {
          const ps = await get(`/projects?org_id=${o.id}`)
          all.push(...ps.map(p => ({ ...p, orgName: o.name })))
        } catch {}
      }
      setProjects(all)
    }).catch(() => {})
  }, [])

  async function parse() {
    if (!rawText.trim()) return
    setParsing(true)
    setError('')
    setSaved(false)
    try {
      const res = await post('/inventory/preview', { text: rawText })
      setWarnings(res.warnings)
      setRows(res.items.map(item => ({
        ...item,
        price: '',
        place: '',
        note: '',
        project_id: globalProject,
      })))
    } catch (err) {
      setError(err.message)
    } finally {
      setParsing(false)
    }
  }

  function updateRow(i, key, val) {
    setRows(r => r.map((row, idx) => idx === i ? { ...row, [key]: val } : row))
  }

  async function saveAll() {
    setSaving(true)
    setError('')
    try {
      await post('/inventory/batch', {
        items: rows.map(r => ({
          eve_type_id: r.eve_type_id || null,
          name: r.name,
          quantity: r.quantity,
          volume: r.volume || null,
          price: r.price !== '' ? Number(r.price) : null,
          place: r.place || null,
          note: r.note || null,
          project_id: r.project_id ? Number(r.project_id) : null,
        })),
      })
      setSaved(true)
      setRows([])
      setRawText('')
      setWarnings([])
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  function applyGlobalProject(pid) {
    setGlobalProject(pid)
    setRows(r => r.map(row => ({ ...row, project_id: pid })))
  }

  function fmtVol(row) {
    if (!row.volume_total) return '—'
    return row.volume_total >= 1000
      ? (row.volume_total / 1000).toFixed(1) + ' k m³'
      : row.volume_total.toFixed(1) + ' m³'
  }

  return (
    <div>
      {/* input area */}
      <div className="card" style={{ marginBottom: 20 }}>
        <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
          <div style={{ flex: 1 }}>
            <label style={{ display: 'block', fontSize: 12, color: 'var(--text)', marginBottom: 6 }}>
              Paste from EVE inventory (Name ⇥ Quantity, one per line)
            </label>
            <textarea
              value={rawText}
              onChange={e => setRawText(e.target.value)}
              placeholder={'Water\t3040\nSynthetic Synapses\t6'}
              rows={6}
              style={{ fontFamily: 'monospace', fontSize: 13 }}
            />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, paddingTop: 22 }}>
            <button className="btn btn-primary" onClick={parse} disabled={parsing || !rawText.trim()}>
              {parsing ? 'Parsing…' : '▶ Parse'}
            </button>
            <button className="btn btn-ghost btn-sm" onClick={() => { setRawText(''); setRows([]); setWarnings([]) }}>
              Clear
            </button>
          </div>
        </div>
      </div>

      {error && <div className="error-box">{error}</div>}
      {saved && (
        <div style={{ background: '#0e2a1a', border: '1px solid var(--success)', borderRadius: 4, padding: '10px 14px', marginBottom: 12, fontSize: 13, color: '#4caf7d' }}>
          ✓ {rows.length === 0 ? 'Items saved to inventory.' : ''}
        </div>
      )}

      {warnings.length > 0 && (
        <div className="warning-box">
          {warnings.map((w, i) => <div key={i}>⚠ {w}</div>)}
        </div>
      )}

      {rows.length > 0 && (
        <>
          {/* global controls */}
          <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 14, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 13, color: 'var(--text)' }}>
              {rows.length} items resolved — fill in details below:
            </span>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 12, color: 'var(--text)', whiteSpace: 'nowrap' }}>Apply project to all:</span>
              <select value={globalProject} onChange={e => applyGlobalProject(e.target.value)} style={{ width: 200 }}>
                <option value="">No project</option>
                {projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            </div>
            <button className="btn btn-primary" onClick={saveAll} disabled={saving} style={{ marginLeft: 'auto' }}>
              {saving ? 'Saving…' : `💾 Save ${rows.length} items`}
            </button>
          </div>

          <div className="card" style={{ padding: 0, overflowX: 'auto' }}>
            <table>
              <thead>
                <tr>
                  <th>Item</th>
                  <th>Qty</th>
                  <th>Volume</th>
                  <th>Price / unit (ISK)</th>
                  <th>Est. value</th>
                  <th>Location (system)</th>
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
                    <td style={{ color: 'var(--text)', fontSize: 12, whiteSpace: 'nowrap' }}>{fmtVol(row)}</td>
                    <td style={{ minWidth: 140 }}>
                      <input
                        type="number"
                        min="0"
                        step="0.01"
                        value={row.price}
                        onChange={e => updateRow(i, 'price', e.target.value)}
                        placeholder="0"
                      />
                    </td>
                    <td style={{ color: 'var(--accent)', fontSize: 12, whiteSpace: 'nowrap' }}>
                      {row.price
                        ? fmtIsk(Number(row.price) * row.quantity)
                        : '—'
                      }
                    </td>
                    <td style={{ minWidth: 180 }}>
                      <SystemSearch
                        value={row.place}
                        onChange={val => updateRow(i, 'place', val)}
                        placeholder="Jita, Amarr…"
                      />
                    </td>
                    <td style={{ minWidth: 160 }}>
                      <select
                        value={row.project_id}
                        onChange={e => updateRow(i, 'project_id', e.target.value)}
                      >
                        <option value="">—</option>
                        {projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                      </select>
                    </td>
                    <td style={{ minWidth: 140 }}>
                      <input
                        value={row.note}
                        onChange={e => updateRow(i, 'note', e.target.value)}
                        placeholder="Note…"
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div style={{ marginTop: 14, display: 'flex', justifyContent: 'flex-end' }}>
            <button className="btn btn-primary" onClick={saveAll} disabled={saving}>
              {saving ? 'Saving…' : `💾 Save ${rows.length} items to inventory`}
            </button>
          </div>
        </>
      )}
    </div>
  )
}

function fmtIsk(v) {
  if (v >= 1e9) return (v / 1e9).toFixed(2) + ' B ISK'
  if (v >= 1e6) return (v / 1e6).toFixed(2) + ' M ISK'
  return v.toLocaleString() + ' ISK'
}
