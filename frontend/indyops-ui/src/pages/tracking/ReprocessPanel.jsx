// Reprocess your in-game ore into minerals. Ore is read live from synced ESI assets and
// grouped by the station/structure that holds it, so you pick a location, select the ore
// there, and a saved preset (base yield / rigs / tax / skills) refines it into minerals —
// showing the refined Jita value vs the raw-ore value (the "refine premium"). Read-only:
// it values your holdings, it doesn't move anything. Rendered in the Tracking → Industry tab.
import { useState, useEffect, useCallback } from 'react'
import { get, post, put, del } from '../../api/client'
import { fmtIsk, fmtInt, GREEN, RED } from './fmt'

const BLANK = {
  name: '', base_yield: 0.5, tax_pct: 0, security: 'hi',
  reprocessing_lvl: 5, efficiency_lvl: 5, ore_specific_lvl: 4, implant_pct: 0, rig_type_ids: [],
}
const numStyle = { width: 64, padding: '5px 6px' }
const rowKey = o => `${o.location_id}:${o.type_id}`

export default function ReprocessPanel() {
  const [presets, setPresets] = useState([])
  const [rigs, setRigs] = useState([])
  const [assets, setAssets] = useState({ locations: [], ore: [] })
  const [presetId, setPresetId] = useState(null)
  const [locId, setLocId] = useState('')          // '' = not yet chosen, 'all' = every location
  const [sel, setSel] = useState({})
  const [basis, setBasis] = useState('sell')
  const [result, setResult] = useState(null)
  const [editing, setEditing] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  const loadPresets = useCallback(() => get('/inventory/reprocessing/presets').then(setPresets).catch(() => {}), [])
  const loadAssets = useCallback(() => get('/inventory/reprocessing/assets').then(d => setAssets(d || { locations: [], ore: [] })).catch(() => {}), [])
  useEffect(() => {
    loadPresets(); loadAssets()
    get('/ore/rigs').then(d => setRigs(d.rigs || [])).catch(() => {})
  }, [loadPresets, loadAssets])

  const locations = assets.locations || []
  // default to the first location once assets load (until the user picks one)
  const activeLoc = locId || (locations[0] ? String(locations[0].id) : 'all')
  const visibleOre = (assets.ore || []).filter(o => activeLoc === 'all' || String(o.location_id) === activeLoc)
  const selectedOre = visibleOre.filter(o => sel[rowKey(o)])

  const activePresetId = presetId ?? (presets[0]?.id ?? null)
  const setField = (k, v) => setEditing(e => ({ ...e, [k]: v }))
  const toggleRig = rid => setEditing(e => ({
    ...e, rig_type_ids: e.rig_type_ids.includes(rid) ? e.rig_type_ids.filter(x => x !== rid) : [...e.rig_type_ids, rid],
  }))

  function pickLocation(v) { setLocId(v); setSel({}); setResult(null) }

  async function doReprocess() {
    setErr(''); setResult(null); setBusy(true)
    try {
      const lines = selectedOre.map(o => ({ type_id: o.type_id, quantity: o.quantity }))
      const r = await post('/inventory/reprocessing/preview', { preset_id: activePresetId, lines, basis })
      setResult(r)
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

  const deltaColor = result && result.delta >= 0 ? GREEN : RED

  return (
    <div className="card" style={{ marginTop: 22 }}>
      <div className="sec-label" style={{ marginBottom: 10 }}>Reprocess ore → minerals (by station)</div>

      {/* preset + basis row */}
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

      {/* location picker + ore list */}
      {(assets.ore || []).length === 0 ? (
        <div className="empty-state" style={{ padding: '18px 12px' }}>
          No ore in your assets. Link characters with the <code>read_assets</code> scope and <b>Sync from ESI</b> —
          your ore then shows up here grouped by station.
        </div>
      ) : (
        <>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 10 }}>
            <span style={{ fontSize: 12, color: 'var(--text)' }}>Location</span>
            <select value={activeLoc} onChange={e => pickLocation(e.target.value)} style={{ padding: '6px 8px', minWidth: 240 }}>
              <option value="all">All locations ({locations.length})</option>
              {locations.map(l => (
                <option key={l.id} value={String(l.id)}>{l.name} — {l.ore_types} ore type(s), {fmtInt(l.total_qty)} units</option>
              ))}
            </select>
            {visibleOre.length > 0 && (
              <button className="btn btn-ghost btn-sm"
                onClick={() => setSel(Object.fromEntries(visibleOre.map(o => [rowKey(o), true])))}>Select all</button>
            )}
            {selectedOre.length > 0 && <button className="btn btn-ghost btn-sm" onClick={() => setSel({})}>Clear</button>}
          </div>

          <div style={{ overflowX: 'auto' }}>
            <table>
              <thead><tr>
                <th /><th>Ore</th>
                {activeLoc === 'all' && <th>Location</th>}
                <th style={{ textAlign: 'right' }}>Quantity</th>
                <th style={{ textAlign: 'right' }}>Jita unit</th>
              </tr></thead>
              <tbody>
                {visibleOre.map(o => (
                  <tr key={rowKey(o)}>
                    <td><input type="checkbox" checked={!!sel[rowKey(o)]} onChange={() => setSel(s => ({ ...s, [rowKey(o)]: !s[rowKey(o)] }))} /></td>
                    <td>{o.name}</td>
                    {activeLoc === 'all' && <td style={{ fontSize: 12, color: 'var(--text)' }}>{o.location_name || '—'}</td>}
                    <td style={{ textAlign: 'right' }}>{fmtInt(o.quantity)}</td>
                    <td style={{ textAlign: 'right' }}>{o.price == null ? '—' : fmtIsk(o.price)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 12 }}>
        <button className="btn btn-sm" onClick={doReprocess} disabled={busy || !activePresetId || !selectedOre.length}>
          {busy ? 'Calculating…' : `Reprocess ${selectedOre.length || ''} ore type(s)`}
        </button>
        {err && <span style={{ fontSize: 12, color: RED }}>{err}</span>}
      </div>

      {/* result */}
      {result && (
        <div className="card" style={{ marginTop: 12, background: 'var(--bg)' }}>
          <div style={{ fontSize: 12, color: 'var(--text-bright)', marginBottom: 8 }}>
            Refined via <b>{result.preset}</b> at {(result.effective_yield * 100).toFixed(1)}% yield · raw ore {fmtIsk(result.raw_ore_value)} ·
            refined <span style={{ color: GREEN }}>{fmtIsk(result.total_value)}</span> ·
            refine premium <span style={{ color: deltaColor }}>{result.delta >= 0 ? '+' : ''}{fmtIsk(result.delta)}</span>
            {result.skipped?.length ? <span style={{ color: 'var(--text)' }}> · skipped (under one batch): {result.skipped.join(', ')}</span> : null}
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table>
              <thead><tr><th>Mineral</th><th style={{ textAlign: 'right' }}>Quantity</th><th style={{ textAlign: 'right' }}>Jita unit</th><th style={{ textAlign: 'right' }}>Jita value</th></tr></thead>
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
        Ore is read live from your synced ESI assets and grouped by station/structure. The refine premium compares the
        refined mineral value against the raw ore value at the chosen Jita basis — positive means refining beats selling
        the ore as-is. Only whole ore batches refine; leftovers are ignored. This view is read-only.
      </div>
    </div>
  )
}
