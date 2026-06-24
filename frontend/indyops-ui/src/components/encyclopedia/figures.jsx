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

// ── Monte-Carlo: simulated Geometric-Brownian-Motion price paths fanning out ──
function GbmPathsFig() {
  const W = 360, H = 190, padL = 30, padB = 24, padT = 14, padR = 14
  const steps = 40, start = 0.42, drift = 0.20
  const x = i => padL + (i / (steps - 1)) * (W - padL - padR)
  const y = v => padT + (1 - v) * (H - padT - padB)
  // deterministic pseudo-noise per path (no RNG → stable render), variance grows like √t
  const phases = [[0.7, 1.3, 0.5], [1.9, 0.6, 1.1], [2.7, 1.7, 0.9], [0.3, 2.2, 1.4], [1.2, 0.9, 2.0]]
  const cols = [C.blue2, C.green, C.amber, C.purple, C.red]
  const path = ([a, b, c], k) => {
    const pts = []
    for (let i = 0; i < steps; i++) {
      const t = i / (steps - 1)
      const noise = (Math.sin(i * 0.5 + a) * 0.6 + Math.sin(i * 0.17 + b) * 0.4 + Math.cos(i * 0.31 + c) * 0.3)
        * 0.07 * Math.sqrt(t + 0.04)
      const v = Math.max(0.04, Math.min(0.97, start + drift * t + noise + (k - 2) * 0.014 * t))
      pts.push(`${x(i)},${y(v)}`)
    }
    return pts.join(' ')
  }
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={svg} role="img" aria-label="Simulated GBM price paths">
      <line x1={padL} y1={H - padB} x2={W - padR} y2={H - padB} stroke={C.grid} />
      <line x1={padL} y1={padT} x2={padL} y2={H - padB} stroke={C.grid} />
      <line x1={x(0)} y1={y(start)} x2={x(steps - 1)} y2={y(start + drift)} stroke={C.text}
            strokeWidth={1.2} strokeDasharray="5 3" opacity={0.7} />
      {phases.map((p, k) => <polyline key={k} points={path(p, k)} fill="none" stroke={cols[k]} strokeWidth={1.4} opacity={0.9} />)}
      <text x={x(steps - 1)} y={y(start + drift) - 4} fill={C.text} fontSize={8} textAnchor="end">drift (μ − ½σ²)</text>
      <text x={padL + 2} y={padT + 2} fill={C.text} fontSize={8}>price Sₜ</text>
      <text x={W / 2} y={H - 6} fill={C.text} fontSize={9} textAnchor="middle">time →</text>
    </svg>
  )
}

// ── Scenarios: a multi-stage scenario tree (branches with probabilities) ──
function ScenarioTreeFig() {
  const W = 360, H = 200, x0 = 26, x1 = 150, x2 = 290
  const root = { x: x0, y: H / 2 }
  const mids = [{ x: x1, y: 46, p: '0.3' }, { x: x1, y: 100, p: '0.5' }, { x: x1, y: 154, p: '0.2' }]
  const leaves = [
    [{ x: x2, y: 26 }, { x: x2, y: 66 }],
    [{ x: x2, y: 84 }, { x: x2, y: 116 }],
    [{ x: x2, y: 138 }, { x: x2, y: 178 }],
  ]
  const dot = (n, k, col) => <circle key={k} cx={n.x} cy={n.y} r={4} fill={col} />
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={svg} role="img" aria-label="Scenario tree">
      {mids.map((m, i) => (
        <g key={i}>
          <line x1={root.x} y1={root.y} x2={m.x} y2={m.y} stroke={C.grid} />
          <text x={(root.x + m.x) / 2} y={(root.y + m.y) / 2 - 3} fill={C.text} fontSize={8} textAnchor="middle">p={m.p}</text>
          {leaves[i].map((lf, j) => (
            <g key={j}>
              <line x1={m.x} y1={m.y} x2={lf.x} y2={lf.y} stroke={C.grid} />
              <text x={lf.x + 7} y={lf.y + 3} fill={C.text} fontSize={8}>Y</text>
            </g>
          ))}
        </g>
      ))}
      {dot(root, 'r', C.white)}
      {mids.map((m, i) => dot(m, `m${i}`, C.blue2))}
      {leaves.flat().map((lf, i) => dot(lf, `l${i}`, C.green))}
      <text x={x0} y={H - 4} fill={C.text} fontSize={8} textAnchor="middle">t=0</text>
      <text x={x1} y={H - 4} fill={C.text} fontSize={8} textAnchor="middle">t=1</text>
      <text x={x2} y={H - 4} fill={C.text} fontSize={8} textAnchor="middle">t=2</text>
    </svg>
  )
}

// ── Markowitz: the efficient frontier (σ vs return) with assets + chosen point ──
function EfficientFrontierFig() {
  const W = 360, H = 210, padL = 38, padB = 30, padT = 16, padR = 14
  const x0 = padL, x1 = W - padR, yb = H - padB, yt = padT
  const sx = s => x0 + (s / 0.9) * (x1 - x0)          // risk σ axis 0..0.9
  const ry = r => yb - r * (yb - yt)                  // return axis 0..1
  // minimum-variance frontier as a sideways parabola; t<0 is the inefficient lower branch
  const sMin = 0.12, curv = 0.52, rMid = 0.5, spread = 0.42
  const pt = t => [sx(sMin + curv * t * t), ry(rMid + spread * t)]
  const ts = Array.from({ length: 41 }, (_, i) => -1 + i * 0.05)
  const eff = ts.filter(t => t >= 0).map(t => pt(t).join(',')).join(' ')
  const ineff = ts.filter(t => t <= 0).map(t => pt(t).join(',')).join(' ')
  const [mvx, mvy] = pt(0)
  // individual assets sit inside/right of the frontier (more risk for the same return)
  const assets = [[0.34, 0.40], [0.48, 0.63], [0.58, 0.33], [0.32, 0.55], [0.66, 0.72], [0.44, 0.26], [0.54, 0.5]]
  const [cx, cy] = [sx(0.30), ry(0.46)]
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={svg} role="img" aria-label="Efficient frontier">
      <line x1={x0} y1={yt} x2={x0} y2={yb} stroke={C.grid} />
      <line x1={x0} y1={yb} x2={x1} y2={yb} stroke={C.grid} />
      <polyline points={ineff} fill="none" stroke={C.text} strokeWidth={1.3} strokeDasharray="4 3" opacity={0.6} />
      <polyline points={eff} fill="none" stroke={C.green} strokeWidth={2} />
      {assets.map(([s, r], i) => <circle key={i} cx={sx(s)} cy={ry(r)} r={2.6} fill={C.blue2} opacity={0.85} />)}
      <circle cx={mvx} cy={mvy} r={3.5} fill={C.white} stroke={C.green} strokeWidth={1.4} />
      <text x={mvx + 6} y={mvy + 3} fill={C.text} fontSize={8}>min-variance</text>
      <circle cx={cx} cy={cy} r={4} fill={C.amber} stroke={C.white} strokeWidth={1.2} />
      <text x={cx + 7} y={cy + 3} fill={C.amber} fontSize={8}>liquidity-capped</text>
      <text x={x1} y={yt + 4} fill={C.green} fontSize={8} textAnchor="end">efficient frontier</text>
      <text x={W / 2} y={H - 7} fill={C.text} fontSize={9} textAnchor="middle">risk σ →</text>
      <text x={x0 + 2} y={yt - 4} fill={C.text} fontSize={8}>expected return ↑</text>
    </svg>
  )
}

// ── Markowitz: diversification — portfolio σ falls toward a systematic-risk floor ──
function DiversificationFig() {
  const W = 360, H = 180, padL = 34, padB = 28, padT = 14, padR = 14
  const x0 = padL, x1 = W - padR, yb = H - padB, yt = padT
  const Nmax = 30, floor = 0.34, s1 = 1.0
  const sig = n => floor + (s1 - floor) / Math.sqrt(n)
  const x = n => x0 + ((n - 1) / (Nmax - 1)) * (x1 - x0)
  const y = v => yb - v * (yb - yt)
  const line = Array.from({ length: Nmax }, (_, i) => `${x(i + 1)},${y(sig(i + 1))}`).join(' ')
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={svg} role="img" aria-label="Diversification">
      <line x1={x0} y1={yt} x2={x0} y2={yb} stroke={C.grid} />
      <line x1={x0} y1={yb} x2={x1} y2={yb} stroke={C.grid} />
      <line x1={x0} y1={y(floor)} x2={x1} y2={y(floor)} stroke={C.amber} strokeWidth={1.2} strokeDasharray="5 3" />
      <text x={x1} y={y(floor) - 4} fill={C.amber} fontSize={8} textAnchor="end">systematic risk floor</text>
      <polyline points={line} fill="none" stroke={C.green} strokeWidth={2} />
      <text x={x(2)} y={y(sig(2)) - 6} fill={C.text} fontSize={8}>σ ≈ σ̄/√N</text>
      <text x={W / 2} y={H - 6} fill={C.text} fontSize={9} textAnchor="middle">number of assets N →</text>
      <text x={x0 + 2} y={yt - 3} fill={C.text} fontSize={8}>portfolio σ</text>
    </svg>
  )
}

