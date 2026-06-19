import { useEffect, useMemo, useState } from 'react'
import PropTypes from 'prop-types'
import * as factoryModule from 'react-plotly.js/factory'
import * as plotlyModule from 'plotly.js-dist-min'
import { get, post, download } from '../api/client'

// Same robust CJS/UMD interop as SimulationPanel / ChainGraph.
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
const signedPct = x => x == null ? '—' : `${x >= 0 ? '+' : ''}${(x * 100).toFixed(1)}%`
const signedIsk = x => x == null ? '—' : `${x >= 0 ? '+' : ''}${isk(x)}`
const GREEN = '#4caf7d'
const RED = '#e05252'
const AMBER = '#e0884f'
const sgn = x => (x >= 0 ? GREEN : RED)

const CAT_LABEL = {
  exogenous: 'Exogenous (market)',
  logistics: 'Logistics',
  demand: 'Market demand',
  counterfactual: 'Counterfactual',
  endogenous: 'Endogenous (decisions)',
}

// the custom-scenario builder knobs (label, field, default)
const CUSTOM_KNOBS = [
  ['Product price ×', 'product_price_mult', 1],
  ['Material price ×', 'material_price_mult', 1],
  ['Taxes ×', 'tax_mult', 1],
  ['Volatility ×', 'volatility_mult', 1],
  ['Volume ×', 'volume_mult', 1],
  ['Prod. cost ×', 'production_cost_mult', 1],
  ['Build time ×', 'time_mult', 1],
  ['Slots ×', 'slots_mult', 1],
]

function Th({ children, right }) {
  return <th style={{ textAlign: right ? 'right' : 'left', padding: '4px 8px', fontSize: 11,
                      color: 'var(--text)', borderBottom: '1px solid var(--border,#2a3140)' }}>{children}</th>
}
Th.propTypes = { children: PropTypes.node, right: PropTypes.bool }

function Td({ children, right, color, bold }) {
  return <td style={{ textAlign: right ? 'right' : 'left', padding: '4px 8px', fontSize: 12,
                      color: color || 'var(--text-white)', fontWeight: bold ? 700 : 400,
                      whiteSpace: 'nowrap' }}>{children}</td>
}
Td.propTypes = { children: PropTypes.node, right: PropTypes.bool, color: PropTypes.string, bold: PropTypes.bool }

