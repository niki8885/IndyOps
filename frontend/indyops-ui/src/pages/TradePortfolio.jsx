// Trade Optimizer → Portfolio tab. Markowitz mean-variance allocation of an ISK budget
// across the cross-hub candidates (POST /trade/portfolio) — the same engine as the
// Jita → C-J haul portfolio. Shows the optimal buy list, totals, and an efficient-frontier
// scatter. Self-contained formatters + a hand-rolled SVG chart keep this Plotly-free so the
// Trade Optimizer stays in the main bundle.
import { useState } from 'react'
import { post } from '../api/client'

function fmtIsk(v) {
  if (v == null) return '—'
  const n = Number(v)
  if (Math.abs(n) >= 1e9) return (n / 1e9).toFixed(2) + ' B'
  if (Math.abs(n) >= 1e6) return (n / 1e6).toFixed(2) + ' M'
  if (Math.abs(n) >= 1e3) return (n / 1e3).toFixed(1) + ' K'
  return n.toLocaleString(undefined, { maximumFractionDigits: 2 })
}
const fmtNum = v => (v == null ? '—' : Number(v).toLocaleString(undefined, { maximumFractionDigits: 0 }))
const pct = v => (v == null ? '—' : (Number(v) * 100).toFixed(1) + '%')
const iconUrl = (id, size = 32) => `https://images.evetech.net/types/${id}/icon?size=${size}`
const GREEN = '#4caf7d', BLUE = '#3a9bd6', ACCENT = '#c8a951'
const cell = { textAlign: 'right', whiteSpace: 'nowrap' }

