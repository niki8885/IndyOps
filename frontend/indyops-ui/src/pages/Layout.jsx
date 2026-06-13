import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../store/AuthContext'

const NAV = [
  { to: '/manufacturing', label: 'Manufacturing'  },
  { to: '/inventory',     label: 'Inventory'      },
  { to: '/facilities',    label: 'Facilities'     },
  { to: '/projects',      label: 'Projects'       },
  { to: '/orgs',          label: 'Organisations'  },
]

export default function Layout() {
  const { user, logout } = useAuth()

  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100vh' }}>
      {/* top bar */}
      <header style={s.header}>
        <span style={s.logo}>INDY<span style={{ color: 'var(--accent)' }}>OPS</span></span>
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
    fontSize: 18, fontWeight: 700, letterSpacing: 3,
    color: 'var(--text-white)', whiteSpace: 'nowrap',
  },
  nav: { display: 'flex', gap: 4, flex: 1 },
  navLink: {
    padding: '16px 14px', fontSize: 13, fontWeight: 500,
    transition: '.15s', textDecoration: 'none', whiteSpace: 'nowrap',
  },
  userArea: { display: 'flex', alignItems: 'center', gap: 14, marginLeft: 'auto' },
  main: { flex: 1, padding: '28px 32px', maxWidth: 1400, width: '100%', margin: '0 auto' },
}
