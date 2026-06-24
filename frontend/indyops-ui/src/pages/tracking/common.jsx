// Shared building blocks for the Tracking income tabs (Deliverly / Mission / Ratting):
// the character/group scope selector, date-range picker, summary stat cards, an
// ESI-sync button and a generic sortable table. Mirrors the patterns in OrdersTracking.
import { useState, useEffect, useMemo } from 'react'
import { post } from '../../api/client'
import { fmtIsk } from './fmt'

export function ScopeSelect({ scope, setScope, chars, groups }) {
  return (
    <select value={scope} onChange={e => setScope(e.target.value)} style={{ padding: '7px 10px', minWidth: 200 }}>
      <option value="all">All characters</option>
      {groups.length > 0 && (
        <optgroup label="Groups">{groups.map(g => <option key={g} value={`group:${g}`}>{g}</option>)}</optgroup>
      )}
      <optgroup label="Characters">
        {chars.map(c => <option key={c.id} value={`char:${c.id}`}>{c.character_name}</option>)}
      </optgroup>
    </select>
  )
}

export function DateRange({ start, end, setStart, setEnd }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
      <input type="date" value={start} onChange={e => setStart(e.target.value)} style={{ padding: '6px 8px' }} />
      <span style={{ color: 'var(--text)' }}>→</span>
      <input type="date" value={end} onChange={e => setEnd(e.target.value)} style={{ padding: '6px 8px' }} />
      {(start || end) && (
        <button className="btn btn-ghost btn-sm" onClick={() => { setStart(''); setEnd('') }}>Clear</button>
      )}
    </span>
  )
}

export function Stat({ label, value, accent }) {
  return (
    <div style={{ minWidth: 0 }}>
      <div style={{ fontSize: 11, color: 'var(--text)', textTransform: 'uppercase', letterSpacing: 0.4 }}>{label}</div>
      <div style={{ fontSize: 15, color: accent ? 'var(--accent)' : 'var(--text-white)', fontWeight: 600 }}>{value}</div>
    </div>
  )
}

export function StatRow({ children }) {
  return <div className="card" style={{ marginBottom: 18, display: 'flex', flexWrap: 'wrap', gap: 28 }}>{children}</div>
}

// Rate-limited "Sync from ESI" button (reuses /account/sync). Calls onDone after a delay
// so freshly-synced data shows up.
export function SyncButton({ scope, onDone }) {
  const [left, setLeft] = useState(0)
  const [msg, setMsg] = useState('')
  useEffect(() => {
    if (left <= 0) return undefined
    const id = setTimeout(() => setLeft(left - 1), 1000)
    return () => clearTimeout(id)
  }, [left])
  async function doSync() {
    setMsg('')
    try {
      const r = await post('/account/sync', { scope })
      setLeft(60)
      setMsg(`Sync started for ${r.characters} char(s) — refreshing shortly…`)
      if (onDone) setTimeout(onDone, 20000)
    } catch (e) { setMsg(e.message) }
  }
  return (
    <>
      <button className="btn btn-ghost btn-sm" onClick={doSync} disabled={left > 0}>
        {left > 0 ? `Sync (${left}s)` : '⟳ Sync from ESI'}
      </button>
      {msg && <span style={{ fontSize: 12, color: 'var(--text-bright)' }}>{msg}</span>}
    </>
  )
}

export function ScopeWarning({ names }) {
  if (!names || !names.length) return null
  return (
    <div className="card" style={{ marginBottom: 16, borderColor: 'var(--accent-dim)', display: 'flex', gap: 10, alignItems: 'center' }}>
      <span style={{ color: '#c8a951' }}>⚠</span>
      <span style={{ fontSize: 13, color: 'var(--text-bright)' }}>
        Re-link to grant the wallet scope for: {names.join(', ')}. Income for them won't appear until then.
      </span>
    </div>
  )
}

// Generic click-to-sort table. Columns: {key, label, num?, field?, sortVal?, render?}.
export function SortableTable({ columns, rows, rowKey, empty = 'Nothing here yet.' }) {
  const [sort, setSort] = useState({ key: null, dir: 1 })
  const sorted = useMemo(() => {
    if (!sort.key) return rows
    const col = columns.find(c => c.key === sort.key)
    if (!col) return rows
    const val = col.sortVal || (r => r[col.field ?? col.key])
    return [...rows].sort((a, b) => {
      const av = val(a), bv = val(b)
      if (av == null && bv == null) return 0
      if (av == null) return 1
      if (bv == null) return -1
      if (typeof av === 'string') return av.localeCompare(bv) * sort.dir
      return (av - bv) * sort.dir
    })
  }, [rows, sort, columns])
  const toggle = k => setSort(s => (s.key === k ? { key: k, dir: -s.dir } : { key: k, dir: 1 }))
  if (!rows.length) return <div className="empty-state" style={{ padding: '28px 16px' }}>{empty}</div>
  return (
    <div style={{ overflowX: 'auto' }}>
      <table>
        <thead>
          <tr>
            {columns.map(c => (
              <th key={c.key} onClick={() => toggle(c.key)} style={{ cursor: 'pointer', textAlign: c.num ? 'right' : 'left' }}>
                {c.label}{' '}
                <span style={{ opacity: 0.45, fontSize: 10 }}>{sort.key === c.key ? (sort.dir > 0 ? '▲' : '▼') : '▴'}</span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((r, i) => (
            <tr key={rowKey(r, i)}>
              {columns.map(c => (
                <td key={c.key} style={{ textAlign: c.num ? 'right' : 'left', whiteSpace: 'nowrap' }}>
                  {c.render ? c.render(r) : (r[c.field ?? c.key] ?? '—')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// Tiny per-day bar chart for an income series ([{date, <valueKey>}…]).
export function MiniBars({ series, valueKey = 'total', label }) {
  if (!series || !series.length) return null
  const max = Math.max(...series.map(s => s[valueKey] || 0)) || 1
  return (
    <div className="card" style={{ marginBottom: 18 }}>
      {label && <div className="sec-label" style={{ marginBottom: 10 }}>{label}</div>}
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 3, height: 110, overflowX: 'auto', paddingBottom: 2 }}>
        {series.map(s => (
          <div key={s.date} title={`${s.date}: ${fmtIsk(s[valueKey])}`}
            style={{ display: 'flex', flexDirection: 'column', justifyContent: 'flex-end', minWidth: 12, height: '100%' }}>
            <div style={{ width: 10, height: `${Math.max(2, (s[valueKey] || 0) / max * 100)}%`, background: 'var(--accent)', borderRadius: '2px 2px 0 0' }} />
          </div>
        ))}
      </div>
    </div>
  )
}
