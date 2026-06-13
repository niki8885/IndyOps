import { useState, useEffect } from 'react'
import { get, post } from '../api/client'

const TYPES   = ['INTERNAL', 'SELL', 'ACCUMULATION', 'OTHER']
const STATUSES = ['ACTIVE', 'INACTIVE', 'PAUSE', 'DELETED']

const STATUS_BADGE = {
  ACTIVE:   'badge-ok',
  INACTIVE: 'badge-warn',
  PAUSE:    'badge-warn',
  DELETED:  'badge-bad',
}

export default function ProjectsPage() {
  const [orgs, setOrgs]         = useState([])
  const [employees, setEmployees] = useState([])
  const [projects, setProjects]  = useState([])
  const [orgId, setOrgId]        = useState('')
  const [showForm, setShowForm]  = useState(false)
  const [form, setForm]          = useState({ name: '', project_type: 'INTERNAL', note: '', created_by: '' })
  const [error, setError]        = useState('')
  const [loading, setLoading]    = useState(false)

  useEffect(() => {
    get('/organisations').then(setOrgs).catch(() => {})
  }, [])

  useEffect(() => {
    if (!orgId) { setProjects([]); setEmployees([]); return }
    get(`/projects?org_id=${orgId}`).then(setProjects).catch(() => {})
    get(`/organisations/${orgId}/employees`).then(setEmployees).catch(() => {})
    setForm(f => ({ ...f, created_by: '' }))
  }, [orgId])

  async function create(e) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await post(`/projects?org_id=${orgId}`, {
        ...form,
        created_by: Number(form.created_by),
      })
      setShowForm(false)
      setForm({ name: '', project_type: 'INTERNAL', note: '', created_by: '' })
      const data = await get(`/projects?org_id=${orgId}`)
      setProjects(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const set = k => e => setForm(f => ({ ...f, [k]: e.target.value }))

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 24 }}>
        <h2>Projects</h2>
        <select
          value={orgId}
          onChange={e => { setOrgId(e.target.value); setProjects([]) }}
          style={{ width: 220 }}
        >
          <option value="">— Select organisation —</option>
          {orgs.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
        </select>
        {orgId && (
          <button className="btn btn-primary btn-sm" onClick={() => setShowForm(v => !v)}>
            {showForm ? 'Cancel' : '+ New project'}
          </button>
        )}
      </div>

      {showForm && (
        <div className="card" style={{ maxWidth: 520, marginBottom: 24 }}>
          <h3 style={{ marginBottom: 16, fontSize: 14 }}>New Project</h3>
          {error && <div className="error-box">{error}</div>}
          <form onSubmit={create} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <input value={form.name} onChange={set('name')} placeholder="Project name" required />
            <select value={form.project_type} onChange={set('project_type')}>
              {TYPES.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
            <select value={form.created_by} onChange={set('created_by')} required>
              <option value="">— Select creator —</option>
              {employees.map(e => (
                <option key={e.id} value={e.id}>{e.name} ({e.status})</option>
              ))}
            </select>
            <textarea
              value={form.note}
              onChange={set('note')}
              placeholder="Note (optional)"
              rows={2}
            />
            <button className="btn btn-primary" type="submit" disabled={loading}>
              {loading ? 'Creating…' : 'Create'}
            </button>
          </form>
        </div>
      )}

      {!orgId
        ? <div className="empty-state">Select an organisation to view projects</div>
        : projects.length === 0
          ? <div className="empty-state">No projects in this organisation</div>
          : (
            <div className="card">
              <table>
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Name</th>
                    <th>Type</th>
                    <th>Status</th>
                    <th>Code</th>
                    <th>Created</th>
                  </tr>
                </thead>
                <tbody>
                  {projects.map(p => (
                    <tr key={p.id}>
                      <td style={{ color: 'var(--text)', width: 48 }}>{p.id}</td>
                      <td style={{ color: 'var(--text-white)' }}>{p.name}</td>
                      <td style={{ color: 'var(--text)', fontSize: 12 }}>{p.project_type}</td>
                      <td>
                        <span className={`badge ${STATUS_BADGE[p.status] || 'badge-warn'}`}>
                          {p.status}
                        </span>
                      </td>
                      <td style={{ color: 'var(--text)', fontSize: 12 }}>{p.org_project_code || '—'}</td>
                      <td style={{ color: 'var(--text)', fontSize: 12 }}>
                        {new Date(p.created_at).toLocaleDateString()}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
      }
    </div>
  )
}
