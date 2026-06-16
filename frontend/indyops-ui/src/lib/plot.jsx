// Shared Plotly setup + dark theme for the analytics pages (Analysis, Market).
// Centralises the fragile factory/UMD interop so each page doesn't repeat it.
import * as factoryModule from 'react-plotly.js/factory'
import * as plotlyModule from 'plotly.js-dist-min'

// The factory (CJS) and plotly-dist (UMD) can land as the module itself, under
// `.default`, or double-wrapped depending on the bundler — normalise to a fn.
function asFn(m) {
  if (typeof m === 'function') return m
  if (m && typeof m.default === 'function') return m.default
  if (m && m.default && typeof m.default.default === 'function') return m.default.default
  return null
}

export let Plot = null
try {
  const create = asFn(factoryModule)
  const Plotly = plotlyModule.default || plotlyModule
  if (create) Plot = create(Plotly)
} catch (e) {
  console.error('Plotly init failed', e)
}

export const C = {
  text: '#8b93b0', grid: '#252a40', accent: '#c8a951', white: '#e8ecf4',
  green: '#4caf7d', red: '#e05252', blue: '#3a9bd6', purple: '#9b6dd6', orange: '#e0884f',
}
export const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

export const baseLayout = (over = {}) => ({
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

export const cfg = { displayModeBar: false, responsive: true }

export function fmtIsk(v) {
  if (v == null) return '—'
  const n = Number(v)
  if (Math.abs(n) >= 1e9) return (n / 1e9).toFixed(2) + ' B'
  if (Math.abs(n) >= 1e6) return (n / 1e6).toFixed(2) + ' M'
  if (Math.abs(n) >= 1e3) return (n / 1e3).toFixed(1) + ' K'
  return n.toLocaleString(undefined, { maximumFractionDigits: 2 })
}

export function fmtNum(v) {
  if (v == null) return '—'
  return Number(v).toLocaleString(undefined, { maximumFractionDigits: 0 })
}

export function secClass(sec) {
  if (sec == null) return 'sec-null'
  if (sec >= 0.5) return 'sec-high'
  if (sec > 0) return 'sec-low'
  return 'sec-null'
}
