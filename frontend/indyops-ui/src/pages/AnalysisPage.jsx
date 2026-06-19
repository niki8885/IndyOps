import { useState, useEffect, useRef } from 'react'
import * as factoryModule from 'react-plotly.js/factory'
import * as plotlyModule from 'plotly.js-dist-min'
import { get, post, patch, del } from '../api/client'
import SystemSearch from '../components/SystemSearch'
import TypeSearch from '../components/TypeSearch'
import AlertDialog from '../components/AlertDialog'

// Robust interop: the factory (CJS) and plotly-dist (UMD) can land as the
// module itself, under `.default`, or double-wrapped depending on the bundler.
function asFn(m) {
  if (typeof m === 'function') return m
  if (m && typeof m.default === 'function') return m.default
  if (m && m.default && typeof m.default.default === 'function') return m.default.default
  return null
}
let Plot = null
try {
  const create = asFn(factoryModule)
  const Plotly = plotlyModule.default || plotlyModule
  if (create) Plot = create(Plotly)
} catch (e) {
  console.error('Plotly init failed', e)
}

const C = {
  text: '#8b93b0', grid: '#252a40', accent: '#c8a951', white: '#e8ecf4',
  green: '#4caf7d', red: '#e05252', blue: '#3a9bd6', purple: '#9b6dd6',
}
const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

const baseLayout = (over = {}) => ({
  paper_bgcolor: 'rgba(0,0,0,0)',
  plot_bgcolor: 'rgba(0,0,0,0)',
  font: { color: C.text, size: 11, family: 'Segoe UI, system-ui, sans-serif' },
  margin: { l: 55, r: 18, t: 28, b: 32 },
  xaxis: { gridcolor: C.grid, zerolinecolor: C.grid },
  yaxis: { gridcolor: C.grid, zerolinecolor: C.grid },
  legend: { orientation: 'h', y: 1.12, font: { size: 10 } },
  hovermode: 'x unified',
  ...over,
})
const cfg = { displayModeBar: false, responsive: true }

function fmtIsk(v) {
  if (v == null) return '—'
  const n = Number(v)
  if (Math.abs(n) >= 1e9) return (n / 1e9).toFixed(2) + ' B'
  if (Math.abs(n) >= 1e6) return (n / 1e6).toFixed(2) + ' M'
  if (Math.abs(n) >= 1e3) return (n / 1e3).toFixed(1) + ' K'
  return n.toLocaleString(undefined, { maximumFractionDigits: 2 })
}

export default function AnalysisPage() {
  const [tab, setTab] = useState(0)
  return (
    <div>
      <h2 style={{ marginBottom: 14 }}>Analysis</h2>
      <div className="tabs" style={{ marginBottom: 18 }}>
        {['Indices', 'Tracking', 'Allocation'].map((t, i) => (
          <button key={i} className={`tab-btn ${tab === i ? 'active' : ''}`} onClick={() => setTab(i)}>{t}</button>
        ))}
      </div>
      {tab === 0 && <IndicesTab />}
      {tab === 1 && <TrackingTab />}
      {tab === 2 && <AllocationTab />}
    </div>
  )
}

