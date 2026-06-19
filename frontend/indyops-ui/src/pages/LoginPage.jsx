import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useAuth } from '../store/AuthContext'

export default function LoginPage() {
  const { login } = useAuth()
  const nav = useNavigate()
  const [form, setForm] = useState({ username: '', password: '' })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function submit(e) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await login(form.username, form.password)
      nav('/')
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={styles.wrap}>
      <div style={styles.box}>
        <div style={styles.logo}>INDY<span style={{ color: 'var(--accent)' }}>OPS</span></div>
        <p style={{ color: 'var(--text)', marginBottom: 24, fontSize: 13 }}>Industry Operations Manager</p>

        {error && <div className="error-box">{error}</div>}

        <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div>
            <label htmlFor="login-username" style={styles.label}>Username</label>
            <input
              id="login-username"
              value={form.username}
              onChange={e => setForm(f => ({ ...f, username: e.target.value }))}
              placeholder="pilot_name"
              required
              autoFocus
            />
          </div>
          <div>
            <label htmlFor="login-password" style={styles.label}>Password</label>
            <input
              id="login-password"
              type="password"
              value={form.password}
              onChange={e => setForm(f => ({ ...f, password: e.target.value }))}
              placeholder="••••••••"
              required
            />
          </div>
          <button className="btn btn-primary" type="submit" disabled={loading} style={{ marginTop: 6 }}>
            {loading ? 'Logging in…' : 'Log In'}
          </button>
        </form>

        <p style={{ marginTop: 20, fontSize: 12, color: 'var(--text)' }}>
          No account? <Link to="/register">Register</Link>
        </p>
      </div>
    </div>
  )
}

const styles = {
  wrap: {
    minHeight: '100vh', display: 'flex', alignItems: 'center',
    justifyContent: 'center', background: 'var(--bg)',
  },
  box: {
    width: 360, padding: 36,
    background: 'var(--surface)', border: '1px solid var(--border)',
    borderRadius: 8, textAlign: 'center',
  },
  logo: {
    fontSize: 28, fontWeight: 700, letterSpacing: 4,
    color: 'var(--text-white)', marginBottom: 6,
  },
  label: {
    display: 'block', fontSize: 12, color: 'var(--text)',
    marginBottom: 5, textAlign: 'left',
  },
}