export default function ScenarioPanel({ source, buildBody, targetTypeId, simRunId }) {
  const endpoint = source === 'chain' ? '/manufacturing/calculate-chain' : '/manufacturing/calculate'
  const [catalog, setCatalog] = useState(null)
  const [selected, setSelected] = useState(() => new Set())
  const [combine, setCombine] = useState(false)
  const [iters, setIters] = useState(25000)
  const [customs, setCustoms] = useState([])
  const [draft, setDraft] = useState(() => ({ name: 'Custom scenario' }))
  const [showCustom, setShowCustom] = useState(false)
  const [busy, setBusy] = useState('')
  const [err, setErr] = useState('')
  const [result, setResult] = useState(null)

  useEffect(() => {
    get('/simulation/scenarios').then(setCatalog).catch(e => setErr(e.message))
  }, [])

  const toggle = key => setSelected(s => {
    const n = new Set(s)
    if (n.has(key)) n.delete(key); else n.add(key)
    return n
  })

  const addCustom = () => {
    const c = { name: draft.name || 'Custom scenario' }
    CUSTOM_KNOBS.forEach(([, f]) => { if (draft[f] != null && Number(draft[f]) !== 1) c[f] = Number(draft[f]) })
    setCustoms(cs => [...cs, c])
    setDraft({ name: 'Custom scenario' })
  }

  const run = async () => {
    const body = buildBody?.()
    if (!body) { setErr('Run a calculation first.'); return }
    setBusy('run'); setErr('')
    const keys = [...selected]
    const scenarios = {
      keys: combine ? [] : keys,
      composites: combine && keys.length > 1 ? [keys] : [],
      custom: customs,
      params: { n_iterations: Number(iters) || 25000 },
    }
    try {
      const res = await post(endpoint, { ...body, share_base: window.location.origin, scenarios })
      const sa = res.scenario_analysis
      if (!sa) setErr('No scenario analysis returned.')
      else if (sa.error) setErr(sa.error)
      else setResult(sa)
    } catch (e) { setErr(e.message) } finally { setBusy('') }
  }

  const dl = async (path, name, key) => {
    setBusy(key)
    try { await download(path, name) } catch (e) { setErr(e.message) } finally { setBusy('') }
  }

  // build comparison rows (sorted by profit impact within category) + chart data
  const rows = useMemo(() => {
    if (!result?.outcomes) return []
    return [...result.outcomes].sort((a, b) =>
      (a.category || '').localeCompare(b.category || '') ||
      (b.comparison?.abs_profit_change || 0) - (a.comparison?.abs_profit_change || 0))
  }, [result])

  const tornado = useMemo(() => {
    if (!rows.length) return null
    const items = rows
      .map(o => ({ name: o.name, v: (o.comparison?.pct_profit_change || 0) * 100 }))
      .sort((a, b) => Math.abs(a.v) - Math.abs(b.v)).slice(-14)
    return items
  }, [rows])

  const baseEp = result?.baseline?.expected_profit

  return (
    <div style={{ border: '1px solid var(--border,#2a3140)', borderRadius: 8, padding: 14, margin: '14px 0',
                  background: 'var(--panel,#161b24)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
        <h3 style={{ margin: 0, color: 'var(--accent)' }}>🧪 Scenario Simulation</h3>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <label style={{ fontSize: 11, color: 'var(--text)' }}>iters{' '}
            <select value={iters} onChange={e => setIters(e.target.value)}>
              <option value={10000}>10k</option>
              <option value={25000}>25k</option>
              <option value={50000}>50k</option>
            </select>
          </label>
          <button className="btn btn-primary" disabled={busy === 'run'} onClick={run}>
            {busy === 'run' ? 'Running…' : '▶ Run Scenario Analysis'}
          </button>
        </div>
      </div>

      {err && <div style={{ color: RED, fontSize: 12, marginTop: 6 }}>{err}</div>}

      {/* scenario picker */}
      {!catalog && !err && <div style={{ fontSize: 12, color: 'var(--text)', marginTop: 8 }}>Loading scenarios…</div>}
      {catalog && (
        <div style={{ marginTop: 10 }}>
          <div style={{ fontSize: 11, color: 'var(--text)', marginBottom: 6 }}>
            Pick scenarios to evaluate, or run with none selected for the full predefined suite.
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(230px,1fr))', gap: 10 }}>
            {catalog.categories.map(cat => (
              <div key={cat.category} style={{ border: '1px solid var(--border,#2a3140)', borderRadius: 6, padding: 8 }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--accent)', marginBottom: 4 }}>
                  {CAT_LABEL[cat.category] || cat.category}
                </div>
                {cat.scenarios.map(s => (
                  <label key={s.key} title={s.description}
                         style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, padding: '1px 0', cursor: 'pointer' }}>
                    <input type="checkbox" checked={selected.has(s.key)} onChange={() => toggle(s.key)} />
                    {s.name}
                  </label>
                ))}
              </div>
            ))}
          </div>
          <div style={{ display: 'flex', gap: 14, alignItems: 'center', flexWrap: 'wrap', marginTop: 8 }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 12, color: 'var(--text)' }}>
              <input type="checkbox" checked={combine} onChange={e => setCombine(e.target.checked)} />
              Combine selected into one composite stress test
            </label>
            <button className="btn btn-ghost" onClick={() => setShowCustom(v => !v)}>
              {showCustom ? '▾' : '▸'} Custom scenario builder ({customs.length})
            </button>
            {selected.size > 0 && (
              <button className="btn btn-ghost" onClick={() => setSelected(new Set())}>Clear ({selected.size})</button>
            )}
          </div>
        </div>
      )}

      {/* custom builder */}
      {showCustom && (
        <div style={{ marginTop: 10, border: '1px dashed var(--border,#2a3140)', borderRadius: 6, padding: 10 }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(140px,1fr))', gap: 8 }}>
            <label style={{ fontSize: 11, color: 'var(--text)' }}>Name
              <input value={draft.name || ''} onChange={e => setDraft(d => ({ ...d, name: e.target.value }))}
                     style={{ width: '100%' }} />
            </label>
            {CUSTOM_KNOBS.map(([label, field, def]) => (
              <label key={field} style={{ fontSize: 11, color: 'var(--text)' }}>{label}
                <input type="number" step="0.05" value={draft[field] ?? def}
                       onChange={e => setDraft(d => ({ ...d, [field]: e.target.value }))}
                       style={{ width: '100%' }} />
              </label>
            ))}
          </div>
          <button className="btn btn-ghost" style={{ marginTop: 6 }} onClick={addCustom}>+ Add custom scenario</button>
          {customs.length > 0 && (
            <div style={{ marginTop: 6, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {customs.map((c, i) => (
                <span key={i} style={{ fontSize: 11, padding: '2px 8px', borderRadius: 10, background: '#23304a', color: '#7da7e0' }}>
                  {c.name}
                  <button onClick={() => setCustoms(cs => cs.filter((_, j) => j !== i))}
                          style={{ marginLeft: 6, background: 'none', border: 'none', color: RED, cursor: 'pointer' }}>×</button>
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* results */}
      {result && (
        <div style={{ marginTop: 14 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
            <div style={{ fontSize: 12, color: 'var(--text)' }}>
              <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 10, marginRight: 8,
                             background: result.engine === 'fortran' ? '#13351f' : '#23304a',
                             color: result.engine === 'fortran' ? GREEN : '#7da7e0' }}>
                {result.engine} · {result.n_scenarios} scenarios
              </span>
              Baseline E[Profit] <b style={{ color: sgn(baseEp || 0) }}>{isk(baseEp)}</b>
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <button className="btn btn-ghost" disabled={busy === 'pdf'}
                      onClick={() => dl(`/simulation/scenario-runs/${result.analysis_id}/pdf`,
                        `scenario_${result.analysis_id}.pdf`, 'pdf')}>📄 Scenario PDF</button>
              {targetTypeId != null && (
                <button className="btn btn-ghost" disabled={busy === 'product'}
                        title="Combined report for THIS build: this scenario analysis + its Monte-Carlo run"
                        onClick={() => {
                          const q = new URLSearchParams({ analysis_id: result.analysis_id })
                          if (simRunId != null) q.set('run_id', simRunId)
                          dl(`/simulation/reports/product/${targetTypeId}/pdf?${q}`,
                            `product_${targetTypeId}_report.pdf`, 'product')
                        }}>📚 Full product report</button>
              )}
            </div>
          </div>

          {/* comparison table */}
          <div style={{ overflowX: 'auto', marginTop: 10 }}>
            <table style={{ borderCollapse: 'collapse', width: '100%' }}>
              <thead>
                <tr>
                  <Th>Scenario</Th><Th>Category</Th><Th right>E[Profit]</Th><Th right>Δ Profit</Th>
                  <Th right>Δ %</Th><Th right>σ</Th><Th right>VaR 5%</Th><Th right>P(loss)</Th>
                  <Th right>ROI Δ</Th><Th right>Viable</Th>
                </tr>
              </thead>
              <tbody>
                <tr style={{ background: 'rgba(125,167,224,0.08)' }}>
                  <Td bold>● Baseline</Td><Td>—</Td>
                  <Td right bold color={sgn(baseEp || 0)}>{isk(baseEp)}</Td>
                  <Td right>—</Td><Td right>—</Td>
                  <Td right>{isk(result.baseline?.std)}</Td>
                  <Td right color={AMBER}>{isk(result.baseline?.var5)}</Td>
                  <Td right>{pct(result.baseline?.prob_loss)}</Td>
                  <Td right>—</Td>
                  <Td right>{(result.baseline?.expected_profit || 0) > 0 ? '✓' : '✗'}</Td>
                </tr>
                {rows.map(o => {
                  const c = o.comparison || {}, m = o.metrics || {}
                  return (
                    <tr key={o.key}>
                      <Td>{o.name}</Td>
                      <Td color="var(--text)">{CAT_LABEL[o.category] || o.category}</Td>
                      <Td right color={sgn(m.expected_profit || 0)}>{isk(m.expected_profit)}</Td>
                      <Td right color={sgn(c.abs_profit_change || 0)}>{signedIsk(c.abs_profit_change)}</Td>
                      <Td right color={sgn(c.pct_profit_change || 0)}>{signedPct(c.pct_profit_change)}</Td>
                      <Td right>{isk(m.std)}</Td>
                      <Td right color={AMBER}>{isk(m.var5)}</Td>
                      <Td right color={(m.prob_loss || 0) > 0.25 ? RED : 'var(--text-white)'}>{pct(m.prob_loss)}</Td>
                      <Td right color={sgn(c.roi_change || 0)}>{signedPct(c.roi_change)}</Td>
                      <Td right color={c.viable ? GREEN : RED}>{c.viable ? '✓' : '✗'}</Td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          {/* sensitivity tornado */}
          {Plot && tornado && tornado.length > 0 && (
            <div style={{ marginTop: 12 }}>
              <div style={{ fontSize: 11, color: 'var(--text)', marginBottom: 2 }}>Sensitivity — profit change vs baseline (%)</div>
              <Plot
                data={[{
                  type: 'bar', orientation: 'h',
                  x: tornado.map(t => t.v), y: tornado.map(t => t.name),
                  marker: { color: tornado.map(t => (t.v >= 0 ? GREEN : RED)) },
                }]}
                layout={{
                  height: Math.max(180, 26 * tornado.length + 40),
                  margin: { l: 160, r: 16, t: 6, b: 30 },
                  paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
                  font: { color: '#aeb6c2', size: 11 },
                  xaxis: { title: 'Δ profit (%)', zeroline: true, zerolinecolor: '#556' },
                  yaxis: { automargin: true },
                }}
                config={{ displayModeBar: false, responsive: true }}
                style={{ width: '100%' }}
              />
            </div>
          )}

          {/* strategy ranking */}
          {result.ranking?.length > 0 && (
            <div style={{ marginTop: 12 }}>
              <div style={{ fontSize: 11, color: 'var(--text)', marginBottom: 4 }}>Risk-adjusted strategy ranking</div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                {result.ranking.slice(0, 8).map(r => (
                  <span key={r.rank} style={{ fontSize: 11, padding: '2px 8px', borderRadius: 10,
                                              background: r.rank === 1 ? '#13351f' : '#23304a',
                                              color: r.rank === 1 ? GREEN : '#aeb6c2' }}>
                    #{r.rank} {r.label} ({r.score?.toFixed(2)})
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

ScenarioPanel.propTypes = {
  source: PropTypes.oneOf(['production', 'chain']).isRequired,
  buildBody: PropTypes.func.isRequired,
  targetTypeId: PropTypes.oneOfType([PropTypes.number, PropTypes.string]),
  simRunId: PropTypes.oneOfType([PropTypes.number, PropTypes.string]),
}
