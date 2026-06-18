import { useState, useEffect, useRef } from 'react'
import { get } from '../api/client'
import RegionSearch from '../components/RegionSearch'
import { Plot, C, WEEKDAYS, baseLayout, cfg, fmtIsk, fmtNum, secClass } from '../lib/plot'

// EVE item icon (rendered into the header + search results — the "с картинками" part).
const iconUrl = (id, size = 32) => `https://images.evetech.net/types/${id}/icon?size=${size}`

// Big trade hubs for one-click region selection.
const HUBS = [
  { region_id: 10000002, region_name: 'The Forge' },
  { region_id: 10000043, region_name: 'Domain' },
  { region_id: 10000032, region_name: 'Sinq Laison' },
  { region_id: 10000030, region_name: 'Heimatar' },
  { region_id: 10000042, region_name: 'Metropolis' },
]

const TABS = ['Orders', 'Order Book', 'History', 'Group Analysis', 'Prediction']

export default function MarketPage() {
  const [region, setRegion] = useState(HUBS[0])     // default Jita / The Forge
  const [item, setItem]     = useState(null)        // {type_id, name}
  const [header, setHeader] = useState(null)        // /market/type/{id} payload
  const [tab, setTab]       = useState(0)

  useEffect(() => {
    if (!item?.type_id) { setHeader(null); return }
    get(`/market/type/${item.type_id}`).then(setHeader).catch(() => setHeader(null))
  }, [item?.type_id])

  const ready = region?.region_id && item?.type_id

  return (
    <div>
      <div style={{ display: 'grid', gridTemplateColumns: '280px 1fr', gap: 18, alignItems: 'start' }}>
        {/* ── left rail: region + item search ── */}
        <div className="card" style={{ padding: 16, position: 'sticky', top: 16 }}>
          <RailLabel>Region</RailLabel>
          <RegionSearch value={region?.region_name} onChange={setRegion} />
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5, marginTop: 8 }}>
            {HUBS.map(h => (
              <button key={h.region_id} onClick={() => setRegion(h)}
                className={`btn btn-sm ${region?.region_id === h.region_id ? 'btn-primary' : 'btn-ghost'}`}
                style={{ padding: '2px 8px', fontSize: 11 }}>
                {h.region_name}
              </button>
            ))}
          </div>

          <RailLabel style={{ marginTop: 18 }}>Item</RailLabel>
          <ItemSearch onPick={setItem} />

          {header && (
            <div style={{ marginTop: 16, borderTop: '1px solid var(--border)', paddingTop: 14 }}>
              <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                <img src={iconUrl(header.type_id, 64)} alt="" width={48} height={48}
                  style={{ borderRadius: 4, background: 'var(--surface3)' }} />
                <div>
                  <div style={{ color: 'var(--text-white)', fontWeight: 600, fontSize: 14 }}>{header.type_name}</div>
                  <div style={{ color: 'var(--text)', fontSize: 11 }}>{header.group_name}</div>
                </div>
              </div>
              {header.breadcrumb?.length > 0 && (
                <div style={{ marginTop: 10, fontSize: 11, color: 'var(--text)', lineHeight: 1.7 }}>
                  {header.breadcrumb.map((b, i) => (
                    <span key={b.id}>
                      {i > 0 && <span style={{ color: 'var(--border2)' }}> ▸ </span>}
                      <span style={{ color: i === header.breadcrumb.length - 1 ? 'var(--accent)' : 'var(--text)' }}>{b.name}</span>
                    </span>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {/* ── main panel ── */}
        <div>
          {!ready ? (
            <div className="empty-state">
              {region?.region_id ? 'Search and pick an item on the left to load its market.' : 'Pick a region first.'}
            </div>
          ) : (
            <>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8, flexWrap: 'wrap' }}>
                {header && <img src={iconUrl(header.type_id, 64)} alt="" width={28} height={28} style={{ borderRadius: 4 }} />}
                <span style={{ color: 'var(--text-white)', fontWeight: 600 }}>{item.name}</span>
                <span className="badge" style={{ background: 'var(--surface3)', color: 'var(--accent)' }}>{region.region_name}</span>
              </div>

              <div className="tabs">
                {TABS.map((t, i) => (
                  <button key={t} className={`tab-btn ${tab === i ? 'active' : ''}`} onClick={() => setTab(i)}>{t}</button>
                ))}
              </div>

              {tab === 0 && <OrdersTab regionId={region.region_id} typeId={item.type_id} />}
              {tab === 1 && <OrderBookTab regionId={region.region_id} typeId={item.type_id} />}
              {tab === 2 && <HistoryTab regionId={region.region_id} typeId={item.type_id} />}
              {tab === 3 && <GroupTab regionId={region.region_id} typeId={item.type_id} itemName={item.name} />}
              {tab === 4 && <PredictionTab itemName={item.name} />}
            </>
          )}
        </div>
      </div>
    </div>
  )
}

/* ════════════════════════════ item search (with icons) ════════════════════════════ */

function ItemSearch({ onPick }) {
  const [q, setQ]       = useState('')
  const [results, setRes] = useState([])
  const [open, setOpen] = useState(false)
  const timer  = useRef(null)
  const wrapRef = useRef(null)

  useEffect(() => {
    const h = e => { if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [])

  function onInput(e) {
    const v = e.target.value; setQ(v)
    clearTimeout(timer.current)
    if (v.length < 2) { setRes([]); setOpen(false); return }
    timer.current = setTimeout(async () => {
      try { setRes(await get(`/eve/types/search?q=${encodeURIComponent(v)}`)); setOpen(true) } catch {}
    }, 250)
  }

  function pick(t) {
    setQ(t.type_name); setOpen(false); setRes([])
    onPick({ type_id: t.type_id, name: t.type_name })
  }

  return (
    <div ref={wrapRef} style={{ position: 'relative' }}>
      <input value={q} onChange={onInput} onFocus={() => results.length && setOpen(true)} placeholder="Search item (e.g. Obelisk)…" />
      {open && results.length > 0 && (
        <ul style={{
          position: 'absolute', zIndex: 999, width: '100%', background: 'var(--surface2)',
          border: '1px solid var(--border2)', borderRadius: 4, listStyle: 'none',
          maxHeight: 280, overflowY: 'auto', marginTop: 2,
        }}>
          {results.map(t => (
            <li key={t.type_id} onMouseDown={() => pick(t)}
              style={{ padding: '5px 10px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 8 }}
              onMouseEnter={e => e.currentTarget.style.background = 'var(--surface3)'}
              onMouseLeave={e => e.currentTarget.style.background = ''}>
              <img src={iconUrl(t.type_id, 32)} alt="" width={26} height={26} style={{ borderRadius: 3, flexShrink: 0 }} />
              <span style={{ minWidth: 0 }}>
                <span style={{ color: 'var(--text-white)', fontSize: 13, display: 'block', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{t.type_name}</span>
                {t.group_name && <span style={{ color: 'var(--border2)', fontSize: 11 }}>{t.group_name}</span>}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/* ════════════════════════════ 1 · ORDERS ════════════════════════════ */

function OrdersTab({ regionId, typeId }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')

  async function load() {
    setLoading(true); setErr('')
    try { setData(await get(`/market/orders?region_id=${regionId}&type_id=${typeId}`)) }
    catch (e) { setErr(e.message); setData(null) }
    finally { setLoading(false) }
  }
  useEffect(() => { load() }, [regionId, typeId])

  if (loading) return <div className="empty-state">Loading orders…</div>
  if (err) return <div className="error-box">{err}</div>
  if (!data || data.count === 0) return <div className="empty-state">No live orders for this item in this region.</div>

  const s = data.summary
  return (
    <div>
      <StatGrid stats={[
        { label: 'Best sell', value: fmtIsk(s.best_sell), color: C.green },
        { label: 'Best buy', value: fmtIsk(s.best_buy), color: C.blue },
        { label: 'Spread', value: fmtIsk(s.spread) },
        { label: 'Spread %', value: s.spread_pct != null ? s.spread_pct.toFixed(2) + '%' : '—' },
        { label: 'Sell orders', value: fmtNum(s.sell_orders) },
        { label: 'Buy orders', value: fmtNum(s.buy_orders) },
        { label: 'Sell volume', value: fmtNum(s.sell_volume) },
        { label: 'Buy volume', value: fmtNum(s.buy_volume) },
      ]} />

      <div style={{ display: 'flex', justifyContent: 'flex-end', margin: '4px 0 10px' }}>
        <button className="btn btn-ghost btn-sm" onClick={load}>⟳ Refresh</button>
      </div>

      <OrderTable title="Sellers" rows={data.sellers} priceColor={C.green} side="sell" />
      <div style={{ height: 18 }} />
      <OrderTable title="Buyers" rows={data.buyers} priceColor={C.blue} side="buy" />
    </div>
  )
}

function OrderTable({ title, rows, priceColor, side }) {
  if (!rows?.length) return (
    <Panel title={title}><div style={{ color: 'var(--text)', fontSize: 13, padding: 8 }}>No {side} orders.</div></Panel>
  )
  return (
    <Panel title={`${title} · ${rows.length}`}>
      <div style={{ maxHeight: 420, overflowY: 'auto' }}>
        <table>
          <thead>
            <tr>
              <th>Price</th><th>Qty</th><th>Location</th><th>Region</th><th>Sec</th>
              {side === 'buy' && <><th>Range</th><th>Min</th></>}
              <th>Expires in</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(r => (
              <tr key={r.order_id}>
                <td style={{ color: priceColor, fontWeight: 600, whiteSpace: 'nowrap' }}>{fmtIsk(r.price)}</td>
                <td style={{ whiteSpace: 'nowrap' }}>{fmtNum(r.quantity)}</td>
                <td style={{ color: 'var(--text-white)' }}>{r.location}</td>
                <td style={{ color: 'var(--text)' }}>{r.region || '—'}</td>
                <td><span className={`sec-label ${secClass(r.security)}`}>{r.security == null ? '?' : r.security.toFixed(1)}</span></td>
                {side === 'buy' && <>
                  <td style={{ color: 'var(--text)', fontSize: 12 }}>{r.range}</td>
                  <td style={{ color: 'var(--text)' }}>{fmtNum(r.min_volume)}</td>
                </>}
                <td style={{ color: 'var(--text)', fontSize: 12, whiteSpace: 'nowrap' }}>{fmtExpires(r.expires_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  )
}

/* ════════════════════════════ 2 · ORDER BOOK (стакан) ════════════════════════════ */

function OrderBookTab({ regionId, typeId }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')

  async function load() {
    setLoading(true); setErr('')
    try { setData(await get(`/market/orderbook?region_id=${regionId}&type_id=${typeId}`)) }
    catch (e) { setErr(e.message); setData(null) }
    finally { setLoading(false) }
  }
  useEffect(() => { load() }, [regionId, typeId])

  if (loading) return <div className="empty-state">Loading order book…</div>
  if (err) return <div className="error-box">{err}</div>
  if (!data || (!data.asks.length && !data.bids.length)) return <div className="empty-state">No order book for this item here.</div>

  const maxCum = Math.max(data.ask_depth || 0, data.bid_depth || 0) || 1
  const asksTop = [...data.asks].reverse()   // highest ask at top → best ask just above the spread

  return (
    <div>
      <StatGrid stats={[
        { label: 'Best bid', value: fmtIsk(data.best_bid), color: C.green },
        { label: 'Best ask', value: fmtIsk(data.best_ask), color: C.red },
        { label: 'Spread', value: fmtIsk(data.spread) },
        { label: 'Spread %', value: data.spread_pct != null ? data.spread_pct.toFixed(3) + '%' : '—' },
        { label: 'Mid', value: fmtIsk(data.mid), color: C.accent },
        { label: 'Bid depth', value: fmtNum(data.bid_depth) },
        { label: 'Ask depth', value: fmtNum(data.ask_depth) },
        { label: 'Levels', value: `${data.bid_levels}/${data.ask_levels}` },
      ]} />

      <div style={{ display: 'grid', gridTemplateColumns: '380px 1fr', gap: 16, marginTop: 8 }}>
        {/* DOM ladder */}
        <Panel title="Depth ladder">
          <table>
            <thead><tr><th>Price</th><th style={{ textAlign: 'right' }}>Size</th><th style={{ textAlign: 'right' }}>Cumulative</th></tr></thead>
            <tbody>
              {asksTop.map(a => <LadderRow key={'a' + a.price} lvl={a} color={C.red} maxCum={maxCum} />)}
              <tr>
                <td colSpan={3} style={{ textAlign: 'center', background: 'var(--surface3)', color: 'var(--accent)', fontWeight: 600, fontSize: 12 }}>
                  spread {fmtIsk(data.spread)} · mid {fmtIsk(data.mid)}
                </td>
              </tr>
              {data.bids.map(b => <LadderRow key={'b' + b.price} lvl={b} color={C.green} maxCum={maxCum} />)}
            </tbody>
          </table>
        </Panel>

        {/* depth chart */}
        <Panel title="Market depth">
          {Plot ? (
            <Plot
              data={[
                { x: data.bids.map(b => b.price), y: data.bids.map(b => b.cum), name: 'Bids', mode: 'lines', line: { color: C.green, width: 1.5, shape: 'hv' }, fill: 'tozeroy', fillcolor: 'rgba(76,175,125,0.15)' },
                { x: data.asks.map(a => a.price), y: data.asks.map(a => a.cum), name: 'Asks', mode: 'lines', line: { color: C.red, width: 1.5, shape: 'hv' }, fill: 'tozeroy', fillcolor: 'rgba(224,82,82,0.15)' },
              ]}
              layout={baseLayout({ height: 380, xaxis: { gridcolor: C.grid, title: 'Price (ISK)', tickformat: '.3s' }, yaxis: { gridcolor: C.grid, title: 'Cumulative size', tickformat: '.3s' } })}
              config={cfg} style={{ width: '100%' }} useResizeHandler
            />
          ) : <Empty msg="Charting library failed to load." />}
        </Panel>
      </div>
    </div>
  )
}

function LadderRow({ lvl, color, maxCum }) {
  const pct = Math.min(100, (lvl.cum / maxCum) * 100)
  return (
    <tr>
      <td style={{ color, fontWeight: 600, position: 'relative', whiteSpace: 'nowrap' }}>
        <span style={{ position: 'absolute', inset: 0, width: `${pct}%`, background: color, opacity: 0.10 }} />
        <span style={{ position: 'relative' }}>{fmtIsk(lvl.price)}</span>
      </td>
      <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>{fmtNum(lvl.volume)}</td>
      <td style={{ textAlign: 'right', color: 'var(--text)', whiteSpace: 'nowrap' }}>{fmtNum(lvl.cum)}</td>
    </tr>
  )
}

/* ════════════════════════════ 3 · HISTORY (max analytics) ════════════════════════════ */

function HistoryTab({ regionId, typeId }) {
  const [detail, setDetail] = useState(null)
  const [window, setWindow] = useState(14)
  const [showIchimoku, setShowIchimoku] = useState(false)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')

  async function load() {
    setLoading(true); setErr('')
    try { setDetail(await get(`/market/history?region_id=${regionId}&type_id=${typeId}&window=${window}`)) }
    catch (e) { setErr(e.message); setDetail(null) }
    finally { setLoading(false) }
  }
  useEffect(() => { load() }, [regionId, typeId, window])

  if (loading) return <div className="empty-state">Loading history…</div>
  if (err) return <div className="error-box">{err}</div>
  if (!detail || detail.empty) return <div className="empty-state">No ESI price history for this item in this region.</div>

  const ts = detail.timestamps || []
  const s = detail.series || {}
  if (!Plot) return <div className="error-box">Charting library failed to load. Hard-refresh (Ctrl+F5).</div>

  return (
    <div>
      <StatGrid stats={[
        { label: 'Last', value: fmtIsk(detail.stats.last), color: C.accent },
        { label: 'Change', value: detail.stats.change_pct == null ? '—' : `${detail.stats.change_pct >= 0 ? '+' : ''}${detail.stats.change_pct.toFixed(2)}%`, color: detail.stats.change_pct >= 0 ? C.green : C.red },
        { label: 'Day high', value: fmtIsk(detail.stats.day_high) },
        { label: 'Day low', value: fmtIsk(detail.stats.day_low) },
        { label: '7d avg', value: fmtIsk(detail.stats.week_avg) },
        { label: 'All max', value: fmtIsk(detail.stats.all_max) },
        { label: 'All min', value: fmtIsk(detail.stats.all_min) },
        { label: 'All avg', value: fmtIsk(detail.stats.all_avg) },
        { label: 'Volatility', value: detail.stats.volatility != null ? (detail.stats.volatility * 100).toFixed(2) + '%' : '—' },
        { label: 'Avg vol/day', value: fmtNum(detail.stats.avg_volume) },
        { label: 'Last vol', value: fmtNum(detail.stats.last_volume) },
        { label: 'Days', value: detail.stats.points },
      ]} />

      <div style={{ display: 'flex', alignItems: 'center', gap: 16, margin: '4px 0 14px', flexWrap: 'wrap' }}>
        <label style={{ fontSize: 12, color: 'var(--text)', display: 'flex', alignItems: 'center', gap: 8 }}>
          SMA / EMA / BB window: <b style={{ color: 'var(--accent)' }}>{window}</b>
          <input type="range" min="3" max="50" value={window} onChange={e => setWindow(Number(e.target.value))} style={{ width: 160 }} />
        </label>
        <label style={{ fontSize: 12, color: 'var(--text-bright)', display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
          <input type="checkbox" checked={showIchimoku} onChange={e => setShowIchimoku(e.target.checked)} /> Ichimoku cloud
        </label>
      </div>

      <Panel title="Price · SMA · EMA · Bollinger Bands">
        <Plot
          data={[
            { x: ts, y: s.bb_upper, name: 'BB upper', mode: 'lines', line: { color: C.grid, width: 1 }, hoverinfo: 'skip' },
            { x: ts, y: s.bb_lower, name: 'BB', mode: 'lines', line: { color: C.grid, width: 1 }, fill: 'tonexty', fillcolor: 'rgba(58,155,214,0.08)', hoverinfo: 'skip' },
            ...(showIchimoku ? [
              { x: ts, y: s.senkou_a, name: 'Senkou A', mode: 'lines', line: { color: C.green, width: 0.8 }, hoverinfo: 'skip' },
              { x: ts, y: s.senkou_b, name: 'Senkou B', mode: 'lines', line: { color: C.red, width: 0.8 }, fill: 'tonexty', fillcolor: 'rgba(155,109,214,0.10)', hoverinfo: 'skip' },
              { x: ts, y: s.tenkan, name: 'Tenkan', mode: 'lines', line: { color: C.accent, width: 0.8, dash: 'dot' } },
              { x: ts, y: s.kijun, name: 'Kijun', mode: 'lines', line: { color: C.blue, width: 0.8, dash: 'dot' } },
            ] : []),
            { x: ts, y: s.sma, name: `SMA ${window}`, mode: 'lines', line: { color: C.accent, width: 1.3 } },
            { x: ts, y: s.ema, name: `EMA ${window}`, mode: 'lines', line: { color: C.orange, width: 1.2 } },
            { x: ts, y: s.price, name: 'Price', mode: 'lines', line: { color: C.white, width: 2 } },
          ]}
          layout={baseLayout({ height: 360, yaxis: { gridcolor: C.grid, tickformat: '.3s' } })}
          config={cfg} style={{ width: '100%' }} useResizeHandler
        />
      </Panel>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <Panel title="RSI (14)">
          <Plot data={[{ x: ts, y: s.rsi, mode: 'lines', line: { color: C.purple, width: 1.5 }, name: 'RSI' }]}
            layout={baseLayout({ height: 220, showlegend: false, yaxis: { gridcolor: C.grid, range: [0, 100] },
              shapes: [
                { type: 'line', xref: 'paper', x0: 0, x1: 1, y0: 70, y1: 70, line: { color: C.red, width: 0.8, dash: 'dash' } },
                { type: 'line', xref: 'paper', x0: 0, x1: 1, y0: 30, y1: 30, line: { color: C.green, width: 0.8, dash: 'dash' } },
              ] })}
            config={cfg} style={{ width: '100%' }} useResizeHandler />
        </Panel>
        <Panel title="MACD (12·26·9)">
          <Plot data={[
            { x: ts, y: s.macd_hist, type: 'bar', name: 'Hist', marker: { color: (s.macd_hist || []).map(v => v >= 0 ? 'rgba(76,175,125,0.6)' : 'rgba(224,82,82,0.6)') } },
            { x: ts, y: s.macd, name: 'MACD', mode: 'lines', line: { color: C.blue, width: 1.3 } },
            { x: ts, y: s.macd_signal, name: 'Signal', mode: 'lines', line: { color: C.accent, width: 1 } },
          ]} layout={baseLayout({ height: 220 })} config={cfg} style={{ width: '100%' }} useResizeHandler />
        </Panel>
      </div>

      <Panel title="Daily volume">
        <Plot data={[{ x: ts, y: s.volume, type: 'bar', marker: { color: 'rgba(155,109,214,0.55)' }, name: 'Volume' }]}
          layout={baseLayout({ height: 200, showlegend: false, yaxis: { gridcolor: C.grid, tickformat: '.3s' } })}
          config={cfg} style={{ width: '100%' }} useResizeHandler />
      </Panel>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <Panel title={`Returns · VaR ${pct(detail.risk.var95)} · CVaR ${pct(detail.risk.cvar95)}`}>
          {detail.risk.hist_counts
            ? <Plot data={[{ type: 'bar', x: detail.risk.hist_edges.slice(0, -1).map((e, i) => (e + detail.risk.hist_edges[i + 1]) / 2), y: detail.risk.hist_counts, marker: { color: 'rgba(139,147,176,0.5)' } }]}
                layout={baseLayout({ height: 240, showlegend: false, bargap: 0.02, xaxis: { gridcolor: C.grid, tickformat: '.1%' },
                  shapes: [
                    detail.risk.var95 != null && { type: 'line', x0: detail.risk.var95, x1: detail.risk.var95, yref: 'paper', y0: 0, y1: 1, line: { color: C.accent, width: 1.2, dash: 'dash' } },
                    detail.risk.cvar95 != null && { type: 'line', x0: detail.risk.cvar95, x1: detail.risk.cvar95, yref: 'paper', y0: 0, y1: 1, line: { color: C.red, width: 1.2, dash: 'dash' } },
                  ].filter(Boolean) })}
                config={cfg} style={{ width: '100%' }} useResizeHandler />
            : <Empty msg="Need ≥5 days for risk distribution" />}
        </Panel>
        <Panel title="Monte Carlo · 24-step projection (GBM, 500 paths)">
          {detail.montecarlo
            ? <Plot data={[
                { y: detail.montecarlo.p95, x: detail.montecarlo.p95.map((_, i) => i + 1), name: 'p95', mode: 'lines', line: { color: C.grid, width: 1 }, hoverinfo: 'skip' },
                { y: detail.montecarlo.p5, x: detail.montecarlo.p5.map((_, i) => i + 1), name: '5–95%', mode: 'lines', line: { color: C.grid, width: 1 }, fill: 'tonexty', fillcolor: 'rgba(200,169,81,0.12)', hoverinfo: 'skip' },
                { y: detail.montecarlo.p50, x: detail.montecarlo.p50.map((_, i) => i + 1), name: 'median', mode: 'lines', line: { color: C.accent, width: 1.6 } },
              ]} layout={baseLayout({ height: 240, xaxis: { gridcolor: C.grid, title: 'steps ahead' }, yaxis: { gridcolor: C.grid, tickformat: '.3s' } })}
              config={cfg} style={{ width: '100%' }} useResizeHandler />
            : <Empty msg="Need ≥10 days for Monte Carlo" />}
        </Panel>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 16 }}>
        <Panel title="Volume by weekday (UTC)">
          <Plot data={[{ x: WEEKDAYS, y: detail.weekday_volume, type: 'bar', marker: { color: 'rgba(58,155,214,0.55)' } }]}
            layout={baseLayout({ height: 240, showlegend: false, yaxis: { gridcolor: C.grid, tickformat: '.3s' } })}
            config={cfg} style={{ width: '100%' }} useResizeHandler />
        </Panel>
        <Panel title="Market states (volatility regime)">
          {detail.states ? <MarketStates states={detail.states} /> : <Empty msg="Need ≥6 days for regime clustering" />}
        </Panel>
      </div>
    </div>
  )
}

/* ════════════════════════════ 4 · GROUP ANALYSIS (correlation) ════════════════════════════ */

function GroupTab({ regionId, typeId, itemName }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')

  useEffect(() => {
    setLoading(true); setErr('')
    get(`/market/correlation?region_id=${regionId}&type_id=${typeId}`)
      .then(setData).catch(e => { setErr(e.message); setData(null) }).finally(() => setLoading(false))
  }, [regionId, typeId])

  if (loading) return <div className="empty-state">Computing correlations…</div>
  if (err) return <div className="error-box">{err}</div>
  if (!data || data.labels.length < 2) return <div className="empty-state">Not enough overlapping history to correlate this item against peers/commodities.</div>

  return (
    <div>
      <div style={{ fontSize: 12, color: 'var(--text)', marginBottom: 12 }}>
        Daily-return correlation of <b style={{ color: 'var(--text-white)' }}>{itemName}</b> against same-group peers and
        the mineral / ore / ice / moon / PLEX reference commodities · {data.points} overlapping days.
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <Panel title={`Correlation with ${itemName}`}>
          {data.to_target.length ? (
            <table>
              <thead><tr><th>Series</th><th style={{ textAlign: 'right' }}>ρ</th><th style={{ width: 120 }}>strength</th></tr></thead>
              <tbody>
                {data.to_target.map(r => (
                  <tr key={r.label}>
                    <td style={{ color: 'var(--text-white)' }}>{r.label}</td>
                    <td style={{ textAlign: 'right', color: corrColor(r.corr), fontWeight: 600 }}>{r.corr == null ? '—' : r.corr.toFixed(2)}</td>
                    <td><CorrBar v={r.corr} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <Empty msg="No peers resolved" />}
        </Panel>

        <Panel title="Correlation matrix">
          {Plot ? (
            <Plot
              data={[{
                type: 'heatmap', z: data.matrix, x: data.labels, y: data.labels,
                zmin: -1, zmax: 1, colorscale: [[0, C.red], [0.5, '#11141f'], [1, C.green]],
                hoverongaps: false, colorbar: { thickness: 8, len: 0.9 },
              }]}
              layout={baseLayout({ height: 420, margin: { l: 120, r: 10, t: 10, b: 110 }, xaxis: { tickangle: -45, gridcolor: 'rgba(0,0,0,0)' }, yaxis: { gridcolor: 'rgba(0,0,0,0)', autorange: 'reversed' } })}
              config={cfg} style={{ width: '100%' }} useResizeHandler
            />
          ) : <Empty msg="Charting library failed to load." />}
        </Panel>
      </div>
    </div>
  )
}

function CorrBar({ v }) {
  if (v == null) return <span style={{ color: 'var(--text)' }}>—</span>
  const pct = Math.abs(v) * 100
  const col = corrColor(v)
  return (
    <div style={{ height: 6, background: 'var(--surface3)', borderRadius: 3, overflow: 'hidden' }}>
      <div style={{ width: `${pct}%`, height: '100%', background: col }} />
    </div>
  )
}

/* ════════════════════════════ 5 · PREDICTION (stub) ════════════════════════════ */

function PredictionTab({ itemName }) {
  return (
    <div>
      <div className="warning-box">
        🔮 Price-prediction model for <b>{itemName}</b> is in development.
      </div>
      <div className="card" style={{ padding: 24 }}>
        <div style={{ fontSize: 13, color: 'var(--text-bright)', lineHeight: 1.8 }}>
          Planned forecasting stack (forthcoming):
          <ul style={{ margin: '10px 0 0 18px', color: 'var(--text)' }}>
            <li><b style={{ color: 'var(--text-white)' }}>Statistical baseline</b> — SARIMA / Holt-Winters on the daily price &amp; volume series.</li>
            <li><b style={{ color: 'var(--text-white)' }}>ML model</b> — gradient-boosted / LSTM forecaster using indicators (RSI, MACD, volatility) and cross-commodity features.</li>
            <li><b style={{ color: 'var(--text-white)' }}>Confidence bands</b> — backtested prediction intervals with directional accuracy &amp; error (MAPE / RMSE).</li>
            <li><b style={{ color: 'var(--text-white)' }}>Signal</b> — buy / hold / sell suggestion with horizon selection (7 / 30 / 90 days).</li>
          </ul>
        </div>
        <div style={{ marginTop: 20, opacity: 0.5, pointerEvents: 'none' }}>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <button className="btn btn-primary btn-sm" disabled>Forecast 30 days</button>
            <select disabled style={{ width: 160 }}><option>SARIMA</option></select>
            <span style={{ fontSize: 12, color: 'var(--text)' }}>(disabled)</span>
          </div>
        </div>
      </div>
    </div>
  )
}

/* ════════════════════════════ shared bits ════════════════════════════ */

function RailLabel({ children, style }) {
  return <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: 1, color: 'var(--accent)', marginBottom: 8, ...style }}>{children?.toUpperCase?.() || children}</div>
}

function StatGrid({ stats }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(120px,1fr))', gap: 8, marginBottom: 12 }}>
      {stats.map((c, i) => (
        <div key={i} style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 6, padding: '8px 12px' }}>
          <div style={{ fontSize: 10, color: 'var(--text)', textTransform: 'uppercase', letterSpacing: 0.5 }}>{c.label}</div>
          <div style={{ fontSize: 15, fontWeight: 600, color: c.color || C.white, marginTop: 3 }}>{c.value}</div>
        </div>
      ))}
    </div>
  )
}

function MarketStates({ states }) {
  const total = states.counts.reduce((a, b) => a + b, 0) || 1
  const colors = [C.green, C.accent, C.red]
  return (
    <div style={{ padding: 4 }}>
      <div style={{ marginBottom: 14 }}>
        <span style={{ fontSize: 11, color: 'var(--text)' }}>Current regime</span>
        <div style={{ fontSize: 22, fontWeight: 700, color: colors[states.current] || C.text }}>
          {states.current != null ? states.names[states.current] : '—'}
        </div>
      </div>
      {states.names.map((n, i) => (
        <div key={i} style={{ marginBottom: 8 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, marginBottom: 3 }}>
            <span style={{ color: colors[i] }}>{n}</span>
            <span style={{ color: 'var(--text)' }}>{(states.counts[i] / total * 100).toFixed(0)}%</span>
          </div>
          <div style={{ height: 6, background: 'var(--surface3)', borderRadius: 3, overflow: 'hidden' }}>
            <div style={{ width: `${states.counts[i] / total * 100}%`, height: '100%', background: colors[i] }} />
          </div>
        </div>
      ))}
    </div>
  )
}

function Panel({ title, children }) {
  return (
    <div className="card" style={{ padding: '12px 14px', marginBottom: 16 }}>
      <div style={{ fontSize: 11, color: 'var(--accent)', fontWeight: 700, letterSpacing: 1, marginBottom: 8 }}>{title.toUpperCase()}</div>
      {children}
    </div>
  )
}

function Empty({ msg }) {
  return <div style={{ padding: '40px 12px', textAlign: 'center', color: 'var(--text)', fontSize: 12 }}>{msg}</div>
}

function fmtExpires(iso) {
  if (!iso) return '—'
  const ms = new Date(iso) - new Date()
  if (ms <= 0) return 'expired'
  const d = Math.floor(ms / 86400000)
  const h = Math.floor((ms % 86400000) / 3600000)
  if (d > 0) return `${d}d ${h}h`
  const m = Math.floor((ms % 3600000) / 60000)
  return `${h}h ${m}m`
}

const pct = v => v != null ? (v * 100).toFixed(2) + '%' : '—'
const corrColor = v => v == null ? C.text : v >= 0 ? C.green : C.red
