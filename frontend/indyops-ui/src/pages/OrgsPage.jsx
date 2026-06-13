import { useState, useEffect } from 'react'
import { get, post, patch, del } from '../api/client'

const STATUSES = ['OWNER', 'ADMIN', 'SENIOR', 'JUNIOR', 'INTERN', 'OTHER', 'INACTIVE']

const STATUS_COLOR = {
  OWNER:    '#c8a951',
  ADMIN:    '#2980b9',
  SENIOR:   '#27ae60',
  JUNIOR:   '#8b93b0',
  INTERN:   '#8b93b0',
  OTHER:    '#8b93b0',
  INACTIVE: '#c0392b',
}

export default function OrgsPage() {
  const [orgs, setOrgs]       = useState([])
  const [name, setName]       = useState('')
  const [error, setError]     = useState('')
  const [loading, setLoading] = useState(false)
  const [expanded, setExpanded] = useState(null)   // org id that is open

  async function load() {
    try { setOrgs(await get('/organisations')) } catch {}
  }

  useEffect(() => { load() }, [])

  async function create(e) {
    e.preventDefault()
    if (!name.trim()) return
    setError(''); setLoading(true)
    try {
      const org = await post('/organisations', { name: name.trim() })
      setName('')
      setOrgs(prev => [...prev, org])
      setExpanded(org.id)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  async function deleteOrg(id) {
    if (!confirm('Delete this organisation?')) return
    try {
      await del(`/organisations/${id}`)
      setOrgs(prev => prev.filter(o => o.id !== id))
      if (expanded === id) setExpanded(null)
    } catch (err) { setError(err.message) }
  }

  function toggle(id) {
    setExpanded(prev => prev === id ? null : id)
  }

  return (
    <div>
      <h2 style={{ marginBottom: 24 }}>Organisations</h2>

      <div className="card" style={{ maxWidth: 480, marginBottom: 28 }}>
        <h3 style={{ marginBottom: 16, fontSize: 14 }}>Create Organisation</h3>
        {error && <div className="error-box">{error}</div>}
        <form onSubmit={create} style={{ display: 'flex', gap: 10 }}>
          <input value={name} onChange={e => setName(e.target.value)} placeholder="Organisation name" required />
          <button className="btn btn-primary" type="submit" disabled={loading} style={{ whiteSpace: 'nowrap' }}>
            {loading ? '…' : '+ Create'}
          </button>
        </form>
      </div>

      {orgs.length === 0
        ? <div className="empty-state">No organisations yet</div>
        : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {orgs.map(o => (
              <OrgCard
                key={o.id}
                org={o}
                open={expanded === o.id}
                onToggle={() => toggle(o.id)}
                onDelete={() => deleteOrg(o.id)}
              />
            ))}
          </div>
        )
      }
    </div>
  )
}

/* ── Per-org card with employee list ── */
function OrgCard({ org, open, onToggle, onDelete }) {
  const [employees, setEmployees] = useState([])
  const [loaded, setLoaded]       = useState(false)
  const [empError, setEmpError]   = useState('')
  const [form, setForm]           = useState({ name: '', character_id: '', status: 'OTHER' })
  const [adding, setAdding]       = useState(false)

  useEffect(() => {
    if (open && !loaded) loadEmployees()
  }, [open])

  async function loadEmployees() {
    try {
      setEmployees(await get(`/organisations/${org.id}/employees`))
      setLoaded(true)
    } catch {}
  }

  async function addEmployee(e) {
    e.preventDefault()
    if (!form.name.trim()) return
    setEmpError(''); setAdding(true)
    try {
      const emp = await post(`/organisations/${org.id}/employees`, {
        name:         form.name.trim(),
        character_id: form.character_id ? Number(form.character_id) : null,
        status:       form.status,
      })
      setEmployees(prev => [...prev, emp])
      setForm({ name: '', character_id: '', status: 'OTHER' })
    } catch (err) {
      setEmpError(err.message)
    } finally {
      setAdding(false)
    }
  }

  async function changeStatus(empId, status) {
    try {
      const updated = await patch(`/organisations/${org.id}/employees/${empId}`, { status })
      setEmployees(prev => prev.map(e => e.id === empId ? updated : e))
    } catch {}
  }

  async function removeEmployee(empId) {
    if (!confirm('Remove this employee?')) return
    try {
      await del(`/organisations/${org.id}/employees/${empId}`)
      setEmployees(prev => prev.filter(e => e.id !== empId))
    } catch {}
  }

  const setF = k => e => setForm(f => ({ ...f, [k]: e.target.value }))

  return (
    <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 6, overflow: 'hidden' }}>
      {/* Header row */}
      <div
        style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '12px 18px', cursor: 'pointer', userSelect: 'none' }}
        onClick={onToggle}
      >
        <span style={{ color: 'var(--text)', fontSize: 13 }}>#{org.id}</span>
        <span style={{ color: 'var(--accent)', fontWeight: 500, flex: 1 }}>{org.name}</span>
        <span style={{ color: 'var(--text)', fontSize: 12 }}>{new Date(org.created_at).toLocaleDateString()}</span>
        <button
          className="btn btn-danger btn-sm"
          onClick={e => { e.stopPropagation(); onDelete() }}
          style={{ marginLeft: 8 }}
        >✕</button>
        <span style={{ color: 'var(--text)', fontSize: 14, marginLeft: 4 }}>{open ? '▲' : '▼'}</span>
      </div>

      {/* Expanded employee section */}
      {open && (
        <div style={{ borderTop: '1px solid var(--border)', padding: '16px 18px', background: 'var(--surface2)' }}>
          <div style={{ fontSize: 12, color: 'var(--text)', fontWeight: 600, letterSpacing: 1, marginBottom: 14 }}>
            MEMBERS
          </div>

          {employees.length > 0 && (
            <table style={{ marginBottom: 18 }}>
              <thead>
                <tr>
                  <th>Character</th>
                  <th>EVE ID</th>
                  <th>Status</th>
                  <th>Added</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {employees.map(emp => (
                  <tr key={emp.id}>
                    <td style={{ color: 'var(--text-white)' }}>{emp.name}</td>
                    <td style={{ color: 'var(--text)', fontSize: 12 }}>{emp.character_id ?? '—'}</td>
                    <td style={{ minWidth: 130 }}>
                      <select
                        value={emp.status}
                        onChange={e => changeStatus(emp.id, e.target.value)}
                        style={{
                          color: STATUS_COLOR[emp.status] || 'var(--text)',
                          background: 'var(--surface3)',
                          border: '1px solid var(--border2)',
                          padding: '3px 6px',
                          fontSize: 12,
                          width: '100%',
                        }}
                      >
                        {STATUSES.map(s => <option key={s} value={s}>{s}</option>)}
                      </select>
                    </td>
                    <td style={{ color: 'var(--text)', fontSize: 12 }}>
                      {new Date(emp.added_at).toLocaleDateString()}
                    </td>
                    <td>
                      <button className="btn btn-danger btn-sm" onClick={() => removeEmployee(emp.id)}>✕</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {/* Add employee form */}
          {empError && <div className="error-box" style={{ marginBottom: 10 }}>{empError}</div>}
          <form onSubmit={addEmployee} style={{ display: 'flex', gap: 10, alignItems: 'flex-end', flexWrap: 'wrap' }}>
            <div style={{ flex: '2 1 160px' }}>
              <label style={{ display: 'block', fontSize: 11, color: 'var(--text)', marginBottom: 5 }}>Character name</label>
              <input value={form.name} onChange={setF('name')} placeholder="e.g. Nikita Manaenkov" required />
            </div>
            <div style={{ flex: '1 1 110px' }}>
              <label style={{ display: 'block', fontSize: 11, color: 'var(--text)', marginBottom: 5 }}>EVE Char ID</label>
              <input type="number" value={form.character_id} onChange={setF('character_id')} placeholder="optional" />
            </div>
            <div style={{ flex: '1 1 120px' }}>
              <label style={{ display: 'block', fontSize: 11, color: 'var(--text)', marginBottom: 5 }}>Role</label>
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
