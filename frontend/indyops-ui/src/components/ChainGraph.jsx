import PropTypes from 'prop-types'
import * as factoryModule from 'react-plotly.js/factory'
import * as plotlyModule from 'plotly.js-dist-min'

// Same robust CJS/UMD interop as AnalysisPage — the bundler may wrap these
// modules under `.default` (or double-wrap) depending on the build.
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

const MAKE = '#4caf7d', BUY = '#3a9bd6', SKIP = '#e0884f', LEAF = '#5a6178'

/**
 * Sankey flow of the build chain: materials flow into the products they make.
 * Node colour = decision (green make / blue buy / orange skipped / grey raw).
 * Clicking a node asks the parent to skip-make it (force buy) and regenerate.
 */
export default function ChainGraph({ plan, forceBuy, onSkip }) {
  if (!Plot) return <div style={{ fontSize: 12, color: 'var(--text)', padding: 12 }}>Graph unavailable.</div>
  if (!plan?.decisions) return null

  const decisions = plan.decisions
  const ids = Object.keys(decisions).map(Number)
  const idx = {}
  ids.forEach((t, i) => { idx[t] = i })

  const skip = forceBuy instanceof Set ? forceBuy : new Set(forceBuy || [])
  const labels = ids.map(t => decisions[t]?.name || String(t))
  const colors = ids.map(t => {
    const d = decisions[t]
    if (skip.has(t)) return SKIP
    if (d?.decision === 'make') return MAKE
    if (d?.decision === 'buy') return (d.unit_make != null ? BUY : LEAF)
    return LEAF
  })

  // Links: child material → parent product, value = qty consumed (aggregated).
  const linkMap = {}
  ;(plan.jobs || []).forEach(j => {
    ;(j.inputs || []).forEach(inp => {
      if (idx[inp.type_id] == null || idx[j.type_id] == null) return
      const key = `${inp.type_id}>${j.type_id}`
      linkMap[key] = (linkMap[key] || 0) + inp.qty
    })
  })
  const source = [], target = [], value = []
  Object.entries(linkMap).forEach(([k, v]) => {
    const [s, t] = k.split('>').map(Number)
    source.push(idx[s]); target.push(idx[t]); value.push(v)
  })

  function handleClick(e) {
    const p = e?.points?.[0]
    // Node clicks carry a label and no link source/target; ignore link clicks.
    if (!p || p.label === undefined || p.source !== undefined) return
    const tid = ids[p.pointNumber]
    if (tid != null && onSkip) onSkip(tid)
  }

  return (
    <Plot
      data={[{
        type: 'sankey',
        orientation: 'h',
        arrangement: 'snap',
        node: {
          pad: 14, thickness: 14, label: labels, color: colors,
          line: { color: 'rgba(0,0,0,0.25)', width: 0.5 },
          hovertemplate: '%{label}<extra></extra>',
        },
        link: {
          source, target, value,
          color: 'rgba(120,130,160,0.20)',
          hovertemplate: '%{value:,} →<extra></extra>',
        },
      }]}
      layout={{
        height: Math.min(720, Math.max(320, ids.length * 26)),
        margin: { l: 8, r: 8, t: 8, b: 8 },
        paper_bgcolor: 'rgba(0,0,0,0)',
        plot_bgcolor: 'rgba(0,0,0,0)',
        font: { color: '#c8cfe0', size: 11 },
      }}
      config={{ displayModeBar: false, responsive: true }}
      style={{ width: '100%' }}
      onClick={handleClick}
    />
  )
}

ChainGraph.propTypes = {
  plan: PropTypes.object,
  forceBuy: PropTypes.oneOfType([PropTypes.instanceOf(Set), PropTypes.array]),
  onSkip: PropTypes.func,
}
