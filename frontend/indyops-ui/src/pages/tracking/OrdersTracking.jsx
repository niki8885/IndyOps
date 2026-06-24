import { useState, useEffect, useMemo, useCallback } from 'react'
import { get, post } from '../../api/client'
import { fmtIsk, fmtInt, timeUntil, GREEN, RED, AMBER } from './fmt'

// ── small countdown hook for the rate-limited buttons ────────────────────────
// Tracks whole seconds left and ticks itself down (no Date.now() in render).
function useCooldown(seconds) {
  const [left, setLeft] = useState(0)
  useEffect(() => {
    if (left <= 0) return undefined
    const id = setTimeout(() => setLeft(left - 1), 1000)
    return () => clearTimeout(id)
  }, [left])
  const start = useCallback(() => setLeft(seconds), [seconds])
  return [left, start]
}

// ── cell renderers ───────────────────────────────────────────────────────────
function PriceStatus({ p }) {
  if (!p || !p.status) return <span style={{ color: 'var(--text)' }}>—</span>
  if (p.status === 'best') return <span className="badge badge-ok">Best</span>
  if (p.status === 'outbid') return <span className="badge badge-bad">Outbid</span>
  if (p.status === 'only') return <span className="badge badge-warn">No rivals</span>
  return <span>—</span>
}

function PriceDiff({ p }) {
  if (!p || p.difference == null) return <span style={{ color: 'var(--text)' }}>—</span>
  const color = p.status === 'best' ? GREEN : RED
  const sign = p.difference > 0 ? '+' : ''
  const pct = p.difference_pct == null ? '' : ` (${sign}${p.difference_pct.toFixed(1)}%)`
  return <span style={{ color }}>{sign}{fmtIsk(p.difference)}{pct}</span>
}

function VolumeCell({ r }) {
  const txt = `${fmtInt(r.volume_remain)} / ${fmtInt(r.volume_total)}`
  return r.low_volume
    ? <span className="badge badge-bad" title="Volume running low">{txt}</span>
    : <span>{txt}</span>
}

function ExpiresCell({ r }) {
  const t = timeUntil(r.expires_at)
  return r.expiring_soon
    ? <span style={{ color: AMBER, fontWeight: 600 }} title="Expiring soon">{t}</span>
    : <span>{t}</span>
}

