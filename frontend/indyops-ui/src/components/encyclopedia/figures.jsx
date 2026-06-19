import PropTypes from 'prop-types'

// Inline SVGs that scale with the screen: a fixed viewBox + width:100% + height:auto, so
// the figure always fits its column and stays crisp at any size.
const C = {
  green: '#4caf7d', red: '#e05252', amber: '#e0884f', blue: '#3a7bd6', blue2: '#7da7e0',
  grid: '#2a3140', text: '#9aa6b6', white: '#e8edf4', purple: '#b06bd6',
}
const svg = { width: '100%', height: 'auto', display: 'block' }

export function Figure({ caption, children, max = 760 }) {
  return (
    <figure style={{ margin: '20px 0' }}>
      <div style={{ width: '100%', maxWidth: max, background: 'var(--surface2,#11161f)',
                    border: '1px solid var(--border,#2a3140)', borderRadius: 8, padding: 12 }}>
        {children}
      </div>
      {caption && <figcaption style={{ fontSize: 12, color: 'var(--text)', marginTop: 6 }}>{caption}</figcaption>}
    </figure>
  )
}
Figure.propTypes = { caption: PropTypes.node, children: PropTypes.node, max: PropTypes.number }

// ── Monte-Carlo: profit-distribution histogram with E[Profit] / VaR5 / break-even ──
function HistogramFig() {
  const bars = [2, 4, 7, 11, 16, 22, 28, 33, 36, 35, 31, 26, 20, 15, 11, 8, 6, 4, 3, 2]
  const n = bars.length, maxH = Math.max(...bars)
  const W = 360, H = 200, padL = 24, padB = 30, padT = 18, padR = 10
  const bw = (W - padL - padR) / n, y0 = H - padB
  const xAt = i => padL + i * bw + bw / 2
  const markers = [[3, C.amber, 'VaR 5%'], [5, C.red, 'break-even'], [9, C.green, 'E[Profit]']]
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={svg} role="img" aria-label="Profit distribution histogram">
      <line x1={padL} y1={y0} x2={W - padR} y2={y0} stroke={C.grid} />
      {bars.map((b, i) => {
        const h = (b / maxH) * (H - padT - padB)
        return <rect key={i} x={padL + i * bw + 1} y={y0 - h} width={bw - 2} height={h} fill={C.blue} opacity={0.85} rx={1} />
      })}
      {markers.map(([i, col, lbl], k) => (
        <g key={k}>
          <line x1={xAt(i)} y1={padT} x2={xAt(i)} y2={y0} stroke={col} strokeWidth={1.5} strokeDasharray="4 3" />
          <text x={xAt(i)} y={padT - 4} fill={col} fontSize={8} textAnchor="middle">{lbl}</text>
        </g>
      ))}
      <text x={W / 2} y={H - 8} fill={C.text} fontSize={9} textAnchor="middle">Net profit (ISK) →</text>
    </svg>
  )
}

// ── Monte-Carlo: the estimate converging, with a shrinking 95% CI band ──
function ConvergenceFig() {
  const W = 360, H = 180, padL = 30, padB = 26, padT = 14, padR = 12
  const xs = Array.from({ length: 40 }, (_, i) => i)
  const level = 0.55
  const val = i => level + (Math.sin(i * 0.9) + Math.cos(i * 0.37)) * 0.16 * Math.exp(-i / 13)
  const band = i => 0.26 * Math.exp(-i / 11) + 0.015
  const x = i => padL + (i / (xs.length - 1)) * (W - padL - padR)
  const y = v => padT + (1 - v) * (H - padT - padB)
  const line = xs.map(i => `${x(i)},${y(val(i))}`).join(' ')
  const top = xs.map(i => `${x(i)},${y(val(i) + band(i))}`)
  const bot = xs.map(i => `${x(i)},${y(val(i) - band(i))}`).reverse()
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={svg} role="img" aria-label="Monte-Carlo convergence">
      <line x1={padL} y1={y(level)} x2={W - padR} y2={y(level)} stroke={C.grid} strokeDasharray="3 3" />
      <polygon points={[...top, ...bot].join(' ')} fill={C.green} opacity={0.14} />
      <polyline points={line} fill="none" stroke={C.green} strokeWidth={1.7} />
      <text x={W - padR} y={y(level) - 4} fill={C.text} fontSize={8} textAnchor="end">true E[Profit]</text>
      <text x={padL} y={padT - 4} fill={C.text} fontSize={8}>95% CI band</text>
      <text x={W / 2} y={H - 7} fill={C.text} fontSize={9} textAnchor="middle">iterations →</text>
    </svg>
  )
}

