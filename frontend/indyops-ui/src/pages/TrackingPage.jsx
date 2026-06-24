import { useState } from 'react'
import OrdersTracking from './tracking/OrdersTracking'
import ComingSoon from './tracking/ComingSoon'

const SUBTABS = ['Market', 'Industry', 'Orders', 'Contracts']

export default function TrackingPage() {
  // Orders is the only built sub-tab today, so land on it.
  const [tab, setTab] = useState(2)
  return (
    <div>
      <h2 style={{ marginBottom: 14 }}>Tracking</h2>
      <div className="tabs" style={{ marginBottom: 20 }}>
        {SUBTABS.map((t, i) => (
          <button key={t} className={`tab-btn ${tab === i ? 'active' : ''}`} onClick={() => setTab(i)}>{t}</button>
        ))}
      </div>
      {tab === 0 && <ComingSoon title="Market" />}
      {tab === 1 && <ComingSoon title="Industry" />}
      {tab === 2 && <OrdersTracking />}
      {tab === 3 && <ComingSoon title="Contracts" />}
    </div>
  )
}
