import { useState, useEffect, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import { get } from '../api/client'
import CharactersTab from './personal/CharactersTab'
import WalletTab from './personal/WalletTab'
import SkillsTab from './personal/SkillsTab'
import AssetsTab from './personal/AssetsTab'
import ContractsTab from './personal/ContractsTab'
import IndustryTab from './personal/IndustryTab'
import { CharacterSelect } from './personal/common'

const SUBTABS = ['Characters', 'Wallet', 'Skills', 'Assets', 'Contracts', 'Industry']

function ssoError(code) {
  switch (code) {
    case 'bad_state':      return 'Login session expired — please try linking again.'
    case 'owned_by_other': return 'That character is already linked to another account.'
    case 'sso_failed':     return 'EVE SSO failed. Please try again.'
    default:               return 'Something went wrong during EVE login.'
  }
}

export default function PersonalFilePage() {
  const [tab, setTab]           = useState(0)
  const [chars, setChars]       = useState([])
  const [selected, setSelected] = useState(null)
  const [banner, setBanner]     = useState(null)
  const [params, setParams]     = useSearchParams()

  const reload = useCallback(async () => {
    try {
      const cs = await get('/characters')
      setChars(cs)
      setSelected(prev => (prev && cs.some(c => c.id === prev)) ? prev : (cs[0]?.id ?? null))
    } catch { /* not logged in / no chars */ }
  }, [])

  useEffect(() => { reload() }, [reload])

  // one-shot: read the ?linked / ?error the SSO callback bounced us back with
  useEffect(() => {
    const linked = params.get('linked')
    const error  = params.get('error')
    if (linked) { setBanner({ ok: true, msg: `Character “${linked}” linked — syncing data…` }); reload() }
    else if (error) { setBanner({ ok: false, msg: ssoError(error) }) }
    if (linked || error) {
      params.delete('linked'); params.delete('error')
      setParams(params, { replace: true })
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const dataReady = chars.length > 0

  return (
    <div>
      <h2 style={{ marginBottom: 6 }}>Personal File</h2>
      <p style={{ color: 'var(--text)', marginTop: 0, marginBottom: 18, fontSize: 13 }}>
        Link your EVE characters via EVE SSO and pull wallet, skills, assets, contracts and
        industry jobs straight from ESI.
      </p>

      {banner && (
        <div className={banner.ok ? 'warning-box' : 'error-box'} style={{ marginBottom: 16 }}>
          {banner.msg}
        </div>
      )}

      <div className="tabs">
        {SUBTABS.map((t, i) => (
          <button key={i} className={`tab-btn ${tab === i ? 'active' : ''}`} onClick={() => setTab(i)}>{t}</button>
        ))}
      </div>

      {tab === 0 && <CharactersTab chars={chars} reload={reload} />}

      {tab !== 0 && !dataReady && (
        <div className="empty-state">Link a character first (Characters tab).</div>
      )}
      {tab !== 0 && dataReady && (
        <>
          <CharacterSelect chars={chars} value={selected} onChange={setSelected} />
          {tab === 1 && <WalletTab    charId={selected} />}
          {tab === 2 && <SkillsTab    charId={selected} />}
          {tab === 3 && <AssetsTab    charId={selected} />}
          {tab === 4 && <ContractsTab charId={selected} />}
          {tab === 5 && <IndustryTab  charId={selected} />}
        </>
      )}
    </div>
  )
}
