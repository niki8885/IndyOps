import { useState, useEffect } from 'react'
import createPlotlyComponent from 'react-plotly.js/factory'
import Plotly from 'plotly.js-dist-min'
import { get, post } from '../api/client'

const Plot = createPlotlyComponent(Plotly)

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
  const [indices, setIndices]   = useState([])
  const [sel, setSel]           = useState('mineral')
  const [detail, setDetail]     = useState(null)
  const [window, setWindow]     = useState(10)
  const [loading, setLoading]   = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [showIchimoku, setShowIchimoku] = useState(false)

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

  async function refresh() {
    setRefreshing(true)
    try { await post('/analysis/refresh', {}); await loadIndices(); await loadDetail() }
    catch {} finally { setRefreshing(false) }
  }

  const ts = detail?.timestamps || []
  const s  = detail?.series || {}

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 18, flexWrap: 'wrap' }}>
        <h2>Analysis</h2>
        <span style={{ fontSize: 11, color: 'var(--text)' }}>EVE commodity indices · hourly</span>
        <button className="btn btn-ghost btn-sm" onClick={refresh} disabled={refreshing} style={{ marginLeft: 'auto' }}>
          {refreshing ? 'Collecting…' : '⟳ Collect snapshot now'}
        </button>
      </div>

      {/* index cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(150px,1fr))', gap: 10, marginBottom: 18 }}>
        {indices.map(ix => (
          <button key={ix.key} onClick={() => setSel(ix.key)}
            style={{
              textAlign: 'left', cursor: 'pointer', padding: '10px 12px', borderRadius: 6,
              background: sel === ix.key ? 'var(--surface3)' : 'var(--surface)',
              border: `1px solid ${sel === ix.key ? 'var(--accent)' : 'var(--border)'}`,
            }}>
            <div style={{ fontSize: 12, color: sel === ix.key ? 'var(--accent)' : 'var(--text-white)', fontWeight: 600 }}>{ix.label}</div>
            <div style={{ fontSize: 14, color: 'var(--text-white)', marginTop: 4 }}>{fmtIsk(ix.last_price)}</div>
            <div style={{ fontSize: 11, color: ix.change_pct == null ? 'var(--text)' : ix.change_pct >= 0 ? C.green : C.red }}>
              {ix.change_pct == null ? `${ix.points} pts` : `${ix.change_pct >= 0 ? '▲' : '▼'} ${Math.abs(ix.change_pct).toFixed(2)}%`}
            </div>
          </button>
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
          click “Collect snapshot now” to capture the first point.
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
