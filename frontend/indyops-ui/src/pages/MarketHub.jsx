import { useState, lazy, Suspense } from 'react'
import TradeOptimizerPage from './TradeOptimizerPage'

// The Browser pulls in Plotly (~4MB) — keep it in its own lazy chunk so the
// Optimizer subtab (chart-free, stays in the main bundle) never drags it in.
const MarketBrowser = lazy(() => import('./MarketPage'))

const SUBTABS = ['Browser', 'Optimizer']

export default function MarketHub() {
  const [tab, setTab] = useState(0)
  return (
    <div>
      <h2 style={{ marginBottom: 14 }}>Market</h2>
      <div className="tabs" style={{ marginBottom: 20 }}>
        {SUBTABS.map((t, i) => (
          <button key={t} className={`tab-btn ${tab === i ? 'active' : ''}`} onClick={() => setTab(i)}>{t}</button>
        ))}
      </div>
      {tab === 0 && (
        <Suspense fallback={<div className="empty-state">Loading market…</div>}>
          <MarketBrowser />
        </Suspense>
      )}
      {tab === 1 && <TradeOptimizerPage />}
    </div>
  )
}