export default function TradePortfolio({ budget, buyHubs, sellHubs, strategy, minMargin, cargo, minVol, risk, setRisk }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')

  async function optimize() {
    setLoading(true); setErr('')
    try {
      const body = {
        budget: Number(budget) || 0,
        strategy,
        min_margin: minMargin ? Number(minMargin) / 100 : 0,
        min_volume: Number(minVol) || 0,
        risk_aversion: Number(risk) || undefined,
      }
      if (buyHubs.length) body.buy_hubs = buyHubs.join(',')
      if (sellHubs.length) body.sell_hubs = sellHubs.join(',')
      if (cargo) body.cargo = Number(cargo)
      setData(await post('/trade/portfolio', body))
    } catch (e) { setErr(e.message); setData(null) }
    finally { setLoading(false) }
  }

  const result = data?.result
  const t = result?.totals
  const allocs = (result?.allocations || []).filter(a => a.qty > 0)

  return (
    <div>
      <div className="card" style={{ padding: 16, marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
          <div style={{ flex: 1, minWidth: 220 }}>
            <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: 1, color: ACCENT, marginBottom: 6 }}>
              RISK AVERSION λ — {Number(risk).toFixed(0)}
            </div>
            <input type="range" min="1" max="200" step="1" value={risk}
              onChange={e => setRisk(Number(e.target.value))} style={{ width: '100%' }} />
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: 'var(--text)' }}>
              <span>aggressive (concentrate)</span><span>cautious (diversify)</span>
            </div>
          </div>
          <button className="btn btn-primary" onClick={optimize} disabled={loading || !(Number(budget) > 0)}
            style={{ minWidth: 180 }}>
            {loading ? 'Optimizing…' : 'Optimize portfolio'}
          </button>
        </div>
        {!(Number(budget) > 0) && (
          <div style={{ fontSize: 11, color: 'var(--text)', marginTop: 8 }}>
            Set an ISK budget in the filters to allocate. Buy/sell hubs, strategy, min margin and the volume slider all apply.
          </div>
        )}
      </div>

      {err && <div className="error-box">{err}</div>}
      {loading && !data && <div className="empty-state">Optimizing…</div>}

      {data && allocs.length === 0 && (
        <div className="empty-state">
          No candidates to allocate. Loosen the filters / volume floor, or check the worker has populated the tables.
        </div>
      )}

      {data && allocs.length > 0 && (
        <>
          <div className="card" style={{ padding: '12px 14px', marginBottom: 16, display: 'flex', flexWrap: 'wrap', gap: 26 }}>
            <Metric label="Capital used" value={fmtIsk(t.capital_used)} />
            <Metric label="Leftover" value={fmtIsk(t.leftover)} />
            <Metric label="Expected profit" value={fmtIsk(t.expected_profit)} accent />
            <Metric label="Portfolio ROI" value={pct(t.portfolio_roi)} />
            <Metric label="Risk (σ)" value={pct(t.stddev)} />
            <Metric label="Total m³" value={fmtNum(t.total_volume_m3)} />
            <Metric label="Items" value={`${t.n_assets} / ${t.n_considered}`} />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 320px', gap: 16, alignItems: 'start' }}>
            <Panel title="Optimal buy list">
              <div style={{ maxHeight: 560, overflowY: 'auto' }}>
                <table>
                  <thead><tr>
                    <Th>Item</Th><Th>Route</Th><Th r>Qty</Th><Th r>Unit cost</Th>
                    <Th r>Capital</Th><Th r>Weight</Th><Th r>Exp. profit</Th><Th r>ROI</Th>
                  </tr></thead>
                  <tbody>
                    {allocs.map(a => (
                      <tr key={a.type_id}>
                        <td>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                            <img src={iconUrl(a.type_id, 32)} alt="" width={22} height={22}
                              style={{ borderRadius: 3, background: 'var(--surface3)' }} />
                            <span style={{ color: 'var(--text-white)' }}>{a.name || a.type_id}</span>
                          </div>
                        </td>
                        <td style={{ whiteSpace: 'nowrap', fontSize: 12 }}>{a.best_method}</td>
                        <td style={cell}>{fmtNum(a.qty)}</td>
                        <td style={cell}>{fmtIsk(a.unit_cost)}</td>
                        <td style={cell}>{fmtIsk(a.capital)}</td>
                        <td style={{ ...cell, color: BLUE }}>{pct(a.weight)}</td>
                        <td style={{ ...cell, color: GREEN }}>{fmtIsk(a.expected_profit)}</td>
                        <td style={cell}>{pct(a.roi)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Panel>

            <Panel title="Efficient frontier">
              <Frontier frontier={result.frontier} />
              <div style={{ fontSize: 11, color: 'var(--text)', marginTop: 8 }}>
                Risk (σ) vs expected return. The line is the optimal trade-off across risk-aversion;
                ◆ is your chosen portfolio, dots are individual items. Engine: {data.meta.engine}.
              </div>
            </Panel>
          </div>
        </>
      )}
    </div>
  )
}

function Frontier({ frontier }) {
  if (!frontier || !frontier.points || frontier.points.length === 0) {
    return <div style={{ color: 'var(--text)', fontSize: 12 }}>—</div>
  }
  const W = 300, H = 220, P = 34
  const pts = frontier.points
  const assets = frontier.assets || []
  const chosen = frontier.chosen
  const xs = [...pts, ...assets, chosen].filter(Boolean).map(p => p.stddev)
  const ys = [...pts, ...assets, chosen].filter(Boolean).map(p => p.exp_return)
  const xMin = Math.min(...xs), xMax = Math.max(...xs) || 1
  const yMin = Math.min(...ys, 0), yMax = Math.max(...ys) || 1
  const sx = v => P + ((v - xMin) / (xMax - xMin || 1)) * (W - 2 * P)
  const sy = v => H - P - ((v - yMin) / (yMax - yMin || 1)) * (H - 2 * P)
  const line = pts.map((p, i) => `${i ? 'L' : 'M'}${sx(p.stddev).toFixed(1)},${sy(p.exp_return).toFixed(1)}`).join(' ')

  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto' }}>
      {/* axes */}
      <line x1={P} y1={H - P} x2={W - P} y2={H - P} stroke="var(--border2)" strokeWidth="1" />
      <line x1={P} y1={P} x2={P} y2={H - P} stroke="var(--border2)" strokeWidth="1" />
      <text x={W / 2} y={H - 6} fill="var(--text)" fontSize="10" textAnchor="middle">risk σ →</text>
      <text x={10} y={H / 2} fill="var(--text)" fontSize="10" textAnchor="middle"
        transform={`rotate(-90 10 ${H / 2})`}>expected return →</text>
      {/* frontier line */}
      {pts.length > 1 && <path d={line} fill="none" stroke={ACCENT} strokeWidth="1.6" opacity="0.85" />}
      {/* individual assets */}
      {assets.map((a, i) => (
        <circle key={i} cx={sx(a.stddev)} cy={sy(a.exp_return)} r="2.5" fill={BLUE} opacity="0.6">
          <title>{`${a.name}: σ ${pct(a.stddev)}, ret ${pct(a.exp_return)}`}</title>
        </circle>
      ))}
      {/* chosen portfolio */}
      {chosen && (
        <path d={`M${sx(chosen.stddev)},${sy(chosen.exp_return) - 5} L${sx(chosen.stddev) + 5},${sy(chosen.exp_return)} L${sx(chosen.stddev)},${sy(chosen.exp_return) + 5} L${sx(chosen.stddev) - 5},${sy(chosen.exp_return)} Z`}
          fill={GREEN} stroke="#fff" strokeWidth="0.8">
          <title>{`Chosen: σ ${pct(chosen.stddev)}, ret ${pct(chosen.exp_return)}`}</title>
        </path>
      )}
    </svg>
  )
}

function Metric({ label, value, accent }) {
  return (
    <div>
      <div style={{ fontSize: 11, color: 'var(--text)', textTransform: 'uppercase', letterSpacing: 0.4 }}>{label}</div>
      <div style={{ fontSize: 15, color: accent ? 'var(--accent)' : 'var(--text-white)', fontWeight: 600 }}>{value}</div>
    </div>
  )
}

function Th({ children, r }) {
  return <th style={{ textAlign: r ? 'right' : 'left' }}>{children}</th>
}

function Panel({ title, children }) {
  return (
    <div className="card" style={{ padding: '12px 14px', marginBottom: 16 }}>
      <div style={{ fontSize: 11, color: 'var(--accent)', fontWeight: 700, letterSpacing: 1, marginBottom: 8 }}>
        {title.toUpperCase()}
      </div>
      {children}
    </div>
  )
}
