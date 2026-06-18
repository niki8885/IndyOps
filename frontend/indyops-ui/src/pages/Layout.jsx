import { useState, useEffect } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import logoSrc from '../assets/logo.png'
import { useAuth } from '../store/AuthContext'
import { get, post } from '../api/client'

const NAV = [
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
          <span style={{ color: 'var(--text)', fontSize: 13 }}>{user?.username}</span>
          <button className="btn btn-ghost btn-sm" onClick={logout}>Logout</button>
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
}