// ── Markowitz: water-filling — weight ∝ (μᵢ − ν) above the cutoff ν (zeros below) ──
function WaterfillFig() {
  const W = 360, H = 195, padL = 22, padB = 32, padT = 18, padR = 12
  const mu = [0.92, 0.74, 0.62, 0.52, 0.43, 0.30, 0.18]
  const nu = 0.4
  const n = mu.length, x0 = padL, x1 = W - padR, yb = H - padB, yt = padT
  const bw = (x1 - x0) / n
  const y = v => yb - v * (yb - yt)
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={svg} role="img" aria-label="Water-filling allocation">
      <line x1={x0} y1={yb} x2={x1} y2={yb} stroke={C.grid} />
      {mu.map((m, i) => {
        const x = x0 + i * bw + 3, w = bw - 6
        const above = m > nu
        return (
          <g key={i}>
            <rect x={x} y={y(m)} width={w} height={yb - y(m)} fill="none" stroke={C.grid} rx={1} />
            {above && <rect x={x} y={y(m)} width={w} height={y(nu) - y(m)} fill={C.green} opacity={0.85} rx={1} />}
            <text x={x + w / 2} y={yb + 11} fill={C.text} fontSize={7.5} textAnchor="middle">{above ? `w${i + 1}` : '0'}</text>
          </g>
        )
      })}
      <line x1={x0} y1={y(nu)} x2={x1} y2={y(nu)} stroke={C.blue2} strokeWidth={1.4} strokeDasharray="5 3" />
      <text x={x1} y={y(nu) - 4} fill={C.blue2} fontSize={8} textAnchor="end">ν (cutoff)</text>
      <text x={x0} y={yt - 4} fill={C.text} fontSize={8}>μᵢ (expected return)</text>
      <text x={W / 2} y={H - 6} fill={C.text} fontSize={9} textAnchor="middle">weight ∝ (μᵢ − ν)/σᵢ² above the line</text>
    </svg>
  )
}

// ── Demand: the order book — asks above, bids (standing demand) below, spread gap ──
function OrderBookFig() {
  const W = 360, H = 210, cx = 150, padT = 16, rowH = 15
  const asks = [[0.30, 1245], [0.55, 980], [0.80, 1520], [1.00, 2100]]   // price-offset, size (top→spread)
  const bids = [[0.30, 1880], [0.55, 1360], [0.80, 900], [1.00, 1450]]   // price-offset, size (spread→down)
  const maxS = 2100, barMax = 120
  const yT = padT, ySpread = padT + 4 * rowH + 8
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={svg} role="img" aria-label="Order book">
      <line x1={cx} y1={yT} x2={cx} y2={H - 14} stroke={C.grid} />
      {asks.map(([, s], i) => {
        const y = yT + (3 - i) * rowH, w = (s / maxS) * barMax
        return <g key={`a${i}`}>
          <rect x={cx} y={y} width={w} height={rowH - 3} fill={C.red} opacity={0.8} rx={1} />
          <text x={cx + w + 4} y={y + 9} fill={C.text} fontSize={7.5}>{s}</text>
        </g>
      })}
      <rect x={20} y={ySpread - rowH} width={W - 40} height={rowH - 4} fill="rgba(58,123,214,0.10)" rx={2} />
      <text x={cx - 5} y={ySpread - 6} fill={C.blue2} fontSize={8} textAnchor="end">bid-ask spread</text>
      <text x={cx + 5} y={ySpread - 6} fill={C.blue2} fontSize={8}>← mid-price</text>
      {bids.map(([, s], i) => {
        const y = ySpread + i * rowH, w = (s / maxS) * barMax
        return <g key={`b${i}`}>
          <rect x={cx - w} y={y} width={w} height={rowH - 3} fill={C.green} opacity={0.8} rx={1} />
          <text x={cx - w - 4} y={y + 9} fill={C.text} fontSize={7.5} textAnchor="end">{s}</text>
        </g>
      })}
      <text x={cx - 60} y={yT + 9} fill={C.red} fontSize={8} textAnchor="middle">SELL orders = supply</text>
      <text x={cx + 60} y={H - 16} fill={C.green} fontSize={8} textAnchor="middle">BUY orders = standing demand</text>
      <text x={W / 2} y={H - 3} fill={C.text} fontSize={8} textAnchor="middle">units at each price level →</text>
    </svg>
  )
}

// ── Demand: supply & demand curves crossing at the market-clearing price ──
function SupplyDemandFig() {
  const W = 360, H = 200, padL = 36, padB = 28, padT = 14, padR = 16
  const x0 = padL, x1 = W - padR, yb = H - padB, yt = padT
  const X = q => x0 + q * (x1 - x0), Y = p => yb - p * (yb - yt)
  const demand = [[0.05, 0.92], [0.95, 0.12]]   // downward
  const supply = [[0.05, 0.15], [0.95, 0.88]]   // upward
  const [ex, ey] = [X(0.5), Y(0.52)]
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={svg} role="img" aria-label="Supply and demand">
      <line x1={x0} y1={yt} x2={x0} y2={yb} stroke={C.grid} />
      <line x1={x0} y1={yb} x2={x1} y2={yb} stroke={C.grid} />
      <line x1={X(demand[0][0])} y1={Y(demand[0][1])} x2={X(demand[1][0])} y2={Y(demand[1][1])} stroke={C.green} strokeWidth={2} />
      <line x1={X(supply[0][0])} y1={Y(supply[0][1])} x2={X(supply[1][0])} y2={Y(supply[1][1])} stroke={C.red} strokeWidth={2} />
      <line x1={ex} y1={yb} x2={ex} y2={ey} stroke={C.text} strokeDasharray="3 3" opacity={0.6} />
      <line x1={x0} y1={ey} x2={ex} y2={ey} stroke={C.text} strokeDasharray="3 3" opacity={0.6} />
      <circle cx={ex} cy={ey} r={4} fill={C.white} />
      <text x={X(0.85)} y={Y(0.18)} fill={C.green} fontSize={8}>Demand</text>
      <text x={X(0.82)} y={Y(0.92)} fill={C.red} fontSize={8}>Supply</text>
      <text x={ex + 6} y={ey - 4} fill={C.white} fontSize={8}>equilibrium</text>
      <text x={W / 2} y={H - 6} fill={C.text} fontSize={9} textAnchor="middle">quantity →</text>
      <text x={x0 + 2} y={yt - 3} fill={C.text} fontSize={8}>price ↑</text>
    </svg>
  )
}

// ── Demand: price elasticity — inelastic (steep) vs elastic (flat) demand ──
function ElasticityFig() {
  const W = 360, H = 180, padL = 34, padB = 26, padT = 14, padR = 14
  const x0 = padL, x1 = W - padR, yb = H - padB, yt = padT
  const X = q => x0 + q * (x1 - x0), Y = p => yb - p * (yb - yt)
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={svg} role="img" aria-label="Demand elasticity">
      <line x1={x0} y1={yt} x2={x0} y2={yb} stroke={C.grid} />
      <line x1={x0} y1={yb} x2={x1} y2={yb} stroke={C.grid} />
      <line x1={X(0.30)} y1={Y(0.95)} x2={X(0.46)} y2={Y(0.08)} stroke={C.amber} strokeWidth={2} />
      <line x1={X(0.10)} y1={Y(0.78)} x2={X(0.95)} y2={Y(0.30)} stroke={C.blue2} strokeWidth={2} />
      <text x={X(0.50)} y={Y(0.12)} fill={C.amber} fontSize={8}>inelastic (necessities)</text>
      <text x={X(0.70)} y={Y(0.46)} fill={C.blue2} fontSize={8}>elastic (luxuries)</text>
      <text x={W / 2} y={H - 6} fill={C.text} fontSize={9} textAnchor="middle">quantity demanded →</text>
      <text x={x0 + 2} y={yt - 3} fill={C.text} fontSize={8}>price ↑</text>
    </svg>
  )
}

// ── Demand metrics: daily volume bars + 7d MA + rising OLS trend line ──
function AdvTrendFig() {
  const W = 360, H = 180, padL = 28, padB = 26, padT = 14, padR = 12
  const n = 28, x0 = padL, x1 = W - padR, yb = H - padB, yt = padT
  const bw = (x1 - x0) / n
  const vol = i => 0.4 + 0.012 * i + 0.18 * Math.sin(i / 7 * 2 * Math.PI) + 0.06 * Math.sin(i * 1.7)
  const Y = v => yb - Math.max(0, Math.min(1, v)) * (yb - yt)
  const ma = i => { let s = 0, c = 0; for (let k = Math.max(0, i - 6); k <= i; k++) { s += vol(k); c++ } return s / c }
  const maLine = Array.from({ length: n }, (_, i) => `${x0 + i * bw + bw / 2},${Y(ma(i))}`).join(' ')
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={svg} role="img" aria-label="Volume, moving average and trend">
      <line x1={x0} y1={yb} x2={x1} y2={yb} stroke={C.grid} />
      {Array.from({ length: n }, (_, i) => {
        const h = yb - Y(vol(i))
        return <rect key={i} x={x0 + i * bw + 1} y={Y(vol(i))} width={bw - 2} height={h} fill={C.blue} opacity={0.45} rx={1} />
      })}
      <line x1={x0 + bw / 2} y1={Y(0.45)} x2={x1 - bw / 2} y2={Y(0.78)} stroke={C.amber} strokeWidth={1.4} strokeDasharray="5 3" />
      <polyline points={maLine} fill="none" stroke={C.white} strokeWidth={1.7} />
      <text x={x0 + 4} y={yt + 2} fill={C.white} fontSize={8}>7-day MA</text>
      <text x={x1 - 4} y={Y(0.80)} fill={C.amber} fontSize={8} textAnchor="end">trend (OLS)</text>
      <text x={W / 2} y={H - 6} fill={C.text} fontSize={9} textAnchor="middle">daily traded volume →</text>
    </svg>
  )
}

// ── Demand metrics: weekly seasonality — mean volume by weekday (weekend hot) ──
function WeekdaySeasonFig() {
  const W = 360, H = 170, padL = 26, padB = 28, padT = 16, padR = 12
  const days = [['Mon', 0.52], ['Tue', 0.50], ['Wed', 0.58], ['Thu', 0.62], ['Fri', 0.74], ['Sat', 0.92], ['Sun', 0.85]]
  const n = days.length, x0 = padL, x1 = W - padR, yb = H - padB, yt = padT
  const bw = (x1 - x0) / n
  const Y = v => yb - v * (yb - yt)
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={svg} role="img" aria-label="Volume by weekday">
      <line x1={x0} y1={yb} x2={x1} y2={yb} stroke={C.grid} />
      {days.map(([d, v], i) => {
        const x = x0 + i * bw, h = yb - Y(v), weekend = i >= 5
        return <g key={i}>
          <rect x={x + 4} y={Y(v)} width={bw - 8} height={h} fill={weekend ? C.green : C.blue} opacity={0.8} rx={2} />
          <text x={x + bw / 2} y={yb + 12} fill={weekend ? C.green : C.text} fontSize={8} textAnchor="middle">{d}</text>
        </g>
      })}
      <text x={x0} y={yt - 4} fill={C.text} fontSize={8}>mean volume</text>
      <text x={x1} y={yt - 4} fill={C.green} fontSize={8} textAnchor="end">weekend lift</text>
    </svg>
  )
}