// ── Monte-Carlo: Gaussian vs Student-t copula (tail dependence) ──
function CopulaFig() {
  const W = 360, H = 190, padT = 22, padB = 18
  const core = [[0, 0], [1, 0.6], [-0.5, -0.3], [0.7, 0.9], [-1, -0.8], [0.3, 0.1], [-0.7, -0.5],
    [1.2, 0.8], [0.1, -0.4], [-0.3, 0.2], [0.9, 0.5], [-1.1, -0.6], [0.5, 0.7], [-0.2, -0.1]]
  const tails = [[2.2, 2.0], [2.5, 2.4], [-2.3, -2.1], [-2.6, -2.5], [2.1, 2.6], [-2.0, -2.4]]
  const panel = (ox, label, extra) => {
    const pw = 150, ph = H - padT - padB, cx = ox + pw / 2, cy = padT + ph / 2
    const sx = v => cx + v * 26, sy = v => cy - v * 26
    return (
      <g>
        <rect x={ox} y={padT} width={pw} height={ph} fill="none" stroke={C.grid} rx={4} />
        <line x1={ox} y1={cy} x2={ox + pw} y2={cy} stroke={C.grid} opacity={0.5} />
        <line x1={cx} y1={padT} x2={cx} y2={padT + ph} stroke={C.grid} opacity={0.5} />
        {core.map(([a, b], i) => <circle key={i} cx={sx(a)} cy={sy(b)} r={2} fill={C.blue2} opacity={0.8} />)}
        {extra && tails.map(([a, b], i) => <circle key={i} cx={sx(a)} cy={sy(b)} r={2.4} fill={C.red} />)}
        <text x={cx} y={padT - 6} fill={C.text} fontSize={9} textAnchor="middle">{label}</text>
      </g>
    )
  }
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={svg} role="img" aria-label="Gaussian vs Student-t copula">
      {panel(14, 'Gaussian copula', false)}
      {panel(196, 'Student-t copula', true)}
      <text x={W / 2} y={H - 3} fill={C.red} fontSize={8} textAnchor="middle">red = joint tail moves (crashes & spikes together)</text>
    </svg>
  )
}

// ── Scenarios: baseline vs scenario E[Profit] bars (colour by direction) ──
function ScenarioBarsFig() {
  const data = [['Baseline', 100, C.blue2], ['Tax −50%', 118, C.green], ['Jita +20%', 132, C.green],
    ['Hauling ×2', 86, C.red], ['Resource short.', 74, C.red], ['Recession', 58, C.red]]
  const W = 360, H = 200, padL = 8, padB = 40, padT = 16, padR = 8
  const n = data.length, maxV = 140
  const bw = (W - padL - padR) / n, y0 = H - padB
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={svg} role="img" aria-label="Baseline vs scenarios">
      <line x1={padL} y1={y0} x2={W - padR} y2={y0} stroke={C.grid} />
      {data.map(([lbl, v, col], i) => {
        const h = (v / maxV) * (H - padT - padB)
        const x = padL + i * bw
        return (
          <g key={i}>
            <rect x={x + 6} y={y0 - h} width={bw - 12} height={h} fill={col} opacity={0.9} rx={2} />
            <text x={x + bw / 2} y={y0 - h - 4} fill={C.white} fontSize={8} textAnchor="middle">{v}</text>
            <text x={x + bw / 2} y={y0 + 12} fill={C.text} fontSize={7.5} textAnchor="middle">{lbl}</text>
          </g>
        )
      })}
      <text x={padL} y={padT - 4} fill={C.text} fontSize={8}>E[Profit], baseline = 100</text>
    </svg>
  )
}

