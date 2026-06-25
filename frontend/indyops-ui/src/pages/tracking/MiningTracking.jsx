// Tracking → Mining: the mined-ore ledger valued as refined minerals at Jita (using each
// character's own reprocessing skills), summarised by category / ore type / day, plus the
// raw ledger (date × ore × system — "where & when"). Mirrors Mission/Ratting; the data is
// esi_mining_ledger, the same source as the per-character Statistics tab.
import { useState, useEffect, useMemo, useCallback } from 'react'
import { get } from '../../api/client'
import { fmtIsk, fmtInt, fmtDate, RED } from './fmt'
import {
  ScopeSelect, DateRange, Stat, StatRow, SyncButton, ScopeWarning, SortableTable, MiniBars,
} from './common'

const CAT_LABELS = { ore: 'Ore', moon_ore: 'Moon ore', ice: 'Ice', gas: 'Gas', other: 'Other' }

export default function MiningTracking() {
  const [chars, setChars] = useState([])
  useEffect(() => { get('/characters').then(setChars).catch(() => {}) }, [])
  const groups = useMemo(() => [...new Set(chars.map(c => c.group_name).filter(Boolean))], [chars])
  const [scope, setScope] = useState('all')
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [basis, setBasis] = useState('sell')
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')

  const load = useCallback(() => {
    const qs = new URLSearchParams({ scope, basis })
    if (start) qs.set('start', start)
    if (end) qs.set('end', end)
    return get(`/account/mining?${qs.toString()}`)
      .then(d => { setData(d); setErr('') })
      .catch(e => setErr(e.message))
  }, [scope, start, end, basis])

  useEffect(() => { load() }, [load])

  const s = data?.summary
  const cats = s?.categories || {}

  const typeCols = [
    { key: 'name', label: 'Ore', sortVal: r => r.name, render: r => r.name },
    { key: 'category', label: 'Category', sortVal: r => r.category, render: r => CAT_LABELS[r.category] || r.category },
    { key: 'qty', label: 'Quantity', num: true, sortVal: r => r.qty, render: r => fmtInt(r.qty) },
    { key: 'value', label: 'Refined value', num: true, sortVal: r => r.value, render: r => fmtIsk(r.value) },
  ]
  const ledgerCols = [
    { key: 'date', label: 'Date', sortVal: r => r.date, render: r => fmtDate(r.date) },
    { key: 'character_name', label: 'Character', sortVal: r => r.character_name, render: r => r.character_name || '—' },
    { key: 'name', label: 'Ore', sortVal: r => r.name, render: r => r.name },
    { key: 'system_name', label: 'System', sortVal: r => r.system_name, render: r => r.system_name || '—' },
    { key: 'quantity', label: 'Quantity', num: true, sortVal: r => r.quantity, render: r => fmtInt(r.quantity) },
    { key: 'value', label: 'Refined value', num: true, sortVal: r => r.value, render: r => fmtIsk(r.value) },
  ]

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', marginBottom: 16 }}>
        <ScopeSelect scope={scope} setScope={setScope} chars={chars} groups={groups} />
        <DateRange start={start} end={end} setStart={setStart} setEnd={setEnd} />
        <select value={basis} onChange={e => setBasis(e.target.value)} style={{ padding: '7px 10px' }}
          title="Jita price basis for the refined minerals">
          <option value="sell">Jita sell</option>
          <option value="buy">Jita buy</option>
          <option value="split">Jita split</option>
        </select>
        <SyncButton scope={scope} onDone={load} />
        {!data && !err && <span style={{ fontSize: 12, color: 'var(--text)' }}>Loading…</span>}
        {err && <span style={{ fontSize: 12, color: RED }}>{err}</span>}
      </div>

      <ScopeWarning names={data?.needs_scope} />

      {s && (
        <StatRow>
          <Stat label="Refined value" value={fmtIsk(s.total_value)} accent />
          <Stat label="Ore" value={fmtIsk(cats.ore?.value)} />
          <Stat label="Moon ore" value={fmtIsk(cats.moon_ore?.value)} />
          <Stat label="Ice" value={fmtIsk(cats.ice?.value)} />
          <Stat label="Gas" value={fmtIsk(cats.gas?.value)} />
          <Stat label="Units mined" value={fmtInt(s.total_quantity)} />
          <Stat label="Ore types" value={fmtInt(s.type_count)} />
        </StatRow>
      )}

      <MiniBars series={s?.series} valueKey="value" label="Refined mining value by day" />

      <div className="sec-label" style={{ marginBottom: 8 }}>By ore type</div>
      <SortableTable columns={typeCols} rows={s?.items || []} rowKey={r => r.type_id}
        empty="No mining recorded yet. Mine some ore, then Sync from ESI (history builds going forward)." />

      <div className="sec-label" style={{ margin: '22px 0 8px' }}>Ledger — where &amp; when</div>
      <SortableTable columns={ledgerCols} rows={data?.entries || []}
        rowKey={(r, i) => `${r.date}-${r.type_id}-${r.solar_system_id}-${i}`}
        empty="No ledger entries in this range." />

      <div style={{ fontSize: 11, color: 'var(--text)', marginTop: 8 }}>
        Refined value uses each character's own reprocessing skills, refine base yield and price basis from their
        Character Settings, priced at Jita ({basis}); gas and unreprocessable types are valued raw. ESI only exposes
        the last ~30 days of the mining ledger, so history accumulates from your first sync.
      </div>
    </div>
  )
}
