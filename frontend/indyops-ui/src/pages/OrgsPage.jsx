import { useState, useEffect } from 'react'
import { get, post, patch, del } from '../api/client'

const STATUSES = ['OWNER', 'ADMIN', 'SENIOR', 'JUNIOR', 'INTERN', 'OTHER', 'INACTIVE']
const ORG_TYPES = ['Personal', 'Corporation']

const STATUS_COLOR = {
  OWNER: '#c8a951', ADMIN: '#2980b9', SENIOR: '#27ae60',
  JUNIOR: '#8b93b0', INTERN: '#8b93b0', OTHER: '#8b93b0', INACTIVE: '#c0392b',
}

export default function OrgsPage() {
  const [orgs, setOrgs]       = useState([])
  const [form, setForm]       = useState({ name: '', org_type: 'Personal', corporation_name: '', corporation_id: '' })
  const [error, setError]     = useState('')
  const [loading, setLoading] = useState(false)
  const [expanded, setExpanded] = useState(null)

  async function load() {
    try { setOrgs(await get('/organisations')) } catch {}
  }
  useEffect(() => { load() }, [])

  async function create(e) {
    e.preventDefault()
    if (!form.name.trim()) return
    setError(''); setLoading(true)
    try {
      const org = await post('/organisations', {
        name: form.name.trim(),
        org_type: form.org_type,
        corporation_name: form.corporation_name || null,
        corporation_id: form.corporation_id ? Number(form.corporation_id) : null,
      })
      setForm({ name: '', org_type: 'Personal', corporation_name: '', corporation_id: '' })
      setOrgs(prev => [...prev, org])
      setExpanded(org.id)
    } catch (err) { setError(err.message) }
    finally { setLoading(false) }
  }

  async function deleteOrg(id) {
    if (!confirm('Delete this organisation?')) return
    try {
      await del(`/organisations/${id}`)
      setOrgs(prev => prev.filter(o => o.id !== id))
      if (expanded === id) setExpanded(null)
    } catch (err) { setError(err.message) }
  }

  function onSaved(updated) {
    setOrgs(prev => prev.map(o => o.id === updated.id ? { ...o, ...updated } : o))
  }

  const setF = k => e => setForm(f => ({ ...f, [k]: e.target.value }))

  return (
    <div>
      <div className="card" style={{ maxWidth: 560, marginBottom: 24 }}>
        <h3 style={{ marginBottom: 16, fontSize: 14 }}>Create Organisation</h3>
        {error && <div className="error-box">{error}</div>}
        <form onSubmit={create} style={{ display: 'grid', gridTemplateColumns: '1fr 160px', gap: 10 }}>
          <div>
            <L>Name</L>
            <input value={form.name} onChange={setF('name')} placeholder="Organisation name" required />
          </div>
          <div>
            <L>Type</L>
            <select value={form.org_type} onChange={setF('org_type')}>
              {ORG_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          {form.org_type === 'Corporation' && (
            <>
              <div>
                <L>In-game corp name</L>
                <input value={form.corporation_name} onChange={setF('corporation_name')} placeholder="e.g. Goonswarm" />
              </div>
              <div>
                <L>Corp ID</L>
                <input type="number" value={form.corporation_id} onChange={setF('corporation_id')} placeholder="ESI id" />
              </div>
            </>
          )}
          <div style={{ gridColumn: '1 / -1', display: 'flex', justifyContent: 'flex-end' }}>
            <button className="btn btn-primary" type="submit" disabled={loading}>
              {loading ? '…' : '+ Create'}
            </button>
          </div>
        </form>
      </div>

      {orgs.length === 0
        ? <div className="empty-state">No organisations yet</div>
        : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {orgs.map(o => (
              <OrgCard key={o.id} org={o} open={expanded === o.id}
                onToggle={() => setExpanded(p => p === o.id ? null : o.id)}
                onDelete={() => deleteOrg(o.id)} onSaved={onSaved} />
            ))}
          </div>
        )
      }
    </div>
  )
}