// ── Demand metrics: the 0-100 demand score, broken into weighted components ──
function DemandScoreFig() {
  const W = 360, H = 175, padL = 96, padR = 50, padT = 18, padB = 18
  const comps = [['Liquidity (ISK/day)', 0.62, 0.5], ['Consistency (active days)', 0.88, 0.3], ['Trend (momentum)', 0.55, 0.2]]
  const x0 = padL, x1 = W - padR, rows = comps.length, rh = (H - padT - padB) / rows
  const score = Math.round(100 * comps.reduce((s, [, v, w]) => s + v * w, 0))
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={svg} role="img" aria-label="Demand score components">
      {comps.map(([lbl, v, w], i) => {
        const y = padT + i * rh + rh / 2
        return <g key={i}>
          <text x={x0 - 6} y={y + 3} fill={C.text} fontSize={8} textAnchor="end">{lbl}</text>
          <rect x={x0} y={y - 6} width={x1 - x0} height={12} fill={C.grid} opacity={0.4} rx={2} />
          <rect x={x0} y={y - 6} width={(x1 - x0) * v} height={12} fill={C.green} opacity={0.85} rx={2} />
          <text x={x1 + 6} y={y + 3} fill={C.text} fontSize={8}>×{w}</text>
        </g>
      })}
      <text x={(x0 + x1) / 2} y={padT - 5} fill={C.text} fontSize={8} textAnchor="middle">component score (0–1)</text>
      <text x={W - 4} y={H - 6} fill={C.amber} fontSize={11} textAnchor="end" fontWeight="bold">score {score}/100</text>
    </svg>
  )
}

// ── Forecasting: a series decomposed into trend + seasonality + residual ──
function DecompositionFig() {
  const W = 360, H = 210, padL = 16, padR = 12, gap = 8
  const panelH = (H - 2 * gap - 12) / 3, x0 = padL, x1 = W - padR
  const X = t => x0 + t * (x1 - x0), N = 50
  const panel = (oy, fn, col, lbl) => {
    const mid = oy + panelH / 2
    const pts = Array.from({ length: N }, (_, i) => `${X(i / (N - 1))},${mid - fn(i / (N - 1)) * panelH * 0.42}`).join(' ')
    return <g>
      <line x1={x0} y1={mid} x2={x1} y2={mid} stroke={C.grid} opacity={0.4} />
      <polyline points={pts} fill="none" stroke={col} strokeWidth={1.5} />
      <text x={x0 + 2} y={oy + 9} fill={C.text} fontSize={8}>{lbl}</text>
    </g>
  }
  const noise = t => Math.sin(t * 73) * 0.5 + Math.sin(t * 191) * 0.3
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={svg} role="img" aria-label="Time-series decomposition">
      {panel(2, t => -0.7 + 1.4 * t, C.amber, 'trend')}
      {panel(2 + panelH + gap, t => Math.sin(t * 6 * Math.PI), C.blue2, 'seasonality (weekly)')}
      {panel(2 + 2 * (panelH + gap), noise, C.text, 'residual (noise)')}
      <text x={W / 2} y={H - 1} fill={C.text} fontSize={8} textAnchor="middle">observed = trend + seasonality + residual</text>
    </svg>
  )
}

// ── Forecasting: fan chart — history, P50 forecast, widening P10–P90 band ──
function FanChartFig() {
  const W = 360, H = 190, padL = 16, padB = 24, padT = 14, padR = 12
  const x0 = padL, x1 = W - padR, yb = H - padB, yt = padT, split = 0.62
  const X = t => x0 + t * (x1 - x0), Y = v => yt + (1 - v) * (yb - yt)
  const hist = t => 0.5 + 0.10 * Math.sin(t * 9) + 0.06 * Math.sin(t * 23) + 0.12 * t
  const Nh = 32, hx = i => i / (Nh - 1) * split
  const histPts = Array.from({ length: Nh }, (_, i) => `${X(hx(i))},${Y(hist(hx(i)))}`).join(' ')
  const lastY = hist(split)
  const Nf = 22, fx = i => split + (i / (Nf - 1)) * (1 - split)
  const mid = i => lastY + 0.10 * (i / (Nf - 1))
  const band = i => 0.04 + 0.20 * (i / (Nf - 1))
  const p50 = Array.from({ length: Nf }, (_, i) => `${X(fx(i))},${Y(mid(i))}`).join(' ')
  const top = Array.from({ length: Nf }, (_, i) => `${X(fx(i))},${Y(mid(i) + band(i))}`)
  const bot = Array.from({ length: Nf }, (_, i) => `${X(fx(i))},${Y(mid(i) - band(i))}`).reverse()
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={svg} role="img" aria-label="Forecast fan chart">
      <line x1={x0} y1={yb} x2={x1} y2={yb} stroke={C.grid} />
      <polygon points={[...top, ...bot].join(' ')} fill={C.amber} opacity={0.16} />
      <polyline points={histPts} fill="none" stroke={C.white} strokeWidth={1.7} />
      <polyline points={p50} fill="none" stroke={C.amber} strokeWidth={1.6} strokeDasharray="5 3" />
      <line x1={X(split)} y1={yt} x2={X(split)} y2={yb} stroke={C.grid} strokeDasharray="2 3" />
      <text x={X(split) - 4} y={yt + 6} fill={C.white} fontSize={8} textAnchor="end">history</text>
      <text x={X(split) + 4} y={yt + 6} fill={C.amber} fontSize={8}>forecast (P10–P90)</text>
      <text x={W / 2} y={H - 6} fill={C.text} fontSize={9} textAnchor="middle">time →</text>
    </svg>
  )
}

// ── Forecasting: rolling-origin (walk-forward) backtest folds ──
function WalkForwardFig() {
  const W = 360, H = 175, padL = 56, padR = 16, padT = 14, padB = 22
  const folds = 4, x0 = padL, x1 = W - padR, rh = (H - padT - padB) / folds
  const totalLen = 0.98
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={svg} role="img" aria-label="Walk-forward backtest">
      {Array.from({ length: folds }, (_, k) => {
        const y = padT + k * rh + rh / 2, cut = totalLen - (folds - k) * 0.14
        const trainW = (x1 - x0) * cut, testW = (x1 - x0) * 0.14
        return <g key={k}>
          <rect x={x0} y={y - rh * 0.3} width={trainW} height={rh * 0.6} fill={C.blue} opacity={0.55} rx={2} />
          <rect x={x0 + trainW} y={y - rh * 0.3} width={testW} height={rh * 0.6} fill={C.amber} opacity={0.9} rx={2} />
          <text x={x0 - 6} y={y + 3} fill={C.text} fontSize={8} textAnchor="end">fold {k + 1}</text>
        </g>
      })}
      <text x={x0 + 30} y={padT - 3} fill={C.blue2} fontSize={8}>train</text>
      <text x={x1 - 18} y={padT - 3} fill={C.amber} fontSize={8}>test</text>
      <text x={W / 2} y={H - 5} fill={C.text} fontSize={9} textAnchor="middle">origin rolls forward → score each test window</text>
    </svg>
  )
}

// ── Forecasting: model panel ranked by MASE (chosen wins; MASE=1 = naive) ──
function ModelPanelFig() {
  const W = 360, H = 185, padL = 92, padR = 40, padT = 14, padB = 26
  const models = [['SARIMA', 0.74, true], ['Holt-Winters', 0.79, false], ['ARIMA', 0.90, false],
    ['Croston', 1.30, false], ['Seasonal-naive', 1.00, false]]
  const x0 = padL, x1 = W - padR, rows = models.length, rh = (H - padT - padB) / rows
  const scale = (x1 - x0) / 1.5
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={svg} role="img" aria-label="Model panel by MASE">
      <line x1={x0 + scale} y1={padT} x2={x0 + scale} y2={H - padB} stroke={C.red} strokeWidth={1.2} strokeDasharray="4 3" />
      <text x={x0 + scale} y={padT - 3} fill={C.red} fontSize={7.5} textAnchor="middle">MASE = 1 (naive)</text>
      {models.map(([m, v, best], i) => {
        const y = padT + i * rh + rh / 2, w = v * scale
        return <g key={i}>
          <text x={x0 - 6} y={y + 3} fill={best ? C.green : C.text} fontSize={8} textAnchor="end">{m}</text>
          <rect x={x0} y={y - 6} width={w} height={12} fill={best ? C.green : v < 1 ? C.blue : C.red} opacity={0.85} rx={2} />
          <text x={x0 + w + 5} y={y + 3} fill={C.text} fontSize={8}>{v.toFixed(2)}</text>
        </g>
      })}
      <text x={W / 2} y={H - 6} fill={C.text} fontSize={9} textAnchor="middle">MASE — lower is better (&lt; 1 beats naive)</text>
    </svg>
  )
}

// ── Liquidity: bid-ask spread + cumulative market depth on both sides ──
function SpreadDepthFig() {
  const W = 360, H = 195, padL = 20, padB = 26, padT = 14, padR = 14
  const x0 = padL, x1 = W - padR, yb = H - padB, yt = padT, cx = (x0 + x1) / 2
  const X = p => cx + p * (x1 - cx), Y = v => yb - v * (yb - yt)
  const bid = Array.from({ length: 12 }, (_, i) => [-0.08 - i * 0.07, (i + 1) / 12])
  const ask = Array.from({ length: 12 }, (_, i) => [0.08 + i * 0.07, (i + 1) / 12])
  const line = (arr, col) => {
    const pts = arr.map(([p, c]) => `${X(p)},${Y(c)}`)
    const base = `${X(arr[0][0])},${yb} ` + pts.join(' ') + ` ${X(arr[arr.length - 1][0])},${yb}`
    return <g><polygon points={base} fill={col} opacity={0.14} /><polyline points={pts.join(' ')} fill="none" stroke={col} strokeWidth={1.6} /></g>
  }
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={svg} role="img" aria-label="Spread and market depth">
      <line x1={x0} y1={yb} x2={x1} y2={yb} stroke={C.grid} />
      {line(bid, C.green)}
      {line(ask, C.red)}
      <rect x={X(-0.08)} y={yt} width={X(0.08) - X(-0.08)} height={yb - yt} fill="rgba(58,123,214,0.12)" />
      <text x={cx} y={yt + 8} fill={C.blue2} fontSize={8} textAnchor="middle">spread</text>
      <text x={X(-0.5)} y={yt + 4} fill={C.green} fontSize={8} textAnchor="middle">bid depth</text>
      <text x={X(0.5)} y={yt + 4} fill={C.red} fontSize={8} textAnchor="middle">ask depth</text>
      <text x={W / 2} y={H - 6} fill={C.text} fontSize={9} textAnchor="middle">price (cumulative volume ↑)</text>
    </svg>
  )
}

