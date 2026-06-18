import { useState, useEffect } from 'react'
import { get, post, patch, del } from '../api/client'

const STATUSES = ['OWNER', 'ADMIN', 'SENIOR', 'JUNIOR', 'INTERN', 'OTHER', 'INACTIVE']
const MEMBER_ROLES = ['ADMIN', 'SENIOR', 'JUNIOR', 'INTERN', 'OTHER']
const ORG_TYPES = ['Personal', 'Corporation']

const STATUS_COLOR = {
  OWNER: '#c8a951', ADMIN: '#2980b9', SENIOR: '#27ae60',
  JUNIOR: '#8b93b0', INTERN: '#8b93b0', OTHER: '#8b93b0', INACTIVE: '#c0392b',
}

const WRITE_ROLES = new Set(['OWNER', 'ADMIN', 'SENIOR'])

function canWrite(role) { return WRITE_ROLES.has(role) }

// EVE image-server corp logo — derived straight from the corp id, no ESI call.
const corpLogo = (id, size = 64) =>
  id ? `https://images.evetech.net/corporations/${id}/logo?size=${size}` : null

// Look up a corp id against ESI to fill in (link) its real name + ticker.
// `setField('corporation_name', value)` writes back into whichever form is editing.
async function lookupCorp(id, setField, setMsg, setBusy) {
  if (!id) return
  setBusy(true); setMsg('')
  try {
    const info = await get(`/organisations/lookup/corporation/${id}`)
    if (info.name) setField('corporation_name', info.name)
    setMsg(`✓ ${info.name}${info.ticker ? ` [${info.ticker}]` : ''}`)
  } catch (e) { setMsg(e.message) }
  finally { setBusy(false) }
}

function CorpIdField({ id, name, onIdChange, onNameLink }) {
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
  return (
    <>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
        <input type="number" value={id} onChange={onIdChange} placeholder="ESI id" style={{ flex: 1, minWidth: 0 }} />
        <button type="button" className="btn btn-ghost btn-sm"
          onClick={() => lookupCorp(id, (_k, v) => onNameLink(v), setMsg, setBusy)}
          disabled={!id || busy}>
          {busy ? '…' : 'Link'}
        </button>
      </div>
      {id ? (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 6, fontSize: 11, color: 'var(--text)' }}>
          <img src={corpLogo(id, 32)} alt="" width={28} height={28}
            style={{ borderRadius: 4, background: 'var(--surface3)' }} />
          <span>{msg || name || 'Click Link to fetch the corp name'}</span>
        </div>
      ) : null}
    </>
  )
}

