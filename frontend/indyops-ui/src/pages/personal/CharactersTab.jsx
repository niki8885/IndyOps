import { useState } from 'react'
import { get, patch, post, del } from '../../api/client'
import { fmtIsk, fmtNum, fmtDate } from './common'

export default function CharactersTab({ chars, reload, onOpen }) {
  const [busy, setBusy]   = useState(false)
  const [error, setError] = useState('')

  async function addCharacter() {
    setBusy(true); setError('')
    try {
      const { url } = await get('/characters/sso/login')
      window.location.href = url   // hand off to EVE SSO
    } catch (e) { setError(e.message); setBusy(false) }
  }

  async function toggle(c) {
    try { await patch(`/characters/${c.id}`, { is_active: !c.is_active }); reload() }
    catch (e) { setError(e.message) }
  }
  async function sync(c) {
    try { await post(`/characters/${c.id}/sync`, {}); setTimeout(reload, 4000) }
    catch (e) { setError(e.message) }
  }
  async function unlink(c) {
    if (!confirm(`Unlink “${c.character_name}” and delete its synced data?`)) return
    try { await del(`/characters/${c.id}`); reload() }
    catch (e) { setError(e.message) }
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <span style={{ color: 'var(--text)', fontSize: 13 }}>
          {chars.length} linked character{chars.length === 1 ? '' : 's'}
        </span>
        <button className="btn btn-primary" onClick={addCharacter} disabled={busy}>
          {busy ? 'Redirecting…' : '+ Add EVE character'}
        </button>
      </div>

      {error && <div className="error-box" style={{ marginBottom: 16 }}>{error}</div>}

      {chars.length === 0 && (
        <div className="empty-state">
          No characters yet. Click “Add EVE character” to log in with EVE SSO.
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(330px, 1fr))', gap: 16 }}>
        {chars.map(c => (
          <CharacterCard
            key={c.id} c={c}
            onToggle={() => toggle(c)} onSync={() => sync(c)} onUnlink={() => unlink(c)}
            onOpen={() => onOpen?.(c.id)}
          />
        ))}
      </div>
    </div>
  )
}

function CharacterCard({ c, onToggle, onSync, onUnlink, onOpen }) {
  const expired = c.status === 'token_expired'
  return (
    <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div onClick={onOpen} role="button" tabIndex={0}
        onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onOpen(e) } }}
        style={{ display: 'flex', gap: 14, cursor: 'pointer' }} title="Open character page">
        <img
          src={c.portrait} alt={c.character_name} width={72} height={72}
          style={{ borderRadius: 8, border: '1px solid var(--border)', flexShrink: 0 }}
        />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            {c.favorite && <span title="Favorite" style={{ color: 'var(--accent)', fontSize: 14 }}>⭐</span>}
            <span style={{ color: 'var(--text-white)', fontWeight: 600, fontSize: 15 }}>{c.character_name}</span>
            <span style={{ color: 'var(--accent)', fontSize: 13 }}>›</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--text)', marginTop: 2 }}>
            {c.corporation_logo && <img src={c.corporation_logo} alt="" width={16} height={16} style={{ borderRadius: 3 }} />}
            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{c.corporation_name || `ID ${c.character_id}`}</span>
          </div>
          <div style={{ marginTop: 6, display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' }}>
            <span className={`badge ${c.is_active ? 'badge-ok' : 'badge-warn'}`}>{c.is_active ? 'Active' : 'Paused'}</span>
            {c.online != null && <span className={`badge ${c.online ? 'badge-ok' : 'badge-warn'}`}>{c.online ? 'Online' : 'Offline'}</span>}
            {expired && <span className="badge badge-bad">Token expired</span>}
            {c.group_name && <span className="badge badge-warn">{c.group_name}</span>}
            {c.is_manufacturer && <span title="Manufacturing char" style={{ fontSize: 13 }}>🏭</span>}
            {c.is_trader && <span title="Trading char" style={{ fontSize: 13 }}>💱</span>}
          </div>
        </div>
      </div>

      <div style={{ fontSize: 12, color: 'var(--text-bright)', display: 'grid', gridTemplateColumns: '1fr auto', rowGap: 4 }}>
        <span>Wallet</span><span style={{ textAlign: 'right' }}>{fmtIsk(c.wallet_balance)}</span>
        <span>Skill points</span><span style={{ textAlign: 'right' }}>{fmtNum(c.total_sp)}</span>
        <span>Last sync</span><span style={{ textAlign: 'right' }}>{fmtDate(c.last_sync_at)}</span>
      </div>

      <div style={{ fontSize: 11, color: 'var(--text)' }}>{c.scopes.length} scope(s) granted</div>
      {expired && <div className="warning-box" style={{ fontSize: 12 }}>Re-link this character to refresh access.</div>}

      <div style={{ display: 'flex', gap: 8, marginTop: 'auto' }}>
        <button className="btn btn-ghost btn-sm" onClick={onSync}>Sync now</button>
        <button className="btn btn-ghost btn-sm" onClick={onToggle}>{c.is_active ? 'Pause' : 'Activate'}</button>
        <button className="btn btn-danger btn-sm" style={{ marginLeft: 'auto' }} onClick={onUnlink}>Unlink</button>
      </div>
    </div>
  )
}