/* ── Per-org card ── */
function OrgCard({ org, open, onToggle, onDelete, onSaved }) {
  const [employees, setEmployees] = useState([])
  const [loaded, setLoaded]       = useState(false)
  const [empError, setEmpError]   = useState('')
  const [form, setForm]           = useState({ name: '', character_id: '', status: 'OTHER' })
  const [adding, setAdding]       = useState(false)
  const [editing, setEditing]     = useState(false)
  const [edit, setEdit]           = useState({})

  useEffect(() => { if (open && !loaded) loadEmployees() }, [open])

  async function loadEmployees() {
    try { setEmployees(await get(`/organisations/${org.id}/employees`)); setLoaded(true) } catch {}
  }

  function startEdit() {
    setEdit({
      name: org.name, org_type: org.org_type || 'Personal',
      corporation_name: org.corporation_name || '', corporation_id: org.corporation_id || '',
    })
    setEditing(true)
  }

  async function saveEdit() {
    try {
      const updated = await patch(`/organisations/${org.id}`, {
        name: edit.name,
        org_type: edit.org_type,
        corporation_name: edit.corporation_name || null,
        corporation_id: edit.corporation_id ? Number(edit.corporation_id) : null,
      })
      onSaved(updated)
      setEditing(false)
    } catch (e) { setEmpError(e.message) }
  }

  async function addEmployee(e) {
    e.preventDefault()
    if (!form.name.trim()) return
    setEmpError(''); setAdding(true)
    try {
      const emp = await post(`/organisations/${org.id}/employees`, {
        name: form.name.trim(),
        character_id: form.character_id ? Number(form.character_id) : null,
        status: form.status,
      })
      setEmployees(prev => [...prev, emp])
      setForm({ name: '', character_id: '', status: 'OTHER' })
    } catch (err) { setEmpError(err.message) }
    finally { setAdding(false) }
  }

  async function patchEmployee(empId, body) {
    try {
      const updated = await patch(`/organisations/${org.id}/employees/${empId}`, body)
      setEmployees(prev => prev.map(e => e.id === empId ? updated : e))
    } catch (e) { setEmpError(e.message) }
  }

  async function removeEmployee(empId) {
    if (!confirm('Remove this employee?')) return
    try {
      await del(`/organisations/${org.id}/employees/${empId}`)
      setEmployees(prev => prev.filter(e => e.id !== empId))
    } catch {}
  }

  const setF = k => e => setForm(f => ({ ...f, [k]: e.target.value }))
  const setE = k => e => setEdit(f => ({ ...f, [k]: e.target.value }))

  return (
    <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 6, overflow: 'hidden' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '12px 18px', cursor: 'pointer', userSelect: 'none' }} onClick={onToggle}>
        <span style={{ color: 'var(--text)', fontSize: 13 }}>#{org.id}</span>
        <span style={{ color: 'var(--accent)', fontWeight: 500 }}>{org.name}</span>
        <span className="badge" style={{ background: org.org_type === 'Corporation' ? '#10243d' : '#1d2135', color: org.org_type === 'Corporation' ? '#3a9bd6' : '#8b93b0' }}>
          {org.org_type || 'Personal'}
        </span>
        {org.corporation_name && <span style={{ fontSize: 12, color: 'var(--text)' }}>{org.corporation_name}{org.corporation_id ? ` · ${org.corporation_id}` : ''}</span>}
        <span style={{ flex: 1 }} />
        <button className="btn btn-ghost btn-sm" onClick={e => { e.stopPropagation(); startEdit(); if (!open) onToggle() }}>Edit</button>
        <button className="btn btn-danger btn-sm" onClick={e => { e.stopPropagation(); onDelete() }}>✕</button>
        <span style={{ color: 'var(--text)', fontSize: 14 }}>{open ? '▲' : '▼'}</span>
      </div>

      {open && (
        <div style={{ borderTop: '1px solid var(--border)', padding: '16px 18px', background: 'var(--surface2)' }}>
          {empError && <div className="error-box" style={{ marginBottom: 10 }}>{empError}</div>}

          {editing && (
            <div className="card" style={{ marginBottom: 16, background: 'var(--surface)' }}>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(150px,1fr))', gap: 10 }}>
                <div><L>Name</L><input value={edit.name} onChange={setE('name')} /></div>
                <div><L>Type</L>
                  <select value={edit.org_type} onChange={setE('org_type')}>
                    {ORG_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
                  </select>
                </div>
                <div><L>Corp name</L><input value={edit.corporation_name} onChange={setE('corporation_name')} /></div>
                <div><L>Corp ID</L><input type="number" value={edit.corporation_id} onChange={setE('corporation_id')} /></div>
              </div>
              <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 12 }}>
                <button className="btn btn-ghost btn-sm" onClick={() => setEditing(false)}>Cancel</button>
                <button className="btn btn-primary btn-sm" onClick={saveEdit}>Save</button>
              </div>
            </div>
          )}

          <div style={{ fontSize: 12, color: 'var(--text)', fontWeight: 600, letterSpacing: 1, marginBottom: 14 }}>MEMBERS</div>

          {employees.length > 0 && (
            <table style={{ marginBottom: 18 }}>
              <thead><tr><th>Character</th><th>EVE ID</th><th>Role</th><th>Added</th><th></th></tr></thead>
              <tbody>
                {employees.map(emp => <EmployeeRow key={emp.id} emp={emp} onPatch={patchEmployee} onRemove={removeEmployee} />)}
              </tbody>
            </table>
          )}

          <form onSubmit={addEmployee} style={{ display: 'flex', gap: 10, alignItems: 'flex-end', flexWrap: 'wrap' }}>
            <div style={{ flex: '2 1 160px' }}><L>Character name</L>
              <input value={form.name} onChange={setF('name')} placeholder="e.g. Nikita Manaenkov" required />
            </div>
            <div style={{ flex: '1 1 110px' }}><L>EVE Char ID</L>
              <input type="number" value={form.character_id} onChange={setF('character_id')} placeholder="optional" />
            </div>
            <div style={{ flex: '1 1 120px' }}><L>Role</L>
              <select value={form.status} onChange={setF('status')}>
                {STATUSES.filter(s => s !== 'INACTIVE').map(s => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
            <button className="btn btn-primary btn-sm" type="submit" disabled={adding} style={{ marginBottom: 1 }}>
              {adding ? '…' : '+ Add'}
            </button>
          </form>
        </div>
      )}
    </div>
  )
}

