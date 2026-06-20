import { useState, useMemo } from 'react'
import { useApi, fmtNum } from './common'

// Blueprint types have no `/icon` render (it 404s) — use the blueprint art:
// `/bp` for originals, `/bpc` for copies.
const bpIcon = (id, isBpo, size = 32) =>
  `https://images.evetech.net/types/${id}/${isBpo ? 'bp' : 'bpc'}?size=${size}`

const COLS = [
  { key: 'type_name',     label: 'Blueprint' },
  { key: 'kind',          label: 'Kind' },
  { key: 'me',            label: 'ME', num: true },
  { key: 'te',            label: 'TE', num: true },
  { key: 'runs',          label: 'Runs', num: true },
  { key: 'count',         label: 'Qty', num: true },
  { key: 'product_name',  label: 'Produces' },
  { key: 'location_name', label: 'Location' },
]

export default function BlueprintsTab({ charId }) {
  const { data, loading, error } = useApi(`/characters/${charId}/blueprints`, [charId])
  const [q, setQ]         = useState('')
  const [kind, setKind]   = useState('all')        // all | bpo | bpc
  const [sort, setSort]   = useState({ key: 'location_name', dir: 1 })

  const rows = useMemo(() => {
    let r = data || []
    if (kind !== 'all') r = r.filter(b => (kind === 'bpo') === !!b.is_bpo)
    const needle = q.trim().toLowerCase()
    if (needle) {
      r = r.filter(b =>
        (b.type_name || '').toLowerCase().includes(needle) ||
        (b.product_name || '').toLowerCase().includes(needle) ||
        (b.location_name || '').toLowerCase().includes(needle))
    }
    const { key, dir } = sort
    const val = (b) => key === 'kind' ? (b.is_bpo ? 0 : 1)
      : key === 'runs' ? (b.is_bpo ? Infinity : (b.runs ?? 0))
      : b[key]
    return [...r].sort((a, b) => {
      const av = val(a), bv = val(b)
      if (av == null && bv == null) return 0
      if (av == null) return 1
      if (bv == null) return -1
      if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * dir
      return String(av).localeCompare(String(bv)) * dir
    })
  }, [data, q, kind, sort])

  if (loading) return <div className="empty-state">Loading…</div>
  if (error)   return <div className="error-box">{error}</div>

  const all = data || []
  const bpos = all.filter(b => b.is_bpo).length
  const bpcs = all.length - bpos

  function toggleSort(key) {
    setSort(s => s.key === key ? { key, dir: -s.dir } : { key, dir: 1 })
  }

  return (
    <div>
      <div style={{ display: 'flex', gap: 14, alignItems: 'center', flexWrap: 'wrap', marginBottom: 14 }}>
        <span style={{ color: 'var(--text)', fontSize: 13 }}>
          {all.length} blueprint(s) · <b style={{ color: 'var(--text-bright)' }}>{bpos}</b> BPO ·{' '}
          <b style={{ color: 'var(--text-bright)' }}>{bpcs}</b> BPC
        </span>
        <div className="tabs" style={{ margin: 0 }}>
          {[['all', 'All'], ['bpo', 'BPO'], ['bpc', 'BPC']].map(([v, label]) => (
            <button key={v} className={`tab-btn ${kind === v ? 'active' : ''}`}
              onClick={() => setKind(v)} style={{ padding: '3px 12px' }}>{label}</button>
          ))}
        </div>
        <input placeholder="Filter by name / product / location…" value={q} onChange={e => setQ(e.target.value)}
          style={{ flex: '1 1 240px', minWidth: 180 }} />
      </div>

      {all.length === 0 ? (
        <div className="empty-state">
          No blueprints synced. Re-link this character to grant the blueprints scope, then sync.
        </div>
      ) : (
        <table>
          <thead>
            <tr>
              <th style={{ width: 32 }}></th>
              {COLS.map(c => (
                <th key={c.key} onClick={() => toggleSort(c.key)}
                  style={{ cursor: 'pointer', textAlign: c.num ? 'right' : 'left', whiteSpace: 'nowrap' }}>
                  {c.label}{sort.key === c.key ? (sort.dir > 0 ? ' ▲' : ' ▼') : ''}
                </th>
              ))}
              <th>Flag</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(b => (
              <tr key={b.key || b.item_id}>
                <td><img src={bpIcon(b.type_id, b.is_bpo)} alt="" width={24} height={24} style={{ borderRadius: 3 }} /></td>
                <td style={{ color: 'var(--text-white)', whiteSpace: 'nowrap' }}>{b.type_name || b.type_id}</td>
                <td>
                  <span className={`badge ${b.is_bpo ? 'badge-ok' : 'badge-warn'}`}>{b.is_bpo ? 'BPO' : 'BPC'}</span>
                </td>
                <td style={{ textAlign: 'right' }}>{b.me ?? 0}</td>
                <td style={{ textAlign: 'right' }}>{b.te ?? 0}</td>
                <td style={{ textAlign: 'right' }}>{b.is_bpo ? '∞' : fmtNum(b.runs)}</td>
                <td style={{ textAlign: 'right' }}>{fmtNum(b.count)}</td>
                <td style={{ color: 'var(--text)' }}>{b.product_name || '—'}</td>
                <td>{b.location_name || b.location_id || '—'}</td>
                <td style={{ color: 'var(--text)', fontSize: 12 }}>{b.location_flag}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