// ── Liquidity: market impact — execution price walks the book as size grows ──
function MarketImpactFig() {
  const W = 360, H = 180, padL = 34, padB = 28, padT = 16, padR = 14
  const x0 = padL, x1 = W - padR, yb = H - padB, yt = padT
  const X = q => x0 + q * (x1 - x0), Y = p => yb - p * (yb - yt)
  const impact = q => 0.18 + 0.62 * Math.sqrt(q)                 // square-root impact law
  const curve = Array.from({ length: 50 }, (_, i) => `${X(i / 49)},${Y(impact(i / 49))}`).join(' ')
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={svg} role="img" aria-label="Market impact">
      <line x1={x0} y1={yt} x2={x0} y2={yb} stroke={C.grid} />
      <line x1={x0} y1={yb} x2={x1} y2={yb} stroke={C.grid} />
      <line x1={x0} y1={Y(0.18)} x2={x1} y2={Y(0.18)} stroke={C.green} strokeDasharray="4 3" />
      <text x={x1} y={Y(0.18) - 4} fill={C.green} fontSize={8} textAnchor="end">best price (small order)</text>
      <polyline points={curve} fill="none" stroke={C.red} strokeWidth={2} />
      <text x={X(0.6)} y={Y(impact(0.6)) - 6} fill={C.red} fontSize={8}>slippage ∝ √size</text>
      <text x={W / 2} y={H - 6} fill={C.text} fontSize={9} textAnchor="middle">order size (share of depth) →</text>
      <text x={x0 + 2} y={yt - 3} fill={C.text} fontSize={8}>avg execution price ↑</text>
    </svg>
  )
}

// ── Liquidity: the liquidity × volatility quadrant ──
function LiqVsVolFig() {
  const W = 360, H = 200, padL = 36, padB = 30, padT = 14, padR = 14
  const x0 = padL, x1 = W - padR, yb = H - padB, yt = padT, mx = (x0 + x1) / 2, my = (yt + yb) / 2
  const items = [[0.78, 0.30, C.green], [0.66, 0.70, C.amber], [0.28, 0.34, C.amber], [0.20, 0.80, C.red],
    [0.85, 0.18, C.green], [0.40, 0.60, C.amber], [0.15, 0.55, C.red]]
  const X = v => x0 + v * (x1 - x0), Y = v => yb - v * (yb - yt)
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={svg} role="img" aria-label="Liquidity versus volatility">
      <rect x={x0} y={yt} width={x1 - x0} height={yb - yt} fill="none" stroke={C.grid} />
      <line x1={mx} y1={yt} x2={mx} y2={yb} stroke={C.grid} opacity={0.5} />
      <line x1={x0} y1={my} x2={x1} y2={my} stroke={C.grid} opacity={0.5} />
      {items.map(([l, v, col], i) => <circle key={i} cx={X(l)} cy={Y(v)} r={3.4} fill={col} opacity={0.9} />)}
      <text x={X(0.75)} y={Y(0.10)} fill={C.green} fontSize={7.5} textAnchor="middle">liquid · calm (safe)</text>
      <text x={X(0.22)} y={Y(0.92)} fill={C.red} fontSize={7.5} textAnchor="middle">illiquid · volatile (danger)</text>
      <text x={W / 2} y={H - 6} fill={C.text} fontSize={9} textAnchor="middle">liquidity →</text>
      <text x={x0 + 2} y={yt - 3} fill={C.text} fontSize={8}>volatility ↑</text>
    </svg>
  )
}

// ── Microstructure: price-time priority — better price first, then FIFO within a level ──
function PriceTimePriorityFig() {
  const W = 360, H = 200, padL = 82, padT = 18, rowH = 21, box = 15, gap = 5
  const qx = padL
  const rows = [
    { col: C.red, n: 3, lbl: '101.2', best: false },
    { col: C.red, n: 4, lbl: '101.0 best ask', best: true },
    { spread: true },
    { col: C.green, n: 4, lbl: '100.8 best bid', best: true },
    { col: C.green, n: 2, lbl: '100.6', best: false },
  ]
  let y = padT
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={svg} role="img" aria-label="Price-time priority">
      {rows.map((r, i) => {
        const yy = y; y += r.spread ? rowH - 4 : rowH
        if (r.spread) return <text key={i} x={qx} y={yy + 7} fill={C.blue2} fontSize={8}>← bid-ask spread</text>
        return (
          <g key={i}>
            <text x={padL - 6} y={yy + box - 3} fill={r.best ? C.white : C.text} fontSize={7.5} textAnchor="end">{r.lbl}</text>
            {Array.from({ length: r.n }, (_, k) =>
              <rect key={k} x={qx + k * (box + gap)} y={yy} width={box} height={box - 2} fill={r.col} opacity={k === 0 ? 0.95 : 0.45} rx={2} />)}
            {r.best && <polygon points={`${qx - 2},${yy + box / 2} ${qx - 9},${yy + box / 2 - 4} ${qx - 9},${yy + box / 2 + 4}`} fill={C.white} />}
          </g>
        )
      })}
      <text x={6} y={padT + 30} fill={C.text} fontSize={8} transform={`rotate(-90 10 ${padT + 30})`}>price priority ↑</text>
      <text x={qx} y={H - 6} fill={C.text} fontSize={8}>time priority (FIFO) → earlier orders fill first</text>
    </svg>
  )
}

// ── Microstructure: the bid-ask spread decomposed into its three cost components ──
function SpreadDecompFig() {
  const W = 360, H = 150, padL = 20, padR = 20, padT = 34, barH = 34
  const x0 = padL, x1 = W - padR
  const segs = [['Order-processing', 0.30, C.blue], ['Inventory-holding', 0.28, C.amber], ['Adverse-selection', 0.42, C.red]]
  let cx = x0
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={svg} role="img" aria-label="Bid-ask spread decomposition">
      <text x={W / 2} y={18} fill={C.text} fontSize={9} textAnchor="middle">the bid-ask spread = three costs the maker must recover</text>
      {segs.map(([lbl, frac, col], i) => {
        const w = (x1 - x0) * frac, x = cx; cx += w
        return (
          <g key={i}>
            <rect x={x} y={padT} width={w - 2} height={barH} fill={col} opacity={0.85} rx={2} />
            <text x={x + w / 2} y={padT + barH / 2 + 3} fill={C.white} fontSize={8} textAnchor="middle">{Math.round(frac * 100)}%</text>
            <text x={x + w / 2} y={padT + barH + 14} fill={C.text} fontSize={7.5} textAnchor="middle">{lbl}</text>
          </g>
        )
      })}
      <line x1={x0} y1={padT + barH + 24} x2={x1} y2={padT + barH + 24} stroke={C.grid} />
      <text x={x0} y={padT + barH + 34} fill={C.green} fontSize={8}>best bid</text>
      <text x={x1} y={padT + barH + 34} fill={C.red} fontSize={8} textAnchor="end">best ask</text>
    </svg>
  )
}

// ── Microstructure: order-book imbalance → microprice leans toward the heavier side ──
function MicropriceFig() {
  const W = 360, H = 175, padT = 18, axisY = 96, padL = 40, padR = 40
  const x0 = padL, x1 = W - padR, bid = x0, ask = x1, mid = (x0 + x1) / 2
  const qBid = 4.0, qAsk = 1.4                                  // deep bid, thin ask
  // microprice = (P_ask·Q_bid + P_bid·Q_ask)/(Q_bid+Q_ask) → leans toward ask
  const micro = (ask * qBid + bid * qAsk) / (qBid + qAsk)
  const bh = 40
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={svg} role="img" aria-label="Microprice and imbalance">
      <rect x={bid} y={axisY - bh * (qBid / 4)} width={26} height={bh * (qBid / 4)} fill={C.green} opacity={0.8} rx={2} />
      <rect x={ask - 26} y={axisY - bh * (qAsk / 4)} width={26} height={bh * (qAsk / 4)} fill={C.red} opacity={0.8} rx={2} />
      <line x1={x0} y1={axisY} x2={x1} y2={axisY} stroke={C.grid} />
      <line x1={mid} y1={axisY - 6} x2={mid} y2={axisY + 26} stroke={C.text} strokeDasharray="3 3" />
      <text x={mid} y={axisY + 38} fill={C.text} fontSize={8} textAnchor="middle">mid</text>
      <line x1={micro} y1={axisY - 6} x2={micro} y2={axisY + 26} stroke={C.amber} strokeWidth={1.6} />
      <text x={micro} y={axisY + 38} fill={C.amber} fontSize={8} textAnchor="middle">microprice</text>
      <text x={bid} y={axisY + 12} fill={C.green} fontSize={8}>best bid (deep)</text>
      <text x={ask} y={axisY + 12} fill={C.red} fontSize={8} textAnchor="end">best ask (thin)</text>
      <text x={W / 2} y={padT} fill={C.text} fontSize={9} textAnchor="middle">positive imbalance (more bids) → microprice leans up → price likely to rise</text>
      <polygon points={`${micro + 16},${axisY - 26} ${micro + 26},${axisY - 32} ${micro + 26},${axisY - 20}`} fill={C.amber} />
    </svg>
  )
}