function IndicesTab() {
  const [indices, setIndices]   = useState([])
  const [sel, setSel]           = useState('mineral')
  const [detail, setDetail]     = useState(null)
  const [window, setWindow]     = useState(10)
  const [loading, setLoading]   = useState(false)
  const [showIchimoku, setShowIchimoku] = useState(false)
  const [alertTarget, setAlertTarget]   = useState(null)

  async function loadIndices() {
    try { const r = await get('/analysis/indices'); setIndices(r.indices) } catch {}
  }
  async function loadDetail() {
    setLoading(true)
    try { setDetail(await get(`/analysis/index/${sel}?window=${window}`)) }
    catch { setDetail(null) }
    finally { setLoading(false) }
  }

  useEffect(() => { loadIndices() }, [])
  useEffect(() => { loadDetail() }, [sel, window])

  const ts = detail?.timestamps || []
  const s  = detail?.series || {}

  if (!Plot) {
    return (
      <div>
        <h2 style={{ marginBottom: 16 }}>Analysis</h2>
        <div className="error-box">Charting library failed to load. Please hard-refresh (Ctrl+F5).</div>
      </div>
    )
  }

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 18, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 12, color: 'var(--text)' }}>EVE commodity indices · hourly</span>
      </div>

      {/* index cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(150px,1fr))', gap: 10, marginBottom: 18 }}>
        {indices.map(ix => (
          <div key={ix.key} style={{ position: 'relative' }}>
            <button onClick={() => setSel(ix.key)}
              style={{
                textAlign: 'left', cursor: 'pointer', padding: '10px 12px', borderRadius: 6, width: '100%',
                background: sel === ix.key ? 'var(--surface3)' : 'var(--surface)',
                border: `1px solid ${sel === ix.key ? 'var(--accent)' : 'var(--border)'}`,
              }}>
              <div style={{ fontSize: 12, color: sel === ix.key ? 'var(--accent)' : 'var(--text-white)', fontWeight: 600, paddingRight: 20 }}>{ix.label}</div>
              <div style={{ fontSize: 14, color: 'var(--text-white)', marginTop: 4 }}>{fmtIsk(ix.last_price)}</div>
              <div style={{ fontSize: 11, color: ix.change_pct == null ? 'var(--text)' : ix.change_pct >= 0 ? C.green : C.red }}>
                {ix.change_pct == null ? `${ix.points} pts` : `${ix.change_pct >= 0 ? '▲' : '▼'} ${Math.abs(ix.change_pct).toFixed(2)}%`}
              </div>
            </button>
            <button title="Create alert" onClick={() => setAlertTarget({ kind: 'index', key: ix.key, label: ix.label })}
              style={{
                position: 'absolute', top: 6, right: 6, background: 'none', border: 'none',
                cursor: 'pointer', fontSize: 13, lineHeight: 1, padding: 2, opacity: 0.7,
              }}>🔔</button>
          </div>
        ))}
      </div>

      {/* controls */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 16, flexWrap: 'wrap' }}>
        <label style={{ fontSize: 12, color: 'var(--text)', display: 'flex', alignItems: 'center', gap: 8 }}>
          SMA / BB window: <b style={{ color: 'var(--accent)' }}>{window}</b>
          <input type="range" min="3" max="50" value={window} onChange={e => setWindow(Number(e.target.value))} style={{ width: 160 }} />
        </label>
        <label style={{ fontSize: 12, color: 'var(--text-bright)', display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
          <input type="checkbox" checked={showIchimoku} onChange={e => setShowIchimoku(e.target.checked)} /> Ichimoku cloud
        </label>
      </div>

      {loading && <div className="empty-state">Loading…</div>}
      {detail?.empty && (
        <div className="warning-box">
          No data collected for <b>{detail.label}</b> yet. The hourly collector builds history over time —
          check back once it has captured its first snapshots.
        </div>
      )}

      {detail && !detail.empty && (
        <>
          <StatRow stats={detail.stats} />

          {/* price + SMA + Bollinger (+ ichimoku) */}
          <Panel title="Price · SMA · Bollinger Bands">
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
                { x: ts, y: s.sma, name: `SMA ${window}`, mode: 'lines', line: { color: C.accent, width: 1.4 } },
                { x: ts, y: s.price, name: 'Price', mode: 'lines', line: { color: C.white, width: 2 } },
              ]}
              layout={baseLayout({ height: 360, yaxis: { gridcolor: C.grid, tickformat: '.3s' } })}
              config={cfg} style={{ width: '100%' }} useResizeHandler
            />
          </Panel>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
            <Panel title="RSI (14)">
              <Plot
                data={[{ x: ts, y: s.rsi, mode: 'lines', line: { color: C.purple, width: 1.5 }, name: 'RSI' }]}
                layout={baseLayout({
                  height: 220, showlegend: false,
                  yaxis: { gridcolor: C.grid, range: [0, 100] },
                  shapes: [
                    { type: 'line', xref: 'paper', x0: 0, x1: 1, y0: 70, y1: 70, line: { color: C.red, width: 0.8, dash: 'dash' } },
                    { type: 'line', xref: 'paper', x0: 0, x1: 1, y0: 30, y1: 30, line: { color: C.green, width: 0.8, dash: 'dash' } },
                  ],
                })}
                config={cfg} style={{ width: '100%' }} useResizeHandler
              />
            </Panel>
            <Panel title="MACD (12·26·9)">
              <Plot
                data={[
                  { x: ts, y: s.macd_hist, type: 'bar', name: 'Hist', marker: { color: (s.macd_hist || []).map(v => v >= 0 ? 'rgba(76,175,125,0.6)' : 'rgba(224,82,82,0.6)') } },
                  { x: ts, y: s.macd, name: 'MACD', mode: 'lines', line: { color: C.blue, width: 1.3 } },
                  { x: ts, y: s.macd_signal, name: 'Signal', mode: 'lines', line: { color: C.accent, width: 1 } },
                ]}
                layout={baseLayout({ height: 220 })}
                config={cfg} style={{ width: '100%' }} useResizeHandler
              />
            </Panel>
          </div>

          <Panel title="Volume index">
            <Plot
              data={[{ x: ts, y: s.volume, type: 'bar', marker: { color: 'rgba(155,109,214,0.55)' }, name: 'Volume' }]}
              layout={baseLayout({ height: 200, showlegend: false, yaxis: { gridcolor: C.grid, tickformat: '.3s' } })}
              config={cfg} style={{ width: '100%' }} useResizeHandler
            />
          </Panel>

          {/* risk row */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
            <Panel title={`Returns · VaR ${detail.risk.var95 != null ? (detail.risk.var95 * 100).toFixed(2) + '%' : '—'} · CVaR ${detail.risk.cvar95 != null ? (detail.risk.cvar95 * 100).toFixed(2) + '%' : '—'}`}>
              {detail.risk.hist_counts
                ? <Plot
                    data={[{
                      type: 'bar',
                      x: detail.risk.hist_edges.slice(0, -1).map((e, i) => (e + detail.risk.hist_edges[i + 1]) / 2),
                      y: detail.risk.hist_counts, marker: { color: 'rgba(139,147,176,0.5)' }, name: 'Returns',
                    }]}
                    layout={baseLayout({
                      height: 240, showlegend: false, bargap: 0.02,
                      xaxis: { gridcolor: C.grid, tickformat: '.1%' },
                      shapes: [
                        detail.risk.var95 != null && { type: 'line', x0: detail.risk.var95, x1: detail.risk.var95, yref: 'paper', y0: 0, y1: 1, line: { color: C.accent, width: 1.2, dash: 'dash' } },
                        detail.risk.cvar95 != null && { type: 'line', x0: detail.risk.cvar95, x1: detail.risk.cvar95, yref: 'paper', y0: 0, y1: 1, line: { color: C.red, width: 1.2, dash: 'dash' } },
                      ].filter(Boolean),
                    })}
                    config={cfg} style={{ width: '100%' }} useResizeHandler
                  />
                : <Empty msg="Need ≥5 points for risk distribution" />
              }
            </Panel>
            <Panel title="Monte Carlo · 24h projection (GBM, 500 paths)">
              {detail.montecarlo
                ? <Plot
                    data={[
                      { y: detail.montecarlo.p95, x: detail.montecarlo.p95.map((_, i) => i + 1), name: 'p95', mode: 'lines', line: { color: C.grid, width: 1 }, hoverinfo: 'skip' },
                      { y: detail.montecarlo.p5, x: detail.montecarlo.p5.map((_, i) => i + 1), name: '5–95%', mode: 'lines', line: { color: C.grid, width: 1 }, fill: 'tonexty', fillcolor: 'rgba(200,169,81,0.12)', hoverinfo: 'skip' },
                      { y: detail.montecarlo.p50, x: detail.montecarlo.p50.map((_, i) => i + 1), name: 'median', mode: 'lines', line: { color: C.accent, width: 1.6 } },
                    ]}
                    layout={baseLayout({ height: 240, xaxis: { gridcolor: C.grid, title: 'hours ahead' }, yaxis: { gridcolor: C.grid, tickformat: '.3s' } })}
                    config={cfg} style={{ width: '100%' }} useResizeHandler
                  />
                : <Empty msg="Need ≥10 points for Monte Carlo" />
              }
            </Panel>
          </div>

          {/* liquidity heatmap + market states */}
          <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 16 }}>
            <Panel title="Liquidity heatmap · volume by weekday × hour (UTC)">
              <Plot
                data={[{
                  type: 'heatmap', z: detail.heatmap, x: [...Array(24).keys()], y: WEEKDAYS,
                  colorscale: [[0, '#11141f'], [0.5, '#3a9bd6'], [1, '#c8a951']], hoverongaps: false,
                  colorbar: { thickness: 8, len: 0.9 },
                }]}
                layout={baseLayout({ height: 260, margin: { l: 42, r: 10, t: 10, b: 34 }, xaxis: { title: 'hour UTC', dtick: 2, gridcolor: 'rgba(0,0,0,0)' }, yaxis: { gridcolor: 'rgba(0,0,0,0)' } })}
                config={cfg} style={{ width: '100%' }} useResizeHandler
              />
            </Panel>
            <Panel title="Market states (volatility regime)">
              {detail.states
                ? <MarketStates states={detail.states} />
                : <Empty msg="Need ≥6 points for regime clustering" />
              }
            </Panel>
          </div>
        </>
      )}

      {alertTarget && <AlertDialog target={alertTarget} onClose={() => setAlertTarget(null)} />}
    </div>
  )
}

