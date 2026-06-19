import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { post } from '../api/client'

export default function RegisterPage() {
  const nav = useNavigate()
  const [form, setForm] = useState({ username: '', email: '', password: '' })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function submit(e) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await post('/register', form)
      nav('/login')
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const set = key => e => setForm(f => ({ ...f, [key]: e.target.value }))

  return (
    <div style={styles.wrap}>
      <div style={styles.box}>
        <div style={styles.logo}>INDY<span style={{ color: 'var(--accent)' }}>OPS</span></div>
        <p style={{ color: 'var(--text)', marginBottom: 24, fontSize: 13 }}>Create account</p>

        {error && <div className="error-box">{error}</div>}

        <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div>
            <label htmlFor="reg-username" style={styles.label}>Username</label>
            <input id="reg-username" value={form.username} onChange={set('username')} placeholder="pilot_name" required autoFocus />
          </div>
          <div>
            <label htmlFor="reg-email" style={styles.label}>Email</label>
            <input id="reg-email" type="email" value={form.email} onChange={set('email')} placeholder="you@example.com" required />
          </div>
          <div>
            <label htmlFor="reg-password" style={styles.label}>Password</label>
            <input id="reg-password" type="password" value={form.password} onChange={set('password')} placeholder="••••••••" required />
          </div>
          <button className="btn btn-primary" type="submit" disabled={loading} style={{ marginTop: 6 }}>
            {loading ? 'Creating…' : 'Register'}
          </button>
        </form>

        <p style={{ marginTop: 20, fontSize: 12, color: 'var(--text)' }}>
          Have an account? <Link to="/login">Log in</Link>
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
