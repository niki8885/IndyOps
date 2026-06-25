// Tracking → Industry: realized manufacturing profit + completed industry jobs. A FIFO
// cost ledger attributes each job's material cost from your tracked buys (and earlier
// builds), then realizes profit when the built items are sold. Jobs whose inputs can't be
// fully attributed are flagged "Missing inputs" — their profit isn't counted on sale.
import { useState, useEffect, useMemo, useCallback } from 'react'
import { get, post } from '../../api/client'
import { fmtIsk, fmtInt, fmtDate, GREEN, RED, AMBER } from './fmt'
import {
  ScopeSelect, DateRange, Stat, StatRow, SyncButton, ScopeWarning, SortableTable,
} from './common'
import ProfitChart from './ProfitChart'
import ReprocessPanel from './ReprocessPanel'

const fmtPct = v => (v == null ? '—' : `${Number(v).toFixed(1)}%`)
const fmtRatio = v => (v == null ? '—' : Number(v).toFixed(2))
const profitColor = v => (v >= 0 ? GREEN : RED)
const fmtTs = ts => (ts ? ts.replace('T', ' ').slice(0, 19) : '—')

export default function IndustryTracking() {
  const [chars, setChars] = useState([])
  useEffect(() => { get('/characters').then(setChars).catch(() => {}) }, [])
  const groups = useMemo(() => [...new Set(chars.map(c => c.group_name).filter(Boolean))], [chars])
  const [scope, setScope] = useState('all')
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const [detail, setDetail] = useState(null)     // job row open in the detail panel
  const [priceInput, setPriceInput] = useState('')

  const load = useCallback(() => {
    const qs = new URLSearchParams({ scope })
    if (start) qs.set('start', start)
    if (end) qs.set('end', end)
    return get(`/account/industry?${qs.toString()}`)
      .then(d => { setData(d); setErr('') })
      .catch(e => setErr(e.message))
  }, [scope, start, end])

  function openDetail(job) {
    setPriceInput(job.custom_unit_price != null ? String(job.custom_unit_price) : '')
    setDetail(job)
  }
  async function reprocessJob() {
    const v = priceInput.trim() === '' ? null : Number(priceInput)
    try {
      await post('/account/industry/job-override', { job_id: detail.job_id, custom_unit_price: v })
      setDetail(null); load()
    } catch (e) { setErr(e.message) }
  }

  useEffect(() => { load() }, [load])

  const m = data?.mfg_summary
  const js = data?.jobs_summary
  const cs = data?.contracts_summary

  const mfgCols = [
    { key: 'date', label: 'Date', sortVal: r => r.date, render: r => fmtDate(r.date) },
    { key: 'name', label: 'Item', sortVal: r => r.name, render: r => r.name },
    { key: 'unit_build', label: 'Unit Build', num: true, sortVal: r => r.unit_build, render: r => fmtIsk(r.unit_build) },
    { key: 'unit_sell', label: 'Unit Sell', num: true, sortVal: r => r.unit_sell, render: r => fmtIsk(r.unit_sell) },
    { key: 'units', label: 'Units', num: true, sortVal: r => r.units, render: r => fmtInt(r.units) },
    { key: 'total_build', label: 'Total Build', num: true, sortVal: r => r.total_build, render: r => fmtIsk(r.total_build) },
    { key: 'total_sell', label: 'Total Sell', num: true, sortVal: r => r.total_sell, render: r => fmtIsk(r.total_sell) },
    { key: 'broker_sell', label: 'Broker Sell', num: true, sortVal: r => r.broker_sell, render: r => fmtIsk(r.broker_sell) },
    { key: 'sales_tax', label: 'Sales Tax', num: true, sortVal: r => r.sales_tax, render: r => fmtIsk(r.sales_tax) },
    { key: 'margin', label: 'Margin', num: true, sortVal: r => r.margin ?? -Infinity, render: r => fmtPct(r.margin) },
    { key: 'profit', label: 'Profit', num: true, sortVal: r => r.profit, render: r => <span style={{ color: profitColor(r.profit) }}>{fmtIsk(r.profit)}</span> },
  ]

  const jobCols = [
    { key: 'completed_at', label: 'Completed Time', sortVal: r => r.completed_at, render: r => fmtTs(r.completed_at) },
    { key: 'owner', label: 'Owner', sortVal: r => r.owner, render: r => r.owner || '—' },
    { key: 'activity', label: 'Activity', sortVal: r => r.activity, render: r => r.activity },
    { key: 'blueprint_name', label: 'Blueprint', sortVal: r => r.blueprint_name, render: r => r.blueprint_name || '—' },
    { key: 'product_name', label: 'Products', sortVal: r => r.product_name, render: r => r.product_name || '—' },
    { key: 'job_cost', label: 'Job Cost', num: true, sortVal: r => r.job_cost, render: r => fmtIsk(r.job_cost) },
    { key: 'materials_cost', label: 'Materials Cost', num: true, sortVal: r => r.materials_cost, render: r => fmtIsk(r.materials_cost) },
    { key: 'copy_cost', label: 'Copy Cost', num: true, sortVal: r => r.copy_cost, render: r => fmtIsk(r.copy_cost) },
    { key: 'unit_cost', label: 'Unit Cost', num: true, sortVal: r => r.unit_cost, render: r => (r.custom_unit_price != null ? <span title="Custom unit price" style={{ color: 'var(--accent)' }}>{fmtIsk(r.unit_cost)} ✎</span> : fmtIsk(r.unit_cost)) },
    { key: 'runs', label: 'Runs', num: true, sortVal: r => r.runs, render: r => fmtInt(r.runs) },
    { key: 'produced', label: 'Produced', num: true, sortVal: r => r.produced, render: r => fmtInt(r.produced) },
    { key: 'sold', label: 'Sold', num: true, sortVal: r => r.sold, render: r => fmtInt(r.sold) },
    { key: 'consumed', label: 'Consumed', num: true, sortVal: r => r.consumed, render: r => fmtInt(r.consumed) },
    { key: 'actions', label: 'Actions', render: r => (r.missing
      ? <button className="badge" style={{ color: AMBER, borderColor: AMBER, cursor: 'pointer', background: 'none' }}
          onClick={() => openDetail(r)} title="Inputs couldn't be fully attributed — click to set a Custom Unit Price.">Missing inputs</button>
      : <button className="btn btn-ghost btn-sm" onClick={() => openDetail(r)}>Details</button>) },
  ]

  const contractCols = [
    { key: 'date', label: 'Date', sortVal: r => r.date, render: r => fmtDate(r.date) },
    { key: 'character', label: 'Character', sortVal: r => r.character, render: r => r.character || '—' },
    { key: 'acceptor', label: 'Accepted by', sortVal: r => r.acceptor, render: r => r.acceptor || '—' },
    { key: 'title', label: 'Title', sortVal: r => r.title, render: r => r.title || '—' },
    { key: 'note', label: 'Notes', render: r => r.note || '—' },
    { key: 'total_cost', label: 'Total Cost', num: true, sortVal: r => r.total_cost, render: r => (r.missing ? <span style={{ color: AMBER }} title="Partial cost basis — some items weren't tracked.">{fmtIsk(r.total_cost)}*</span> : fmtIsk(r.total_cost)) },
    { key: 'total_sell', label: 'Total Sell', num: true, sortVal: r => r.total_sell, render: r => fmtIsk(r.total_sell) },
    { key: 'broker_sell', label: 'Broker Sell', num: true, sortVal: r => r.broker_sell, render: r => fmtIsk(r.broker_sell) },
    { key: 'sales_tax', label: 'Sales Tax', num: true, sortVal: r => r.sales_tax, render: r => fmtIsk(r.sales_tax) },
    { key: 'margin', label: 'Margin', num: true, sortVal: r => r.margin ?? -Infinity, render: r => fmtPct(r.margin) },
    { key: 'profit', label: 'Profit', num: true, sortVal: r => r.profit, render: r => <span style={{ color: profitColor(r.profit) }}>{fmtIsk(r.profit)}</span> },
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

      {m && (
        <StatRow>
          <Stat label="Mfg profit" value={fmtIsk(m.total_profit)} accent />
          <Stat label="Total sell" value={fmtIsk(m.total_sell)} />
          <Stat label="Total build" value={fmtIsk(m.total_build)} />
          <Stat label="Broker + tax" value={fmtIsk((m.total_broker || 0) + (m.total_tax || 0))} />
          <Stat label="Avg margin / ROI" value={fmtPct(m.avg_margin)} />
          <Stat label="Profit / day" value={fmtIsk(m.profit_per_day)} />
          <Stat label="Win rate" value={fmtPct(m.win_rate)} />
          <Stat label="Profit factor" value={fmtRatio(m.profit_factor)} />
          <Stat label="Sales (W / L)" value={`${fmtInt(m.trade_count)} (${fmtInt(m.win_count)} / ${fmtInt(m.loss_count)})`} />
        </StatRow>
      )}

      <ProfitChart series={m?.series} label="Realized manufacturing profit — daily bars + cumulative line" />

      <div className="sec-label" style={{ marginBottom: 8 }}>Manufacturing Profit</div>
      <SortableTable columns={mfgCols} rows={data?.manufacturing || []}
        rowKey={(r, i) => `${r.date}-${r.type_id}-${i}`}
        rowStyle={r => (r.profit < 0 ? { background: 'rgba(224,82,82,0.06)' } : undefined)}
        empty="No manufactured items sold yet (with a tracked build cost). Build, sell, then Sync from ESI." />

      <div className="sec-label" style={{ margin: '22px 0 8px' }}>Completed Industry Jobs</div>
      {js && (
        <StatRow>
          <Stat label="Jobs" value={fmtInt(js.job_count)} />
          <Stat label="Job cost" value={fmtIsk(js.total_job_cost)} />
          <Stat label="Materials cost" value={fmtIsk(js.total_materials_cost)} />
          <Stat label="Produced" value={fmtInt(js.total_produced)} />
          <Stat label="Missing inputs" value={fmtInt(js.missing_count)} />
        </StatRow>
      )}
      <SortableTable columns={jobCols} rows={data?.jobs || []} rowKey={r => r.job_id}
        rowStyle={r => (r.missing ? { background: 'rgba(200,169,81,0.07)' } : undefined)}
        empty="No completed industry jobs yet. Deliver a job, then Sync from ESI." />

      {detail && (
        <div className="card" style={{ marginTop: 12, background: 'var(--bg)' }}>
          <div className="sec-label" style={{ marginBottom: 10 }}>Job detail — {detail.product_name || detail.activity}</div>
          <table style={{ marginBottom: 10 }}>
            <thead><tr><th>Blueprint</th><th style={{ textAlign: 'right' }}>Runs Missing</th><th>Custom Unit Price</th></tr></thead>
            <tbody>
              <tr>
                <td>{detail.blueprint_name || '—'}</td>
                <td style={{ textAlign: 'right' }}>{fmtInt(detail.runs_missing || 0)}</td>
                <td>
                  <input type="number" min="0" step="0.01" value={priceInput} placeholder="ISK / unit"
                    onChange={e => setPriceInput(e.target.value)} style={{ width: 140, padding: '5px 7px' }} />
                </td>
              </tr>
            </tbody>
          </table>
          {detail.missing && (
            <div style={{ fontSize: 12, color: '#c8a951', marginBottom: 10 }}>
              Because there were missing inputs, profits won't be tracked when this item is sold — set a Custom Unit Price to track it.
            </div>
          )}
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="btn btn-sm" onClick={reprocessJob}>Re-process Job</button>
            <button className="btn btn-ghost btn-sm" onClick={() => setDetail(null)}>Close</button>
            <span style={{ fontSize: 11, color: 'var(--text)', alignSelf: 'center' }}>
              Empty price + Re-process = clear the override and re-attribute from tracked buys.
            </span>
          </div>
        </div>
      )}

      <div className="sec-label" style={{ margin: '22px 0 8px' }}>Contract Profit</div>
      {cs && (
        <StatRow>
          <Stat label="Contract profit" value={fmtIsk(cs.total_profit)} accent />
          <Stat label="Total sell" value={fmtIsk(cs.total_sell)} />
          <Stat label="Total cost" value={fmtIsk(cs.total_cost)} />
          <Stat label="Broker fees" value={fmtIsk(cs.total_broker)} />
          <Stat label="Avg margin" value={fmtPct(cs.avg_margin)} />
          <Stat label="Contracts" value={fmtInt(cs.count)} />
        </StatRow>
      )}
      <SortableTable columns={contractCols} rows={data?.contracts || []}
        rowKey={(r, i) => `${r.contract_id}-${i}`}
        rowStyle={r => (r.missing ? { background: 'rgba(200,169,81,0.07)' } : undefined)}
        empty="No sold item-exchange contracts yet. Sell items via contract, then Sync from ESI." />
      <div style={{ fontSize: 11, color: 'var(--text)', marginTop: 8 }}>
        Item-exchange contracts you issued and sold: the bundle's items consume cost basis from the same FIFO ledger
        (buys, builds, reprocessed ore). Contracts pay a broker fee but no sales tax. A <span style={{ color: AMBER }}>*</span> cost
        means part of the bundle had no tracked cost basis (margin is overstated).
      </div>

      <ReprocessPanel />

      <div style={{ fontSize: 11, color: 'var(--text)', marginTop: 8 }}>
        Material cost is realized via FIFO from your tracked buys (and earlier builds you consumed). A job is flagged
        <span style={{ color: AMBER }}> Missing inputs</span> when some inputs predate your synced history (ESI exposes
        ~30 days of transactions) or were mined/acquired without a purchase — its profit isn't counted on sale. Unit Cost
        = (Job + Materials + Copy) ÷ Produced. ME comes from your owned blueprint; structure rig ME is not applied.
      </div>
    </div>
  )
}
