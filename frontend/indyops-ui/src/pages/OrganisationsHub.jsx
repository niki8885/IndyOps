import { useState } from 'react'
import OrgsPage from './OrgsPage'
import CorporationsPage from './CorporationsPage'
import ProjectsPage from './ProjectsPage'
import FacilitiesPage from './FacilitiesPage'
import BlueprintsPage from './BlueprintsPage'

const SUBTABS = ['Organisations', 'Corporations', 'Projects', 'Facilities', 'Blueprints']

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
      {tab === 1 && <CorporationsPage />}
      {tab === 2 && <ProjectsPage />}
      {tab === 3 && <FacilitiesPage />}
      {tab === 4 && <BlueprintsPage />}
    </div>
  )
}
