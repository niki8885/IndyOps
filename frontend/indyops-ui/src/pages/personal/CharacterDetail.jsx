import { useState } from 'react'
import { useApi, fmtIsk, fmtNum, fmtDate } from './common'
import WalletTab from './WalletTab'
import SkillsTab from './SkillsTab'
import AssetsTab from './AssetsTab'
import ContractsTab from './ContractsTab'
import IndustryTab from './IndustryTab'
import JournalTab from './JournalTab'
import StandingsTab from './StandingsTab'
import StatisticsTab from './StatisticsTab'
import SettingsTab from './SettingsTab'

const SUBTABS = ['Wallet', 'Skills', 'Assets', 'Contracts', 'Industry', 'Journal', 'Standing', 'Statistics', 'Settings']

const typeIcon = (id, size = 32) => `https://images.evetech.net/types/${id}/icon?size=${size}`

export default function CharacterDetail({ char, onBack }) {
  const [tab, setTab] = useState('Wallet')
  const charId = char.id

  return (
    <div>
      <button className="btn btn-ghost btn-sm" onClick={onBack} style={{ marginBottom: 14 }}>
        ← Back to characters
      </button>

      <Overview charId={charId} fallback={char} />

      <div className="tabs" style={{ marginTop: 18, marginBottom: 18 }}>
        {SUBTABS.map(t => (
          <button key={t} className={`tab-btn ${tab === t ? 'active' : ''}`} onClick={() => setTab(t)}>{t}</button>
        ))}
      </div>

      {tab === 'Wallet'     && <WalletTab     charId={charId} />}
      {tab === 'Skills'     && <SkillsTab     charId={charId} />}
      {tab === 'Assets'     && <AssetsTab     charId={charId} />}
      {tab === 'Contracts'  && <ContractsTab  charId={charId} />}
      {tab === 'Industry'   && <IndustryTab   charId={charId} />}
      {tab === 'Journal'    && <JournalTab    charId={charId} />}
      {tab === 'Standing'   && <StandingsTab  charId={charId} />}
      {tab === 'Statistics' && <StatisticsTab charId={charId} />}
      {tab === 'Settings'   && <SettingsTab    charId={charId} />}
    </div>
  )
}

function Overview({ charId, fallback }) {
  const { data } = useApi(`/characters/${charId}/overview`, [charId])
  const o = data || {}
  const loc = o.location || {}
  const ship = o.ship || {}
  const wealth = o.wealth || {}

  return (
    <div className="card" style={{ display: 'flex', gap: 20, flexWrap: 'wrap', alignItems: 'flex-start' }}>
      <img src={o.portrait || fallback.portrait} alt={fallback.character_name} width={104} height={104}
        style={{ borderRadius: 10, border: '1px solid var(--border)', flexShrink: 0 }} />

      {/* identity + status */}
      <div style={{ flex: '1 1 240px', minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ color: 'var(--text-white)', fontWeight: 600, fontSize: 18 }}>
            {o.character_name || fallback.character_name}
          </span>
          {o.online != null && (
            <span className={`badge ${o.online ? 'badge-ok' : 'badge-warn'}`}>{o.online ? 'Online' : 'Offline'}</span>
          )}
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8 }}>
          {o.corporation_logo && <img src={o.corporation_logo} alt="" width={24} height={24} style={{ borderRadius: 4 }} />}
          <span style={{ fontSize: 13, color: 'var(--text-bright)' }}>{o.corporation_name || '—'}</span>
        </div>
        {o.alliance_id && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 6 }}>
            {o.alliance_logo && <img src={o.alliance_logo} alt="" width={24} height={24} style={{ borderRadius: 4 }} />}
            <span style={{ fontSize: 13, color: 'var(--text)' }}>{o.alliance_name || '—'}</span>
          </div>
        )}

        <div style={{ fontSize: 12, color: 'var(--text)', marginTop: 10, lineHeight: 1.8 }}>
          <div>📍 {loc.location_name || loc.system_name || '—'}{loc.system_name && loc.location_name ? ` · ${loc.system_name}` : ''}</div>
          <div>🚀 {ship.ship_type_name || '—'}{ship.ship_name ? ` · “${ship.ship_name}”` : ''}</div>
          <div>🧠 {fmtNum(o.total_sp)} SP · last sync {fmtDate(o.last_sync_at)}</div>
        </div>

        {o.missing_scopes?.length > 0 && (
          <div className="warning-box" style={{ marginTop: 10, fontSize: 11 }}>
            Re-link this character to enable live location &amp; implants.
          </div>
        )}
      </div>

      {/* wealth */}
      <div style={{ flex: '1 1 240px', minWidth: 220 }}>
        <div style={{ fontSize: 11, color: 'var(--accent)', fontWeight: 700, letterSpacing: 1 }}>WEALTH</div>
        <div style={{ fontSize: 22, fontWeight: 700, color: 'var(--text-white)', margin: '4px 0' }}>
          {fmtIsk(wealth.total)}
        </div>
        <WealthPlot charId={charId} />
        <div style={{ display: 'grid', gridTemplateColumns: '1fr auto', rowGap: 3, fontSize: 12, color: 'var(--text-bright)', marginTop: 8 }}>
          <span>Liquid (wallet)</span><span style={{ textAlign: 'right' }}>{fmtIsk(wealth.liquid)}</span>
          <span>Assets (ESI avg)</span><span style={{ textAlign: 'right' }}>{fmtIsk(wealth.assets_value)}</span>
        </div>
      </div>

      {/* implants */}
      <div style={{ flex: '1 1 200px', minWidth: 180 }}>
        <div style={{ fontSize: 11, color: 'var(--accent)', fontWeight: 700, letterSpacing: 1, marginBottom: 6 }}>
          ACTIVE IMPLANTS
        </div>
        {!o.implants ? (
          <div style={{ fontSize: 12, color: 'var(--text)' }}>—</div>
        ) : o.implants.length === 0 ? (
          <div style={{ fontSize: 12, color: 'var(--text)' }}>No implants.</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {o.implants.map(im => (
              <div key={im.type_id} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <img src={typeIcon(im.type_id)} alt="" width={24} height={24} style={{ borderRadius: 3 }} />
                <span style={{ fontSize: 12, color: 'var(--text-white)' }}>{im.name || im.type_id}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function WealthPlot({ charId }) {
  const { data } = useApi(`/characters/${charId}/wealth-history`, [charId])
  const totals = (data || []).map(d => d.total).filter(v => v != null)
  return <Sparkline points={totals} />
}

function Sparkline({ points, width = 220, height = 44, color = '#c8a951' }) {
  if (!points || points.length < 2) {
    return <div style={{ fontSize: 11, color: 'var(--text)', height }}>Building history — one point per sync.</div>
  }
  const min = Math.min(...points), max = Math.max(...points)
  const range = max - min || 1
  const d = points.map((p, i) => {
    const x = (i / (points.length - 1)) * width
    const y = height - ((p - min) / range) * (height - 4) - 2
    return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
  return (
    <svg width="100%" height={height} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
      <path d={d} fill="none" stroke={color} strokeWidth="1.5" />
    </svg>
  )
}
