import { useState, useEffect } from 'react'
import { get, post } from '../api/client'

export default function OrgsPage() {
  const [orgs, setOrgs] = useState([])
  const [name, setName] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function load() {
    try {
      const data = await get('/organisations')
      setOrgs(data)
    } catch {}
  }

  useEffect(() => { load() }, [])

  async function create(e) {
    e.preventDefault()
    if (!name.trim()) return
    setError('')
    setLoading(true)
    try {
      await post('/organisations', { name: name.trim() })
      setName('')
      load()
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <h2 style={{ marginBottom: 24 }}>Organisations</h2>

      <div className="card" style={{ maxWidth: 480, marginBottom: 28 }}>
        <h3 style={{ marginBottom: 16, fontSize: 14 }}>Create Organisation</h3>
        {error && <div className="error-box">{error}</div>}
        <form onSubmit={create} style={{ display: 'flex', gap: 10 }}>
          <input
            value={name}
            onChange={e => setName(e.target.value)}
            placeholder="Organisation name"
            required
          />
          <button className="btn btn-primary" type="submit" disabled={loading} style={{ whiteSpace: 'nowrap' }}>
            {loading ? '…' : '+ Create'}
          </button>
        </form>
      </div>

      {orgs.length === 0
        ? <div className="empty-state">No organisations yet</div>
        : (
          <div className="card">
            <table>
              <thead>
                <tr>
                  <th>#</th>
                  <th>Name</th>
                  <th>Created</th>
                </tr>
              </thead>
              <tbody>
                {orgs.map(o => (
                  <tr key={o.id}>
                    <td style={{ color: 'var(--text)', width: 48 }}>{o.id}</td>
                    <td style={{ color: 'var(--accent)' }}>{o.name}</td>
                    <td style={{ color: 'var(--text)', fontSize: 12 }}>
                      {new Date(o.created_at).toLocaleDateString()}
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
