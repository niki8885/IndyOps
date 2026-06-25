// Daily + cumulative profit chart for the Tracking tabs. Consumes the per-day `series`
// ([{date, profit|<valueKey>, sell}]) the backend already emits, drawing daily bars
// (green/red by sign) with a cumulative running-total line on a secondary axis. Falls
// back to the tiny CSS MiniBars when Plotly failed to initialise.
import { Plot, baseLayout, cfg, C } from '../../lib/plot'
import { MiniBars } from './common'

export default function ProfitChart({ series, valueKey = 'profit', label }) {
  if (!series || !series.length) return null
  if (!Plot) return <MiniBars series={series} valueKey={valueKey} label={label} />

  const dates = series.map(s => s.date)
  const vals = series.map(s => Number(s[valueKey] || 0))
  // running total (pure — avoids a reassigned closure var across renders)
  const cum = vals.map((_, i) => vals.slice(0, i + 1).reduce((a, b) => a + b, 0))
  const colors = vals.map(v => (v >= 0 ? C.green : C.red))

  return (
    <div className="card" style={{ marginBottom: 18 }}>
      {label && <div className="sec-label" style={{ marginBottom: 10 }}>{label}</div>}
      <Plot
        data={[
          {
            type: 'bar', name: 'Daily', x: dates, y: vals,
            marker: { color: colors },
            hovertemplate: '%{x}<br>%{y:,.0f} ISK<extra>daily</extra>',
          },
          {
            type: 'scatter', mode: 'lines', name: 'Cumulative', x: dates, y: cum, yaxis: 'y2',
            line: { color: C.accent, width: 2 },
            hovertemplate: '%{y:,.0f} ISK<extra>cumulative</extra>',
          },
        ]}
        layout={baseLayout({
          height: 250,
          bargap: 0.25,
          yaxis: { gridcolor: C.grid, zerolinecolor: C.grid, tickformat: '.2s' },
          yaxis2: {
            overlaying: 'y', side: 'right', tickformat: '.2s',
            gridcolor: 'rgba(0,0,0,0)', zerolinecolor: 'rgba(0,0,0,0)', showgrid: false,
          },
        })}
        config={cfg}
        style={{ width: '100%', height: 250 }}
        useResizeHandler
      />
    </div>
  )
}