// ── Microstructure (EVE): the 0.01 ISK undercut war grinding the best ask to a floor ──
function UndercutWarFig() {
  const W = 360, H = 170, padL = 30, padB = 26, padT = 26, padR = 14
  const x0 = padL, x1 = W - padR, yb = H - padB, yt = padT, floor = 0.30
  const Y = v => yb - v * (yb - yt)
  const N = 64, pts = []
  let price = 0.92
  for (let i = 0; i < N; i++) {
    if (i > 0) price = (i % 16 === 0) ? Math.min(0.92, price + 0.40) : Math.max(floor, price - 0.045)
    pts.push(`${x0 + (i / (N - 1)) * (x1 - x0)},${Y(price)}`)
  }
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={svg} role="img" aria-label="0.01 ISK undercut war">
      <line x1={x0} y1={yb} x2={x1} y2={yb} stroke={C.grid} />
      <line x1={x0} y1={Y(floor)} x2={x1} y2={Y(floor)} stroke={C.green} strokeDasharray="5 3" />
      <text x={x1} y={Y(floor) - 4} fill={C.green} fontSize={8} textAnchor="end">cost + fee floor</text>
      <polyline points={pts.join(' ')} fill="none" stroke={C.red} strokeWidth={1.6} />
      <text x={x0 + 70} y={Y(0.66)} fill={C.text} fontSize={7.5}>−0.01 undercut ↓</text>
      <text x={x0 + (15 / (N - 1)) * (x1 - x0)} y={Y(0.92) - 4} fill={C.amber} fontSize={7.5} textAnchor="middle">relist ↑</text>
      <text x={W / 2} y={padT - 12} fill={C.text} fontSize={9} textAnchor="middle">best ask ground down by repeated undercutting, reset by relists</text>
      <text x={W / 2} y={H - 5} fill={C.text} fontSize={8} textAnchor="middle">time →</text>
    </svg>
  )
}

// ═══════════════ Market Economics figures ═══════════════
// shared mini-axes helper for the economics panels
function axes(x0, yt, yb, x1) {
  return <g>
    <line x1={x0} y1={yt} x2={x0} y2={yb} stroke={C.grid} />
    <line x1={x0} y1={yb} x2={x1} y2={yb} stroke={C.grid} />
  </g>
}

// ── Supply: upward supply curve with producer surplus ──
function SupplyCurveFig() {
  const W = 360, H = 190, padL = 36, padB = 28, padT = 14, padR = 16
  const x0 = padL, x1 = W - padR, yb = H - padB, yt = padT
  const X = q => x0 + q * (x1 - x0), Y = p => yb - p * (yb - yt)
  const s0 = 0.12, s1 = 0.9, pStar = 0.6, qStar = (pStar - s0) / (s1 - s0)
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={svg} role="img" aria-label="Supply curve and producer surplus">
      {axes(x0, yt, yb, x1)}
      <polygon points={`${X(0)},${Y(s0)} ${X(qStar)},${Y(pStar)} ${X(0)},${Y(pStar)}`} fill={C.blue} opacity={0.18} />
      <line x1={X(0)} y1={Y(s0)} x2={X(0.95)} y2={Y(s1)} stroke={C.red} strokeWidth={2} />
      <line x1={X(0)} y1={Y(pStar)} x2={X(qStar)} y2={Y(pStar)} stroke={C.text} strokeDasharray="3 3" opacity={0.6} />
      <text x={X(0.8)} y={Y(s1) + 2} fill={C.red} fontSize={8}>Supply</text>
      <text x={X(0.06)} y={Y(pStar) - 16} fill={C.blue2} fontSize={8}>producer surplus</text>
      <text x={X(0)} y={Y(s0) + 10} fill={C.text} fontSize={7.5}>= marginal cost</text>
      <text x={W / 2} y={H - 6} fill={C.text} fontSize={9} textAnchor="middle">quantity →</text>
      <text x={x0 + 2} y={yt - 3} fill={C.text} fontSize={8}>price ↑</text>
    </svg>
  )
}

// ── Supply: a rightward shift (lower cost) vs a movement along the curve ──
function SupplyShiftFig() {
  const W = 360, H = 180, padL = 32, padB = 26, padT = 14, padR = 14
  const x0 = padL, x1 = W - padR, yb = H - padB, yt = padT
  const X = q => x0 + q * (x1 - x0), Y = p => yb - p * (yb - yt)
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={svg} role="img" aria-label="Supply shift">
      {axes(x0, yt, yb, x1)}
      <line x1={X(0.05)} y1={Y(0.12)} x2={X(0.85)} y2={Y(0.92)} stroke={C.red} strokeWidth={2} />
      <line x1={X(0.30)} y1={Y(0.12)} x2={X(0.98)} y2={Y(0.78)} stroke={C.green} strokeWidth={2} strokeDasharray="5 3" />
      <text x={X(0.7)} y={Y(0.92)} fill={C.red} fontSize={8}>S₀</text>
      <text x={X(0.95)} y={Y(0.78)} fill={C.green} fontSize={8}>S₁ (cost ↓)</text>
      <text x={X(0.5)} y={Y(0.95)} fill={C.text} fontSize={8} textAnchor="middle">shift right = more supplied at every price</text>
      <text x={W / 2} y={H - 6} fill={C.text} fontSize={9} textAnchor="middle">quantity →</text>
      <text x={x0 + 2} y={yt - 3} fill={C.text} fontSize={8}>price ↑</text>
    </svg>
  )
}

// ── Equilibrium: a demand shift moves the clearing point ──
function EquilibriumShiftFig() {
  const W = 360, H = 195, padL = 34, padB = 28, padT = 14, padR = 16
  const x0 = padL, x1 = W - padR, yb = H - padB, yt = padT
  const X = q => x0 + q * (x1 - x0), Y = p => yb - p * (yb - yt)
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={svg} role="img" aria-label="Equilibrium shift">
      {axes(x0, yt, yb, x1)}
      <line x1={X(0.05)} y1={Y(0.15)} x2={X(0.95)} y2={Y(0.9)} stroke={C.red} strokeWidth={2} />
      <line x1={X(0.05)} y1={Y(0.88)} x2={X(0.78)} y2={Y(0.12)} stroke={C.green} strokeWidth={2} />
      <line x1={X(0.32)} y1={Y(0.95)} x2={X(0.98)} y2={Y(0.28)} stroke={C.green} strokeWidth={1.8} strokeDasharray="5 3" />
      <circle cx={X(0.45)} cy={Y(0.5)} r={3.5} fill={C.white} />
      <circle cx={X(0.62)} cy={Y(0.66)} r={3.5} fill={C.amber} />
      <text x={X(0.62) + 6} y={Y(0.66)} fill={C.amber} fontSize={8}>new eq. (↑P, ↑Q)</text>
      <text x={X(0.8)} y={Y(0.12)} fill={C.green} fontSize={8}>D₀</text>
      <text x={X(0.98)} y={Y(0.28)} fill={C.green} fontSize={8}>D₁</text>
      <text x={X(0.9)} y={Y(0.9)} fill={C.red} fontSize={8}>S</text>
      <text x={W / 2} y={H - 6} fill={C.text} fontSize={9} textAnchor="middle">quantity →</text>
      <text x={x0 + 2} y={yt - 3} fill={C.text} fontSize={8}>price ↑</text>
    </svg>
  )
}

// ── Equilibrium: surplus (price above clearing) vs shortage (below) ──
function SurplusShortageFig() {
  const W = 360, H = 185, padL = 34, padB = 26, padT = 16, padR = 14
  const x0 = padL, x1 = W - padR, yb = H - padB, yt = padT
  const X = q => x0 + q * (x1 - x0), Y = p => yb - p * (yb - yt)
  const D = p => (0.9 - p) / 0.78 * 0.83 + 0.05, S = p => (p - 0.15) / 0.75 * 0.9 + 0.05
  const pHigh = 0.72
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={svg} role="img" aria-label="Surplus and shortage">
      {axes(x0, yt, yb, x1)}
      <line x1={X(0.05)} y1={Y(0.15)} x2={X(0.95)} y2={Y(0.9)} stroke={C.red} strokeWidth={1.8} />
      <line x1={X(0.05)} y1={Y(0.88)} x2={X(0.78)} y2={Y(0.12)} stroke={C.green} strokeWidth={1.8} />
      <line x1={x0} y1={Y(pHigh)} x2={x1} y2={Y(pHigh)} stroke={C.amber} strokeWidth={1.4} strokeDasharray="4 3" />
      <line x1={X(D(pHigh))} y1={Y(pHigh)} x2={X(S(pHigh))} y2={Y(pHigh)} stroke={C.white} strokeWidth={2.5} opacity={0.8} />
      <text x={X(0.5)} y={Y(pHigh) - 5} fill={C.amber} fontSize={8} textAnchor="middle">price above clearing → glut (surplus)</text>
      <text x={W / 2} y={H - 6} fill={C.text} fontSize={9} textAnchor="middle">quantity →</text>
      <text x={x0 + 2} y={yt - 3} fill={C.text} fontSize={8}>price ↑</text>
    </svg>
  )
}

// ── Elasticity: the total-revenue test (revenue rises then falls along demand) ──
function ElasticityRevenueFig() {
  const W = 360, H = 185, padL = 30, padB = 28, padT = 14, padR = 14
  const x0 = padL, x1 = W - padR, yb = H - padB, yt = padT
  const X = t => x0 + t * (x1 - x0), Y = v => yb - v * (yb - yt)
  const rev = q => 4 * q * (1 - q)                  // P×Q, inverted parabola, peak at q=0.5
  const pts = Array.from({ length: 50 }, (_, i) => `${X(i / 49)},${Y(rev(i / 49) * 0.95)}`).join(' ')
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={svg} role="img" aria-label="Total revenue test">
      {axes(x0, yt, yb, x1)}
      <polyline points={pts} fill="none" stroke={C.blue2} strokeWidth={2} />
      <line x1={X(0.5)} y1={yt} x2={X(0.5)} y2={yb} stroke={C.grid} strokeDasharray="3 3" />
      <text x={X(0.25)} y={Y(0.55)} fill={C.green} fontSize={8} textAnchor="middle">elastic: cut P → rev ↑</text>
      <text x={X(0.75)} y={Y(0.55)} fill={C.red} fontSize={8} textAnchor="middle">inelastic: cut P → rev ↓</text>
      <text x={X(0.5)} y={Y(0.98)} fill={C.text} fontSize={8} textAnchor="middle">|E| = 1</text>
      <text x={W / 2} y={H - 6} fill={C.text} fontSize={9} textAnchor="middle">quantity sold →</text>
      <text x={x0 + 2} y={yt - 3} fill={C.text} fontSize={8}>total revenue ↑</text>
    </svg>
  )
}

