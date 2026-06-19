import { useState, useEffect, useRef } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import logoSrc from '../assets/logo.png'
import { useAuth } from '../store/AuthContext'
import { get, post } from '../api/client'

const NAV = [
  { to: '/agenda',        label: 'Agenda'         },
  { to: '/manufacturing', label: 'Manufacturing'  },
  { to: '/ore',           label: 'Ore & Refining' },
  { to: '/inventory',     label: 'Inventory'      },
  { to: '/market',        label: 'Market'         },
  { to: '/analysis',      label: 'Analysis'       },
  { to: '/organisations', label: 'Organisations'  },
  { to: '/personal',      label: 'Personal File'  },
]

export default function Layout() {
  const { user, logout } = useAuth()
  const [sdeStatus, setSdeStatus]   = useState(null)   // null | {synced, type_count}
  const [syncing, setSyncing]       = useState(false)
  const [syncMsg, setSyncMsg]       = useState('')

  useEffect(() => {
    get('/eve/sde/status').then(setSdeStatus).catch(() => {})
  }, [])

  async function triggerSync() {
    setSyncing(true); setSyncMsg('')
    try {
      const r = await post('/eve/sde/update', {})
      setSyncMsg(r.message)
      // poll until synced
      const poll = setInterval(async () => {
        try {
          const s = await get('/eve/sde/status')
          setSdeStatus(s)
          if (s.synced) { clearInterval(poll); setSyncing(false) }
        } catch {}
      }, 30000)
    } catch (e) { setSyncMsg(e.message); setSyncing(false) }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100vh' }}>
      {/* top bar */}
      <header style={s.header}>
        <img src={logoSrc} alt="IndyOps" style={s.logo} />
        <nav style={s.nav}>
          {NAV.map(n => (
            <NavLink
              key={n.to}
              to={n.to}
              style={({ isActive }) => ({
                ...s.navLink,
                color: isActive ? 'var(--accent)' : 'var(--text)',
                borderBottom: isActive ? '2px solid var(--accent)' : '2px solid transparent',
              })}
            >
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div style={s.userArea}>
          <AccountMenu user={user} logout={logout} />
        </div>
      </header>

      {/* SDE warning banner */}
      {sdeStatus && !sdeStatus.synced && (
        <div style={{
          background: '#2a1800', borderBottom: '1px solid #5a3500',
          padding: '8px 32px', display: 'flex', alignItems: 'center', gap: 14, fontSize: 13,
        }}>
          <span style={{ color: '#c8a951' }}>
            ⚠ EVE database not synced — system / item search will not work
          </span>
          <button
            className="btn btn-ghost btn-sm"
            onClick={triggerSync}
            disabled={syncing}
            style={{ borderColor: '#c8a951', color: '#c8a951' }}
          >
            {syncing ? 'Syncing…' : '⚡ Sync EVE SDE'}
          </button>
          {syncMsg && <span style={{ color: 'var(--text)', fontSize: 12 }}>{syncMsg}</span>}
        </div>
      )}

      {/* content */}
      <main style={s.main}>
        <Outlet />
      </main>
    </div>
  )
}

function AccountMenu({ user, logout }) {
  const [open, setOpen]   = useState(false)
  const [modal, setModal] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    if (!open) return
    const onDoc = e => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open])

  return (
    <div ref={ref} style={{ position: 'relative' }}>
      <button className="btn btn-ghost btn-sm" onClick={() => setOpen(o => !o)}
        style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span style={{ color: 'var(--text-bright)', fontSize: 13 }}>{user?.username || 'Account'}</span>
        <span style={{ fontSize: 9 }}>▾</span>
      </button>
      {open && (
        <div style={s.menu}>
          <button style={s.menuItem} onClick={() => { setOpen(false); setModal(true) }}>Account settings</button>
          <button style={s.menuItem} onClick={logout}>Log out</button>
        </div>
      )}
      {modal && <AccountModal onClose={() => setModal(false)} />}
    </div>
  )
}

function AccountModal({ onClose }) {
  const [me, setMe] = useState(null)
  useEffect(() => {
    let alive = true
    get('/me').then(d => { if (alive) setMe(d) }).catch(() => {})
    return () => { alive = false }
  }, [])

  return (
    <div onClick={onClose} style={s.overlay}>
      <div onClick={e => e.stopPropagation()} className="card" style={{ width: 380, maxWidth: '90vw' }}>
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 16 }}>
          <h3 style={{ margin: 0 }}>Account settings</h3>
          <button className="btn btn-ghost btn-sm" style={{ marginLeft: 'auto' }} onClick={onClose}>✕</button>
        </div>
        <Row label="Username" value={me?.username} />
        <Row label="Email" value={me?.email} />
      </div>
    </div>
  )
}

function Row({ label, value }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '110px 1fr', gap: 8, padding: '8px 0', borderBottom: '1px solid var(--border)' }}>
      <span style={{ fontSize: 12, color: 'var(--text)' }}>{label}</span>
      <span style={{ fontSize: 13, color: 'var(--text-white)', wordBreak: 'break-all' }}>{value || '—'}</span>
    </div>
  )
}

const s = {
  header: {
    display: 'flex', alignItems: 'center', gap: 32,
    padding: '0 28px', height: 52,
    background: 'var(--surface)', borderBottom: '1px solid var(--border)',
    flexShrink: 0,
  },
  logo: {
    height: 32, width: 'auto', display: 'block', flexShrink: 0,
  },
  nav: { display: 'flex', gap: 4, flex: 1 },
  navLink: {
    padding: '16px 14px', fontSize: 13, fontWeight: 500,
    transition: '.15s', textDecoration: 'none', whiteSpace: 'nowrap',
  },
  userArea: { display: 'flex', alignItems: 'center', gap: 14, marginLeft: 'auto' },
  main: { flex: 1, padding: '28px 32px', maxWidth: 1400, width: '100%', margin: '0 auto' },
  menu: {
    position: 'absolute', right: 0, top: 'calc(100% + 6px)', minWidth: 170, zIndex: 50,
    background: 'var(--surface2)', border: '1px solid var(--border2)', borderRadius: 6,
    padding: 4, boxShadow: '0 8px 24px rgba(0,0,0,.4)',
  },
  menuItem: {
    display: 'block', width: '100%', textAlign: 'left', background: 'none', border: 'none',
    color: 'var(--text-bright)', padding: '8px 12px', fontSize: 13, cursor: 'pointer', borderRadius: 4,
  },
  overlay: {
    position: 'fixed', inset: 0, zIndex: 100, background: 'rgba(0,0,0,.55)',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
  },
}