/* ════════════════════════════ TRACKING ════════════════════════════ */

const PLACE_COLORS = ['#c8a951', '#3a9bd6', '#4caf7d', '#9b6dd6', '#e0884f']

function TrackingTab() {
  const [places, setPlaces]   = useState([])
  const [items, setItems]     = useState([])
  const [selItem, setSelItem] = useState(null)
  const [detail, setDetail]   = useState(null)
  const [selPlace, setSelPlace] = useState(null)
  const [win, setWin]         = useState(10)
  const [loading, setLoading] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError]     = useState('')
  const [alertItem, setAlertItem] = useState(null)

  const [placeKind, setPlaceKind] = useState('system')
  const [pendingSystem, setPendingSystem] = useState(null)
  const [pendingRegion, setPendingRegion] = useState(null)
  const [special, setSpecial] = useState(false)
  const [pendingItem, setPendingItem] = useState(null)

  const loadPlaces = () => get('/tracking/places').then(setPlaces).catch(() => {})
  const loadItems  = () => get('/tracking/items').then(setItems).catch(() => {})
  useEffect(() => { loadPlaces(); loadItems() }, [])

  async function loadDetail(id, pid) {
    if (!id) return
    setLoading(true)
    try {
      const d = await get(`/tracking/item/${id}?window=${win}${pid ? `&place_id=${pid}` : ''}`)
      setDetail(d); setSelPlace(d.selected_place_id)
    } catch {} finally { setLoading(false) }
  }
  useEffect(() => { if (selItem) loadDetail(selItem, selPlace) }, [selItem, win])

  async function addPlace() {
    setError('')
    try {
      let body
      if (placeKind === 'system') {
        const s = pendingSystem?.sys
        if (!s) return
        body = { kind: 'system', name: s.solar_system_name, solar_system_id: s.solar_system_id, region_id: s.region_id, special_parser: special }
      } else {
        if (!pendingRegion) return
        body = { kind: 'region', name: pendingRegion.region_name, region_id: pendingRegion.region_id, special_parser: false }
      }
      await post('/tracking/places', body)
      setPendingSystem(null); setPendingRegion(null); setSpecial(false)
      loadPlaces()
    } catch (e) { setError(e.message) }
  }
  async function delPlace(id) {
    try { await del(`/tracking/places/${id}`); loadPlaces(); loadItems() } catch (e) { setError(e.message) }
  }
  async function addItem() {
    if (!pendingItem?.type_id) return
    setError('')
    try { await post('/tracking/items', { type_id: pendingItem.type_id, name: pendingItem.name, place_ids: [] }); setPendingItem(null); loadItems() }
    catch (e) { setError(e.message) }
  }
  async function delItem(id) {
    try { await del(`/tracking/items/${id}`); if (selItem === id) { setSelItem(null); setDetail(null) } loadItems() } catch {}
  }
  async function toggleItemPlace(item, pid) {
    const cur = new Set(item.place_ids || [])
    cur.has(pid) ? cur.delete(pid) : cur.add(pid)
    try {
      const updated = await patch(`/tracking/items/${item.id}`, { place_ids: [...cur] })
      setItems(items.map(i => i.id === item.id ? updated : i))
      if (selItem === item.id) loadDetail(item.id, selPlace)
    } catch (e) { setError(e.message) }
  }
  async function refresh() {
    setRefreshing(true)
    try { await post('/tracking/refresh', {}); if (selItem) await loadDetail(selItem, selPlace) }
    catch (e) { setError(e.message) } finally { setRefreshing(false) }
  }

  const placeName = id => places.find(p => p.id === id)?.name || `#${id}`

  return (
    <div>
      {error && <div className="error-box">{error}</div>}

      {/* ── management ── */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 18 }}>
        {/* places */}
        <div className="card">
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
            <span style={{ fontSize: 12, fontWeight: 700, letterSpacing: 1, color: 'var(--accent)' }}>FAVOURITE PLACES</span>
            <span style={{ fontSize: 11, color: 'var(--text)' }}>{places.length}/5</span>
          </div>
          {places.map(p => (
            <div key={p.id} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, padding: '4px 0' }}>
              <span style={{ color: 'var(--text-white)' }}>{p.name}</span>
              <span className="badge" style={{ background: 'var(--surface3)', color: 'var(--text)' }}>{p.kind}</span>
              {p.special_parser && <span className="badge badge-warn">C-J parser</span>}
              <button className="btn btn-danger btn-sm" style={{ marginLeft: 'auto' }} onClick={() => delPlace(p.id)}>✕</button>
            </div>
          ))}
          {places.length < 5 && (
            <div style={{ marginTop: 12, borderTop: '1px solid var(--border)', paddingTop: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
              <div style={{ display: 'flex', gap: 4 }}>
                {['system', 'region'].map(k => (
                  <button key={k} className={`btn btn-sm ${placeKind === k ? 'btn-primary' : 'btn-ghost'}`} onClick={() => setPlaceKind(k)}>{k}</button>
                ))}
              </div>
              {placeKind === 'system'
                ? <>
                    <SystemSearch value={pendingSystem?.name || ''} onChange={(name, sys) => setPendingSystem(sys ? { name, sys } : null)} placeholder="System (e.g. C-J6MT)…" />
                    <label style={{ fontSize: 12, color: 'var(--text-bright)', display: 'flex', gap: 6, alignItems: 'center', cursor: 'pointer' }}>
                      <input type="checkbox" checked={special} onChange={e => setSpecial(e.target.checked)} /> C-J special parser (local market)
                    </label>
                  </>
                : <RegionSearch value={pendingRegion?.region_name || ''} onChange={setPendingRegion} />
              }
              <button className="btn btn-primary btn-sm" onClick={addPlace}>+ Add place</button>
            </div>
          )}
        </div>

        {/* items */}
        <div className="card">
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
            <span style={{ fontSize: 12, fontWeight: 700, letterSpacing: 1, color: 'var(--accent)' }}>TRACKED ITEMS</span>
            <span style={{ fontSize: 11, color: 'var(--text)' }}>{items.length}/100</span>
            <button className="btn btn-ghost btn-sm" onClick={refresh} disabled={refreshing} style={{ marginLeft: 'auto' }}>
              {refreshing ? 'Collecting…' : '⟳ Collect now'}
            </button>
          </div>
          <div style={{ maxHeight: 220, overflowY: 'auto' }}>
            {items.map(it => (
              <div key={it.id} style={{ padding: '5px 0', borderBottom: '1px solid var(--border)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <button className="btn btn-ghost btn-sm" onClick={() => setSelItem(it.id)}
                    style={{ color: selItem === it.id ? 'var(--accent)' : 'var(--text-white)', padding: '2px 6px' }}>
                    {it.name}
                  </button>
                  <button className="btn btn-ghost btn-sm" title="Create alert" style={{ marginLeft: 'auto', padding: '2px 6px' }}
                    onClick={() => setAlertItem({ kind: 'item', itemId: it.id, label: it.name,
                      places: places.filter(p => (it.place_ids || []).includes(p.id)) })}>🔔</button>
                  <button className="btn btn-danger btn-sm" onClick={() => delItem(it.id)}>✕</button>
                </div>
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 3 }}>
                  {places.map(p => {
                    const on = (it.place_ids || []).includes(p.id)
                    return (
                      <button key={p.id} onClick={() => toggleItemPlace(it, p.id)}
                        className={`btn btn-sm ${on ? 'btn-primary' : 'btn-ghost'}`} style={{ padding: '1px 7px', fontSize: 10 }}>
                        {p.name}
                      </button>
                    )
                  })}
                </div>
              </div>
            ))}
          </div>
          <div style={{ marginTop: 12, display: 'flex', gap: 8, alignItems: 'flex-end' }}>
            <div style={{ flex: 1 }}>
              <TypeSearch value={pendingItem} onChange={t => setPendingItem(t?.type_id ? t : null)} placeholder="Add item to track…" />
            </div>
            <button className="btn btn-primary btn-sm" onClick={addItem}>+ Add</button>
          </div>
        </div>
      </div>

      {/* ── tracking charts ── */}
      {!selItem && <div className="empty-state">Pick a tracked item above to see its charts.</div>}
      {loading && <div className="empty-state">Loading…</div>}
      {selItem && detail && !loading && <TrackingCharts detail={detail} win={win} setWin={setWin} selPlace={selPlace} setSelPlace={pid => { setSelPlace(pid); loadDetail(selItem, pid) }} placeName={placeName} />}

      {alertItem && <AlertDialog target={alertItem} onClose={() => setAlertItem(null)} />}
    </div>
  )
}

