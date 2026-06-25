// Reprocess warehouse ore into minerals using a saved preset (base yield / rigs / tax /
// skills), carrying the ore's cost basis onto the minerals. The resulting "reprocess" lots
// feed the Industry cost ledger, so building with your own ore no longer reads "missing
// inputs". Rendered inside the Tracking → Industry tab.
import { useState, useEffect, useCallback } from 'react'
import { get, post, put, del } from '../../api/client'
import { fmtIsk, fmtInt, GREEN, RED } from './fmt'

const BLANK = {
  name: '', base_yield: 0.5, tax_pct: 0, security: 'hi',
  reprocessing_lvl: 5, efficiency_lvl: 5, ore_specific_lvl: 4, implant_pct: 0, rig_type_ids: [],
}
const numStyle = { width: 64, padding: '5px 6px' }

export default function ReprocessPanel({ onReprocessed }) {
  const [presets, setPresets] = useState([])
  const [rigs, setRigs] = useState([])
  const [stock, setStock] = useState([])
  const [presetId, setPresetId] = useState(null)
  const [sel, setSel] = useState({})
  const [basis, setBasis] = useState('sell')
  const [result, setResult] = useState(null)
  const [editing, setEditing] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  const loadPresets = useCallback(() => get('/inventory/reprocessing/presets').then(setPresets).catch(() => {}), [])
  const loadStock = useCallback(() => get('/inventory/reprocessing/stock').then(setStock).catch(() => {}), [])
  useEffect(() => {
    loadPresets(); loadStock()
    get('/ore/rigs').then(d => setRigs(d.rigs || [])).catch(() => {})
  }, [loadPresets, loadStock])

  // default to the first preset until the user explicitly picks one (no state-in-effect)
  const activePresetId = presetId ?? (presets[0]?.id ?? null)
  const selectedIds = stock.filter(i => sel[i.id]).map(i => i.id)
  const setField = (k, v) => setEditing(e => ({ ...e, [k]: v }))
  const toggleRig = rid => setEditing(e => ({
    ...e, rig_type_ids: e.rig_type_ids.includes(rid) ? e.rig_type_ids.filter(x => x !== rid) : [...e.rig_type_ids, rid],
  }))

  async function doReprocess() {
    setErr(''); setResult(null); setBusy(true)
    try {
      const r = await post('/inventory/reprocessing/reprocess', { preset_id: activePresetId, item_ids: selectedIds, basis })
      setResult(r); setSel({}); loadStock()
      if (onReprocessed) onReprocessed()
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }

  async function savePreset() {
    setErr('')
    try {
      if (editing.id) await put(`/inventory/reprocessing/presets/${editing.id}`, editing)
      else await post('/inventory/reprocessing/presets', editing)
      setEditing(null); loadPresets()
    } catch (e) { setErr(e.message) }
  }
  async function removePreset(id) {
    setErr('')
    try { await del(`/inventory/reprocessing/presets/${id}`); if (presetId === id) setPresetId(null); loadPresets() }
    catch (e) { setErr(e.message) }
  }

  return (
    <div className="card" style={{ marginTop: 22 }}>
      <div className="sec-label" style={{ marginBottom: 10 }}>Reprocess warehouse ore → minerals</div>

      {/* preset row */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
        <span style={{ fontSize: 12, color: 'var(--text)' }}>Preset</span>
        <select value={activePresetId || ''} onChange={e => setPresetId(Number(e.target.value) || null)} style={{ padding: '6px 8px', minWidth: 160 }}>
          {!presets.length && <option value="">No presets yet</option>}
          {presets.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
        <button className="btn btn-ghost btn-sm" onClick={() => setEditing({ ...BLANK })}>+ New</button>
        {activePresetId && <button className="btn btn-ghost btn-sm" onClick={() => setEditing({ ...presets.find(p => p.id === activePresetId) })}>Edit</button>}
        {activePresetId && <button className="btn btn-ghost btn-sm" onClick={() => removePreset(activePresetId)} title="Delete preset">✕</button>}
        <span style={{ flex: 1 }} />
        <span style={{ fontSize: 12, color: 'var(--text)' }}>Jita basis</span>
        <select value={basis} onChange={e => setBasis(e.target.value)} style={{ padding: '6px 8px' }}>
          <option value="sell">sell</option><option value="buy">buy</option><option value="split">split</option>
        </select>
      </div>

      {/* preset editor */}
      {editing && (
        <div className="card" style={{ marginBottom: 12, background: 'var(--bg)' }}>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginBottom: 10 }}>
            <input placeholder="Preset name" value={editing.name} onChange={e => setField('name', e.target.value)} style={{ padding: '6px 8px', minWidth: 180 }} />
            <label style={{ fontSize: 12 }}>Base yield <input type="number" step="0.01" min="0" max="1" value={editing.base_yield} onChange={e => setField('base_yield', Number(e.target.value))} style={numStyle} /></label>
            <label style={{ fontSize: 12 }}>Tax % <input type="number" step="0.1" min="0" value={editing.tax_pct} onChange={e => setField('tax_pct', Number(e.target.value))} style={numStyle} /></label>
            <label style={{ fontSize: 12 }}>Security
              <select value={editing.security} onChange={e => setField('security', e.target.value)} style={{ marginLeft: 4, padding: '5px 6px' }}>
                <option value="hi">hi</option><option value="low">low</option><option value="null">null</option>
              </select>
            </label>
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginBottom: 10 }}>
            <label style={{ fontSize: 12 }}>Reprocessing <input type="number" min="0" max="5" value={editing.reprocessing_lvl} onChange={e => setField('reprocessing_lvl', Number(e.target.value))} style={numStyle} /></label>
            <label style={{ fontSize: 12 }}>Efficiency <input type="number" min="0" max="5" value={editing.efficiency_lvl} onChange={e => setField('efficiency_lvl', Number(e.target.value))} style={numStyle} /></label>
            <label style={{ fontSize: 12 }}>Ore-specific <input type="number" min="0" max="5" value={editing.ore_specific_lvl} onChange={e => setField('ore_specific_lvl', Number(e.target.value))} style={numStyle} /></label>
            <label style={{ fontSize: 12 }}>Implant % <input type="number" min="0" step="1" value={editing.implant_pct} onChange={e => setField('implant_pct', Number(e.target.value))} style={numStyle} /></label>
          </div>
          {rigs.length > 0 && (
            <div style={{ marginBottom: 10 }}>
              <div style={{ fontSize: 11, color: 'var(--text)', marginBottom: 4 }}>Yield rigs</div>
              <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
                {rigs.map(r => (
                  <label key={r.type_id} style={{ fontSize: 12, display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                    <input type="checkbox" checked={editing.rig_type_ids.includes(r.type_id)} onChange={() => toggleRig(r.type_id)} />
                    {r.name} (+{r.yield_bonus}%)
                  </label>
                ))}
              </div>
            </div>
          )}
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="btn btn-sm" onClick={savePreset} disabled={!editing.name.trim()}>Save preset</button>
            <button className="btn btn-ghost btn-sm" onClick={() => setEditing(null)}>Cancel</button>
          </div>
        </div>
      )}

      {/* ore picker */}
      {stock.length === 0 ? (
        <div className="empty-state" style={{ padding: '18px 12px' }}>
          No ore in your warehouse. Add ore to inventory first — then reprocess it here.
        </div>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table>
            <thead><tr><th /><th>Ore</th><th style={{ textAlign: 'right' }}>Quantity</th><th style={{ textAlign: 'right' }}>Unit cost</th><th>Place</th></tr></thead>
            <tbody>
              {stock.map(i => (
                <tr key={i.id}>
                  <td><input type="checkbox" checked={!!sel[i.id]} onChange={() => setSel(s => ({ ...s, [i.id]: !s[i.id] }))} /></td>
                  <td>{i.name}</td>
                  <td style={{ textAlign: 'right' }}>{fmtInt(i.quantity)}</td>
                  <td style={{ textAlign: 'right' }}>{i.price == null ? '—' : fmtIsk(i.price)}</td>
                  <td>{i.place || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 12 }}>
        <button className="btn btn-sm" onClick={doReprocess} disabled={busy || !activePresetId || !selectedIds.length}>
          {busy ? 'Reprocessing…' : `Reprocess ${selectedIds.length || ''} lot(s)`}
        </button>
        {err && <span style={{ fontSize: 12, color: RED }}>{err}</span>}
      </div>

      {/* result */}
      {result && (
        <div className="card" style={{ marginTop: 12, background: 'var(--bg)' }}>
          <div style={{ fontSize: 12, color: 'var(--text-bright)', marginBottom: 8 }}>
            Refined via <b>{result.preset}</b> at {(result.effective_yield * 100).toFixed(1)}% yield · ore cost {fmtIsk(result.ore_cost)} ·
            mineral value <span style={{ color: GREEN }}>{fmtIsk(result.total_value)}</span>
            {result.skipped?.length ? <span style={{ color: 'var(--text)' }}> · skipped (under one batch): {result.skipped.join(', ')}</span> : null}
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table>
              <thead><tr><th>Mineral</th><th style={{ textAlign: 'right' }}>Quantity</th><th style={{ textAlign: 'right' }}>Unit cost</th><th style={{ textAlign: 'right' }}>Jita value</th></tr></thead>
              <tbody>
                {result.minerals.map(mn => (
                  <tr key={mn.type_id}>
                    <td>{mn.name}</td>
                    <td style={{ textAlign: 'right' }}>{fmtInt(mn.quantity)}</td>
                    <td style={{ textAlign: 'right' }}>{fmtIsk(mn.unit_cost)}</td>
                    <td style={{ textAlign: 'right' }}>{fmtIsk(mn.value)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div style={{ fontSize: 11, color: 'var(--text)', marginTop: 8 }}>
        Minerals inherit the ore's cost basis (allocated by Jita value) and are added to your warehouse as
        <code> source=reprocess</code> lots, so building with your own ore no longer reads "Missing inputs". Only whole
        ore batches refine; leftovers stay in the lot.
      </div>
    </div>
  )
}
