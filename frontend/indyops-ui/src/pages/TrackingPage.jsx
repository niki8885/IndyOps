import { useState } from 'react'
import OrdersTracking from './tracking/OrdersTracking'
import ContractsTracking from './tracking/ContractsTracking'
import MissionTracking from './tracking/MissionTracking'
import RattingTracking from './tracking/RattingTracking'
import ComingSoon from './tracking/ComingSoon'

const SUBTABS = ['Market', 'Industry', 'Orders', 'Contracts', 'Mission', 'Ratting']

export default function TrackingPage() {
  // Orders is the first fully built sub-tab, so land on it.
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
      {tab === 3 && <ContractsTracking />}
      {tab === 4 && <MissionTracking />}
      {tab === 5 && <RattingTracking />}
    </div>
  )
}