function TrackingCharts({ detail, win, setWin, selPlace, setSelPlace, placeName }) {
  const sbp = detail.series_by_place || {}
  const ind = detail.indicators
  const placeIds = Object.keys(sbp).map(Number)

  return (
    <>
      {/* latest + spread cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(150px,1fr))', gap: 8, marginBottom: 14 }}>
        {detail.places.map(p => (
          <div key={p.place_id} style={{ background: 'var(--surface)', border: `1px solid ${selPlace === p.place_id ? 'var(--accent)' : 'var(--border)'}`, borderRadius: 6, padding: '8px 12px', cursor: 'pointer' }}
            onClick={() => setSelPlace(p.place_id)}>
            <div style={{ fontSize: 12, color: 'var(--text-white)', fontWeight: 600 }}>{p.name}{p.special ? ' ·CJ' : ''}</div>
            <div style={{ fontSize: 11, color: '#4caf7d' }}>S {fmtIsk(p.latest_sell)}</div>
            <div style={{ fontSize: 11, color: '#3a9bd6' }}>B {fmtIsk(p.latest_buy)}</div>
            <div style={{ fontSize: 10, color: 'var(--text)' }}>{p.points} pts</div>
          </div>
        ))}
      </div>

      {detail.spread && (
        <div style={{ display: 'flex', gap: 16, marginBottom: 14, flexWrap: 'wrap' }}>
          <SmallStat label={`Spread @ ${placeName(selPlace)}`} value={fmtIsk(detail.spread.abs)} />
          <SmallStat label="Spread %" value={detail.spread.pct != null ? detail.spread.pct + '%' : '—'} />
          <SmallStat label="Buy" value={fmtIsk(detail.spread.buy)} />
          <SmallStat label="Sell" value={fmtIsk(detail.spread.sell)} />
          <label style={{ fontSize: 12, color: 'var(--text)', display: 'flex', alignItems: 'center', gap: 8, marginLeft: 'auto' }}>
            window <b style={{ color: 'var(--accent)' }}>{win}</b>
            <input type="range" min="3" max="50" value={win} onChange={e => setWin(Number(e.target.value))} style={{ width: 140 }} />
          </label>
        </div>
      )}

      {/* cross-place sell comparison */}
      <Panel title="Sell price by place">
        <Plot
          data={placeIds.map((pid, i) => ({
            x: sbp[pid].timestamps, y: sbp[pid].sell, name: placeName(pid), mode: 'lines',
            line: { color: PLACE_COLORS[i % PLACE_COLORS.length], width: 1.6 },
          }))}
          layout={baseLayout({ height: 300, yaxis: { gridcolor: C.grid, tickformat: '.3s' } })}
          config={cfg} style={{ width: '100%' }} useResizeHandler
        />
      </Panel>

      {ind ? (
        <>
          <Panel title={`Price · SMA · EMA · Bollinger · Ichimoku — ${placeName(selPlace)}`}>
            <Plot
              data={[
                { x: ind.timestamps, y: ind.bb_upper, name: 'BB', mode: 'lines', line: { color: C.grid, width: 1 }, hoverinfo: 'skip' },
                { x: ind.timestamps, y: ind.bb_lower, name: 'BB', mode: 'lines', line: { color: C.grid, width: 1 }, fill: 'tonexty', fillcolor: 'rgba(58,155,214,0.07)', hoverinfo: 'skip', showlegend: false },
                { x: ind.timestamps, y: ind.senkou_a, name: 'Senkou A', mode: 'lines', line: { color: C.green, width: 0.7 }, hoverinfo: 'skip' },
                { x: ind.timestamps, y: ind.senkou_b, name: 'Cloud', mode: 'lines', line: { color: C.red, width: 0.7 }, fill: 'tonexty', fillcolor: 'rgba(155,109,214,0.08)', hoverinfo: 'skip' },
                { x: ind.timestamps, y: ind.buy, name: 'Buy', mode: 'lines', line: { color: C.blue, width: 1, dash: 'dot' } },
                { x: ind.timestamps, y: ind.sell, name: 'Sell', mode: 'lines', line: { color: C.green, width: 1, dash: 'dot' } },
                { x: ind.timestamps, y: ind.sma, name: `SMA${win}`, mode: 'lines', line: { color: C.accent, width: 1.3 } },
                { x: ind.timestamps, y: ind.ema, name: `EMA${win}`, mode: 'lines', line: { color: '#e0884f', width: 1.2 } },
                { x: ind.timestamps, y: ind.mid, name: 'Mid', mode: 'lines', line: { color: C.white, width: 1.8 } },
              ]}
              layout={baseLayout({ height: 340, yaxis: { gridcolor: C.grid, tickformat: '.3s' } })}
              config={cfg} style={{ width: '100%' }} useResizeHandler
            />
          </Panel>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
            <Panel title="RSI (14)">
              <Plot data={[{ x: ind.timestamps, y: ind.rsi, mode: 'lines', line: { color: C.purple, width: 1.4 } }]}
                layout={baseLayout({ height: 200, showlegend: false, yaxis: { gridcolor: C.grid, range: [0, 100] },
                  shapes: [
                    { type: 'line', xref: 'paper', x0: 0, x1: 1, y0: 70, y1: 70, line: { color: C.red, width: 0.7, dash: 'dash' } },
                    { type: 'line', xref: 'paper', x0: 0, x1: 1, y0: 30, y1: 30, line: { color: C.green, width: 0.7, dash: 'dash' } },
                  ] })}
                config={cfg} style={{ width: '100%' }} useResizeHandler />
            </Panel>
            <Panel title="MACD (12·26·9)">
              <Plot data={[
                { x: ind.timestamps, y: ind.macd_hist, type: 'bar', name: 'Hist', marker: { color: (ind.macd_hist || []).map(v => v >= 0 ? 'rgba(76,175,125,0.6)' : 'rgba(224,82,82,0.6)') } },
                { x: ind.timestamps, y: ind.macd, name: 'MACD', mode: 'lines', line: { color: C.blue, width: 1.2 } },
                { x: ind.timestamps, y: ind.macd_signal, name: 'Signal', mode: 'lines', line: { color: C.accent, width: 1 } },
              ]} layout={baseLayout({ height: 200 })} config={cfg} style={{ width: '100%' }} useResizeHandler />
            </Panel>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
            <Panel title="Volume">
              <Plot data={[{ x: sbp[selPlace]?.timestamps, y: sbp[selPlace]?.volume, type: 'bar', marker: { color: 'rgba(155,109,214,0.5)' } }]}
                layout={baseLayout({ height: 200, showlegend: false, yaxis: { gridcolor: C.grid, tickformat: '.3s' } })}
                config={cfg} style={{ width: '100%' }} useResizeHandler />
            </Panel>
            <Panel title="Price distribution + current spread">
              {detail.distribution
                ? <Plot data={[{ type: 'bar', x: detail.distribution.edges.slice(0, -1).map((e, i) => (e + detail.distribution.edges[i + 1]) / 2), y: detail.distribution.counts, marker: { color: 'rgba(139,147,176,0.5)' } }]}
                    layout={baseLayout({ height: 200, showlegend: false, bargap: 0.02, xaxis: { gridcolor: C.grid, tickformat: '.3s' },
                      shapes: detail.spread ? [
                        { type: 'line', x0: detail.spread.buy, x1: detail.spread.buy, yref: 'paper', y0: 0, y1: 1, line: { color: C.blue, width: 1.2, dash: 'dash' } },
                        { type: 'line', x0: detail.spread.sell, x1: detail.spread.sell, yref: 'paper', y0: 0, y1: 1, line: { color: C.green, width: 1.2, dash: 'dash' } },
                      ] : [] })}
                    config={cfg} style={{ width: '100%' }} useResizeHandler />
                : <Empty msg="Need ≥5 points" />}
            </Panel>
          </div>
        </>
      ) : <div className="empty-state">No price history yet — click “Collect now”, then it builds hourly.</div>}
    </>
  )
}