export default function OrgsPage() {
  const [orgs, setOrgs]         = useState([])
  const [publicOrgs, setPublicOrgs] = useState([])
  const [form, setForm]         = useState({ name: '', org_type: 'Personal', corporation_name: '', corporation_id: '', is_public: false })
  const [error, setError]       = useState('')
  const [loading, setLoading]   = useState(false)
  const [expanded, setExpanded] = useState(null)

  async function load() {
    try { setOrgs(await get('/organisations')) } catch {}
  }
  async function loadPublic() {
    try {
      const all = await get('/organisations/public')
      // filter out orgs user is already a member/owner of
      setPublicOrgs(all.filter(o => o.my_role == null))
    } catch {}
  }

  useEffect(() => { load(); loadPublic() }, [])

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
        is_public: form.is_public,
      })
      setForm({ name: '', org_type: 'Personal', corporation_name: '', corporation_id: '', is_public: false })
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

  async function joinOrg(orgId) {
    try {
      const joined = await post(`/organisations/${orgId}/join`, {})
      setOrgs(prev => [...prev, joined])
      setPublicOrgs(prev => prev.filter(o => o.id !== orgId))
      setExpanded(joined.id)
    } catch (err) { setError(err.message) }
  }

  function onSaved(updated) {
    setOrgs(prev => prev.map(o => o.id === updated.id ? { ...o, ...updated } : o))
  }

  const setF = k => e => setForm(f => ({ ...f, [k]: e.target.value }))
  const setFBool = k => e => setForm(f => ({ ...f, [k]: e.target.checked }))

  return (
    <div>
      {/* ── Create form ── */}
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
                <CorpIdField
                  id={form.corporation_id}
                  name={form.corporation_name}
                  onIdChange={setF('corporation_id')}
                  onNameLink={v => setForm(f => ({ ...f, corporation_name: v }))}
                />
              </div>
            </>
          )}
          <div style={{ gridColumn: '1 / -1', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: 'var(--text)', cursor: 'pointer' }}>
              <input type="checkbox" checked={form.is_public} onChange={setFBool('is_public')} />
              Public — visible to all users, anyone can join
            </label>
            <button className="btn btn-primary" type="submit" disabled={loading}>
              {loading ? '…' : '+ Create'}
            </button>
          </div>
        </form>
      </div>

      {/* ── My orgs ── */}
      {orgs.length === 0
        ? <div className="empty-state">No organisations yet</div>
        : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {orgs.map(o => (
              <OrgCard key={o.id} org={o} open={expanded === o.id}
                onToggle={() => setExpanded(p => p === o.id ? null : o.id)}
                onDelete={() => deleteOrg(o.id)}
                onSaved={onSaved}
                onLeft={id => { setOrgs(prev => prev.filter(x => x.id !== id)); loadPublic() }}
              />
            ))}
          </div>
        )
      }

      {/* ── Public orgs to discover ── */}
      {publicOrgs.length > 0 && (
        <div style={{ marginTop: 32 }}>
          <div style={{ fontSize: 12, color: 'var(--text)', fontWeight: 600, letterSpacing: 1, marginBottom: 12 }}>
            PUBLIC ORGANISATIONS
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {publicOrgs.map(o => (
              <div key={o.id} style={{
                display: 'flex', alignItems: 'center', gap: 12,
                background: 'var(--surface)', border: '1px solid var(--border)',
                borderRadius: 6, padding: '10px 16px',
              }}>
                <span style={{ color: 'var(--text)', fontSize: 13 }}>#{o.id}</span>
                {o.corporation_logo && (
                  <img src={o.corporation_logo} alt="" width={26} height={26}
                    style={{ borderRadius: 4, background: 'var(--surface3)', flexShrink: 0 }} />
                )}
                <span style={{ color: 'var(--accent)', fontWeight: 500 }}>{o.name}</span>
                <span className="badge" style={{ background: '#1a2a1a', color: '#4caf7d' }}>Public</span>
                <span className="badge" style={{ background: o.org_type === 'Corporation' ? '#10243d' : '#1d2135', color: o.org_type === 'Corporation' ? '#3a9bd6' : '#8b93b0' }}>
                  {o.org_type || 'Personal'}
                </span>
                {o.corporation_name && <span style={{ fontSize: 12, color: 'var(--text)' }}>{o.corporation_name}</span>}
                <span style={{ flex: 1 }} />
                <span style={{ fontSize: 12, color: 'var(--text)' }}>
                  {o.member_count} member{o.member_count !== 1 ? 's' : ''}
                </span>
                <button className="btn btn-primary btn-sm" onClick={() => joinOrg(o.id)}>Join</button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

/* ── Per-org card ── */
function OrgCard({ org, open, onToggle, onDelete, onSaved, onLeft }) {
  const isOwner = org.my_role === 'OWNER'
  const isMember = org.my_role != null
  const canEdit = canWrite(org.my_role)

  const [employees, setEmployees] = useState([])
  const [members, setMembers]     = useState([])
  const [loaded, setLoaded]       = useState(false)
  const [empError, setEmpError]   = useState('')
  const [form, setForm]           = useState({ name: '', character_id: '', status: 'OTHER' })
  const [adding, setAdding]       = useState(false)
  const [editing, setEditing]     = useState(false)
  const [edit, setEdit]           = useState({})
  const [tab, setTab]             = useState('chars')  // 'chars' | 'members'

  useEffect(() => { if (open && !loaded) loadAll() }, [open])

  async function loadAll() {
    try {
      if (isOwner) {
        const [emps, mems] = await Promise.all([
          get(`/organisations/${org.id}/employees`),
          get(`/organisations/${org.id}/members`),
        ])
        setEmployees(emps)
        setMembers(mems)
      }
      setLoaded(true)
    } catch {}
  }

  function startEdit() {
    setEdit({
      name: org.name, org_type: org.org_type || 'Personal',
      corporation_name: org.corporation_name || '', corporation_id: org.corporation_id || '',
      is_public: org.is_public ?? false,
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
        is_public: edit.is_public,
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

  async function updateMemberRole(userId, role) {
    try {
      const updated = await patch(`/organisations/${org.id}/members/${userId}`, { role })
      setMembers(prev => prev.map(m => m.user_id === userId ? updated : m))
    } catch (e) { setEmpError(e.message) }
  }

  async function kickMember(userId) {
    if (!confirm('Remove this member?')) return
    try {
      await del(`/organisations/${org.id}/members/${userId}`)
      setMembers(prev => prev.filter(m => m.user_id !== userId))
    } catch (e) { setEmpError(e.message) }
  }

  async function leaveOrg() {
    if (!confirm('Leave this organisation?')) return
    try {
      await del(`/organisations/${org.id}/leave`)
      onLeft(org.id)
    } catch (e) { setEmpError(e.message) }
  }

  const setF = k => e => setForm(f => ({ ...f, [k]: e.target.value }))
  const setE = k => e => setEdit(f => ({ ...f, [k]: e.target.value }))
  const setEBool = k => e => setEdit(f => ({ ...f, [k]: e.target.checked }))

  return (
    <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 6, overflow: 'hidden' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '12px 18px', cursor: 'pointer', userSelect: 'none' }} onClick={onToggle}>
        <span style={{ color: 'var(--text)', fontSize: 13 }}>#{org.id}</span>
        {org.corporation_logo && (
          <img src={org.corporation_logo} alt="" width={26} height={26}
            style={{ borderRadius: 4, background: 'var(--surface3)', flexShrink: 0 }} />
        )}
        <span style={{ color: 'var(--accent)', fontWeight: 500 }}>{org.name}</span>
        <span className="badge" style={{ background: org.org_type === 'Corporation' ? '#10243d' : '#1d2135', color: org.org_type === 'Corporation' ? '#3a9bd6' : '#8b93b0' }}>
          {org.org_type || 'Personal'}
        </span>
        {org.is_public && (
          <span className="badge" style={{ background: '#1a2a1a', color: '#4caf7d' }}>Public</span>
        )}
        {org.corporation_name && <span style={{ fontSize: 12, color: 'var(--text)' }}>{org.corporation_name}{org.corporation_id ? ` · ${org.corporation_id}` : ''}</span>}
        {org.my_role && (
          <span className="badge" style={{ background: (STATUS_COLOR[org.my_role] || '#8b93b0') + '22', color: STATUS_COLOR[org.my_role] || '#8b93b0' }}>
            {org.my_role}
          </span>
        )}
        <span style={{ flex: 1 }} />
        {org.member_count > 0 && (
          <span style={{ fontSize: 12, color: 'var(--text)' }}>{org.member_count} member{org.member_count !== 1 ? 's' : ''}</span>
        )}
        {canEdit && (
          <button className="btn btn-ghost btn-sm" onClick={e => { e.stopPropagation(); startEdit(); if (!open) onToggle() }}>Edit</button>
        )}
        {isOwner
          ? <button className="btn btn-danger btn-sm" onClick={e => { e.stopPropagation(); onDelete() }}>✕</button>
          : <button className="btn btn-ghost btn-sm" onClick={e => { e.stopPropagation(); leaveOrg() }} style={{ color: '#e05252' }}>Leave</button>
        }
        <span style={{ color: 'var(--text)', fontSize: 14 }}>{open ? '▲' : '▼'}</span>
      </div>

      {/* Body */}
      {open && (
        <div style={{ borderTop: '1px solid var(--border)', padding: '16px 18px', background: 'var(--surface2)' }}>
          {empError && <div className="error-box" style={{ marginBottom: 10 }}>{empError}</div>}

          {/* Edit form — owner only */}
          {editing && isOwner && (
            <div className="card" style={{ marginBottom: 16, background: 'var(--surface)' }}>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(150px,1fr))', gap: 10 }}>
                <div><L>Name</L><input value={edit.name} onChange={setE('name')} /></div>
                <div><L>Type</L>
                  <select value={edit.org_type} onChange={setE('org_type')}>
                    {ORG_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
                  </select>
                </div>
                <div><L>Corp name</L><input value={edit.corporation_name} onChange={setE('corporation_name')} /></div>
                <div><L>Corp ID</L>
                  <CorpIdField
                    id={edit.corporation_id}
                    name={edit.corporation_name}
                    onIdChange={setE('corporation_id')}
                    onNameLink={v => setEdit(f => ({ ...f, corporation_name: v }))}
                  />
                </div>
              </div>
              <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: 'var(--text)', marginTop: 10, cursor: 'pointer' }}>
                <input type="checkbox" checked={edit.is_public} onChange={setEBool('is_public')} />
                Public — visible to all users, anyone can join
              </label>
              <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 12 }}>
                <button className="btn btn-ghost btn-sm" onClick={() => setEditing(false)}>Cancel</button>
                <button className="btn btn-primary btn-sm" onClick={saveEdit}>Save</button>
              </div>
            </div>
          )}

          {/* Tabs — owner sees both chars + members; member sees only chars */}
          {isOwner && (
            <div style={{ display: 'flex', gap: 2, marginBottom: 14 }}>
              {['chars', 'members'].map(t => (
                <button key={t} className={`btn btn-sm ${tab === t ? 'btn-primary' : 'btn-ghost'}`}
                  onClick={() => setTab(t)} style={{ textTransform: 'capitalize', fontSize: 12 }}>
                  {t === 'chars' ? 'EVE Characters' : `Members (${members.length})`}
                </button>
              ))}
            </div>
          )}

          {/* EVE Characters tab */}
          {(!isOwner || tab === 'chars') && (
            <>
              <div style={{ fontSize: 12, color: 'var(--text)', fontWeight: 600, letterSpacing: 1, marginBottom: 14 }}>EVE CHARACTERS</div>
              {employees.length > 0 && (
                <table style={{ marginBottom: 18 }}>
                  <thead><tr><th>Character</th><th>EVE ID</th><th>Role</th><th>Added</th><th></th></tr></thead>
                  <tbody>
                    {employees.map(emp => (
                      <EmployeeRow key={emp.id} emp={emp} onPatch={patchEmployee} onRemove={removeEmployee} readonly={!isOwner} />
                    ))}
                  </tbody>
                </table>
              )}
              {!isMember && employees.length === 0 && (
                <div style={{ color: 'var(--text)', fontSize: 12, marginBottom: 16 }}>No characters yet</div>
              )}
              {isOwner && (
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
              )}
              {!isOwner && (
                <div style={{ fontSize: 12, color: 'var(--text)', fontStyle: 'italic', marginTop: 8 }}>
                  {canEdit
                    ? 'You have read/write access as ' + org.my_role
                    : 'Read-only access · You can view inventory, use facilities for calculations · Role: ' + org.my_role}
                </div>
              )}
            </>
          )}

          {/* Members tab — owner only */}
          {isOwner && tab === 'members' && (
            <>
              <div style={{ fontSize: 12, color: 'var(--text)', fontWeight: 600, letterSpacing: 1, marginBottom: 14 }}>USER MEMBERS</div>
              {members.length === 0
                ? <div style={{ color: 'var(--text)', fontSize: 12, marginBottom: 12 }}>No members yet — make the org public so users can join</div>
                : (
                  <table style={{ marginBottom: 18 }}>
                    <thead><tr><th>Username</th><th>Role</th><th>Joined</th><th></th></tr></thead>
                    <tbody>
                      {members.map(m => (
                        <tr key={m.user_id}>
                          <td style={{ color: 'var(--text-white)' }}>{m.username}</td>
                          <td style={{ minWidth: 130 }}>
                            <select
                              value={m.role}
                              onChange={e => updateMemberRole(m.user_id, e.target.value)}
                              style={{ color: STATUS_COLOR[m.role] || 'var(--text)', background: 'var(--surface3)', border: '1px solid var(--border2)', padding: '3px 6px', fontSize: 12, width: '100%' }}>
                              {MEMBER_ROLES.map(r => <option key={r} value={r}>{r}</option>)}
                            </select>
                          </td>
                          <td style={{ color: 'var(--text)', fontSize: 12 }}>{new Date(m.joined_at).toLocaleDateString()}</td>
                          <td>
                            <button className="btn btn-danger btn-sm" onClick={() => kickMember(m.user_id)}>✕</button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )
              }
              <div style={{ fontSize: 12, color: 'var(--text)', fontStyle: 'italic' }}>
                SENIOR and above can edit projects, packs and org info. JUNIOR and below have read-only access.
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}

function EmployeeRow({ emp, onPatch, onRemove, readonly }) {
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
        {readonly
          ? <span style={{ color: STATUS_COLOR[emp.status] || 'var(--text)', fontSize: 12 }}>{emp.status}</span>
          : (
            <select value={emp.status} onChange={e => onPatch(emp.id, { status: e.target.value })}
              style={{ color: STATUS_COLOR[emp.status] || 'var(--text)', background: 'var(--surface3)', border: '1px solid var(--border2)', padding: '3px 6px', fontSize: 12, width: '100%' }}>
              {STATUSES.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          )
        }
      </td>
      <td style={{ color: 'var(--text)', fontSize: 12 }}>{new Date(emp.added_at).toLocaleDateString()}</td>
      <td style={{ whiteSpace: 'nowrap' }}>
        {!readonly && (
          <>
            <button className="btn btn-ghost btn-sm" onClick={() => setEditing(true)} style={{ marginRight: 4 }}>Edit</button>
            <button className="btn btn-danger btn-sm" onClick={() => onRemove(emp.id)}>✕</button>
          </>
        )}
      </td>
    </tr>
  )
}

function L({ children }) {
  return <label style={{ display: 'block', fontSize: 11, color: 'var(--text)', marginBottom: 5 }}>{children}</label>
}
