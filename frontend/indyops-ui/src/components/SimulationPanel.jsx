import { useEffect, useState } from 'react'
import PropTypes from 'prop-types'
import * as factoryModule from 'react-plotly.js/factory'
import * as plotlyModule from 'plotly.js-dist-min'
import { get, download } from '../api/client'

// Same robust CJS/UMD interop as ChainGraph / AnalysisPage.
function asFn(m) {
  if (typeof m === 'function') return m
  if (typeof m?.default === 'function') return m.default
  if (typeof m?.default?.default === 'function') return m.default.default
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

const isk = x => {
  if (x == null) return '—'
  const a = Math.abs(x)
  if (a >= 1e9) return `${(x / 1e9).toFixed(2)} B`
  if (a >= 1e6) return `${(x / 1e6).toFixed(2)} M`
  if (a >= 1e3) return `${(x / 1e3).toFixed(2)} K`
  return x.toFixed(2)
}
const pct = x => x == null ? '—' : `${(x * 100).toFixed(2)}%`
const num = (x, n = 2) => x == null ? '—' : Number(x).toFixed(n)

function Stat({ label, value, color, sub }) {
  return (
    <div>
      <div style={{ fontSize: 11, color: 'var(--text)' }}>{label}</div>
      <div style={{ fontWeight: 700, fontSize: 16, color: color || 'var(--text-white)' }}>{value}</div>
      {sub && <div style={{ fontSize: 10, color: 'var(--text)' }}>{sub}</div>}
    </div>
  )
}

Stat.propTypes = {
  label: PropTypes.node,
  value: PropTypes.node,
  color: PropTypes.string,
  sub: PropTypes.node,
}

// Mean cost breakdown (revenue vs material / taxes / logistics) as horizontal bars.
function BreakdownBars({ m }) {
  const bd = m.breakdown || {}
  const rows = [
    ['Revenue', bd.revenue?.mean, '#4caf7d'],
    ['Material', bd.material_cost?.mean, '#e0884f'],
    ['Taxes & fees', bd.taxes_fees?.mean, '#7da7e0'],
    ['Logistics', bd.logistics?.mean, '#b06bd6'],
  ].map(([l, v, c]) => [l, Number(v || 0), c])
  const max = Math.max(1, ...rows.map(r => r[1]))
  return (
    <div>
      <div style={{ fontSize: 11, color: 'var(--text)', marginBottom: 4 }}>Mean cost breakdown</div>
      {rows.map(([l, v, c]) => (
        <div key={l} style={{ display: 'flex', alignItems: 'center', gap: 8, margin: '3px 0' }}>
          <span style={{ width: 86, fontSize: 11, color: 'var(--text)' }}>{l}</span>
          <span style={{ flex: 1, background: '#222a37', borderRadius: 3, height: 12, overflow: 'hidden' }}>
            <span style={{ display: 'block', width: `${Math.max(2, (v / max) * 100)}%`, height: '100%', background: c }} />
          </span>
          <span style={{ width: 66, textAlign: 'right', fontSize: 11, color: 'var(--text-white)' }}>{isk(v)}</span>
        </div>
      ))}
    </div>
  )
}
BreakdownBars.propTypes = { m: PropTypes.object }

// Profit percentile strip p1…p99.
function PercentileStrip({ m }) {
  const p = m.percentiles || {}
  const keys = [['p1', '1%'], ['p5', '5%'], ['p25', '25%'], ['p50', '50%'], ['p75', '75%'], ['p95', '95%'], ['p99', '99%']]
  return (
    <div>
      <div style={{ fontSize: 11, color: 'var(--text)', marginBottom: 4 }}>Profit percentiles</div>
      <div style={{ display: 'flex', flexWrap: 'wrap' }}>
        {keys.map(([k, lbl]) => (
          <div key={k} style={{ flex: '1 0 50px', textAlign: 'center', padding: '2px 0' }}>
            <div style={{ fontSize: 10, color: 'var(--text)' }}>{lbl}</div>
            <div style={{ fontSize: 11, fontWeight: 600, color: (p[k] ?? 0) >= 0 ? '#4caf7d' : '#e05252' }}>{isk(p[k])}</div>
          </div>
        ))}
      </div>
    </div>
  )
}
PercentileStrip.propTypes = { m: PropTypes.object }

// Operational / completion-time metrics.
function OperationalBlock({ m }) {
  const items = [
    ['Mean completion', `${num(m.time_mean_h, 2)} h`],
    ['Median', `${num(m.time_median_h, 2)} h`],
    ['95th percentile', `${num(m.time_p95_h, 2)} h`],
    ['Per job / slot', `${num(m.time_per_job_h, 2)} h`],
  ]
  return (
    <div>
      <div style={{ fontSize: 11, color: 'var(--text)', marginBottom: 4 }}>Operational (time)</div>
      {items.map(([l, v]) => (
        <div key={l} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, margin: '2px 0' }}>
          <span style={{ color: 'var(--text)' }}>{l}</span>
          <span style={{ color: 'var(--text-white)' }}>{v}</span>
        </div>
      ))}
    </div>
  )
}
OperationalBlock.propTypes = { m: PropTypes.object }