/* ════════════════════════════ ALLOCATION ════════════════════════════ */

const SIGNAL_COLOR = { sell: '#4caf7d', hold: '#e05252', neutral: '#c8a951' }

function AllocationTab() {
  const [places, setPlaces]       = useState([])
  const [selPlaces, setSelPlaces] = useState({})    // {place_id: true}
  const [deliveryPlaces, setDeliveryPlaces] = useState({})
  const [rows, setRows]           = useState([])     // {type_id,name,quantity,cost}
  const [rawText, setRawText]     = useState('')
  const [projects, setProjects]   = useState([])
  const [loadProject, setLoadProject] = useState('')
  const [strategy, setStrategy]   = useState('balanced')
  const [fees, setFees]           = useState(8)
  const [deliveryCoef, setDeliveryCoef] = useState(1200)
  const [balanceDays, setBalanceDays]   = useState(7)
  const [result, setResult]       = useState(null)
  const [loading, setLoading]     = useState(false)
  const [error, setError]         = useState('')

  useEffect(() => {
    get('/tracking/places').then(setPlaces).catch(() => {})
    get('/organisations').then(async orgs => {
      const all = []
      for (const o of orgs) { try { all.push(...(await get(`/projects?org_id=${o.id}`))) } catch {} }
      setProjects(all)
    }).catch(() => {})
  }, [])

  async function parseList() {
    if (!rawText.trim()) return
    try {
      const res = await post('/inventory/preview', { text: rawText })
      setRows(res.items.map(i => ({ type_id: i.eve_type_id, name: i.name, quantity: i.quantity, cost: '' })))
    } catch (e) { setError(e.message) }
  }

  async function loadFromWarehouse() {
    setError('')
    try {
      const p = new URLSearchParams()
      if (loadProject) p.set('project_id', loadProject)
      const items = await get(`/inventory?${p}`)
      const g = {}
      for (const it of items) {
        if (!it.eve_type_id) continue
        const k = it.eve_type_id
        if (!g[k]) g[k] = { type_id: k, name: it.name, quantity: 0, value: 0, priced: 0 }
        g[k].quantity += it.quantity
        if (it.price) { g[k].value += it.price * it.quantity; g[k].priced += it.quantity }
      }
      setRows(Object.values(g).map(x => ({ type_id: x.type_id, name: x.name, quantity: x.quantity, cost: x.priced ? (x.value / x.priced).toFixed(2) : '' })))
    } catch (e) { setError(e.message) }
  }

  async function compute() {
    const place_ids = Object.keys(selPlaces).filter(k => selPlaces[k]).map(Number)
    if (!place_ids.length) { setError('Select at least one place'); return }
    if (!rows.length) { setError('Add items first'); return }
    setLoading(true); setError('')
    try {
      const res = await post('/tracking/allocate', {
        items: rows.filter(r => r.type_id && r.quantity > 0).map(r => ({ type_id: r.type_id, name: r.name, quantity: Number(r.quantity), cost: r.cost !== '' ? Number(r.cost) : null })),
        place_ids,
        delivery_place_ids: place_ids.filter(pid => deliveryPlaces[pid]),
        strategy, fees_pct: Number(fees), delivery_coef: Number(deliveryCoef), balance_days: Number(balanceDays),
      })
      setResult(res)
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }

  const setRow = (i, k, v) => setRows(rs => rs.map((r, idx) => idx === i ? { ...r, [k]: v } : r))

  return (
    <div>
      {error && <div className="error-box">{error}</div>}

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
        {/* items input */}
        <div className="card">
          <div style={{ fontSize: 12, fontWeight: 700, letterSpacing: 1, color: 'var(--accent)', marginBottom: 10 }}>ITEMS TO SELL</div>
          <textarea value={rawText} onChange={e => setRawText(e.target.value)} rows={4} placeholder={'Helium Fuel Block\t40000'} style={{ fontFamily: 'monospace', fontSize: 12 }} />
          <div style={{ display: 'flex', gap: 8, marginTop: 8, flexWrap: 'wrap', alignItems: 'center' }}>
            <button className="btn btn-ghost btn-sm" onClick={parseList}>▶ Parse</button>
            <span style={{ color: 'var(--border2)' }}>or</span>
            <select value={loadProject} onChange={e => setLoadProject(e.target.value)} style={{ width: 150 }}>
              <option value="">All warehouse</option>
              {projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
            <button className="btn btn-ghost btn-sm" onClick={loadFromWarehouse}>📦 Load from warehouse</button>
          </div>
          {rows.length > 0 && (
            <table style={{ marginTop: 10 }}>
              <thead><tr><th>Item</th><th>Qty</th><th>Cost/unit</th></tr></thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={i}>
                    <td style={{ color: r.type_id ? 'var(--text-white)' : '#e05252' }}>{r.name}{!r.type_id && ' (?)'}</td>
                    <td style={{ width: 90 }}><input type="number" value={r.quantity} onChange={e => setRow(i, 'quantity', e.target.value)} style={{ padding: '3px 6px' }} /></td>
                    <td style={{ width: 110 }}><input type="number" value={r.cost} onChange={e => setRow(i, 'cost', e.target.value)} placeholder="—" style={{ padding: '3px 6px' }} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* venues + strategy */}
        <div className="card">
          <div style={{ fontSize: 12, fontWeight: 700, letterSpacing: 1, color: 'var(--accent)', marginBottom: 10 }}>VENUES & STRATEGY</div>
          {places.length === 0 && <div style={{ fontSize: 12, color: 'var(--text)' }}>Add favourite places in the Tracking tab first.</div>}
          {places.map(p => (
            <div key={p.id} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, padding: '3px 0' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer' }}>
                <input type="checkbox" checked={!!selPlaces[p.id]} onChange={e => setSelPlaces(s => ({ ...s, [p.id]: e.target.checked }))} />
                <span style={{ color: 'var(--text-white)' }}>{p.name}</span>
              </label>
              <span className="badge" style={{ background: 'var(--surface3)', color: 'var(--text)' }}>{p.kind}</span>
              <label style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--text)', display: 'flex', gap: 4, alignItems: 'center', cursor: 'pointer' }}>
                <input type="checkbox" checked={!!deliveryPlaces[p.id]} onChange={e => setDeliveryPlaces(d => ({ ...d, [p.id]: e.target.checked }))} /> delivery
              </label>
            </div>
          ))}
          <div style={{ display: 'flex', gap: 4, marginTop: 12 }}>
            {[['fast', 'Fast sell'], ['balanced', 'Balanced'], ['maxprofit', 'Max profit']].map(([k, l]) => (
              <button key={k} className={`btn btn-sm ${strategy === k ? 'btn-primary' : 'btn-ghost'}`} onClick={() => setStrategy(k)}>{l}</button>
            ))}
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 10, marginTop: 12 }}>
            <div><label style={lbl}>Sell fees %</label><input type="number" value={fees} onChange={e => setFees(e.target.value)} /></div>
            <div><label style={lbl}>Delivery ISK/m³</label><input type="number" value={deliveryCoef} onChange={e => setDeliveryCoef(e.target.value)} /></div>
            <div><label style={lbl}>Balance days</label><input type="number" value={balanceDays} onChange={e => setBalanceDays(e.target.value)} /></div>
          </div>
          <button className="btn btn-primary" onClick={compute} disabled={loading} style={{ marginTop: 14, width: '100%' }}>
            {loading ? 'Computing…' : '⚖ Compute allocation'}
          </button>
        </div>
      </div>

      {result && result.items.map(it => <AllocItemResult key={it.type_id} it={it} />)}
    </div>
  )
}