// ── Elasticity: cross-price — substitutes (+) vs complements (−) ──
function CrossPriceFig() {
  const W = 360, H = 150, padT = 22
  const panel = (ox, label, up, col) => {
    const x0 = ox + 14, x1 = ox + 150, yb = H - 24, yt = padT
    const X = t => x0 + t * (x1 - x0), Y = v => yb - v * (yb - yt)
    return <g>
      <line x1={x0} y1={yt} x2={x0} y2={yb} stroke={C.grid} />
      <line x1={x0} y1={yb} x2={x1} y2={yb} stroke={C.grid} />
      <line x1={X(0.05)} y1={up ? Y(0.15) : Y(0.85)} x2={X(0.95)} y2={up ? Y(0.85) : Y(0.15)} stroke={col} strokeWidth={2} />
      <text x={(x0 + x1) / 2} y={padT - 6} fill={col} fontSize={8.5} textAnchor="middle">{label}</text>
    </g>
  }
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={svg} role="img" aria-label="Cross-price elasticity">
      {panel(8, 'substitutes (+)', true, C.green)}
      {panel(190, 'complements (−)', false, C.red)}
      <text x={W / 2} y={H - 4} fill={C.text} fontSize={8} textAnchor="middle">price of good A →  vs  demand for good B ↑</text>
    </svg>
  )
}

// ── Surplus: consumer + producer surplus around the equilibrium ──
function SurplusAreasFig() {
  const W = 360, H = 195, padL = 34, padB = 28, padT = 14, padR = 16
  const x0 = padL, x1 = W - padR, yb = H - padB, yt = padT
  const X = q => x0 + q * (x1 - x0), Y = p => yb - p * (yb - yt)
  const qE = 0.5, pE = 0.5
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={svg} role="img" aria-label="Consumer and producer surplus">
      {axes(x0, yt, yb, x1)}
      <polygon points={`${X(0)},${Y(pE)} ${X(qE)},${Y(pE)} ${X(0)},${Y(0.92)}`} fill={C.green} opacity={0.2} />
      <polygon points={`${X(0)},${Y(pE)} ${X(qE)},${Y(pE)} ${X(0)},${Y(0.12)}`} fill={C.blue} opacity={0.2} />
      <line x1={X(0)} y1={Y(0.92)} x2={X(0.85)} y2={Y(0.18)} stroke={C.green} strokeWidth={1.8} />
      <line x1={X(0)} y1={Y(0.12)} x2={X(0.9)} y2={Y(0.9)} stroke={C.red} strokeWidth={1.8} />
      <line x1={X(0)} y1={Y(pE)} x2={X(qE)} y2={Y(pE)} stroke={C.text} strokeDasharray="3 3" opacity={0.6} />
      <line x1={X(qE)} y1={Y(pE)} x2={X(qE)} y2={yb} stroke={C.text} strokeDasharray="3 3" opacity={0.6} />
      <text x={X(0.1)} y={Y(0.72)} fill={C.green} fontSize={8}>consumer surplus</text>
      <text x={X(0.1)} y={Y(0.3)} fill={C.blue2} fontSize={8}>producer surplus</text>
      <circle cx={X(qE)} cy={Y(pE)} r={3} fill={C.white} />
      <text x={W / 2} y={H - 6} fill={C.text} fontSize={9} textAnchor="middle">quantity →</text>
      <text x={x0 + 2} y={yt - 3} fill={C.text} fontSize={8}>price ↑</text>
    </svg>
  )
}

// ── Surplus: a tax wedge creates deadweight loss ──
function DeadweightLossFig() {
  const W = 360, H = 195, padL = 34, padB = 28, padT = 14, padR = 16
  const x0 = padL, x1 = W - padR, yb = H - padB, yt = padT
  const X = q => x0 + q * (x1 - x0), Y = p => yb - p * (yb - yt)
  const qT = 0.36, pB = 0.66, pS = 0.42                 // quantity with tax, buyer/seller prices
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={svg} role="img" aria-label="Deadweight loss from a tax">
      {axes(x0, yt, yb, x1)}
      <line x1={X(0)} y1={Y(0.92)} x2={X(0.85)} y2={Y(0.18)} stroke={C.green} strokeWidth={1.8} />
      <line x1={X(0)} y1={Y(0.12)} x2={X(0.9)} y2={Y(0.9)} stroke={C.red} strokeWidth={1.8} />
      <polygon points={`${X(qT)},${Y(pB)} ${X(qT)},${Y(pS)} ${X(0.5)},${Y(0.5)}`} fill={C.red} opacity={0.35} />
      <line x1={X(qT)} y1={Y(pB)} x2={X(qT)} y2={Y(pS)} stroke={C.amber} strokeWidth={2} />
      <text x={X(qT) + 6} y={Y((pB + pS) / 2)} fill={C.amber} fontSize={8}>tax wedge</text>
      <text x={X(0.56)} y={Y(0.46)} fill={C.red} fontSize={8}>deadweight loss</text>
      <circle cx={X(0.5)} cy={Y(0.5)} r={2.6} fill={C.white} />
      <text x={W / 2} y={H - 6} fill={C.text} fontSize={9} textAnchor="middle">quantity →  (tax shrinks trade below the efficient Q*)</text>
      <text x={x0 + 2} y={yt - 3} fill={C.text} fontSize={8}>price ↑</text>
    </svg>
  )
}

// ── Cost: U-shaped AC/AVC with MC cutting through their minima ──
function CostCurvesFig() {
  const W = 360, H = 195, padL = 34, padB = 28, padT = 14, padR = 16
  const x0 = padL, x1 = W - padR, yb = H - padB, yt = padT
  const X = q => x0 + (0.08 + q * 0.9) * (x1 - x0), Y = c => yb - c * (yb - yt)
  const AC = q => 0.18 / q + 0.18 + 0.55 * q
  const AVC = q => 0.16 + 0.55 * q
  const MC = q => 0.16 + 1.1 * q
  const curve = (f, col, dash) => {
    const pts = Array.from({ length: 40 }, (_, i) => { const q = 0.12 + i / 39 * 0.85; return `${X(q)},${Y(Math.min(0.97, f(q)))}` }).join(' ')
    return <polyline points={pts} fill="none" stroke={col} strokeWidth={1.8} strokeDasharray={dash || ''} />
  }
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={svg} role="img" aria-label="Cost curves">
      {axes(x0, yt, yb, x1)}
      {curve(MC, C.red)}
      {curve(AC, C.green)}
      {curve(AVC, C.blue2, '5 3')}
      <text x={X(0.95)} y={Y(MC(0.95)) - 2} fill={C.red} fontSize={8} textAnchor="end">MC</text>
      <text x={X(0.9)} y={Y(AC(0.9)) - 4} fill={C.green} fontSize={8} textAnchor="end">AC</text>
      <text x={X(0.92)} y={Y(AVC(0.92)) + 10} fill={C.blue2} fontSize={8} textAnchor="end">AVC</text>
      <text x={W / 2} y={H - 6} fill={C.text} fontSize={9} textAnchor="middle">output q →  (MC crosses AC/AVC at their minima)</text>
      <text x={x0 + 2} y={yt - 3} fill={C.text} fontSize={8}>cost per unit ↑</text>
    </svg>
  )
}

// ── Cost: break-even where total revenue meets total cost (FC + VC) ──
function BreakEvenFig() {
  const W = 360, H = 185, padL = 34, padB = 28, padT = 14, padR = 16
  const x0 = padL, x1 = W - padR, yb = H - padB, yt = padT
  const X = q => x0 + q * (x1 - x0), Y = v => yb - v * (yb - yt)
  const fc = 0.25, tc = q => fc + 0.55 * q, tr = q => 0.95 * q
  const qBE = fc / (0.95 - 0.55)
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={svg} role="img" aria-label="Break-even analysis">
      {axes(x0, yt, yb, x1)}
      <line x1={X(0)} y1={Y(0)} x2={X(1)} y2={Y(tr(1))} stroke={C.green} strokeWidth={2} />
      <line x1={X(0)} y1={Y(fc)} x2={X(1)} y2={Y(tc(1))} stroke={C.red} strokeWidth={2} />
      <line x1={X(0)} y1={Y(fc)} x2={X(1)} y2={Y(fc)} stroke={C.amber} strokeDasharray="4 3" />
      <circle cx={X(qBE)} cy={Y(tr(qBE))} r={3.5} fill={C.white} />
      <text x={X(qBE) + 6} y={Y(tr(qBE)) + 2} fill={C.white} fontSize={8}>break-even</text>
      <text x={X(1)} y={Y(tr(1)) - 2} fill={C.green} fontSize={8} textAnchor="end">total revenue</text>
      <text x={X(1)} y={Y(tc(1)) + 10} fill={C.red} fontSize={8} textAnchor="end">total cost</text>
      <text x={X(0.02)} y={Y(fc) - 4} fill={C.amber} fontSize={8}>fixed cost</text>
      <text x={W / 2} y={H - 6} fill={C.text} fontSize={9} textAnchor="middle">quantity →</text>
    </svg>
  )
}

