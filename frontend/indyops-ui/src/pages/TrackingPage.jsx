import { useState } from 'react'
import MarketTracking from './tracking/MarketTracking'
import IndustryTracking from './tracking/IndustryTracking'
import OrdersTracking from './tracking/OrdersTracking'
import ContractsTracking from './tracking/ContractsTracking'
import MissionTracking from './tracking/MissionTracking'
import RattingTracking from './tracking/RattingTracking'
import MiningTracking from './tracking/MiningTracking'
import PITracking from './tracking/PITracking'

const SUBTABS = ['Market', 'Industry', 'Orders', 'Contracts', 'Mission', 'Ratting', 'Mining', 'PI']

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
      {tab === 0 && <MarketTracking />}
      {tab === 1 && <IndustryTracking />}
      {tab === 2 && <OrdersTracking />}
      {tab === 3 && <ContractsTracking />}
      {tab === 4 && <MissionTracking />}
      {tab === 5 && <RattingTracking />}
      {tab === 6 && <MiningTracking />}
      {tab === 7 && <PITracking />}
    </div>
  )
}
