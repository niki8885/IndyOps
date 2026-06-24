// Tracking → Mission: agent-mission reward income (main reward + time bonus) for the
// selected character(s) over an optional date range. Data is the wallet journal, which
// carries the agent but not the mission name — so rewards are grouped by agent.
import { useState, useEffect, useMemo, useCallback } from 'react'
import { get } from '../../api/client'
import { fmtIsk, fmtInt, RED } from './fmt'
import {
  ScopeSelect, DateRange, Stat, StatRow, SyncButton, ScopeWarning, SortableTable, MiniBars,
} from './common'

export default function MissionTracking() {
  const [chars, setChars] = useState([])
  useEffect(() => { get('/characters').then(setChars).catch(() => {}) }, [])
  const groups = useMemo(() => [...new Set(chars.map(c => c.group_name).filter(Boolean))], [chars])
  const [scope, setScope] = useState('all')
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')

  const load = useCallback(() => {
    const qs = new URLSearchParams({ scope })
    if (start) qs.set('start', start)
    if (end) qs.set('end', end)
    return get(`/account/missions?${qs.toString()}`)
      .then(d => { setData(d); setErr('') })
      .catch(e => setErr(e.message))
  }, [scope, start, end])

  useEffect(() => { load() }, [load])

  const s = data?.summary
  const columns = [
    { key: 'agent', label: 'Agent', sortVal: r => r.agent_name, render: r => r.agent_name },
    { key: 'count', label: 'Missions', num: true, sortVal: r => r.count, render: r => fmtInt(r.count) },
    { key: 'main', label: 'Main reward', num: true, sortVal: r => r.main, render: r => fmtIsk(r.main) },
    { key: 'bonus', label: 'Time bonus', num: true, sortVal: r => r.bonus, render: r => fmtIsk(r.bonus) },
    { key: 'total', label: 'Total', num: true, sortVal: r => r.total, render: r => fmtIsk(r.total) },
  ]

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', marginBottom: 16 }}>
        <ScopeSelect scope={scope} setScope={setScope} chars={chars} groups={groups} />
        <DateRange start={start} end={end} setStart={setStart} setEnd={setEnd} />
        <SyncButton scope={scope} onDone={load} />
        {!data && !err && <span style={{ fontSize: 12, color: 'var(--text)' }}>Loading…</span>}
        {err && <span style={{ fontSize: 12, color: RED }}>{err}</span>}
      </div>

      <ScopeWarning names={data?.needs_scope} />

      {s && (
        <StatRow>
          <Stat label="Missions" value={fmtInt(s.count)} />
          <Stat label="Main reward" value={fmtIsk(s.main_total)} />
          <Stat label="Time bonus" value={fmtIsk(s.bonus_total)} />
          <Stat label="Total reward" value={fmtIsk(s.total)} accent />
        </StatRow>
      )}

      <MiniBars series={s?.series} valueKey="total" label="Reward income by day" />

      <div className="sec-label" style={{ marginBottom: 8 }}>By agent</div>
      <SortableTable columns={columns} rows={s?.by_agent || []} rowKey={r => r.agent_id ?? 'unknown'}
        empty="No mission rewards recorded yet. Run missions, then Sync from ESI (history builds going forward)." />
      <div style={{ fontSize: 11, color: 'var(--text)', marginTop: 8 }}>
        Note: the wallet journal doesn't include mission names, so rewards are grouped by agent. Only the last ~30 days
        of journal are available from ESI, so history accumulates from your first sync.
      </div>
    </div>
  )
}