function AllocItemResult({ it }) {
  return (
    <div className="card" style={{ padding: 0, marginBottom: 14, overflow: 'hidden' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 16px', background: 'var(--surface2)', borderBottom: '1px solid var(--border)', flexWrap: 'wrap' }}>
        <span style={{ color: 'var(--accent)', fontWeight: 600 }}>{it.name}</span>
        <span style={{ color: 'var(--text)', fontSize: 12 }}>×{it.quantity.toLocaleString()}</span>
        <span className="badge" style={{ background: (SIGNAL_COLOR[it.signal] || '#888') + '22', color: SIGNAL_COLOR[it.signal] || '#888', fontSize: 11 }}>
          {it.signal === 'sell' ? 'SELL NOW' : it.signal === 'hold' ? 'HOLD' : 'NEUTRAL'}
        </span>
        <span style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--text)' }}>
          Net <b style={{ color: 'var(--text-white)' }}>{fmtIsk(it.total_net)}</b>
          {it.total_profit != null && <> · Profit <b style={{ color: it.total_profit >= 0 ? '#4caf7d' : '#e05252' }}>{fmtIsk(it.total_profit)}</b></>}
        </span>
      </div>

      {/* venues 30d context */}
      <table>
        <thead><tr><th>Venue</th><th>Buy</th><th>Sell</th><th>30d avg</th><th>30d min/max</th><th>30d vol/day</th><th>Net instant</th><th>Net patient</th></tr></thead>
        <tbody>
          {it.venues.map(v => (
            <tr key={v.place_id}>
              <td style={{ color: 'var(--text-white)' }}>{v.place_name}{v.delivery_unit ? ' 🚚' : ''}</td>
              <td style={{ color: '#3a9bd6' }}>{fmtIsk(v.buy)}</td>
              <td style={{ color: '#4caf7d' }}>{fmtIsk(v.sell)}</td>
              <td style={{ color: 'var(--text)' }}>{fmtIsk(v.hist.avg)}</td>
              <td style={{ color: 'var(--text)', fontSize: 11 }}>{fmtIsk(v.hist.min)} / {fmtIsk(v.hist.max)}</td>
              <td style={{ color: 'var(--text)', fontSize: 12 }}>{v.hist.vol != null ? Math.round(v.hist.vol).toLocaleString() : '—'}</td>
              <td>{fmtIsk(v.net_instant)}</td>
              <td style={{ color: 'var(--accent)' }}>{fmtIsk(v.net_patient)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {/* allocation plan */}
      <div style={{ padding: '6px 16px', fontSize: 11, color: 'var(--accent)', fontWeight: 700, letterSpacing: 1, borderTop: '1px solid var(--border)' }}>ALLOCATION PLAN</div>
      <table>
        <thead><tr><th>Where</th><th>How much</th><th>Method</th><th>Net/unit</th><th>Net total</th><th>Est. time</th></tr></thead>
        <tbody>
          {it.allocations.length === 0
            ? <tr><td colSpan={6} style={{ color: 'var(--text)' }}>No priced venue available.</td></tr>
            : it.allocations.map((a, i) => (
              <tr key={i}>
                <td style={{ color: 'var(--text-white)' }}>{a.place_name}</td>
                <td>{a.qty.toLocaleString()}</td>
                <td style={{ fontSize: 12, color: a.method.startsWith('instant') ? '#3a9bd6' : '#4caf7d' }}>{a.method}</td>
                <td>{fmtIsk(a.unit_net)}</td>
                <td style={{ color: 'var(--text-white)' }}>{fmtIsk(a.net_total)}</td>
                <td style={{ color: 'var(--text)', fontSize: 12 }}>{a.est_days ? `~${a.est_days} d` : 'instant'}</td>
              </tr>
            ))}
        </tbody>
      </table>
    </div>
  )
}

const lbl = { display: 'block', fontSize: 11, color: 'var(--text)', marginBottom: 4 }

function RegionSearch({ value, onChange }) {
  const [q, setQ] = useState(value || '')
  const [results, setResults] = useState([])
  const [open, setOpen] = useState(false)
  const timer = useRef(null)
  function onInput(e) {
    const v = e.target.value; setQ(v)
    clearTimeout(timer.current)
    if (v.length < 2) { setResults([]); return }
    timer.current = setTimeout(async () => {
      try { setResults(await get(`/eve/regions?q=${encodeURIComponent(v)}`)); setOpen(true) } catch {}
    }, 250)
  }
  return (
    <div style={{ position: 'relative' }}>
      <input value={q} onChange={onInput} placeholder="Region (e.g. The Forge)…" />
      {open && results.length > 0 && (
        <ul style={{ position: 'absolute', zIndex: 999, width: '100%', background: 'var(--surface2)', border: '1px solid var(--border2)', borderRadius: 4, listStyle: 'none', maxHeight: 180, overflowY: 'auto', marginTop: 2 }}>
          {results.map(r => (
            <li key={r.region_id} onMouseDown={() => { onChange(r); setQ(r.region_name); setOpen(false) }}
              style={{ padding: '6px 12px', cursor: 'pointer', color: 'var(--text-white)', fontSize: 13 }}>
              {r.region_name}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function SmallStat({ label, value }) {
  return (
    <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 6, padding: '6px 14px' }}>
      <div style={{ fontSize: 10, color: 'var(--text)' }}>{label}</div>
      <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-white)' }}>{value}</div>
    </div>
  )
}

function StatRow({ stats }) {
  const cards = [
    { label: 'Last', value: fmtIsk(stats.last), accent: true },
    { label: 'Change', value: stats.change_pct == null ? '—' : `${stats.change_pct >= 0 ? '+' : ''}${stats.change_pct.toFixed(2)}%`, color: stats.change_pct >= 0 ? C.green : C.red },
    { label: 'Today max', value: fmtIsk(stats.today_max) },
    { label: 'Today min', value: fmtIsk(stats.today_min) },
    { label: 'Today avg', value: fmtIsk(stats.today_avg) },
    { label: 'All-time max', value: fmtIsk(stats.all_max) },
    { label: 'All-time min', value: fmtIsk(stats.all_min) },
    { label: 'Volatility', value: stats.volatility != null ? (stats.volatility * 100).toFixed(2) + '%' : '—' },
    { label: 'Liquidity', value: stats.liquidity != null ? stats.liquidity.toFixed(2) : '—' },
    { label: 'Entropy', value: stats.entropy != null ? stats.entropy.toFixed(2) : '—' },
    { label: 'Top-3 share', value: stats.top3_share != null ? (stats.top3_share * 100).toFixed(1) + '%' : '—' },
    { label: 'Points', value: stats.points },
  ]
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(120px,1fr))', gap: 8, marginBottom: 16 }}>
      {cards.map((c, i) => (
        <div key={i} style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 6, padding: '8px 12px' }}>
          <div style={{ fontSize: 10, color: 'var(--text)', textTransform: 'uppercase', letterSpacing: 0.5 }}>{c.label}</div>
          <div style={{ fontSize: 15, fontWeight: 600, color: c.color || (c.accent ? C.accent : C.white), marginTop: 3 }}>{c.value}</div>
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