function EmployeeRow({ emp, onPatch, onRemove }) {
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(emp.name)
  const [charId, setCharId] = useState(emp.character_id ?? '')

  async function save() {
    await onPatch(emp.id, { name, character_id: charId ? Number(charId) : null })
    setEditing(false)
  }

  if (editing) {
    return (
      <tr>
        <td><input value={name} onChange={e => setName(e.target.value)} /></td>
        <td><input type="number" value={charId} onChange={e => setCharId(e.target.value)} placeholder="char id" /></td>
        <td colSpan={2} style={{ color: 'var(--text)', fontSize: 11 }}>editing…</td>
        <td style={{ whiteSpace: 'nowrap' }}>
          <button className="btn btn-primary btn-sm" onClick={save} style={{ marginRight: 4 }}>✓</button>
          <button className="btn btn-ghost btn-sm" onClick={() => setEditing(false)}>✕</button>
        </td>
      </tr>
    )
  }

  return (
    <tr>
      <td style={{ color: 'var(--text-white)' }}>{emp.name}</td>
      <td style={{ color: 'var(--text)', fontSize: 12 }}>{emp.character_id ?? '—'}</td>
      <td style={{ minWidth: 130 }}>
        <select value={emp.status} onChange={e => onPatch(emp.id, { status: e.target.value })}
          style={{ color: STATUS_COLOR[emp.status] || 'var(--text)', background: 'var(--surface3)', border: '1px solid var(--border2)', padding: '3px 6px', fontSize: 12, width: '100%' }}>
          {STATUSES.map(s => <option key={s} value={s}>{s}</option>)}
        </select>
      </td>
      <td style={{ color: 'var(--text)', fontSize: 12 }}>{new Date(emp.added_at).toLocaleDateString()}</td>
      <td style={{ whiteSpace: 'nowrap' }}>
        <button className="btn btn-ghost btn-sm" onClick={() => setEditing(true)} style={{ marginRight: 4 }}>Edit</button>
        <button className="btn btn-danger btn-sm" onClick={() => onRemove(emp.id)}>✕</button>
      </td>
    </tr>
  )
}

function L({ children }) {
  return <label style={{ display: 'block', fontSize: 11, color: 'var(--text)', marginBottom: 5 }}>{children}</label>
}
