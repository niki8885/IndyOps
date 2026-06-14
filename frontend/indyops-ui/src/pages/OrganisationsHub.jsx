import { useState } from 'react'
import OrgsPage from './OrgsPage'
import ProjectsPage from './ProjectsPage'
import FacilitiesPage from './FacilitiesPage'

const SUBTABS = ['Organisations', 'Projects', 'Facilities']

export default function OrganisationsHub() {
  const [tab, setTab] = useState(0)
  return (
    <div>
      <div className="tabs" style={{ marginBottom: 20 }}>
        {SUBTABS.map((t, i) => (
          <button key={i} className={`tab-btn ${tab === i ? 'active' : ''}`} onClick={() => setTab(i)}>{t}</button>
        ))}
      </div>
      {tab === 0 && <OrgsPage />}
      {tab === 1 && <ProjectsPage />}
      {tab === 2 && <FacilitiesPage />}
    </div>
  )
}