// ── Scenarios: sensitivity tornado (sorted by |Δ profit|) ──
function TornadoFig() {
  const data = [['Jita +20%', 32], ['Tax −50%', 18], ['Hauling ×2', -14], ['Volatility ×1.5', -8],
    ['Resource short.', -26], ['Recession', -42]].sort((a, b) => Math.abs(a[1]) - Math.abs(b[1]))
  const W = 360, H = 190, padL = 96, padR = 16, padT = 10, padB = 22
  const rows = data.length, rh = (H - padT - padB) / rows
  const cx = padL + (W - padL - padR) * 0.5, scale = (W - padL - padR) * 0.5 / 50
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={svg} role="img" aria-label="Sensitivity tornado">
      <line x1={cx} y1={padT} x2={cx} y2={H - padB} stroke={C.grid} />
      {data.map(([lbl, v], i) => {
        const y = padT + i * rh + rh / 2, w = v * scale
        return (
          <g key={i}>
            <rect x={v >= 0 ? cx : cx + w} y={y - rh * 0.32} width={Math.abs(w)} height={rh * 0.64}
                  fill={v >= 0 ? C.green : C.red} opacity={0.9} rx={2} />
            <text x={padL - 6} y={y + 3} fill={C.text} fontSize={8} textAnchor="end">{lbl}</text>
            <text x={v >= 0 ? cx + w + 3 : cx + w - 3} y={y + 3} fill={C.white} fontSize={8}
                  textAnchor={v >= 0 ? 'start' : 'end'}>{v > 0 ? `+${v}` : v}%</text>
          </g>
        )
      })}
      <text x={cx} y={H - 6} fill={C.text} fontSize={9} textAnchor="middle">Δ profit vs baseline (%)</text>
    </svg>
  )
}

// ── Scenarios: a scenario shifts & widens the profit distribution ──
function ScenarioShiftFig() {
  const W = 360, H = 180, padL = 20, padB = 26, padT = 14, padR = 12
  const x = t => padL + t * (W - padL - padR)
  const y0 = H - padB
  const bell = (mu, sd, amp) => Array.from({ length: 60 }, (_, i) => {
    const t = i / 59, z = (t - mu) / sd
    return `${x(t)},${y0 - amp * Math.exp(-0.5 * z * z)}`
  }).join(' ')
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={svg} role="img" aria-label="Scenario shifts the distribution">
      <line x1={padL} y1={y0} x2={W - padR} y2={y0} stroke={C.grid} />
      <polyline points={bell(0.58, 0.13, H - padT - padB)} fill="none" stroke={C.blue2} strokeWidth={1.8} />
      <polyline points={bell(0.40, 0.18, (H - padT - padB) * 0.8)} fill="none" stroke={C.red} strokeWidth={1.8} strokeDasharray="5 3" />
      <text x={x(0.58)} y={padT} fill={C.blue2} fontSize={8} textAnchor="middle">baseline</text>
      <text x={x(0.40)} y={y0 - (H - padT - padB) * 0.8 - 4} fill={C.red} fontSize={8} textAnchor="middle">stress scenario</text>
      <text x={W / 2} y={H - 7} fill={C.text} fontSize={9} textAnchor="middle">Net profit (ISK) →</text>
    </svg>
  )
}

// registry used by the Markdown [[fig:KEY]] marker
// eslint-disable-next-line react-refresh/only-export-components
export const FIGURES = {
  histogram: HistogramFig,
  convergence: ConvergenceFig,
  copula: CopulaFig,
  scenarioBars: ScenarioBarsFig,
  tornado: TornadoFig,
  scenarioShift: ScenarioShiftFig,
}
