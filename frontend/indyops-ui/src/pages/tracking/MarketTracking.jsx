// Tracking → Market: realized trade profit. Each sell from your wallet transactions is
// FIFO-matched against the oldest tracked buys of the same item to compute true profit,
// with broker fee (buy + sell) and sales tax from the character's skills. Sells with no
// tracked buy (unknown cost basis) are surfaced as a warning, not silently counted.
import { useState, useEffect, useMemo, useCallback } from 'react'
import { get, post } from '../../api/client'
import { fmtIsk, fmtInt, fmtDate, GREEN, RED } from './fmt'
import {
  ScopeSelect, DateRange, Stat, StatRow, SyncButton, ScopeWarning, SortableTable,
} from './common'
import ProfitChart from './ProfitChart'

const fmtPct = v => (v == null ? '—' : `${Number(v).toFixed(1)}%`)
const fmtRatio = v => (v == null ? '—' : Number(v).toFixed(2))
const profitColor = v => (v >= 0 ? GREEN : RED)

export default function MarketTracking() {
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
    return get(`/account/trade-profits?${qs.toString()}`)
      .then(d => { setData(d); setErr('') })
      .catch(e => setErr(e.message))
  }, [scope, start, end])

  useEffect(() => { load() }, [load])

  // per-row opt-out (same backend mechanism as Industry: kind 'trade', keyed on the sell
  // transaction id). Excluded trades stay in the table (dimmed) but drop out of the totals.
  const toggleExclude = useCallback(async (refId, excluded) => {
    try {
      await post('/account/industry/exclude', { kind: 'trade', ref_id: refId, excluded })
      await load()
    } catch (e) { setErr(e.message) }
  }, [load])

  const s = data?.summary
  const multiChar = scope === 'all' || scope.startsWith('group:')

  const columns = [
    { key: 'date', label: 'Date', sortVal: r => r.date, render: r => fmtDate(r.date) },
    ...(multiChar ? [{ key: 'character_name', label: 'Character', sortVal: r => r.character_name, render: r => r.character_name || '—' }] : []),
    { key: 'name', label: 'Item', sortVal: r => r.name, render: r => r.name },
    { key: 'unit_buy', label: 'Unit Buy', num: true, sortVal: r => r.unit_buy, render: r => fmtIsk(r.unit_buy) },
    { key: 'unit_sell', label: 'Unit Sell', num: true, sortVal: r => r.unit_sell, render: r => fmtIsk(r.unit_sell) },
    { key: 'units', label: 'Units', num: true, sortVal: r => r.units, render: r => fmtInt(r.units) },
    { key: 'total_buy', label: 'Total Buy', num: true, sortVal: r => r.total_buy, render: r => fmtIsk(r.total_buy) },
    { key: 'total_sell', label: 'Total Sell', num: true, sortVal: r => r.total_sell, render: r => fmtIsk(r.total_sell) },
    { key: 'broker_buy', label: 'Broker Buy', num: true, sortVal: r => r.broker_buy, render: r => fmtIsk(r.broker_buy) },
    { key: 'broker_sell', label: 'Broker Sell', num: true, sortVal: r => r.broker_sell, render: r => fmtIsk(r.broker_sell) },
    { key: 'sales_tax', label: 'Sales Tax', num: true, sortVal: r => r.sales_tax, render: r => fmtIsk(r.sales_tax) },
    { key: 'margin', label: 'Margin', num: true, sortVal: r => r.margin ?? -Infinity, render: r => fmtPct(r.margin) },
    { key: 'profit', label: 'Profit', num: true, sortVal: r => r.profit, render: r => <span style={{ color: profitColor(r.profit) }}>{fmtIsk(r.profit)}</span> },
    { key: 'actions', label: 'Actions', render: r => (
      <button className="btn btn-ghost btn-sm" onClick={() => toggleExclude(r.sell_tx_id, !r.excluded)}
        disabled={r.sell_tx_id == null}
        title={r.excluded ? 'Count this trade again' : "Don't count this trade in the totals"}>
        {r.excluded ? 'Include' : 'Exclude'}
      </button>
    ) },
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

      {data?.unmatched?.length > 0 && (
        <div className="card" style={{ marginBottom: 16, borderColor: 'var(--accent-dim)', display: 'flex', gap: 10, alignItems: 'flex-start' }}>
          <span style={{ color: '#c8a951' }}>⚠</span>
          <span style={{ fontSize: 13, color: 'var(--text-bright)' }}>
            Sold without a tracked buy (cost basis unknown — profit not counted):{' '}
            {data.unmatched.slice(0, 8).map(u => `${u.name} ×${fmtInt(u.units)}`).join(', ')}
            {data.unmatched.length > 8 ? ` +${data.unmatched.length - 8} more` : ''}.
            {' '}History accumulates from your first sync (ESI exposes ~30 days of transactions).
          </span>
        </div>
      )}

      {s && (
        <StatRow>
          <Stat label="Profit" value={fmtIsk(s.total_profit)} accent />
          <Stat label="Total sell" value={fmtIsk(s.total_sell)} />
          <Stat label="Total buy" value={fmtIsk(s.total_buy)} />
          <Stat label="Broker fees" value={fmtIsk(s.total_broker)} />
          <Stat label="Sales tax" value={fmtIsk(s.total_tax)} />
          <Stat label="Avg margin / ROI" value={fmtPct(s.avg_margin)} />
          <Stat label="Profit / day" value={fmtIsk(s.profit_per_day)} />
          <Stat label="Win rate" value={fmtPct(s.win_rate)} />
          <Stat label="Profit factor" value={fmtRatio(s.profit_factor)} />
          <Stat label="Trades (W / L)" value={`${fmtInt(s.trade_count)} (${fmtInt(s.win_count)} / ${fmtInt(s.loss_count)})`} />
        </StatRow>
      )}

      <ProfitChart series={s?.series} label="Realized profit — daily bars + cumulative line" />

      <div className="sec-label" style={{ marginBottom: 8 }}>Trade Profits</div>
      <SortableTable columns={columns} rows={data?.rows || []}
        rowKey={(r, i) => (r.sell_tx_id != null ? `tx-${r.sell_tx_id}` : `${r.character_id}-${r.date}-${r.type_id}-${i}`)}
        rowStyle={r => (r.excluded ? { opacity: 0.4 } : (r.profit < 0 ? { background: 'rgba(224,82,82,0.06)' } : undefined))}
        empty="No matched trades yet. Buy then sell an item, and Sync from ESI (history builds going forward)." />

      <div style={{ fontSize: 11, color: 'var(--text)', marginTop: 8 }}>
        Profit is realized via FIFO: each sell is matched to your oldest tracked buys of that item. Broker fee (on both
        buy and sell) and sales tax use each character's Accounting + Broker Relations skills, assuming orders are placed
        (instant trades pay no broker fee). Margin = profit ÷ purchase cost.
      </div>
    </div>
  )
}
