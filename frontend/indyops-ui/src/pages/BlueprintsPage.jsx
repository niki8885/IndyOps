import { useState, useEffect } from 'react'
import { get, post, patch, del } from '../api/client'
import TypeSearch from '../components/TypeSearch'

const EMPTY = {
  blueprint: { type_id: null, name: null },
  organisation_id: '', is_bpo: true, me: 0, te: 0, runs: '', quantity: 1, cost: '', note: '',
}

// "Name, BPO/BPC, ME, TE, runs, cost, qty" — tab or comma separated, one per line.
function parsePaste(text) {
  return text.split('\n').map(l => l.trim()).filter(Boolean).map(l => {
    const c = l.split(/\t|,/).map(s => s.trim())
    const t = (c[1] || '').toLowerCase()
    const is_bpo = t.includes('bpc') ? false : t.includes('bpo') ? true : !c[4]
    return {
      name: c[0], is_bpo,
      me: Number(c[2]) || 0, te: Number(c[3]) || 0,
      runs: c[4] ? Number(c[4]) : null,
      cost: c[5] ? Number(c[5]) : null,
      quantity: c[6] ? Number(c[6]) : 1,
    }
  }).filter(r => r.name)
}

export default function BlueprintsPage() {
  const [list, setList]       = useState([])
  const [orgs, setOrgs]       = useState([])
  const [showForm, setShow]   = useState(false)
  const [editId, setEditId]   = useState(null)
  const [form, setForm]       = useState(EMPTY)
  const [error, setError]     = useState('')
  const [paste, setPaste]     = useState('')
  const [showPaste, setShowPaste] = useState(false)
  const [importMsg, setImportMsg] = useState('')

  async function load() {
    try { setList(await get('/blueprints')) } catch {}
  }
  useEffect(() => { load() }, [])
  useEffect(() => { get('/organisations').then(setOrgs).catch(() => {}) }, [])
  const orgName = id => orgs.find(o => o.id === id)?.name || '—'

  function openCreate() { setEditId(null); setForm(EMPTY); setError(''); setShow(true) }
  function openEdit(b) {
    setEditId(b.id)
    setForm({
      blueprint: { type_id: b.blueprint_type_id, name: b.name },
      organisation_id: b.organisation_id ?? '', is_bpo: b.is_bpo, me: b.me, te: b.te,
      runs: b.runs ?? '', quantity: b.quantity, cost: b.cost ?? '', note: b.note ?? '',
    })
    setError(''); setShow(true)
  }

  async function submit(e) {
    e.preventDefault()
    setError('')
    const body = {
      blueprint_type_id: form.blueprint.type_id,
      name: form.blueprint.name,
      organisation_id: form.organisation_id ? Number(form.organisation_id) : null,
      is_bpo: form.is_bpo, me: Number(form.me) || 0, te: Number(form.te) || 0,
      runs: form.is_bpo || form.runs === '' ? null : Number(form.runs),
      quantity: Number(form.quantity) || 1,
      cost: form.cost === '' ? null : Number(form.cost),
      note: form.note || null,
    }
    try {
      if (editId) await patch(`/blueprints/${editId}`, body)
      else {
        if (!body.blueprint_type_id) { setError('Pick a blueprint'); return }
        await post('/blueprints', body)
      }
      setShow(false); setEditId(null); load()
    } catch (err) { setError(err.message) }
  }

  async function remove(id) {
    if (!confirm('Delete blueprint?')) return
    try { await del(`/blueprints/${id}`); load() } catch {}
  }

  async function runImport() {
    setImportMsg('')
    const rows = parsePaste(paste)
    if (!rows.length) { setImportMsg('Nothing to import'); return }
    try {
      const res = await post('/blueprints/import', { rows })
      setImportMsg(`Imported ${res.created_count}.` + (res.unresolved?.length ? ` Unresolved: ${res.unresolved.join(', ')}` : ''))
      setPaste(''); load()
    } catch (e) { setImportMsg('⚠ ' + e.message) }
  }

  const setF = k => e => setForm(f => ({ ...f, [k]: e.target.value }))

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 24 }}>
        <h2>Blueprints</h2>
        <button className="btn btn-primary btn-sm" onClick={openCreate}>+ Add</button>
        <button className="btn btn-ghost btn-sm" onClick={() => setShowPaste(p => !p)}>📋 Paste import</button>
      </div>

      {showPaste && (
        <div className="card" style={{ marginBottom: 20, maxWidth: 720 }}>
          <Label>Paste rows — <span style={{ color: 'var(--border2)' }}>Name, BPO/BPC, ME, TE, runs, cost, qty</span> (tab or comma, one per line)</Label>
          <textarea value={paste} onChange={e => setPaste(e.target.value)} rows={6}
            placeholder={'Obelisk Blueprint\tBPO\t10\t20\nReinforced Carbon Fiber Reaction Formula\tBPC\t0\t0\t50\t1500000\t3'}
            style={{ fontFamily: 'monospace', fontSize: 12, width: '100%', marginTop: 6 }} />
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginTop: 8 }}>
            <button className="btn btn-primary btn-sm" onClick={runImport}>Import</button>
            {importMsg && <span style={{ fontSize: 12, color: importMsg.startsWith('⚠') ? '#e05252' : '#4caf7d' }}>{importMsg}</span>}
          </div>
        </div>
      )}

      {showForm && (
        <div className="card" style={{ marginBottom: 24, maxWidth: 640 }}>
          <h3 style={{ marginBottom: 16, fontSize: 14 }}>{editId ? 'Edit Blueprint' : 'New Blueprint'}</h3>
          {error && <div className="error-box">{error}</div>}
          <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <div>
              <Label>Blueprint</Label>
              {editId
                ? <input value={form.blueprint.name || ''} disabled />
                : <TypeSearch value={{ name: form.blueprint.name }}
                    onChange={v => setForm(f => ({ ...f, blueprint: v }))} placeholder="Search blueprint…" />}
            </div>
            <div style={{ display: 'flex', gap: 18, alignItems: 'center' }}>
              <label style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: 13, cursor: 'pointer' }}>
                <input type="radio" checked={form.is_bpo} onChange={() => setForm(f => ({ ...f, is_bpo: true }))} /> BPO
              </label>
              <label style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: 13, cursor: 'pointer' }}>
                <input type="radio" checked={!form.is_bpo} onChange={() => setForm(f => ({ ...f, is_bpo: false }))} /> BPC
              </label>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(120px,1fr))', gap: 12 }}>
              <Field label="ME %"><input type="number" value={form.me} onChange={setF('me')} min={0} max={10} /></Field>
              <Field label="TE %"><input type="number" value={form.te} onChange={setF('te')} min={0} max={20} /></Field>
              <Field label="Quantity"><input type="number" value={form.quantity} onChange={setF('quantity')} min={1} /></Field>
              {!form.is_bpo && <Field label="Runs"><input type="number" value={form.runs} onChange={setF('runs')} min={1} /></Field>}
              {!form.is_bpo && <Field label="Cost (per copy)"><input type="number" value={form.cost} onChange={setF('cost')} min={0} /></Field>}
            </div>
            <Field label="Organisation (optional)">
              <select value={form.organisation_id} onChange={setF('organisation_id')}>
                <option value="">— personal —</option>
                {orgs.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
              </select>
            </Field>
            <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
              <button type="button" className="btn btn-ghost" onClick={() => setShow(false)}>Cancel</button>
              <button type="submit" className="btn btn-primary">{editId ? 'Update' : 'Create'}</button>
            </div>
          </form>
        </div>
      )}

      {list.length === 0
        ? <div className="empty-state">No blueprints yet</div>
        : (
          <div className="card" style={{ padding: 0 }}>
            <table>
              <thead><tr><th>Blueprint</th><th>Type</th><th>ME</th><th>TE</th><th>Runs</th><th>Qty</th><th>Cost</th><th>Org</th><th></th></tr></thead>
              <tbody>
                {list.map(b => (
                  <tr key={b.id}>
                    <td style={{ color: 'var(--text-white)' }}>{b.name}</td>
                    <td>
                      <span style={{ fontSize: 11, fontWeight: 700, padding: '2px 8px', borderRadius: 3,
                        background: (b.is_bpo ? '#4caf7d' : '#3a9bd6') + '22', color: b.is_bpo ? '#4caf7d' : '#3a9bd6' }}>
                        {b.is_bpo ? 'BPO' : 'BPC'}
                      </span>
                    </td>
                    <td>{b.me}</td>
                    <td>{b.te}</td>
                    <td>{b.is_bpo ? '∞' : (b.runs ?? '—')}</td>
                    <td>{b.quantity}</td>
                    <td style={{ color: 'var(--text)' }}>{b.cost != null ? (b.cost / 1e6).toFixed(2) + ' M' : '—'}</td>
                    <td style={{ fontSize: 12, color: 'var(--text)' }}>{orgName(b.organisation_id)}</td>
                    <td style={{ whiteSpace: 'nowrap' }}>
                      <button className="btn btn-ghost btn-sm" onClick={() => openEdit(b)} style={{ marginRight: 4 }}>Edit</button>
                      <button className="btn btn-danger btn-sm" onClick={() => remove(b.id)}>✕</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
    </div>
  )
}

function Label({ children }) {
  return <label style={{ display: 'block', fontSize: 11, color: 'var(--text)', marginBottom: 5 }}>{children}</label>
}
function Field({ label, children }) {
  return <div><Label>{label}</Label>{children}</div>
}