// ── Marginal analysis: profit maximised where MR = MC ──
function MarginalRevenueCostFig() {
  const W = 360, H = 190, padL = 34, padB = 28, padT = 14, padR = 16
  const x0 = padL, x1 = W - padR, yb = H - padB, yt = padT
  const X = q => x0 + q * (x1 - x0), Y = v => yb - v * (yb - yt)
  const MC = q => 0.18 + 0.9 * q, MR = q => 0.82 - 0.5 * q
  const qStar = (0.82 - 0.18) / (0.9 + 0.5)
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={svg} role="img" aria-label="MR = MC">
      {axes(x0, yt, yb, x1)}
      <line x1={X(0)} y1={Y(MC(0))} x2={X(0.95)} y2={Y(MC(0.95))} stroke={C.red} strokeWidth={2} />
      <line x1={X(0)} y1={Y(MR(0))} x2={X(0.95)} y2={Y(MR(0.95))} stroke={C.green} strokeWidth={2} />
      <line x1={X(qStar)} y1={yb} x2={X(qStar)} y2={Y(MC(qStar))} stroke={C.text} strokeDasharray="3 3" opacity={0.6} />
      <circle cx={X(qStar)} cy={Y(MC(qStar))} r={3.5} fill={C.white} />
      <text x={X(qStar) + 6} y={Y(MC(qStar)) - 4} fill={C.white} fontSize={8}>MR = MC → Q*</text>
      <text x={X(0.9)} y={Y(MC(0.9)) - 2} fill={C.red} fontSize={8} textAnchor="end">MC</text>
      <text x={X(0.9)} y={Y(MR(0.9)) + 10} fill={C.green} fontSize={8} textAnchor="end">MR</text>
      <text x={X(0.2)} y={yt + 8} fill={C.text} fontSize={7.5}>MR &gt; MC: make more</text>
      <text x={X(0.78)} y={yb - 6} fill={C.text} fontSize={7.5} textAnchor="end">MR &lt; MC: make less</text>
      <text x={W / 2} y={H - 6} fill={C.text} fontSize={9} textAnchor="middle">output q →</text>
    </svg>
  )
}

// ── Opportunity cost: production-possibilities frontier (PPF) ──
function PpfFig() {
  const W = 360, H = 190, padL = 36, padB = 28, padT = 14, padR = 16
  const x0 = padL, x1 = W - padR, yb = H - padB, yt = padT
  const X = a => x0 + a * (x1 - x0), Y = b => yb - b * (yb - yt)
  const pts = Array.from({ length: 40 }, (_, i) => { const t = i / 39; return `${X(t)},${Y(Math.sqrt(1 - t * t) * 0.9)}` }).join(' ')
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={svg} role="img" aria-label="Production possibilities frontier">
      {axes(x0, yt, yb, x1)}
      <polyline points={pts} fill="none" stroke={C.green} strokeWidth={2} />
      <circle cx={X(0.45)} cy={Y(Math.sqrt(1 - 0.45 * 0.45) * 0.9)} r={3.5} fill={C.amber} />
      <text x={X(0.45) + 6} y={Y(Math.sqrt(1 - 0.45 * 0.45) * 0.9) - 4} fill={C.amber} fontSize={8}>efficient</text>
      <circle cx={X(0.3)} cy={Y(0.3)} r={3} fill={C.blue2} />
      <text x={X(0.3) + 6} y={Y(0.3) + 3} fill={C.blue2} fontSize={8}>inside (slack)</text>
      <circle cx={X(0.8)} cy={Y(0.8)} r={3} fill={C.red} />
      <text x={X(0.8) - 4} y={Y(0.8)} fill={C.red} fontSize={8} textAnchor="end">unreachable</text>
      <text x={W / 2} y={H - 6} fill={C.text} fontSize={9} textAnchor="middle">good A (e.g. build ships) →</text>
      <text x={x0 + 2} y={yt - 3} fill={C.text} fontSize={8}>good B ↑</text>
    </svg>
  )
}

// ── Comparative advantage: opportunity cost decides who makes what ──
function ComparativeAdvantageFig() {
  const W = 360, H = 165, padT = 20
  const rows = [['You: make widget', 0.35, C.green], ['You: make gadget', 0.85, C.red],
    ['Rival: make widget', 0.75, C.red], ['Rival: make gadget', 0.30, C.green]]
  const x0 = 130, x1 = W - 30, rh = (H - padT - 16) / rows.length
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={svg} role="img" aria-label="Comparative advantage">
      <text x={W / 2} y={14} fill={C.text} fontSize={8.5} textAnchor="middle">opportunity cost (lower = your advantage → specialise)</text>
      {rows.map(([lbl, v, col], i) => {
        const y = padT + i * rh + rh / 2
        return <g key={i}>
          <text x={x0 - 6} y={y + 3} fill={C.text} fontSize={8} textAnchor="end">{lbl}</text>
          <rect x={x0} y={y - 6} width={(x1 - x0) * v} height={12} fill={col} opacity={0.85} rx={2} />
        </g>
      })}
      <text x={W / 2} y={H - 4} fill={C.text} fontSize={7.5} textAnchor="middle">green = lower opportunity cost → make it yourself; red → buy it</text>
    </svg>
  )
}

// ── Market structures: the competition → monopoly spectrum ──
function StructureSpectrumFig() {
  const W = 360, H = 150, padL = 16, padR = 16, y = 70
  const stops = [['Perfect\ncompetition', 0.0, C.green], ['Monopolistic\ncompetition', 0.33, C.blue2],
    ['Oligopoly', 0.66, C.amber], ['Monopoly', 1.0, C.red]]
  const x0 = padL, x1 = W - padR, X = t => x0 + t * (x1 - x0)
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={svg} role="img" aria-label="Market structure spectrum">
      <defs><linearGradient id="spec" x1="0" x2="1"><stop offset="0" stopColor={C.green} /><stop offset="1" stopColor={C.red} /></linearGradient></defs>
      <rect x={x0} y={y - 5} width={x1 - x0} height={10} fill="url(#spec)" opacity={0.5} rx={5} />
      {stops.map(([lbl, t, col], i) => (
        <g key={i}>
          <circle cx={X(t)} cy={y} r={5} fill={col} />
          {lbl.split('\n').map((ln, j) => <text key={j} x={X(t)} y={y + 22 + j * 9} fill={col} fontSize={7.5} textAnchor="middle">{ln}</text>)}
        </g>
      ))}
      <text x={x0} y={y - 14} fill={C.green} fontSize={8}>many firms · no power</text>
      <text x={x1} y={y - 14} fill={C.red} fontSize={8} textAnchor="end">one firm · price-setter</text>
      <text x={W / 2} y={H - 6} fill={C.text} fontSize={8} textAnchor="middle">← more competition   ·   more market power →</text>
    </svg>
  )
}

// ── Market structures: monopoly sets MR=MC, prices up the demand curve, DWL ──
function MonopolyPricingFig() {
  const W = 360, H = 195, padL = 34, padB = 28, padT = 14, padR = 16
  const x0 = padL, x1 = W - padR, yb = H - padB, yt = padT
  const X = q => x0 + q * (x1 - x0), Y = v => yb - v * (yb - yt)
  const D = q => 0.92 - 0.8 * q, MR = q => 0.92 - 1.6 * q, MC = 0.28
  const qM = (0.92 - MC) / 1.6
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={svg} role="img" aria-label="Monopoly pricing">
      {axes(x0, yt, yb, x1)}
      <line x1={X(0)} y1={Y(D(0))} x2={X(1)} y2={Y(D(1))} stroke={C.green} strokeWidth={1.8} />
      <line x1={X(0)} y1={Y(MR(0))} x2={X(0.57)} y2={Y(MR(0.57))} stroke={C.blue2} strokeWidth={1.6} strokeDasharray="5 3" />
      <line x1={x0} y1={Y(MC)} x2={x1} y2={Y(MC)} stroke={C.red} strokeWidth={1.6} />
      <line x1={X(qM)} y1={yb} x2={X(qM)} y2={Y(D(qM))} stroke={C.text} strokeDasharray="3 3" opacity={0.6} />
      <circle cx={X(qM)} cy={Y(D(qM))} r={3.5} fill={C.amber} />
      <text x={X(qM) + 5} y={Y(D(qM)) - 4} fill={C.amber} fontSize={8}>monopoly P (&gt; MC)</text>
      <text x={X(0.9)} y={Y(D(0.9)) - 2} fill={C.green} fontSize={8} textAnchor="end">Demand</text>
      <text x={X(0.5)} y={Y(MR(0.5)) + 10} fill={C.blue2} fontSize={8}>MR</text>
      <text x={x1} y={Y(MC) - 3} fill={C.red} fontSize={8} textAnchor="end">MC</text>
      <text x={W / 2} y={H - 6} fill={C.text} fontSize={9} textAnchor="middle">output q →  (restricts Q, raises P above MC)</text>
    </svg>
  )
}

// ── Arbitrage: two markets with a transport-cost no-arbitrage band ──
function ArbitrageBandFig() {
  const W = 360, H = 180, padL = 40, padB = 26, padT = 16, padR = 14
  const x0 = padL, x1 = W - padR, yb = H - padB, yt = padT
  const X = t => x0 + t * (x1 - x0), Y = v => yb - v * (yb - yt)
  const jita = 0.45, band = 0.18
  const cj = t => 0.78 - 0.12 * t + 0.05 * Math.sin(t * 9)
  const cjPts = Array.from({ length: 40 }, (_, i) => `${X(i / 39)},${Y(cj(i / 39))}`).join(' ')
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={svg} role="img" aria-label="Arbitrage band">
      {axes(x0, yt, yb, x1)}
      <rect x={x0} y={Y(jita + band)} width={x1 - x0} height={Y(jita - band) - Y(jita + band)} fill={C.blue} opacity={0.12} />
      <line x1={x0} y1={Y(jita)} x2={x1} y2={Y(jita)} stroke={C.green} strokeWidth={1.6} />
      <line x1={x0} y1={Y(jita + band)} x2={x1} y2={Y(jita + band)} stroke={C.blue2} strokeDasharray="4 3" />
      <polyline points={cjPts} fill="none" stroke={C.amber} strokeWidth={1.8} />
      <text x={x0 + 4} y={Y(jita) - 4} fill={C.green} fontSize={8}>Jita price</text>
      <text x={x0 + 4} y={Y(jita + band) - 3} fill={C.blue2} fontSize={7.5}>+ transport cost (no-arb band)</text>
      <text x={X(0.3)} y={Y(cj(0.3)) - 4} fill={C.amber} fontSize={8}>C-J price → arbitrage while above band</text>
      <text x={W / 2} y={H - 5} fill={C.text} fontSize={9} textAnchor="middle">time →  (gap closes as haulers exploit it)</text>
    </svg>
  )
}

