// Tracking → Contracts → Deliverly: courier deliveries the selected character(s)
// accepted and hauled. Shows reward / collateral / volume / jumps / time, active vs
// completed, summary stats, and per-delivery custom tags + note.
import { useState, useEffect, useMemo, useCallback } from 'react'
import { get, put } from '../../api/client'
import { fmtIsk, fmtInt, fmtDate, fmtDuration, RED } from './fmt'
import {
  ScopeSelect, DateRange, Stat, StatRow, SyncButton, ScopeWarning, SortableTable,
} from './common'

function StateBadge({ state }) {
  if (state === 'active') return <span className="badge badge-warn">Active</span>
  if (state === 'completed') return <span className="badge badge-ok">Completed</span>
  if (state === 'failed') return <span className="badge badge-bad">Failed</span>
  return <span className="badge">{state}</span>
}

// Tags + note cell with inline editing (datalist-backed autocomplete).
function TagNoteCell({ row, onSave }) {
  const [editing, setEditing] = useState(false)
  const [tags, setTags] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)

  // Load the current values from the row each time the editor is opened.
  function openEditor() {
    setTags((row.tags || []).join(', '))
    setNote(row.note || '')
    setEditing(true)
  }

  if (!editing) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4, whiteSpace: 'normal', maxWidth: 240 }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, alignItems: 'center' }}>
          {(row.tags || []).map(t => <span key={t} className="badge">{t}</span>)}
          <button className="btn btn-ghost btn-sm" title="Edit tags / note" onClick={openEditor}>✎</button>
        </div>
        {row.note && <span style={{ fontSize: 11, color: 'var(--text)' }}>{row.note}</span>}
      </div>
    )
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, whiteSpace: 'normal', minWidth: 220 }}>
      <input list="delivery-tags" value={tags} onChange={e => setTags(e.target.value)}
        placeholder="tags, comma separated" style={{ padding: '5px 7px' }} />
      <input value={note} onChange={e => setNote(e.target.value)} placeholder="note" style={{ padding: '5px 7px' }} />
      <div style={{ display: 'flex', gap: 6 }}>
        <button className="btn btn-primary btn-sm" disabled={busy}
          onClick={async () => { setBusy(true); try { await onSave(row.contract_id, tags, note); setEditing(false) } finally { setBusy(false) } }}>
          {busy ? 'Saving…' : 'Save'}
        </button>
        <button className="btn btn-ghost btn-sm" onClick={() => setEditing(false)}>Cancel</button>
      </div>
    </div>
  )
}

const STATUS_TABS = [['all', 'All'], ['active', 'Active'], ['completed', 'Completed']]

