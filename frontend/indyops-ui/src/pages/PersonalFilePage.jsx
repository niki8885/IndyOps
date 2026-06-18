import { useState, useEffect, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import { get } from '../api/client'
import CharactersTab from './personal/CharactersTab'
import CharacterDetail from './personal/CharacterDetail'

function ssoError(code) {
  switch (code) {
    case 'bad_state':      return 'Login session expired — please try linking again.'
    case 'owned_by_other': return 'That character is already linked to another account.'
    case 'sso_failed':     return 'EVE SSO failed. Please try again.'
    default:               return 'Something went wrong during EVE login.'
  }
}

export default function PersonalFilePage() {
  const [chars, setChars]   = useState([])
  const [openId, setOpenId] = useState(null)   // selected character → detail view
  const [banner, setBanner] = useState(null)
  const [params, setParams] = useSearchParams()

  const reload = useCallback(async () => {
    try { setChars(await get('/characters')) } catch { /* not logged in / no chars */ }
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

  const openChar = openId != null ? chars.find(c => c.id === openId) : null

  if (openChar) {
    return <CharacterDetail char={openChar} onBack={() => { setOpenId(null); reload() }} />
  }

  return (
    <div>
      <h2 style={{ marginBottom: 6 }}>Personal File</h2>
      <p style={{ color: 'var(--text)', marginTop: 0, marginBottom: 18, fontSize: 13 }}>
        Link your EVE characters via EVE SSO and pull wallet, skills, assets, contracts and
        industry jobs straight from ESI. Click a character to open its page.
      </p>

      {banner && (
        <div className={banner.ok ? 'warning-box' : 'error-box'} style={{ marginBottom: 16 }}>
          {banner.msg}
        </div>
      )}

      <CharactersTab chars={chars} reload={reload} onOpen={setOpenId} />
    </div>
  )
}