// ── Market making: buy at bid, sell at ask, capture the spread; inventory swings ──
function SpreadCaptureFig() {
  const W = 360, H = 180, padL = 30, padB = 26, padT = 16, padR = 14
  const x0 = padL, x1 = W - padR, yb = H - padB, yt = padT
  const X = t => x0 + t * (x1 - x0), Y = v => yb - v * (yb - yt)
  const ask = 0.7, bid = 0.4
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={svg} role="img" aria-label="Market making spread capture">
      {axes(x0, yt, yb, x1)}
      <line x1={x0} y1={Y(ask)} x2={x1} y2={Y(ask)} stroke={C.red} strokeWidth={1.6} />
      <line x1={x0} y1={Y(bid)} x2={x1} y2={Y(bid)} stroke={C.green} strokeWidth={1.6} />
      <rect x={x0} y={Y(ask)} width={x1 - x0} height={Y(bid) - Y(ask)} fill={C.blue} opacity={0.08} />
      <text x={x0 + 4} y={Y(ask) - 3} fill={C.red} fontSize={8}>your sell order (ask)</text>
      <text x={x0 + 4} y={Y(bid) + 11} fill={C.green} fontSize={8}>your buy order (bid)</text>
      <circle cx={X(0.25)} cy={Y(bid)} r={3.5} fill={C.green} /><text x={X(0.25)} y={Y(bid) - 6} fill={C.green} fontSize={7.5} textAnchor="middle">buy</text>
      <circle cx={X(0.7)} cy={Y(ask)} r={3.5} fill={C.red} /><text x={X(0.7)} y={Y(ask) + 12} fill={C.red} fontSize={7.5} textAnchor="middle">sell</text>
      <line x1={X(0.9)} y1={Y(ask)} x2={X(0.9)} y2={Y(bid)} stroke={C.amber} strokeWidth={2} />
      <text x={X(0.9) - 4} y={Y((ask + bid) / 2)} fill={C.amber} fontSize={8} textAnchor="end">spread = gross profit/unit</text>
      <text x={W / 2} y={H - 5} fill={C.text} fontSize={8} textAnchor="middle">time →  (profit if fees &lt; spread and inventory stays balanced)</text>
    </svg>
  )
}

// ── Game theory: a 2×2 payoff matrix with the Nash equilibrium ──
function PayoffMatrixFig() {
  const W = 360, H = 195, ox = 110, oy = 46, cell = 88
  const cells = [['+3, +3', false], ['−1, +4', false], ['+4, −1', false], ['+1, +1', true]]
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={svg} role="img" aria-label="Payoff matrix">
      <text x={ox + cell} y={20} fill={C.text} fontSize={8} textAnchor="middle">Rival</text>
      <text x={ox + cell / 2} y={38} fill={C.green} fontSize={8} textAnchor="middle">Hold</text>
      <text x={ox + cell * 1.5} y={38} fill={C.red} fontSize={8} textAnchor="middle">Undercut</text>
      <text x={28} y={oy + cell} fill={C.text} fontSize={8} transform={`rotate(-90 28 ${oy + cell})`} textAnchor="middle">You</text>
      <text x={ox - 8} y={oy + cell / 2} fill={C.green} fontSize={8} textAnchor="end">Hold</text>
      <text x={ox - 8} y={oy + cell * 1.5} fill={C.red} fontSize={8} textAnchor="end">Undercut</text>
      {cells.map((c, i) => {
        const r = Math.floor(i / 2), col = i % 2, x = ox + col * cell, y = oy + r * cell
        return <g key={i}>
          <rect x={x} y={y} width={cell - 4} height={cell - 4} fill={c[1] ? 'rgba(224,82,82,0.18)' : 'none'} stroke={c[1] ? C.red : C.grid} rx={4} />
          <text x={x + (cell - 4) / 2} y={y + (cell - 4) / 2 + 4} fill={C.white} fontSize={11} textAnchor="middle">{c[0]}</text>
          {c[1] && <text x={x + (cell - 4) / 2} y={y + cell - 12} fill={C.red} fontSize={7.5} textAnchor="middle">Nash equilibrium</text>}
        </g>
      })}
      <text x={W / 2} y={H - 4} fill={C.text} fontSize={7.5} textAnchor="middle">both would prefer (Hold, Hold) — but each defects: a prisoner’s dilemma</text>
    </svg>
  )
}

// ── Time value of money: future cash flows discounted to present value ──
function DiscountingFig() {
  const W = 360, H = 185, padL = 30, padB = 30, padT = 16, padR = 14
  const x0 = padL, x1 = W - padR, yb = H - padB, yt = padT
  const n = 6, bw = (x1 - x0) / n, r = 0.12
  const Y = v => yb - v * (yb - yt)
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={svg} role="img" aria-label="Discounting cash flows">
      <line x1={x0} y1={yb} x2={x1} y2={yb} stroke={C.grid} />
      {Array.from({ length: n }, (_, i) => {
        const face = 0.8, pv = face / Math.pow(1 + r, i)
        const x = x0 + i * bw
        return <g key={i}>
          <rect x={x + 4} y={Y(face)} width={bw - 8} height={yb - Y(face)} fill="none" stroke={C.grid} rx={1} />
          <rect x={x + 4} y={Y(pv)} width={bw - 8} height={yb - Y(pv)} fill={C.green} opacity={0.8} rx={1} />
          <text x={x + bw / 2} y={yb + 12} fill={C.text} fontSize={7.5} textAnchor="middle">t={i}</text>
        </g>
      })}
      <text x={x0 + 4} y={yt + 2} fill={C.text} fontSize={8}>same future cash flow, shrinking present value (r = 12%)</text>
      <text x={x1} y={Y(0.8 / Math.pow(1 + r, n - 1)) - 4} fill={C.green} fontSize={7.5} textAnchor="end">PV = FV/(1+r)ⁿ</text>
      <text x={W / 2} y={H - 6} fill={C.text} fontSize={9} textAnchor="middle">years out →  (the later, the less it’s worth today)</text>
    </svg>
  )
}

// ── Time value of money: the NPV profile crosses zero at the IRR ──
function NpvProfileFig() {
  const W = 360, H = 180, padL = 36, padB = 28, padT = 14, padR = 14
  const x0 = padL, x1 = W - padR, yb = H - padB, yt = padT, y0 = yt + (yb - yt) * 0.42
  const X = t => x0 + t * (x1 - x0)
  const npv = r => 1.0 - 2.6 * r - 1.2 * r * r       // decreasing, crosses zero
  const irr = 0.34
  const top = npv(0), Y = v => y0 - (v / top) * (y0 - yt)
  const pts = Array.from({ length: 40 }, (_, i) => { const r = i / 39 * 0.6; return `${X(r / 0.6)},${Y(npv(r))}` }).join(' ')
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={svg} role="img" aria-label="NPV profile and IRR">
      <line x1={x0} y1={yt} x2={x0} y2={yb} stroke={C.grid} />
      <line x1={x0} y1={y0} x2={x1} y2={y0} stroke={C.grid} />
      <polyline points={pts} fill="none" stroke={C.blue2} strokeWidth={2} />
      <circle cx={X(irr / 0.6)} cy={y0} r={3.5} fill={C.amber} />
      <text x={X(irr / 0.6)} y={y0 + 14} fill={C.amber} fontSize={8} textAnchor="middle">IRR (NPV = 0)</text>
      <text x={x0 + 4} y={Y(top) + 2} fill={C.green} fontSize={8}>NPV &gt; 0: accept</text>
      <text x={x1 - 4} y={yb - 4} fill={C.red} fontSize={8} textAnchor="end">NPV &lt; 0: reject</text>
      <text x={W / 2} y={H - 6} fill={C.text} fontSize={9} textAnchor="middle">discount rate r →</text>
    </svg>
  )
}

// registry used by the Markdown [[fig:KEY]] marker
// eslint-disable-next-line react-refresh/only-export-components
export const FIGURES = {
  histogram: HistogramFig,
  convergence: ConvergenceFig,
  copula: CopulaFig,
  gbmPaths: GbmPathsFig,
  scenarioBars: ScenarioBarsFig,
  tornado: TornadoFig,
  scenarioShift: ScenarioShiftFig,
  scenarioTree: ScenarioTreeFig,
  efficientFrontier: EfficientFrontierFig,
  diversification: DiversificationFig,
  waterfill: WaterfillFig,
  orderBook: OrderBookFig,
  supplyDemand: SupplyDemandFig,
  elasticity: ElasticityFig,
  advTrend: AdvTrendFig,
  weekdaySeason: WeekdaySeasonFig,
  demandScore: DemandScoreFig,
  decomposition: DecompositionFig,
  fanChart: FanChartFig,
  walkForward: WalkForwardFig,
  modelPanel: ModelPanelFig,
  spreadDepth: SpreadDepthFig,
  marketImpact: MarketImpactFig,
  liqVsVol: LiqVsVolFig,
  priceTimePriority: PriceTimePriorityFig,
  spreadDecomp: SpreadDecompFig,
  microprice: MicropriceFig,
  undercutWar: UndercutWarFig,
  supplyCurve: SupplyCurveFig,
  supplyShift: SupplyShiftFig,
  equilibriumShift: EquilibriumShiftFig,
  surplusShortage: SurplusShortageFig,
  elasticityRevenue: ElasticityRevenueFig,
  crossPrice: CrossPriceFig,
  surplusAreas: SurplusAreasFig,
  deadweightLoss: DeadweightLossFig,
  costCurves: CostCurvesFig,
  breakEven: BreakEvenFig,
  marginalRevenueCost: MarginalRevenueCostFig,
  ppf: PpfFig,
  comparativeAdvantage: ComparativeAdvantageFig,
  structureSpectrum: StructureSpectrumFig,
  monopolyPricing: MonopolyPricingFig,
  arbitrageBand: ArbitrageBandFig,
  spreadCapture: SpreadCaptureFig,
  payoffMatrix: PayoffMatrixFig,
  discounting: DiscountingFig,
  npvProfile: NpvProfileFig,
}
