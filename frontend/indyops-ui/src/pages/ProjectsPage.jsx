import { useState, useEffect } from 'react'
import { get, post, patch, del } from '../api/client'

const TYPES    = ['INTERNAL', 'SELL', 'ACCUMULATION', 'OTHER']
const STATUSES = ['ACTIVE', 'INACTIVE', 'PAUSE', 'DELETED']

const STATUS_BADGE = {
  ACTIVE: 'badge-ok', INACTIVE: 'badge-warn', PAUSE: 'badge-warn', DELETED: 'badge-bad',
}

const EMPTY = { name: '', project_type: 'INTERNAL', note: '', created_by: '', supervised_by: '', org_project_code: '' }

export default function ProjectsPage() {
  const [orgs, setOrgs]           = useState([])
  const [employees, setEmployees] = useState([])
  const [projects, setProjects]   = useState([])
  const [orgId, setOrgId]         = useState('')
  const [showForm, setShowForm]   = useState(false)
  const [form, setForm]           = useState(EMPTY)
  const [error, setError]         = useState('')
  const [loading, setLoading]     = useState(false)
  const [expand, setExpand]       = useState(null)
  const [editId, setEditId]       = useState(null)

  useEffect(() => { get('/organisations').then(setOrgs).catch(() => {}) }, [])

  useEffect(() => {
    if (!orgId) { setProjects([]); setEmployees([]); return }
    reload()
    get(`/organisations/${orgId}/employees`).then(setEmployees).catch(() => {})
    setForm(f => ({ ...f, created_by: '', supervised_by: '' }))
  }, [orgId])

  async function reload() {
    try { setProjects(await get(`/projects?org_id=${orgId}`)) } catch {}
  }

  const empName = id => employees.find(e => e.id === id)?.name || (id ? `#${id}` : '—')

  async function submit(e) {
    e.preventDefault()
    setError(''); setLoading(true)
    try {
      const body = {
        name: form.name,
        project_type: form.project_type,
        note: form.note || null,
        supervised_by: form.supervised_by ? Number(form.supervised_by) : null,
        org_project_code: form.org_project_code || null,
      }
      if (editId) {
        await patch(`/projects/${editId}?org_id=${orgId}`, body)
      } else {
        await post(`/projects?org_id=${orgId}`, { ...body, created_by: Number(form.created_by) })
      }
      setShowForm(false); setEditId(null); setForm(EMPTY)
      reload()
    } catch (err) { setError(err.message) }
    finally { setLoading(false) }
  }

  function openCreate() {
    setEditId(null); setForm(EMPTY); setError(''); setShowForm(true)
  }
  function openEdit(p) {
    setEditId(p.id)
    setForm({
      name: p.name, project_type: p.project_type, note: p.note ?? '',
      created_by: p.created_by, supervised_by: p.supervised_by ?? '',
      org_project_code: p.org_project_code ?? '',
    })
    setError(''); setShowForm(true)
  }

  async function setStatus(p, status) {
    try { await patch(`/projects/${p.id}?org_id=${orgId}`, { status }); reload() } catch {}
  }
  async function remove(p) {
    if (!confirm(`Delete project "${p.name}"?`)) return
    try { await del(`/projects/${p.id}?org_id=${orgId}`); reload() } catch {}
  }

  const set = k => e => setForm(f => ({ ...f, [k]: e.target.value }))

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 24 }}>
        <select value={orgId} onChange={e => { setOrgId(e.target.value); setProjects([]) }} style={{ width: 220 }}>
          <option value="">— Select organisation —</option>
          {orgs.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
        </select>
        {orgId && <button className="btn btn-primary btn-sm" onClick={openCreate}>+ New project</button>}
      </div>

      {showForm && orgId && (
        <div className="card" style={{ maxWidth: 560, marginBottom: 24 }}>
          <h3 style={{ marginBottom: 16, fontSize: 14 }}>{editId ? 'Edit Project' : 'New Project'}</h3>
          {error && <div className="error-box">{error}</div>}
          <form onSubmit={submit} style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <div style={{ gridColumn: '1 / -1' }}><L>Name</L>
              <input value={form.name} onChange={set('name')} placeholder="Project name" required />
            </div>
            <div><L>Type</L>
              <select value={form.project_type} onChange={set('project_type')}>
                {TYPES.map(t => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>
            <div><L>Project code <Hint>used for PAK contracts</Hint></L>
              <input value={form.org_project_code} onChange={set('org_project_code')} placeholder="e.g. FUEL-RYC" />
            </div>
            {!editId && (
              <div><L>Creator</L>
                <select value={form.created_by} onChange={set('created_by')} required>
                  <option value="">— select —</option>
                  {employees.map(e => <option key={e.id} value={e.id}>{e.name} ({e.status})</option>)}
                </select>
              </div>
            )}
            <div><L>Supervisor <Hint>optional</Hint></L>
              <select value={form.supervised_by} onChange={set('supervised_by')}>
                <option value="">— none —</option>
                {employees.map(e => <option key={e.id} value={e.id}>{e.name} ({e.status})</option>)}
              </select>
            </div>
            <div style={{ gridColumn: '1 / -1' }}><L>Note</L>
              <textarea value={form.note} onChange={set('note')} rows={2} />
            </div>
            <div style={{ gridColumn: '1 / -1', display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button type="button" className="btn btn-ghost" onClick={() => { setShowForm(false); setEditId(null) }}>Cancel</button>
              <button className="btn btn-primary" type="submit" disabled={loading}>
                {loading ? '…' : editId ? 'Update' : 'Create'}
              </button>
            </div>
          </form>
        </div>
      )}

      {!orgId
        ? <div className="empty-state">Select an organisation to view projects</div>
        : projects.length === 0
          ? <div className="empty-state">No projects in this organisation</div>
          : (
            <div className="card" style={{ padding: 0, overflowX: 'auto' }}>
              <table>
                <thead>
                  <tr>
                    <th>#</th><th>Name</th><th>Type</th><th>Status</th>
                    <th>Code</th><th>Creator</th><th>Supervisor</th><th>Created</th><th></th>
                  </tr>
                </thead>
                <tbody>
                  {projects.map(p => [
                    <tr key={p.id} style={{ cursor: 'pointer' }} onClick={() => setExpand(expand === p.id ? null : p.id)}>
                      <td style={{ color: 'var(--text)', width: 40 }}>{p.id}</td>
                      <td style={{ color: 'var(--text-white)' }}>{p.name}</td>
                      <td style={{ color: 'var(--text)', fontSize: 12 }}>{p.project_type}</td>
                      <td>
                        <select value={p.status} onClick={e => e.stopPropagation()} onChange={e => setStatus(p, e.target.value)}
                          style={{ width: 105, fontSize: 12, padding: '3px 6px', background: 'var(--surface)', border: '1px solid var(--border)' }}>
                          {STATUSES.map(s => <option key={s} value={s}>{s}</option>)}
                        </select>
                      </td>
                      <td style={{ color: 'var(--accent)', fontSize: 12 }}>{p.org_project_code || '—'}</td>
                      <td style={{ color: 'var(--text)', fontSize: 12 }}>{empName(p.created_by)}</td>
                      <td style={{ color: 'var(--text)', fontSize: 12 }}>{empName(p.supervised_by)}</td>
                      <td style={{ color: 'var(--text)', fontSize: 12 }}>{new Date(p.created_at).toLocaleDateString()}</td>
                      <td style={{ whiteSpace: 'nowrap' }}>
                        <button className="btn btn-ghost btn-sm" onClick={e => { e.stopPropagation(); openEdit(p) }} style={{ marginRight: 4 }}>Edit</button>
                        <button className="btn btn-danger btn-sm" onClick={e => { e.stopPropagation(); remove(p) }}>✕</button>
                      </td>
                    </tr>,
                    expand === p.id && (
                      <tr key={`x-${p.id}`}>
                        <td colSpan={9} style={{ background: 'var(--surface2)', padding: 0 }}>
                          <ProjectPaks project={p} />
                        </td>
                      </tr>
                    ),
                  ])}
                </tbody>
              </table>
            </div>
          )
      }
    </div>
  )
}

function ProjectPaks({ project }) {
  const [jobs, setJobs] = useState(null)
  useEffect(() => {
    get(`/manufacturing/jobs?project_id=${project.id}`).then(setJobs).catch(() => setJobs([]))
  }, [project.id])

  return (
    <div style={{ padding: 16 }}>
      <div style={{ fontSize: 12, color: 'var(--accent)', fontWeight: 700, letterSpacing: 1, marginBottom: 10 }}>
        PAK JOBS {project.org_project_code ? `· code ${project.org_project_code}` : ''}
      </div>
      {jobs === null
        ? <span style={{ color: 'var(--text)', fontSize: 12 }}>Loading…</span>
        : jobs.length === 0
          ? <span style={{ color: 'var(--text)', fontSize: 12 }}>No PAK jobs for this project yet.</span>
          : (
            <table>
              <thead><tr><th>#</th><th>Product</th><th>PAKs</th><th>Status</th><th>Place</th><th>Date</th></tr></thead>
              <tbody>
                {jobs.map(j => (
                  <tr key={j.id}>
                    <td style={{ color: 'var(--text)' }}>{j.id}</td>
                    <td style={{ color: 'var(--accent)' }}>{j.product_name}</td>
                    <td>{j.paks ?? '—'}</td>
                    <td style={{ fontSize: 12 }}>{j.status}</td>
                    <td style={{ color: 'var(--text)', fontSize: 12 }}>{j.place || '—'}</td>
                    <td style={{ color: 'var(--text)', fontSize: 12 }}>{j.date_planned ? new Date(j.date_planned).toLocaleDateString() : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
      }
    </div>
  )
}

function L({ children }) {
  return <label style={{ display: 'block', fontSize: 11, color: 'var(--text)', marginBottom: 5 }}>{children}</label>
}
function Hint({ children }) {
  return <span style={{ fontWeight: 400, color: 'var(--border2)', marginLeft: 4 }}>{children}</span>
}