// ± half-width of a 95% CI [lo,hi]
const ciHalf = (ci) => (Array.isArray(ci) && ci.length === 2) ? (ci[1] - ci[0]) / 2 : null

export default function SimulationPanel({ run, projectId }) {
  const [detail, setDetail] = useState(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState('')

  useEffect(() => {
    if (!run?.run_id) return
    setDetail(null); setErr('')
    get(`/simulation/runs/${run.run_id}`).then(setDetail).catch(e => setErr(e.message))
  }, [run?.run_id])

  if (!run) return null
  if (run.error) {
    return (
      <div style={{ padding: 12, border: '1px solid #e05252', borderRadius: 6, color: '#e05252', margin: '12px 0' }}>
        Monte-Carlo simulation failed: {run.error}
      </div>
    )
  }

  const m = detail?.metrics
  const s = run.summary || {}
  const ep = m?.expected_profit ?? s.expected_profit
  const lossColor = (s.prob_loss ?? 0) > 0.25 ? '#e05252' : '#4caf7d'

  // profit-distribution histogram (bin centres × counts) with E[Profit] / VaR5 markers
  let chart = null
  if (Plot && m?.hist_counts?.length && m?.hist_edges?.length === m.hist_counts.length + 1) {
    const centres = m.hist_counts.map((_, i) => (m.hist_edges[i] + m.hist_edges[i + 1]) / 2)
    const shape = (x, color) => ({
      type: 'line', x0: x, x1: x, yref: 'paper', y0: 0, y1: 1,
      line: { color, width: 2, dash: 'dash' },
    })
    chart = (
      <Plot
        data={[{ type: 'bar', x: centres, y: m.hist_counts, marker: { color: '#3a7bd6' }, name: 'scenarios' }]}
        layout={{
          height: 280, margin: { l: 48, r: 16, t: 10, b: 40 },
          paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
          font: { color: '#aeb6c2', size: 11 },
          xaxis: { title: 'Net profit (ISK)', zeroline: true, zerolinecolor: '#556' },
          yaxis: { title: 'Scenarios' },
          shapes: [shape(m.expected_profit, '#4caf7d'), shape(m.var5, '#e0884f'), shape(0, '#e05252')],
          showlegend: false,
        }}
        config={{ displayModeBar: false, responsive: true }}
        style={{ width: '100%' }}
      />
    )
  }

  const dl = async (path, name, key) => {
    setBusy(key)
    try { await download(path, name) } catch (e) { setErr(e.message) } finally { setBusy('') }
  }

  return (
    <div style={{ border: '1px solid var(--border, #2a3140)', borderRadius: 8, padding: 14, margin: '14px 0',
                  background: 'var(--panel, #161b24)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
        <h3 style={{ margin: 0, color: 'var(--accent)' }}>🎲 Monte-Carlo profit simulation</h3>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 10,
                         background: run.engine === 'fortran' ? '#13351f' : '#23304a',
                         color: run.engine === 'fortran' ? '#4caf7d' : '#7da7e0' }}>
            {run.engine} · {(run.n_iterations || s.n_iterations || 0).toLocaleString()} runs
          </span>
          <button className="btn btn-ghost" disabled={busy === 'run'}
                  onClick={() => dl(`/simulation/runs/${run.run_id}/pdf`, `simulation_${run.run_id}.pdf`, 'run')}>
            📄 Report PDF
          </button>
          {projectId != null && (
            <button className="btn btn-ghost" disabled={busy === 'roll'}
                    onClick={() => dl(`/simulation/reports/project/${projectId}/pdf`, `project_${projectId}_simulations.pdf`, 'roll')}>
              📚 Project roll-up
            </button>
          )}
        </div>
      </div>

      {err && <div style={{ color: '#e05252', fontSize: 12, marginTop: 6 }}>{err}</div>}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(130px,1fr))', gap: 12, marginTop: 12 }}>
        <Stat label="Expected profit" value={isk(ep)} color={ep >= 0 ? '#4caf7d' : '#e05252'}
              sub={m && ciHalf(m.ci95?.expected_profit) != null ? `95% CI ±${isk(ciHalf(m.ci95.expected_profit))}` : null} />
        <Stat label="Median" value={isk(m?.median_profit ?? s.median_profit)} />
        <Stat label="Std σ" value={isk(m?.std ?? s.std)} />
        <Stat label="Coef. of variation" value={num(m?.cv ?? s.cv, 3)} />
        <Stat label="VaR 5%" value={isk(m?.var5 ?? s.var5)} color="#e0884f"
              sub={m && ciHalf(m.ci95?.var5) != null ? `±${isk(ciHalf(m.ci95.var5))}` : null} />
        <Stat label="VaR 1%" value={isk(m?.var1 ?? s.var1)} color="#e0884f" />
        <Stat label="CVaR 5%" value={isk(m?.cvar5 ?? s.cvar5)} color="#e0884f" />
        <Stat label="Worst 1%" value={isk(m?.worst1 ?? s.worst1)} color="#e05252" />
        <Stat label="Prob. of loss" value={pct(m?.prob_loss ?? s.prob_loss)} color={lossColor} />
        <Stat label="Sharpe-like" value={num(m?.sharpe_like ?? s.sharpe_like, 3)} />
        <Stat label="Return / slot" value={isk(m?.return_per_slot ?? s.return_per_slot)} />
        <Stat label="Return / hour" value={isk(m?.return_per_time ?? s.return_per_time)} />
      </div>

      {m && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(230px,1fr))', gap: 18,
                      marginTop: 14, paddingTop: 12, borderTop: '1px solid var(--border,#2a3140)' }}>
          <BreakdownBars m={m} />
          <PercentileStrip m={m} />
          <OperationalBlock m={m} />
        </div>
      )}

      {!detail && !err && <div style={{ fontSize: 12, color: 'var(--text)', marginTop: 10 }}>Loading distribution…</div>}
      {chart && <div style={{ marginTop: 12 }}>{chart}</div>}
      {m && (
        <div style={{ fontSize: 11, color: 'var(--text)', marginTop: 6 }}>
          Best {isk(m.best)} · Worst {isk(m.worst)} · Mean completion {num(m.time_mean_h, 2)} h
          {' '}(<span style={{ color: '#4caf7d' }}>— E[Profit]</span>,{' '}
          <span style={{ color: '#e0884f' }}>— VaR 5%</span>,{' '}
          <span style={{ color: '#e05252' }}>— break-even</span>)
          {m.mc_rel_error != null && (
            <span> · MC error {(m.mc_rel_error * 100).toFixed(2)}% ·{' '}
              <span style={{ color: m.converged ? '#4caf7d' : '#e0884f' }}>
                {m.converged ? '✓ converged' : '⚠ increase iterations'}
              </span>
            </span>
          )}
        </div>
      )}
    </div>
  )
}

SimulationPanel.propTypes = {
  run: PropTypes.object,
  projectId: PropTypes.oneOfType([PropTypes.number, PropTypes.string]),
}
