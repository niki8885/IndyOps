import { useState, useEffect } from 'react'
import { get, post, patch, del } from '../api/client'
import SystemSearch from '../components/SystemSearch'
import TypeSearch from '../components/TypeSearch'

const TYPES = ['Raitaru', 'Azbel', 'Sotiyo', 'Other']

const TYPE_COLOR = {
  Raitaru: '#4caf7d',
  Azbel:   '#c8a951',
  Sotiyo:  '#e05252',
  Other:   '#8b93b0',
}

const EMPTY_FORM = {
  name: '', facility_type: 'Raitaru',
  tax: '', cost_bonus: '', system_name: '', system_cost_index: '',
  rig1: { type_id: null, name: null },
  rig2: { type_id: null, name: null },
  rig3: { type_id: null, name: null },
}

export default function FacilitiesPage() {
  const [facilities, setFacilities] = useState([])
  const [showForm, setShowForm]     = useState(false)
  const [editId, setEditId]         = useState(null)
  const [form, setForm]             = useState(EMPTY_FORM)
  const [error, setError]           = useState('')
  const [loading, setLoading]       = useState(false)
  const [filter, setFilter]         = useState('')
  const [sciLoading, setSciLoading] = useState(false)
  const [sciInfo, setSciInfo]       = useState('')

  async function load() {
    try {
      const params = filter ? `?facility_type=${filter}` : ''
      const data = await get(`/facilities${params}`)
      setFacilities(data)
    } catch {}
  }

  useEffect(() => { load() }, [filter])

  function openCreate() {
    setEditId(null)
    setForm(EMPTY_FORM)
    setError('')
    setSciInfo('')
    setShowForm(true)
  }

  function openEdit(f) {
    setEditId(f.id)
    setForm({
      name: f.name,
      facility_type: f.facility_type,
      tax: f.tax ?? '',
      cost_bonus: f.cost_bonus ?? '',
      system_name: f.system_name ?? '',
      system_cost_index: f.system_cost_index ?? '',
      rig1: { type_id: f.rig1.type_id, name: f.rig1.name },
      rig2: { type_id: f.rig2.type_id, name: f.rig2.name },
      rig3: { type_id: f.rig3.type_id, name: f.rig3.name },
    })
    setError('')
    setSciInfo('')
    setShowForm(true)
  }

  async function submit(e) {
    e.preventDefault()
    setError('')
    setLoading(true)

    const body = {
      name:              form.name,
      facility_type:     form.facility_type,
      tax:               form.tax !== '' ? Number(form.tax) : null,
      cost_bonus:        form.cost_bonus !== '' ? Number(form.cost_bonus) : null,
      system_name:       form.system_name || null,
      system_cost_index: form.system_cost_index !== '' ? Number(form.system_cost_index) : null,
      rig1: form.rig1.name ? form.rig1 : null,
      rig2: form.rig2.name ? form.rig2 : null,
      rig3: form.rig3.name ? form.rig3 : null,
    }

    try {
      if (editId) {
        await patch(`/facilities/${editId}`, body)
      } else {
        await post('/facilities', body)
      }
      setShowForm(false)
      setEditId(null)
      load()
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  async function remove(id) {
    if (!confirm('Delete facility?')) return
    try { await del(`/facilities/${id}`); load() } catch {}
  }

  const set = k => v => setForm(f => ({ ...f, [k]: v }))
  const setInput = k => e => setForm(f => ({ ...f, [k]: e.target.value }))

  async function fetchSci(systemName) {
    if (!systemName) return
    setSciLoading(true); setSciInfo('')
    try {
      const r = await get(`/eve/industry/cost-index?system_name=${encodeURIComponent(systemName)}`)
      if (r.manufacturing != null) {
        setForm(f => ({ ...f, system_cost_index: r.manufacturing }))
        setSciInfo(`✓ ${(r.manufacturing * 100).toFixed(2)}% manufacturing${r.reaction != null ? ` · ${(r.reaction * 100).toFixed(2)}% reaction` : ''}`)
      } else {
        setSciInfo('No manufacturing index for this system')
      }
    } catch (e) {
      setSciInfo('⚠ ' + e.message)
    } finally {
      setSciLoading(false)
    }
  }

  // when a system is chosen, store name and auto-fetch its cost index
  function onSystemChange(name) {
    setForm(f => ({ ...f, system_name: name }))
    setSciInfo('')
    if (name) fetchSci(name)
  }

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 24 }}>
        <h2>Facilities</h2>
        <select value={filter} onChange={e => setFilter(e.target.value)} style={{ width: 160 }}>
          <option value="">All types</option>
          {TYPES.map(t => <option key={t} value={t}>{t}</option>)}
        </select>
        <button className="btn btn-primary btn-sm" onClick={openCreate}>+ Add facility</button>
      </div>

      {/* ── Form ── */}
      {showForm && (
        <div className="card" style={{ marginBottom: 24, maxWidth: 640 }}>
          <h3 style={{ marginBottom: 18, fontSize: 14 }}>
            {editId ? 'Edit Facility' : 'New Facility'}
          </h3>
          {error && <div className="error-box">{error}</div>}

          <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            {/* Row 1: name + type */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 160px', gap: 12 }}>
              <div>
                <Label>Name</Label>
                <input value={form.name} onChange={setInput('name')} placeholder="My Raitaru" required />
              </div>
              <div>
                <Label>Type</Label>
                <select value={form.facility_type} onChange={setInput('facility_type')}>
                  {TYPES.map(t => <option key={t} value={t}>{t}</option>)}
                </select>
              </div>
            </div>

            {/* Row 2: system + SCI */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 160px', gap: 12 }}>
              <div>
                <Label>System</Label>
                <SystemSearch
                  value={form.system_name}
                  onChange={onSystemChange}
                  placeholder="Jita, Amarr…"
                />
              </div>
              <div>
                <Label>
                  System Cost Index
                  {sciLoading ? <Hint>fetching…</Hint> : <Hint>auto from ESI</Hint>}
                </Label>
                <input
                  type="number" step="0.0001" min="0" max="1"
                  value={form.system_cost_index}
                  onChange={setInput('system_cost_index')}
                  placeholder="0.042"
                />
                {sciInfo && (
                  <div style={{ fontSize: 11, marginTop: 4, color: sciInfo.startsWith('⚠') ? '#e05252' : '#4caf7d' }}>
                    {sciInfo}
                  </div>
                )}
              </div>
            </div>

            {/* Row 3: tax + cost bonus */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              <div>
                <Label>Tax % <Hint>facility/broker tax</Hint></Label>
                <input
                  type="number" step="0.01" min="0" max="100"
                  value={form.tax} onChange={setInput('tax')} placeholder="0.00"
                />
              </div>
              <div>
                <Label>Cost Bonus % <Hint>rig/structure bonus</Hint></Label>
                <input
                  type="number" step="0.01" min="0" max="100"
                  value={form.cost_bonus} onChange={setInput('cost_bonus')} placeholder="0.00"
                />
              </div>
            </div>

            {/* Rigs */}
            <div style={{ borderTop: '1px solid var(--border)', paddingTop: 14 }}>
              <Label>Rigs</Label>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 8 }}>
                {[1, 2, 3].map(n => (
                  <div key={n} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ width: 40, fontSize: 12, color: 'var(--text)', flexShrink: 0 }}>Rig {n}</span>
                    <TypeSearch
                      value={{ name: form[`rig${n}`].name }}
                      onChange={set(`rig${n}`)}
                      placeholder="Search rig…"
                    />
                  </div>
                ))}
              </div>
            </div>

            <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 4 }}>
              <button type="button" className="btn btn-ghost" onClick={() => setShowForm(false)}>Cancel</button>
              <button type="submit" className="btn btn-primary" disabled={loading}>
                {loading ? 'Saving…' : editId ? 'Update' : 'Create'}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* ── Table ── */}
      {facilities.length === 0
        ? <div className="empty-state">No facilities added yet</div>
        : (
          <div className="card" style={{ padding: 0 }}>
            <table>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Type</th>
                  <th>System</th>
                  <th>SCI</th>
                  <th>Tax %</th>
                  <th>Bonus %</th>
                  <th>Rig 1</th>
                  <th>Rig 2</th>
                  <th>Rig 3</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {facilities.map(f => (
                  <tr key={f.id}>
                    <td style={{ color: 'var(--text-white)', fontWeight: 500 }}>{f.name}</td>
                    <td>
                      <span style={{
                        fontSize: 11, fontWeight: 700, padding: '2px 8px',
                        borderRadius: 3, background: TYPE_COLOR[f.facility_type] + '22',
                        color: TYPE_COLOR[f.facility_type],
                      }}>
                        {f.facility_type}
                      </span>
                    </td>
                    <td style={{ color: 'var(--text)' }}>{f.system_name || '—'}</td>
                    <td style={{ color: 'var(--accent)', fontFamily: 'monospace' }}>
                      {f.system_cost_index != null ? (f.system_cost_index * 100).toFixed(2) + '%' : '—'}
                    </td>
                    <td style={{ color: 'var(--text)' }}>
                      {f.tax != null ? f.tax + '%' : '—'}
                    </td>
                    <td style={{ color: '#4caf7d' }}>
                      {f.cost_bonus != null ? '-' + f.cost_bonus + '%' : '—'}
                    </td>
                    <RigCell rig={f.rig1} />
                    <RigCell rig={f.rig2} />
                    <RigCell rig={f.rig3} />
                    <td style={{ whiteSpace: 'nowrap' }}>
                      <button className="btn btn-ghost btn-sm" onClick={() => openEdit(f)} style={{ marginRight: 4 }}>Edit</button>
                      <button className="btn btn-danger btn-sm" onClick={() => remove(f.id)}>✕</button>
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

function RigCell({ rig }) {
  if (!rig?.name) return <td style={{ color: 'var(--border2)' }}>—</td>
  return (
    <td style={{ fontSize: 11, color: 'var(--text)', maxWidth: 140, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
        title={rig.name}>
      {rig.name}
    </td>
  )
}

function Label({ children }) {
  return <label style={{ display: 'block', fontSize: 11, color: 'var(--text)', marginBottom: 5 }}>{children}</label>
}

function Hint({ children }) {
  return <span style={{ fontWeight: 400, color: 'var(--border2)', marginLeft: 4 }}>{children}</span>
}