export default function ContractsTracking() {
  const [chars, setChars] = useState([])
  useEffect(() => { get('/characters').then(setChars).catch(() => {}) }, [])
  const groups = useMemo(() => [...new Set(chars.map(c => c.group_name).filter(Boolean))], [chars])
  const [scope, setScope] = useState('all')
  const [status, setStatus] = useState('all')
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [data, setData] = useState(null)
  const [tagOptions, setTagOptions] = useState([])
  const [err, setErr] = useState('')

  const load = useCallback(() => {
    const qs = new URLSearchParams({ scope, status })
    if (start) qs.set('start', start)
    if (end) qs.set('end', end)
    return get(`/account/deliveries?${qs.toString()}`)
      .then(d => { setData(d); setErr('') })
      .catch(e => setErr(e.message))
  }, [scope, status, start, end])

  useEffect(() => { load() }, [load])
  useEffect(() => { get('/account/deliveries/tags').then(d => setTagOptions(d.tags || [])).catch(() => {}) }, [])

  const saveAnnotation = useCallback(async (contractId, tags, note) => {
    const res = await put(`/account/deliveries/${contractId}/annotation`, { tags, note })
    setData(d => d && ({
      ...d,
      deliveries: d.deliveries.map(x => x.contract_id === contractId ? { ...x, tags: res.tags, note: res.note } : x),
    }))
    get('/account/deliveries/tags').then(d => setTagOptions(d.tags || [])).catch(() => {})
  }, [])

  const rows = data?.deliveries || []
  const s = data?.summary

  const columns = [
    { key: 'title', label: 'Title', sortVal: r => r.title, render: r => r.title || <span style={{ color: 'var(--text)' }}>(courier)</span> },
    { key: 'route', label: 'Route', sortVal: r => r.start_system, render: r => `${r.start_system || '?'} → ${r.end_system || '?'}` },
    { key: 'jumps', label: 'Jumps', num: true, sortVal: r => r.jumps, render: r => r.jumps == null ? '—' : fmtInt(r.jumps) },
    { key: 'reward', label: 'Reward', num: true, sortVal: r => r.reward, render: r => fmtIsk(r.reward) },
    { key: 'rpj', label: 'Reward/Jump', num: true, sortVal: r => r.reward_per_jump, render: r => fmtIsk(r.reward_per_jump) },
    { key: 'coll', label: 'Collateral', num: true, sortVal: r => r.collateral, render: r => fmtIsk(r.collateral) },
    { key: 'vol', label: 'Volume m³', num: true, sortVal: r => r.volume, render: r => fmtInt(r.volume) },
    { key: 'state', label: 'State', sortVal: r => r.state, render: r => <StateBadge state={r.state} /> },
    { key: 'accepted', label: 'Accepted', sortVal: r => r.date_accepted, render: r => fmtDate(r.date_accepted) },
    { key: 'completed', label: 'Completed', sortVal: r => r.date_completed, render: r => fmtDate(r.date_completed) },
    { key: 'dur', label: 'Time', num: true, sortVal: r => r.duration_seconds, render: r => fmtDuration(r.duration_seconds) },
    { key: 'issuer', label: 'For', sortVal: r => r.issuer, render: r => r.issuer || '—' },
    { key: 'tags', label: 'Tags / Note', render: r => <TagNoteCell row={r} onSave={saveAnnotation} /> },
  ]

  return (
    <div>
      <datalist id="delivery-tags">{tagOptions.map(t => <option key={t} value={t} />)}</datalist>

      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', marginBottom: 16 }}>
        <ScopeSelect scope={scope} setScope={setScope} chars={chars} groups={groups} />
        <div className="tabs">
          {STATUS_TABS.map(([v, label]) => (
            <button key={v} className={`tab-btn ${status === v ? 'active' : ''}`} onClick={() => setStatus(v)}>{label}</button>
          ))}
        </div>
        <DateRange start={start} end={end} setStart={setStart} setEnd={setEnd} />
        <SyncButton scope={scope} onDone={load} />
        {!data && !err && <span style={{ fontSize: 12, color: 'var(--text)' }}>Loading…</span>}
        {err && <span style={{ fontSize: 12, color: RED }}>{err}</span>}
      </div>

      <ScopeWarning names={data?.needs_scope} />

      {s && (
        <StatRow>
          <Stat label="Active" value={fmtInt(s.active_count)} />
          <Stat label="Completed" value={fmtInt(s.completed_count)} />
          <Stat label="Reward earned" value={fmtIsk(s.reward_total)} accent />
          <Stat label="Avg reward / jump" value={fmtIsk(s.reward_per_jump)} />
          <Stat label="Jumps flown" value={fmtInt(s.jumps_total)} />
          <Stat label="Volume hauled" value={`${fmtInt(s.volume_total)} m³`} />
          <Stat label="Collateral carried" value={fmtIsk(s.collateral_total)} />
          <Stat label="Avg delivery time" value={fmtDuration(s.avg_duration_seconds)} />
          <Stat label="Active collateral" value={fmtIsk(s.active_collateral)} />
        </StatRow>
      )}

      <SortableTable columns={columns} rows={rows} rowKey={r => r.contract_id}
        empty="No courier deliveries you've hauled yet. Accept and complete a courier contract, then Sync from ESI." />
    </div>
  )
}