// ── generic sortable table ───────────────────────────────────────────────────
function Table({ columns, rows }) {
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

  if (!rows.length) return <div className="empty-state" style={{ padding: '28px 16px' }}>No active orders.</div>
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
          {sorted.map(r => (
            <tr key={r.order_id} style={r.expiring_soon ? { background: 'rgba(200,169,81,.08)' } : undefined}>
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

// ── shared column fragments ──────────────────────────────────────────────────
const COL = {
  type: { key: 'type', label: 'Type', field: 'type_name', sortVal: r => r.type_name },
  price: { key: 'price', label: 'Price', num: true, sortVal: r => r.price, render: r => fmtIsk(r.price) },
  pstatus: { key: 'pstatus', label: 'Price Status', sortVal: r => r._p?.status, render: r => <PriceStatus p={r._p} /> },
  pdiff: { key: 'pdiff', label: 'Price Difference', num: true, sortVal: r => r._p?.difference, render: r => <PriceDiff p={r._p} /> },
  vol: { key: 'vol', label: 'Volume', num: true, sortVal: r => r.volume_remain, render: r => <VolumeCell r={r} /> },
  total: { key: 'total', label: 'Total', num: true, sortVal: r => r.total, render: r => fmtIsk(r.total) },
  owner: { key: 'owner', label: 'Owner', field: 'owner', sortVal: r => r.owner },
  expires: { key: 'expires', label: 'Expires In', sortVal: r => r.expires_at, render: r => <ExpiresCell r={r} /> },
  station: { key: 'station', label: 'Station', field: 'station', sortVal: r => r.station },
  region: { key: 'region', label: 'Region', field: 'region', sortVal: r => r.region },
  range: { key: 'range', label: 'Range', field: 'range' },
  minvol: { key: 'minvol', label: 'Min Volume', num: true, sortVal: r => r.min_volume, render: r => fmtInt(r.min_volume) },
  escrow: { key: 'escrow', label: 'Escrow Remaining', num: true, sortVal: r => r.escrow, render: r => fmtIsk(r.escrow) },
}
const SELL_COLS = [COL.type, COL.price, COL.pstatus, COL.pdiff, COL.vol, COL.total, COL.owner, COL.expires, COL.station, COL.region]
const BUY_COLS = [COL.type, COL.price, COL.pstatus, COL.pdiff, COL.vol, COL.total, COL.range, COL.minvol, COL.owner, COL.expires, COL.escrow, COL.station, COL.region]

// ── summary card ─────────────────────────────────────────────────────────────
function Stat({ label, value }) {
  return (
    <div style={{ minWidth: 0 }}>
      <div style={{ fontSize: 11, color: 'var(--text)', textTransform: 'uppercase', letterSpacing: 0.4 }}>{label}</div>
      <div style={{ fontSize: 15, color: 'var(--text-white)', fontWeight: 600 }}>{value}</div>
    </div>
  )
}

function Dist({ title, rows }) {
  if (!rows || !rows.length) return null
  return (
    <div>
      <div className="sec-label" style={{ marginBottom: 6 }}>{title}</div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
        {rows.slice(0, 12).map(g => (
          <span key={g.name} style={{
            display: 'inline-flex', gap: 6, alignItems: 'baseline',
            background: 'var(--surface2)', border: '1px solid var(--border)',
            borderRadius: 6, padding: '4px 10px', fontSize: 12,
          }}>
            <span style={{ color: 'var(--text-bright)' }}>{g.name}</span>
            <span style={{ color: 'var(--text)' }}>×{g.count}</span>
            <span style={{ color: 'var(--accent)' }}>{fmtIsk(g.value)}</span>
          </span>
        ))}
      </div>
    </div>
  )
}

function Summary({ s }) {
  if (!s) return null
  return (
    <div className="card" style={{ marginBottom: 18, display: 'grid', gap: 16 }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 28 }}>
        <Stat label="Order Slots" value={`${s.order_slots?.used ?? 0} / ${s.order_slots?.max ?? 0}`} />
        <Stat label="Sell Orders" value={fmtInt(s.sell_count)} />
        <Stat label="Buy Orders" value={fmtInt(s.buy_count)} />
        <Stat label="Sell ISK" value={fmtIsk(s.sell_isk)} />
        <Stat label="Buy ISK" value={fmtIsk(s.buy_isk)} />
        <Stat label="Escrow" value={fmtIsk(s.buy_escrow)} />
        <Stat label="Remaining to cover" value={fmtIsk(s.remaining_to_cover)} />
      </div>
      <Dist title="Distribution by station" rows={s.by_station} />
      <Dist title="Distribution by system" rows={s.by_system} />
    </div>
  )
}

function SectionHead({ side, s }) {
  const title = side === 'sell' ? 'Selling' : 'Buying'
  return (
    <div style={{ display: 'flex', alignItems: 'baseline', gap: 14, flexWrap: 'wrap', margin: '6px 0 10px' }}>
      <span style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-white)' }}>{title}</span>
      <span className="badge badge-ok">Active Orders: {fmtInt(side === 'sell' ? s?.sell_count : s?.buy_count) || 0}</span>
      <span style={{ fontSize: 12, color: 'var(--text)' }}>Total ISK: {fmtIsk(side === 'sell' ? s?.sell_isk : s?.buy_isk)}</span>
      {side === 'buy' && <span style={{ fontSize: 12, color: 'var(--text)' }}>Escrow: {fmtIsk(s?.buy_escrow)}</span>}
      {side === 'buy' && <span style={{ fontSize: 12, color: 'var(--text)' }}>Remaining to cover: {fmtIsk(s?.remaining_to_cover)}</span>}
    </div>
  )
}

// ── page ─────────────────────────────────────────────────────────────────────
export default function OrdersTracking() {
  const [chars, setChars] = useState([])
  const [scope, setScope] = useState('all')
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState('')
  const [priceMap, setPriceMap] = useState({})
  const [priceBusy, setPriceBusy] = useState(false)
  const [syncLeft, startSync] = useCooldown(60)
  const [priceLeft, startPrice] = useCooldown(60)

  useEffect(() => { get('/characters').then(setChars).catch(() => {}) }, [])
  const groups = useMemo(() => [...new Set(chars.map(c => c.group_name).filter(Boolean))], [chars])

  // setState happens only inside the async callbacks (never synchronously), so this is
  // safe to call straight from the effect — mirrors the AgendaPage usePoll pattern.
  const load = useCallback(() => (
    get(`/account/orders?scope=${encodeURIComponent(scope)}`)
      .then(d => { setData(d); setErr('') })
      .catch(e => setErr(e.message))
  ), [scope])

  useEffect(() => { load() }, [load])

  async function doSync() {
    setMsg('')
    try {
      const r = await post('/account/sync', { scope })
      startSync()
      setMsg(`Sync started for ${r.characters} character(s) — refreshing shortly…`)
      setTimeout(load, 20000)
    } catch (e) { setMsg(e.message) }
  }

  async function doPriceCheck() {
    setMsg(''); setPriceBusy(true)
    try {
      const r = await post('/account/orders/price-check', { scope })
      setPriceMap(r.prices || {})
      startPrice()
      setMsg(`Checked competitor prices for ${r.checked} order(s).`)
    } catch (e) { setMsg(e.message) }
    finally { setPriceBusy(false) }
  }

  const selling = useMemo(() => (data?.selling || []).map(r => ({ ...r, _p: priceMap[String(r.order_id)] })), [data, priceMap])
  const buying = useMemo(() => (data?.buying || []).map(r => ({ ...r, _p: priceMap[String(r.order_id)] })), [data, priceMap])
  const needsScope = data?.needs_scope || []

  return (
    <div>
      {/* controls */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', marginBottom: 16 }}>
        <select value={scope} onChange={e => { setPriceMap({}); setScope(e.target.value) }}
          style={{ padding: '7px 10px', minWidth: 200 }}>
          <option value="all">All characters</option>
          {groups.length > 0 && (
            <optgroup label="Groups">
              {groups.map(g => <option key={g} value={`group:${g}`}>{g}</option>)}
            </optgroup>
          )}
          <optgroup label="Characters">
            {chars.map(c => <option key={c.id} value={`char:${c.id}`}>{c.character_name}</option>)}
          </optgroup>
        </select>

        <button className="btn btn-ghost btn-sm" onClick={doSync} disabled={syncLeft > 0}>
          {syncLeft > 0 ? `Sync (${syncLeft}s)` : '⟳ Sync from ESI'}
        </button>
        <button className="btn btn-ghost btn-sm" onClick={doPriceCheck} disabled={priceBusy || priceLeft > 0}>
          {priceBusy ? 'Checking…' : priceLeft > 0 ? `Prices (${priceLeft}s)` : '⚖ Check competitor prices'}
        </button>
        {!data && !err && <span style={{ fontSize: 12, color: 'var(--text)' }}>Loading…</span>}
        {msg && <span style={{ fontSize: 12, color: 'var(--text-bright)' }}>{msg}</span>}
        {err && <span style={{ fontSize: 12, color: RED }}>{err}</span>}
      </div>

      {needsScope.length > 0 && (
        <div className="card" style={{ marginBottom: 16, borderColor: 'var(--accent-dim)', display: 'flex', gap: 10, alignItems: 'center' }}>
          <span style={{ color: AMBER }}>⚠</span>
          <span style={{ fontSize: 13, color: 'var(--text-bright)' }}>
            Re-link to grant the market-orders scope for: {needsScope.join(', ')}. Until then their orders won't appear.
            Add/re-authorise characters from <strong>Personal File</strong>.
          </span>
        </div>
      )}

      <Summary s={data?.summary} />

      <SectionHead side="sell" s={data?.summary} />
      <Table columns={SELL_COLS} rows={selling} />

      <div style={{ height: 26 }} />

      <SectionHead side="buy" s={data?.summary} />
      <Table columns={BUY_COLS} rows={buying} />
    </div>
  )
}
