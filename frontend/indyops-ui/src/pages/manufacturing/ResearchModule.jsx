import { useState, useEffect } from 'react'
import { get } from '../../api/client'
import CopyingTab from './CopyingTab'
import MeTeTab from './MeTeTab'

const SUBTABS = ['Copying', 'ME / TE Payback', 'Invention', 'Invention Optimizer']

export default function ResearchModule() {
  const [sub, setSub] = useState(0)
  const [facilities, setFacilities] = useState([])
  const [characters, setCharacters] = useState([])

  useEffect(() => { get('/facilities').then(setFacilities).catch(() => {}) }, [])
  useEffect(() => { get('/characters').then(setCharacters).catch(() => {}) }, [])

  const shared = { facilities, characters }

  return (
    <div>
      <div className="tabs" style={{ marginTop: 4 }}>
        {SUBTABS.map((t, i) => (
          <button key={i} className={`tab-btn ${sub === i ? 'active' : ''}`} onClick={() => setSub(i)}>{t}</button>
        ))}
      </div>
      {sub === 0 && <CopyingTab {...shared} />}
      {sub === 1 && <MeTeTab {...shared} />}
      {sub === 2 && <Placeholder name="Invention" />}
      {sub === 3 && <Placeholder name="Invention Optimizer" />}
    </div>
  )
}

function Placeholder({ name }) {
  return <div className="empty-state" style={{ marginTop: 24 }}>{name} — coming in the next stage.</div>
}
