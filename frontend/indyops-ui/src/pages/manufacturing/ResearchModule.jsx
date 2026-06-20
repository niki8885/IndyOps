import { useState, useEffect } from 'react'
import { get } from '../../api/client'
import CopyingTab from './CopyingTab'
import MeTeTab from './MeTeTab'
import InventionTab from './InventionTab'
import InventionOptimizerTab from './InventionOptimizerTab'

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
      {sub === 2 && <InventionTab {...shared} />}
      {sub === 3 && <InventionOptimizerTab {...shared} />}
    </div>
  )
}
